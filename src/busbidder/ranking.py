import logging
from dataclasses import dataclass

from busbidder.criteria import CRITERIA, Criterion, ScoringContext, create_criterion
from busbidder.models import Offer
from busbidder.profiles import TravelRequest

logger = logging.getLogger(__name__)

TOTAL_DECIMALS = 2


@dataclass(frozen=True)
class CriterionScore:
    name: str
    score: float
    weight: float
    estimated: bool

    @property
    def points(self) -> float:
        return self.score * self.weight / 100

    @property
    def points_lost(self) -> float:
        return (100 - self.score) * self.weight / 100


@dataclass(frozen=True)
class RankedOffer:
    rank: int
    offer: Offer
    total: float
    scores: dict[str, CriterionScore]
    tie_break: str | None = None

    @property
    def offer_id(self) -> str:
        return self.offer.offer_id


def sort_key(item: tuple[float, Offer]):
    total, offer = item
    return (-total, offer.price_eur, offer.departure, offer.offer_id)


def tie_break_reason(offer: Offer, above: Offer) -> str:
    if offer.price_eur != above.price_eur:
        return f"same score as {above.offer_id}; placed below it because it costs more"
    if offer.departure != above.departure:
        return f"same score and price as {above.offer_id}; placed below it because it departs later"
    return f"same score, price and departure as {above.offer_id}; ordered by offer ID"


class Ranker:
    def __init__(self, criteria: list[Criterion] | None = None) -> None:
        self.criteria = criteria if criteria is not None else [create_criterion(n) for n in CRITERIA]

    def score_offer(self, offer: Offer, context: ScoringContext,
                    weights: dict[str, float]) -> dict[str, CriterionScore]:
        scores = {}
        for criterion in self.criteria:
            estimated = criterion.name == "emissions" and offer.co2_kg is None
            scores[criterion.name] = CriterionScore(
                name=criterion.name,
                score=criterion.score(offer, context),
                weight=weights.get(criterion.name, 0.0),
                estimated=estimated,
            )
        return scores

    def rank(self, offers: list[Offer], request: TravelRequest) -> list[RankedOffer]:
        if not offers:
            return []

        weights = request.profile.weights
        context = ScoringContext(offers=tuple(offers), departure_window=request.profile.departure_window)

        scored = []
        for offer in offers:
            scores = self.score_offer(offer, context, weights)
            total = round(sum(s.points for s in scores.values()), TOTAL_DECIMALS)
            scored.append((total, offer, scores))

        scored.sort(key=lambda item: sort_key((item[0], item[1])))

        ranked = []
        for position, (total, offer, scores) in enumerate(scored, start=1):
            tie = None
            if ranked and ranked[-1].total == total:
                tie = tie_break_reason(offer, ranked[-1].offer)
            ranked.append(RankedOffer(position, offer, total, scores, tie))

        logger.info("Ranked %d offers for %s; top: %s (%.2f)", len(ranked),
                    request.profile.key, ranked[0].offer_id, ranked[0].total)
        return ranked