import statistics
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from busbidder.models import Offer

MINUTES_PER_DAY = 24 * 60
DEPARTURE_FALLOFF_MINUTES = 6 * 60
NO_INFORMATION_SCORE = 50.0

DEPARTURE_WINDOWS = {
    "morning": (6 * 60, 12 * 60),
    "afternoon": (12 * 60, 18 * 60),
    "evening": (18 * 60, 6 * 60),
}

CHANGEABLE_POINTS = 60
REFUNDABLE_POINTS = 40


@dataclass(frozen=True)
class ScoringContext:
    offers: tuple[Offer, ...]
    departure_window: str




class Criterion(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    def score(self, offer: Offer, context: ScoringContext) -> float:
        """Score from 0 to 100, higher is better."""


class RatioCriterion(Criterion):

    @abstractmethod
    def value(self, offer: Offer) -> float | None:
        """The offers raw value for this criterion or none if not reported."""

    def score(self, offer: Offer, context: ScoringContext) -> float:
        own = self.value(offer)
        if own is None:
            return self.score_missing(offer, context)
        reported = [v for v in map(self.value, context.offers) if v is not None]
        best = min(reported + [own])
        return 100 * best / own

    def score_missing(self, offer: Offer, context: ScoringContext) -> float:
        raise ValueError(f"{self.name}: offer {offer.offer_id} has no value")


CRITERIA: dict[str, type[Criterion]] = {}


def register_criterion(name: str):
    def decorator(cls: type[Criterion]) -> type[Criterion]:
        if not (isinstance(cls, type) and issubclass(cls, Criterion)):
            raise TypeError(f"@register_criterion can only be used on Criterion classes, not {cls!r}")
        if name in CRITERIA:
            raise ValueError(f"A criterion named {name!r} is already registered")
        cls.name = name
        CRITERIA[name] = cls
        return cls
    return decorator


def create_criterion(name: str) -> Criterion:
    return CRITERIA[name]()



@register_criterion("price")
class PriceCriterion(RatioCriterion):
    description = "Ticket price (lower is better)"

    def value(self, offer: Offer) -> float:
        return offer.price_eur


@register_criterion("duration")
class DurationCriterion(RatioCriterion):
    description = "Journey time (shorter is better)"

    def value(self, offer: Offer) -> float:
        return offer.duration_minutes


@register_criterion("emissions")
class EmissionsCriterion(RatioCriterion):
    description = "CO2 per passenger (lower is better)"

    def value(self, offer: Offer) -> float | None:
        return offer.co2_kg

    def score_missing(self, offer: Offer, context: ScoringContext) -> float:
        reported = [other for other in context.offers if other.co2_kg is not None]
        if not reported:
            return NO_INFORMATION_SCORE
        return statistics.median(self.score(other, context) for other in reported)


@register_criterion("departure")
class DepartureCriterion(Criterion):
    description = "Departure time compared with the preferred window"

    def score(self, offer: Offer, context: ScoringContext) -> float:
        minutes_away = minutes_outside_window(offer.departure, context.departure_window)
        return max(0.0, 100 * (1 - minutes_away / DEPARTURE_FALLOFF_MINUTES))


@register_criterion("flexibility")
class FlexibilityCriterion(Criterion):
    description = "Ticket can be changed (60) and/or refunded (40)"

    def score(self, offer: Offer, context: ScoringContext) -> float:
        points = 0
        if offer.fare.changeable:
            points += CHANGEABLE_POINTS
        if offer.fare.refundable:
            points += REFUNDABLE_POINTS
        return float(points)


def minutes_outside_window(departure: datetime, window: str) -> int:
    if window not in DEPARTURE_WINDOWS:
        raise ValueError(f"Unknown departure window {window!r}; "
                         f"choose from {', '.join(DEPARTURE_WINDOWS)}")
    start, end = DEPARTURE_WINDOWS[window]
    time = departure.hour * 60 + departure.minute

    if start <= end:
        inside = start <= time <= end
    else:
        inside = time >= start or time <= end
    if inside:
        return 0

    def around_the_clock(a: int, b: int) -> int:
        difference = abs(a - b)
        return min(difference, MINUTES_PER_DAY - difference)

    return min(around_the_clock(time, start), around_the_clock(time, end))