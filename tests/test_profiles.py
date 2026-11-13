import json
from datetime import date
from pathlib import Path

import pytest

from busbidder.exceptions import ConfigError, InvalidWeightsError, ProfileNotFoundError
from busbidder.models import Destination
from busbidder.profiles import (
    Limits,
    TravellerProfile,
    TravelRequest,
    find_destination,
    get_profile,
    load_profiles,
    validate_weights,
)
from busbidder.validation import load_destinations

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WEIGHTS = {"price": 35, "duration": 25, "departure": 15, "flexibility": 15, "emissions": 10}
MALAGA = Destination("MAL", "Malaga", 530, True)


def make_profile(**changes) -> TravellerProfile:
    values = {"key": "test", "name": "Test", "departure_window": "morning",
              "weights": DEFAULT_WEIGHTS}
    values.update(changes)
    return TravellerProfile(**values)


def write_profiles(folder: Path, content) -> Path:
    path = folder / "profiles.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return path



def test_valid_weights_are_accepted_as_floats():
    assert validate_weights(DEFAULT_WEIGHTS) == {k: float(v) for k, v in DEFAULT_WEIGHTS.items()}


def test_criteria_left_out_get_weight_zero():
    weights = validate_weights({"price": 60, "duration": 40})
    assert weights["emissions"] == 0 and weights["flexibility"] == 0
    assert set(weights) == set(DEFAULT_WEIGHTS)


def test_one_criterion_may_have_all_the_weight():
    assert validate_weights({"price": 100})["price"] == 100


def test_decimal_weights_that_total_100_are_accepted():
    validate_weights({"price": 33.3, "duration": 33.3, "departure": 33.4})


@pytest.mark.parametrize("weights, message", [
    ({"price": 60, "duration": 30}, "total 90%"),
    ({"price": 60, "duration": 50}, "total 110%"),
    ({"price": 110, "duration": -10}, "must not be negative"),
    ({"prise": 100}, "Unknown criteria: prise"),
    ({"price": "100"}, "must be a number"),
    ({"price": True}, "must be a number"),
    ({"price": float("nan")}, "must be a number"),
    ({}, "total 0%"),
])
def test_invalid_weights_are_rejected_not_rescaled(weights, message):
    with pytest.raises(InvalidWeightsError, match=message):
        validate_weights(weights)


def test_error_for_unknown_criterion_lists_the_known_ones():
    with pytest.raises(InvalidWeightsError, match="departure, duration, emissions, flexibility, price"):
        validate_weights({"speed": 100})



def test_no_limits_by_default():
    limits = Limits()
    assert limits.max_price_eur is None and limits.changeable_required is False


def test_zero_transfers_is_a_valid_limit():
    assert Limits(max_transfers=0).max_transfers == 0


@pytest.mark.parametrize("changes", [
    {"max_price_eur": 0}, {"max_price_eur": -5}, {"max_price_eur": "40"},
    {"max_transfers": -1}, {"max_transfers": 1.5}, {"max_duration_minutes": 0},
    {"changeable_required": "yes"},
])
def test_invalid_limits_are_rejected(changes):
    with pytest.raises(ConfigError):
        Limits(**changes)



def test_profile_completes_its_weights_on_creation():
    profile = make_profile(weights={"price": 100})
    assert profile.weights["duration"] == 0


def test_profile_with_invalid_weights_cannot_be_created():
    with pytest.raises(InvalidWeightsError):
        make_profile(weights={"price": 50})


def test_profile_with_unknown_departure_window_cannot_be_created():
    with pytest.raises(ConfigError, match="unknown departure window"):
        make_profile(departure_window="night")



def test_single_day_request_is_valid():
    request = TravelRequest(make_profile(), MALAGA, date(2027, 7, 12), date(2027, 7, 12))
    assert request.earliest_date == request.latest_date


def test_request_with_dates_in_the_wrong_order_is_rejected():
    with pytest.raises(ConfigError, match="before earliest date"):
        TravelRequest(make_profile(), MALAGA, date(2027, 7, 14), date(2027, 7, 12))



def test_real_profiles_file_loads_four_profiles():
    profiles = load_profiles(ROOT / "config" / "profiles.json")
    assert list(profiles) == ["budget", "business", "flexible", "eco"]
    assert profiles["budget"].limits.max_price_eur == 40
    assert profiles["business"].limits == Limits(max_transfers=0, max_duration_minutes=420,
                                                 changeable_required=True)
    assert profiles["flexible"].departure_window == "afternoon"
    assert profiles["eco"].weights["emissions"] == 45


def test_profile_without_limits_has_no_limits(tmp_path):
    path = write_profiles(tmp_path, {"plain": {"name": "Plain", "departure_window": "evening",
                                               "weights": {"price": 100}}})
    assert load_profiles(path)["plain"].limits == Limits()


def test_misspelled_limit_is_rejected_instead_of_ignored(tmp_path):
    path = write_profiles(tmp_path, {"p": {"name": "P", "departure_window": "morning",
                                           "weights": {"price": 100},
                                           "limits": {"max_prize_eur": 40}}})
    with pytest.raises(ConfigError, match="unknown limit\\(s\\): max_prize_eur"):
        load_profiles(path)


def test_error_names_the_profile_that_is_wrong(tmp_path):
    path = write_profiles(tmp_path, {"ok": {"name": "OK", "departure_window": "morning",
                                            "weights": {"price": 100}},
                                     "broken": {"name": "B", "departure_window": "morning",
                                                "weights": {"price": 90}}})
    with pytest.raises(InvalidWeightsError, match="Profile 'broken'"):
        load_profiles(path)


def test_profile_missing_required_keys_is_rejected(tmp_path):
    path = write_profiles(tmp_path, {"p": {"name": "P"}})
    with pytest.raises(ConfigError, match="missing: departure_window, weights"):
        load_profiles(path)


def test_invalid_json_reports_the_line(tmp_path):
    path = write_profiles(tmp_path, '{\n  "budget": {\n    "name": "Budget",\n  }\n}')
    with pytest.raises(ConfigError, match=r"not valid JSON \(line [34]\)"):
        load_profiles(path)


def test_empty_profiles_file_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="at least one profile"):
        load_profiles(write_profiles(tmp_path, {}))


def test_missing_profiles_file_raises_config_error(tmp_path):
    with pytest.raises(ConfigError, match="Cannot read"):
        load_profiles(tmp_path / "missing.json")



def test_get_profile_ignores_case_and_spaces():
    profiles = load_profiles(ROOT / "config" / "profiles.json")
    assert get_profile(profiles, " Budget ").key == "budget"


def test_unknown_profile_lists_the_available_ones():
    profiles = load_profiles(ROOT / "config" / "profiles.json")
    with pytest.raises(ProfileNotFoundError, match="budget, business, flexible, eco"):
        get_profile(profiles, "student")


@pytest.mark.parametrize("text", ["Malaga", "malaga", " MÁLAGA ", "MAL", "mal"])
def test_destination_can_be_found_by_name_or_code(text):
    destinations = load_destinations(ROOT / "data" / "destinations.csv")
    assert find_destination(destinations, text).code == "MAL"


def test_unknown_destination_lists_the_valid_ones():
    destinations = load_destinations(ROOT / "data" / "destinations.csv")
    with pytest.raises(ConfigError, match="Barcelona, Bilbao, Cadiz"):
        find_destination(destinations, "Paris")