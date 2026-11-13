"""후보 추리기와 수량·금액 계산 (docs/PRD.md 7.1절의 1단계, docs/FORMATS.md 3절·9절).

LLM 에 맡기지 않는 것을 여기서 정한다: 갈 수 있는 업장, 주문할 수 있는 상품, 수량, 금액.
프로모션은 아직 넣지 않는다 (T10). 그래서 할인은 늘 0 이고 후보의 `promotions` 는 비어 있다.
"""

import math
from typing import Any

from engine.formats.choice import Addon, Candidate, ChoiceRequest, Line, Option, RequestVocab, RunCondition
from engine.formats.conditions import Condition
from engine.formats.evidence import Vocab
from engine.formats.money import to_paid_price
from engine.formats.persona import Persona
from engine.formats.venue import Product, Venue

ALL_MONTHS = frozenset(range(1, 13))


def months_sold(venue: Venue, product: Product) -> frozenset[int]:
    """이 상품을 파는 달. 상품에 적혀 있지 않으면 업장이 영업하는 달이다."""
    return frozenset(product.months or venue.months or ALL_MONTHS)


def run_condition(condition: Condition, persona: Persona) -> RunCondition:
    """묶음의 조건에 페르소나의 인원과 예산을 붙인다 (묶음의 조건에는 인원과 예산이 없다)."""
    return RunCondition(
        **condition.model_dump(),
        adults=persona.visit.party.adults,
        children=persona.visit.party.children,
        budget=persona.budget,
        purpose=None,
        party=None,
    )


def is_open(venue: Venue, condition: RunCondition) -> bool:
    """그 끼니, 그 요일에 영업하는가. 영업 시간을 모르는 업장(`hours` 가 null)은 검사를 건너뛴다."""
    if venue.hours is None:
        return True
    return any(h.meal == condition.meal and h.day_type in (condition.day_type, "all") for h in venue.hours)


def seats_party(venue: Venue, condition: RunCondition) -> bool:
    """일행의 수가 예약 조건의 인원 범위 안인가. 예약 조건을 모르면 건너뛴다."""
    reservation = venue.reservation
    if reservation is None:
        return True
    people = condition.adults + condition.children
    if reservation.party_min is not None and people < reservation.party_min:
        return False
    return reservation.party_max is None or people <= reservation.party_max


def products_on_sale(venue: Venue, condition: RunCondition) -> list[Product]:
    """이번 조건에서 살 수 있는 상품: 이용 상황, 파는 때, (조건에 달이 있으면) 파는 달이 맞는 것."""
    return [
        product
        for product in venue.products
        if product.occasion == condition.occasion
        and product.sold_at(condition.meal, condition.day_type)
        and (condition.month is None or condition.month in months_sold(venue, product))
    ]


def quantity_for(product: Product, adults: int, children: int) -> int:
    """수량 규칙으로 낸 수량 (docs/FORMATS.md 3절). `choice` 는 고객이 정하므로 여기서 내지 않는다."""
    people = {"adult": adults, "child": children, "all": adults + children}[product.audience]
    if product.qty_rule == "per_person":
        return people
    if product.qty_rule == "per_serves":
        return math.ceil(people / product.serves)
    raise ValueError(f"상품 '{product.product_id}' 의 수량은 고객이 정한다")


def _line(product: Product, quantity: int) -> Line:
    unit_price = to_paid_price(product.price, product.price_basis)
    return Line(
        product_id=product.product_id,
        name=product.name,
        unit=product.unit,
        quantity=quantity,
        unit_price=unit_price,
        discount=0,
        line_total=quantity * unit_price,
    )


def _orders(venue: Venue, mains: list[Product], condition: RunCondition) -> list[list[Line]]:
    """고를 수 있는 주문들. 주문 하나는 일행 모두의 몫을 담는다.

    - 구분 없는 가격(`all`)의 상품은 그 상품 하나가 주문 하나다.
    - 성인 가격과 어린이 가격이 따로면 한 주문에 두 줄로 넣는다. 조건에 달이 없으면 파는 달이 같은 것끼리만 짝짓는다
      (방문 하나의 몫은 하나여야 한다. docs/FORMATS.md 10.2절). 조건에 달이 있으면 그 달에 파는 것끼리라 그대로 짝짓는다.
    - 어린이 가격이 둘 이상이면 가격마다 주문이 따로 생긴다 (어린이 모두가 그 가격이다).
    - 어린이가 있는데 어린이 가격이 없는 성인 상품은 주문이 되지 못한다 (어린이의 몫을 낼 수 없다).
    """
    adults, children = condition.adults, condition.children
    orders: list[list[Line]] = []
    kids = [p for p in mains if p.audience == "child"]
    for product in mains:
        if product.audience == "all":
            orders.append([_line(product, quantity_for(product, adults, children))])
        elif product.audience == "adult":
            adult_line = _line(product, quantity_for(product, adults, children))
            if children == 0:
                orders.append([adult_line])
            for kid in kids:
                same_months = condition.month is not None or months_sold(venue, kid) == months_sold(venue, product)
                if children and same_months:
                    orders.append([adult_line, _line(kid, quantity_for(kid, adults, children))])
    return orders


def candidate_for(venue: Venue, condition: RunCondition) -> tuple[Candidate | None, list[str]]:
    """업장 하나를 규칙으로 걸러 후보로 만든다. 후보가 못 되면 None.

    함께 돌려주는 것은 가격이 비어 있어 뺀 상품이다 (`<venue_id>:<product_id>`. 실행 기록의 `skipped_products`).
    """
    if condition.occasion not in venue.occasions:
        return None, []
    if condition.month is not None and venue.months is not None and condition.month not in venue.months:
        return None, []
    if not is_open(venue, condition) or not seats_party(venue, condition):
        return None, []

    on_sale = products_on_sale(venue, condition)
    skipped = [f"{venue.venue_id}:{p.product_id}" for p in on_sale if p.price is None]
    priced = [p for p in on_sale if p.price is not None]
    limit = condition.budget_limit()

    # 번호는 예산으로 거르기 전에 매긴다. 같은 주문은 누가 와도 같은 번호를 갖고, 걸러진 번호는 비어 있을 수 있다.
    options = [
        Option(option_id=f"{venue.venue_id}-o{number}", lines=lines, total=sum(line.line_total for line in lines))
        for number, lines in enumerate(_orders(venue, [p for p in priced if p.qty_rule != "choice"], condition), 1)
    ]
    options = [option for option in options if option.total <= limit]

    # 수량 규칙이 있는 상품이 아예 없는 업장(포장·구매)은 추가 상품만으로 산다.
    # 그런 상품이 있는데 예산이나 가격 때문에 주문이 남지 않은 업장은 후보에서 뺀다. 음료만 사러 가는 곳이 아니다.
    addons_only = all(p.qty_rule == "choice" for p in on_sale)

    # 예산은 산 것 전부와 견주므로, 가장 싼 주문에 하나만 더해도 max 를 넘는 추가 상품은 넣지 않는다.
    cheapest = min((option.total for option in options), default=0)
    # 조건에 달이 없으면 방문의 몫은 고른 주문을 파는 달로 정해진다. 주문을 파는 달 가운데 팔지 않는 달이 있는
    # 추가 상품은 그 몫만큼 팔린 것으로 세면 부풀려지므로 넣지 않는다.
    by_id = {p.product_id: p for p in priced}
    order_months: frozenset[int] = frozenset()
    if condition.month is None:
        for option in options:
            for line in option.lines:
                order_months |= months_sold(venue, by_id[line.product_id])
    addons = [
        Addon(
            product_id=p.product_id,
            name=p.name,
            unit=p.unit,
            unit_price=to_paid_price(p.price, p.price_basis),
            qty_max=p.qty_max,
        )
        for p in priced
        if p.qty_rule == "choice"
        and cheapest + to_paid_price(p.price, p.price_basis) <= limit
        and order_months <= months_sold(venue, p)
    ]
    if not (addons if addons_only else options):
        return None, skipped
    candidate = Candidate(
        venue_id=venue.venue_id,
        name=venue.name,
        hotel=venue.hotel,
        is_competitor=venue.is_competitor,
        cuisine=venue.cuisine,
        options=options,
        addons=addons,
        promotions=[],
    )
    return candidate, skipped


def candidates_for(venues: list[Venue], condition: RunCondition) -> tuple[list[Candidate], list[str]]:
    """같은 이용 상황의 워커힐 업장과 그 경쟁 업장을 후보로 추린다 (docs/PRD.md 7.1절).

    경쟁 업장은 그 이용 상황이 있는 워커힐 업장과 견주는 곳만 본다. 순서는 워커힐 업장 먼저, 그 안에서는 `venue_id` 순이다.
    """
    ours = {v.venue_id for v in venues if not v.is_competitor and condition.occasion in v.occasions}
    candidates: list[Candidate] = []
    skipped: list[str] = []
    for venue in sorted(venues, key=lambda v: (v.is_competitor, v.venue_id)):
        if venue.is_competitor and not ours.intersection(venue.competes_with):
            continue
        candidate, missing = candidate_for(venue, condition)
        skipped.extend(missing)
        if candidate is not None:
            candidates.append(candidate)
    return candidates, skipped


def build_request(
    *,
    prompt_version: str,
    scenario_id: str,
    persona: dict[str, Any],
    condition: RunCondition,
    venues: list[Venue],
    vocab: Vocab,
) -> tuple[ChoiceRequest | None, list[str]]:
    """선택 요청을 만든다 (docs/FORMATS.md 9절). 후보가 하나도 없으면 요청은 None 이다.

    `persona` 는 요청에 그대로 들어갈 사전이다 (가상 예시로 돌릴 때는 공개 층, 기본 데이터로 돌릴 때는 두 층을 합친 것).
    """
    candidates, skipped = candidates_for(venues, condition)
    if not candidates:
        return None, skipped
    request = ChoiceRequest(
        prompt_version=prompt_version,
        scenario_id=scenario_id,
        persona=persona,
        condition=condition,
        candidates=candidates,
        allow_none=True,
        vocab=RequestVocab(reasons_chosen=vocab.reasons_chosen, pain_points=vocab.pain_points),
    )
    return request, skipped
