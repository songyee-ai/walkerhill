"""6단계의 되돌려 맞혀 보기 (T224, engine/backtest.py, docs/FORMATS.md 10.9절).

가상 예시 값에 반응을 일부러 심어 채점이 방향과 크기를 잡아내는지, 심지 않으면 잡지 않는지 본다.
예시 묶음의 사본에 워커힐 업장 하나(온달, 금룡을 베낌)를 더해 견줄 업장을 두고, 테스트가 끼운 공급자가
가격이 오르면 점수를 낮추는 답을 준다. 엔진은 사건 앞 달까지의 자료로(`data_until`) 돈다. LLM 을 부르지 않는다.
"""

import json
import shutil
from pathlib import Path

import pytest

from engine import backtest
from engine.backtest import (
    MIN_EVENTS,
    Step,
    did,
    direction,
    draft_events,
    find_changes,
    magnitude_correct,
    score,
    unit_prices,
    verdict,
)
from engine.formats import ChoiceRequest, RunRecord, SummaryRow
from engine.formats.backtest import BacktestEvents, BacktestResult
from engine.formats.io import read_model
from engine.llm import LlmReply
from engine.runner import latest_baseline_run, load_inputs, run
from tests.conftest import EXAMPLE_ROOT, load_json, save_json
from tests.test_check_shares import scored
from tests.test_engine import DINNER, MODEL, NOW, PROVIDER
from tools.check_formats import check

ELDERS = "family-elders"
PROMPT = "p4"
SCENARIO = "geumryong-backtest-price-up"
EVENT_MONTH = 7
PRICE_PCT = 10

# ── 셈 ────────────────────────────────────────────────────────────────────


def test_did_divides_out_the_common_change():
    # 사건 업장 −20%, 견줄 업장 −10% (철 효과): 가격 반응은 0.8 ÷ 0.9 − 1.
    assert did(100, 80, 1000, 900) == pytest.approx(0.8 / 0.9 - 1)
    assert did(0, 80, 1000, 900) is None
    assert did(100, 80, 1000, 0) is None


def test_direction_uses_the_band():
    assert direction(-0.02, 0.03) == "none"
    assert direction(-0.04, 0.03) == "down"
    assert direction(0.04, 0.03) == "up"
    assert direction(0.0, 0.0) == "none"


def test_magnitude_is_right_between_half_and_double():
    assert magnitude_correct(-0.10, -0.12)[1]  # 0.83 배
    assert magnitude_correct(-0.06, -0.12)[1]  # 0.5 배 (끝 포함)
    assert magnitude_correct(-0.24, -0.12)[1]  # 2 배 (끝 포함)
    assert not magnitude_correct(-0.05, -0.12)[1]
    assert not magnitude_correct(-0.30, -0.12)[1]
    assert not magnitude_correct(0.10, -0.12)[1]  # 방향이 반대


def test_verdict_follows_the_criteria():
    assert verdict(MIN_EVENTS - 1, MIN_EVENTS - 1, 3, 3) == "too_few"
    assert verdict(6, 5, 3, 2) == "pass"  # 방향 5/6, 크기 2/3 (문서의 예)
    assert verdict(6, 4, 3, 2) == "pass"  # 방향 4/6 = 2/3 (끝 포함)
    assert verdict(6, 3, 3, 3) == "fail"  # 방향 절반
    assert verdict(6, 6, 3, 1) == "fail"  # 크기 1/3
    assert verdict(6, 6, 0, 0) == "pass"  # 크기를 채점한 사건이 없으면 방향만 본다
    assert verdict(6, 6, 2, 1) == "pass"  # 크기 절반 (끝 포함)


# ── 사건 찾기의 정확도 ────────────────────────────────────────────────────

# 할인 쿠폰이 섞여 달마다 ±1% 안팎으로 흔들리는 평균 가격 (상품마다 차례를 밀어 쓴다).
WOBBLE = [0.0, 0.006, -0.008, 0.004, -0.005, 0.009, -0.003, 0.007, -0.006, 0.002, -0.009, 0.005]


def _rows(prices: dict[tuple[str, str], list[float]]) -> list[SummaryRow]:
    rows = []
    for i, ((venue, product), series) in enumerate(prices.items()):
        for month, price in enumerate(series, start=1):
            unit = price * (1 + WOBBLE[(month + 3 * i) % 12])
            qty = 100
            paid = round(unit * qty)
            rows.append(
                SummaryRow(
                    customer_group="가족·친족",
                    venue_id=venue,
                    product_id=product,
                    occasion="meal",
                    meal=None,
                    day_type="weekend",
                    month=month,
                    unit="1인",
                    quantity=qty,
                    people=qty,
                    paid=paid,
                    revenue_net=round(paid / 1.1),
                    price_unconfirmed="N",
                )
            )
    return rows


def _series(level: float, changes: dict[int, float] | None = None, step: tuple[int, float] | None = None) -> list[float]:
    """한 해의 가격. `step` 은 (그 달부터, 배수), `changes` 는 그 달만의 배수."""
    out = []
    for month in range(1, 13):
        price = level * (step[1] if step and month >= step[0] else 1.0)
        out.append(price * (changes or {}).get(month, 1.0))
    return out


def test_finder_separates_price_changes_from_coupons_and_promotions():
    prices = {
        ("geumryong", "course-a"): _series(150000, step=(7, 1.10)),  # 가격 변경 +10%, 7월부터
        ("geumryong", "course-b"): _series(200000, changes={8: 0.90, 9: 0.90}),  # 두 달짜리 프로모션
        ("pizzahill", "pizza"): _series(30000, step=(5, 0.94)),  # 가격 변경 −6%, 5월부터
        ("thebuffet", "dinner"): _series(120000, step=(9, 1.04)),  # 가격 변경 +4%, 9월부터
        ("ondal", "set"): _series(90000, changes={4: 0.92}),  # 한 달짜리 할인 쿠폰
        ("ondal", "course"): _series(110000, changes={3: 0.88, 4: 0.88, 5: 0.88}),  # 석 달짜리 프로모션
        ("moegi", "lunch"): _series(80000, step=(6, 1.02)),  # +2%: 쿠폰의 흔들림과 가를 수 없어 찾지 않는다
        ("myongwolgwan", "course"): _series(130000),  # 바뀌지 않음
    }
    steps, temps = find_changes(unit_prices(_rows(prices)))
    assert {(s.venue_id, s.product_id, s.month) for s in steps} == {
        ("geumryong", "course-a", 7),
        ("pizzahill", "pizza", 5),
        ("thebuffet", "dinner", 9),
    }
    by = {(s.venue_id, s.product_id): s for s in steps}
    assert by[("geumryong", "course-a")].pct == pytest.approx(0.10, abs=0.015)
    assert by[("pizzahill", "pizza")].pct == pytest.approx(-0.06, abs=0.015)
    assert {(t.venue_id, t.product_id, tuple(t.months)) for t in temps} == {
        ("geumryong", "course-b", (8, 9)),
        ("ondal", "set", (4,)),
        ("ondal", "course", (3, 4, 5)),
    }


def test_finder_sets_aside_changes_in_the_last_months():
    # 12월에만 오른 가격은 뒤 달이 없어 가격 변경인지 연말 프로모션인지 가를 수 없다. 사건으로 쓰지 않고 따로 적는다.
    prices = {
        ("geumryong", "course-a"): _series(150000, changes={12: 1.12}),
        ("ondal", "set"): _series(90000, changes={11: 0.90, 12: 0.90}),
        ("moegi", "lunch"): _series(80000),
    }
    found = unit_prices(_rows(prices))
    steps, temps = find_changes(found)
    assert steps == [] and temps == []
    assert {(e.venue_id, e.product_id, tuple(e.months)) for e in backtest.find_edges(found)} == {
        ("geumryong", "course-a", (12,)),
        ("ondal", "set", (11, 12)),
    }


def test_drafts_group_products_by_venue_and_month():
    steps = [
        Step("geumryong", "course-a", 7, 100.0, 110.0),
        Step("geumryong", "course-b", 7, 100.0, 108.0),
        Step("pizzahill", "pizza", 5, 100.0, 94.0),
    ]
    drafts = draft_events(steps)
    assert [(d["venue_id"], d["start_month"], len(d["products"]), d["mixed"]) for d in drafts] == [
        ("geumryong", 7, 2, False),
        ("pizzahill", 5, 1, False),
    ]
    assert drafts[0]["pct"] == pytest.approx(9.0)


# ── 끝까지: 엔진을 data_until 로 돌려 채점 ─────────────────────────────────

# 철 효과 (두 업장에 같이 걸린다)와 업장마다의 작은 흔들림.
SEASON = [1.00, 0.95, 1.00, 1.05, 1.00, 0.90, 0.80, 0.85, 0.90, 1.05, 1.10, 1.20]
NOISE = {
    "geumryong": [0.0, 0.01, -0.01, 0.005, -0.005, 0.01, 0.0, -0.01, 0.005, 0.0, -0.005, 0.01],
    "ondal": [0.005, -0.01, 0.0, 0.01, 0.0, -0.005, 0.01, 0.0, -0.01, 0.005, 0.0, -0.005],
}
# 심는 반응: 7월부터 금룡 사람 수 −20%, 손님 일부가 옮겨 온 온달 +5%. 이중 차분으로 0.8 ÷ 1.05 − 1 ≈ −23.8%.
PLANTED = {"geumryong": 0.80, "ondal": 1.05}


def _summary(root: Path, planted: bool | dict[str, float]) -> None:
    lines = ["customer_group,venue_id,product_id,occasion,meal,day_type,month,unit,quantity,people,paid,revenue_net,price_unconfirmed"]
    for venue, base in (("geumryong", 400), ("ondal", 300)):
        for month in range(1, 13):
            factor = SEASON[month - 1] * (1 + NOISE[venue][month - 1])
            if planted and month >= EVENT_MONTH:
                factor *= (PLANTED if planted is True else planted)[venue]
            people = round(base * factor)
            price = 150000 * (1 + PRICE_PCT / 100) if venue == "geumryong" and month >= EVENT_MONTH else 150000
            paid = round(people * price)
            lines.append(f"가족·친족,{venue},course-a,meal,dinner,weekend,{month},1인,{people},{people},{paid},{round(paid / 1.1)},N")
    (root / "data" / "samples" / "base_summary.csv").write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def _world(root: Path, planted: bool | dict[str, float]) -> None:
    """예시 사본에 온달(금룡을 베낌), 반응을 심거나 심지 않은 집계 파일, 금룡 가격 +10% 상황을 둔다."""
    geumryong = load_json(root / "data" / "venues" / "geumryong.json")
    save_json(root / "data" / "venues" / "ondal.json", {**geumryong, "venue_id": "ondal", "name": "온달"})
    rival = root / "data" / "venues" / "examplehotel-chinese.json"
    save_json(rival, {**load_json(rival), "competes_with": ["geumryong", "ondal"]})
    _summary(root, planted)
    save_json(
        root / "scenarios" / f"{SCENARIO}.json",
        {
            "format_version": 1,
            "scenario_id": SCENARIO,
            "name": "금룡 가격 +10% (되돌려 맞혀 보기)",
            "kind": "our_price",
            "description": "7월부터 금룡의 가격이 10% 올랐다는 가상 사건이다.",
            "changes": [{"op": "change_price_pct", "venue_id": "geumryong", "product_id": None, "pct": PRICE_PCT}],
            "note": "테스트의 가상 사건이다.",
        },
    )
    prompts = root / "personas" / "prompts"
    shutil.copy(prompts / "p1.md", prompts / f"{PROMPT}.md")


def _to_hundred(raw: dict[str | None, float]) -> dict[str | None, int]:
    """점수를 합이 100 인 정수로 (남는 몫이 큰 곳부터 1 씩)."""
    total = sum(raw.values())
    exact = {k: 100 * v / total for k, v in raw.items()}
    out = {k: int(v) for k, v in exact.items()}
    for k in sorted(exact, key=lambda k: exact[k] - out[k], reverse=True)[: 100 - sum(out.values())]:
        out[k] += 1
    return out


class PriceAware:
    """가격이 오르면 금룡의 점수를 낮추는 공급자. 처음 본 금룡 주문 금액을 기준으로 (기준 ÷ 지금)^민감도 를 곱한다."""

    def __init__(self, sensitivity: float = 4) -> None:
        self.sensitivity = sensitivity
        self.reference: dict[str, int] = {}

    def complete(self, system: str, user: str, schema: dict | None = None) -> LlmReply:
        request = ChoiceRequest.model_validate_json(user)
        option = request.candidate("geumryong").options[0]
        key = f"{request.persona['persona_id']}:{option.option_id}"
        ref = self.reference.setdefault(key, option.total)
        raw = {"geumryong": 60 * (ref / option.total) ** self.sensitivity, "ondal": 30.0, "examplehotel-chinese": 10.0, None: 10.0}
        response = scored(request, _to_hundred(raw))
        return LlmReply(json.dumps(response.model_dump(mode="json"), ensure_ascii=False), 11, 7)


def _play(root: Path, provider: PriceAware, data_until: int = EVENT_MONTH - 1) -> tuple[Path, Path]:
    same = {
        "data_mode": "sample",
        "provider": PROVIDER,
        "model": MODEL,
        "prompt_version": PROMPT,
        "answers": [],
        "engine_commit": "0000000",
        "llm": provider,
        "call_limit": 10,
    }
    base = run(root, now=NOW, persona_ids=[ELDERS], condition_ids=[DINNER], data_until=data_until, **same)
    scen = run(root, now=NOW.replace(minute=1), scenario_id=SCENARIO, weights_from=base.name, **same)
    return base, scen


def _events(root: Path) -> Path:
    path = root / "backtest" / "events.json"
    save_json(
        path,
        {
            "format_version": 1,
            "events": [
                {
                    "event_id": "geumryong-price-up-07",
                    "name": "금룡 가격 +10%",
                    "kind": "price",
                    "venue_id": "geumryong",
                    "start_month": EVENT_MONTH,
                    "scenario_id": SCENARIO,
                    "source": "given",
                    "note": "테스트에 심은 가상 사건이다.",
                }
            ],
        },
    )
    return path


def _scored(root: Path, planted: bool | dict[str, float], sensitivity: float = 4, **kwargs) -> BacktestResult:
    _world(root, planted)
    _play(root, PriceAware(sensitivity))
    return score(root, "sample", _events(root), NOW, **kwargs)


def test_planted_reaction_is_caught_in_direction_and_size(example_copy):
    result = _scored(example_copy, planted=True)
    (event,) = result.events
    assert event.status == "scored", event.skip_reason
    assert event.control_venues == ["ondal"]
    people = event.people
    # 실제 쪽은 심은 반응(≈ −23.8%)을 철 효과를 뺀 채 되찾는다. 흔들림(가짜 사건)보다 훨씬 크다.
    assert people.actual == pytest.approx(PLANTED["geumryong"] / PLANTED["ondal"] - 1, abs=0.03)
    assert people.actual_band is not None and people.actual_band < 0.05
    assert people.actual_direction == "down"
    assert people.predicted is not None and people.predicted < 0
    assert people.predicted_direction == "down"
    assert people.direction_correct is True
    assert event.people_magnitude.status == "scored"
    assert event.people_magnitude.correct is True, event.people_magnitude
    # 매출: 가격이 10% 오른 만큼 덜 줄어든다. 같은 셈으로 채점해 적는다.
    assert event.revenue.actual == pytest.approx(people.actual + 0.1 * (1 + people.actual), abs=0.03)
    assert result.summary.people.direction_correct == 1
    assert result.summary.verdict == "too_few"  # 사건 하나라 합격을 말하지 않는다
    assert result.summary.magnitude_said is True
    assert result.criteria.window_before == 3 and result.criteria.metric == "people"


def test_no_reaction_is_not_caught(example_copy):
    result = _scored(example_copy, planted=False)
    (event,) = result.events
    assert event.status == "scored", event.skip_reason
    # 실제는 흔들림 안이라 변화 없음이다. 시뮬레이터는 줄어든다고 했으니 방향이 틀린 것으로 채점한다.
    assert abs(event.people.actual) <= event.people.actual_band
    assert event.people.actual_direction == "none"
    assert event.people.direction_correct is False
    assert event.people_magnitude.status == "no_change"
    assert result.summary.people.direction_correct == 0


def test_seasonal_drop_alone_is_not_taken_for_a_reaction(example_copy):
    # 심지 않은 자료도 7 ~ 9월은 철 효과로 4 ~ 6월보다 낮다. 전후만 견주면 반응처럼 보이지만 이중 차분은 지운다.
    _world(example_copy, planted=False)
    rows = load_inputs(example_copy, "sample", base_profile_mode="none").summary
    raw = sum(r.people for r in rows if r.venue_id == "geumryong" and 7 <= r.month <= 9) / sum(
        r.people for r in rows if r.venue_id == "geumryong" and 4 <= r.month <= 6
    )
    assert raw - 1 < -0.10
    _play(example_copy, PriceAware())
    (event,) = score(example_copy, "sample", _events(example_copy), NOW).events
    assert abs(event.people.actual) < 0.03


def test_prediction_far_too_large_is_wrong_in_size(example_copy):
    # 시뮬레이터가 가격에 지나치게 민감하다 (민감도 30): 방향은 맞지만 크기가 실제의 두 배를 넘는다.
    (event,) = _scored(example_copy, planted=True, sensitivity=30).events
    assert event.people.direction_correct is True
    assert event.people_magnitude.status == "scored"
    assert event.people_magnitude.ratio > 2
    assert event.people_magnitude.correct is False


def test_opposite_reaction_is_wrong_in_direction(example_copy):
    # 실제로는 가격을 올린 뒤 손님이 늘었다 (예: 같은 때 다른 일이 있었다). 시뮬레이터는 줄어든다고 했다.
    (event,) = _scored(example_copy, planted={"geumryong": 1.25, "ondal": 1.0}).events
    assert event.people.actual_direction == "up"
    assert event.people.predicted_direction == "down"
    assert event.people.direction_correct is False
    assert event.people_magnitude.correct is False  # 예측 ÷ 실제가 0 보다 작다


def test_control_venues_leave_out_venues_with_their_own_events():
    def event(venue: str, month: int, event_id: str):
        return BacktestEvents.model_validate(
            {
                "format_version": 1,
                "events": [
                    {
                        "event_id": event_id,
                        "name": "가",
                        "kind": "price",
                        "venue_id": venue,
                        "start_month": month,
                        "scenario_id": "s",
                        "source": "detected",
                        "note": "n",
                    }
                ],
            }
        ).events[0]

    events = [event("geumryong", 7, "a"), event("ondal", 8, "b"), event("moegi", 4, "c"), event("geumryong", 9, "d")]
    present = {"geumryong", "ondal", "moegi", "pizzahill"}
    # 온달은 8월에 제 사건이 있어 빠지고, 모에기의 4월 사건은 7월의 창(4 ~ 9월, 섞이는 것은 5 ~ 9월)과 섞이지 않는다.
    assert backtest.controls(7, "geumryong", events, {"pizzahill"}, present) == ["moegi"]
    # 금룡의 7월 사건은 9월 사건과 두 달 거리라 섞인다 (겹침).
    assert backtest.busy("geumryong", 7, events, skip=events[0])
    assert not backtest.busy("geumryong", 7, events[:3], skip=events[0])


def _fitted(root: Path, scenarios: list[str], day_types: list[str]) -> tuple[Path, Path]:
    elasticity = root / "backtest" / "elasticity.json"
    segments = root / "backtest" / "elasticity_segments.json"
    save_json(
        elasticity,
        {
            "fitted_on": {
                "baseline_run_id": "20261120-000000-baseline",
                "price_runs": [{"run_id": "x", "scenario_id": s, "venues": ["geumryong"], "pct": 10} for s in scenarios],
                "segments": ["upscale-weekday"],
                "venues": ["geumryong"],
            }
        },
    )
    save_json(
        segments,
        {
            "format_version": 1,
            "segments": [
                {"segment_id": "upscale-weekday", "venues": ["geumryong", "moegi"], "occasions": ["meal"], "day_types": day_types}
            ],
        },
    )
    return elasticity, segments


def test_size_skips_what_stage_four_fitted(example_copy):
    _world(example_copy, planted=True)
    _play(example_copy, PriceAware())
    events = _events(example_copy)

    # 4단계 구간이 금룡의 평일 식사만: 이 사건의 방문은 모두 주말이라 그대로 크기를 잰다.
    elasticity, segments = _fitted(example_copy, ["market-price-up"], ["weekday"])
    (event,) = score(example_copy, "sample", events, NOW, elasticity, segments).events
    assert event.people_magnitude.status == "scored"
    assert event.people_magnitude.excluded_slices == [("meal", "weekday")]

    # 구간이 주말까지 덮으면 남는 방문이 없어 크기를 보지 않는다. 방향은 그대로 채점한다.
    elasticity, segments = _fitted(example_copy, ["market-price-up"], ["weekday", "weekend"])
    result = score(example_copy, "sample", events, NOW, elasticity, segments)
    (event,) = result.events
    assert event.people_magnitude.status == "excluded"
    assert event.people.direction_correct is True
    assert result.summary.magnitude_said is False
    assert result.fitted_on.segments == ["upscale-weekday"]

    # 4단계가 k 를 맞추는 데 쓴 상황 그 자체면 통째로 뺀다.
    elasticity, segments = _fitted(example_copy, [SCENARIO], ["weekday"])
    (event,) = score(example_copy, "sample", events, NOW, elasticity, segments).events
    assert event.people_magnitude.status == "excluded"
    assert "상황" in event.people_magnitude.reason


def test_predicted_band_comes_from_the_repeated_answers(example_copy, monkeypatch):
    _world(example_copy, planted=True)
    base, _ = _play(example_copy, PriceAware())
    shutil.copy(base / "ledger.csv", base / "repeat_ledger.csv")  # 같은 답을 다시 받았다: 흔들림 0
    monkeypatch.setattr(backtest, "constant", lambda constant_id: 2.0)
    (event,) = score(example_copy, "sample", _events(example_copy), NOW).events
    assert event.people.predicted_band == 0.0


def test_events_are_skipped_with_a_reason(example_copy):
    _world(example_copy, planted=True)
    events = _events(example_copy)
    # 사건 앞 달까지로 돈 실행이 없다.
    (event,) = score(example_copy, "sample", events, NOW).events
    assert event.status == "skipped" and "--data-until 6" in event.skip_reason
    # 실행 뒤에 집계 파일이 바뀌었다.
    _play(example_copy, PriceAware())
    _summary(example_copy, planted=False)
    (event,) = score(example_copy, "sample", events, NOW).events
    assert event.status == "skipped" and "집계 파일" in event.skip_reason
    # 앞뒤 석 달이 한 해 안에 들지 않는 달.
    data = load_json(events)
    data["events"][0]["start_month"] = 11
    save_json(events, data)
    (event,) = score(example_copy, "sample", events, NOW).events
    assert event.status == "skipped" and "4 ~ 10월" in event.skip_reason


def test_events_file_rules():
    good = {
        "event_id": "a",
        "name": "가",
        "kind": "price",
        "venue_id": "geumryong",
        "start_month": 7,
        "scenario_id": "s",
        "source": "detected",
        "note": "n",
    }
    BacktestEvents.model_validate({"format_version": 1, "events": [good]})
    with pytest.raises(ValueError):  # 같은 업장·같은 달
        BacktestEvents.model_validate({"format_version": 1, "events": [good, {**good, "event_id": "b"}]})
    with pytest.raises(ValueError):  # 경쟁 업장
        BacktestEvents.model_validate({"format_version": 1, "events": [{**good, "venue_id": "examplehotel-chinese"}]})


# ── 엔진의 data_until ─────────────────────────────────────────────────────


def test_data_until_reads_only_the_months_before(example_copy):
    _world(example_copy, planted=True)
    base, scen = _play(example_copy, PriceAware())
    record = read_model(base / "run.json", RunRecord)
    assert record.data_until == EVENT_MONTH - 1
    assert read_model(scen / "run.json", RunRecord).data_until == EVENT_MONTH - 1
    # 가중치는 6월까지의 인원으로 낸다: 7월 뒤의 줄을 바꿔도 같은 가중치가 나온다.
    _summary(example_copy, planted=False)
    again = run(
        example_copy,
        data_mode="sample",
        now=NOW.replace(minute=5),
        provider=PROVIDER,
        model=MODEL,
        prompt_version=PROMPT,
        answers=[base / "llm"],
        persona_ids=[ELDERS],
        condition_ids=[DINNER],
        engine_commit="0000000",
        data_until=EVENT_MONTH - 1,
    )
    assert read_model(again / "run.json", RunRecord).weights == record.weights
    # 보통의 상황은 일 년 전체를 읽은 기준 실행만 고른다.
    assert latest_baseline_run(example_copy, "sample") != base.name
    assert latest_baseline_run(example_copy, "sample", data_until=EVENT_MONTH - 1) == again.name


def test_data_until_must_match_the_baseline(example_copy):
    _world(example_copy, planted=True)
    base, _ = _play(example_copy, PriceAware())
    with pytest.raises(ValueError, match="같은 자료"):
        run(
            example_copy,
            data_mode="sample",
            now=NOW.replace(minute=7),
            provider=PROVIDER,
            model=MODEL,
            prompt_version=PROMPT,
            answers=[],
            scenario_id=SCENARIO,
            weights_from=base.name,
            data_until=5,
            engine_commit="0000000",
        )


def test_full_year_run_record_has_no_data_until_key(example_copy):
    # 일 년 전체를 읽은 실행 기록은 이 칸이 생기기 전과 같다 (예시 실행이 그대로).
    assert "data_until" not in load_json(EXAMPLE_ROOT / "engine" / "samples" / "runs" / "20261117-101500-baseline" / "run.json")
    _world(example_copy, planted=True)
    base, scen = _play(example_copy, PriceAware())
    assert load_json(base / "run.json")["data_until"] == EVENT_MONTH - 1


def test_checker_accepts_backtest_runs(example_copy):
    _world(example_copy, planted=True)
    _play(example_copy, PriceAware())
    problems = [str(p) for p in check(example_copy, strict=True) if p.level == "error"]
    assert problems == []


def test_checker_blocks_backtest_files_in_the_repository(example_copy):
    # 결과와 사건 후보에는 집계 파일에서 낸 변화와 가격이 들어 있다. 이름이나 자리를 바꿔도 안쪽 키로 알아본다.
    result = _scored(example_copy, planted=True)
    save_json(example_copy / "data" / "evidence" / "extra" / "notes.json", result.model_dump(mode="json"))
    save_json(example_copy / "docs" / "candidates.json", {"price_changes": [], "temporary": [], "edge": []})
    problems = [str(p) for p in check(example_copy, strict=True) if p.level == "error"]
    assert any("notes.json" in p and "되돌려 맞혀 보기" in p for p in problems)
    assert any("candidates.json" in p and "되돌려 맞혀 보기" in p for p in problems)



def test_doc_events_example_is_valid(doc):
    # 형식 문서 10.9절의 사건 목록 예시가 모델에 맞는다 (예시 묶음에는 이 파일이 없다).
    found = [o for o in doc.json if "events" in o and "format_version" in o]
    assert len(found) == 1
    events = BacktestEvents.model_validate(found[0]).events
    assert events[0].scenario_id == SCENARIO and events[0].start_month == EVENT_MONTH


# ── 독립 검토에서 나온 것 (11-20) ─────────────────────────────────────────


def test_finder_catches_a_mid_month_change():
    # 15일에 10% 올리면 그 달 평균은 +5% 쯤이라 두 수준 사이에 있다. 그 달을 사건 달로 보고 표시한다.
    prices = {("geumryong", "course-a"): _series(150000, changes={7: 1.05}, step=(8, 1.10))}
    prices[("geumryong", "course-a")][6] = 150000 * 1.05  # 7월만 중간 (step 이 8월부터라 7월 배수를 덮어씀)
    steps, temps = find_changes(unit_prices(_rows(prices)))
    assert [(s.month, s.mid_month) for s in steps] == [(7, True)]
    assert steps[0].pct == pytest.approx(0.10, abs=0.015)
    assert temps == []


def test_draft_scenario_uses_set_price_for_products_without_a_price():
    draft = draft_events([Step("geumryong", "course-a", 7, 100.0, 110.0), Step("geumryong", "seasonal", 7, 50.0, 55.0)])[0]
    scenario = backtest.draft_scenario(draft, priced={("geumryong", "course-a")})
    assert scenario["changes"] == [
        {"op": "change_price_pct", "venue_id": "geumryong", "product_id": "course-a", "pct": 10.0},
        {"op": "set_price", "venue_id": "geumryong", "product_id": "seasonal", "price": 55},
    ]


def test_promotion_mixes_into_windows_after_it_ends():
    events = BacktestEvents.model_validate(
        {
            "format_version": 1,
            "events": [
                {"event_id": "p", "name": "가", "kind": "promotion", "venue_id": "ondal", "start_month": 4,
                 "scenario_id": "s", "source": "public", "note": "n"},
                {"event_id": "q", "name": "가", "kind": "price", "venue_id": "moegi", "start_month": 4,
                 "scenario_id": "s", "source": "public", "note": "n"},
            ],
        }
    ).events
    # 9월의 앞 창(6 ~ 8월)은 가격 변경이면 바뀐 뒤라 괜찮지만, 4 ~ 6월 프로모션이 끝난 6월이 걸린다.
    assert backtest.busy("ondal", 9, events) and not backtest.busy("moegi", 9, events)
    assert not backtest.busy("ondal", 10, events)


def test_breakfast_is_left_out_of_the_actual_side():
    rows = _rows({("thebuffet", "dinner"): _series(100000)})
    breakfast = rows[0].model_copy(update={"meal": "breakfast", "product_id": "breakfast"})
    table = backtest.actual_table([*rows, breakfast], {"가족·친족": 3.0})
    assert table.total("people", ["thebuffet"], [1], set()) == rows[0].people


def test_one_bad_event_does_not_stop_the_others(example_copy):
    _world(example_copy, planted=True)
    _play(example_copy, PriceAware())
    path = _events(example_copy)
    data = load_json(path)
    data["events"].append({**data["events"][0], "event_id": "missing", "venue_id": "moegi", "scenario_id": "no-such-scenario"})
    save_json(path, data)
    first, missing = score(example_copy, "sample", path, NOW).events
    assert first.status == "scored"
    assert missing.status == "skipped" and "채점하지 못했다" in missing.skip_reason


def test_fresh_full_year_run_has_no_data_until_key_and_cut_inputs_stop_at_the_month(example_copy):
    _world(example_copy, planted=True)
    full = run(
        example_copy,
        data_mode="sample",
        now=NOW.replace(minute=9),
        provider=PROVIDER,
        model=MODEL,
        prompt_version=PROMPT,
        answers=[],
        persona_ids=[ELDERS],
        condition_ids=[DINNER],
        engine_commit="0000000",
        llm=PriceAware(),
        call_limit=10,
    )
    assert "data_until" not in load_json(full / "run.json")
    # 가중치, 기본 데이터의 요약, 빈 가격 채우기는 모두 이 줄 목록으로 낸다.
    cut = load_inputs(example_copy, "sample", base_profile_mode="none", data_until=6)
    assert {r.month for r in cut.summary} == set(range(1, 7))
