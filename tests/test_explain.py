from datetime import date, datetime, timedelta

from busbidder.explain import DISCLAIMER, Explainer, plural
from busbidder.models import Company, Destination, FareConditions, Offer
from busbidder.profiles import TravellerProfile, TravelRequest
from busbidder.ranking import Ranker

MALAGA = Destination("MAL", "Malaga", 530, True)


def make_offer(offer_id="SOL-MAL-001", price=30.0, minutes=480, departure="09:00",
               changeable=False, refundable=False, co2=15.0, seats=10, transfers=0) -> Offer:
    start = datetime.fromisoformat(f"2027-07-12T{departure}")
    return Offer(offer_id, Company(offer_id[:3], f"Company {offer_id[:3]}", ""), MALAGA, start,
                 start + timedelta(minutes=minutes), price, transfers,
                 FareConditions(changeable, refundable, 1), seats, 4.0, co2)


def explain(offers, weights, window="morning"):
    profile = TravellerProfile(key="test", name="Test", departure_window=window, weights=weights)
    request = TravelRequest(profile, MALAGA, date(2027, 7, 12), date(2027, 7, 14))
    ranked = Ranker().rank(offers, request)
    return {e.offer_id: e for e in Explainer(ranked, request).explain_all()}



def test_strengths_and_weaknesses_come_from_the_data():
    cheap_slow = make_offer("AAA-MAL-001", price=20, minutes=600)
    pricey_fast = make_offer("BBB-MAL-001", price=40, minutes=300)
    result = explain([cheap_slow, pricey_fast], {"price": 50, "duration": 50})

    assert result["AAA-MAL-001"].strengths == ["Cheapest offer (EUR 20.00)"]
    assert result["AAA-MAL-001"].weaknesses == ["Journey 10h 00m (fastest: 5h 00m)"]
    assert result["BBB-MAL-001"].strengths == ["Fastest journey (5h 00m)"]
    assert result["BBB-MAL-001"].weaknesses == ["Price EUR 40.00 (cheapest: EUR 20.00)"]


def test_criteria_with_weight_zero_are_never_mentioned():
    result = explain([make_offer("A", minutes=300), make_offer("B", minutes=900)], {"price": 100})
    for explanation in result.values():
        assert not any("Journey" in s for s in explanation.strengths + explanation.weaknesses)


def test_strengths_are_ordered_by_points_contributed():
    offer = make_offer(changeable=True, refundable=True)
    result = explain([offer], {"price": 20, "flexibility": 80})
    assert result["SOL-MAL-001"].strengths[0] == "Ticket can be changed and refunded"


def test_departure_is_described_relative_to_the_window():
    inside = make_offer("A", departure="09:00")
    outside = make_offer("B", departure="16:00")
    result = explain([inside, outside], {"departure": 100})
    assert result["A"].strengths == ["Departs 09:00, inside your morning window (06:00-12:00)"]
    assert result["B"].weaknesses == ["Departs 16:00, 4h 00m outside your morning window (06:00-12:00)"]


def test_flexibility_wording():
    fixed = make_offer("A")
    result = explain([fixed], {"flexibility": 100})
    assert result["A"].weaknesses == ["Ticket can be neither changed nor refunded"]


def test_middle_option_gets_a_note_instead_of_empty_lists():
    fast = make_offer("A", minutes=350)
    middle = make_offer("B", minutes=500)
    result = explain([fast, middle], {"duration": 100})
    assert result["B"].strengths == [] and result["B"].weaknesses == []
    assert result["B"].notes[0].startswith("No clear strengths or weaknesses")




def test_estimated_emissions_are_never_claimed_as_a_strength():
    reported = [make_offer("A", co2=10), make_offer("B", co2=11)]
    missing = make_offer("C", co2=None)
    result = explain(reported + [missing], {"emissions": 100})
    assert result["C"].strengths == [] and result["C"].weaknesses == []
    assert any("not reported" in note for note in result["C"].notes)


def test_no_estimate_note_when_emissions_have_no_weight():
    result = explain([make_offer("A", co2=None)], {"price": 100})
    assert not any("not reported" in note for note in result["A"].notes)





def test_top_offer_is_called_best_match_not_best():
    result = explain([make_offer("A", price=20), make_offer("B", price=40)], {"price": 100})
    assert result["A"].comparison == "Best match for your preferences, 50.0 points ahead of #2 B."


def test_other_offers_name_the_main_reason_they_are_behind():
    result = explain([make_offer("A", price=20, minutes=480), make_offer("B", price=40, minutes=480)],
                     {"price": 60, "duration": 40})
    assert result["B"].comparison == "30.0 points behind #1 A, mainly because of price (30.0 points)."


def test_single_offer_comparison():
    result = explain([make_offer("A")], {"price": 100})
    assert result["A"].comparison == "The only offer that meets your requirements."


def test_disclaimer_says_the_ranking_is_not_objective():
    assert "not an objectively best offer" in DISCLAIMER






def test_notes_warn_about_few_seats_and_transfers():
    result = explain([make_offer("A", seats=1, transfers=2)], {"price": 100})
    assert "Only 1 seat left." in result["A"].notes
    assert "2 transfers on the way." in result["A"].notes


def test_tie_is_explained_in_the_notes():
    result = explain([make_offer("A", price=40), make_offer("B", price=30)], {"departure": 100})
    assert any(note.startswith("Tie: same score as B") for note in result["A"].notes)


def test_headline_shows_rank_company_times_price_and_score():
    result = explain([make_offer("SOL-MAL-001", price=29.5, departure="23:00", minutes=600)],
                     {"price": 100})
    assert result["SOL-MAL-001"].headline == (
        "#1 SOL-MAL-001  Company SOL  Mon 12 Jul 23:00 -> 09:00 (+1 day)  "
        "EUR 29.50  score 100.0/100")


def test_plural():
    assert plural(1, "seat") == "1 seat"
    assert plural(3, "seat") == "3 seats"