import csv
import logging
import statistics
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date
from pathlib import Path

from busbidder.cli import BusBidderApp, Paths, render_search
from busbidder.constraints import OfferFilter
from busbidder.criteria import CRITERIA, ScoringContext, create_criterion
from busbidder.profiles import TravelRequest
from busbidder.ranking import Ranker

OUTPUTS = Path(__file__).resolve().parent.parent / "outputs"
MAIN_DESTINATION = "MAL"
EARLIEST, LATEST = date(2027, 7, 12), date(2027, 7, 14)
SHIFT = 10



def write_csv(name: str, header: list[str], rows: list[list]) -> None:
    with (OUTPUTS / name).open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(rows)


def markdown_table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def request_for(app, profile, destination_code=MAIN_DESTINATION):
    return TravelRequest(profile, app.destinations[destination_code], EARLIEST, LATEST)


def rank(app, request, offers=None):
    kept = OfferFilter().apply(offers if offers is not None else app.offers, request).kept
    return Ranker().rank(kept, request)


def shifted_weights(weights: dict[str, float], name: str, delta: float) -> dict[str, float] | None:
    new = weights[name] + delta
    others = {k: v for k, v in weights.items() if k != name}
    rest = sum(others.values())
    if not 0 <= new <= 100 or rest == 0:
        return None
    return {name: new, **{k: v * (100 - new) / rest for k, v in others.items()}}




def e1_profiles(app, report: list[str]) -> None:
    rows = []
    for key, profile in app.profiles.items():
        request = request_for(app, profile)
        result = app.search(request)
        (OUTPUTS / f"e1_{key}_malaga.txt").write_text(render_search(result), encoding="utf-8", newline="\n")
        top = result.ranked[:3]
        rows.append([profile.name, result.filtered.summary().split("; ")[-1].replace(" ranked", ""),
                     *[f"{r.offer_id} ({r.total:.1f})" for r in top],
                     f"{top[0].total - top[1].total:.2f}"])
    header = ["Profile", "Ranked", "#1", "#2", "#3", "Lead of #1"]
    write_csv("e1_profile_comparison.csv", header, rows)
    report += ["## E1 Profile comparison (Madrid -> Malaga, 12-14 Jul 2027)", "",
               "Full outputs: `outputs/e1_<profile>_malaga.txt`", "", markdown_table(header, rows), ""]



def e2_sensitivity(app, report: list[str]) -> None:
    rows, changed = [], 0
    for key, profile in app.profiles.items():
        base = rank(app, request_for(app, profile))[0].offer_id
        for name in CRITERIA:
            for delta in (-SHIFT, +SHIFT):
                weights = shifted_weights(profile.weights, name, delta)
                if weights is None:
                    rows.append([profile.name, name, f"{delta:+d}", base, "not possible", ""])
                    continue
                varied = replace(profile, weights=weights)
                winner = rank(app, request_for(app, varied))[0]
                flipped = winner.offer_id != base
                changed += flipped
                rows.append([profile.name, name, f"{delta:+d}", base, winner.offer_id,
                             "CHANGED" if flipped else ""])
    header = ["Profile", "Weight shifted", "Shift (pp)", "Original #1", "New #1", ""]
    write_csv("e2_sensitivity.csv", header, rows)
    tested = sum(1 for r in rows if r[4] != "not possible")
    report += [f"## E2 Sensitivity: each weight shifted by +-{SHIFT} percentage points",
               "", "Other weights rescaled proportionally so the total stays 100.",
               f"The top offer changed in {changed} of {tested} cases.", "",
               markdown_table(header, [r for r in rows if r[5] or r[4] == "not possible"]
                              or [["(no changes)", "", "", "", "", ""]]),
               "", "Full table: `outputs/e2_sensitivity.csv`", ""]



def e3_missing_emissions(app, report: list[str]) -> None:
    per_km = defaultdict(list)
    for offer in app.offers:
        if offer.co2_kg is not None:
            per_km[offer.company.code].append(offer.co2_kg / offer.destination.distance_km)
    company_rate = {code: statistics.median(values) for code, values in per_km.items()}

    def fill(policy: str):
        if policy == "median score (used)":
            return app.offers
        filled = []
        reported_by_route = defaultdict(list)
        for offer in app.offers:
            if offer.co2_kg is not None:
                reported_by_route[offer.destination.code].append(offer.co2_kg)
        for offer in app.offers:
            if offer.co2_kg is None:
                if policy == "company typical value":
                    value = round(company_rate[offer.company.code] * offer.destination.distance_km, 1)
                else:  # highest reported on the route
                    value = max(reported_by_route[offer.destination.code])
                offer = replace(offer, co2_kg=value)
            filled.append(offer)
        return filled

    missing = sum(o.co2_kg is None for o in app.offers)
    by_company = Counter(o.company.name for o in app.offers if o.co2_kg is None)
    rows = []
    for key in ("budget", "eco"):
        profile = app.profiles[key]
        for policy in ("median score (used)", "company typical value", "highest reported on route"):
            ranked = rank(app, request_for(app, profile), offers=fill(policy))
            sol_positions = [str(r.rank) for r in ranked if r.offer.company.code == "SOL"]
            rows.append([profile.name, policy, f"{ranked[0].offer_id} ({ranked[0].total:.1f})",
                         ", ".join(sol_positions) or "-"])

    malaga = [o for o in app.offers if o.destination.code == MAIN_DESTINATION]
    context = ScoringContext(tuple(malaga), "morning")
    emissions = create_criterion("emissions")
    sol_rows = [[o.offer_id, "not reported" if o.co2_kg is None else f"{o.co2_kg:.1f}",
                 f"{emissions.score(o, context):.1f}"]
                for o in malaga if o.company.code == "SOL"]

    header = ["Profile", "Policy for missing CO2", "#1", "SolRuta ranks"]
    write_csv("e3_missing_emissions.csv", header, rows)
    report += ["## E3 Missing emissions",
               "", f"{missing} loaded offers do not report CO2: " +
               ", ".join(f"{name} {n}" for name, n in by_company.most_common()) + ".",
               "", "Emission scores of SolRuta's Malaga offers (all 15 Malaga offers compared):", "",
               markdown_table(["Offer", "CO2 kg", "Emission score"], sol_rows), "",
               "Ranking under three policies for missing values:", "",
               markdown_table(header, rows), ""]



RAW_VALUES = {
    "price": lambda offer: offer.price_eur,
    "duration": lambda offer: offer.duration_minutes,
    "emissions": lambda offer: offer.co2_kg,
}


def minmax(value: float, low: float, high: float) -> float:
    return 100.0 if high == low else 100 * (high - value) / (high - low)


def minmax_totals(offers, request) -> dict[str, float]:
    context = ScoringContext(tuple(offers), request.profile.departure_window)
    totals = {}
    for offer in offers:
        total = 0.0
        for name, weight in request.profile.weights.items():
            if name in RAW_VALUES:
                reported = [v for v in map(RAW_VALUES[name], offers) if v is not None]
                low, high = min(reported), max(reported)
                own = RAW_VALUES[name](offer)
                score = (minmax(own, low, high) if own is not None
                         else statistics.median(minmax(v, low, high) for v in reported))
            else:
                score = create_criterion(name).score(offer, context)
            total += score * weight / 100
        totals[offer.offer_id] = round(total, 2)
    return totals


def e4_normalisation(app, report: list[str]) -> None:
    rows = []
    for key, profile in app.profiles.items():
        request = request_for(app, profile)
        ranked = rank(app, request)
        ratio_order = [r.offer_id for r in ranked]
        kept = [r.offer for r in ranked]
        mm = minmax_totals(kept, request)
        mm_order = sorted(mm, key=lambda i: (-mm[i], ratio_order.index(i)))
        moved = sum(a != b for a, b in zip(ratio_order, mm_order))
        rows.append([profile.name, ratio_order[0], mm_order[0],
                     "same" if ratio_order[0] == mm_order[0] else "DIFFERENT",
                     f"{moved} of {len(ratio_order)}"])
    header = ["Profile", "#1 ratio (used)", "#1 min-max", "Winner", "Positions that differ"]
    write_csv("e4_normalisation.csv", header, rows)
    report += ["## E4 Ratio-to-best versus min-max normalisation", "",
               markdown_table(header, rows), ""]



def e5_fairness(app, report: list[str]) -> None:
    wins, top3, removed = Counter(), Counter(), Counter()
    no_result = []
    for key, profile in app.profiles.items():
        for code in app.destinations:
            request = request_for(app, profile, code)
            filtered = OfferFilter().apply(app.offers, request)
            ranked = Ranker().rank(filtered.kept, request)
            for item in filtered.removed:
                removed[(key, item.offer.company.name)] += 1
            if not ranked:
                no_result.append(f"{profile.name} -> {app.destinations[code].name}")
                continue
            wins[(key, ranked[0].offer.company.name)] += 1
            for item in ranked[:3]:
                top3[(key, item.offer.company.name)] += 1

    companies = sorted({o.company.name for o in app.offers})
    rows = []
    for company in companies:
        row = [company]
        for key in app.profiles:
            row.append(f"{wins[(key, company)]} / {top3[(key, company)]} / {removed[(key, company)]}")
        row.append(sum(wins[(k, company)] for k in app.profiles))
        rows.append(row)
    header = ["Company", *[p.name for p in app.profiles.values()], "Total wins"]
    write_csv("e5_company_fairness.csv", header, rows)


    evening = replace(app.profiles["budget"], key="budget-evening",
                      name="Budget traveller, evening window", departure_window="evening")
    evening_wins = Counter()
    for code in app.destinations:
        ranked = rank(app, request_for(app, evening, code))
        if ranked:
            evening_wins[ranked[0].offer.company.name] += 1

    report += ["## E5 Company fairness over all 15 destinations (12-14 Jul 2027)", "",
               "Each cell: destinations won / top-3 places / offers removed by the profile's limits.", "",
               markdown_table(header, rows), "",
               f"Searches with no ranked offers ({len(no_result)}): " + (", ".join(no_result) or "none"), "",
               "Control: Budget profile with an evening window instead of morning. Destinations won: " +
               ", ".join(f"{name} {n}" for name, n in evening_wins.most_common()) + ".", ""]



def e6_validation(app, report: list[str]) -> None:
    r = app.report
    rows = ([["Rejected", e.line, e.record_id, e.reason] for e in r.rejected]
            + [["Corrected", "", offer_id, "; ".join(c)] for offer_id, c in r.corrected.items()]
            + [["Quarantined", q.line, q.offer_id, q.reason] for q in r.quarantined])
    header = ["Outcome", "Line", "Record", "Reason"]
    write_csv("e6_validation.csv", header, rows)
    report += ["## E6 Validation of the real dataset", "", f"Summary: {r.summary()}", "",
               markdown_table(header, rows), ""]


def main() -> None:
    logging.disable(logging.CRITICAL)
    OUTPUTS.mkdir(exist_ok=True)
    app = BusBidderApp(replace(Paths(), quarantine=OUTPUTS / "e6_quarantine.csv"), use_bookings=False)

    report = ["# BusBidder Spain - experiment results", "",
              "Generated by `python scripts/run_experiments.py`. Stored bookings are ignored.", ""]
    for experiment in (e1_profiles, e2_sensitivity, e3_missing_emissions, e4_normalisation,
                       e5_fairness, e6_validation):
        experiment(app, report)
        print(f"{experiment.__name__} done")

    (OUTPUTS / "experiments.md").write_text("\n".join(report), encoding="utf-8", newline="\n")
    print(f"Results written to {OUTPUTS}")


if __name__ == "__main__":
    main()