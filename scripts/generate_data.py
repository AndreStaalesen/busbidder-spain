"""Generate the BusBidder Spain dataset.

Writes three files to the data/ folder:
    companies.csv     the five companies
    destinations.csv  the fifteen destinations served from Madrid
    offers.csv        225 generated offers + deliberate edge-case records

Run from the repository root:
    python scripts/generate_data.py

fixed random seed means every run produces identical files. This script is a development tool and the application itself
only reads the generated CSV files.
"""

import csv
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

SEED = 4420
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TRAVEL_DATES = [date(2027, 7, 12), date(2027, 7, 13), date(2027, 7, 14)]

# Base model for a direct route, before company adjustments.
PRICE_PER_KM = 0.07
PRICE_FIXED = 5.0
SPEED_KMH = 75
CO2_PER_KM = 0.03
TRANSFER_MINUTES = 30

# (code, name, approximate distance from Madrid in km, coastal)
DESTINATIONS = [
    ("BAR", "Barcelona", 620, True),
    ("VAL", "Valencia", 355, True),
    ("SEV", "Seville", 530, False),
    ("MAL", "Malaga", 530, True),
    ("GRA", "Granada", 420, False),
    ("COR", "Cordoba", 400, False),
    ("BIL", "Bilbao", 400, True),
    ("SAN", "San Sebastian", 450, True),
    ("ZAR", "Zaragoza", 315, False),
    ("ALI", "Alicante", 420, True),
    ("MUR", "Murcia", 400, False),
    ("SAL", "Salamanca", 215, False),
    ("TOL", "Toledo", 72, False),
    ("SDC", "Santiago de Compostela", 600, False),
    ("CAD", "Cadiz", 650, True),
]


@dataclass(frozen=True)
class CompanyProfile:
    """Rules describing how one companys offers differ from the base route."""

    code: str
    name: str
    description: str
    price_factor: float
    duration_factor: float
    first_departure: str
    last_departure: str
    transfer_options: tuple
    p_changeable: float
    p_refundable: float
    rating_mean: float
    co2_factor: float
    p_co2_missing: float
    luggage_options: tuple


COMPANIES = [
    CompanyProfile("SOL", "SolRuta", "Low-cost daytime services",
                   0.75, 1.15, "07:00", "16:00", (0, 1), 0.2, 0.0,
                   3.6, 1.2, 0.6, (0, 1)),
    CompanyProfile("CAM", "Camino Express", "Fast direct connections between major cities",
                   1.25, 0.85, "06:00", "20:00", (0,), 1.0, 0.7,
                   4.3, 1.0, 0.0, (1, 2)),
    CompanyProfile("COS", "CostaLink", "Strong coverage of coastal destinations",
                   1.0, 1.0, "07:00", "18:00", (0,), 1.0, 0.4,
                   4.0, 1.0, 0.0, (1, 2)),
    CompanyProfile("VER", "VerdeBus", "Environment-focused services and modern vehicles",
                   1.1, 1.0, "07:00", "19:00", (0, 0, 1), 1.0, 1.0,
                   4.4, 0.5, 0.0, (1,)),
    CompanyProfile("NOC", "NocheVia", "Overnight and late-evening services",
                   0.85, 1.3, "21:00", "23:45", (0, 1), 1.0, 0.0,
                   3.9, 1.0, 0.25, (1, 2)),
]

OFFER_FIELDS = [
    "offer_id", "company", "destination", "departure", "arrival",
    "price_eur", "transfers", "luggage_bags", "changeable", "refundable",
    "seats_available", "rating", "co2_kg",
]

DATETIME_FORMAT = "%Y-%m-%dT%H:%M"


def to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def random_departure(rng: random.Random, company: CompanyProfile, day: date) -> datetime:
    """Pick a departure time on `day` in 15-minute steps within the companys window."""
    slots = range(to_minutes(company.first_departure), to_minutes(company.last_departure) + 1, 15)
    minute_of_day = rng.choice(list(slots))
    return datetime.combine(day, datetime.min.time()) + timedelta(minutes=minute_of_day)


def generate_offer(rng: random.Random, company: CompanyProfile,
                   destination: tuple, day_number: int, day: date) -> dict:
    code, name, km, coastal = destination

    price_factor = company.price_factor
    duration_factor = company.duration_factor
    transfer_options = company.transfer_options

    # CostaLink is strong on the coast and weak inland.
    if company.code == "COS":
        if coastal:
            price_factor *= 0.9
            duration_factor *= 0.95
        else:
            price_factor *= 1.1
            duration_factor *= 1.2
            transfer_options = (1,) if km < 300 else (1, 2)

    # Short routes are always direct, except CostaLink inland connections.
    elif km < 300:
        transfer_options = (0,)

    transfers = rng.choice(transfer_options)

    base_minutes = km / SPEED_KMH * 60
    minutes = base_minutes * duration_factor * rng.uniform(0.95, 1.05)
    minutes += transfers * TRANSFER_MINUTES
    minutes = max(45, round(minutes / 5) * 5)

    departure = random_departure(rng, company, day)
    arrival = departure + timedelta(minutes=minutes)

    price = (km * PRICE_PER_KM + PRICE_FIXED) * price_factor * rng.uniform(0.9, 1.1)

    if rng.random() < company.p_co2_missing:
        co2 = ""
    else:
        co2 = f"{km * CO2_PER_KM * company.co2_factor * rng.uniform(0.9, 1.1):.1f}"

    rating = min(5.0, max(1.0, rng.gauss(company.rating_mean, 0.25)))
    seats = 0 if rng.random() < 0.04 else rng.randint(1, 50)

    return {
        "offer_id": f"{company.code}-{code}-{day_number:03d}",
        "company": company.code,
        "destination": name,
        "departure": departure.strftime(DATETIME_FORMAT),
        "arrival": arrival.strftime(DATETIME_FORMAT),
        "price_eur": f"{price:.2f}",
        "transfers": transfers,
        "luggage_bags": rng.choice(company.luggage_options),
        "changeable": str(rng.random() < company.p_changeable).lower(),
        "refundable": str(rng.random() < company.p_refundable).lower(),
        "seats_available": seats,
        "rating": f"{rating:.1f}",
        "co2_kg": co2,
    }


def edge_case_records() -> list[tuple[str, dict]]:
    
    template = {
        "company": "SOL", "destination": "Cordoba",
        "departure": "2027-07-13T09:00", "arrival": "2027-07-13T15:00",
        "price_eur": "26.50", "transfers": 0, "luggage_bags": 1,
        "changeable": "false", "refundable": "false",
        "seats_available": 20, "rating": "3.6", "co2_kg": "14.0",
    }

    def record(offer_id: str, **changes) -> dict:
        return {"offer_id": offer_id, **template, **changes}

    return [
        # Reject
        ("missing price", record("SOL-COR-901", price_eur="")),
        ("negative price", record("SOL-COR-902", price_eur="-12.00")),
        ("zero price", record("SOL-COR-903", price_eur="0.00")),
        ("unknown destination", record("SOL-COR-904", destination="Paris")),
        ("unknown company", record("XYZ-COR-905", company="XYZ")),
        ("arrival before departure", record("SOL-COR-906", arrival="2027-07-13T07:00")),
        ("zero duration", record("SOL-COR-907", arrival="2027-07-13T09:00")),
        ("impossible date", record("SOL-COR-908", departure="2027-07-32T09:00")),
        ("badly formatted ID", record("sol-cor-1")),
        ("ID company does not match company", record("CAM-COR-910")),
        ("duplicate ID", record("CAM-BAR-001", destination="Barcelona")),
        ("negative seats", record("SOL-COR-912", seats_available=-3)),
        ("zero emissions", record("SOL-COR-913", co2_kg="0.0")),
        # Correct
        ("destination with spaces and lower case", record("SOL-COR-914", destination=" cordoba ")),
        ("destination with accent", record("SOL-COR-915", destination="Córdoba")),
        ("boolean variants", record("SOL-COR-916", changeable="Y", refundable="yes")),
        # Quarantine
        ("rating outside 1-5", record("SOL-COR-917", rating="7.5")),
        ("price more than 3x destination median", record("SOL-COR-918", price_eur="120.00")),
        # Valid edge cases
        ("emissions not reported", record("SOL-COR-919", co2_kg="")),
        ("sold out", record("SOL-COR-920", seats_available=0)),
    ]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rng = random.Random(SEED)
    DATA_DIR.mkdir(exist_ok=True)

    write_csv(DATA_DIR / "companies.csv", ["code", "name", "description"],
              [{"code": c.code, "name": c.name, "description": c.description} for c in COMPANIES])

    write_csv(DATA_DIR / "destinations.csv", ["code", "name", "distance_km", "coastal"],
              [{"code": code, "name": name, "distance_km": km, "coastal": str(coastal).lower()}
               for code, name, km, coastal in DESTINATIONS])

    offers = []
    for company in COMPANIES:
        for destination in DESTINATIONS:
            for day_number, day in enumerate(TRAVEL_DATES, start=1):
                offers.append(generate_offer(rng, company, destination, day_number, day))

    edge_cases = edge_case_records()
    offers.extend(row for _, row in edge_cases)

    write_csv(DATA_DIR / "offers.csv", OFFER_FIELDS, offers)

    generated = len(offers) - len(edge_cases)
    print(f"Wrote {len(COMPANIES)} companies, {len(DESTINATIONS)} destinations, "
          f"{generated} generated offers + {len(edge_cases)} edge-case records to {DATA_DIR}")


if __name__ == "__main__":
    main()