"""상황 적용 (docs/FORMATS.md 7절).

상황은 업장 정의 파일을 고치지 않는다. 읽어 둔 업장 정의의 사본에 `changes` 를 순서대로 적용해 돌려준다.
적용한 뒤의 업장 정의도 업장 정의의 규칙(3절)을 지켜야 한다. 어긋나면 틀린 금액을 내지 않고 멈춘다.
엔진은 가격이 빈 상품의 단가를 먼저 채우고 상황을 적용한다 (`apply_with_prices`, docs/FORMATS.md 3절, T223).
"""

import json
from typing import Any

from pydantic import ValidationError

from engine.formats.money import change_price
from engine.formats.scenario import (
    AddProduct,
    AddPromotion,
    Change,
    ChangePricePct,
    RemoveProduct,
    RemovePromotion,
    Scenario,
    SetPrice,
)
from engine.formats.summary import SummaryRow
from engine.formats.venue import Venue
from engine.weights import fill_prices


class ScenarioError(ValueError):
    """상황을 업장 정의에 적용할 수 없다. 적용하지 못한 채로 돌리면 기준과 같은 결과가 조용히 나온다."""


def _as_json(model: Any) -> dict[str, Any]:
    """모델을 파일에 적는 모양의 사전으로 바꾼다 (고쳐도 원래 모델은 바뀌지 않는다)."""
    return json.loads(model.model_dump_json(by_alias=True))


def _apply(data: dict[str, Any], change: Change, where: str) -> None:
    """업장 정의의 사본(사전) 하나에 바꾸는 것 하나를 적용한다."""
    venue_id = data["venue_id"]
    products: list[dict[str, Any]] = data["products"]
    promotions: list[dict[str, Any]] = data["promotions"]

    def product(product_id: str) -> dict[str, Any]:
        found = next((p for p in products if p["product_id"] == product_id), None)
        if found is None:
            raise ScenarioError(f"{where} — 상품 '{product_id}' 가 업장 '{venue_id}' 에 없다")
        return found

    if isinstance(change, SetPrice):
        product(change.product_id)["price"] = change.price
    elif isinstance(change, ChangePricePct):
        if change.product_id is None:
            # 업장의 모든 상품. 가격이 비어 있는 상품은 바꿀 값이 없어 그대로 둔다 (후보에서 빠지고 실행 기록에 남는다).
            targets = [p for p in products if p["price"] is not None]
            if not targets:
                raise ScenarioError(f"{where} — 업장 '{venue_id}' 에 가격이 있는 상품이 없어 바뀌는 것이 없다")
        else:
            targets = [product(change.product_id)]
            if targets[0]["price"] is None:
                raise ScenarioError(
                    f"{where} — 상품 '{change.product_id}' 는 가격이 비어 있어 퍼센트로 바꿀 수 없다 (set_price 로 값을 정한다)"
                )
        for target in targets:
            target["price"] = change_price(target["price"], change.pct)
    elif isinstance(change, AddProduct):
        if any(p["product_id"] == change.product.product_id for p in products):
            raise ScenarioError(f"{where} — 상품 '{change.product.product_id}' 가 업장 '{venue_id}' 에 이미 있다")
        products.append(_as_json(change.product))
    elif isinstance(change, RemoveProduct):
        products.remove(product(change.product_id))
    elif isinstance(change, AddPromotion):
        if any(p["promo_id"] == change.promotion.promo_id for p in promotions):
            raise ScenarioError(f"{where} — 프로모션 '{change.promotion.promo_id}' 가 업장 '{venue_id}' 에 이미 있다")
        promotions.append(_as_json(change.promotion))
    elif isinstance(change, RemovePromotion):
        found = next((p for p in promotions if p["promo_id"] == change.promo_id), None)
        if found is None:
            raise ScenarioError(f"{where} — 프로모션 '{change.promo_id}' 가 업장 '{venue_id}' 에 없다")
        promotions.remove(found)
    else:  # pragma: no cover - 형식의 모델이 받는 op 는 위의 여섯 가지뿐이다
        raise ScenarioError(f"{where} — 모르는 op 다")


def apply_scenario(venues: dict[str, Venue], scenario: Scenario) -> dict[str, Venue]:
    """업장 정의의 사본에 상황의 `changes` 를 순서대로 적용해 돌려준다. 받은 `venues` 와 파일은 바뀌지 않는다.

    - `our_price`·`our_promo` 는 워커힐 업장만, `competitor` 는 경쟁 업장만 바꾼다.
    - 바꾸려는 업장, 상품, 프로모션이 없으면 멈춘다. 읽을 업장을 골라 돌릴 때는 상황이 바꾸는 업장도 읽어야 한다.
    - 다 적용한 업장 정의를 3절의 규칙으로 다시 본다 (예: 뺀 상품을 가리키는 프로모션이 남아 있으면 멈춘다).
    """
    changed: dict[str, dict[str, Any]] = {}
    for index, change in enumerate(scenario.changes):
        where = f"상황 '{scenario.scenario_id}' 의 changes[{index}] ({change.op})"
        venue = venues.get(change.venue_id)
        if venue is None:
            raise ScenarioError(f"{where} — 업장 '{change.venue_id}' 의 정의를 읽지 않았다 (파일이 없거나, 읽을 업장에서 빠졌다)")
        if scenario.kind in ("our_price", "our_promo") and venue.is_competitor:
            raise ScenarioError(f"{where} — 우리 쪽 상황({scenario.kind})은 워커힐 업장만 바꾼다")
        if scenario.kind == "competitor" and not venue.is_competitor:
            raise ScenarioError(f"{where} — 경쟁 쪽 상황(competitor)은 경쟁 업장만 바꾼다")
        _apply(changed.setdefault(venue.venue_id, _as_json(venue)), change, where)

    applied = dict(venues)
    for venue_id, data in changed.items():
        try:
            applied[venue_id] = Venue.model_validate_json(json.dumps(data, ensure_ascii=False), strict=True)
        except ValidationError as exc:
            problems = "; ".join(error["msg"] for error in exc.errors())
            raise ScenarioError(
                f"상황 '{scenario.scenario_id}' 를 적용한 업장 '{venue_id}' 의 정의가 형식에 어긋난다: {problems}"
            ) from exc
    return applied


def apply_with_prices(
    venues: dict[str, Venue], scenario: Scenario, rows: list[SummaryRow], data_mode: str
) -> tuple[dict[str, Venue], list[str]]:
    """가격이 빈 상품의 단가를 집계 파일로 채우고, 그 위에 상황을 적용한다 (docs/FORMATS.md 3절·7절, T223).

    순서: 단가 채우기 → 상황 적용 → 상황이 더한 가격 빈 상품 채우기.
    그래서 `change_price_pct` 가 채운 단가에도 걸린다 (11-20 까지는 상황을 먼저 적용해, 업장 전체를 올려도 채운 단가는 그대로였다).
    `set_price` 로 값을 정한 상품은 채운 상품이 아니다. 채울 때 붙인 등급과 가격 표기를 업장 정의의 것으로 되돌리고
    `filled_products` 에서 뺀다 (상황을 먼저 적용하던 때와 같은 결과). 상황이 뺀 상품도 목록에서 뺀다.
    돌려주는 것: 적용한 업장 정의(받은 것은 고치지 않는다), 채운 상품의 목록(`<venue_id>:<product_id>`).
    """
    prefilled, filled = fill_prices(venues, rows, data_mode)
    applied = apply_scenario(prefilled, scenario)
    still_filled = set(filled)
    restore: set[tuple[str, str]] = set()  # 값을 정해 등급과 표기를 되돌릴 상품
    for change in scenario.changes:
        if not isinstance(change, (SetPrice, RemoveProduct)):
            continue
        key = f"{change.venue_id}:{change.product_id}"
        if isinstance(change, SetPrice) and key in still_filled:
            restore.add((change.venue_id, change.product_id))
        elif isinstance(change, RemoveProduct):
            restore.discard((change.venue_id, change.product_id))
        still_filled.discard(key)
    for venue_id, product_id in sorted(restore):
        original = venues[venue_id].product(product_id)
        products = [
            p.model_copy(update={"price_basis": original.price_basis, "grade": original.grade}) if p.product_id == product_id else p
            for p in applied[venue_id].products
        ]
        applied[venue_id] = applied[venue_id].model_copy(update={"products": products})
    # 상황이 더한 상품 가운데 가격이 빈 것을 채운다. 처음에 채우지 못한 상품은 집계가 같아 이번에도 채워지지 않는다.
    refilled, added = fill_prices(applied, rows, data_mode)
    return refilled, sorted(still_filled | set(added))
