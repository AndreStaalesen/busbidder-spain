import csv
import logging
import math
import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from busbidder.exceptions import (
    DataError,
    InconsistentRecordError,
    InvalidValueError,
    MissingFieldError,
    UnknownReferenceError,
)
from busbidder.loader import RawRecord, read_csv
from busbidder.models import Company, Destination, FareConditions, Offer

logger = logging.getLogger(__name__)

OFFER_COLUMNS = [
    "offer_id", "company", "destination", "departure", "arrival",
    "price_eur", "transfers", "luggage_bags", "changeable", "refundable",
    "seats_available", "rating", "co2_kg",
]
COMPANY_COLUMNS = ["code", "name", "description"]
DESTINATION_COLUMNS = ["code", "name", "distance_km", "coastal"]

OFFER_ID_PATTERN = re.compile(r"^(?P<company>[A-Z]{3})-(?P<destination>[A-Z]{3})-(?P<number>\d{3})$")

DATETIME_FORMAT = "%Y-%m-%dT%H:%M"
TRUE_WORDS = {"true", "yes", "y", "1"}
FALSE_WORDS = {"false", "no", "n", "0"}
RATING_RANGE = (1.0, 5.0)
PRICE_OUTLIER_FACTOR = 3


def normalise_name(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.strip())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return without_accents.casefold()












class FieldReader:
    def __init__(self, record: RawRecord, record_id: str | None = None) -> None:
        self.record = record
        self.record_id = record_id
        self.corrections: list[str] = []

    def _error(self, error_class: type[DataError], message: str) -> DataError:
        return error_class(message, record_id=self.record_id, line=self.record.line)

    def text(self, name: str) -> str:
        raw = self.record.fields.get(name, "")
        value = raw.strip()
        if not value:
            raise self._error(MissingFieldError, f"{name} is missing")
        if value != raw:
            self.corrections.append(f"{name}: removed surrounding spaces from {raw!r}")
        return value

    def optional_text(self, name: str) -> str | None:
        if not self.record.fields.get(name, "").strip():
            return None
        return self.text(name)

    def integer(self, name: str, minimum: int | None = None) -> int:
        value = self.text(name)
        try:
            number = int(value)
        except ValueError:
            raise self._error(InvalidValueError, f"{name} {value!r} is not a whole number") from None
        if minimum is not None and number < minimum:
            raise self._error(InvalidValueError, f"{name} must be at least {minimum}, got {number}")
        return number

    def decimal(self, name: str, must_be_positive: bool = False) -> float:
        value = self.text(name)
        try:
            number = float(value)
        except ValueError:
            raise self._error(InvalidValueError, f"{name} {value!r} is not a number") from None
        if not math.isfinite(number):
            raise self._error(InvalidValueError, f"{name} {value!r} is not a finite number")
        if must_be_positive and number <= 0:
            raise self._error(InvalidValueError, f"{name} must be greater than 0, got {value}")
        return number

    def optional_decimal(self, name: str, must_be_positive: bool = False) -> float | None:
        if not self.record.fields.get(name, "").strip():
            return None
        return self.decimal(name, must_be_positive)

    def boolean(self, name: str) -> bool:
        value = self.text(name)
        word = value.lower()
        if word in TRUE_WORDS:
            result = True
        elif word in FALSE_WORDS:
            result = False
        else:
            raise self._error(InvalidValueError, f"{name} {value!r} is not true or false")
        canonical = str(result).lower()
        if value != canonical:
            self.corrections.append(f"{name}: read {value!r} as {canonical}")
        return result

    def date_time(self, name: str) -> datetime:
        value = self.text(name)
        try:
            return datetime.strptime(value, DATETIME_FORMAT)
        except ValueError:
            raise self._error(
                InvalidValueError, f"{name} {value!r} is not a valid date and time (YYYY-MM-DDTHH:MM)"
            ) from None


def load_companies(path: Path) -> dict[str, Company]:
    companies = {}
    for record in read_csv(path, COMPANY_COLUMNS):
        reader = FieldReader(record)
        code = reader.text("code").upper()
        companies[code] = Company(code, reader.text("name"), reader.text("description"))
    return companies


def load_destinations(path: Path) -> dict[str, Destination]:
    destinations = {}
    for record in read_csv(path, DESTINATION_COLUMNS):
        reader = FieldReader(record)
        code = reader.text("code").upper()
        destinations[code] = Destination(
            code=code,
            name=reader.text("name"),
            distance_km=reader.integer("distance_km", minimum=1),
            coastal=reader.boolean("coastal"),
        )
    return destinations









@dataclass
class QuarantinedRecord:
    line: int
    offer_id: str
    reason: str
    fields: dict[str, str]


@dataclass
class ValidationReport:
    records_read: int = 0
    offers: list[Offer] = field(default_factory=list)
    corrected: dict[str, list[str]] = field(default_factory=dict)
    rejected: list[DataError] = field(default_factory=list)
    quarantined: list[QuarantinedRecord] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.records_read} read, {len(self.offers)} loaded "
                f"({len(self.corrected)} corrected), {len(self.rejected)} rejected, "
                f"{len(self.quarantined)} quarantined")












class OfferValidator:

    def __init__(self, companies: dict[str, Company], destinations: dict[str, Destination]) -> None:
        self.companies = companies
        self.destinations_by_name = {normalise_name(d.name): d for d in destinations.values()}


    def validate_record(self, record: RawRecord) -> tuple[Offer, list[str]]:
        reader = FieldReader(record)
        offer_id = reader.text("offer_id")
        reader.record_id = offer_id

        id_match = OFFER_ID_PATTERN.fullmatch(offer_id)
        if id_match is None:
            raise InvalidValueError(
                f"offer_id {offer_id!r} does not match the format AAA-AAA-000",
                record_id=offer_id, line=record.line)

        company = self._find_company(reader)
        destination = self._find_destination(reader)

        if id_match["company"] != company.code or id_match["destination"] != destination.code:
            raise InconsistentRecordError(
                f"offer_id codes {id_match['company']}-{id_match['destination']} do not match "
                f"company {company.code} and destination {destination.code}",
                record_id=offer_id, line=record.line)

        departure = reader.date_time("departure")
        arrival = reader.date_time("arrival")
        if arrival <= departure:
            raise InconsistentRecordError(
                f"arrival {arrival:%Y-%m-%d %H:%M} is not after departure {departure:%Y-%m-%d %H:%M}",
                record_id=offer_id, line=record.line)

        offer = Offer(
            offer_id=offer_id,
            company=company,
            destination=destination,
            departure=departure,
            arrival=arrival,
            price_eur=reader.decimal("price_eur", must_be_positive=True),
            transfers=reader.integer("transfers", minimum=0),
            fare=FareConditions(
                changeable=reader.boolean("changeable"),
                refundable=reader.boolean("refundable"),
                luggage_bags=reader.integer("luggage_bags", minimum=0),
            ),
            seats_available=reader.integer("seats_available", minimum=0),
            rating=reader.decimal("rating"),
            co2_kg=reader.optional_decimal("co2_kg", must_be_positive=True),
        )
        return offer, reader.corrections

    def _find_company(self, reader: FieldReader) -> Company:
        value = reader.text("company")
        company = self.companies.get(value.upper())
        if company is None:
            raise reader._error(UnknownReferenceError, f"unknown company {value!r}")
        if value != company.code:
            reader.corrections.append(f"company: {value!r} read as {company.code!r}")
        return company

    def _find_destination(self, reader: FieldReader) -> Destination:
        raw = reader.record.fields.get("destination", "")
        value = reader.text("destination")
        destination = self.destinations_by_name.get(normalise_name(value))
        if destination is None:
            raise reader._error(UnknownReferenceError, f"unknown destination {value!r}")
        if value != destination.name:
            reader.corrections = [c for c in reader.corrections if not c.startswith("destination:")]
            reader.corrections.append(f"destination: {raw!r} corrected to {destination.name!r}")
        return destination

    def quarantine_reason(self, offer: Offer) -> str | None:
        low, high = RATING_RANGE
        if not low <= offer.rating <= high:
            return f"rating {offer.rating} is outside {low}-{high}; it may use a different scale"
        return None





    @staticmethod
    def price_outliers(offers: list[Offer]) -> dict[str, str]:
        prices_by_destination: dict[str, list[float]] = {}
        for offer in offers:
            prices_by_destination.setdefault(offer.destination.code, []).append(offer.price_eur)
        medians = {code: statistics.median(prices) for code, prices in prices_by_destination.items()}

        outliers = {}
        for offer in offers:
            limit = PRICE_OUTLIER_FACTOR * medians[offer.destination.code]
            if offer.price_eur > limit:
                outliers[offer.offer_id] = (
                    f"price {offer.price_eur:.2f} is more than {PRICE_OUTLIER_FACTOR}x the "
                    f"{offer.destination.name} median of {medians[offer.destination.code]:.2f}")
        return outliers



    def validate(self, records: list[RawRecord]) -> ValidationReport:
        report = ValidationReport(records_read=len(records))
        candidates: list[tuple[Offer, RawRecord, list[str]]] = []
        first_seen: dict[str, int] = {}
        for record in records:
            try:
                offer_id = record.fields.get("offer_id", "").strip()
                if offer_id in first_seen:
                    raise InconsistentRecordError(
                        f"duplicate offer_id, first seen on line {first_seen[offer_id]}",
                        record_id=offer_id, line=record.line)
                offer, corrections = self.validate_record(record)
            except DataError as error:
                report.rejected.append(error)
                logger.error("Rejected: %s", error)
                continue

            first_seen[offer.offer_id] = record.line
            reason = self.quarantine_reason(offer)
            if reason:
                self._quarantine(report, record, offer.offer_id, reason)
            else:
                candidates.append((offer, record, corrections))

        outliers = self.price_outliers([offer for offer, _, _ in candidates])
        for offer, record, corrections in candidates:
            if offer.offer_id in outliers:
                self._quarantine(report, record, offer.offer_id, outliers[offer.offer_id])
                continue
            report.offers.append(offer)
            if corrections:
                report.corrected[offer.offer_id] = corrections
                for correction in corrections:
                    logger.warning("Corrected: [line %d, %s] %s", record.line, offer.offer_id, correction)

        logger.info("Validation: %s", report.summary())
        return report

    @staticmethod
    def _quarantine(report: ValidationReport, record: RawRecord, offer_id: str, reason: str) -> None:
        report.quarantined.append(QuarantinedRecord(record.line, offer_id, reason, record.fields))
        logger.warning("Quarantined: [line %d, %s] %s", record.line, offer_id, reason)

def load_offers(offers_path: Path, companies_path: Path, destinations_path: Path) -> ValidationReport:
    validator = OfferValidator(load_companies(companies_path), load_destinations(destinations_path))
    return validator.validate(read_csv(offers_path, OFFER_COLUMNS))


def write_quarantine(records: list[QuarantinedRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["line", "reason", *OFFER_COLUMNS])
        writer.writeheader()
        for item in records:
            writer.writerow({"line": item.line, "reason": item.reason, **item.fields})