"""Tests for the domain model classes."""

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from busbidder.exceptions import NoSeatsAvailableError
from busbidder.models import Company, Destination, FareConditions, Offer


def make_offer(**changes) -> Offer:
    """Build a valid offer; keyword arguments override individual fields."""
    values = {
        "offer_id": "SOL-MAL-001",
        "company": Company("SOL", "SolRuta", "Low-cost daytime services"),
        "destination": Destination("MAL", "Malaga", 530, True),
        "departure": datetime(2027, 7, 12, 9, 0),
        "arrival": datetime(2027, 7, 12, 17, 15),
        "price_eur": 32.07,
        "transfers": 0,
        "fare": FareConditions(changeable=True, refundable=False, luggage_bags=1),
        "seats_available": 10,
        "rating": 3.6,
        "co2_kg": 17.9,
    }
    values.update(changes)
    return Offer(**values)











def test_duration_is_calculated_from_departure_and_arrival():
    offer = make_offer()
    assert offer.duration_minutes == 8 * 60 + 15


def test_duration_works_across_midnight():
    overnight = make_offer(
        departure=datetime(2027, 7, 12, 23, 0),
        arrival=datetime(2027, 7, 13, 6, 30),
    )
    assert overnight.duration_minutes == 7 * 60 + 30


def test_reserve_seat_reduces_available_seats_by_one():
    offer = make_offer(seats_available=2)
    offer.reserve_seat()
    assert offer.seats_available == 1


def test_offer_with_zero_seats_is_sold_out():
    assert make_offer(seats_available=0).is_sold_out
    assert not make_offer(seats_available=1).is_sold_out


def test_reserving_the_last_seat_makes_the_offer_sold_out():
    offer = make_offer(seats_available=1)
    offer.reserve_seat()
    assert offer.is_sold_out


def test_reserving_a_seat_on_a_sold_out_offer_raises_and_changes_nothing():
    offer = make_offer(seats_available=0)
    with pytest.raises(NoSeatsAvailableError):
        offer.reserve_seat()
    assert offer.seats_available == 0


def test_emissions_default_to_none_when_not_reported():
    values = {
        "offer_id": "NOC-MAL-001",
        "company": Company("NOC", "NocheVia", "Overnight services"),
        "destination": Destination("MAL", "Malaga", 530, True),
        "departure": datetime(2027, 7, 12, 23, 15),
        "arrival": datetime(2027, 7, 13, 9, 5),
        "price_eur": 38.42,
        "transfers": 1,
        "fare": FareConditions(True, False, 1),
        "seats_available": 43,
        "rating": 3.9,
    }
    offer = Offer(**values)
    assert offer.co2_kg is None


def test_fare_conditions_cannot_be_changed_after_creation():
    fare = FareConditions(changeable=False, refundable=False, luggage_bags=1)
    with pytest.raises(FrozenInstanceError):
        fare.refundable = True


def test_company_cannot_be_changed_after_creation():
    company = Company("SOL", "SolRuta", "Low-cost daytime services")
    with pytest.raises(FrozenInstanceError):
        company.name = "Other"