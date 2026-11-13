from dataclasses import dataclass, field

from busbidder.constraints import format_duration
from busbidder.criteria import DEPARTURE_WINDOWS, minutes_outside_window
from busbidder.models import Offer
from busbidder.profiles import TravelRequest
from busbidder.ranking import RankedOffer

STRENGTH_SCORE = 80
WEAKNESS_SCORE = 60
MAX_ITEMS = 3
FEW_SEATS = 5 

DISCLAIMER = ("Rankings reflect the preferences and weights you chose. "
              "The top offer is the best match for those preferences, not an objectively best offer.")

LABELS = {
    "price": "price",
    "duration": "journey time",
    "departure": "departure time",
    "flexibility": "ticket flexibility",
    "emissions": "emissions",
}


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


@dataclass
class Explanation:
    rank: int
    offer_id: str
    headline: str
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    comparison: str = ""
    notes: list[str] = field(default_factory=list)


class Explainer:

    def __init__(self, ranked: list[RankedOffer], request: TravelRequest) -> None:
        self.ranked = ranked
        self.request = request
        offers = [item.offer for item in ranked]
        self.cheapest = min((o.price_eur for o in offers), default=None)
        self.fastest = min((o.duration_minutes for o in offers), default=None)
        reported = [o.co2_kg for o in offers if o.co2_kg is not None]
        self.cleanest = min(reported, default=None)

    def explain_all(self) -> list[Explanation]:
        return [self.explain(item) for item in self.ranked]

    def explain(self, item: RankedOffer) -> Explanation:

        considered = [s for s in item.scores.values() if s.weight > 0 and not s.estimated]

        strengths = sorted((s for s in considered if s.score >= STRENGTH_SCORE),
                           key=lambda s: s.points, reverse=True)
        weaknesses = sorted((s for s in considered if s.score < WEAKNESS_SCORE),
                            key=lambda s: s.points_lost, reverse=True)

        explanation = Explanation(
            rank=item.rank,
            offer_id=item.offer_id,
            headline=self.headline(item),
            strengths=[self.describe(s.name, item.offer) for s in strengths[:MAX_ITEMS]],
            weaknesses=[self.describe(s.name, item.offer) for s in weaknesses[:MAX_ITEMS]],
            comparison=self.compare_with_top(item),
            notes=self.notes(item),
        )
        if not explanation.strengths and not explanation.weaknesses:
            explanation.notes.insert(0, "No clear strengths or weaknesses: an all-round middle option.")
        return explanation


    def headline(self, item: RankedOffer) -> str:
        o = item.offer
        return (f"#{item.rank} {o.offer_id}  {o.company.name}  "
                f"{o.departure:%a %d %b %H:%M} -> {o.arrival:%H:%M}"
                f"{' (+1 day)' if o.arrival.date() > o.departure.date() else ''}  "
                f"EUR {o.price_eur:.2f}  score {item.total:.1f}/100")

    def describe(self, name: str, offer: Offer) -> str:
        if name == "price":
            if offer.price_eur == self.cheapest:
                return f"Cheapest offer (EUR {offer.price_eur:.2f})"
            return f"Price EUR {offer.price_eur:.2f} (cheapest: EUR {self.cheapest:.2f})"

        if name == "duration":
            if offer.duration_minutes == self.fastest:
                return f"Fastest journey ({format_duration(offer.duration_minutes)})"
            return (f"Journey {format_duration(offer.duration_minutes)} "
                    f"(fastest: {format_duration(self.fastest)})")

        if name == "departure":
            window = self.request.profile.departure_window
            start, end = DEPARTURE_WINDOWS[window]
            away = minutes_outside_window(offer.departure, window)
            window_text = f"your {window} window ({start // 60:02d}:00-{end // 60:02d}:00)"
            if away == 0:
                return f"Departs {offer.departure:%H:%M}, inside {window_text}"
            return f"Departs {offer.departure:%H:%M}, {format_duration(away)} outside {window_text}"

        if name == "flexibility":
            fare = offer.fare
            if fare.changeable and fare.refundable:
                return "Ticket can be changed and refunded"
            if fare.changeable:
                return "Ticket can be changed but not refunded"
            if fare.refundable:
                return "Ticket can be refunded but not changed"
            return "Ticket can be neither changed nor refunded"

        if name == "emissions":
            if offer.co2_kg == self.cleanest:
                return f"Lowest emissions ({offer.co2_kg:.1f} kg CO2)"
            return f"Emissions {offer.co2_kg:.1f} kg CO2 (lowest: {self.cleanest:.1f} kg)"

        return f"{LABELS.get(name, name).capitalize()}"

    def compare_with_top(self, item: RankedOffer) -> str:
        if item.rank == 1:
            if len(self.ranked) == 1:
                return "The only offer that meets your requirements."
            gap = item.total - self.ranked[1].total
            return (f"Best match for your preferences, {gap:.1f} points ahead of "
                    f"#{self.ranked[1].rank} {self.ranked[1].offer_id}.")

        top = self.ranked[0]
        gap = top.total - item.total
        differences = {name: top.scores[name].points - score.points
                       for name, score in item.scores.items() if score.weight > 0}
        main = max(differences, key=differences.get)
        if differences[main] <= 0:
            return f"{gap:.1f} points behind #1 {top.offer_id}."
        return (f"{gap:.1f} points behind #1 {top.offer_id}, mainly because of "
                f"{LABELS[main]} ({differences[main]:.1f} points).")

    def notes(self, item: RankedOffer) -> list[str]:
        notes = []
        emissions = item.scores.get("emissions")
        if emissions and emissions.estimated and emissions.weight > 0:
            notes.append("Emissions were not reported for this offer; the median of the other "
                         "offers' emission scores was used, which may favour it.")
        if item.tie_break:
            notes.append(f"Tie: {item.tie_break}.")
        if item.offer.seats_available <= FEW_SEATS:
            notes.append(f"Only {plural(item.offer.seats_available, 'seat')} left.")
        if item.offer.transfers:
            notes.append(f"{plural(item.offer.transfers, 'transfer')} on the way.")
        return notes