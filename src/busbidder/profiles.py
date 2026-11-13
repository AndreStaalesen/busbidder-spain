import json
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from busbidder.criteria import CRITERIA, DEPARTURE_WINDOWS
from busbidder.exceptions import ConfigError, InvalidWeightsError, ProfileNotFoundError
from busbidder.models import Destination
from busbidder.validation import normalise_name

WEIGHT_TOTAL = 100



def validate_weights(weights: dict[str, float]) -> dict[str, float]:
    unknown = sorted(set(weights) - set(CRITERIA))
    if unknown:
        raise InvalidWeightsError(
            f"Unknown criteria: {', '.join(unknown)}. Known criteria: {', '.join(sorted(CRITERIA))}")

    for name, value in weights.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise InvalidWeightsError(f"Weight for {name} must be a number, got {value!r}")
        if value < 0:
            raise InvalidWeightsError(f"Weight for {name} must not be negative, got {value}")

    total = sum(weights.values())
    if not math.isclose(total, WEIGHT_TOTAL, abs_tol=1e-9):
        raise InvalidWeightsError(f"Weights total {total:g}%, but must total exactly {WEIGHT_TOTAL}%")

    return {name: float(weights.get(name, 0)) for name in CRITERIA}



@dataclass(frozen=True)
class Limits:
    max_price_eur: float | None = None
    max_transfers: int | None = None
    max_duration_minutes: int | None = None
    changeable_required: bool = False
    refundable_required: bool = False

    def __post_init__(self) -> None:
        for name in ("max_price_eur", "max_transfers", "max_duration_minutes"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"Limit {name} must be a number, got {value!r}")
            if value < 0 or (name != "max_transfers" and value == 0):
                raise ConfigError(f"Limit {name} must be greater than 0, got {value}")
        if self.max_transfers is not None and not isinstance(self.max_transfers, int):
            raise ConfigError(f"Limit max_transfers must be a whole number, got {self.max_transfers!r}")
        for name in ("changeable_required", "refundable_required"):
            if not isinstance(getattr(self, name), bool):
                raise ConfigError(f"Limit {name} must be true or false, got {getattr(self, name)!r}")



@dataclass(frozen=True)
class TravellerProfile:

    key: str
    name: str
    departure_window: str
    weights: dict[str, float]
    limits: Limits = field(default_factory=Limits)
    description: str = ""

    def __post_init__(self) -> None:
        if self.departure_window not in DEPARTURE_WINDOWS:
            raise ConfigError(f"Profile {self.key!r}: unknown departure window "
                              f"{self.departure_window!r}; choose from {', '.join(DEPARTURE_WINDOWS)}")
        object.__setattr__(self, "weights", validate_weights(self.weights))


@dataclass(frozen=True)
class TravelRequest:
    profile: TravellerProfile
    destination: Destination
    earliest_date: date
    latest_date: date

    def __post_init__(self) -> None:
        if self.latest_date < self.earliest_date:
            raise ConfigError(f"Latest date {self.latest_date} is before earliest date {self.earliest_date}")


LIMIT_KEYS = set(Limits.__dataclass_fields__)


def profile_from_dict(key: str, data: dict) -> TravellerProfile:
    if not isinstance(data, dict):
        raise ConfigError(f"Profile {key!r} must be a JSON object")
    missing = [name for name in ("name", "departure_window", "weights") if name not in data]
    if missing:
        raise ConfigError(f"Profile {key!r} is missing: {', '.join(missing)}")

    limits_data = data.get("limits", {})
    unknown = sorted(set(limits_data) - LIMIT_KEYS)
    if unknown:
        raise ConfigError(f"Profile {key!r} has unknown limit(s): {', '.join(unknown)}. "
                          f"Known limits: {', '.join(sorted(LIMIT_KEYS))}")
    try:
        return TravellerProfile(
            key=key,
            name=data["name"],
            description=data.get("description", ""),
            departure_window=data["departure_window"],
            weights=data["weights"],
            limits=Limits(**limits_data),
        )
    except ConfigError as error:
        raise type(error)(f"Profile {key!r}: {error}") from None


def load_profiles(path: Path) -> dict[str, TravellerProfile]:
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except OSError as error:
        raise ConfigError(f"Cannot read {path}: {error.strerror}") from error
    except json.JSONDecodeError as error:
        raise ConfigError(f"{path.name} is not valid JSON (line {error.lineno}): {error.msg}") from error

    if not isinstance(data, dict) or not data:
        raise ConfigError(f"{path.name} must contain at least one profile")
    return {key: profile_from_dict(key, value) for key, value in data.items()}


def get_profile(profiles: dict[str, TravellerProfile], key: str) -> TravellerProfile:
    try:
        return profiles[key.strip().lower()]
    except KeyError:
        raise ProfileNotFoundError(
            f"No profile called {key!r}. Available: {', '.join(profiles)}") from None


def find_destination(destinations: dict[str, Destination], text: str) -> Destination:
    wanted = normalise_name(text)
    for destination in destinations.values():
        if wanted in (normalise_name(destination.name), destination.code.lower()):
            return destination
    names = ", ".join(sorted(d.name for d in destinations.values()))
    raise ConfigError(f"Unknown destination {text!r}. Destinations from Madrid: {names}")