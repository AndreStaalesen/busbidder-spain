"""Domain model for BusBidder.

Plain data classes that represent the marketplace. They hold data and a few
small behaviours that belong to the data itself.
"""

from dataclasses import dataclass
from datetime import datetime

from busbidder.exceptions import NoSeatsAvailableError


@dataclass(frozen=True)
class Company:
    """A bus company. Frozen: company details never change while the program runs."""

    code: str
    name: str
    description: str


@dataclass(frozen=True)
class Destination:
    """A destination served from Madrid."""

    code: str
    name: str
    distance_km: int
    coastal: bool


@dataclass(frozen=True)
class FareConditions:
    """The ticket conditions attached to an offer.
    Kept as its own class because a booking stores a copy of
    the conditions that applied when it was made.
    """

    changeable: bool
    refundable: bool
    luggage_bags: int


@dataclass
class Offer:
    """One bookable departure from one company to one destination.
    Not frozen, because the number of available seats goes down when a
    booking is made.
    """

    offer_id: str
    company: Company
    destination: Destination
    departure: datetime
    arrival: datetime
    price_eur: float
    transfers: int
    fare: FareConditions
    seats_available: int
    rating: float
    co2_kg: float | None = None

    @property
    def duration_minutes(self) -> int:
        """Journey time in minutes, calculated from departure and arrival.
        """
        return int((self.arrival - self.departure).total_seconds() // 60)

    @property
    def is_sold_out(self) -> bool:
        return self.seats_available == 0

    def reserve_seat(self) -> None:
        """Take one seat. Raises NoSeatsAvailableError if the offer is sold out."""
        if self.seats_available <= 0:
            raise NoSeatsAvailableError(f"Offer {self.offer_id} has no seats left")
        self.seats_available -= 1