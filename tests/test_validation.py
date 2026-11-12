import csv
from datetime import datetime
from pathlib import Path

import pytest

from busbidder.exceptions import (
    DataError,
    InconsistentRecordError,
    InvalidValueError,
    MissingFieldError,
    UnknownReferenceError,
)
from busbidder.loader import RawRecord
from busbidder.models import Company, Destination
from busbidder.validation import (
    FieldReader,
    OfferValidator,
    load_companies,
    load_destinations,
    load_offers,
    normalise_name,
    write_quarantine,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

COMPANIES = {
    "SOL": Company("SOL", "SolRuta", "Low-cost daytime services"),
    "CAM": Company("CAM", "Camino Express", "Fast direct connections"),
}
DESTINATIONS = {
    "MAL": Destination("MAL", "Malaga", 530, True),
    "COR": Destination("COR", "Cordoba", 400, False),
}

VALID_FIELDS = {
    "offer_id": "SOL-MAL-001", "company": "SOL", "destination": "Malaga",
    "departure": "2027-07-12T09:00", "arrival": "2027-07-12T17:15",
    "price_eur": "32.07", "transfers": "0", "luggage_bags": "1",
    "changeable": "true", "refundable": "false", "seats_available": "10",
    "rating": "3.6", "co2_kg": "17.9",
}


def raw(line: int = 2, **changes) -> RawRecord:
    return RawRecord(line=line, fields={**VALID_FIELDS, **changes})


@pytest.fixture
def validator() -> OfferValidator:
    return OfferValidator(COMPANIES, DESTINATIONS)


@pytest.mark.parametrize("text", ["Cordoba", "cordoba", " cordoba ", "Córdoba", "CÓRDOBA"])
def test_name_variants_normalise_to_the_same_key(text):
    assert normalise_name(text) == "cordoba"


def test_reader_records_removed_spaces_as_a_correction():
    reader = FieldReader(raw(price_eur=" 32.07 "))
    assert reader.decimal("price_eur") == 32.07
    assert reader.corrections == ["price_eur: removed surrounding spaces from ' 32.07 '"]






@pytest.mark.parametrize("value, expected", [
    ("true", True), ("false", False), ("Y", True), ("yes", True), ("1", True),
    ("N", False), ("no", False), ("0", False),
])
def test_reader_accepts_boolean_variants(value, expected):
    assert FieldReader(raw(changeable=value)).boolean("changeable") is expected


def test_reader_records_boolean_variant_as_a_correction():
    reader = FieldReader(raw(changeable="Y"))
    reader.boolean("changeable")
    assert reader.corrections == ["changeable: read 'Y' as true"]


def test_reader_does_not_record_a_correction_for_canonical_values():
    reader = FieldReader(raw())
    reader.boolean("changeable")
    reader.decimal("price_eur")
    assert reader.corrections == []


@pytest.mark.parametrize("value", ["maybe", "2", "T"])
def test_reader_rejects_unknown_boolean_words(value):
    with pytest.raises(InvalidValueError):
        FieldReader(raw(changeable=value)).boolean("changeable")


@pytest.mark.parametrize("value", ["abc", "nan", "inf"])
def test_reader_rejects_values_that_are_not_finite_numbers(value):
    with pytest.raises(InvalidValueError):
        FieldReader(raw(price_eur=value)).decimal("price_eur")


def test_reader_rejects_decimal_where_whole_number_is_required():
    with pytest.raises(InvalidValueError, match="whole number"):
        FieldReader(raw(transfers="1.5")).integer("transfers")


def test_reader_treats_empty_optional_value_as_none():
    assert FieldReader(raw(co2_kg="")).optional_decimal("co2_kg") is None
    assert FieldReader(raw(co2_kg="   ")).optional_decimal("co2_kg") is None


def test_valid_record_becomes_an_offer_with_converted_values(validator):
    offer, corrections = validator.validate_record(raw())
    assert offer.offer_id == "SOL-MAL-001"
    assert offer.company is COMPANIES["SOL"]
    assert offer.destination is DESTINATIONS["MAL"]
    assert offer.departure == datetime(2027, 7, 12, 9, 0)
    assert offer.price_eur == 32.07
    assert offer.fare.changeable is True
    assert offer.fare.refundable is False
    assert offer.seats_available == 10
    assert offer.co2_kg == 17.9
    assert corrections == []


def test_missing_emissions_are_accepted_as_none(validator):
    offer, _ = validator.validate_record(raw(co2_kg=""))
    assert offer.co2_kg is None


def test_sold_out_offer_is_accepted(validator):
    offer, _ = validator.validate_record(raw(seats_available="0"))
    assert offer.is_sold_out


def test_overnight_offer_is_accepted(validator):
    offer, _ = validator.validate_record(
        raw(departure="2027-07-12T23:15", arrival="2027-07-13T09:05"))
    assert offer.duration_minutes == 590


@pytest.mark.parametrize("changes, error_class, message", [
    ({"price_eur": ""}, MissingFieldError, "price_eur is missing"),
    ({"price_eur": "-12.00"}, InvalidValueError, "greater than 0"),
    ({"price_eur": "0.00"}, InvalidValueError, "greater than 0"),
    ({"destination": "Paris"}, UnknownReferenceError, "unknown destination"),
    ({"offer_id": "XYZ-MAL-001", "company": "XYZ"}, UnknownReferenceError, "unknown company"),
    ({"arrival": "2027-07-12T07:00"}, InconsistentRecordError, "not after departure"),
    ({"arrival": "2027-07-12T09:00"}, InconsistentRecordError, "not after departure"),
    ({"departure": "2027-07-32T09:00"}, InvalidValueError, "not a valid date"),
    ({"offer_id": "sol-mal-1"}, InvalidValueError, "does not match the format"),
    ({"offer_id": "CAM-MAL-001"}, InconsistentRecordError, "do not match"),
    ({"offer_id": "SOL-COR-001"}, InconsistentRecordError, "do not match"),
    ({"seats_available": "-3"}, InvalidValueError, "at least 0"),
    ({"co2_kg": "0.0"}, InvalidValueError, "greater than 0"),
    ({"transfers": "-1"}, InvalidValueError, "at least 0"),
])




def test_invalid_records_are_rejected_with_a_clear_reason(validator, changes, error_class, message):
    with pytest.raises(error_class, match=message):
        validator.validate_record(raw(**changes))


def test_rejection_message_names_the_line_and_record(validator):
    with pytest.raises(DataError) as caught:
        validator.validate_record(raw(line=228, price_eur="-12.00"))
    assert str(caught.value).startswith("[line 228, SOL-MAL-001]")





@pytest.mark.parametrize("destination", [" malaga ", "Málaga", "MALAGA"])
def test_destination_spelling_is_corrected_and_logged(validator, destination):
    offer, corrections = validator.validate_record(raw(destination=destination))
    assert offer.destination.name == "Malaga"
    assert corrections == [f"destination: {destination!r} corrected to 'Malaga'"]


def test_lower_case_company_code_is_corrected(validator):
    offer, corrections = validator.validate_record(raw(company="sol"))
    assert offer.company.code == "SOL"
    assert "company: 'sol' read as 'SOL'" in corrections


def test_boolean_variants_are_corrected(validator):
    offer, corrections = validator.validate_record(raw(changeable="Y", refundable="yes"))
    assert offer.fare.changeable is True and offer.fare.refundable is True
    assert len(corrections) == 2


@pytest.mark.parametrize("rating, quarantined", [
    ("7.5", True), ("0.5", True), ("5.1", True),
    ("1.0", False), ("5.0", False), ("3.6", False),
])
def test_rating_outside_one_to_five_is_quarantined(validator, rating, quarantined):
    offer, _ = validator.validate_record(raw(rating=rating))
    assert (validator.quarantine_reason(offer) is not None) is quarantined


def test_price_more_than_three_times_the_destination_median_is_an_outlier(validator):
    prices = ["30.00", "32.00", "34.00", "120.00"]
    offers = [validator.validate_record(raw(offer_id=f"SOL-MAL-00{i}", price_eur=p))[0]
              for i, p in enumerate(prices, start=1)]
    outliers = validator.price_outliers(offers)
    assert list(outliers) == ["SOL-MAL-004"]
    assert "median of 33.00" in outliers["SOL-MAL-004"]


def test_price_exactly_three_times_the_median_is_not_an_outlier(validator):
    prices = ["30.00", "30.00", "90.00"]
    offers = [validator.validate_record(raw(offer_id=f"SOL-MAL-00{i}", price_eur=p))[0]
              for i, p in enumerate(prices, start=1)]
    assert validator.price_outliers(offers) == {}


def test_duplicate_id_keeps_the_first_record_and_rejects_later_ones(validator):
    report = validator.validate([
        raw(line=2),
        raw(line=3, price_eur="99.00"),
    ])
    assert [o.price_eur for o in report.offers] == [32.07]
    assert "duplicate offer_id, first seen on line 2" in str(report.rejected[0])


def test_duplicate_is_reported_even_if_the_record_has_other_problems(validator):
    report = validator.validate([raw(line=2), raw(line=3, company="CAM")])
    assert "duplicate" in str(report.rejected[0])


def test_report_sorts_records_into_loaded_corrected_rejected_and_quarantined(validator):
    report = validator.validate([
        raw(line=2, offer_id="SOL-MAL-001"),
        raw(line=3, offer_id="SOL-MAL-002", destination="Málaga"),
        raw(line=4, offer_id="SOL-MAL-003", price_eur="-1"),
        raw(line=5, offer_id="SOL-MAL-004", rating="7.5"),
    ])
    assert [o.offer_id for o in report.offers] == ["SOL-MAL-001", "SOL-MAL-002"]
    assert list(report.corrected) == ["SOL-MAL-002"]
    assert [e.record_id for e in report.rejected] == ["SOL-MAL-003"]
    assert [q.offer_id for q in report.quarantined] == ["SOL-MAL-004"]
    assert report.summary() == "4 read, 2 loaded (1 corrected), 1 rejected, 1 quarantined"


def test_empty_input_gives_an_empty_report(validator):
    report = validator.validate([])
    assert report.summary() == "0 read, 0 loaded (0 corrected), 0 rejected, 0 quarantined"


def test_quarantine_file_contains_reason_and_original_values(validator, tmp_path):
    report = validator.validate([raw(rating="7.5")])
    path = tmp_path / "quarantine.csv"
    write_quarantine(report.quarantined, path)

    with path.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 1
    assert rows[0]["offer_id"] == "SOL-MAL-001"
    assert rows[0]["rating"] == "7.5"
    assert "outside" in rows[0]["reason"]



def test_real_reference_files_load():
    companies = load_companies(DATA_DIR / "companies.csv")
    destinations = load_destinations(DATA_DIR / "destinations.csv")
    assert set(companies) == {"SOL", "CAM", "COS", "VER", "NOC"}
    assert len(destinations) == 15
    assert destinations["MAL"] == Destination("MAL", "Malaga", 530, True)


def test_invalid_reference_file_stops_loading(tmp_path):
    path = tmp_path / "destinations.csv"
    path.write_text("code,name,distance_km,coastal\nMAL,Malaga,far,true\n", encoding="utf-8")
    with pytest.raises(InvalidValueError, match="distance_km"):
        load_destinations(path)


@pytest.fixture(scope="module")
def real_report():
    return load_offers(DATA_DIR / "offers.csv", DATA_DIR / "companies.csv",
                       DATA_DIR / "destinations.csv")


def test_real_dataset_summary(real_report):
    assert real_report.summary() == "245 read, 230 loaded (3 corrected), 13 rejected, 2 quarantined"


def test_real_dataset_rejects_exactly_the_planned_edge_cases(real_report):
    expected = {f"SOL-COR-9{n:02d}" for n in [1, 2, 3, 4, 6, 7, 8, 12, 13]}
    expected |= {"XYZ-COR-905", "sol-cor-1", "CAM-COR-910", "CAM-BAR-001"}
    assert {error.record_id for error in real_report.rejected} == expected


def test_real_dataset_corrects_and_quarantines_the_planned_edge_cases(real_report):
    assert set(real_report.corrected) == {"SOL-COR-914", "SOL-COR-915", "SOL-COR-916"}
    assert {q.offer_id for q in real_report.quarantined} == {"SOL-COR-917", "SOL-COR-918"}


def test_real_dataset_keeps_the_first_of_the_duplicate_ids(real_report):
    first = next(o for o in real_report.offers if o.offer_id == "CAM-BAR-001")
    assert first.company.code == "CAM"


def test_all_generated_offers_are_loaded(real_report):
    generated = [o for o in real_report.offers if not o.offer_id.endswith(("-914", "-915", "-916", "-919", "-920"))]
    assert len(generated) == 225





    