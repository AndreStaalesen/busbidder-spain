import json
import random
from datetime import datetime, timedelta

import pytest

from busbidder.booking import (
    REFERENCE_PATTERN,
    Booking,
    BookingManager,
    clean_name,
    is_valid_reference,
)
from busbidder.exceptions import BookingError, NoSeatsAvailableError
from busbidder.models import Company, Destination, FareConditions, Offer

FIXED_TIME = datetime(2026, 11, 13, 18, 30, 15)


def make_offer(offer_id="SOL-MAL-001", seats=10) -> Offer:
    start = datetime(2027, 7, 12, 9, 0)
    return Offer(offer_id, Company(offer_id[:3], "SolRuta", ""), Destination("MAL", "Malaga", 530, True),
                 start, start + timedelta(hours=8), 32.07, 0,
                 FareConditions(changeable=True, refundable=False, luggage_bags=1), seats, 3.6, 17.9)


@pytest.fixture
def manager(tmp_path) -> BookingManager:
    return BookingManager(tmp_path / "bookings.json", rng=random.Random(1), clock=lambda: FIXED_TIME)




@pytest.mark.parametrize("name, expected", [
    ("Ana Garcia", "Ana Garcia"),
    ("  André   Smurfu ", "André Smurfu"),
    ("Anne-Marie O'Brien", "Anne-Marie O'Brien"),
    ("José", "José"),
])
def test_valid_names_are_accepted_and_tidied(name, expected):
    assert clean_name(name) == expected


@pytest.mark.parametrize("name, message", [
    ("", "enter the traveller's name"),
    ("   ", "enter the traveller's name"),
    ("R2D2", "only contain letters"),
    ("Ana--Garcia", "only contain letters"),
    ("-Ana", "only contain letters"),
    ("Ana_Garcia", "only contain letters"),
    ("A" * 61, "too long"),
])
def test_invalid_names_are_rejected(name, message):
    with pytest.raises(BookingError, match=message):
        clean_name(name)


def test_name_of_exactly_maximum_length_is_accepted():
    assert clean_name("A" * 60) == "A" * 60









@pytest.mark.parametrize("text, valid", [
    ("BB-SOL-7K3Q9X", True),
    ("bb-sol-7k3q9x", True),
    (" BB-SOL-7K3Q9X ", True),
    ("BB-SOL-7K3Q9", False),
    ("BB-SOL-7K3Q9O", False),
    ("BB-SOL-7K3Q91", False),
    ("XX-SOL-7K3Q9X", False),
    ("BB-SO-7K3Q9X", False),
])
def test_reference_format(text, valid):
    assert is_valid_reference(text) is valid


def test_new_references_match_the_pattern_and_use_the_company_code(manager):
    for _ in range(50):
        reference = manager.new_reference("VER")
        assert REFERENCE_PATTERN.fullmatch(reference)
        assert reference.startswith("BB-VER-")


def test_reference_already_in_use_is_never_repeated(tmp_path):
    path = tmp_path / "bookings.json"
    first = BookingManager(path, rng=random.Random(7), clock=lambda: FIXED_TIME)
    taken = first.book(make_offer(), "Ana Garcia").reference

    second = BookingManager(path, rng=random.Random(7), clock=lambda: FIXED_TIME)
    assert second.new_reference("SOL") != taken



def test_booking_takes_one_seat(manager):
    offer = make_offer(seats=3)
    manager.book(offer, "Ana Garcia")
    assert offer.seats_available == 2


def test_booking_stores_offer_details_and_fare_conditions(manager):
    offer = make_offer()
    booking = manager.book(offer, " Ana  Garcia ")
    assert booking.offer_id == "SOL-MAL-001"
    assert booking.traveller_name == "Ana Garcia"
    assert booking.company_name == "SolRuta"
    assert booking.destination_name == "Malaga"
    assert booking.price_eur == 32.07
    assert booking.fare == FareConditions(changeable=True, refundable=False, luggage_bags=1)
    assert booking.booked_at == FIXED_TIME
    assert booking.payment_status == "simulated - no payment taken"


def test_booking_the_last_seat_makes_the_offer_sold_out(manager):
    offer = make_offer(seats=1)
    manager.book(offer, "Ana Garcia")
    assert offer.is_sold_out


def test_booking_a_sold_out_offer_fails_and_saves_nothing(manager):
    offer = make_offer(seats=0)
    with pytest.raises(NoSeatsAvailableError):
        manager.book(offer, "Ana Garcia")
    assert manager.bookings == []
    assert not manager.path.exists()


def test_invalid_name_fails_before_a_seat_is_taken(manager):
    offer = make_offer(seats=5)
    with pytest.raises(BookingError):
        manager.book(offer, "R2D2")
    assert offer.seats_available == 5


def test_failed_save_is_undone(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("this is a file, not a folder", encoding="utf-8")
    manager = BookingManager(blocked / "bookings.json", clock=lambda: FIXED_TIME)

    offer = make_offer(seats=5)
    with pytest.raises(BookingError, match="could not be saved"):
        manager.book(offer, "Ana Garcia")
    assert offer.seats_available == 5
    assert manager.bookings == []


def test_find_booking_by_reference(manager):
    booking = manager.book(make_offer(), "Ana Garcia")
    assert manager.find(booking.reference.lower()) == booking
    assert manager.find("BB-SOL-ZZZZZZ") is None



def test_bookings_are_saved_as_readable_json(manager):
    manager.book(make_offer(), "André Smurfu")
    data = json.loads(manager.path.read_text(encoding="utf-8"))
    assert data[0]["traveller_name"] == "André Smurfu"
    assert data[0]["fare"] == {"changeable": True, "refundable": False, "luggage_bags": 1}
    assert data[0]["departure"] == "2027-07-12T09:00"


def test_booking_survives_a_round_trip_through_json():
    booking = Booking("BB-SOL-7K3Q9X", "SOL-MAL-001", "Ana Garcia", "SolRuta", "Malaga",
                      datetime(2027, 7, 12, 9, 0), datetime(2027, 7, 12, 17, 0), 32.07,
                      FareConditions(True, False, 1), FIXED_TIME)
    assert Booking.from_dict(booking.to_dict()) == booking


def test_bookings_are_loaded_again_by_a_new_manager(manager):
    first = manager.book(make_offer(), "Ana Garcia")
    reopened = BookingManager(manager.path)
    assert reopened.bookings == [first]


def test_stored_bookings_reduce_seats_after_a_restart(manager):
    offer = make_offer(seats=10)
    manager.book(offer, "Ana Garcia")
    manager.book(offer, "Luis Perez")

    fresh_offer = make_offer(seats=10)
    BookingManager(manager.path).apply_to_offers([fresh_offer])
    assert fresh_offer.seats_available == 8


def test_more_bookings_than_seats_leaves_the_offer_sold_out(manager):
    offer = make_offer(seats=2)
    manager.book(offer, "Ana Garcia")
    manager.book(offer, "Luis Perez")

    smaller = make_offer(seats=1)
    BookingManager(manager.path).apply_to_offers([smaller])
    assert smaller.seats_available == 0


def test_bookings_for_unknown_offers_are_ignored(manager):
    manager.book(make_offer("SOL-MAL-001"), "Ana Garcia")
    other = make_offer("CAM-MAL-001", seats=10)
    BookingManager(manager.path).apply_to_offers([other])
    assert other.seats_available == 10


def test_missing_bookings_file_means_no_bookings(tmp_path):
    assert BookingManager(tmp_path / "none.json").bookings == []


def test_damaged_bookings_file_raises_booking_error(tmp_path):
    path = tmp_path / "bookings.json"
    path.write_text("[{\"reference\": ", encoding="utf-8")
    with pytest.raises(BookingError, match="Cannot read bookings"):
        BookingManager(path)