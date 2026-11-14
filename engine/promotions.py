"""프로모션을 금액에 넣는 규칙 (docs/FORMATS.md 3절).

할인은 엔진이 주문의 줄에 미리 넣는다. LLM 에 맡기지 않는다.
후보를 만드는 쪽(`engine/candidates.py`)과 받은 답의 금액을 다시 계산하는 쪽(`engine/ledger.py`)이 함께 쓴다.
"""

from engine.formats.choice import RunCondition
from engine.formats.money import apply_pct
from engine.formats.venue import Period, Promotion, Venue


def months_in(period: Period) -> frozenset[int]:
    """기간이 하루라도 걸치는 달. 방문 조건의 달에는 연도가 없어 달만 본다."""
    months: set[int] = set()
    year, month = period.from_.year, period.from_.month
    while (year, month) <= (period.to.year, period.to.month) and len(months) < 12:
        months.add(month)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return frozenset(months)


def meets_conditions(promotion: Promotion, condition: RunCondition) -> bool:
    """이번 방문 조건이 프로모션의 적용 조건에 드는가.

    - 조건에 값이 적혀 있는데 방문 조건의 그 값이 null 이거나 다르면 적용하지 않는다.
    - 기간은 방문 조건에 달이 있을 때만 견준다. 달이 없으면 기간을 보지 않는다.
    """
    wanted = promotion.conditions
    for key in ("day_type", "meal", "stay"):
        if getattr(wanted, key) is not None and getattr(wanted, key) != getattr(condition, key):
            return False
    if wanted.party_min is not None and condition.adults + condition.children < wanted.party_min:
        return False
    if promotion.period is not None and condition.month is not None:
        return condition.month in months_in(promotion.period)
    return True


def promotions_for(venue: Venue, condition: RunCondition) -> list[Promotion]:
    """그 업장에서 이번 방문 조건에 해당하는 프로모션. 순서는 업장 정의에 적힌 순서다."""
    return [promotion for promotion in venue.promotions if meets_conditions(promotion, condition)]


def covers(promotion: Promotion, product_id: str) -> bool:
    return promotion.applies_to is None or product_id in promotion.applies_to


def order_discounts(promotions: list[Promotion], lines: list[tuple[str, int]]) -> tuple[list[int], str | None]:
    """주문 하나의 줄마다 깎이는 금액과, 적용한 프로모션의 `promo_id` (없으면 None).

    `lines` 는 주문의 줄 순서대로 (`product_id`, 수량 × 단가) 다. `promotions` 는 조건에 해당하는 것만 준다.

    - `discount_pct`: 적용되는 상품의 줄마다 수량 × 단가 × 퍼센트를 깎는다 (줄마다 원 단위로 반올림한다).
    - `discount_amount`: 주문 한 번에 한 번만 깎는다. 적용되는 상품의 첫 줄에서 빼고, 그 줄의 금액보다 많이 깎지 않는다.
    - `gift`: 금액은 바뀌지 않는다.
    - 할인이 둘 이상 해당하면 깎이는 금액이 가장 큰 것 하나만 적용한다. 같으면 업장 정의에 먼저 적힌 것이다.
    """
    best: list[int] = [0] * len(lines)
    best_id: str | None = None
    for promotion in promotions:
        benefit = promotion.benefit
        if benefit.type == "gift":
            continue
        hit = [covers(promotion, product_id) for product_id, _ in lines]
        cuts = [0] * len(lines)
        if benefit.type == "discount_pct":
            cuts = [apply_pct(amount, benefit.value) if on else 0 for (_, amount), on in zip(lines, hit, strict=True)]
        elif True in hit:
            first = hit.index(True)
            cuts[first] = min(int(benefit.value), lines[first][1])
        if sum(cuts) > sum(best):
            best, best_id = cuts, promotion.promo_id
    return best, best_id
