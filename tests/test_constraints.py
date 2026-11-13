from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from busbidder.constraints import (
    DEFAULT_CONSTRAINTS,
    ChangeableRequiredConstraint,
    Constraint,
    DestinationConstraint,
    MaxBudgetConstraint,
    MaxDurationConstraint,
    MaximumConstraint,
    MaxTransfersConstraint,
    OfferFilter,
    RefundableRequiredConstraint,
    SeatsAvailableConstraint,
    TravelWindowConstraint,
    format_duration,
)
from busbidder.models import Company, Destination, FareConditions, Offer
from busbidder.profiles import Limits, TravellerProfile, TravelRequest, load_profiles
from busbidder.validation import load_offers

ROOT = Path(__file__).resolve().parent.parent
MALAGA = Destination("MAL", "Malaga", 530, True)
CORDOBA = Destination("COR", "Cordoba", 400, False)


def make_offer(offer_id="SOL-MAL-001", destination=MALAGA, day=12, price=30.0, minutes=480,
               transfers=0, changeable=True, refundable=True, seats=10) -> Offer:
    start = datetime(2027, 7, day, 9, 0)
    return Offer(offer_id, Company("SOL", "SolRuta", ""), destination, start,
                 start + timedelta(minutes=minutes), price, transfers,
                 FareConditions(changeable, refundable, 1), seats, 4.0, 15.0)


def make_request(earliest=12, latest=14, **limits) -> TravelRequest:
    profile = TravellerProfile(key="test", name="Test", departure_window="morning",
                               weights={"price": 100}, limits=Limits(**limits))
    return TravelRequest(profile, MALAGA, date(2027, 7, earliest), date(2027, 7, latest))



def test_every_default_constraint_has_a_name_layer_and_outcome():
    for constraint in DEFAULT_CONSTRAINTS:
        assert constraint.name
        assert constraint.layer in ("A", "B")
        assert constraint.outcome in ("not_matching", "sold_out", "removed")


def test_abstract_constraint_classes_cannot_be_created():
    with pytest.raises(TypeError):
        Constraint()
    with pytest.raises(TypeError):
        MaximumConstraint()


def test_destination_must_match():
    request = make_request()
    assert DestinationConstraint().check(make_offer(), request)
    assert not DestinationConstraint().check(make_offer(destination=CORDOBA), request)


@pytest.mark.parametrize("day, inside", [(11, False), (12, True), (13, True), (14, True), (15, False)])
def test_departure_date_must_be_within_the_travel_window_including_both_ends(day, inside):
    assert TravelWindowConstraint().check(make_offer(day=day), make_request()) is inside


def test_overnight_arrival_after_the_window_still_counts_by_departure_date():
    offer = make_offer(day=14, minutes=16 * 60)
    assert TravelWindowConstraint().check(offer, make_request())


@pytest.mark.parametrize("seats, ok", [(0, False), (1, True), (40, True)])
def test_at_least_one_seat_is_needed(seats, ok):
    assert SeatsAvailableConstraint().check(make_offer(seats=seats), make_request()) is ok


def test_layer_a_constraints_are_always_active():
    request = make_request()
    for constraint in (DestinationConstraint(), TravelWindowConstraint(), SeatsAvailableConstraint()):
        assert constraint.is_active(request)



def test_layer_b_constraints_are_inactive_without_a_limit():
    request = make_request()
    for constraint in DEFAULT_CONSTRAINTS:
        if constraint.layer == "B":
            assert not constraint.is_active(request)


@pytest.mark.parametrize("price, ok", [(39.99, True), (40.00, True), (40.01, False)])
def test_price_at_the_limit_passes_and_above_fails(price, ok):
    assert MaxBudgetConstraint().check(make_offer(price=price), make_request(max_price_eur=40)) is ok


@pytest.mark.parametrize("transfers, ok", [(0, True), (1, False)])
def test_zero_transfer_limit_allows_only_direct_buses(transfers, ok):
    assert MaxTransfersConstraint().check(make_offer(transfers=transfers),
                                          make_request(max_transfers=0)) is ok


@pytest.mark.parametrize("minutes, ok", [(419, True), (420, True), (421, False)])
def test_duration_at_the_limit_passes_and_above_fails(minutes, ok):
    assert MaxDurationConstraint().check(make_offer(minutes=minutes),
                                         make_request(max_duration_minutes=420)) is ok


def test_required_features():
    request = make_request(changeable_required=True, refundable_required=True)
    fixed = make_offer(changeable=False, refundable=False)
    assert not ChangeableRequiredConstraint().check(fixed, request)
    assert not RefundableRequiredConstraint().check(fixed, request)
    assert ChangeableRequiredConstraint().check(make_offer(), request)


def test_failure_reasons_include_the_offer_value_and_the_limit():
    request = make_request(max_price_eur=40, max_duration_minutes=420, changeable_required=True)
    offer = make_offer(price=52.3, minutes=455, changeable=False)
    assert MaxBudgetConstraint().failure_reason(offer, request) == \
        "price EUR 52.30 is over the limit of EUR 40.00"
    assert MaxDurationConstraint().failure_reason(offer, request) == \
        "duration 7h 35m is over the limit of 7h 00m"
    assert ChangeableRequiredConstraint().failure_reason(offer, request) == "ticket is not changeable"


def test_format_duration():
    assert format_duration(420) == "7h 00m"
    assert format_duration(595) == "9h 55m"



def test_filter_sorts_offers_into_not_matching_sold_out_removed_and_kept():
    offers = [
        make_offer("A"),
        make_offer("B", destination=CORDOBA),
        make_offer("C", day=20),
        make_offer("D", seats=0),
        make_offer("E", price=55),
    ]
    result = OfferFilter().apply(offers, make_request(max_price_eur=40))
    assert [o.offer_id for o in result.kept] == ["A"]
    assert result.not_matching == 2
    assert [o.offer_id for o in result.sold_out] == ["D"]
    assert [r.offer.offer_id for r in result.removed] == ["E"]
    assert result.matching == 3


def test_layer_a_is_checked_before_layer_b():
    result = OfferFilter().apply([make_offer(seats=0, price=99)], make_request(max_price_eur=40))
    assert len(result.sold_out) == 1 and result.removed == []


def test_removed_offer_records_every_failed_limit_and_shows_the_first():
    request = make_request(max_price_eur=40, refundable_required=True)
    result = OfferFilter().apply([make_offer(price=55, refundable=False)], request)
    removed = result.removed[0]
    assert [c.name for c in removed.failed] == ["price", "refundable"]
    assert removed.reason == "price EUR 55.00 is over the limit of EUR 40.00"


def test_removed_counts_use_the_first_failure_only():
    request = make_request(max_price_eur=40, refundable_required=True)
    offers = [make_offer("A", price=55, refundable=False), make_offer("B", refundable=False)]
    assert OfferFilter().apply(offers, request).removed_counts() == {"price": 1, "refundable": 1}


def test_most_restrictive_counts_every_failure():
    request = make_request(max_price_eur=40, refundable_required=True)
    offers = [make_offer("A", price=55, refundable=False), make_offer("B", refundable=False)]
    assert OfferFilter().apply(offers, request).most_restrictive() == ("refundable", 2)


def test_most_restrictive_is_none_when_nothing_was_removed():
    assert OfferFilter().apply([make_offer()], make_request()).most_restrictive() is None


def test_active_constraints_are_listed_in_words():
    result = OfferFilter().apply([], make_request(max_price_eur=40, changeable_required=True))
    assert result.active == [
        "destination Malaga",
        "departing 12 Jul 2027 to 14 Jul 2027",
        "at least one free seat",
        "price at most EUR 40.00",
        "ticket must be changeable",
    ]


def test_summary_line():
    offers = [make_offer("A"), make_offer("B", seats=0), make_offer("C", price=55),
              make_offer("D", price=60)]
    result = OfferFilter().apply(offers, make_request(max_price_eur=40))
    assert result.summary() == \
        "4 matching offers; 1 sold out; 2 removed by your limits (2 price); 1 ranked"


def test_no_offers_gives_an_empty_result():
    result = OfferFilter().apply([], make_request())
    assert result.kept == [] and result.matching == 0













@pytest.mark.parametrize("profile_key, expected_kept", [
    ("budget", 8), ("business", 5), ("flexible", 6), ("eco", 14),
])
def test_real_malaga_search_keeps_the_expected_number_of_offers(profile_key, expected_kept):
    report = load_offers(ROOT / "data" / "offers.csv", ROOT / "data" / "companies.csv",
                         ROOT / "data" / "destinations.csv")
    profile = load_profiles(ROOT / "config" / "profiles.json")[profile_key]
    request = TravelRequest(profile, MALAGA, date(2027, 7, 12), date(2027, 7, 14))

    result = OfferFilter().apply(report.offers, request)

    assert len(result.kept) == expected_kept
    assert [o.offer_id for o in result.sold_out] == ["COS-MAL-001"]
    assert result.matching == 15