import logging
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field

from busbidder.models import Offer
from busbidder.profiles import TravelRequest

logger = logging.getLogger(__name__)



class Constraint(ABC):
    name: str = ""
    layer: str = ""
    outcome: str = ""

    def is_active(self, request: TravelRequest) -> bool:
        return True

    @abstractmethod
    def check(self, offer: Offer, request: TravelRequest) -> bool:
        """True if the offer satisfies the constraint."""

    @abstractmethod
    def describe(self, request: TravelRequest) -> str:
        """Describe the constraint in words, for the user."""

    def failure_reason(self, offer: Offer, request: TravelRequest) -> str:
        """Explain why the offer fails the constraint, for the user."""
        return f"fails: {self.describe(request)}"


class MaximumConstraint(Constraint):
    layer = "B"
    outcome = "removed"

    @abstractmethod
    def limit(self, request: TravelRequest) -> float | None: ...

    @abstractmethod
    def value(self, offer: Offer) -> float: ...

    @abstractmethod
    def format(self, amount: float) -> str: ...

    def is_active(self, request: TravelRequest) -> bool:
        return self.limit(request) is not None

    def check(self, offer: Offer, request: TravelRequest) -> bool:
        return self.value(offer) <= self.limit(request)

    def describe(self, request: TravelRequest) -> str:
        return f"{self.name} at most {self.format(self.limit(request))}"

    def failure_reason(self, offer: Offer, request: TravelRequest) -> str:
        return (f"{self.name} {self.format(self.value(offer))} is over the limit of "
                f"{self.format(self.limit(request))}")


class RequiredFeatureConstraint(Constraint):
    layer = "B"
    outcome = "removed"

    @abstractmethod
    def required(self, request: TravelRequest) -> bool: ...

    @abstractmethod
    def has_feature(self, offer: Offer) -> bool: ...

    def is_active(self, request: TravelRequest) -> bool:
        return self.required(request)

    def check(self, offer: Offer, request: TravelRequest) -> bool:
        return self.has_feature(offer)

    def describe(self, request: TravelRequest) -> str:
        return f"ticket must be {self.name}"

    def failure_reason(self, offer: Offer, request: TravelRequest) -> str:
        return f"ticket is not {self.name}"


def format_duration(minutes: float) -> str:
    hours, rest = divmod(int(minutes), 60)
    return f"{hours}h {rest:02d}m"



class DestinationConstraint(Constraint):
    name, layer, outcome = "destination", "A", "not_matching"

    def check(self, offer: Offer, request: TravelRequest) -> bool:
        return offer.destination.code == request.destination.code

    def describe(self, request: TravelRequest) -> str:
        return f"destination {request.destination.name}"


class TravelWindowConstraint(Constraint):
    name, layer, outcome = "travel dates", "A", "not_matching"

    def check(self, offer: Offer, request: TravelRequest) -> bool:
        return request.earliest_date <= offer.departure.date() <= request.latest_date

    def describe(self, request: TravelRequest) -> str:
        return f"departing {request.earliest_date:%d %b %Y} to {request.latest_date:%d %b %Y}"


class SeatsAvailableConstraint(Constraint):
    name, layer, outcome = "seats", "A", "sold_out"

    def check(self, offer: Offer, request: TravelRequest) -> bool:
        return offer.seats_available > 0

    def describe(self, request: TravelRequest) -> str:
        return "at least one free seat"

    def failure_reason(self, offer: Offer, request: TravelRequest) -> str:
        return "sold out"



class MaxBudgetConstraint(MaximumConstraint):
    name = "price"

    def limit(self, request): return request.profile.limits.max_price_eur
    def value(self, offer): return offer.price_eur
    def format(self, amount): return f"EUR {amount:.2f}"


class MaxTransfersConstraint(MaximumConstraint):
    name = "transfers"

    def limit(self, request): return request.profile.limits.max_transfers
    def value(self, offer): return offer.transfers
    def format(self, amount): return str(int(amount))


class MaxDurationConstraint(MaximumConstraint):
    name = "duration"

    def limit(self, request): return request.profile.limits.max_duration_minutes
    def value(self, offer): return offer.duration_minutes
    def format(self, amount): return format_duration(amount)


class ChangeableRequiredConstraint(RequiredFeatureConstraint):
    name = "changeable"

    def required(self, request): return request.profile.limits.changeable_required
    def has_feature(self, offer): return offer.fare.changeable


class RefundableRequiredConstraint(RequiredFeatureConstraint):
    name = "refundable"

    def required(self, request): return request.profile.limits.refundable_required
    def has_feature(self, offer): return offer.fare.refundable


DEFAULT_CONSTRAINTS: tuple[Constraint, ...] = (
    DestinationConstraint(),
    TravelWindowConstraint(),
    SeatsAvailableConstraint(),
    MaxBudgetConstraint(),
    MaxTransfersConstraint(),
    MaxDurationConstraint(),
    ChangeableRequiredConstraint(),
    RefundableRequiredConstraint(),
)



@dataclass
class RemovedOffer:
    offer: Offer
    failed: list[Constraint]
    reasons: list[str]

    @property
    def reason(self) -> str:
        return self.reasons[0]


@dataclass
class FilterResult:
    kept: list[Offer] = field(default_factory=list)
    removed: list[RemovedOffer] = field(default_factory=list)
    sold_out: list[Offer] = field(default_factory=list)
    not_matching: int = 0
    active: list[str] = field(default_factory=list)

    @property
    def matching(self) -> int:
        return len(self.kept) + len(self.removed) + len(self.sold_out)

    def removed_counts(self) -> Counter:
        return Counter(item.failed[0].name for item in self.removed)

    def most_restrictive(self) -> tuple[str, int] | None:
        counts = Counter(c.name for item in self.removed for c in item.failed)
        return counts.most_common(1)[0] if counts else None

    def summary(self) -> str:
        parts = [f"{self.matching} matching offers"]
        if self.sold_out:
            parts.append(f"{len(self.sold_out)} sold out")
        if self.removed:
            details = ", ".join(f"{n} {name}" for name, n in self.removed_counts().most_common())
            parts.append(f"{len(self.removed)} removed by your limits ({details})")
        parts.append(f"{len(self.kept)} ranked")
        return "; ".join(parts)


class OfferFilter:

    def __init__(self, constraints: tuple[Constraint, ...] = DEFAULT_CONSTRAINTS) -> None:
        self.constraints = constraints

    def apply(self, offers: list[Offer], request: TravelRequest) -> FilterResult:
        active = [c for c in self.constraints if c.is_active(request)]
        layer_a = [c for c in active if c.layer == "A"]
        layer_b = [c for c in active if c.layer == "B"]
        result = FilterResult(active=[c.describe(request) for c in active])

        for offer in offers:
            failed_a = next((c for c in layer_a if not c.check(offer, request)), None)
            if failed_a is not None:
                if failed_a.outcome == "sold_out":
                    result.sold_out.append(offer)
                else:
                    result.not_matching += 1
                continue

            failed_b = [c for c in layer_b if not c.check(offer, request)]
            if failed_b:
                reasons = [c.failure_reason(offer, request) for c in failed_b]
                result.removed.append(RemovedOffer(offer, failed_b, reasons))
            else:
                result.kept.append(offer)

        logger.info("Filter for %s, %s: %s", request.profile.key, request.destination.name,
                    result.summary())
        return result