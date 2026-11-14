import argparse
import logging
import sys
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Callable

from busbidder.booking import Booking, BookingManager, is_valid_reference
from busbidder.constraints import FilterResult, OfferFilter, format_duration
from busbidder.criteria import CRITERIA, DEPARTURE_WINDOWS
from busbidder.exceptions import BusBidderError, ConfigError
from busbidder.explain import DISCLAIMER, Explainer, Explanation, plural
from busbidder.logging_setup import close_logging, setup_logging
from busbidder.models import Destination
from busbidder.profiles import (
    Limits,
    TravellerProfile,
    TravelRequest,
    find_destination,
    get_profile,
    load_profiles,
)
from busbidder.ranking import RankedOffer, Ranker
from busbidder.validation import load_destinations, load_offers, write_quarantine

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEIGHTS = {"price": 35, "duration": 25, "departure": 15, "flexibility": 15, "emissions": 10}


@dataclass(frozen=True)
class Paths:
    offers: Path = PROJECT_ROOT / "data" / "offers.csv"
    companies: Path = PROJECT_ROOT / "data" / "companies.csv"
    destinations: Path = PROJECT_ROOT / "data" / "destinations.csv"
    profiles: Path = PROJECT_ROOT / "config" / "profiles.json"
    bookings: Path = PROJECT_ROOT / "bookings" / "bookings.json"
    log: Path = PROJECT_ROOT / "logs" / "busbidder.log"
    quarantine: Path = PROJECT_ROOT / "logs" / "quarantine.csv"


@dataclass
class SearchResult:
    request: TravelRequest
    filtered: FilterResult
    ranked: list[RankedOffer]
    explanations: list[Explanation]



class BusBidderApp:

    def __init__(self, paths: Paths = Paths(), use_bookings: bool = True) -> None:
        self.paths = paths
        self.report = load_offers(paths.offers, paths.companies, paths.destinations)
        write_quarantine(self.report.quarantined, paths.quarantine)
        self.offers = self.report.offers
        self.destinations: dict[str, Destination] = load_destinations(paths.destinations)
        self.profiles: dict[str, TravellerProfile] = load_profiles(paths.profiles)
        self.bookings = BookingManager(paths.bookings)
        if use_bookings:
            self.bookings.apply_to_offers(self.offers)

    def search(self, request: TravelRequest) -> SearchResult:
        filtered = OfferFilter().apply(self.offers, request)
        ranked = Ranker().rank(filtered.kept, request)
        explanations = Explainer(ranked, request).explain_all()
        return SearchResult(request, filtered, ranked, explanations)




def describe_weights(profile: TravellerProfile) -> str:
    parts = []
    for name, weight in profile.weights.items():
        if weight == 0:
            continue
        extra = f" ({profile.departure_window})" if name == "departure" else ""
        parts.append(f"{name} {weight:g}%{extra}")
    return ", ".join(parts)


def describe_limits(limits: Limits) -> str:
    parts = []
    if limits.max_price_eur is not None:
        parts.append(f"price at most EUR {limits.max_price_eur:.2f}")
    if limits.max_transfers is not None:
        parts.append(f"at most {plural(limits.max_transfers, 'transfer')}")
    if limits.max_duration_minutes is not None:
        parts.append(f"journey at most {format_duration(limits.max_duration_minutes)}")
    if limits.changeable_required:
        parts.append("changeable ticket required")
    if limits.refundable_required:
        parts.append("refundable ticket required")
    return ", ".join(parts) if parts else "none"


def render_search(result: SearchResult, top: int | None = None) -> str:
    request, filtered = result.request, result.filtered
    profile = request.profile
    lines = [
        f"Request:  Madrid -> {request.destination.name}, "
        f"{request.earliest_date:%d %b %Y} to {request.latest_date:%d %b %Y}",
        f"Profile:  {profile.name} ({profile.key})",
        "",
        "Hard constraints - offers that fail these are NOT ranked:",
        *[f"  - {text}" for text in filtered.active],
        "Preferences - used only to rank the remaining offers:",
        f"  {describe_weights(profile)}",
        "",
        f"Result:   {filtered.summary()}",
    ]

    if not result.ranked:
        lines.append("")
        if filtered.matching == 0:
            lines.append(f"No offers to {request.destination.name} depart in that period.")
        elif filtered.removed:
            name, count = filtered.most_restrictive()
            lines.append("No offers meet all your requirements.")
            lines.append(f"The limit that removed most offers is '{name}' ({count} offers). "
                         f"Relaxing it would give you more choice.")
        else:
            lines.append("All matching offers are sold out.")
    else:
        lines += ["", DISCLAIMER, ""]
        shown = list(zip(result.ranked, result.explanations))[:top]
        for item, explanation in shown:
            lines.append(explanation.headline)
            scores = "  ".join(
                f"{s.name} {s.score:.0f}{'*' if s.estimated else ''}"
                for s in item.scores.values() if s.weight > 0)
            lines.append(f"    Scores: {scores}")
            lines += [f"    + {text}" for text in explanation.strengths]
            lines += [f"    - {text}" for text in explanation.weaknesses]
            lines.append(f"    = {explanation.comparison}")
            lines += [f"    ! {text}" for text in explanation.notes]
            lines.append("")
        if top is not None and len(result.ranked) > top:
            lines.append(f"({len(result.ranked) - top} more offers not shown)")
        if any(s.estimated and s.weight > 0 for item, _ in shown for s in item.scores.values()):
            lines.append("* estimated score (value not reported)")

    if filtered.removed:
        if lines[-1] != "":
            lines.append("")
        lines.append("Removed by your limits:")
        lines += [f"  {r.offer.offer_id}  {r.offer.company.name:<15} {r.reason}" for r in filtered.removed]
    return "\n".join(lines).rstrip() + "\n"


def render_booking(booking: Booking) -> str:
    fare = booking.fare
    conditions = ", ".join([
        "changeable" if fare.changeable else "not changeable",
        "refundable" if fare.refundable else "not refundable",
        f"{plural(fare.luggage_bags, 'checked bag')}",
    ])
    return "\n".join([
        f"Booking reference: {booking.reference}",
        f"  Traveller:   {booking.traveller_name}",
        f"  Journey:     Madrid -> {booking.destination_name} with {booking.company_name} ({booking.offer_id})",
        f"  Departure:   {booking.departure:%a %d %b %Y %H:%M}",
        f"  Arrival:     {booking.arrival:%a %d %b %Y %H:%M}",
        f"  Price:       EUR {booking.price_eur:.2f}",
        f"  Conditions:  {conditions}",
        f"  Booked at:   {booking.booked_at:%Y-%m-%d %H:%M:%S}",
        f"  Payment:     {booking.payment_status}",
    ]) + "\n"








class InteractiveMenu:
    def __init__(self, app: BusBidderApp, read: Callable[[str], str] = input,
                 write: Callable[[str], None] = print) -> None:
        self.app = app
        self.read = read
        self.write = write

    def ask(self, prompt: str, convert: Callable[[str], object], default: str | None = None):
        while True:
            answer = self.read(prompt).strip()
            if not answer and default is not None:
                answer = default
            try:
                return convert(answer)
            except (ValueError, BusBidderError) as error:
                self.write(f"  {error}")

    def run(self) -> int:
        report = self.app.report
        self.write("BusBidder Spain - bus offers from Madrid")
        self.write(f"Data: {report.summary()} (details in {self.app.paths.log.name})")
        actions = {"1": self.search, "2": self.view_booking, "3": self.list_profiles}
        while True:
            self.write("\n1) Search and rank offers\n2) View a booking\n3) List traveller profiles\nq) Quit")
            choice = self.read("Choose: ").strip().lower()
            if choice in ("q", "quit"):
                self.write("Goodbye.")
                return 0
            action = actions.get(choice)
            if action is None:
                self.write("  Please choose 1, 2, 3 or q.")
                continue
            action()


    def search(self) -> None:
        names = ", ".join(sorted(d.name for d in self.app.destinations.values()))
        self.write(f"\nDestinations: {names}")
        destination = self.ask("Destination: ", lambda text: find_destination(self.app.destinations, text))
        earliest = self.ask("Earliest departure date (YYYY-MM-DD): ", parse_date)
        latest = self.ask("Latest departure date (Enter = same day): ", parse_date,
                          default=earliest.isoformat())
        profile = self.choose_profile()
        try:
            request = TravelRequest(profile, destination, earliest, latest)
        except ConfigError as error:
            self.write(f"  {error}")
            return

        result = self.app.search(request)
        self.write("")
        self.write(render_search(result))
        if result.ranked:
            self.offer_booking(result)

    def choose_profile(self) -> TravellerProfile:
        profiles = list(self.app.profiles.values())
        self.write("\nTraveller profiles:")
        for number, profile in enumerate(profiles, start=1):
            self.write(f"  {number}) {profile.name} - {profile.description}")
        self.write("  c) Custom: set your own preferences")

        def convert(answer: str) -> TravellerProfile | None:
            if answer.lower() == "c":
                return None
            if answer.isdigit() and 1 <= int(answer) <= len(profiles):
                return profiles[int(answer) - 1]
            return get_profile(self.app.profiles, answer)

        chosen = self.ask("Profile: ", convert)
        return chosen if chosen is not None else self.custom_profile()

    def custom_profile(self) -> TravellerProfile:
        self.write("\nCustom profile. Press Enter to accept the value in brackets.")
        window = self.ask(f"Preferred departure window ({'/'.join(DEPARTURE_WINDOWS)}) [morning]: ",
                          parse_window, default="morning")
        while True:
            self.write("Weights in percent; they must total 100.")
            weights = {name: self.ask(f"  {name} [{DEFAULT_WEIGHTS.get(name, 0)}]: ", float,
                                      default=str(DEFAULT_WEIGHTS.get(name, 0)))
                       for name in CRITERIA}
            self.write("Hard limits (offers that break them are removed). Enter = no limit.")
            limits = Limits(
                max_price_eur=self.ask("  Maximum price in EUR: ", optional(float), default=""),
                max_transfers=self.ask("  Maximum transfers: ", optional(int), default=""),
                max_duration_minutes=self.ask("  Maximum journey time in hours: ",
                                              optional(lambda t: round(float(t) * 60)), default=""),
                changeable_required=self.ask("  Changeable ticket required? (y/n) [n]: ", parse_yes_no,
                                             default="n"),
                refundable_required=self.ask("  Refundable ticket required? (y/n) [n]: ", parse_yes_no,
                                             default="n"),
            )
            try:
                return TravellerProfile(key="custom", name="Custom profile", departure_window=window,
                                        weights=weights, limits=limits)
            except BusBidderError as error:
                self.write(f"  {error}. Please try again.")


    def offer_booking(self, result: SearchResult) -> None:
        def convert(answer: str) -> RankedOffer | None:
            if answer == "":
                return None
            if answer.isdigit() and 1 <= int(answer) <= len(result.ranked):
                return result.ranked[int(answer) - 1]
            raise ValueError(f"Enter a rank between 1 and {len(result.ranked)}, or press Enter")

        chosen = self.ask("Enter a rank number to book that offer, or press Enter to go back: ",
                          convert, default="")
        if chosen is None:
            return
        offer = chosen.offer
        while True:
            name = self.read("Traveller's full name (Enter = cancel): ")
            if not name.strip():
                self.write("  Booking cancelled.")
                return
            try:
                booking = self.app.bookings.book(offer, name)
                break
            except BusBidderError as error:
                self.write(f"  {error}")
                if offer.is_sold_out:
                    return
        self.write("\nBooking confirmed (simulated - no payment taken).")
        self.write(render_booking(booking))

    def view_booking(self) -> None:
        def convert(text: str) -> str:
            if not is_valid_reference(text):
                raise ValueError("A booking reference looks like BB-SOL-7K3Q9X")
            return text

        reference = self.ask("Booking reference: ", convert)
        booking = self.app.bookings.find(reference)
        self.write(render_booking(booking) if booking else "  No booking with that reference.")

    def list_profiles(self) -> None:
        for profile in self.app.profiles.values():
            self.write(f"\n{profile.name} ({profile.key}): {profile.description}")
            self.write(f"  Preferences: {describe_weights(profile)}")
            self.write(f"  Hard limits: {describe_limits(profile.limits)}")



def parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise ValueError(f"{text!r} is not a date in the format YYYY-MM-DD") from None


def parse_window(text: str) -> str:
    window = text.strip().lower()
    if window not in DEPARTURE_WINDOWS:
        raise ValueError(f"Choose one of: {', '.join(DEPARTURE_WINDOWS)}")
    return window


def parse_yes_no(text: str) -> bool:
    answer = text.strip().lower()
    if answer in ("y", "yes"):
        return True
    if answer in ("n", "no"):
        return False
    raise ValueError("Please answer y or n")


def optional(convert: Callable[[str], object]) -> Callable[[str], object]:
    def wrapper(text: str):
        return None if text.strip() == "" else convert(text)
    return wrapper


def argument_date(text: str) -> date:
    try:
        return parse_date(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def positive_int(text: str) -> int:
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError(f"{text!r} must be a whole number of at least 1")
    return int(text)


def parse_weights(text: str) -> dict[str, float]:
    weights = {}
    for part in text.split(","):
        name, separator, value = part.partition("=")
        if not separator:
            raise argparse.ArgumentTypeError(f"{part!r} must look like name=number")
        try:
            weights[name.strip().lower()] = float(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{value!r} is not a number") from None
    return weights



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="busbidder",
        description="Filter, rank and explain bus offers from Madrid. "
                    "Run without arguments for the interactive menu.")
    parser.add_argument("--profile", help="traveller profile key, e.g. budget, business, flexible, eco")
    parser.add_argument("--destination", help="destination name or code, e.g. Malaga or MAL")
    parser.add_argument("--from", dest="earliest", type=argument_date, metavar="YYYY-MM-DD",
                        help="earliest departure date")
    parser.add_argument("--to", dest="latest", type=argument_date, metavar="YYYY-MM-DD",
                        help="latest departure date (default: same as --from)")
    parser.add_argument("--weights", type=parse_weights, metavar="NAME=N,...",
                        help="replace the profile's weights, e.g. price=50,duration=50 (must total 100)")
    parser.add_argument("--top", type=positive_int, metavar="N", help="show only the first N offers")
    parser.add_argument("--output", type=Path, metavar="FILE", help="also save the result to FILE")
    parser.add_argument("--ignore-bookings", action="store_true",
                        help="use the seat counts in offers.csv, ignoring stored bookings "
                             "(for reproducible results)")
    return parser


def run_once(app: BusBidderApp, args: argparse.Namespace, write: Callable[[str], None] = print) -> int:
    missing = [flag for flag, value in (("--profile", args.profile), ("--destination", args.destination),
                                        ("--from", args.earliest)) if value is None]
    if missing:
        raise ConfigError(f"Missing {', '.join(missing)} (or run without arguments for the menu)")

    profile = get_profile(app.profiles, args.profile)
    if args.weights is not None:
        profile = replace(profile, key=f"{profile.key}+weights",
                          name=f"{profile.name} (custom weights)", weights=args.weights)
    request = TravelRequest(profile, find_destination(app.destinations, args.destination),
                            args.earliest, args.latest or args.earliest)

    text = render_search(app.search(request), top=args.top)
    write(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        write(f"Saved to {args.output}")
    return 0


def main(argv: list[str] | None = None, paths: Paths = Paths()) -> int:
    args = build_parser().parse_args(argv)
    argument_mode = any(value is not None for value in
                        (args.profile, args.destination, args.earliest, args.weights))
    setup_logging(paths.log)
    logger.info("Started in %s mode", "argument" if argument_mode else "interactive")
    try:
        app = BusBidderApp(paths, use_bookings=not args.ignore_bookings)
        if argument_mode:
            return run_once(app, args)
        return InteractiveMenu(app).run()
    except BusBidderError as error:
        logger.error("Stopped: %s", error)
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nGoodbye.")
        return 0
    finally:
        close_logging()