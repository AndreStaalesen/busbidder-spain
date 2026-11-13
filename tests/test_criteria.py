from datetime import datetime, timedelta
from pathlib import Path

import pytest

from busbidder.criteria import (
    CRITERIA,
    Criterion,
    DepartureCriterion,
    DurationCriterion,
    EmissionsCriterion,
    FlexibilityCriterion,
    PriceCriterion,
    RatioCriterion,
    ScoringContext,
    create_criterion,
    minutes_outside_window,
    register_criterion,
)
from busbidder.models import Company, Destination, FareConditions, Offer
from busbidder.validation import load_offers

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def make_offer(offer_id="SOL-MAL-001", price=30.0, minutes=480, departure="09:00",
               changeable=False, refundable=False, co2=15.0) -> Offer:
    start = datetime.fromisoformat(f"2027-07-12T{departure}")
    return Offer(
        offer_id=offer_id,
        company=Company("SOL", "SolRuta", ""),
        destination=Destination("MAL", "Malaga", 530, True),
        departure=start,
        arrival=start + timedelta(minutes=minutes),
        price_eur=price,
        transfers=0,
        fare=FareConditions(changeable, refundable, 1),
        seats_available=10,
        rating=4.0,
        co2_kg=co2,
    )


def context(*offers, window="morning") -> ScoringContext:
    return ScoringContext(offers=tuple(offers), departure_window=window)


def test_all_five_criteria_are_registered_by_name():
    assert set(CRITERIA) == {"price", "duration", "departure", "flexibility", "emissions"}


def test_decorator_sets_the_name_on_the_class():
    assert PriceCriterion.name == "price"
    assert CRITERIA["emissions"] is EmissionsCriterion


def test_create_criterion_returns_a_new_instance():
    criterion = create_criterion("duration")
    assert isinstance(criterion, DurationCriterion)


def test_unknown_criterion_name_raises_key_error():
    with pytest.raises(KeyError):
        create_criterion("prise")


def test_registering_a_name_twice_is_refused():
    with pytest.raises(ValueError, match="already registered"):
        @register_criterion("price")
        class AnotherPrice(PriceCriterion):
            pass


def test_decorator_refuses_classes_that_are_not_criteria():
    with pytest.raises(TypeError):
        @register_criterion("not_a_criterion")
        class Something:
            pass
    assert "not_a_criterion" not in CRITERIA


def test_new_criterion_can_be_added_without_changing_existing_code():
    try:
        @register_criterion("rating")
        class RatingCriterion(Criterion):
            def score(self, offer, context):
                return offer.rating * 20

        assert create_criterion("rating").score(make_offer(), context()) == 80
    finally:
        CRITERIA.pop("rating", None)



def test_abstract_criterion_cannot_be_created():
    with pytest.raises(TypeError):
        Criterion()


def test_subclass_without_score_cannot_be_created():
    class Incomplete(Criterion):
        pass
    with pytest.raises(TypeError):
        Incomplete()


def test_ratio_criterion_without_value_cannot_be_created():
    class Incomplete(RatioCriterion):
        pass
    with pytest.raises(TypeError):
        Incomplete()



def test_cheapest_offer_scores_100_and_double_price_scores_50():
    cheap, double = make_offer("A", price=20), make_offer("B", price=40)
    ctx = context(cheap, double)
    assert PriceCriterion().score(cheap, ctx) == 100
    assert PriceCriterion().score(double, ctx) == 50


def test_small_price_difference_gives_small_score_difference():
    a, b = make_offer("A", price=30), make_offer("B", price=31)
    ctx = context(a, b)
    assert PriceCriterion().score(a, ctx) == 100
    assert PriceCriterion().score(b, ctx) == pytest.approx(96.77, abs=0.01)


def test_one_extreme_price_does_not_squeeze_the_other_scores():
    offers = [make_offer(str(p), price=p) for p in (30, 35, 40, 120)]
    ctx = context(*offers)
    scores = [PriceCriterion().score(o, ctx) for o in offers]
    assert scores == pytest.approx([100, 85.71, 75, 25], abs=0.01)


def test_only_offer_scores_100():
    offer = make_offer()
    assert PriceCriterion().score(offer, context(offer)) == 100


def test_equal_prices_score_equally():
    a, b = make_offer("A", price=30), make_offer("B", price=30)
    ctx = context(a, b)
    assert PriceCriterion().score(a, ctx) == PriceCriterion().score(b, ctx) == 100


def test_shortest_journey_scores_100():
    fast, slow = make_offer("A", minutes=300), make_offer("B", minutes=600)
    ctx = context(fast, slow)
    assert DurationCriterion().score(fast, ctx) == 100
    assert DurationCriterion().score(slow, ctx) == 50



def test_lowest_emissions_score_100():
    clean, dirty = make_offer("A", co2=8), make_offer("B", co2=16)
    ctx = context(clean, dirty)
    assert EmissionsCriterion().score(clean, ctx) == 100
    assert EmissionsCriterion().score(dirty, ctx) == 50


def test_missing_emissions_get_the_median_score_of_reported_offers():
    reported = [make_offer("A", co2=10), make_offer("B", co2=20), make_offer("C", co2=40)]
    missing = make_offer("D", co2=None)
    ctx = context(*reported, missing)
    assert EmissionsCriterion().score(missing, ctx) == 50


def test_median_of_an_even_number_of_scores_is_the_average_of_the_middle_two():
    reported = [make_offer("A", co2=10), make_offer("B", co2=20)]
    missing = make_offer("C", co2=None)
    assert EmissionsCriterion().score(missing, context(*reported, missing)) == 75


def test_missing_values_do_not_count_when_finding_the_best():
    reported, missing = make_offer("A", co2=20), make_offer("B", co2=None)
    assert EmissionsCriterion().score(reported, context(reported, missing)) == 100


def test_neutral_score_when_no_offer_reports_emissions():
    a, b = make_offer("A", co2=None), make_offer("B", co2=None)
    ctx = context(a, b)
    assert EmissionsCriterion().score(a, ctx) == EmissionsCriterion().score(b, ctx) == 50


def test_price_cannot_be_missing():
    offer = make_offer(price=None)
    with pytest.raises(ValueError):
        PriceCriterion().score(offer, context(offer))



@pytest.mark.parametrize("time, window, expected", [
    ("09:00", "morning", 100),
    ("06:00", "morning", 100),
    ("12:00", "morning", 100),
    ("13:00", "morning", 83.33),
    ("15:00", "morning", 50),
    ("18:00", "morning", 0),
    ("23:00", "morning", 0),
    ("05:00", "morning", 83.33),
    ("14:00", "afternoon", 100),
    ("10:00", "afternoon", 66.67),
    ("22:00", "evening", 100),
    ("02:00", "evening", 100),
    ("07:00", "evening", 83.33),
    ("17:00", "evening", 83.33),
])
def test_departure_score_falls_by_distance_from_the_window(time, window, expected):
    offer = make_offer(departure=time)
    score = DepartureCriterion().score(offer, context(offer, window=window))
    assert score == pytest.approx(expected, abs=0.01)


def test_distance_is_measured_around_midnight():
    assert minutes_outside_window(datetime(2027, 7, 12, 23, 0), "morning") == 7 * 60
    assert minutes_outside_window(datetime(2027, 7, 12, 1, 0), "afternoon") == 7 * 60


def test_unknown_departure_window_raises():
    with pytest.raises(ValueError, match="Unknown departure window"):
        minutes_outside_window(datetime(2027, 7, 12, 9, 0), "night")


@pytest.mark.parametrize("changeable, refundable, expected", [
    (False, False, 0), (True, False, 60), (False, True, 40), (True, True, 100),
])
def test_flexibility_points(changeable, refundable, expected):
    offer = make_offer(changeable=changeable, refundable=refundable)
    assert FlexibilityCriterion().score(offer, context(offer)) == expected



def test_every_criterion_scores_real_malaga_offers_between_0_and_100():
    report = load_offers(DATA_DIR / "offers.csv", DATA_DIR / "companies.csv",
                         DATA_DIR / "destinations.csv")
    malaga = tuple(o for o in report.offers if o.destination.code == "MAL")
    ctx = ScoringContext(offers=malaga, departure_window="morning")
    for name in CRITERIA:
        criterion = create_criterion(name)
        for offer in malaga:
            assert 0 <= criterion.score(offer, ctx) <= 100, (name, offer.offer_id)