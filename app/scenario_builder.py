"""화면에서 고른 변화로 상황 정의 파일을 만든다 (T202, docs/FORMATS.md 7절).

상황 정의는 화면 담당의 폴더(`scenarios/`)에 둔다. 화면이 만든 파일은 이름이 `ui-` 로 시작한다.
시연에 쓸 상황(T20)은 사람이 확정해 따로 올리고, `ui-` 파일은 올리지 않는다.

- 경쟁 호텔의 할인: 경쟁 업장에 할인 프로모션을 붙인다 (`competitor`, `add_promotion`).
- 우리 가격 바꾸기: 워커힐 업장의 모든 상품 가격을 퍼센트로 바꾼다 (`our_price`, `change_price_pct`).
- 우리 한정 메뉴: 워커힐 업장에 한정 메뉴를 더한다 (`our_promo`, `add_product`). 팀장 요청(11-16)으로 할인 대신 이 방식이다.

만든 파일은 엔진과 형식 검사가 쓰는 모델(`engine.formats.Scenario`)로 검사한 뒤 쓴다.
"""

import hashlib
from pathlib import Path

from engine.formats import Scenario
from engine.formats.io import write_json

UI_PREFIX = "ui-"

# 한정 메뉴를 파는 때. 화면의 고르기 → (이용 상황, 끼니).
MENU_SLOTS = {
    "점심": ("meal", "lunch"),
    "저녁": ("meal", "dinner"),
    "디저트·차": ("dessert", None),
    "포장·구매": ("takeout", None),
}

DAY_TYPES = {"평일·주말": "all", "주말만": "weekend", "평일만": "weekday"}


def _pct_tag(pct: float) -> str:
    """식별자에 넣을 퍼센트. 식별자는 영어 소문자, 숫자, 하이픈만 쓴다 (-20 → m20, 10 → p10)."""
    value = round(abs(pct))
    return f"{'m' if pct < 0 else 'p'}{value}"


def _short_hash(*parts: object) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:6]


def competitor_discount(venue_id: str, venue_name: str, pct: int, day_type: str = "all") -> Scenario:
    weekend = {"all": None, "weekend": "weekend", "weekday": "weekday"}[day_type]
    when = {"all": "", "weekend": "주말 ", "weekday": "평일 "}[day_type]
    promo_id = f"ui-discount-{pct}" + (f"-{day_type}" if weekend else "")
    return Scenario.model_validate(
        {
            "format_version": 1,
            "scenario_id": f"{UI_PREFIX}competitor-{venue_id}-d{pct}" + (f"-{day_type}" if weekend else ""),
            "name": f"{venue_name} {when}{pct}% 할인",
            "kind": "competitor",
            "description": f"경쟁 업장 {venue_name} 이 {when}{pct}% 할인을 열었을 때 누가 옮겨 가는지 본다.",
            "changes": [
                {
                    "op": "add_promotion",
                    "venue_id": venue_id,
                    "promotion": {
                        "promo_id": promo_id,
                        "name": f"{when}{pct}% 할인",
                        "benefit": {"type": "discount_pct", "value": pct},
                        "applies_to": None,
                        "conditions": {"day_type": weekend, "meal": None, "stay": None, "party_min": None},
                        "period": None,
                        "grade": "assumption",
                        "source_id": None,
                    },
                }
            ],
            "note": "화면에서 만든 상황이다. 할인 폭은 가정이다.",
        }
    )


def our_price(venue_id: str, venue_name: str, pct: int) -> Scenario:
    word = "인상" if pct > 0 else "인하"
    return Scenario.model_validate(
        {
            "format_version": 1,
            "scenario_id": f"{UI_PREFIX}price-{venue_id}-{_pct_tag(pct)}",
            "name": f"{venue_name} 가격 {abs(pct)}% {word}",
            "kind": "our_price",
            "description": f"{venue_name} 의 모든 상품 가격을 {abs(pct)}% {word}했을 때 누가 남고 누가 옮기는지 본다.",
            "changes": [{"op": "change_price_pct", "venue_id": venue_id, "product_id": None, "pct": pct}],
            "note": "화면에서 만든 상황이다. 바꾸는 폭은 가정이다.",
        }
    )


def our_limited_menu(
    venue_id: str, venue_name: str, menu_name: str, price: int, when: str = "저녁", day_type: str = "all"
) -> Scenario:
    """워커힐 업장에 한정 메뉴(1인 기준)를 더한다. 같은 이름·가격·때면 같은 식별자가 나와 저장된 답을 다시 쓸 수 있다."""
    occasion, meal = MENU_SLOTS[when]
    tag = _short_hash(venue_id, menu_name, price, when, day_type)
    return Scenario.model_validate(
        {
            "format_version": 1,
            "scenario_id": f"{UI_PREFIX}menu-{venue_id}-{tag}",
            "name": f"{venue_name} 한정 메뉴 '{menu_name}'",
            "kind": "our_promo",
            "description": f"{venue_name} 에 한정 메뉴 '{menu_name}' 을 더했을 때 누가 새로 오거나 옮기는지 본다.",
            "changes": [
                {
                    "op": "add_product",
                    "venue_id": venue_id,
                    "product": {
                        "product_id": f"ui-limited-{tag}",
                        "name": menu_name,
                        "occasion": occasion,
                        "slots": [{"meal": meal, "day_type": day_type}],
                        "months": None,
                        "audience": "all",
                        "unit": "1인",
                        "serves": 1,
                        "qty_rule": "per_person",
                        "qty_max": None,
                        "price": price,
                        "price_basis": "included",
                        "grade": "assumption",
                        "source_id": None,
                    },
                }
            ],
            "note": "화면에서 만든 상황이다. 메뉴와 가격은 가정이다.",
        }
    )


def write_scenario(root: Path, scenario: Scenario) -> Path:
    """`<root>/scenarios/<scenario_id>.json` 에 쓴다. 같은 식별자는 같은 내용이라 덮어써도 된다."""
    path = root / "scenarios" / f"{scenario.scenario_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, scenario.model_dump(mode="json", by_alias=True))
    return path
