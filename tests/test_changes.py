"""매출 변화 나누기 (T210, docs/FORMATS.md 10.6절).

방문마다 기준과 상황에서 간 곳을 견줘, 워커힐 업장마다의 변화를 새로 들어온·옮겨 온·잃은 매출, 가격 효과, 주문 변화로 나눈다.
원장 줄은 모두 지어낸 값이다.
"""

import pytest

from engine.changes import decompose
from engine.formats import LedgerRow, read_model
from engine.formats.changes import Changes
from tests.conftest import COMPETITOR_RUN, EXAMPLE_ROOT
from tests.test_engine import pick_geumryong, play
from tests.test_scenarios import PRICE_UP, play_scenario
from tools.check_formats import check

RUNS = EXAMPLE_ROOT / "engine" / "samples" / "runs"
CONDITION = "meal-dinner-weekend"


def row(persona: str, kind: str, venue: str | None = None, product: str = "course", quantity: int = 2, price: int = 110000,
        discount: int = 0, teams: float = 10.0, *, failed: bool = False, run: str = "r") -> LedgerRow:
    """원장의 한 줄 (지어낸 것). 워커힐 업장이면 낸 금액 ÷ 1.1 이 세금을 뺀 매출이다."""
    paid = quantity * price - discount if kind != "none" else 0
    net = round(paid / 1.1) if kind == "walkerhill" else 0
    if failed:
        kind, venue, product, quantity, price, discount, paid, net = "none", None, None, 0, 0, 0, 0, 0
    elif kind == "none":
        venue, product, quantity, price, discount = None, None, 0, 0, 0
    return LedgerRow.model_validate(
        {
            "run_id": run,
            "scenario_id": "baseline",
            "visit_id": f"{persona}__{CONDITION}",
            "persona_id": persona,
            "customer_group": "가족·친족",
            "condition_id": CONDITION,
            "choice_kind": kind,
            "venue_id": venue,
            "product_id": product,
            "quantity": quantity,
            "unit": "1인" if venue else None,
            "list_price": price,
            "discount": discount,
            "paid": paid,
            "revenue_net": net,
            "represented": teams,
            "counted_share": 1.0,
            "weighted_revenue": net * teams,
            "reason_labels": [],
            "reason_text": None,
            "used_attributes": [],
            "llm_call": None if failed or kind == "none" else "replay",
            "request_hash": None if failed or kind == "none" else "0123456789abcdef",
            "status": "failed" if failed else "ok",
            "fail_reason": "답 없음" if failed else None,
        }
    )


def test_five_parts_add_up_to_the_change_of_each_venue():
    """FORMATS 10.6절의 예와 같은 다섯 방문. 갈래를 더하면 업장의 변화이고, 업장을 더하면 워커힐의 변화다."""
    base = [
        row("a", "walkerhill", "thebuffet", "adult", 2, 352000, teams=100),  # 그대로, 값만 오름 → 가격 효과
        row("b", "walkerhill", "thebuffet", "adult", 2, 352000, teams=50),  # 경쟁으로 → 잃은
        row("c", "walkerhill", "thebuffet", "adult", 4, 176000, teams=80),  # 피자힐로 → 워커힐 안에서 옮김
        row("d", "none", teams=30),  # 이용 안 함 → 금룡 → 새로 들어옴
        row("e", "walkerhill", "pizzahill", "set", 1, 110000, teams=40),  # 같은 곳, 다른 주문 → 주문 변화
    ]
    scen = [
        row("a", "walkerhill", "thebuffet", "adult", 2, 396000, teams=100, run="s"),
        row("b", "competitor", "rival-buffet", "buffet", 2, 300000, teams=50, run="s"),
        row("c", "walkerhill", "pizzahill", "set", 1, 220000, teams=80, run="s"),
        row("d", "walkerhill", "geumryong", "course", 2, 165000, teams=30, run="s"),
        row("e", "walkerhill", "pizzahill", "single", 1, 66000, teams=40, run="s"),
    ]
    found = decompose(base, scen, "base", "scen")
    venues = {v.venue_id: v.parts for v in found.venues}
    assert venues["thebuffet"].price == 100 * (720000 - 640000)
    assert venues["thebuffet"].to_competitor == -50 * 640000
    assert venues["thebuffet"].to_walkerhill == -80 * 640000
    assert venues["pizzahill"].from_walkerhill == 80 * 200000
    assert venues["pizzahill"].order == 40 * (60000 - 100000)
    assert venues["geumryong"].new == 30 * 300000
    for venue in found.venues:
        assert venue.after - venue.before == venue.parts.total
    assert found.walkerhill.total == sum(v.parts.total for v in found.venues)
    total_before = sum(r.weighted_revenue for r in base if r.choice_kind == "walkerhill")
    total_after = sum(r.weighted_revenue for r in scen if r.choice_kind == "walkerhill")
    assert found.walkerhill.total == total_after - total_before
    assert found.excluded_visits == []


def test_same_order_with_a_discount_is_a_price_effect_and_from_competitor_is_moved_in():
    base = [row("a", "walkerhill", "geumryong"), row("b", "competitor", "rival", teams=5), row("c", "walkerhill", "geumryong")]
    scen = [
        row("a", "walkerhill", "geumryong", discount=22000, run="s"),  # 같은 주문, 할인만 → 가격 효과
        row("b", "walkerhill", "geumryong", teams=5, run="s"),  # 경쟁에서 → 옮겨 옴
        row("c", "none", run="s"),  # 이용 안 함으로 → 잃음
    ]
    parts = decompose(base, scen, "base", "scen").venues[0].parts
    assert parts.price == -10 * 20000 and parts.order == 0
    assert parts.from_competitor == 5 * 200000
    assert parts.to_none == -10 * 200000


def test_visits_failed_in_either_run_are_left_out_of_both():
    base = [row("a", "walkerhill", "geumryong"), row("b", "walkerhill", "geumryong")]
    scen = [row("a", "walkerhill", "geumryong", failed=True, run="s"), row("b", "walkerhill", "geumryong", run="s")]
    found = decompose(base, scen, "base", "scen")
    assert found.excluded_visits == [f"a__{CONDITION}"]
    assert found.walkerhill.total == 0 and found.venues[0].before == found.venues[0].after == 10 * 200000


def test_parts_that_do_not_add_up_are_refused():
    found = decompose([row("a", "walkerhill", "geumryong")], [row("a", "none", run="s")], "base", "scen")
    data = found.model_dump(mode="json")
    data["walkerhill"]["to_none"] += 1
    with pytest.raises(ValueError, match="갈래를 더한 값이 total 과 다르다"):
        Changes.model_validate(data)


def test_example_scenario_run_has_the_changes_the_engine_writes():
    """예시 묶음의 경쟁 업장 할인 실행: 어르신 가족이 금룡에서 경쟁 중식으로 옮겨 금룡의 매출을 모두 잃었다."""
    changes = read_model(RUNS / COMPETITOR_RUN / "changes.json", Changes)
    (geumryong,) = changes.venues
    assert geumryong.venue_id == "geumryong" and geumryong.after == 0
    assert geumryong.parts.to_competitor == -geumryong.before == changes.walkerhill.total


def test_scenario_run_writes_changes_and_the_checker_compares_them_with_the_ledgers(example_copy):
    base = play(example_copy, pick_geumryong)
    played = play_scenario(example_copy, PRICE_UP, pick_geumryong, base)
    path = played.run_dir / "changes.json"
    changes = read_model(path, Changes)
    assert changes.baseline_run_id == base.run_dir.name and changes.run_id == played.run_dir.name
    assert not (base.run_dir / "changes.json").exists()  # 기준 실행에는 없다
    assert [str(p) for p in check(example_copy, strict=True)] == []
    # 손으로 고치면 형식 검사가 원장으로 다시 낸 것과 견줘 막는다.
    data = changes.model_dump(mode="json")
    data["visits"][0]["represented"] += 1
    path.write_text(Changes.model_validate(data).model_dump_json(indent=2), encoding="utf-8")
    assert any("원장으로 다시 나눈 것과 다르다" in str(p) for p in check(example_copy, strict=True))


def test_format_doc_example_is_the_example_run():
    """FORMATS.md 10.6절의 JSON 예시는 예시 묶음의 changes.json 과 같다."""
    import json
    import re

    doc = (EXAMPLE_ROOT.parents[2] / "docs" / "FORMATS.md").read_text(encoding="utf-8")
    section = doc[doc.index("### 10.6") :]
    example = re.search(r"```json\n(.*?)\n```", section, re.S).group(1)
    assert json.loads(example) == json.loads((RUNS / COMPETITOR_RUN / "changes.json").read_text(encoding="utf-8"))


def test_visit_unrelated_to_the_changed_venue_keeps_the_baseline_answer(example_copy):
    """바꾼 업장(금룡)이 기준과 상황 어느 선택에도 끼지 않으면 원장은 기준의 답이다 (T210 의 임시 규칙).

    요청은 금룡의 가격이 달라 기준과 다르다. 상황의 답이 경쟁 뷔페로 옮겨도 그 변화는 기준의 답으로 덮이고 실행 기록에 남는다.
    """
    from tests.test_engine import first_option

    base = play(example_copy, lambda visit_id, request: first_option(request, "thebuffet"))
    played = play_scenario(example_copy, PRICE_UP, lambda visit_id, request: first_option(request, "examplehotel-buffet"), base)
    (visit,) = {row.visit_id for row in played.rows}
    assert played.record.baseline_answers == [visit]
    assert [(r.venue_id, r.product_id, r.request_hash) for r in played.rows] == [(r.venue_id, r.product_id, r.request_hash) for r in base.rows]
    assert read_model(played.run_dir / "changes.json", Changes).walkerhill.total == 0
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_visit_that_chooses_the_changed_venue_keeps_its_own_answer(example_copy):
    """상황에서 바꾼 업장을 고르면 그것이 상황의 효과다. 기준의 답으로 덮지 않는다."""
    from tests.test_engine import first_option

    base = play(example_copy, lambda visit_id, request: first_option(request, "thebuffet"))
    played = play_scenario(example_copy, PRICE_UP, pick_geumryong, base)
    assert played.record.baseline_answers == []
    assert {r.venue_id for r in played.rows} == {"geumryong"}
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_promo_tells_whether_a_discounted_visit_would_have_come_anyway():
    """상황에서 워커힐 업장의 할인을 받은 방문이 기준에서도 그 업장에 오던 방문인가 (T215, T130 ③, PRD 3절의 "혜택이 없어도 올 고객")."""
    from engine.changes import _promo, _Visit

    at_geumryong = _Visit(kind="walkerhill", venue_id="geumryong")
    with_discount = _Visit(kind="walkerhill", venue_id="geumryong", discounted=True)
    assert _promo(at_geumryong, with_discount) == "would_come"
    assert _promo(_Visit(kind="competitor", venue_id="examplehotel-chinese"), with_discount) == "drawn"
    assert _promo(_Visit(), with_discount) == "drawn"
    assert _promo(_Visit(kind="walkerhill", venue_id="thebuffet"), with_discount) == "drawn"
    assert _promo(at_geumryong, at_geumryong) == "none"
    assert _promo(at_geumryong, _Visit(kind="competitor", venue_id="examplehotel-chinese")) == "none"
