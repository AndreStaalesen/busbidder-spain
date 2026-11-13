import json
import logging
import os
import random
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from busbidder.exceptions import BookingError
from busbidder.models import FareConditions, Offer

logger = logging.getLogger(__name__)


REFERENCE_CHARACTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
REFERENCE_PATTERN = re.compile(r"^BB-[A-Z]{3}-[A-HJ-NP-Z2-9]{6}$")


NAME_PATTERN = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$")
MAX_NAME_LENGTH = 60

PAYMENT_STATUS = "simulated - no payment taken"
MAX_REFERENCE_ATTEMPTS = 100


@dataclass(frozen=True)
class Booking:
    reference: str
    offer_id: str
    traveller_name: str
    company_name: str
    destination_name: str
    departure: datetime
    arrival: datetime
    price_eur: float
    fare: FareConditions
    booked_at: datetime
    payment_status: str = PAYMENT_STATUS

    def to_dict(self) -> dict:
        return {
            "reference": self.reference,
            "offer_id": self.offer_id,
            "traveller_name": self.traveller_name,
            "company_name": self.company_name,
            "destination_name": self.destination_name,
            "departure": self.departure.isoformat(timespec="minutes"),
            "arrival": self.arrival.isoformat(timespec="minutes"),
            "price_eur": self.price_eur,
            "fare": {"changeable": self.fare.changeable,
                     "refundable": self.fare.refundable,
                     "luggage_bags": self.fare.luggage_bags},
            "booked_at": self.booked_at.isoformat(timespec="seconds"),
            "payment_status": self.payment_status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Booking":
        return cls(
            reference=data["reference"],
            offer_id=data["offer_id"],
            traveller_name=data["traveller_name"],
            company_name=data["company_name"],
            destination_name=data["destination_name"],
            departure=datetime.fromisoformat(data["departure"]),
            arrival=datetime.fromisoformat(data["arrival"]),
            price_eur=data["price_eur"],
            fare=FareConditions(**data["fare"]),
            booked_at=datetime.fromisoformat(data["booked_at"]),
            payment_status=data.get("payment_status", PAYMENT_STATUS),
        )


def is_valid_reference(text: str) -> bool:
    return REFERENCE_PATTERN.fullmatch(text.strip().upper()) is not None


def clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise BookingError("Please enter the traveller's name")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise BookingError(f"Name is too long (at most {MAX_NAME_LENGTH} characters)")
    if not NAME_PATTERN.fullmatch(cleaned):
        raise BookingError("Name may only contain letters, single spaces, hyphens and apostrophes")
    return cleaned


class BookingManager:
    def __init__(self, path: Path, rng: random.Random | None = None,
                 clock: Callable[[], datetime] = datetime.now) -> None:
        self.path = path
        self.rng = rng or random.SystemRandom()
        self.clock = clock
        self.bookings: list[Booking] = self._load()

  

    def _load(self) -> list[Booking]:
        if not self.path.exists():
            return []
        try:
            with self.path.open(encoding="utf-8") as file:
                data = json.load(file)
            return [Booking.from_dict(item) for item in data]
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise BookingError(f"Cannot read bookings from {self.path}: {error}") from error

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as file:
            json.dump([b.to_dict() for b in self.bookings], file, indent=2, ensure_ascii=False)
        os.replace(temporary, self.path)




    def apply_to_offers(self, offers: list[Offer]) -> None:
        by_id = {offer.offer_id: offer for offer in offers}
        for offer_id, count in Counter(b.offer_id for b in self.bookings).items():
            offer = by_id.get(offer_id)
            if offer is None:
                logger.warning("Bookings exist for unknown offer %s; ignored", offer_id)
                continue
            if count > offer.seats_available:
                logger.warning("Offer %s has %d bookings but only %d seats; set to sold out",
                               offer_id, count, offer.seats_available)
            offer.seats_available = max(0, offer.seats_available - count)









    def new_reference(self, company_code: str) -> str:
        used = {b.reference for b in self.bookings}
        for _ in range(MAX_REFERENCE_ATTEMPTS):
            code = "".join(self.rng.choice(REFERENCE_CHARACTERS) for _ in range(6))
            reference = f"BB-{company_code}-{code}"
            if reference not in used:
                assert REFERENCE_PATTERN.fullmatch(reference), reference
                return reference
        raise BookingError("Could not create a unique booking reference")

    def book(self, offer: Offer, traveller_name: str) -> Booking:
        name = clean_name(traveller_name)
        offer.reserve_seat()

        booking = Booking(
            reference=self.new_reference(offer.company.code),
            offer_id=offer.offer_id,
            traveller_name=name,
            company_name=offer.company.name,
            destination_name=offer.destination.name,
            departure=offer.departure,
            arrival=offer.arrival,
            price_eur=offer.price_eur,
            fare=offer.fare,
            booked_at=self.clock().replace(microsecond=0),
        )
        self.bookings.append(booking)
        try:
            self._save()
        except OSError as error:
            self.bookings.pop()
            offer.seats_available += 1
            raise BookingError(f"Booking could not be saved: {error}") from error

        logger.info("Booked %s on %s for %s; %d seat(s) left",
                    booking.reference, offer.offer_id, name, offer.seats_available)
        return booking

    def find(self, reference: str) -> Booking | None:
        wanted = reference.strip().upper()
        return next((b for b in self.bookings if b.reference == wanted), None)