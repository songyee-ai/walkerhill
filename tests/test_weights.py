"""가중 합산과 기본 데이터에서 내는 값 (T11).

예시 묶음(tests/fixtures/example)의 사본에서 엔진을 돌린다. 집계 파일은 모두 지어낸 값이다.
기본 데이터로 돌리는 경우는 지어낸 집계 파일을 사본의 `private/base/` 자리에 두고 시험한다 (실행 결과도 사본에만 생긴다).
"""

import json
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

import engine.__main__ as cli
from engine.formats import ConditionBundle, LedgerRow, SummaryRow, Venue, read_model
from engine.formats.run import Weights
from engine.formats.summary import SUMMARY_COLUMNS
from engine.ledger import venue_shares
from engine.llm import LlmReply
from engine.runner import load_inputs, run
from engine.scenarios import ScenarioError, apply_scenario, apply_with_prices
from engine.weights import (
    MEAL_SPLIT_ID,
    base_profiles,
    condition_ratios,
    fill_prices,
    group_people,
    group_revenue,
    read_summary,
    summary_path,
    weaker,
)
from tests.conftest import (
    BASELINE_RUN,
    COMPETITOR_RUN,
    EXAMPLE_ROOT,
    REPO_ROOT,
    load_json,
    save_csv,
    save_json,
)
from tests.test_engine import (
    DINNER,
    LUNCH,
    MODEL,
    NOW,
    PROVIDER,
    answer,
    edit,
    first_option,
    persona_file,
    pick_geumryong,
    play,
    product_of,
    venue_file,
)
from tests.test_llm import Clock, Fake
from tests.test_scenarios import (
    COMPETITOR_DISCOUNT,
    LLM_ENV,
    new_product,
    run_scenario,
    scenario,
    write_scenario,
)
from tools.check_formats import check

GROUP = "가족·친족"
ELDERS, KIDS = "family-elders", "family-kids"
RUNS = Path("engine") / "samples" / "runs"
BUNDLE = read_model(EXAMPLE_ROOT / "engine" / "conditions.json", ConditionBundle)
EIGHT = [c.condition_id for c in BUNDLE.conditions]


def _dessert_venue() -> Venue:
    """디저트 업장 하나 (지어낸 것). 예시 묶음에는 디저트 업장이 없어 금룡의 정의를 고쳐 만든다."""
    data = load_json(EXAMPLE_ROOT / "data" / "venues" / "geumryong.json")
    hours = {"meal": None, "day_type": "all", "open": "10:00", "last_order": None, "close": "20:00", "source_id": None}
    sweet = dict(data["products"][0], occasion="dessert", slots=[{"meal": None, "day_type": "all"}], unit="개")
    sweet.update(qty_rule="choice", qty_max=4, audience="all", serves=1)
    data.update(venue_id="pavilion", name="더파빌리온", occasions=["dessert"], hours=[hours], promotions=[])
    data["products"] = [dict(sweet, product_id="bingsu", name="빙수"), dict(sweet, product_id="cake", name="케이크")]
    return Venue.model_validate(data)


# 읽은 업장 정의: 예시 묶음의 네 곳과 디저트 업장 하나. 끼니가 빈 줄의 끼니를 정하는 데 쓴다.
VENUES = {v.venue_id: v for v in (read_model(p, Venue) for p in sorted((EXAMPLE_ROOT / "data" / "venues").glob("*.json")))}
VENUES["pavilion"] = _dessert_venue()


def only(*venue_ids: str) -> dict[str, Venue]:
    return {venue_id: VENUES[venue_id] for venue_id in venue_ids}


# ── 도우미 ──────────────────────────────────────────────────────────────


def line(
    venue_id, product_id, meal, day_type, quantity, unit_net, *, month=5, occasion="meal", group=GROUP, unit="1인", people=None
) -> dict:
    """집계 파일의 한 줄 (지어낸 값). 매출은 하나씩 팔린 줄마다 반올림한 값을 더한 것처럼 짓는다.

    `people` 을 주지 않으면 수량과 같다 (한 개에 한 사람). 빈 칸으로 두려면 "" 를 준다.
    """
    paid = round(unit_net * 1.1) * quantity
    return {
        "customer_group": group,
        "venue_id": venue_id,
        "product_id": product_id,
        "occasion": occasion,
        "meal": meal or "",
        "day_type": day_type,
        "month": str(month),
        "unit": unit,
        "quantity": str(quantity),
        "people": str(quantity if people is None else people),
        "paid": str(paid),
        "revenue_net": str(unit_net * quantity),
        "price_unconfirmed": "N",
    }


def rows_of(*lines: dict) -> list[SummaryRow]:
    return [SummaryRow.from_row(item) for item in lines]


def write_summary(root: Path, *lines: dict, private: bool = False) -> Path:
    path = root / ("private/base/summary.csv" if private else "data/samples/base_summary.csv")
    if lines:
        save_csv(path, list(lines))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(",".join(SUMMARY_COLUMNS) + "\n", encoding="utf-8-sig", newline="\n")
    return path


def to_private(root: Path) -> None:
    """지어낸 집계 파일을 기본 데이터의 자리(private/base/)에 베낀다."""
    target = root / "private" / "base" / "summary.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / "data" / "samples" / "base_summary.csv", target)


def weighted_total(rows: list[LedgerRow]) -> int:
    return sum(round(row.weighted_revenue) for row in rows if row.status == "ok" and row.choice_kind == "walkerhill")


class Replay:
    """예시의 저장된 응답 하나를 새로 받은 답처럼 돌려준다. 받은 요청이 예시의 요청과 같아야 한다."""

    def __init__(self, saved_path: Path) -> None:
        self.saved = load_json(saved_path)

    def complete(self, system: str, user: str, schema: dict) -> LlmReply:
        assert json.loads(user) == self.saved["request"]
        usage = self.saved["usage"]
        return LlmReply(self.saved["raw_text"], usage["input_tokens"], usage["output_tokens"])


def private_run(root: Path, *, now=NOW, persona_ids=(ELDERS,), condition_ids=(DINNER,), **more) -> Path:
    """기본 데이터로 돌린다. 답은 가짜 공급자가 금룡의 첫 주문으로 준다. 기준이 아닌 상황은 목록을 None 으로 준다."""
    settings = dict(
        data_mode="private",
        now=now,
        provider=PROVIDER,
        model=MODEL,
        prompt_version="p1",
        answers=[],
        persona_ids=None if persona_ids is None else list(persona_ids),
        condition_ids=None if condition_ids is None else list(condition_ids),
        engine_commit="0000000",
        llm=Fake(),
        call_limit=50,
        # 기본 데이터의 요약을 이 공급자로 보내도 된다고 확인한 PC 로 본다 (T115). 확인이 없을 때는 테스트가 따로 준다.
        base_profile_confirmed_for=PROVIDER,
    )
    return run(root, **(settings | more))


# ── 예시 묶음을 엔진이 그대로 만든다 ─────────────────────────────────────


def test_engine_writes_both_example_runs_as_they_are(example_copy):
    """예시 묶음의 두 실행(기준, 경쟁 업장의 할인)을 엔진이 글자 그대로 만든다. 가중치도 엔진이 가상 예시 값에서 낸 것이다.

    LLM 대신 예시의 저장된 응답의 글을 그대로 돌려주는 공급자를 끼운다. 그래서 새로 부른 실행으로 나온다.
    실행 기록, 원장, 저장된 응답이 모두 바이트까지 같아야 한다 (보정의 대조 결과는 엔진이 쓰지 않아 빼고 견준다).
    """
    kept = example_copy.parent / "kept"
    kept.mkdir()
    for name in (BASELINE_RUN, COMPETITOR_RUN):
        shutil.move(example_copy / RUNS / name, kept / name)
    same = dict(
        data_mode="sample",
        provider="anthropic",
        model="claude-opus-5-5",
        prompt_version="p1",
        venue_ids=["geumryong", "examplehotel-chinese"],
        engine_commit="0000000",
        answers=[],
        call_limit=200,
    )

    def only_llm(name: str) -> Path:
        (path,) = (kept / name / "llm").iterdir()
        return path

    base = run(
        example_copy,
        now=NOW.replace(year=2026, month=11, day=17, hour=10, minute=15),
        persona_ids=[ELDERS],
        condition_ids=[DINNER],
        llm=Replay(only_llm(BASELINE_RUN)),
        **same,
    )
    again = run(
        example_copy,
        now=NOW.replace(year=2026, month=11, day=17, hour=10, minute=30),
        scenario_id=COMPETITOR_DISCOUNT,
        weights_from=base.name,
        llm=Replay(only_llm(COMPETITOR_RUN)),
        **same,
    )

    for made, name in ((base, BASELINE_RUN), (again, COMPETITOR_RUN)):
        assert made.name == name
        written = {p.relative_to(made).as_posix(): p.read_bytes() for p in made.rglob("*") if p.is_file()}
        example = {
            p.relative_to(kept / name).as_posix(): p.read_bytes()
            for p in (kept / name).rglob("*")
            if p.is_file() and p.name != "calibration.json"
        }
        assert written == example, name


# ── 묶음의 비율 ─────────────────────────────────────────────────────────


SPLIT_ROWS = (
    line("geumryong", "course-a", None, "weekday", 10, 100),  # 끼니를 모름: 평일 점심과 평일 저녁에 반씩
    line("geumryong", "course-b", "dinner", "weekend", 20, 100),
    line("thebuffet", "dinner-adult", "breakfast", "weekend", 99, 100),  # 조식은 묶음에 없다
    line("pavilion", "bingsu", None, "weekend", 5, 100, occasion="dessert", unit="개"),
    line("thebuffet", "lunch-adult", "lunch", "weekday", 7, 100, group="다른 고객군"),
)


def test_condition_ratio_splits_unknown_meals_and_leaves_out_breakfast():
    rows = rows_of(*SPLIT_ROWS)
    revenue = group_revenue(rows, BUNDLE.conditions, BUNDLE.assumed_splits, VENUES)
    assert revenue[GROUP].total() == 3500  # 1000 + 2000 + 500. 조식 9900 은 들지 않는다
    ratios, grades = condition_ratios(revenue, [GROUP, "다른 고객군", "없는 고객군"], EIGHT, "private")
    assert ratios[GROUP] == {
        "meal-lunch-weekday": 500 / 3500,
        "meal-lunch-weekend": 0.0,
        "meal-dinner-weekday": 500 / 3500,
        "meal-dinner-weekend": 2000 / 3500,
        "dessert-weekday": 0.0,
        "dessert-weekend": 500 / 3500,
        "takeout-weekday": 0.0,
        "takeout-weekend": 0.0,
    }
    assert sum(ratios[GROUP].values()) == pytest.approx(1)
    # 팀이 정한 비율로 나눈 매출이 든 조건만 설계 가정이다. 매출이 0 인 조건도 기본 데이터로 안 것이다.
    assumed = {c for c, grade in grades[GROUP].items() if grade == "assumption"}
    assert assumed == {"meal-lunch-weekday", "meal-dinner-weekday"}
    assert set(grades[GROUP].values()) == {"internal", "assumption"}
    assert ratios["다른 고객군"]["meal-lunch-weekday"] == 1.0
    # 매출이 없는 고객군은 비율을 낼 수 없다.
    assert set(ratios["없는 고객군"].values()) == {0.0} and set(grades["없는 고객군"].values()) == {"unknown"}
    # 가상 예시로 돌리면 모두 설계 가정이다.
    _, sample = condition_ratios(revenue, [GROUP], EIGHT, "sample")
    assert set(sample[GROUP].values()) == {"assumption"}


def test_condition_ratio_reads_only_the_venues_and_conditions_that_run():
    rows = rows_of(*SPLIT_ROWS)
    # 금룡만 읽었다: 더파빌리온의 디저트 매출은 들지 않는다.
    only_geumryong = group_revenue(rows, BUNDLE.conditions, BUNDLE.assumed_splits, only("geumryong"))
    assert only_geumryong[GROUP].total() == 3000
    # 조건의 일부만 돌리면 그 조건들 안에서 나눈다.
    two = [c for c in BUNDLE.conditions if c.condition_id in ("meal-lunch-weekday", DINNER)]
    revenue = group_revenue(rows, two, BUNDLE.assumed_splits, VENUES)
    ratios, _ = condition_ratios(revenue, [GROUP], ["meal-lunch-weekday", DINNER], "sample")
    assert ratios[GROUP] == {"meal-lunch-weekday": 500 / 2500, DINNER: 2000 / 2500}
    # 평일의 끼니를 모르는 매출은 점심 몫만 들었다. 그래서 주말 저녁의 비율도 반반 가정에 기댄다.
    assert revenue[GROUP].split_partly_used
    _, grades = condition_ratios(revenue, [GROUP], ["meal-lunch-weekday", DINNER], "private")
    assert grades[GROUP] == {"meal-lunch-weekday": "assumption", DINNER: "assumption"}


def test_unknown_meals_need_the_split_of_the_bundle():
    rows = rows_of(line("geumryong", "course-a", None, "weekday", 10, 100))
    with pytest.raises(ValueError, match=MEAL_SPLIT_ID):
        group_revenue(rows, BUNDLE.conditions, [], only("geumryong"))
    # 끼니가 있는 줄만 있으면 나눌 일이 없다. 저녁에만 파는 상품의 끼니 빈 줄도 저녁이라 나눌 일이 없다.
    rows = rows_of(line("geumryong", "course-b", "dinner", "weekend", 10, 100), line("geumryong", "course-b", None, "weekday", 5, 100))
    revenue = group_revenue(rows, BUNDLE.conditions, [], only("geumryong"))[GROUP]
    assert dict(revenue.by_condition) == {DINNER: 1000, "meal-dinner-weekday": 500} and not revenue.assumed


def test_unknown_meal_is_taken_from_the_slots_when_only_one_meal_is_sold():
    """끼니가 빈 줄이라도 그 요일에 한 끼니에만 파는 상품이면 그 끼니다. 둘 다 팔 때만 나눈다 (docs/FORMATS.md 8절)."""
    data = VENUES["thebuffet"].model_dump(mode="json")
    peak = dict(data["products"][2], product_id="peak-adult", slots=[{"meal": "lunch", "day_type": "weekend"}, {"meal": "dinner", "day_type": "all"}])
    data["products"].append(peak)
    venues = {"thebuffet": Venue.model_validate(data)}
    rows = rows_of(
        line("thebuffet", "peak-adult", None, "weekday", 10, 100),  # 평일에는 저녁에만 판다
        line("thebuffet", "peak-adult", None, "weekend", 10, 100),  # 주말에는 점심과 저녁에 판다
        line("thebuffet", "not-in-the-venue", None, "weekday", 4, 100),  # 업장 정의에 없는 상품은 나눈다
    )
    revenue = group_revenue(rows, BUNDLE.conditions, BUNDLE.assumed_splits, venues)[GROUP]
    assert dict(revenue.by_condition) == {
        "meal-dinner-weekday": 1000 + 200,
        "meal-lunch-weekend": 500,
        "meal-dinner-weekend": 500,
        "meal-lunch-weekday": 200,
    }
    ratios, grades = condition_ratios({GROUP: revenue}, [GROUP], EIGHT, "private")
    assert grades[GROUP]["meal-lunch-weekend"] == "assumption" and grades[GROUP]["meal-lunch-weekday"] == "assumption"
    assert grades[GROUP]["dessert-weekday"] == "internal"
    assert ratios[GROUP]["meal-dinner-weekday"] == 1200 / 2400


def test_grade_of_split_conditions_follows_the_grade_of_the_split():
    """나누는 비율의 등급을 따른다. 지금은 assumption 이지만, 후기에서 비율을 냈으면(review) 그 등급이 된다."""
    reviewed = [split.model_copy(update={"grade": "review"}) for split in BUNDLE.assumed_splits]
    rows = rows_of(line("geumryong", "course-a", None, "weekday", 10, 100), line("geumryong", "course-b", "dinner", "weekend", 20, 100))
    revenue = group_revenue(rows, BUNDLE.conditions, reviewed, only("geumryong"))
    _, grades = condition_ratios(revenue, [GROUP], EIGHT, "private")
    assert grades[GROUP]["meal-lunch-weekday"] == "review" and grades[GROUP][DINNER] == "internal"
    _, sample = condition_ratios(revenue, [GROUP], EIGHT, "sample")
    assert set(sample[GROUP].values()) == {"assumption"}  # 가상 예시는 그보다 약한 assumption 이다


def test_bundle_with_two_conditions_for_the_same_time_stops():
    twin = BUNDLE.conditions[3].model_copy(update={"condition_id": "meal-dinner-weekend-again"})
    rows = rows_of(line("geumryong", "course-b", "dinner", "weekend", 10, 100))
    with pytest.raises(ValueError, match="같은 때의 조건이 둘 이상"):
        group_revenue(rows, [*BUNDLE.conditions, twin], BUNDLE.assumed_splits, only("geumryong"))


# ── 고객군 배수와 페르소나의 가중치 ──────────────────────────────────────


RICH = (
    line("geumryong", "course-a", None, "weekday", 100, 136364),
    line("geumryong", "course-a", None, "weekend", 200, 136364),
    line("geumryong", "course-b", "dinner", "weekend", 50, 181818, month=6),
    line("thebuffet", "lunch-adult", "lunch", "weekend", 100, 145455),
    line("thebuffet", "dinner-child", "dinner", "weekday", 40, 81818, month=7),
)


def pick_by_persona(visit_id: str, request):
    """어르신 가족은 금룡, 아이 동반 가족은 더뷔페의 첫 주문을 고른다. 아이 동반 가족의 평일 점심은 답을 두지 않는다(실패)."""
    if visit_id == f"{KIDS}__meal-lunch-weekday":
        return None
    venue_id = "geumryong" if visit_id.startswith(ELDERS) else "thebuffet"
    return first_option(request, venue_id) if request.candidate(venue_id) else answer(request, None)


def test_weights_come_from_the_people_before_the_visits(example_copy):
    """가중치는 방문을 돌기 전에 집계 파일의 인원으로 정한다 (T210, docs/FORMATS.md 10.1절).

    한 방문이 대표하는 팀 수 = 조건의 인원 × 몫 ÷ Σ(몫 × 일행 수). 그래서 대표 팀 수 × 일행 수를 다 더하면 고객군의 인원이다.
    가상 매출을 기본 데이터 매출에 맞추지 않는다: AI 가 고른 금액이 실제와 다르면 그 차이가 그대로 남는다.
    """
    other = line("thebuffet", "lunch-adult", "lunch", "weekday", 10, 145455, group="다른 고객군")  # 페르소나가 없는 고객군
    edit(example_copy / "data" / "evidence" / "vocab.json", lambda d: d["customer_group"].append("다른 고객군"))
    write_summary(example_copy, *RICH, other)
    shutil.rmtree(example_copy / RUNS)  # 예시 묶음의 실행은 다른 집계 값으로 낸 것이라 뺀다
    played = play(example_copy, pick_by_persona, persona_ids=(ELDERS, KIDS), condition_ids=EIGHT)
    weights = played.record.weights

    people = 100 + 200 + 50 + 100 + 40  # 조식이 없고 모두 돌리는 조건이다
    parties = {ELDERS: 4, KIDS: 4}  # 예시 페르소나의 어른 + 아이
    denominator = 0.5 * 4 + 0.5 * 4
    assert weights.group_multiplier[GROUP] == pytest.approx(people / denominator)
    assert weights.persona_weight == {ELDERS: weights.group_multiplier[GROUP] * 0.5, KIDS: weights.group_multiplier[GROUP] * 0.5}
    # 끼니를 모르는 평일 코스 100명은 점심과 저녁에 반씩 든다.
    assert weights.condition_ratio[GROUP]["meal-lunch-weekday"] == pytest.approx(50 / people)
    assert weights.condition_ratio[GROUP]["dessert-weekend"] == 0.0
    assert sum(weights.condition_ratio[GROUP].values()) == pytest.approx(1)
    # 대표 팀 수 × 일행 수를 다 더하면 그 고객군의 인원이다.
    teams = {
        (p, c): weights.persona_weight[p] * weights.condition_ratio[GROUP][c] for p in (ELDERS, KIDS) for c in EIGHT
    }
    assert sum(size * parties[p] for (p, _), size in teams.items()) == pytest.approx(people)
    # 페르소나가 없는 고객군의 인원은 가중치에 들지 않고, 덮는 몫에서 빠진다.
    assert weights.people_coverage == pytest.approx(people / (people + 10))
    # 원장의 대표하는 크기는 가중치 × 묶음의 비율이다. 실패한 방문에도 적혀 있다.
    for row in played.rows:
        assert row.represented == teams[(row.persona_id, row.condition_id)]
    (failed,) = played.visit(KIDS, "meal-lunch-weekday")
    assert failed.status == "failed" and failed.represented > 0
    # 실패한 방문은 업장별 방문의 크기에 들지 않는다.
    none_ok = sum(r.represented * r.counted_share for r in played.rows if r.status == "ok" and r.choice_kind == "none")
    assert venue_shares(played.rows)["none"]["visits"] == pytest.approx(none_ok)
    # 가상 매출은 기본 데이터 매출에 맞추지 않는다.
    base_total = 100 * 136364 + 200 * 136364 + 50 * 181818 + 100 * 145455 + 40 * 81818
    assert abs(weighted_total(played.rows) - base_total) > len(played.rows)
    assert weights.grades.model_dump() == {
        "group_multiplier": {GROUP: "assumption"},
        "persona_weight": {ELDERS: "assumption", KIDS: "assumption"},
        "condition_ratio": {GROUP: dict.fromkeys(EIGHT, "assumption")},
    }
    assert played.violations() == []
    assert [str(p) for p in check(example_copy, strict=True)] == []


def persona_like(root: Path, source: str, persona_id: str, group: str) -> None:
    """페르소나 파일 하나를 베껴 다른 고객군의 페르소나로 만든다 (지어낸 것). 그 고객군의 몫은 1 이다."""
    data = load_json(persona_file(root, source))
    data.update(persona_id=persona_id, customer_group=group)
    data["share_in_group"].update(value=1)
    save_json(persona_file(root, persona_id), data)


def test_each_group_is_weighed_on_its_own(example_copy):
    """고객군마다 따로 정한다. 일부 달에만 파는 상품을 고른 고객군도, 집계 파일에 없는 고객군도 섞이지 않는다.

    - 가족·친족: 어르신 가족이 금룡을 고른다.
    - B: 더뷔페를 고른다. 저녁 상품은 6~8월에만 팔아 그 방문의 몫이 1/4 이다. 평일 점심에는 답을 두지 않는다(실패).
    - C: 금룡을 고르지만 집계 파일에 매출이 없다.
    """
    persona_like(example_copy, KIDS, "group-b", "B 고객군")
    persona_like(example_copy, ELDERS, "group-c", "C 고객군")
    edit(venue_file(example_copy, "thebuffet"), lambda d: [p.update(months=[6, 7, 8]) for p in d["products"] if p["product_id"].startswith("dinner")])
    write_summary(
        example_copy,
        *RICH[:3],
        line("thebuffet", "lunch-adult", "lunch", "weekend", 100, 145455, group="B 고객군"),
        line("thebuffet", "dinner-child", "dinner", "weekday", 40, 81818, month=7, group="B 고객군"),
    )
    shutil.rmtree(example_copy / RUNS)

    def pick(visit_id: str, request):
        if visit_id == "group-b__meal-lunch-weekday":
            return None
        venue_id = "thebuffet" if visit_id.startswith("group-b") else "geumryong"
        return first_option(request, venue_id) if request.candidate(venue_id) else answer(request, None)

    played = play(example_copy, pick, persona_ids=(ELDERS, "group-b", "group-c"), condition_ids=EIGHT)
    weights = played.record.weights
    # 가족·친족은 어르신 가족(몫 0.5, 4명)만 돌린다. B 는 아이 동반 가족을 베낀 페르소나(몫 1, 4명)다.
    expected = {GROUP: (100 + 200 + 50) / (0.5 * 4), "B 고객군": (100 + 40) / (1 * 4)}
    for group, multiplier in expected.items():
        assert weights.group_multiplier[group] == pytest.approx(multiplier), group
        assert weights.grades.group_multiplier[group] == "assumption"
    seasonal = [row for row in played.rows if row.persona_id == "group-b" and row.venue_id == "thebuffet" and row.counted_share == 0.25]
    assert seasonal  # 일부 달에만 파는 상품을 고르면 그 방문의 몫만큼 센다
    assert any(row.status == "failed" for row in played.visit("group-b", "meal-lunch-weekday"))

    # 집계 파일에 없는 고객군은 비율도 배수도 낼 수 없다.
    assert weights.group_multiplier["C 고객군"] == 0.0 and weights.grades.group_multiplier["C 고객군"] == "unknown"
    assert set(weights.grades.condition_ratio["C 고객군"].values()) == {"unknown"}
    assert weights.persona_weight["group-c"] == 0.0 and weights.grades.persona_weight["group-c"] == "unknown"
    assert weighted_total([row for row in played.rows if row.customer_group == "C 고객군"]) == 0

    # 업장별 방문의 크기는 방문마다 한 번, 몫만큼 센다. 실패한 방문은 세지 않는다.
    shares = venue_shares(played.rows)
    once = {(r.visit_id, r.choice_kind, r.venue_id): r.represented * r.counted_share for r in played.rows if r.status == "ok"}
    for venue_id, value in shares["walkerhill"].items():
        assert value["visits"] == pytest.approx(sum(v for (_, kind, vid), v in once.items() if kind == "walkerhill" and vid == venue_id))
    assert shares["none"]["visits"] == pytest.approx(sum(v for (_, kind, _), v in once.items() if kind == "none"))


def test_weights_do_not_depend_on_what_the_visits_chose(example_copy):
    """워커힐 업장을 고른 방문이 하나도 없어도 무게는 같다. 옛 방식은 이때 배수를 정하지 못해 0 이었다 (T210 에서 바뀜)."""
    shutil.rmtree(example_copy / RUNS)
    played = play(example_copy, lambda visit_id, request: answer(request, None))
    weights = played.record.weights
    # 주말 저녁: 코스 B 180명 + 끼니를 모르는 주말 코스 A 480명의 반. 어르신 가족은 몫 0.5, 4명이다.
    assert weights.group_multiplier == {GROUP: (180 + 240) / (0.5 * 4)}
    assert weights.grades.group_multiplier == {GROUP: "assumption"}
    assert weights.persona_weight == {ELDERS: (180 + 240) / 4}
    assert weights.condition_ratio[GROUP] == {DINNER: 1.0}
    assert all(row.represented == (180 + 240) / 4 for row in played.rows)
    assert weighted_total(played.rows) == 0
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_takeout_without_people_counts_one_team_and_add_ons_count_nobody():
    """빈 칸인 포장은 한 개를 한 팀으로 보고 평균 일행 수를 곱한다. 빈 칸인 그 밖의 상품(추가 상품)은 0 명이다 (docs/FORMATS.md 8절)."""
    rows = rows_of(
        line("geumryong", "course-b", "dinner", "weekend", 10, 100),
        line("geumryong", "course-a", "dinner", "weekend", 3, 100, people=""),  # 추가 상품처럼 빈 칸
        line("thebuffet", "lunch-adult", None, "weekend", 6, 100, occasion="takeout", unit="개", people=""),
        line("thebuffet", "lunch-adult", None, "weekend", 2, 100, occasion="takeout", unit="개", people="", group="다른 고객군"),
    )
    people = group_people(rows, BUNDLE.conditions, BUNDLE.assumed_splits, VENUES, {GROUP: 3.0, "셋째": 5.0})
    assert dict(people[GROUP].by_condition) == {DINNER: 10, "takeout-weekend": 6 * 3.0}
    # 일행 수를 모르는 고객군은 아는 고객군들의 평균(4)을 쓴다.
    assert dict(people["다른 고객군"].by_condition) == {"takeout-weekend": 2 * 4.0}
    # 달을 주면 그 달의 줄만 센다.
    assert group_people(rows, BUNDLE.conditions, BUNDLE.assumed_splits, VENUES, {GROUP: 3.0}, month=6) == {}


def test_persona_weight_grade_is_the_weaker_of_its_two_parts():
    assert weaker("internal", "assumption") == "assumption"
    assert weaker("internal", "review") == "review"
    assert weaker("internal", "official") == "internal"
    assert weaker("assumption", "unknown") == "unknown"


def test_private_run_writes_internal_grades_except_for_split_conditions(example_copy):
    to_private(example_copy)
    edit(persona_file(example_copy, ELDERS), lambda d: d["share_in_group"].update(grade="review"))
    run_dir = private_run(example_copy, condition_ids=EIGHT)
    grades = load_json(run_dir / "run.json")["weights"]["grades"]
    assert grades["group_multiplier"] == {GROUP: "internal"}
    assert grades["persona_weight"] == {ELDERS: "review"}  # 배수(internal)와 몫(review) 가운데 약한 것
    # 식사 조건에는 끼니를 모르는 매출을 반씩 나눈 것이 들었다. 디저트와 포장은 매출이 없다는 것을 기본 데이터로 안다.
    assert grades["condition_ratio"][GROUP] == {c: "assumption" if c.startswith("meal-") else "internal" for c in EIGHT}


def test_part_of_a_split_in_the_run_makes_every_grade_of_the_group_an_assumption(example_copy):
    """저녁만 돌리면 끼니를 모르는 매출의 반만 든다. 그러면 합계가 반반이라는 가정에 기대므로 비율과 배수가 모두 설계 가정이다."""
    to_private(example_copy)
    run_dir = private_run(example_copy, condition_ids=(DINNER, "dessert-weekend"))
    weights = load_json(run_dir / "run.json")["weights"]
    assert weights["grades"]["group_multiplier"] == {GROUP: "assumption"}
    assert weights["grades"]["condition_ratio"] == {GROUP: {DINNER: "assumption", "dessert-weekend": "assumption"}}
    assert weights["condition_ratio"] == {GROUP: {DINNER: 1.0, "dessert-weekend": 0.0}}
    # 나눈 매출이 아예 들지 않으면(나누는 줄의 조건을 하나도 돌리지 않으면) 합계가 그 비율에 기대지 않는다.
    rows = rows_of(line("geumryong", "course-a", None, "weekday", 10, 100), line("pavilion", "cake", None, "weekend", 5, 100, occasion="dessert", unit="개"))
    dessert = [c for c in BUNDLE.conditions if c.condition_id == "dessert-weekend"]
    revenue = group_revenue(rows, dessert, BUNDLE.assumed_splits, only("geumryong", "pavilion"))
    assert not revenue[GROUP].split_partly_used
    assert condition_ratios(revenue, [GROUP], ["dessert-weekend"], "private")[1] == {GROUP: {"dessert-weekend": "internal"}}


# ── 가격이 빈 상품 ───────────────────────────────────────────────────────


def without_price(root: Path, product_id: str = "course-b") -> None:
    edit(venue_file(root, "geumryong"), lambda d: product_of(d, product_id).update(price=None, grade="unknown"))


def test_price_is_filled_from_the_summary_and_rounded_to_hundreds(example_copy):
    without_price(example_copy)
    # 코스 B 의 줄: 낸 금액 36,012,345 ÷ 180개 = 200,068.58… → 백 원 단위로 200,100.
    summary = example_copy / "data" / "samples" / "base_summary.csv"
    summary.write_bytes(summary.read_bytes().replace(b",180,36000000,32727240,", b",180,36012345,32738495,"))

    venue = load_inputs(example_copy, "sample").venues["geumryong"]
    course = venue.product("course-b")
    assert (course.price, course.price_basis, course.grade) == (200100, "included", "assumption")
    assert venue.product("course-a").price == 150000  # 가격이 있는 상품은 그대로다
    assert load_json(venue_file(example_copy, "geumryong"))["products"][1]["price"] is None  # 파일은 그대로다

    played = play(example_copy, lambda visit_id, request: answer(request, "geumryong", "geumryong-o2"))
    (row,) = played.rows
    assert (row.product_id, row.list_price, row.paid) == ("course-b", 200100, 800400)
    assert played.record.filled_products == ["geumryong:course-b"]
    assert played.record.skipped_products == []
    assert played.violations() == []
    assert [str(p) for p in check(example_copy, strict=True)] == []

    to_private(example_copy)
    assert load_inputs(example_copy, "private").venues["geumryong"].product("course-b").grade == "internal"


def test_percent_change_reaches_filled_prices(example_copy):
    """단가를 먼저 채우고 상황을 적용한다. 업장 전체와 상품 하나의 퍼센트 변경이 채운 단가에도 걸린다 (docs/FORMATS.md 3절, T223)."""
    without_price(example_copy)  # 코스 B 는 가상 예시 값으로 채우면 200,000원이다
    every = write_scenario(
        example_copy,
        "our_price",
        {"op": "change_price_pct", "venue_id": "geumryong", "product_id": None, "pct": 10},
        scenario_id="geumryong-all-up",
    )
    inputs = load_inputs(example_copy, "sample", every)
    venue = inputs.venues["geumryong"]
    assert (venue.product("course-a").price, venue.product("course-b").price) == (165000, 220000)
    # 오른 값도 채운 단가다. 등급과 가격 표기는 채울 때의 것 그대로다.
    assert (venue.product("course-b").price_basis, venue.product("course-b").grade) == ("included", "assumption")
    assert inputs.filled == ["geumryong:course-b"]

    one = write_scenario(
        example_copy,
        "our_price",
        {"op": "change_price_pct", "venue_id": "geumryong", "product_id": "course-b", "pct": -10},
        scenario_id="geumryong-course-b-down",
    )
    inputs = load_inputs(example_copy, "sample", one)
    assert inputs.venues["geumryong"].product("course-b").price == 180000 and inputs.filled == ["geumryong:course-b"]
    # 형식 검사도 같은 순서로 적용해 본다. 가상 예시 값으로 채우는 상품이라 상품 하나를 가리켜도 막지 않는다.
    scenario_problems = [str(p) for p in check(example_copy) if p.path.startswith("scenarios/")]
    assert scenario_problems == []

    # 집계 파일에 없어 채우지 못하는 상품을 상품 하나로 가리키면 형식 검사가 막는다 (엔진도 멈춘다).
    summary = example_copy / "data" / "samples" / "base_summary.csv"
    summary.write_text(
        "".join(row for row in summary.read_text(encoding="utf-8-sig").splitlines(keepends=True) if ",course-b," not in row),
        encoding="utf-8-sig",
        newline="",
    )
    found = [p.message for p in check(example_copy) if p.path == "scenarios/geumryong-course-b-down.json"]
    assert len(found) == 1 and "가격이 비어 있어" in found[0]
    with pytest.raises(ScenarioError, match="가격이 비어 있어"):
        load_inputs(example_copy, "sample", one)


def test_format_check_says_when_it_applied_without_filled_prices(example_copy):
    """가상 예시 값을 읽지 못하면 형식 검사는 단가를 채우지 않고 적용한다. 그때 나온 상황 오류에는 그 사실을 붙인다 (T223)."""
    without_price(example_copy)
    one = write_scenario(
        example_copy,
        "our_price",
        {"op": "change_price_pct", "venue_id": "geumryong", "product_id": "course-b", "pct": 10},
        scenario_id="geumryong-course-b-up",
    )
    where = f"scenarios/{one}.json"
    assert [p for p in check(example_copy) if p.path == where] == []  # 읽을 수 있으면 채워서 적용해 통과한다

    summary = example_copy / "data" / "samples" / "base_summary.csv"
    header, first, *rest = summary.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    cells = first.rstrip("\n").split(",")
    cells[SUMMARY_COLUMNS.index("quantity")] = "많음"  # 숫자가 아니라 읽지 못한다
    summary.write_text("".join([header, ",".join(cells) + "\n", *rest]), encoding="utf-8-sig", newline="")
    found = [p.message for p in check(example_copy) if p.path == where]
    assert len(found) == 1 and "가격이 비어 있어" in found[0]
    assert found[0].endswith("(가상 예시 값을 읽지 못해 단가를 채우지 않고 적용함)")


def unpriced_with_basis(product_id: str = "course-b", basis: str = "excluded_vat") -> dict[str, Venue]:
    """금룡의 상품 하나를 가격이 빈 상품으로 바꾼다. 채우면 표기가 included 로 바뀌는 것을 보려고 표기를 다르게 둔다."""
    data = VENUES["geumryong"].model_dump(mode="json")
    product_of(data, product_id).update(price=None, grade="unknown", price_basis=basis)
    return {"geumryong": Venue.model_validate(data)}


SET_B = {"op": "set_price", "venue_id": "geumryong", "product_id": "course-b", "price": 210000}
EVERY_UP = {"op": "change_price_pct", "venue_id": "geumryong", "product_id": None, "pct": 10}
REMOVE_B = {"op": "remove_product", "venue_id": "geumryong", "product_id": "course-b"}


ADD_B = {"op": "add_product", "venue_id": "geumryong", "product": new_product("course-b", price=None, grade="unknown")}


@pytest.mark.parametrize(
    "kind, changes",
    [
        ("our_price", [SET_B]),
        ("our_price", [SET_B, EVERY_UP]),
        ("our_price", [SET_B, {"op": "change_price_pct", "venue_id": "geumryong", "product_id": "course-b", "pct": -10}]),
        ("our_price", [SET_B, REMOVE_B]),
        ("our_price", [REMOVE_B]),
        ("our_price", [{"op": "set_price", "venue_id": "geumryong", "product_id": "course-a", "price": 140000}]),
        ("our_price", [EVERY_UP, SET_B]),
        ("our_promo", [REMOVE_B, ADD_B]),
        ("our_promo", [SET_B, REMOVE_B, ADD_B]),
        ("our_promo", [REMOVE_B, ADD_B, SET_B]),
    ],
    ids=[
        "set",
        "set-then-every",
        "set-then-one",
        "set-then-remove",
        "remove",
        "set-priced",
        "every-then-set",
        "remove-then-add",
        "set-remove-add",
        "remove-add-set",
    ],
)
def test_set_price_gives_the_same_result_as_the_old_order(kind, changes):
    """set_price 로 값을 정한 상품은 채운 상품이 아니다. 상황을 먼저 적용하고 채우던 때(11-20 까지)와 결과가 같다 (T223)."""
    venues = unpriced_with_basis()
    rows = rows_of(line("geumryong", "course-b", "dinner", "weekday", 10, 100000))
    applied = scenario(kind, *changes)
    old = fill_prices(apply_scenario(venues, applied), rows, "private")
    assert apply_with_prices(venues, applied, rows, "private") == old


def test_set_price_on_a_filled_product_keeps_the_venue_grade_and_basis():
    venues = unpriced_with_basis()
    rows = rows_of(line("geumryong", "course-b", "dinner", "weekday", 10, 100000))
    applied, filled = apply_with_prices(venues, scenario("our_price", SET_B), rows, "private")
    course = applied["geumryong"].product("course-b")
    assert (course.price, course.price_basis, course.grade) == (210000, "excluded_vat", "unknown") and filled == []
    # 값을 정하지 않으면 채운 단가에 퍼센트가 걸리고 채운 상품으로 남는다.
    applied, filled = apply_with_prices(venues, scenario("our_price", EVERY_UP), rows, "private")
    course = applied["geumryong"].product("course-b")
    assert (course.price, course.price_basis, course.grade) == (121000, "included", "internal")
    assert filled == ["geumryong:course-b"]


def test_product_added_without_a_price_is_filled_after_the_scenario():
    """상황이 더한 가격 빈 상품은 다 적용한 뒤에 채운다. 그래서 그 상황의 퍼센트 변경은 받지 않는다 (docs/FORMATS.md 3절)."""
    venues = {"geumryong": VENUES["geumryong"]}
    rows = rows_of(line("geumryong", "tea", "dinner", "weekday", 10, 10000))
    added = scenario(
        "our_promo",
        {"op": "add_product", "venue_id": "geumryong", "product": new_product("tea", price=None, grade="unknown")},
        EVERY_UP,
    )
    applied, filled = apply_with_prices(venues, added, rows, "sample")
    tea = applied["geumryong"].product("tea")
    assert (tea.price, tea.price_basis, tea.grade) == (11000, "included", "assumption") and filled == ["geumryong:tea"]
    assert applied["geumryong"].product("course-a").price == 165000
    # 집계 파일에 없으면 채우지 못해 가격이 빈 채로 남는다 (후보에서 빠진다).
    applied, filled = apply_with_prices(venues, added, [], "sample")
    assert applied["geumryong"].product("tea").price is None and filled == []


def test_percent_change_on_a_price_nobody_could_fill_stops():
    venues = unpriced_with_basis()
    one = scenario("our_price", {"op": "change_price_pct", "venue_id": "geumryong", "product_id": "course-b", "pct": 10})
    with pytest.raises(ScenarioError, match="가격이 비어 있어"):
        apply_with_prices(venues, one, [], "sample")
    # 업장 전체는 가격이 있는 상품만 바꾼다. 바꿀 것이 하나도 없으면 멈춘다.
    applied, filled = apply_with_prices(venues, scenario("our_price", EVERY_UP), [], "sample")
    assert [p.price for p in applied["geumryong"].products] == [165000, None] and filled == []
    data = venues["geumryong"].model_dump(mode="json")
    product_of(data, "course-a").update(price=None, grade="unknown")
    with pytest.raises(ScenarioError, match="바뀌는 것이 없다"):
        apply_with_prices({"geumryong": Venue.model_validate(data)}, scenario("our_price", EVERY_UP), [], "sample")


def unpriced(venue: Venue, *product_ids: str) -> Venue:
    data = venue.model_dump(mode="json")
    for product_id in product_ids:
        product_of(data, product_id).update(price=None, grade="unknown")
    return Venue.model_validate(data)


def test_fill_prices_leaves_products_nobody_bought():
    venues = {"geumryong": unpriced(VENUES["geumryong"], "course-b")}
    filled, which = fill_prices(venues, rows_of(line("geumryong", "course-a", "lunch", "weekday", 0, 0)), "sample")
    assert filled["geumryong"].product("course-b").price is None and which == []
    # 반올림한 단가가 0 원이면 채우지 않는다 (낸 금액 10원 ÷ 100개).
    cheap = line("geumryong", "course-b", "dinner", "weekday", 100, 0) | {"paid": "10", "revenue_net": "9"}
    filled, which = fill_prices(venues, rows_of(cheap), "sample")
    assert filled["geumryong"].product("course-b").price is None and which == []


def test_fill_prices_keeps_venues_apart_and_needs_the_same_unit():
    twin = VENUES["pavilion"].model_copy(update={"venue_id": "pavilion-two"})
    venues = {"pavilion": unpriced(VENUES["pavilion"], "bingsu"), "pavilion-two": unpriced(twin, "bingsu")}
    rows = rows_of(
        line("pavilion", "bingsu", None, "weekend", 2, 10000, occasion="dessert", unit="개"),
        line("pavilion-two", "bingsu", None, "weekend", 2, 20000, occasion="dessert", unit="개"),
    )
    filled, which = fill_prices(venues, rows, "private")
    # 같은 product_id 라도 업장마다 따로 낸다. 낸 금액은 매출 × 1.1 이다.
    assert (filled["pavilion"].product("bingsu").price, filled["pavilion-two"].product("bingsu").price) == (11000, 22000)
    assert which == ["pavilion-two:bingsu", "pavilion:bingsu"] and filled["pavilion"].product("bingsu").grade == "internal"
    # 단위가 업장 정의와 다른 줄이 있으면 수량을 더할 수 없어 멈춘다.
    wrong = line("pavilion", "bingsu", None, "weekday", 1, 10000, occasion="dessert", unit="그릇")
    with pytest.raises(ValueError, match="단위"):
        fill_prices(venues, [*rows, *rows_of(wrong)], "private")


# ── 기본 데이터의 요약 ───────────────────────────────────────────────────


PROFILE_ROWS = (
    line("geumryong", "course-a", "dinner", "weekend", 60, 100),
    line("geumryong", "course-b", "dinner", "weekend", 20, 100),
    line("thebuffet", "dinner-adult", "dinner", "weekday", 15, 100),
    line("ondal", "course", "lunch", "weekday", 5, 100),
    line("thebuffet", "breakfast", "breakfast", "weekday", 900, 100),  # 조식은 넣지 않는다
    line("pavilion", "cake", None, "weekend", 0, 0, occasion="dessert", unit="개"),  # 매출이 없는 갈래는 적지 않는다
)


def test_base_profile_buckets_shares_against_an_even_split():
    profile = base_profiles(rows_of(*PROFILE_ROWS), "bucketed")[GROUP]
    # 업장(8곳): 0.8·0.15·0.05 를 1/8 과 견준다 → 6.4배 high, 1.2배 mid, 0.4배 low.
    assert profile["venue_share"] == {"geumryong": "high", "ondal": "low", "thebuffet": "mid"}
    assert profile["occasion_share"] == {"meal": "high"}
    # 평일·주말(둘): 0.2·0.8 을 1/2 과 견준다 → 0.4배 low, 1.6배 high.
    assert profile["day_type_share"] == {"weekday": "low", "weekend": "high"}
    assert profile["top_products"] == {"geumryong": ["course-a", "course-b"], "ondal": ["course"], "thebuffet": ["dinner-adult"]}

    raw = base_profiles(rows_of(*PROFILE_ROWS), "raw")[GROUP]
    assert raw["venue_share"] == {"geumryong": 0.8, "ondal": 0.05, "thebuffet": 0.15}
    with pytest.raises(ValueError, match="base_profile_mode"):
        base_profiles(rows_of(*PROFILE_ROWS), "none")


def test_base_profile_example_of_the_format_doc_and_the_edges_of_the_buckets():
    # FORMATS.md 5절의 예: 금룡 0.6, 더뷔페 0.3, 온달 0.1 (지어낸 값이다).
    doc = rows_of(*(line(v, "x", "dinner", "weekend", n, 100) for v, n in (("geumryong", 6), ("thebuffet", 3), ("ondal", 1))))
    assert base_profiles(doc, "bucketed")[GROUP]["venue_share"] == {"geumryong": "high", "ondal": "mid", "thebuffet": "high"}
    # 경계: 고르게 나눈 몫(1/8)의 꼭 1.5배(3/16)는 high, 꼭 0.5배(1/16)는 mid 다.
    edges = rows_of(line("geumryong", "x", "dinner", "weekend", 3, 100), line("thebuffet", "x", "dinner", "weekend", 1, 100), line("ondal", "x", "dinner", "weekend", 12, 100))
    assert base_profiles(edges, "bucketed")[GROUP]["venue_share"] == {"geumryong": "high", "ondal": "high", "thebuffet": "mid"}
    # raw 는 소수 셋째 자리까지 보낸다.
    thirds = rows_of(*(line(v, "x", "dinner", "weekend", 1, 100) for v in ("geumryong", "thebuffet", "ondal")))
    assert base_profiles(thirds, "raw")[GROUP]["venue_share"] == {"geumryong": 0.333, "ondal": 0.333, "thebuffet": 0.333}
    # 고객군마다 따로 낸다.
    two = rows_of(line("geumryong", "x", "dinner", "weekend", 1, 100), line("ondal", "y", "lunch", "weekday", 1, 100, group="B"))
    profiles = base_profiles(two, "bucketed")
    assert profiles[GROUP]["venue_share"] == {"geumryong": "high"} and profiles["B"]["venue_share"] == {"ondal": "high"}
    assert profiles["B"]["top_products"] == {"ondal": ["y"]} and profiles["B"]["day_type_share"] == {"weekday": "high"}


def test_top_products_keep_three_in_order_of_revenue():
    many = [line("geumryong", f"dish-{n}", "dinner", "weekend", 10 - n, 100) for n in range(5)]
    many.append(line("geumryong", "dish-z", "dinner", "weekend", 10, 100))  # dish-0 과 같으면 이름 순서
    profile = base_profiles(rows_of(*many), "bucketed")[GROUP]
    assert profile["top_products"] == {"geumryong": ["dish-0", "dish-z", "dish-1"]}


def test_private_run_sends_the_base_profile_and_sample_run_never_does(example_copy):
    to_private(example_copy)
    private = load_inputs(example_copy, "private", base_profile_mode="bucketed")
    profile = private.persona_json[ELDERS]["base_profile"]
    # 예시 값의 주말 비중은 0.71 이라 고르게 나눈 몫(0.5)의 1.5배(0.75)에 못 미쳐 mid 다.
    assert profile == {
        "venue_share": {"geumryong": "high"},
        "occasion_share": {"meal": "high"},
        "day_type_share": {"weekday": "mid", "weekend": "mid"},
        "top_products": {"geumryong": ["course-a", "course-b"]},
    }
    # 함수의 기본값도 실행과 같다 (다른 영역이 이 함수로 만든 요청이 실행의 요청과 같아야 한다).
    assert load_inputs(example_copy, "private").persona_json[ELDERS]["base_profile"] == profile
    assert "base_profile" not in load_inputs(example_copy, "private", base_profile_mode="none").persona_json[ELDERS]

    run_dir = private_run(example_copy)
    record = load_json(run_dir / "run.json")
    assert record["base_profile_mode"] == "bucketed"  # 실행의 기본값은 bucketed 다
    (saved,) = (run_dir / "llm").iterdir()
    assert load_json(saved)["request"]["persona"]["base_profile"] == profile

    with pytest.raises(ValueError, match="base_profile_mode 는 none"):
        load_inputs(example_copy, "sample", base_profile_mode="bucketed")
    with pytest.raises(ValueError, match="base_profile_mode 는 none"):
        run_scenario(example_copy, "baseline", base_profile_mode="raw")
    assert "base_profile" not in load_inputs(example_copy, "sample").persona_json[ELDERS]


def test_base_profile_does_not_change_with_the_venues_read(example_copy):
    to_private(example_copy)
    every = load_inputs(example_copy, "private", base_profile_mode="bucketed")
    some = load_inputs(example_copy, "private", venue_ids=["thebuffet"], base_profile_mode="bucketed")
    assert some.persona_json[ELDERS]["base_profile"] == every.persona_json[ELDERS]["base_profile"]


def test_group_without_sales_gets_an_empty_base_profile(example_copy):
    write_summary(example_copy, private=True)
    inputs = load_inputs(example_copy, "private", base_profile_mode="raw")
    assert inputs.persona_json[ELDERS]["base_profile"] == {
        "venue_share": {},
        "occasion_share": {},
        "day_type_share": {},
        "top_products": {},
    }


def test_scenario_follows_the_base_profile_mode_of_its_baseline(example_copy):
    to_private(example_copy)
    base = private_run(example_copy, base_profile_mode="raw")
    later = NOW + timedelta(hours=1)
    with pytest.raises(ValueError, match="기준 실행의 base_profile_mode 는 raw"):
        private_run(example_copy, now=later, scenario_id=COMPETITOR_DISCOUNT, weights_from=base.name, base_profile_mode="bucketed",
                    persona_ids=None, condition_ids=None)
    again = private_run(example_copy, now=later, scenario_id=COMPETITOR_DISCOUNT, weights_from=base.name, persona_ids=None, condition_ids=None)
    assert load_json(again / "run.json")["base_profile_mode"] == "raw"


# ── 기본 데이터의 요약은 확인한 공급자로만 보낸다 (T115) ────────────────


def test_base_profile_is_not_sent_until_the_provider_is_confirmed(example_copy):
    """기본 데이터의 요약이 밖의 LLM 으로 나가는 실행은, 그 공급자로 보내도 된다고 확인한 PC 에서만 돈다.

    확인은 공급자의 이름으로 적는다. 다른 공급자의 확인은 통하지 않는다 (받는 회사가 바뀌면 다시 확인한다).
    """
    to_private(example_copy)
    runs = example_copy / "private" / "runs"
    for confirmed in (None, "", "another-provider"):
        for mode in (None, "bucketed", "raw"):
            with pytest.raises(ValueError, match="아직 확인되지 않았다") as stopped:
                private_run(example_copy, base_profile_mode=mode, base_profile_confirmed_for=confirmed)
            # 무엇을 하면 되는지 알려 준다: 확인한 뒤 적을 것과, 확인 전에 돌리는 법.
            assert f"BASE_PROFILE_CONFIRMED_FOR={PROVIDER}" in str(stopped.value) and "--base-profile none" in str(stopped.value)
    assert not runs.exists()  # 실행 폴더를 만들지 않았고 LLM 도 부르지 않았다

    # 요약을 보내지 않으면 확인이 없어도 돈다.
    none = private_run(example_copy, base_profile_mode="none", base_profile_confirmed_for=None)
    (saved,) = (none / "llm").iterdir()
    assert "base_profile" not in load_json(saved)["request"]["persona"]
    # 재생만 하면(LLM 을 주지 않음) 아무것도 나가지 않으므로 막지 않는다. 저장된 답이 없어 방문은 실패로 남는다.
    replay = private_run(example_copy, now=NOW + timedelta(hours=1), llm=None, base_profile_confirmed_for=None)
    record = load_json(replay / "run.json")
    assert (record["base_profile_mode"], record["llm"]["calls_new"], record["counts"]["failed"]) == ("bucketed", 0, 1)

    # 확인한 공급자면 요약을 보낸다.
    base = private_run(example_copy, now=NOW + timedelta(hours=2), base_profile_confirmed_for=PROVIDER)
    (saved,) = (base / "llm").iterdir()
    assert "base_profile" in load_json(saved)["request"]["persona"]
    # 상황은 기준 실행의 방식을 따르므로, 기준 실행이 요약을 보냈으면 상황도 확인이 있어야 돈다.
    scenario = dict(scenario_id=COMPETITOR_DISCOUNT, weights_from=base.name, persona_ids=None, condition_ids=None)
    with pytest.raises(ValueError, match="아직 확인되지 않았다"):
        private_run(example_copy, now=NOW + timedelta(hours=3), base_profile_confirmed_for=None, **scenario)
    assert private_run(example_copy, now=NOW + timedelta(hours=3), **scenario).is_dir()

    # 주소로 받는 곳이 갈리는 공급자는 받는 곳의 이름(주소의 호스트까지)으로 견준다. 공급자의 이름만 적은 확인은 통하지 않는다.
    elsewhere = dict(now=NOW + timedelta(hours=4), receiver=f"{PROVIDER}:host-a.example.test")
    for confirmed in (PROVIDER, f"{PROVIDER}:host-b.example.test"):
        with pytest.raises(ValueError, match=f"BASE_PROFILE_CONFIRMED_FOR={PROVIDER}:host-a.example.test"):
            private_run(example_copy, base_profile_confirmed_for=confirmed, **elsewhere)
    assert private_run(example_copy, base_profile_confirmed_for=f"{PROVIDER}:host-a.example.test", **elsewhere).is_dir()

    # 가상 예시로 돌릴 때는 요약이 없어 확인을 보지 않는다.
    sample = private_run(example_copy, data_mode="sample", now=NOW + timedelta(hours=5), base_profile_confirmed_for=None)
    assert load_json(sample / "run.json")["base_profile_mode"] == "none"


def test_command_reads_the_confirmation_from_the_environment(example_copy, quiet_env, capsys):
    """명령은 확인한 공급자를 `.env` 의 `BASE_PROFILE_CONFIRMED_FOR` 에서 읽는다."""
    to_private(example_copy)
    runs = example_copy / "private" / "runs"
    quiet_env.setenv("LLM_PROVIDER", "openai-compatible")
    quiet_env.setenv("LLM_MODEL", "some-model")
    quiet_env.setenv("LLM_BASE_URL", "https://LLM.example.test:8443/v1")
    here = "openai-compatible:llm.example.test"  # 받는 곳의 이름: 공급자와 주소의 호스트 (포트와 경로는 뺀다)
    quiet_env.setattr(cli, "make_provider", lambda settings: Fake())
    quiet_env.setattr(cli, "datetime", Clock())  # 부를 때마다 5분씩 가는 시계
    private = ["--data", "private", "--root", str(example_copy), *EXAMPLE_PROMPT, "--personas", ELDERS, "--conditions", DINNER]

    # 적혀 있지 않거나, 다른 공급자나 다른 주소가 적혀 있거나, 주소 없이 공급자의 이름만 적혀 있으면 멈추고 실행 폴더를 만들지 않는다.
    for written in (None, "claude-code", "openai-compatible", "openai-compatible:other.example.test"):
        if written:
            quiet_env.setenv("BASE_PROFILE_CONFIRMED_FOR", written)
        assert cli.main(private) == cli.EXIT_FAILED
        said = capsys.readouterr().err
        assert "아직 확인되지 않았다" in said and f"BASE_PROFILE_CONFIRMED_FOR={here}" in said
    assert not runs.exists()

    # 확인 전에도 요약을 보내지 않거나 재생만 하면 돈다.
    assert cli.main([*private, "--base-profile", "none"]) == cli.EXIT_OK
    assert cli.main([*private, "--replay-only"]) == cli.EXIT_OK
    capsys.readouterr()

    # 지금 받는 곳의 이름을 적으면 요약을 보낸다. 앞뒤의 빈칸은 봐준다.
    quiet_env.setenv("BASE_PROFILE_CONFIRMED_FOR", f" {here} ")
    assert cli.main(private) == cli.EXIT_OK
    assert "기본 데이터의 요약 bucketed" in capsys.readouterr().out
    records = [load_json(path / "run.json") for path in sorted(runs.iterdir())]
    assert [r["base_profile_mode"] for r in records] == ["none", "bucketed", "bucketed"]
    assert [r["llm"]["calls_new"] for r in records] == [1, 0, 1]

    # 주소를 다른 곳으로 바꾸면 적어 둔 확인이 맞지 않아 다시 멈춘다.
    quiet_env.setenv("LLM_BASE_URL", "https://other.example.test/v1")
    assert cli.main(private) == cli.EXIT_FAILED
    assert "BASE_PROFILE_CONFIRMED_FOR=openai-compatible:other.example.test" in capsys.readouterr().err
    assert len(list(runs.iterdir())) == 3


# ── 기준 실행 뒤에 집계 파일이 바뀌면 ────────────────────────────────────


def test_scenario_does_not_run_after_the_summary_changed(example_copy):
    shutil.rmtree(example_copy / RUNS)
    base = play(example_copy, pick_geumryong)
    summary = example_copy / "data" / "samples" / "base_summary.csv"
    summary.write_bytes(summary.read_bytes().replace(b",300,45000000,40909200,", b",310,46500000,42272840,"))
    with pytest.raises(ValueError, match="summary"):
        run_scenario(example_copy, COMPETITOR_DISCOUNT, weights_from=base.run_dir.name)


def test_summary_is_required_and_read_strictly(example_copy):
    (example_copy / "data" / "samples" / "base_summary.csv").unlink()
    with pytest.raises(FileNotFoundError, match="집계 파일이 없다"):
        load_inputs(example_copy, "sample")
    with pytest.raises(FileNotFoundError, match="private"):
        load_inputs(example_copy, "private")
    bad = line("geumryong", "course-a", "lunch", "weekday", 10, 100) | {"revenue_net": "1"}
    write_summary(example_copy, bad)
    with pytest.raises(ValueError, match="2번째 줄"):
        load_inputs(example_copy, "sample")


# ── 업장별 가상 매출과 비중 ──────────────────────────────────────────────


def test_venue_shares_come_from_the_weighted_revenue(example_copy):
    write_summary(example_copy, *RICH)
    shutil.rmtree(example_copy / RUNS)

    def pick(visit_id: str, request):
        if visit_id.startswith(KIDS) and visit_id.endswith("weekday"):
            return answer(request, None)
        if visit_id.startswith(KIDS) and request.candidate("examplehotel-buffet"):
            return first_option(request, "examplehotel-buffet")
        return pick_by_persona(visit_id, request)

    played = play(example_copy, pick, persona_ids=(ELDERS, KIDS), condition_ids=EIGHT)
    shares = venue_shares(played.rows)
    walkerhill = shares["walkerhill"]
    assert shares["walkerhill_total"] == weighted_total(played.rows)
    assert sum(v["weighted_revenue"] for v in walkerhill.values()) == shares["walkerhill_total"]
    assert sum(v["share"] for v in walkerhill.values()) == pytest.approx(1)
    assert set(walkerhill) <= {"geumryong", "thebuffet"}
    # 경쟁 업장과 "이용하지 않음"은 분모에 넣지 않고 방문의 크기로 따로 낸다.
    went = {row.visit_id: row.represented for row in played.rows if row.venue_id == "examplehotel-buffet"}
    assert shares["competitor"] == {"examplehotel-buffet": {"visits": pytest.approx(sum(went.values()))}}
    assert shares["none"]["visits"] > 0

    # 한 고객군만 볼 수 있다. 없는 고객군이면 비중을 낼 수 없다.
    assert venue_shares(played.rows, GROUP)["walkerhill_total"] == shares["walkerhill_total"]
    nobody = venue_shares(played.rows, "없는 고객군")
    assert nobody == {"walkerhill": {}, "walkerhill_total": 0, "competitor": {}, "none": {"visits": 0.0}}


def test_venue_shares_count_a_visit_once_even_with_many_lines(example_copy):
    played = play(example_copy, lambda visit_id, request: first_option(request, "thebuffet"), persona_ids=(KIDS,))
    assert len([row for row in played.rows if row.venue_id == "thebuffet"]) == 2  # 성인 줄과 어린이 줄
    (only,) = {row.represented for row in played.rows}
    assert venue_shares(played.rows)["walkerhill"]["thebuffet"]["visits"] == pytest.approx(only)
    assert venue_shares(played.rows)["walkerhill"]["thebuffet"]["share"] == 1.0


# ── 저장소의 업장 정의와 가상 예시 값 ────────────────────────────────────


def test_sample_summary_fills_every_missing_price_of_the_real_venues():
    """저장소의 가상 예시 값은 워커힐 8개 업장의 상품을 모두 담는다. 그래서 가상 예시로 돌리면 가격이 빈 상품이 모두 채워진다."""
    venues = {p.stem: read_model(p, Venue) for p in sorted((REPO_ROOT / "data" / "venues").glob("*.json"))}
    missing = sorted(f"{v.venue_id}:{p.product_id}" for v in venues.values() for p in v.products if p.price is None)
    filled_venues, filled = fill_prices(venues, read_summary(summary_path(REPO_ROOT, "sample")), "sample")
    assert missing and filled == missing
    for item in filled:
        venue_id, _, product_id = item.partition(":")
        product = filled_venues[venue_id].product(product_id)
        assert product.price > 0 and product.price % 100 == 0 and product.grade == "assumption"


# ── 실행하는 명령 ───────────────────────────────────────────────────────


@pytest.fixture
def quiet_env(monkeypatch):
    """이 PC 의 .env 와 환경 변수가 테스트에 섞이지 않게 한다."""
    for name in LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "load_dotenv", lambda *args, **kwargs: False)
    return monkeypatch


EXAMPLE_PROMPT = ("--prompt", "p1")  # 예시 묶음에는 p1 만 있다. 명령의 기본값은 팀이 쓰는 판이다 (T108)


def command(root: Path, *more: str) -> int:
    return cli.main(
        ["--data", "sample", "--root", str(root), "--replay-only", *EXAMPLE_PROMPT, "--personas", ELDERS, "--conditions", DINNER, *more]
    )


def test_command_tells_about_filled_prices_coverage_and_missing_groups(example_copy, quiet_env, capsys):
    shutil.rmtree(example_copy / RUNS)  # 재생할 응답이 없어 방문이 실패한다. 무게는 그래도 정해진다
    assert command(example_copy) == cli.EXIT_OK
    said = capsys.readouterr()
    assert "기본 데이터의 요약 none · 가격을 집계 파일로 채운 상품 0개 · 채우지 못해 뺀 상품 0개" in said.out
    assert "페르소나가 있는 고객군이 집계 파일의 인원 가운데 100.0% 를 차지한다" in said.out
    assert "찾지 못한 고객군" not in said.err

    # 페르소나의 고객군 이름이 집계 파일과 다르면 알린다 (가장 흔한 까닭이다).
    edit(persona_file(example_copy, ELDERS), lambda d: d.update(customer_group="가족 친족"))
    quiet_env.setattr(cli, "datetime", type("Later", (), {"now": staticmethod(lambda: NOW.replace(tzinfo=None))}))
    assert command(example_copy) == cli.EXIT_OK
    said = capsys.readouterr()
    assert "찾지 못한 고객군이 있다: 가족 친족" in said.err
    assert "0.0% 를 차지한다" in said.out

    assert command(example_copy, "--base-profile", "bucketed") == cli.EXIT_FAILED
    assert "base_profile_mode 는 none" in capsys.readouterr().err


def test_same_condition_twice_is_refused(example_copy):
    with pytest.raises(ValueError, match="같은 방문 조건을 두 번"):
        run_scenario(example_copy, "baseline", persona_ids=[ELDERS], condition_ids=[DINNER, DINNER])


def test_weights_refuse_ratios_outside_zero_to_one():
    grades = {"group_multiplier": {GROUP: "assumption"}, "persona_weight": {ELDERS: "assumption"}}
    with pytest.raises(ValueError, match="0 ~ 1"):
        Weights.model_validate(
            {
                "group_multiplier": {GROUP: 1.0},
                "persona_weight": {ELDERS: 0.5},
                "condition_ratio": {GROUP: {DINNER: 1.5, LUNCH: -0.5}},  # 더하면 1 이지만 범위 밖이다
                "grades": grades | {"condition_ratio": {GROUP: {DINNER: "assumption", LUNCH: "assumption"}}},
            }
        )


def test_command_runs_on_the_example_baseline_with_the_same_venues(example_copy, quiet_env, capsys):
    """예시 묶음의 기준 실행은 엔진이 쓴 것이라, 같은 업장으로 고르면 그 실행의 가중치로 상황을 돌릴 수 있다."""
    venues = ["--venues", "geumryong", "examplehotel-chinese"]
    quiet_env.setattr(cli, "datetime", type("Later", (), {"now": staticmethod(lambda: NOW.replace(tzinfo=None))}))
    code = cli.main(
        ["--data", "sample", "--root", str(example_copy), "--replay-only", *EXAMPLE_PROMPT, "--scenario", COMPETITOR_DISCOUNT, *venues]
    )
    said = capsys.readouterr()
    assert code == cli.EXIT_OK, said.err
    assert f"기준 실행 {BASELINE_RUN}" in said.out
    assert "실패" not in said.err  # 예시의 저장된 응답을 재생했다
