"""소비 원장 (docs/FORMATS.md 10.2절).

응답을 받은 뒤의 일을 한다: 금액을 업장 정의로 다시 계산해 견주고(9절의 마지막 검사),
방문 하나를 원장의 줄로 바꾸고, 원장에서 합계를 낸다. 모든 합계는 원장에서만 낸다.
"""

from collections import defaultdict
from pathlib import Path
from typing import Any

from engine.candidates import months_sold, products_on_sale, quantity_for
from engine.formats.choice import ChoiceRequest, ChoiceResponse
from engine.formats.io import write_csv
from engine.formats.money import net_of_tax, round_half_up, to_paid_price, weighted_amount
from engine.formats.run import LEDGER_COLUMNS, SEASON_GAP_REASON, LedgerRow
from engine.formats.venue import Product, Venue

# 후보가 하나도 없어 엔진이 응답 없이 "이용하지 않음"으로 정한 방문의 reason_text.
NO_CANDIDATE_REASON = "후보가 없음"

# 합계를 내는 열.
TOTAL_KEYS = ("paid", "revenue_net", "weighted_revenue")


def _chosen_products(
    request: ChoiceRequest, response: ChoiceResponse, venue: Venue
) -> tuple[list[tuple[Product | None, Any]], list[tuple[Product | None, Any, int]]]:
    """고른 주문의 줄과 고른 추가 상품을 업장 정의의 상품과 짝지어 돌려준다. 정의에 없는 상품은 None 이다."""
    candidate = request.candidate(venue.venue_id)
    option = candidate.option(response.choice.option_id) if candidate else None
    lines = [(venue.product(line.product_id), line) for line in (option.lines if option else [])]
    offered = {addon.product_id: addon for addon in (candidate.addons if candidate else [])}
    extras = [
        (venue.product(picked.product_id), offered[picked.product_id], picked.quantity)
        for picked in response.choice.addons
        if picked.quantity > 0 and picked.product_id in offered
    ]
    return lines, extras


def _months_together(venue: Venue, products: list[Product]) -> frozenset[int]:
    """상품들을 모두 함께 파는 달."""
    months = frozenset(range(1, 13))
    for product in products:
        months &= months_sold(venue, product)
    return months


def _share(request: ChoiceRequest, venue: Venue, products: list[Product]) -> float:
    """방문을 그 업장의 것으로 세는 몫: 상품들을 모두 함께 파는 달 수 ÷ 12. 조건에 달이 있으면 1 이다.

    `products` 는 고른 주문의 상품이다. 주문 없이 추가 상품만 샀으면 산 추가 상품이다.
    """
    if request.condition.month is not None:
        return 1.0
    return len(_months_together(venue, products)) / 12


def amount_problems(request: ChoiceRequest, response: ChoiceResponse, venues: dict[str, Venue]) -> list[str]:
    """원장에 적을 금액을 업장 정의로 다시 계산해 요청의 금액과 견준다 (docs/FORMATS.md 9절의 마지막 검사).

    요청의 후보를 믿지 않고 업장 정의에서 다시 낸다: 그 상품이 있는지, 이번 조건에 파는지, 수량과 단가가 맞는지.
    `problems_in_response` 가 보는 것(후보에 있는 업장과 주문인지 등)은 다시 보지 않는다.
    """
    venue_id = response.choice.venue_id
    if venue_id is None:
        return []
    venue = venues.get(venue_id)
    if venue is None:
        return [f"고른 업장 '{venue_id}' 의 정의가 없다"]
    condition = request.condition
    on_sale = {p.product_id for p in products_on_sale(venue, condition)}
    lines, extras = _chosen_products(request, response, venue)
    problems: list[str] = []

    for product, line in lines:
        if product is None or product.product_id not in on_sale:
            problems.append(f"상품 '{line.product_id}' 는 업장 '{venue_id}' 가 이번 조건에 파는 상품이 아니다")
        elif product.qty_rule == "choice" or product.price is None:
            problems.append(f"상품 '{line.product_id}' 는 주문의 줄에 넣을 수 없다 (수량을 고객이 정하거나 가격이 없다)")
        else:
            if line.quantity != quantity_for(product, condition.adults, condition.children):
                problems.append(f"상품 '{line.product_id}' 의 수량이 수량 규칙으로 낸 값과 다르다")
            if line.unit_price != to_paid_price(product.price, product.price_basis):
                problems.append(f"상품 '{line.product_id}' 의 단가가 업장 정의의 가격과 다르다")
            if line.discount != 0:
                problems.append(f"상품 '{line.product_id}' 에 할인이 있다 (프로모션은 아직 넣지 않는다)")
    for product, addon, quantity in extras:
        if product is None or product.product_id not in on_sale or product.qty_rule != "choice":
            problems.append(f"추가 상품 '{addon.product_id}' 는 업장 '{venue_id}' 가 이번 조건에 파는 추가 상품이 아니다")
        elif product.price is None or addon.unit_price != to_paid_price(product.price, product.price_basis):
            problems.append(f"추가 상품 '{addon.product_id}' 의 단가가 업장 정의의 가격과 다르다")
        elif quantity > product.qty_max:
            problems.append(f"추가 상품 '{addon.product_id}' 의 수량이 업장 정의의 qty_max 를 넘는다")

    # 방문의 몫은 하나다 (docs/FORMATS.md 10.2절). 조건에 달이 없을 때만 본다.
    if not problems and condition.month is None:
        months = _months_together(venue, [p for p, _ in lines] if lines else [p for p, _, _ in extras])
        if not months:
            problems.append("고른 상품들을 함께 파는 달이 없다")
        for product, addon, _ in extras if lines else []:
            if not months <= months_sold(venue, product):
                problems.append(f"추가 상품 '{addon.product_id}' 는 고른 주문을 파는 달 가운데 팔지 않는 달이 있다")
    return problems


def _row(base: dict[str, Any], **values: Any) -> LedgerRow:
    row = {
        "choice_kind": "none",
        "venue_id": None,
        "product_id": None,
        "quantity": 0,
        "unit": None,
        "list_price": 0,
        "discount": 0,
        "paid": 0,
        "revenue_net": 0,
        "counted_share": 1.0,
        "weighted_revenue": 0,
        "reason_labels": [],
        "reason_text": None,
        "used_attributes": [],
        "llm_call": None,
        "request_hash": None,
        "status": "ok",
        "fail_reason": None,
    }
    return LedgerRow.model_validate({**row, **base, **values})


def failed_row(base: dict[str, Any], reason: str, llm_call: str | None = None, request_hash: str | None = None) -> LedgerRow:
    """실패한 방문은 금액이 0 인 줄 하나로만 남긴다."""
    return _row(base, status="failed", fail_reason=reason, llm_call=llm_call, request_hash=request_hash)


def no_candidate_row(base: dict[str, Any]) -> LedgerRow:
    """후보가 하나도 없어 엔진이 응답 없이 "이용하지 않음"으로 정한 방문."""
    return _row(base, reason_text=NO_CANDIDATE_REASON)


def visit_rows(
    base: dict[str, Any],
    request: ChoiceRequest,
    response: ChoiceResponse,
    venues: dict[str, Venue],
    llm_call: str,
    request_hash: str,
) -> list[LedgerRow]:
    """검사를 통과한 응답 하나를 원장의 줄로 바꾼다. 주문한 상품 한 줄이 원장의 한 줄이다.

    `base` 에는 방문마다 같은 값이 들어 있다: run_id, scenario_id, visit_id, persona_id, customer_group,
    condition_id, represented. 추가 상품 줄의 할인은 0 이다 (할인을 적용할지는 아직 정하지 않았다. FORMATS 12절).
    """
    told = {
        "reason_labels": response.reason_labels,
        "reason_text": response.reason_text,
        "used_attributes": response.used_attributes,
        "llm_call": llm_call,
        "request_hash": request_hash,
    }
    if response.choice.venue_id is None:
        return [_row(base, **told)]

    venue = venues[response.choice.venue_id]
    lines, extras = _chosen_products(request, response, venue)
    share = _share(request, venue, [p for p, _ in lines] if lines else [p for p, _, _ in extras])
    walkerhill = not venue.is_competitor
    bought = [(line.product_id, line.quantity, line.unit, line.unit_price, line.discount) for _, line in lines]
    bought += [(addon.product_id, quantity, addon.unit, addon.unit_price, 0) for _, addon, quantity in extras]

    rows = []
    for product_id, quantity, unit, unit_price, discount in bought:
        paid = quantity * unit_price - discount
        revenue_net = net_of_tax(paid) if walkerhill else 0
        rows.append(
            _row(
                base,
                **told,
                choice_kind="walkerhill" if walkerhill else "competitor",
                venue_id=venue.venue_id,
                product_id=product_id,
                quantity=quantity,
                unit=unit,
                list_price=unit_price,
                discount=discount,
                paid=paid,
                revenue_net=revenue_net,
                counted_share=share,
                weighted_revenue=round_half_up(weighted_amount(revenue_net, base["represented"], share)),
            )
        )
    if share < 1:
        # 일부 달에만 파는 것을 골랐다. 나머지 몫은 "이용하지 않음"으로 센다 (docs/PRD.md 7.2절).
        rows.append(
            _row(base, counted_share=1 - share, reason_text=SEASON_GAP_REASON, llm_call=llm_call, request_hash=request_hash)
        )
    return rows


def totals(rows: list[LedgerRow]) -> dict[str, Any]:
    """원장의 합계. `status` 가 ok 인 줄만 넣는다.

    돌려주는 것: `total`, `by_persona`, `by_venue` (업장을 고르지 않은 줄의 키는 None).
    값은 낸 금액, 세금을 뺀 워커힐 매출, 가중 매출의 합이다. 어느 쪽으로 더해도 전체 합과 같다.
    """
    by_persona: dict[str, dict[str, float]] = defaultdict(lambda: dict.fromkeys(TOTAL_KEYS, 0))
    by_venue: dict[str | None, dict[str, float]] = defaultdict(lambda: dict.fromkeys(TOTAL_KEYS, 0))
    total: dict[str, float] = dict.fromkeys(TOTAL_KEYS, 0)
    for row in rows:
        if row.status != "ok":
            continue
        for key in TOTAL_KEYS:
            value = getattr(row, key)
            total[key] += value
            by_persona[row.persona_id][key] += value
            by_venue[row.venue_id][key] += value
    return {"total": total, "by_persona": dict(by_persona), "by_venue": dict(by_venue)}


def write_ledger(path: Path, rows: list[LedgerRow]) -> None:
    """원장을 CSV 로 쓴다. 가중 매출은 원 단위로 반올림한 정수로 적는다."""
    cells = []
    for row in rows:
        data = row.model_dump()
        data["weighted_revenue"] = round_half_up(row.weighted_revenue)
        cells.append(data)
    write_csv(path, LEDGER_COLUMNS, cells)
