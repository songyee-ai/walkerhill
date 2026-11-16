"""상황 적용과 프로모션 규칙 (T10).

예시 묶음(tests/fixtures/example)의 사본에서 엔진을 돌린다. LLM 은 부르지 않고 정해 둔 답을 재생한다.
가격, 할인, 프로모션은 모두 지어낸 값이다.
"""

import hashlib
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

import engine.__main__ as cli
from engine.answers import save_answer
from engine.candidates import build_request, run_condition
from engine.formats import ChoiceRequest, RunRecord, Scenario, Venue, net_of_tax, read_model
from engine.formats.scenario import BASELINE_ID
from engine.formats.venue import Period, Promotion
from engine.ledger import amount_problems
from engine.promotions import meets_conditions, months_in, order_discounts
from engine.runner import latest_baseline_run, load_inputs, run
from engine.scenarios import ScenarioError, apply_scenario
from tests.conftest import BASELINE_RUN, COMPETITOR_RUN, EXAMPLE_ROOT, load_json, save_json
from tests.test_engine import (
    DINNER,
    KST,
    LUNCH,
    MODEL,
    NOW,
    PROVIDER,
    Played,
    add_tea,
    answer,
    audit,
    budget,
    edit,
    first_option,
    party,
    persona_file,
    pick_geumryong,
    play,
    product_of,
    venue_file,
)
from tests.test_llm import Clock, Fake
from tools.check_formats import check

ELDERS, KIDS = "family-elders", "family-kids"
PRICE_UP = "geumryong-course-price-up"
COMPETITOR_DISCOUNT = "competitor-chinese-discount"
LLM_ENV = ("LLM_PROVIDER", "LLM_MODEL", "LLM_CALL_LIMIT", "LLM_BASE_URL", "LLM_API_KEY")


# ── 도우미 ──────────────────────────────────────────────────────────────


def promo(promo_id="sale", kind="discount_pct", value=10, applies_to=None, period=None, **conditions) -> dict:
    """프로모션 한 줄 (지어낸 값). `conditions` 에 적지 않은 조건은 null 이다."""
    wanted = {"day_type": None, "meal": None, "stay": None, "party_min": None} | conditions
    return {
        "promo_id": promo_id,
        "name": f"테스트 프로모션 {promo_id}",
        "benefit": {"type": kind, "value": value},
        "applies_to": applies_to,
        "conditions": wanted,
        "period": period,
        "grade": "assumption",
        "source_id": None,
    }


def gift(promo_id="gift", applies_to=None) -> dict:
    return promo(promo_id, "gift", "차 한 잔", applies_to)


def give(root: Path, venue_id: str, *promotions: dict) -> None:
    """업장 정의 파일에 프로모션을 적는다 (지금 진행 중인 프로모션)."""
    edit(venue_file(root, venue_id), lambda d: d["promotions"].extend(promotions))


def scenario(kind: str, *changes: dict, scenario_id: str = "test-scenario") -> Scenario:
    return Scenario.model_validate(
        {
            "format_version": 1,
            "scenario_id": scenario_id,
            "name": "테스트 상황",
            "kind": kind,
            "description": "테스트에 쓰는 상황이다.",
            "changes": list(changes),
            "note": "값은 모두 지어낸 것이다",
        }
    )


def write_scenario(root: Path, kind: str, *changes: dict, scenario_id: str = "test-scenario") -> str:
    data = scenario(kind, *changes, scenario_id=scenario_id).model_dump(mode="json", by_alias=True)
    save_json(root / "scenarios" / f"{scenario_id}.json", data)
    return scenario_id


def venues_of(root: Path = EXAMPLE_ROOT) -> dict[str, Venue]:
    return {p.stem: read_model(p, Venue) for p in sorted((root / "data" / "venues").glob("*.json"))}


def new_product(product_id: str, **values) -> dict:
    """금룡의 코스 A 를 베껴 만든 상품 한 줄."""
    base = product_of(load_json(venue_file(EXAMPLE_ROOT, "geumryong")), "course-a")
    return dict(base, product_id=product_id, name=f"테스트 상품 {product_id}") | values


def request_for(
    root: Path, scenario_id="baseline", persona_id=ELDERS, condition_id=DINNER, venue_ids=None, **condition
) -> ChoiceRequest | None:
    """엔진이 그 상황, 그 방문에 만들 요청. `condition` 으로 방문 조건의 값(달, 투숙 여부)을 바꿀 수 있다."""
    inputs = load_inputs(root, "sample", scenario_id, venue_ids=venue_ids, persona_ids=[persona_id])
    persona = inputs.personas[persona_id]
    visit = run_condition(inputs.conditions.condition(condition_id), persona).model_copy(update=condition)
    request, _ = build_request(
        prompt_version="p1",
        scenario_id=scenario_id,
        persona=inputs.persona_json[persona_id],
        condition=visit,
        venues=list(inputs.venues.values()),
        vocab=inputs.vocab,
    )
    return request


def lines_of(request: ChoiceRequest, venue_id: str, number: int = 1) -> list[tuple[str, int, int]]:
    """그 업장의 number 번째 주문의 줄: (상품, 할인, 줄의 금액)."""
    option = request.candidate(venue_id).option(f"{venue_id}-o{number}")
    return [(line.product_id, line.discount, line.line_total) for line in option.lines]


def shown(request: ChoiceRequest, venue_id: str) -> list[tuple[str, bool]]:
    return [(p.promo_id, p.applied) for p in request.candidate(venue_id).promotions]


def play_scenario(root: Path, scenario_id: str, pick, base: Played, *, now=None, venue_ids=None, **more) -> Played:
    """기준 실행 `base` 의 페르소나·조건·가중치로 상황 하나를 돌린다. 답은 `pick(visit_id, request)` 으로 정해 둔다."""
    now = now or NOW + timedelta(hours=1)
    answers = root.parent / f"answers-{scenario_id}-{now:%H%M%S}"
    requests = {}
    for persona_id in base.record.persona_ids:
        for condition_id in base.record.condition_ids:
            request = request_for(root, scenario_id, persona_id, condition_id, venue_ids)
            if request is None:
                continue
            visit_id = f"{persona_id}__{condition_id}"
            requests[visit_id] = request
            response = pick(visit_id, request)
            if response is not None:
                save_answer(answers, PROVIDER, MODEL, request, response, now)
    run_dir = run(
        root,
        data_mode="sample",
        now=now,
        provider=PROVIDER,
        model=MODEL,
        prompt_version="p1",
        answers=[answers],
        scenario_id=scenario_id,
        venue_ids=venue_ids,
        weights_from=base.run_dir.name,
        engine_commit="0000000",
        **more,
    )
    played = Played(root, run_dir, requests)
    # 위반을 셀 때는 그 실행의 상황을 적용한 업장 정의와 견준다.
    played.venues = load_inputs(root, "sample", scenario_id, venue_ids=venue_ids).venues
    return played


def pick_venue(venue_id: str):
    return lambda visit_id, request: first_option(request, venue_id)


def run_scenario(root: Path, scenario_id: str, **values):
    """답 없이 상황을 돌려 본다 (돌릴 수 있는지만 볼 때)."""
    settings = dict(data_mode="sample", now=NOW + timedelta(hours=2), provider=PROVIDER, model=MODEL, prompt_version="p1", answers=[])
    return run(root, scenario_id=scenario_id, engine_commit="0000000", **(settings | values))


def files_hash(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            digest.update(path.name.encode("utf-8") + path.read_bytes())
    return digest.hexdigest()


def no_format_errors(root: Path) -> None:
    assert [str(p) for p in check(root, strict=True)] == []


# ── 상황 정의의 바꾸는 종류 여섯 가지 ───────────────────────────────────


def test_six_kinds_of_change_are_applied_in_order_to_a_copy():
    venues = venues_of()
    before = {venue_id: venue.model_dump_json() for venue_id, venue in venues.items()}
    applied = apply_scenario(
        venues,
        scenario(
            "our_promo",
            {"op": "set_price", "venue_id": "geumryong", "product_id": "course-a", "price": 160000},
            {"op": "change_price_pct", "venue_id": "geumryong", "product_id": "course-a", "pct": 10},
            {"op": "add_product", "venue_id": "geumryong", "product": new_product("tea", price=10000)},
            {"op": "change_price_pct", "venue_id": "geumryong", "product_id": None, "pct": -50},
            {"op": "remove_product", "venue_id": "geumryong", "product_id": "course-b"},
            {"op": "add_promotion", "venue_id": "geumryong", "promotion": promo("first")},
            {"op": "add_promotion", "venue_id": "geumryong", "promotion": gift()},
            {"op": "remove_promotion", "venue_id": "geumryong", "promo_id": "first"},
        ),
    )
    geumryong = applied["geumryong"]
    # 160000 → 10% 올려 176000 → 모든 상품을 50% 내려 88000. 순서대로 적용한다.
    assert [(p.product_id, p.price) for p in geumryong.products] == [("course-a", 88000), ("tea", 5000)]
    assert [p.promo_id for p in geumryong.promotions] == ["gift"]
    # 받은 업장 정의는 그대로다. 바꾸지 않은 업장은 같은 것을 돌려준다.
    assert {venue_id: venue.model_dump_json() for venue_id, venue in venues.items()} == before
    assert applied["thebuffet"] is venues["thebuffet"] and applied["geumryong"] is not venues["geumryong"]


def test_baseline_changes_nothing():
    venues = venues_of()
    assert apply_scenario(venues, read_model(EXAMPLE_ROOT / "scenarios" / "baseline.json", Scenario)) == venues


def test_price_changed_by_percent_is_rounded_as_a_price():
    """15원을 10% 내리면 14원이다. 내린 폭(1.5원)을 먼저 반올림해서 빼면 13원이 된다 (docs/FORMATS.md 7절)."""
    applied = apply_scenario(
        venues_of(),
        scenario(
            "our_price",
            {"op": "set_price", "venue_id": "geumryong", "product_id": "course-a", "price": 15},
            {"op": "change_price_pct", "venue_id": "geumryong", "product_id": "course-a", "pct": -10},
        ),
    )
    assert applied["geumryong"].product("course-a").price == 14


def test_product_without_a_price_is_left_out_of_a_change_to_every_product():
    venues = venues_of()
    data = load_json(venue_file(EXAMPLE_ROOT, "geumryong"))
    product_of(data, "course-b").update(price=None, grade="unknown")
    venues["geumryong"] = Venue.model_validate(data)

    every = scenario("our_price", {"op": "change_price_pct", "venue_id": "geumryong", "product_id": None, "pct": 10})
    assert [p.price for p in apply_scenario(venues, every)["geumryong"].products] == [165000, None]
    # 그 상품 하나를 가리켜 바꾸라고 했는데 바꿀 값이 없으면 멈춘다. 조용히 지나가면 기준과 같은 결과가 나온다.
    one = scenario("our_price", {"op": "change_price_pct", "venue_id": "geumryong", "product_id": "course-b", "pct": 10})
    with pytest.raises(ScenarioError, match="가격이 비어 있어"):
        apply_scenario(venues, one)
    # 모든 상품을 바꾸라고 했는데 가격이 있는 상품이 하나도 없으면, 바뀌는 것이 없으니 역시 멈춘다.
    product_of(data, "course-a").update(price=None, grade="unknown")
    venues["geumryong"] = Venue.model_validate(data)
    with pytest.raises(ScenarioError, match="바뀌는 것이 없다"):
        apply_scenario(venues, every)


@pytest.mark.parametrize(
    "kind, changes, message",
    [
        ("competitor", [{"op": "set_price", "venue_id": "geumryong", "product_id": "course-a", "price": 1}], "경쟁 업장만"),
        ("our_price", [{"op": "set_price", "venue_id": "examplehotel-chinese", "product_id": "course", "price": 1}], "워커힐 업장만"),
        ("our_promo", [{"op": "add_promotion", "venue_id": "examplehotel-chinese", "promotion": promo()}], "워커힐 업장만"),
        ("our_price", [{"op": "set_price", "venue_id": "nowhere", "product_id": "course-a", "price": 1}], "정의를 읽지 않았다"),
        ("our_price", [{"op": "set_price", "venue_id": "geumryong", "product_id": "ghost", "price": 1}], "상품 'ghost' 가"),
        ("our_price", [{"op": "change_price_pct", "venue_id": "geumryong", "product_id": "ghost", "pct": 5}], "상품 'ghost' 가"),
        ("our_price", [{"op": "remove_product", "venue_id": "geumryong", "product_id": "ghost"}], "상품 'ghost' 가"),
        ("our_price", [{"op": "add_product", "venue_id": "geumryong", "product": new_product("course-a")}], "이미 있다"),
        ("our_promo", [{"op": "remove_promotion", "venue_id": "geumryong", "promo_id": "ghost"}], "프로모션 'ghost' 가"),
        (
            "our_promo",
            [{"op": "add_promotion", "venue_id": "geumryong", "promotion": promo()}] * 2,
            "이미 있다",
        ),
        # 다 적용한 업장 정의도 업장 정의의 규칙을 지켜야 한다.
        (
            "our_promo",
            [
                {"op": "add_promotion", "venue_id": "geumryong", "promotion": promo(applies_to=["course-b"])},
                {"op": "remove_product", "venue_id": "geumryong", "product_id": "course-b"},
            ],
            "형식에 어긋난다",
        ),
        (
            "our_price",
            [{"op": "add_product", "venue_id": "geumryong", "product": new_product("cake", occasion="dessert", slots=[{"meal": None, "day_type": "all"}])}],
            "형식에 어긋난다",
        ),
    ],
)
def test_change_that_cannot_be_applied_stops(kind, changes, message):
    with pytest.raises(ScenarioError, match=message):
        apply_scenario(venues_of(), scenario(kind, *changes))


def test_scenario_must_be_able_to_reach_the_venue_it_changes(example_copy):
    """읽을 업장을 골라 돌릴 때 상황이 바꾸는 업장이 빠져 있으면 멈춘다. 적용하지 못한 채 돌리지 않는다."""
    with pytest.raises(ScenarioError, match="examplehotel-chinese"):
        load_inputs(example_copy, "sample", COMPETITOR_DISCOUNT, venue_ids=["geumryong"])


def test_format_check_applies_the_scenario_the_way_the_engine_does(example_copy):
    """바꾸는 것을 하나씩 보면 맞는데 다 적용하면 어긋나는 상황을 형식 검사가 잡는다."""
    write_scenario(
        example_copy,
        "our_promo",
        {"op": "add_promotion", "venue_id": "geumryong", "promotion": promo(applies_to=["course-b"])},
        {"op": "remove_product", "venue_id": "geumryong", "product_id": "course-b"},
    )
    errors = [str(p) for p in check(example_copy, strict=True)]
    assert len(errors) == 1 and "scenarios/test-scenario.json" in errors[0] and "형식에 어긋난다" in errors[0]
    # 이미 적은 오류(없는 상품)는 겹쳐 적지 않는다.
    write_scenario(example_copy, "our_price", {"op": "set_price", "venue_id": "geumryong", "product_id": "ghost", "price": 1})
    assert len(check(example_copy, strict=True)) == 1


# ── 프로모션을 금액에 넣는 규칙 (FORMATS 3절) ───────────────────────────


def as_promotions(*promotions: dict) -> list[Promotion]:
    return [Promotion.model_validate(p) for p in promotions]


def test_percent_discount_is_taken_from_every_line_and_rounded_per_line():
    cuts, applied = order_discounts(as_promotions(promo()), [("a", 33333), ("b", 5), ("c", 4)])
    assert (cuts, applied) == ([3333, 1, 0], "sale")  # 3333.3 → 3333, 0.5 → 1, 0.4 → 0


def test_percent_discount_on_adult_and_child_lines(example_copy):
    give(example_copy, "thebuffet", promo())
    request = request_for(example_copy, persona_id=KIDS)
    # 성인 180000 × 2, 어린이 90000 × 2. 줄마다 10% 를 깎는다.
    assert lines_of(request, "thebuffet") == [("dinner-adult", 36000, 324000), ("dinner-child", 18000, 162000)]
    assert request.candidate("thebuffet").options[0].total == 486000
    assert shown(request, "thebuffet") == [("sale", True)]


@pytest.mark.parametrize(
    "value, applies_to, lines",
    [
        # 주문 한 번에 한 번만 깎는다. 적용되는 상품의 첫 줄에서 뺀다.
        (50000, None, [("dinner-adult", 50000, 310000), ("dinner-child", 0, 180000)]),
        (50000, ["dinner-child"], [("dinner-adult", 0, 360000), ("dinner-child", 50000, 130000)]),
        # 그 줄의 금액보다 많이 깎지 않는다.
        (999999, ["dinner-child"], [("dinner-adult", 0, 360000), ("dinner-child", 180000, 0)]),
    ],
)
def test_amount_discount_is_taken_once_from_the_first_line_it_applies_to(example_copy, value, applies_to, lines):
    give(example_copy, "thebuffet", promo(kind="discount_amount", value=value, applies_to=applies_to))
    assert lines_of(request_for(example_copy, persona_id=KIDS), "thebuffet") == lines


def test_gift_changes_no_amount_and_is_only_told(example_copy):
    plain = request_for(example_copy)
    give(example_copy, "geumryong", gift())
    request = request_for(example_copy)
    assert request.candidate("geumryong").options == plain.candidate("geumryong").options
    assert shown(request, "geumryong") == [("gift", False)]
    assert request.candidate("geumryong").promotions[0].benefit.value == "차 한 잔"


def test_only_the_largest_discount_is_applied_and_every_gift_is_told(example_copy):
    give(
        example_copy,
        "geumryong",
        promo("ten-percent"),  # 코스 A 4명 600000 의 10% 는 60000
        gift("gift-a"),
        promo("small", "discount_amount", 50000),
        promo("big", "discount_amount", 70000),
        gift("gift-b"),
    )
    request = request_for(example_copy)
    assert lines_of(request, "geumryong", 1) == [("course-a", 70000, 530000)]
    # 코스 B 4명 800000 의 10% 는 80000 이라, 이 주문에서는 퍼센트 할인이 가장 크다. 할인은 주문마다 따로 고른다.
    assert lines_of(request, "geumryong", 2) == [("course-b", 80000, 720000)]
    assert shown(request, "geumryong") == [
        ("ten-percent", True),
        ("gift-a", False),
        ("small", False),
        ("big", True),
        ("gift-b", False),
    ]


def test_equal_discounts_spread_differently_still_apply_the_one_written_first(example_copy):
    """깎이는 금액의 합이 같아도 줄에 나뉘는 모양은 다를 수 있다. 엔진도, 따로 확인하는 쪽도 먼저 적힌 것을 쓴다."""
    percent, amount = promo("pct"), promo("amount", "discount_amount", 54000)  # 성인 360000 + 어린이 180000 의 10% 는 54000
    give(example_copy, "thebuffet", percent, amount)
    played = play(example_copy, pick_venue("thebuffet"), persona_ids=(KIDS,))
    assert [(r.product_id, r.discount) for r in played.rows] == [("dinner-adult", 36000), ("dinner-child", 18000)]
    assert audit(played) == []

    edit(venue_file(example_copy, "thebuffet"), lambda d: d["promotions"].reverse())
    again = play(example_copy, pick_venue("thebuffet"), persona_ids=(KIDS,), now=NOW + timedelta(hours=1))
    assert [(r.product_id, r.discount) for r in again.rows] == [("dinner-adult", 54000), ("dinner-child", 0)]
    assert audit(again) == []


def test_party_min_counts_children_too(example_copy):
    """`party_min` 은 일행의 수(성인 + 어린이)와 견준다. 이 페르소나는 성인 2명과 어린이 2명이다."""
    give(example_copy, "thebuffet", promo(party_min=4))
    played = play(example_copy, pick_venue("thebuffet"), persona_ids=(KIDS,))
    assert [(r.product_id, r.discount) for r in played.rows] == [("dinner-adult", 36000), ("dinner-child", 18000)]
    assert audit(played) == []
    edit(venue_file(example_copy, "thebuffet"), lambda d: d["promotions"][0]["conditions"].update(party_min=5))
    assert lines_of(request_for(example_copy, persona_id=KIDS), "thebuffet") == [("dinner-adult", 0, 360000), ("dinner-child", 0, 180000)]


def test_discount_only_on_an_order_dropped_by_the_budget_is_not_marked_applied(example_copy):
    """예산으로 빠진 주문에만 들어간 할인은 `applied` 가 아니다. 남은 주문의 금액에는 들어 있지 않기 때문이다."""
    edit(persona_file(example_copy, ELDERS), party(1))
    edit(persona_file(example_copy, ELDERS), budget(typical=150000, max=170000))
    give(example_copy, "geumryong", promo("all10"), promo("a50k", "discount_amount", 50000, ["course-a"]))
    request = request_for(example_copy)
    # 코스 A(150000): 금액 할인 50000 이 10%(15000)보다 크다. 코스 B(200000)는 10% 를 깎아도 180000 이라 예산 밖이다.
    assert [o.option_id for o in request.candidate("geumryong").options] == ["geumryong-o1"]
    assert lines_of(request, "geumryong") == [("course-a", 50000, 100000)]
    assert shown(request, "geumryong") == [("all10", False), ("a50k", True)]


def test_recomputing_the_amount_reads_the_conditions_of_the_promotion(example_copy):
    """받은 답의 금액을 다시 계산할 때도 이번 방문에 해당하는 프로모션만 쓴다."""
    give(example_copy, "geumryong", promo(day_type="weekday"))  # 이 방문은 주말이다
    played = play(example_copy, pick_geumryong)
    (row,) = played.rows
    assert (row.status, row.discount, row.paid) == ("ok", 0, 600000)
    assert played.violations() == []


def test_equal_discounts_apply_the_one_written_first():
    lines = [("course-a", 600000)]
    first, second = promo("pct"), promo("amount", "discount_amount", 60000)
    assert order_discounts(as_promotions(first, second), lines) == ([60000], "pct")
    assert order_discounts(as_promotions(second, first), lines) == ([60000], "amount")
    assert order_discounts(as_promotions(gift()), lines) == ([0], None)
    assert order_discounts([], lines) == ([0], None)


@pytest.mark.parametrize(
    "conditions, visit, applies",
    [
        ({"day_type": "weekend"}, {}, True),
        ({"day_type": "weekday"}, {}, False),
        ({"meal": "dinner"}, {}, True),
        ({"meal": "lunch"}, {}, False),
        # 조건에 투숙 여부가 적혀 있는데 방문 조건의 투숙 여부가 null 이면 적용하지 않는다.
        ({"stay": "guest"}, {}, False),
        ({"stay": "guest"}, {"stay": "guest"}, True),
        ({"stay": "guest"}, {"stay": "visitor"}, False),
        ({"party_min": 4}, {}, True),  # 이 페르소나는 4명이다
        ({"party_min": 5}, {}, False),
        ({"day_type": "weekend", "meal": "dinner", "party_min": 4}, {}, True),
        ({"day_type": "weekend", "meal": "lunch", "party_min": 4}, {}, False),
    ],
)
def test_promotion_applies_only_when_its_conditions_are_met(example_copy, conditions, visit, applies):
    give(example_copy, "geumryong", promo(**conditions))
    request = request_for(example_copy, **visit)
    assert lines_of(request, "geumryong") == [("course-a", 60000, 540000) if applies else ("course-a", 0, 600000)]
    assert shown(request, "geumryong") == ([("sale", True)] if applies else [])


def test_meal_condition_never_matches_a_visit_without_a_meal(example_copy):
    """식사가 아닌 방문(끼니가 null)에는 끼니 조건이 있는 프로모션을 적용하지 않는다."""
    promotion = Promotion.model_validate(promo(meal="dinner"))
    lunch_visit = request_for(example_copy, condition_id=LUNCH).condition
    assert not meets_conditions(promotion, lunch_visit.model_copy(update={"occasion": "dessert", "meal": None}))


@pytest.mark.parametrize(
    "start, end, months",
    [
        ("2026-11-15", "2026-11-20", {11}),
        ("2026-12-20", "2027-02-03", {12, 1, 2}),
        ("2026-11-01", "2027-10-31", set(range(1, 13))),
        ("2026-01-01", "2030-12-31", set(range(1, 13))),
    ],
)
def test_period_is_read_as_the_months_it_touches(start, end, months):
    assert months_in(Period.model_validate({"from": start, "to": end})) == months


@pytest.mark.parametrize("month, applies", [(None, True), (12, True), (1, True), (7, False)])
def test_period_is_compared_only_when_the_visit_has_a_month(example_copy, month, applies):
    give(example_copy, "geumryong", promo(period={"from": "2026-12-01", "to": "2027-01-31"}))
    request = request_for(example_copy, month=month)
    assert lines_of(request, "geumryong")[0][1] == (60000 if applies else 0)


def test_promotion_on_products_not_offered_this_visit_is_not_shown(example_copy):
    give(example_copy, "geumryong", promo(applies_to=["course-b"]))  # 코스 B 는 저녁에만 판다
    assert shown(request_for(example_copy, condition_id=LUNCH), "geumryong") == []
    dinner = request_for(example_copy)
    assert lines_of(dinner, "geumryong", 1) == [("course-a", 0, 600000)]
    assert lines_of(dinner, "geumryong", 2) == [("course-b", 80000, 720000)]
    assert shown(dinner, "geumryong") == [("sale", True)]


def test_budget_is_compared_with_the_amount_after_the_discount(example_copy):
    edit(persona_file(example_copy, ELDERS), budget(typical=120000, max=140000))  # 4명이라 560000 까지
    assert request_for(example_copy).candidate("geumryong") is None  # 코스 A 600000 은 넘는다
    give(example_copy, "geumryong", promo())
    request = request_for(example_copy)
    # 할인을 받은 코스 A(540000)는 예산 안이고, 코스 B(720000)는 여전히 넘어 빠진다. 번호는 그대로다.
    assert [o.option_id for o in request.candidate("geumryong").options] == ["geumryong-o1"]
    assert lines_of(request, "geumryong") == [("course-a", 60000, 540000)]


def test_discount_that_survives_on_no_order_is_not_marked_applied(example_copy):
    edit(persona_file(example_copy, ELDERS), budget(typical=150000, max=160000))  # 640000 까지
    give(example_copy, "geumryong", promo(applies_to=["course-b"]))  # 코스 B 는 할인해도 720000 이라 빠진다
    request = request_for(example_copy)
    assert [o.option_id for o in request.candidate("geumryong").options] == ["geumryong-o1"]
    assert shown(request, "geumryong") == []


def test_addon_rows_are_not_discounted(example_copy):
    """추가 상품에는 프로모션 할인을 적용하지 않는다 (11-16 회의에서 정함. FORMATS 3절). 추가 상품 줄의 할인은 0 이다."""
    edit(venue_file(example_copy, "geumryong"), add_tea)
    give(example_copy, "geumryong", promo(), promo("tea-only", "discount_amount", 3000, ["tea"]))
    played = play(example_copy, lambda visit, request: answer(request, "geumryong", "geumryong-o1", [("tea", 3)]))
    request = played.requests[f"{ELDERS}__{DINNER}"]
    assert request.candidate("geumryong").addons[0].unit_price == 10000
    assert shown(request, "geumryong") == [("sale", True), ("tea-only", False)]
    rows = played.visit(ELDERS, DINNER)
    assert [(r.product_id, r.list_price, r.discount, r.paid) for r in rows] == [
        ("course-a", 150000, 60000, 540000),
        ("tea", 10000, 0, 30000),
    ]
    assert played.violations() == []
    no_format_errors(example_copy)


def test_discounted_order_is_written_to_the_ledger(example_copy):
    give(example_copy, "geumryong", promo())
    played = play(example_copy, pick_geumryong)
    (row,) = played.visit(ELDERS, DINNER)
    assert (row.list_price, row.quantity, row.discount, row.paid) == (150000, 4, 60000, 540000)
    assert row.revenue_net == net_of_tax(540000) == 490909  # 세금을 뺀 매출은 할인을 뺀 금액에서 낸다
    assert played.violations() == []
    no_format_errors(example_copy)


def test_reply_is_refused_when_the_discount_is_not_what_the_rules_give(example_copy):
    """받은 답의 금액을 업장 정의로 다시 계산한다. 요청에 적힌 할인을 믿지 않는다 (docs/FORMATS.md 9절)."""
    give(example_copy, "geumryong", promo())
    request = request_for(example_copy)
    venues = load_inputs(example_copy, "sample").venues
    assert amount_problems(request, first_option(request, "geumryong"), venues) == []

    data = request.model_dump(mode="json")
    line = data["candidates"][0]["options"][0]["lines"][0]
    line.update(discount=90000, line_total=510000)
    data["candidates"][0]["options"][0]["total"] = 510000
    tampered = ChoiceRequest.model_validate(data)
    assert amount_problems(tampered, first_option(tampered, "geumryong"), venues) == [
        "상품 'course-a' 의 할인이 프로모션 규칙으로 낸 값과 다르다"
    ]
    # 프로모션이 없어진 업장 정의로 다시 계산하면, 요청의 할인은 어디서도 나오지 않는 값이다.
    assert amount_problems(request, first_option(request, "geumryong"), venues_of()) != []


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda c: c["promotions"][0].update(applied=False), "서로 다른 말"),
        (lambda c: c.update(promotions=[]), "서로 다른 말"),
        (lambda c: c["promotions"].append(dict(c["promotions"][0])), "두 번"),
        (lambda c: c["promotions"].append({"promo_id": "gift", "name": "증정", "benefit": {"type": "gift", "value": "차"}, "applied": True}), "증정"),
    ],
)
def test_request_must_say_the_same_thing_in_discounts_and_applied(example_copy, change, message):
    give(example_copy, "geumryong", promo())
    data = request_for(example_copy).model_dump(mode="json")
    change(data["candidates"][0])
    with pytest.raises(ValidationError, match=message):
        ChoiceRequest.model_validate(data)


def test_request_without_discounts_cannot_claim_an_applied_promotion(example_copy):
    data = request_for(example_copy).model_dump(mode="json")
    data["candidates"][0]["promotions"] = [{"promo_id": "sale", "name": "할인", "benefit": {"type": "discount_pct", "value": 10}, "applied": True}]
    with pytest.raises(ValidationError, match="서로 다른 말"):
        ChoiceRequest.model_validate(data)


# ── 원장을 따로 확인하는 쪽이 할인을 알아보는가 ─────────────────────────


def test_audit_recomputes_the_discount_on_its_own(example_copy):
    edit(venue_file(example_copy, "geumryong"), add_tea)
    give(example_copy, "geumryong", promo())
    played = play(example_copy, lambda visit, request: answer(request, "geumryong", "geumryong-o1", [("tea", 1)]))
    assert audit(played) == []
    # 업장 정의의 프로모션이 원장과 다르면 잡는다: 할인 폭이 다르다, 프로모션이 없다, 조건이 맞지 않는다.
    assert audit(played, venue=lambda d: d["promotions"][0]["benefit"].update(value=20)) == ["금액 불일치"]
    assert audit(played, venue=lambda d: d.update(promotions=[])) == ["금액 불일치"]
    assert audit(played, venue=lambda d: d["promotions"][0]["conditions"].update(day_type="weekday")) == ["금액 불일치"]
    assert audit(played, venue=lambda d: d["promotions"][0].update(applies_to=["course-b"])) == ["금액 불일치"]
    # 금액 할인으로 바꿔도 같은 60000 이면 원장과 맞는다.
    same = {"type": "discount_amount", "value": 60000}
    assert audit(played, venue=lambda d: d["promotions"][0].update(benefit=same)) == []
    # 추가 상품의 줄에 할인이 적혀 있으면 잡는다 (아직 적용하지 않기로 한 것이다).
    rows = [r.model_copy(update={"discount": 1000, "paid": r.paid - 1000}) if r.product_id == "tea" else r for r in played.rows]
    assert audit(played, rows=rows) == ["금액 불일치"]


def test_audit_reads_the_period_only_when_the_visit_has_a_month(example_copy):
    give(example_copy, "geumryong", promo(period={"from": "2026-12-01", "to": "2027-01-31"}))
    played = play(example_copy, pick_geumryong)
    assert audit(played) == []

    def manual(month: int) -> dict:
        """같은 방문을 화면에서 달을 직접 넣어 돌린 것으로 바꾼다. 후보는 그대로 둔다."""
        saved = {}
        for key, entry in played.saved.items():
            data = entry.model_dump(mode="json")
            data["request"]["condition"].update(condition_id="manual-1", month=month)
            saved[key] = type(entry).model_validate(data)
        rows = [r.model_copy(update={"condition_id": "manual-1", "visit_id": f"{r.persona_id}__manual-1"}) for r in played.rows]
        return {"rows": rows, "saved": saved}

    assert audit(played, **manual(1)) == []
    assert audit(played, **manual(7)) == ["금액 불일치"]  # 7월은 기간 밖이라 할인이 없어야 한다


# ── 상황을 돌린다: 같은 페르소나, 같은 조건, 같은 가중치 ────────────────

FOUR = dict(persona_ids=(ELDERS, KIDS), condition_ids=(DINNER, LUNCH))


def test_four_kinds_of_scenario_run_with_the_same_personas_conditions_and_weights(example_copy):
    venue_files = files_hash(example_copy / "data" / "venues")
    base = play(example_copy, pick_geumryong, **FOUR)
    our_promo = write_scenario(
        example_copy,
        "our_promo",
        {"op": "add_promotion", "venue_id": "geumryong", "promotion": promo(day_type="weekend")},
        scenario_id="geumryong-weekend-sale",
    )
    played = {
        scenario_id: play_scenario(example_copy, scenario_id, pick_geumryong, base, now=NOW + timedelta(hours=hour))
        for hour, scenario_id in enumerate((PRICE_UP, our_promo, COMPETITOR_DISCOUNT), 1)
    }

    kinds = {read_model(example_copy / "scenarios" / f"{s}.json", Scenario).kind for s in played}
    assert kinds | {"baseline"} == {"baseline", "our_price", "our_promo", "competitor"}
    represented = {row.visit_id: row.represented for row in base.rows}
    assert len(represented) == 4 and all(value > 0 for value in represented.values())
    for scenario_id, result in played.items():
        record = result.record
        assert (record.scenario_id, record.status, record.counts.failed) == (scenario_id, "ok", 0)
        assert record.weights_from == base.run_dir.name
        assert record.persona_ids == base.record.persona_ids
        assert record.condition_ids == base.record.condition_ids
        assert record.weights == base.record.weights
        assert {row.visit_id: row.represented for row in result.rows} == represented
        assert result.violations() == []

    paid = {name: [(r.visit_id, r.list_price, r.discount, r.paid) for r in result.rows] for name, result in played.items()}
    assert [(r.list_price, r.discount, r.paid) for r in base.rows] == [(150000, 0, 600000)] * 4
    assert [row[1:] for row in paid[PRICE_UP]] == [(165000, 0, 660000)] * 4
    assert [row[1:] for row in paid[our_promo]] == [(150000, 60000, 540000)] * 4
    # 경쟁 업장만 바뀐 상황에서 금룡을 고른 줄은 기준과 같다.
    assert [row[1:] for row in paid[COMPETITOR_DISCOUNT]] == [(150000, 0, 600000)] * 4

    # 업장 정의 파일은 바뀌지 않는다.
    assert files_hash(example_copy / "data" / "venues") == venue_files
    no_format_errors(example_copy)


def test_competitor_promotion_and_price_can_be_changed_and_run(example_copy):
    base = play(example_copy, pick_geumryong)
    discount = play_scenario(example_copy, COMPETITOR_DISCOUNT, pick_venue("examplehotel-chinese"), base)
    (row,) = discount.rows
    assert (row.choice_kind, row.venue_id, row.list_price, row.discount, row.paid) == (
        "competitor", "examplehotel-chinese", 140000, 56000, 504000,
    )
    assert (row.revenue_net, row.weighted_revenue) == (0, 0)  # 경쟁 업장에 낸 돈은 워커힐 매출이 아니다
    assert shown(discount.requests[f"{ELDERS}__{DINNER}"], "examplehotel-chinese") == [("weekend-10", True)]
    assert shown(discount.requests[f"{ELDERS}__{DINNER}"], "geumryong") == []

    cheaper = write_scenario(
        example_copy,
        "competitor",
        {"op": "set_price", "venue_id": "examplehotel-chinese", "product_id": "course", "price": 100000},
        {"op": "change_price_pct", "venue_id": "examplehotel-buffet", "product_id": None, "pct": -20},
        scenario_id="competitor-price-cut",
    )
    cut = play_scenario(example_copy, cheaper, pick_venue("examplehotel-chinese"), base, now=NOW + timedelta(hours=2))
    (row,) = cut.rows
    assert (row.venue_id, row.list_price, row.discount, row.paid, row.revenue_net) == ("examplehotel-chinese", 100000, 0, 400000, 0)
    buffet = cut.requests[f"{ELDERS}__{DINNER}"].candidate("examplehotel-buffet")
    assert buffet.options[0].lines[0].unit_price == 136000  # 170000 을 20% 내린 값
    assert discount.violations() == [] and cut.violations() == []
    no_format_errors(example_copy)


def test_scenario_can_add_and_remove_products(example_copy):
    base = play(example_copy, pick_geumryong)
    menu = write_scenario(
        example_copy,
        "our_price",
        {"op": "remove_product", "venue_id": "geumryong", "product_id": "course-a"},
        {"op": "add_product", "venue_id": "geumryong", "product": new_product("course-c", price=170000)},
        scenario_id="geumryong-new-course",
    )
    played = play_scenario(example_copy, menu, lambda visit, request: answer(request, "geumryong", "geumryong-o2"), base)
    request = played.requests[f"{ELDERS}__{DINNER}"]
    assert [[line.product_id for line in o.lines] for o in request.candidate("geumryong").options] == [["course-b"], ["course-c"]]
    (row,) = played.rows
    assert (row.product_id, row.list_price, row.paid, row.status) == ("course-c", 170000, 680000, "ok")
    assert played.violations() == []
    no_format_errors(example_copy)  # 형식 검사는 상황이 더한 상품을 그 상황의 원장에서 받는다


# ── 기준 실행이 있어야 하고, 그 뒤로 달라진 것이 없어야 한다 ────────────


def test_scenario_cannot_run_without_a_finished_baseline_run(example_copy):
    with pytest.raises(ValueError, match="기준 상황을 먼저"):
        run_scenario(example_copy, PRICE_UP)
    with pytest.raises(FileNotFoundError, match="실행 기록이 없다"):
        run_scenario(example_copy, PRICE_UP, weights_from="20200101-000000-baseline")
    with pytest.raises(ValueError, match="run_id 가 아니다"):
        run_scenario(example_copy, PRICE_UP, weights_from="../../private/runs/20200101-000000-baseline")
    with pytest.raises(ValueError, match="기준 상황의 실행이 아니다"):
        run_scenario(example_copy, PRICE_UP, weights_from=COMPETITOR_RUN)

    base = play(example_copy, pick_geumryong)
    edit(base.run_dir / "run.json", lambda d: d.update(status="failed"))
    with pytest.raises(ValueError, match="끝까지 돌지 않았다"):
        run_scenario(example_copy, PRICE_UP, weights_from=base.run_dir.name)


def test_weights_come_only_from_the_baseline_run(example_copy):
    base = play(example_copy, pick_geumryong)
    with pytest.raises(ValueError, match="weights 를 따로 주지 않는다"):
        run_scenario(example_copy, PRICE_UP, weights_from=base.run_dir.name, weights=base.record.weights)
    with pytest.raises(ValueError, match="weights_from 을 주지 않는다"):
        run_scenario(example_copy, "baseline", weights_from=base.run_dir.name)


@pytest.mark.parametrize(
    "more, message",
    [
        ({"persona_ids": [ELDERS, KIDS]}, "기준 실행과 페르소나의 목록이 다르다"),
        ({"condition_ids": [LUNCH]}, "기준 실행과 방문 조건의 목록이 다르다"),
        ({"model": "another-model"}, "llm.model"),
        ({"provider": "another"}, "llm.provider"),
        ({"prompt_version": "p2"}, "llm.prompt_version"),
        ({"venue_ids": ["geumryong", "examplehotel-chinese"]}, "venues"),
    ],
)
def test_scenario_must_run_on_what_the_baseline_ran_on(example_copy, more, message):
    base = play(example_copy, pick_geumryong)
    with pytest.raises(ValueError, match=message):
        run_scenario(example_copy, PRICE_UP, weights_from=base.run_dir.name, **more)
    assert not (base.run_dir.parent / f"{NOW + timedelta(hours=2):%Y%m%d-%H%M%S}-{PRICE_UP}").exists()


@pytest.mark.parametrize(
    "path, change, changed",
    [
        ("personas/family-elders.json", budget(typical=100000), "personas"),
        ("data/venues/thebuffet.json", lambda d: d.update(cuisine="뷔페 (고침)"), "venues"),
        ("data/evidence/vocab.json", lambda d: d["pain_points"].append("새 라벨"), "vocab"),
        ("engine/conditions.json", lambda d: d["assumed_splits"][0].update(note="고침"), "conditions"),
    ],
)
def test_scenario_is_refused_when_an_input_changed_after_the_baseline_run(example_copy, path, change, changed):
    base = play(example_copy, pick_geumryong)
    assert run_scenario(example_copy, PRICE_UP, weights_from=base.run_dir.name).is_dir()  # 그대로면 돌아간다
    edit(example_copy / path, change)
    with pytest.raises(ValueError, match=f"달라진 것이 있다: {changed}"):
        run_scenario(example_copy, PRICE_UP, weights_from=base.run_dir.name, now=NOW + timedelta(hours=3))


def test_scenario_is_refused_when_the_prompt_text_changed_after_the_baseline_run(example_copy):
    """두 실행이 모두 프롬프트를 읽었으면(LLM 을 부를 수 있게 돌렸으면) 프롬프트의 글도 견준다."""
    with_llm = dict(data_mode="sample", provider=PROVIDER, model=MODEL, prompt_version="p1", answers=[], engine_commit="0000000")
    base = run(example_copy, now=NOW, persona_ids=[ELDERS], condition_ids=[DINNER], llm=Fake(), **with_llm)
    first = run(example_copy, now=NOW + timedelta(hours=1), scenario_id=PRICE_UP, weights_from=base.name, llm=Fake(), **with_llm)
    assert read_model(first / "run.json", RunRecord).counts.model_dump() == {"visits": 1, "failed": 0}

    prompt = example_copy / "personas" / "prompts" / "p1.md"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "\n한 줄을 더했다.\n", encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="달라진 것이 있다: prompt"):
        run(example_copy, now=NOW + timedelta(hours=2), scenario_id=PRICE_UP, weights_from=base.name, llm=Fake(), **with_llm)
    # 재생만 하는 실행은 프롬프트를 읽지 않아 견줄 것이 없다. 저장된 응답은 프롬프트의 판 이름으로 갈린다.
    assert run(example_copy, now=NOW + timedelta(hours=3), scenario_id=PRICE_UP, weights_from=base.name, **with_llm).is_dir()


def test_same_personas_and_conditions_may_be_named_again(example_copy):
    base = play(example_copy, pick_geumryong, **FOUR)
    run_dir = run_scenario(
        example_copy, PRICE_UP, weights_from=base.run_dir.name, persona_ids=[KIDS, ELDERS], condition_ids=[LUNCH, DINNER]
    )
    record = read_model(run_dir / "run.json", RunRecord)
    # 순서는 기준 실행의 것을 따른다.
    assert (record.persona_ids, record.condition_ids) == (base.record.persona_ids, base.record.condition_ids)
    assert record.counts.model_dump() == {"visits": 4, "failed": 4}  # 답을 두지 않아 모두 실패로 남는다


def test_latest_finished_baseline_run_is_found(example_copy):
    assert latest_baseline_run(example_copy, "sample") == BASELINE_RUN  # 예시 묶음에 든 기준 실행
    base = play(example_copy, pick_geumryong)
    play_scenario(example_copy, PRICE_UP, pick_geumryong, base)
    (base.run_dir.parent / "20261119-000000-baseline").mkdir()  # 실행 기록이 없는 폴더는 건너뛴다
    assert latest_baseline_run(example_copy, "sample") == base.run_dir.name
    edit(base.run_dir / "run.json", lambda d: d.update(status="failed"))
    assert latest_baseline_run(example_copy, "sample") == BASELINE_RUN
    assert latest_baseline_run(example_copy, "private") is None


# ── 방문 조건의 달과 상황 ───────────────────────────────────────────────


def test_month_drops_venues_and_products_not_sold_then_also_after_a_scenario(example_copy):
    edit(venue_file(example_copy, "examplehotel-chinese"), lambda d: d.update(months=[11, 12, 1, 2]))
    winter = write_scenario(
        example_copy,
        "our_price",
        {"op": "add_product", "venue_id": "geumryong", "product": new_product("winter-course", price=180000, months=[12, 1, 2])},
        scenario_id="geumryong-winter-course",
    )

    def offered(month: int | None) -> dict[str, list[str]]:
        request = request_for(example_copy, winter, venue_ids=["geumryong", "examplehotel-chinese"], month=month)
        return {c.venue_id: [line.product_id for o in c.options for line in o.lines] for c in request.candidates}

    assert offered(7) == {"geumryong": ["course-a", "course-b"]}  # 경쟁 업장은 7월에 쉬고, 겨울 코스는 팔지 않는다
    assert offered(11) == {"geumryong": ["course-a", "course-b"], "examplehotel-chinese": ["course"]}
    assert offered(12) == {"geumryong": ["course-a", "course-b", "winter-course"], "examplehotel-chinese": ["course"]}
    # 달이 없으면 일 년 전체로 본다. 일부 달에만 파는 것도 후보에 있고 몫으로 센다 (T04).
    assert offered(None) == {"geumryong": ["course-a", "course-b", "winter-course"], "examplehotel-chinese": ["course"]}


def test_seasonal_product_added_by_a_scenario_is_counted_by_its_share(example_copy):
    base = play(example_copy, pick_geumryong)
    winter = write_scenario(
        example_copy,
        "our_price",
        {"op": "add_product", "venue_id": "geumryong", "product": new_product("winter-course", price=180000, months=[12, 1, 2])},
        scenario_id="geumryong-winter-course",
    )
    played = play_scenario(example_copy, winter, lambda visit, request: answer(request, "geumryong", "geumryong-o3"), base)
    bought, gap = played.rows
    assert (bought.product_id, bought.counted_share, bought.paid) == ("winter-course", 0.25, 720000)
    assert (gap.choice_kind, gap.counted_share) == ("none", 0.75)
    assert played.violations() == []
    no_format_errors(example_copy)


# ── 문서의 예시가 그대로 나오는가 ───────────────────────────────────────


def test_engine_makes_the_second_example_run(example_copy):
    """예시 묶음의 둘째 실행(경쟁 업장의 할인)을 엔진이 그대로 만들어 낸다 (docs/FORMATS.md 10.2절의 둘째 줄).

    기준 실행을 엔진으로 먼저 만들고(가중치는 엔진이 가상 예시 값에서 낸다), 그 실행의 가중치로 상황을 돌려 저장된 응답을 재생한다.
    엔진이 상황을 적용해 만든 요청의 해시가 예시와 같아야 재생된다. 다른 칸은 새로 불렀는지 재생했는지뿐이다.
    새로 부른 것까지 글자 그대로 만드는 것은 tests/test_weights.py 의 test_engine_writes_both_example_runs_as_they_are 가 본다.
    """
    runs = example_copy / "engine" / "samples" / "runs"
    kept = example_copy.parent / "kept"
    kept.mkdir()
    for name in (BASELINE_RUN, COMPETITOR_RUN):
        shutil.move(runs / name, kept / name)
    same = dict(
        data_mode="sample",
        provider="anthropic",
        model="claude-opus-5-5",
        prompt_version="p1",
        venue_ids=["geumryong", "examplehotel-chinese"],
        engine_commit="0000000",
    )
    base = run(
        example_copy,
        now=datetime(2026, 11, 17, 10, 15, 0, tzinfo=KST),
        answers=[kept / BASELINE_RUN / "llm"],
        persona_ids=[ELDERS],
        condition_ids=[DINNER],
        **same,
    )
    again = run(
        example_copy,
        now=datetime(2026, 11, 17, 10, 30, 0, tzinfo=KST),
        answers=[kept / COMPETITOR_RUN / "llm"],
        scenario_id=COMPETITOR_DISCOUNT,
        weights_from=base.name,
        **same,
    )

    old = kept / COMPETITOR_RUN
    assert again.name == COMPETITOR_RUN
    assert (again / "ledger.csv").read_bytes() == (old / "ledger.csv").read_bytes().replace(b",new,", b",replay,")
    assert {p.name: p.read_bytes() for p in (again / "llm").iterdir()} == {p.name: p.read_bytes() for p in (old / "llm").iterdir()}
    record, example = load_json(again / "run.json"), load_json(old / "run.json")
    for key in ("run_id", "created_at", "data_mode", "scenario_id", "persona_ids", "condition_ids", "base_profile_mode"):
        assert record[key] == example[key], key
    for key in ("weights", "weights_from", "filled_products", "skipped_products", "counts", "status"):
        assert record[key] == example[key], key
    assert record["inputs"] == {k: v for k, v in example["inputs"].items() if k != "prompt"}
    assert (record["llm"]["calls_new"], record["llm"]["calls_replayed"]) == (0, 1)
    no_format_errors(example_copy)


# ── 실행하는 명령 ───────────────────────────────────────────────────────


@pytest.fixture
def clean_env(monkeypatch):
    """이 PC 의 .env 와 환경 변수가 테스트에 섞이지 않게 한다."""
    for name in LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "load_dotenv", lambda *args, **kwargs: False)
    return monkeypatch


def command(root: Path, *more: str) -> int:
    # 예시 묶음에는 p1 만 있다. 명령의 기본값은 팀이 쓰는 판이다 (T108)
    return cli.main(["--data", "sample", "--root", str(root), "--replay-only", "--prompt", "p1", *more])


def test_command_runs_a_scenario_on_the_latest_finished_baseline_run(example_copy, clean_env, capsys):
    runs = example_copy / "engine" / "samples" / "runs"

    # 예시 묶음에 든 기준 실행은 업장 두 곳만 읽어 돌린 것이라(--venues), 업장을 모두 읽는 이 실행과 입력의 해시가 다르다. 그 실행으로는 돌리지 않는다.
    assert command(example_copy, "--scenario", COMPETITOR_DISCOUNT) == cli.EXIT_FAILED
    assert "달라진 것이 있다" in capsys.readouterr().err
    kept = example_copy.parent / "kept"
    kept.mkdir()
    for name in (BASELINE_RUN, COMPETITOR_RUN):
        shutil.move(runs / name, kept / name)
    assert command(example_copy, "--scenario", COMPETITOR_DISCOUNT) == cli.EXIT_FAILED
    assert "기준 상황을 먼저" in capsys.readouterr().err
    assert not list(runs.iterdir())

    def records() -> list[RunRecord]:
        return [read_model(p / "run.json", RunRecord) for p in sorted(runs.iterdir())]

    clean_env.setattr(cli, "datetime", Clock())  # 부를 때마다 5분씩 가는 시계
    two_venues = ("--venues", "geumryong", "examplehotel-chinese")
    # 재생만 했고 저장된 응답이 없어 방문이 실패로 남은 기준 실행이다.
    assert command(example_copy, "--personas", ELDERS, "--conditions", DINNER, *two_venues) == cli.EXIT_OK
    (failed_base,) = records()
    assert failed_base.counts.failed == 1
    capsys.readouterr()

    # 실패한 방문이 있는 기준 실행으로는 상황을 돌리지 않고 그 까닭을 알린다 (11-16 회의).
    assert command(example_copy, "--scenario", COMPETITOR_DISCOUNT, *two_venues) == cli.EXIT_FAILED
    said = capsys.readouterr().err
    assert f"기준 실행 '{failed_base.run_id}' 에 실패한 방문이 1건 있어 상황을 돌리지 않는다" in said
    assert "fail_reason" in said and "그 방문만 LLM 을 새로 부른다" in said and "replay 인 실패는" in said
    assert records() == [failed_base]  # 실행 폴더를 만들지 않았다

    # 저장된 응답이 있으면 기준 실행이 실패 없이 끝난다. 적지 않으면 끝까지 돈 가장 새 기준 실행을 쓴다.
    base_answers = ("--answers", str(kept / BASELINE_RUN / "llm"))
    assert command(example_copy, "--personas", ELDERS, "--conditions", DINNER, *two_venues, *base_answers) == cli.EXIT_OK
    newer = records()[-1]
    assert (newer.scenario_id, newer.counts.failed) == (BASELINE_ID, 0)
    capsys.readouterr()
    scenario_answers = ("--answers", str(kept / COMPETITOR_RUN / "llm"))
    assert command(example_copy, "--scenario", COMPETITOR_DISCOUNT, *two_venues, *scenario_answers) == cli.EXIT_OK
    assert f"기준 실행 {newer.run_id}" in capsys.readouterr().out
    record = records()[-1]
    assert (record.scenario_id, record.weights_from, record.counts.failed) == (COMPETITOR_DISCOUNT, newer.run_id, 0)
    assert (record.persona_ids, record.condition_ids, record.weights) == ([ELDERS], [DINNER], newer.weights)

    # 기준 실행을 직접 가리킬 수도 있다. 실패한 방문이 있는 실행이나 없는 실행을 가리키면 돌리지 않는다.
    assert command(example_copy, "--scenario", PRICE_UP, *two_venues, "--baseline", newer.run_id) == cli.EXIT_OK
    assert records()[-1].weights_from == newer.run_id
    assert command(example_copy, "--scenario", PRICE_UP, *two_venues, "--baseline", failed_base.run_id) == cli.EXIT_FAILED
    assert "실패한 방문이 1건 있어" in capsys.readouterr().err
    assert command(example_copy, "--scenario", PRICE_UP, "--baseline", "20200101-000000-baseline") == cli.EXIT_FAILED
    no_format_errors(example_copy)
