import random
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from busbidder.constraints import OfferFilter
from busbidder.models import Company, Destination, FareConditions, Offer
from busbidder.profiles import TravellerProfile, TravelRequest, load_profiles
from busbidder.ranking import CriterionScore, Ranker
from busbidder.validation import load_offers

ROOT = Path(__file__).resolve().parent.parent
MALAGA = Destination("MAL", "Malaga", 530, True)


def make_offer(offer_id="SOL-MAL-001", price=30.0, minutes=480, departure="09:00",
               changeable=False, refundable=False, co2=15.0) -> Offer:
    start = datetime.fromisoformat(f"2027-07-12T{departure}")
    return Offer(offer_id, Company(offer_id[:3], offer_id[:3], ""), MALAGA, start,
                 start + timedelta(minutes=minutes), price, 0,
                 FareConditions(changeable, refundable, 1), 10, 4.0, co2)


def make_request(weights, window="morning") -> TravelRequest:
    profile = TravellerProfile(key="test", name="Test", departure_window=window, weights=weights)
    return TravelRequest(profile, MALAGA, date(2027, 7, 12), date(2027, 7, 14))



def test_criterion_points_are_score_times_weight():
    score = CriterionScore("price", score=80, weight=40, estimated=False)
    assert score.points == 32
    assert score.points_lost == 8


def test_total_is_the_weighted_sum_of_criterion_scores():
    cheap = make_offer("A", price=20, minutes=600)
    fast = make_offer("B", price=40, minutes=300)
    request = make_request({"price": 60, "duration": 40})

    ranked = Ranker().rank([cheap, fast], request)

    assert ranked[0].offer_id == "A" and ranked[0].total == 80.0
    assert ranked[1].offer_id == "B" and ranked[1].total == 70.0


def test_changing_the_weights_changes_the_order():
    cheap = make_offer("A", price=20, minutes=600)
    fast = make_offer("B", price=40, minutes=300)

    price_first = Ranker().rank([cheap, fast], make_request({"price": 60, "duration": 40}))
    time_first = Ranker().rank([cheap, fast], make_request({"price": 40, "duration": 60}))

    assert [r.offer_id for r in price_first] == ["A", "B"]
    assert [r.offer_id for r in time_first] == ["B", "A"]


def test_criterion_with_weight_zero_is_scored_but_adds_nothing():
    ranked = Ranker().rank([make_offer()], make_request({"price": 100}))
    assert ranked[0].scores["duration"].score == 100
    assert ranked[0].scores["duration"].points == 0
    assert ranked[0].total == 100


def test_every_offer_gets_a_score_for_every_criterion():
    ranked = Ranker().rank([make_offer()], make_request({"price": 100}))
    assert set(ranked[0].scores) == {"price", "duration", "departure", "flexibility", "emissions"}


def test_missing_emissions_are_marked_as_estimated():
    ranked = Ranker().rank([make_offer("A", co2=10), make_offer("B", co2=None)],
                           make_request({"emissions": 100}))
    estimated = {r.offer_id: r.scores["emissions"].estimated for r in ranked}
    assert estimated == {"A": False, "B": True}


def test_totals_are_rounded_to_two_decimals():
    ranked = Ranker().rank([make_offer("A", price=30), make_offer("B", price=31)],
                           make_request({"price": 100}))
    assert ranked[1].total == 96.77


def test_ranks_start_at_one():
    ranked = Ranker().rank([make_offer("A", price=30), make_offer("B", price=40)],
                           make_request({"price": 100}))
    assert [r.rank for r in ranked] == [1, 2]


def test_no_offers_gives_an_empty_ranking():
    assert Ranker().rank([], make_request({"price": 100})) == []


def test_single_offer_scores_100_on_ratio_criteria():
    ranked = Ranker().rank([make_offer()], make_request({"price": 50, "duration": 50}))
    assert ranked[0].total == 100



def test_tie_is_broken_by_lower_price():
    a = make_offer("A", price=40)
    b = make_offer("B", price=30)
    ranked = Ranker().rank([a, b], make_request({"departure": 100}))
    assert [r.offer_id for r in ranked] == ["B", "A"]
    assert ranked[0].tie_break is None
    assert "costs more" in ranked[1].tie_break


def test_tie_with_equal_price_is_broken_by_earlier_departure():
    a = make_offer("A", departure="11:00")
    b = make_offer("B", departure="08:00")
    ranked = Ranker().rank([a, b], make_request({"departure": 100}))
    assert [r.offer_id for r in ranked] == ["B", "A"]
    assert "departs later" in ranked[1].tie_break


def test_complete_tie_is_broken_by_offer_id():
    ranked = Ranker().rank([make_offer("B"), make_offer("A")], make_request({"departure": 100}))
    assert [r.offer_id for r in ranked] == ["A", "B"]
    assert "offer ID" in ranked[1].tie_break


def test_ranking_does_not_depend_on_input_order():
    report = load_offers(ROOT / "data" / "offers.csv", ROOT / "data" / "companies.csv",
                         ROOT / "data" / "destinations.csv")
    offers = [o for o in report.offers if o.destination.code == "MAL"]
    request = make_request({"price": 35, "duration": 25, "departure": 15,
                            "flexibility": 15, "emissions": 10})
    expected = [r.offer_id for r in Ranker().rank(offers, request)]

    for seed in range(5):
        shuffled = offers[:]
        random.Random(seed).shuffle(shuffled)
        assert [r.offer_id for r in Ranker().rank(shuffled, request)] == expected



@pytest.fixture(scope="module")
def malaga_rankings():
    report = load_offers(ROOT / "data" / "offers.csv", ROOT / "data" / "companies.csv",
                         ROOT / "data" / "destinations.csv")
    rankings = {}
    for key, profile in load_profiles(ROOT / "config" / "profiles.json").items():
        request = TravelRequest(profile, MALAGA, date(2027, 7, 12), date(2027, 7, 14))
        kept = OfferFilter().apply(report.offers, request).kept
        rankings[key] = Ranker().rank(kept, request)
    return rankings


@pytest.mark.parametrize("profile, winner", [
    ("budget", "SOL-MAL-003"),
    ("business", "COS-MAL-003"),
    ("flexible", "VER-MAL-003"),
    ("eco", "VER-MAL-002"),
])
def test_each_profile_gets_its_expected_top_offer(malaga_rankings, profile, winner):
    assert malaga_rankings[profile][0].offer_id == winner


def test_profiles_produce_different_rankings(malaga_rankings):
    winners = {ranking[0].offer_id for ranking in malaga_rankings.values()}
    assert len(winners) == 4


def test_all_totals_are_between_0_and_100(malaga_rankings):
    for ranking in malaga_rankings.values():
        for item in ranking:
            assert 0 <= item.total <= 100