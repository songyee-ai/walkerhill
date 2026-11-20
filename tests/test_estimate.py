"""상수 추정 (T212, `engine/estimate.py`): 업장 상수를 고객군의 실제 업장 몫에 맞춘다.

- 맞추기(`fit`)와 몫 내기(`simulate`)는 손으로 지은 방문으로 본다. 값은 모두 지어낸 것이다.
- 원장 읽기(`scored_visits`)는 손으로 지은 원장 줄로 본다.
- 고객군마다 업장별 인원(`group_venue_people`)은 예시 묶음과 지어낸 집계 줄로 `group_people` 과 견준다.
- 끝까지: 예시 묶음의 사본에서 점수를 묻는 판(`p4`, 사본에만 둔다)으로 기준 상황을 돌리고, 추정한 상수 파일을 써서 다시 돌린다.
  LLM 대신 테스트가 끼운 공급자(`tests.test_check_shares.Scoring`)가 점수를 나눈 답을 준다.
- 기본 데이터로 점수를 묻는 판을 돌릴 때 추정한 상수 파일이 없으면 멈추는 규칙은, 지어낸 집계 파일을 `private/base/` 자리에 베낀
  임시 사본에서 본다 (저장소의 `private/` 는 읽지 않는다).
"""

import json
import math
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from engine.calibration import calibrate
from engine.estimate import MIN_CONSTANT, NotFitted, ScoredVisit, estimate, fit, scored_visits, simulate
from engine.formats import LedgerRow, Persona, read_model
from engine.formats.constants import ConstantsFile
from engine.formats.run import SEASON_GAP_REASON
from engine.runner import _with_estimated, load_inputs, run
from engine.shares import VENUE_CONSTANT_PREFIX, ShareParams
from engine.weights import average_parties, estimated_constants_path, group_people, group_venue_people
from tests.conftest import EXAMPLE_ROOT, load_csv, load_json, save_csv, save_json
from tests.test_check_shares import Scoring
from tests.test_engine import DINNER, LUNCH, MODEL, NOW, PROVIDER, Played
from tests.test_llm import Fake
from tests.test_weights import BUNDLE, GROUP, VENUES, line, rows_of

WALKERHILL = {"a", "b", "c"}
COMPETITOR = "x"
ESTIMATED_SAMPLE = "data/samples/base_estimated_constants.json"  # docs 와 모듈 설명이 정한 자리
ELDERS = "family-elders"
PROMPT = "p4"  # 점수를 묻는 판 (SINGLE_ANSWER_PROMPTS 밖)


# ── 도우미 ──────────────────────────────────────────────────────────────


def visit(group: str, people: float, **places: int) -> ScoredVisit:
    """점수를 받은 방문 하나 (파는 달의 몫은 모두 1). `none` 은 "이용하지 않음"의 점수다."""
    found: dict[str | None, tuple[int, float]] = {}
    for place, score in places.items():
        found[None if place == "none" else place] = (score, 1.0)
    return ScoredVisit(group=group, people=people, places=found)


# 두 고객군. AI 는 a 를 많이 고르고 b 는 적게 고른다 (지어낸 점수).
VISITS = [
    visit("첫째", 100, a=50, b=10, x=30, none=10),
    visit("첫째", 60, a=40, b=20, c=20, x=10, none=10),
    visit("둘째", 80, a=30, c=40, x=20, none=10),
]
# 고객군마다 워커힐 업장의 실제 인원 (지어낸 값). d 는 실제 몫은 있는데 점수를 받은 방문이 없다.
TARGET = {"첫째": {"a": 300.0, "b": 500.0, "c": 200.0, "d": 50.0}, "둘째": {"a": 100.0, "c": 300.0}}


def pooled(by_group: dict[str, dict[str, float]], groups: list[str], venues: list[str]) -> dict[str, float]:
    """고객군들을 사람 수로 더한 업장 몫 (테스트가 따로 낸다)."""
    summed = {v: sum(by_group.get(g, {}).get(v, 0.0) for g in groups) for v in venues}
    total = sum(summed.values())
    return {v: summed[v] / total for v in venues}


def ledger_row(
    persona_id: str,
    condition_id: str,
    kind: str,
    venue_id: str | None,
    score: int | None,
    *,
    counted: float = 1.0,
    share: float = 1.0,
    season_gap_of: str | None = None,
    reason_text: str | None = None,
    represented: float = 12.5,
    request_hash: str | None = "0123456789abcdef",
    group: str = GROUP,
) -> LedgerRow:
    """원장의 한 줄 (지어낸 값). 금액은 모두 0 이라 몫 계산에만 쓴다."""
    return LedgerRow.model_validate(
        {
            "run_id": "20261120-090000-baseline",
            "scenario_id": "baseline",
            "visit_id": f"{persona_id}__{condition_id}",
            "persona_id": persona_id,
            "customer_group": group,
            "condition_id": condition_id,
            "choice_kind": kind,
            "venue_id": venue_id,
            "product_id": None if venue_id is None else "item",
            "quantity": 0,
            "unit": None,
            "list_price": 0,
            "discount": 0,
            "paid": 0,
            "revenue_net": 0,
            "represented": represented,
            "counted_share": counted,
            "choice_share": share,
            "score": score,
            "season_gap_of": season_gap_of,
            "weighted_revenue": 0,
            "reason_labels": [],
            "reason_text": reason_text,
            "used_attributes": [],
            "llm_call": None if request_hash is None else "new",
            "request_hash": request_hash,
            "status": "ok",
            "fail_reason": None,
        }
    )


def failed_row(persona_id: str, condition_id: str) -> LedgerRow:
    return LedgerRow.model_validate(
        ledger_row(persona_id, condition_id, "none", None, None).model_dump()
        | {"status": "failed", "fail_reason": "지어낸 실패", "llm_call": "new"}
    )


def personas() -> dict[str, Persona]:
    return {p.stem: read_model(p, Persona) for p in (EXAMPLE_ROOT / "personas").glob("*.json")}


def constant_entry(constant_id: str, value, in_use: bool = True) -> dict:
    return {
        "constant_id": constant_id,
        "name": f"지어낸 상수 {constant_id}",
        "value": value,
        "unit": None,
        "used_in": "tests/test_estimate.py",
        "grade": "assumption",
        "sources": [],
        "checked_on": "2026-11-20",
        "note": "테스트가 지어낸 값",
        "owner": "wilstein91",
        "in_use": in_use,
    }


def constants_file(*entries: dict) -> ConstantsFile:
    return ConstantsFile.model_validate({"format_version": 1, "constants": list(entries)})


def add_thebuffet_people(root: Path, people: int = 280) -> None:
    """예시의 집계 파일에 더뷔페의 주말 저녁 줄을 더한다 (지어낸 값). 그러면 맞출 업장이 금룡과 더뷔페 둘이 된다."""
    path = root / "data" / "samples" / "base_summary.csv"
    rows = load_csv(path)
    unit_net = round(180000 / 1.1)
    rows.append(
        dict(
            rows[0],
            venue_id="thebuffet",
            product_id="dinner-adult",
            meal="dinner",
            day_type="weekend",
            quantity=str(people),
            people=str(people),
            paid=str(180000 * people),
            revenue_net=str(unit_net * people),
        )
    )
    save_csv(path, rows)


# 금룡 50, 더뷔페 20, 예시호텔 중식당 20, 이용하지 않음 10 (지어낸 점수).
PERCENTS: dict[str | None, int] = {"geumryong": 50, "thebuffet": 20, "examplehotel-chinese": 20, None: 10}


def only_elders_dinner(root: Path) -> None:
    """예시 사본을 어르신 가족 한 명과 주말 저녁 한 조건으로 줄인다. 상수 추정은 저장소의 페르소나와 조건을 모두 돌린 실행만 받는다."""
    (root / "personas" / "family-kids.json").unlink(missing_ok=True)
    path = root / "engine" / "conditions.json"
    bundle = load_json(path)
    bundle["conditions"] = [c for c in bundle["conditions"] if c["condition_id"] == DINNER]
    save_json(path, bundle)


def scored_run(root: Path, *, now=NOW, scenario_id: str = "baseline", weights_from: str | None = None, data_mode="sample", **more) -> Path:
    """점수를 묻는 판으로 금룡 어르신 가족의 주말 저녁을 돌린다. 기준이 아닌 상황은 `weights_from` 의 기준 실행을 따른다."""
    only_elders_dinner(root)
    prompts = root / "personas" / "prompts"
    if not (prompts / f"{PROMPT}.md").exists():
        shutil.copy(prompts / "p1.md", prompts / f"{PROMPT}.md")
    settings = dict(
        data_mode=data_mode,
        now=now,
        provider=PROVIDER,
        model=MODEL,
        prompt_version=PROMPT,
        answers=[],
        scenario_id=scenario_id,
        persona_ids=[ELDERS] if weights_from is None else None,
        condition_ids=[DINNER] if weights_from is None else None,
        weights_from=weights_from,
        engine_commit="0000000",
        llm=Scoring(PERCENTS),
        call_limit=10,
    )
    return run(root, **(settings | more))


def sample_estimated(root: Path) -> Path:
    """가상 예시의 추정한 상수 파일 자리 (엔진이 정한 것. 그 자리가 문서와 맞는지는 따로 본다)."""
    return estimated_constants_path(root, "sample")


def sample_estimated_file(root: Path) -> str:
    return sample_estimated(root).relative_to(root).as_posix()


def share_of(played: Played, venue_id: str | None) -> float:
    (row,) = [r for r in played.visit(ELDERS, DINNER) if r.venue_id == venue_id and r.season_gap_of is None]
    return row.choice_share


# ── 맞추기 (fit) ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("k", [1.0, 2.0])
def test_fit_makes_pooled_shares_equal_the_actual_shares(k):
    found = fit(VISITS, TARGET, k, WALKERHILL)
    after = pooled(simulate(VISITS, k, found.constants, WALKERHILL), found.groups, found.fitted)
    goal = pooled(TARGET, ["첫째", "둘째"], ["a", "b", "c"])
    assert after == pytest.approx(goal, abs=1e-6)
    assert found.target == pytest.approx(goal, abs=1e-12)


@pytest.mark.parametrize("k", [1.0, 2.0])
def test_fit_normalises_constants_to_a_target_weighted_geometric_mean_of_one(k):
    found = fit(VISITS, TARGET, k, WALKERHILL)
    log_mean = sum(found.target[v] * math.log(found.constants[v]) for v in found.fitted) / sum(found.target.values())
    assert log_mean == pytest.approx(0.0, abs=1e-5)


def test_fit_raises_the_constant_of_the_venue_the_ai_under_picks():
    found = fit(VISITS, TARGET, 1.0, WALKERHILL)
    before = pooled(simulate(VISITS, 1.0, {}, WALKERHILL), found.groups, found.fitted)
    # 지어낸 점수에서 AI 는 a 를 실제보다 많이, b 를 실제보다 적게 고른다.
    assert before["a"] > found.target["a"] and before["b"] < found.target["b"]
    assert found.constants["b"] > 1 > found.constants["a"]


def test_fit_leaves_competitors_and_none_without_a_constant():
    found = fit(VISITS, TARGET, 1.0, WALKERHILL)
    assert set(found.constants) == set(found.fitted) == {"a", "b", "c"}
    assert COMPETITOR not in found.constants and None not in found.constants


def test_fit_reports_a_venue_with_actual_people_but_no_scores_as_unscored():
    found = fit(VISITS, TARGET, 1.0, WALKERHILL | {"d"})
    assert found.unscored == ["d"]
    assert "d" not in found.constants and "d" not in found.target


def test_fit_floors_the_constant_of_a_venue_whose_actual_share_is_zero():
    target = {"첫째": {"a": 300.0, "b": 500.0, "c": 0.0}, "둘째": {"a": 100.0}}
    found = fit(VISITS, target, 1.0, WALKERHILL)
    assert found.zero_target == ["c"] and "c" not in found.fitted
    assert found.constants["c"] == pytest.approx(MIN_CONSTANT)
    assert found.constants["a"] > MIN_CONSTANT and found.constants["b"] > MIN_CONSTANT


def test_fit_pools_only_the_groups_in_the_summary():
    visits = [*VISITS, visit("셋째", 1000, a=90, none=10)]
    found = fit(visits, TARGET, 1.0, WALKERHILL)
    assert found.groups == ["둘째", "첫째"]
    assert found.constants == fit(VISITS, TARGET, 1.0, WALKERHILL).constants


def test_fit_stops_when_no_scored_group_is_in_the_summary():
    with pytest.raises(ValueError, match="customer_group"):
        fit([visit("셋째", 10, a=90, none=10)], TARGET, 1.0, WALKERHILL)


# ── 몫 내기 (simulate) ───────────────────────────────────────────────────


def test_simulate_counts_only_the_selling_months_of_a_seasonal_venue():
    seasonal = ScoredVisit(group="첫째", people=10, places={"a": (60, 0.25), "b": (40, 1.0)})
    assert simulate([seasonal], 1.0, {}, WALKERHILL) == {"첫째": pytest.approx({"a": 10 * 0.6 * 0.25, "b": 10 * 0.4})}


def test_simulate_skips_places_scored_zero():
    zero = ScoredVisit(group="첫째", people=10, places={"a": (75, 1.0), "c": (0, 1.0), None: (25, 1.0)})
    # 점수가 0 인 곳은 상수가 커도 몫을 받지 않고 나눗셈에도 들지 않는다.
    assert simulate([zero], 1.0, {"c": 100.0}, WALKERHILL) == {"첫째": pytest.approx({"a": 7.5})}


def test_simulate_weights_scores_by_the_constants_and_counts_only_walkerhill():
    one = visit("첫째", 10, a=40, x=40, none=20)
    # a 의 무게 40 × 2 = 80, 경쟁 업장 40, 이용하지 않음 20 → a 의 몫 80 / 140. 경쟁 업장의 몫은 세지 않는다.
    assert simulate([one], 1.0, {"a": 2.0}, WALKERHILL) == {"첫째": pytest.approx({"a": 10 * 80 / 140})}


def test_simulate_applies_a_given_competitor_constant_like_the_engine():
    """`engine.shares.places` 처럼 상수가 적힌 곳이면 경쟁 업장에도 곱한다 (추정은 경쟁 업장의 상수를 주지 않는다)."""
    one = visit("첫째", 10, a=40, x=40, none=20)
    assert simulate([one], 1.0, {COMPETITOR: 5.0}, WALKERHILL) == {"첫째": pytest.approx({"a": 10 * 40 / 260})}


def test_simulate_sharpens_scores_with_k():
    one = visit("첫째", 10, a=60, b=40)
    assert simulate([one], 2.0, {}, WALKERHILL) == {"첫째": pytest.approx({"a": 10 * 3600 / 5200, "b": 10 * 1600 / 5200})}


# ── 원장 읽기 (scored_visits) ────────────────────────────────────────────


def test_scored_visits_reads_places_and_people_from_the_ledger():
    rows = [
        ledger_row(ELDERS, DINNER, "walkerhill", "geumryong", 60, reason_text="고른 이유"),
        ledger_row(ELDERS, DINNER, "competitor", "examplehotel-chinese", 30),
        ledger_row(ELDERS, DINNER, "none", None, 10),
    ]
    (found,), skipped = scored_visits(rows, personas())
    assert skipped == 0
    assert found.group == GROUP
    assert found.people == 12.5 * 4  # 대표하는 수 × 일행 수 (어른 넷)
    assert found.places == {"geumryong": (60, 1.0), "examplehotel-chinese": (30, 1.0), None: (10, 1.0)}


def test_scored_visits_does_not_count_the_season_gap_row_as_none():
    rows = [
        ledger_row(ELDERS, DINNER, "walkerhill", "geumryong", 60, counted=0.25, share=0.6),
        ledger_row(ELDERS, DINNER, "none", None, 60, counted=0.75, share=0.6, season_gap_of="geumryong", reason_text=SEASON_GAP_REASON),
        ledger_row(ELDERS, DINNER, "competitor", "examplehotel-chinese", 30, share=0.3),
        ledger_row(ELDERS, DINNER, "none", None, 10, share=0.1),
    ]
    (found,), _ = scored_visits(rows, personas())
    assert found.places == {"geumryong": (60, 0.25), "examplehotel-chinese": (30, 1.0), None: (10, 1.0)}


def test_scored_visits_does_not_count_an_old_style_season_gap_row_as_none():
    """season_gap_of 가 없던 때의 '파는 달이 아님' 줄도 이용하지 않음으로 세지 않는다."""
    rows = [
        ledger_row(ELDERS, DINNER, "walkerhill", "geumryong", 100, counted=0.25),
        ledger_row(ELDERS, DINNER, "none", None, 100, counted=0.75, reason_text=SEASON_GAP_REASON),
    ]
    (found,), _ = scored_visits(rows, personas())
    assert found.places == {"geumryong": (100, 0.25)}


def test_scored_visits_counts_single_answer_visits_as_skipped_and_drops_failed_ones():
    rows = [
        ledger_row(ELDERS, DINNER, "walkerhill", "geumryong", 70),
        ledger_row(ELDERS, DINNER, "none", None, 30),
        # 점수가 없는 답(1단계 방식): 뺀 방문으로 센다.
        ledger_row("family-kids", DINNER, "walkerhill", "geumryong", None),
        # 실패한 방문과 후보가 없던 방문: 빼지만 세지 않는다.
        failed_row("family-kids", LUNCH),
        ledger_row(ELDERS, LUNCH, "none", None, None, request_hash=None, reason_text="후보 없음"),
    ]
    found, skipped = scored_visits(rows, personas())
    assert skipped == 1
    assert [v.places for v in found] == [{"geumryong": (70, 1.0), None: (30, 1.0)}]


def test_scored_visits_stops_on_a_persona_without_a_definition():
    rows = [ledger_row("nobody", DINNER, "walkerhill", "geumryong", 100)]
    with pytest.raises(ValueError, match="nobody"):
        scored_visits(rows, personas())


# ── 고객군마다 업장별 인원 (group_venue_people) ──────────────────────────


def test_group_venue_people_adds_up_to_group_people_on_the_example():
    inputs = load_inputs(EXAMPLE_ROOT, "sample")
    parties = average_parties(list(inputs.personas.values()))
    conditions = inputs.conditions.conditions
    by_venue = group_venue_people(inputs.summary, conditions, inputs.conditions.assumed_splits, inputs.venues, parties)
    totals = group_people(inputs.summary, conditions, inputs.conditions.assumed_splits, inputs.venues, parties)
    assert set(by_venue) == set(totals)
    for group, people in totals.items():
        assert sum(by_venue[group].values()) == pytest.approx(people.total())


def test_group_venue_people_counts_only_the_conditions_that_run():
    inputs = load_inputs(EXAMPLE_ROOT, "sample")
    dinner = [inputs.conditions.condition(DINNER)]
    parties = average_parties(list(inputs.personas.values()))
    by_venue = group_venue_people(inputs.summary, dinner, inputs.conditions.assumed_splits, inputs.venues, parties)
    # 끼니가 빈 주말 줄 480명의 반(240)과 주말 저녁 180명. 주중 줄은 들지 않는다.
    assert by_venue == {GROUP: {"geumryong": pytest.approx(240 + 180)}}


def test_group_venue_people_matches_group_people_with_takeout_and_unknown_groups():
    rows = rows_of(
        line("geumryong", "course-b", "dinner", "weekend", 10, 100),
        line("thebuffet", "dinner-adult", "dinner", "weekend", 7, 100),
        line("geumryong", "course-a", "dinner", "weekend", 3, 100, people=""),  # 추가 상품처럼 빈 칸 → 0 명
        line("thebuffet", "lunch-adult", None, "weekend", 6, 100, occasion="takeout", unit="개", people=""),
        line("thebuffet", "lunch-adult", None, "weekend", 2, 100, occasion="takeout", unit="개", people="", group="다른 고객군"),
        line("examplehotel-chinese", "course", "dinner", "weekend", 50, 100),  # 경쟁 업장은 세지 않는다
    )
    parties = {GROUP: 3.0, "셋째": 5.0}
    by_venue = group_venue_people(rows, BUNDLE.conditions, BUNDLE.assumed_splits, VENUES, parties)
    totals = group_people(rows, BUNDLE.conditions, BUNDLE.assumed_splits, VENUES, parties)
    assert {g: sum(v.values()) for g, v in by_venue.items()} == pytest.approx({g: p.total() for g, p in totals.items()})
    assert by_venue[GROUP] == pytest.approx({"geumryong": 10, "thebuffet": 7 + 6 * 3.0})
    assert by_venue["다른 고객군"] == pytest.approx({"thebuffet": 2 * 4.0})


def test_estimated_constants_path_sits_next_to_the_summary(tmp_path):
    assert estimated_constants_path(tmp_path, "sample") == tmp_path / ESTIMATED_SAMPLE
    assert estimated_constants_path(tmp_path, "private") == tmp_path / "private" / "base" / "estimated_constants.json"


# ── 추정한 상수 파일을 읽기 (_with_estimated, load_inputs) ───────────────


SHARES = ShareParams(k=1.0, venue_constants={"thebuffet": 1.5})


def test_estimated_constants_are_added_to_the_venue_constants():
    found = _with_estimated(SHARES, constants_file(constant_entry(f"{VENUE_CONSTANT_PREFIX}geumryong", 0.8)), Path("f.json"))
    assert found == ShareParams(k=1.0, venue_constants={"thebuffet": 1.5, "geumryong": 0.8})


def test_estimated_file_refuses_a_constant_that_is_not_a_venue_constant():
    with pytest.raises(ValueError, match="share-sharpness-k"):
        _with_estimated(SHARES, constants_file(constant_entry("share-sharpness-k", 2.0)), Path("f.json"))


def test_estimated_file_refuses_a_venue_constant_also_in_engine_constants():
    with pytest.raises(ValueError, match="engine/constants.json"):
        _with_estimated(SHARES, constants_file(constant_entry(f"{VENUE_CONSTANT_PREFIX}thebuffet", 2.0)), Path("f.json"))


@pytest.mark.parametrize("value", [0, -1.0, True])
def test_estimated_file_refuses_a_constant_that_is_not_a_positive_number(value):
    with pytest.raises(ValueError, match="0 보다 큰 수"):
        _with_estimated(SHARES, constants_file(constant_entry(f"{VENUE_CONSTANT_PREFIX}geumryong", value)), Path("f.json"))


def test_estimated_file_ignores_constants_not_in_use():
    estimated = constants_file(constant_entry(f"{VENUE_CONSTANT_PREFIX}thebuffet", 2.0, in_use=False))
    assert _with_estimated(SHARES, estimated, Path("f.json")) == SHARES


def test_load_inputs_hashes_the_estimated_file_only_when_it_exists(example_copy):
    without = load_inputs(example_copy, "sample")
    assert "estimated" not in without.hashes and without.estimated is None and without.estimated_file is None

    save_json(sample_estimated(example_copy), constants_file(constant_entry(f"{VENUE_CONSTANT_PREFIX}geumryong", 0.8)).model_dump(mode="json"))
    found = load_inputs(example_copy, "sample")
    assert "estimated" in found.hashes
    assert found.estimated_file == sample_estimated_file(example_copy)
    assert found.shares.venue_constants["geumryong"] == 0.8


def test_load_inputs_stops_on_a_bad_estimated_file(example_copy):
    save_json(sample_estimated(example_copy), constants_file(constant_entry("share-sharpness-k", 2.0)).model_dump(mode="json"))
    with pytest.raises(ValueError, match="업장 상수"):
        load_inputs(example_copy, "sample")


# ── 끝까지: 기준 실행 → 추정 → 다시 돌린 기준 실행 ───────────────────────


def test_estimate_writes_the_estimated_constants_file(example_copy):
    add_thebuffet_people(example_copy)
    first = Played(example_copy, scored_run(example_copy), {})
    assert first.record.share_method == "scores"

    path, found, record, shown = estimate(example_copy, "sample", first.record.run_id)
    assert path == sample_estimated(example_copy)
    written = read_model(path, ConstantsFile)
    assert {c.constant_id for c in written.constants} == {f"{VENUE_CONSTANT_PREFIX}geumryong", f"{VENUE_CONSTANT_PREFIX}thebuffet"}
    assert {c.grade for c in written.constants} == {"assumption"}
    assert record.run_id == first.record.run_id
    # 실제 몫(금룡 420 : 더뷔페 280)보다 AI 가 금룡을 많이 고르므로 더뷔페의 상수가 1 보다 크다.
    assert found.target == pytest.approx({"geumryong": 0.6, "thebuffet": 0.4})
    assert found.constants["thebuffet"] > 1 > found.constants["geumryong"]
    assert shown[GROUP]["after"] == pytest.approx({"geumryong": 0.6, "thebuffet": 0.4}, abs=1e-6)


def test_baseline_after_estimate_uses_and_records_the_estimated_constants(example_copy):
    add_thebuffet_people(example_copy)
    first = Played(example_copy, scored_run(example_copy), {})
    estimate(example_copy, "sample", first.record.run_id)
    values = {c.constant_id.removeprefix(VENUE_CONSTANT_PREFIX): c.value for c in read_model(sample_estimated(example_copy), ConstantsFile).constants}

    second = Played(example_copy, scored_run(example_copy, now=NOW + timedelta(hours=1)), {})
    record = load_json(second.run_dir / "run.json")
    assert "estimated" in record["inputs"] and "estimated" not in load_json(first.run_dir / "run.json")["inputs"]
    used = {c["constant_id"]: c for c in record["constants"] if c["constant_id"].startswith(VENUE_CONSTANT_PREFIX)}
    assert {c["file"] for c in used.values()} == {sample_estimated_file(example_copy)}
    assert {key.removeprefix(VENUE_CONSTANT_PREFIX): c["value"] for key, c in used.items()} == values

    weights = {
        "geumryong": 50 * values["geumryong"],
        "thebuffet": 20 * values["thebuffet"],
        "examplehotel-chinese": 20.0,
        None: 10.0,
    }
    total = sum(weights.values())
    for venue_id, weight in weights.items():
        assert share_of(second, venue_id) == pytest.approx(weight / total, abs=1e-4)
    assert share_of(first, "geumryong") == pytest.approx(0.5, abs=1e-4)


def test_scenario_against_a_baseline_from_before_the_estimate_is_refused(example_copy):
    add_thebuffet_people(example_copy)
    first = Played(example_copy, scored_run(example_copy), {})
    # 추정하기 전에는 같은 기준 실행으로 상황을 돌릴 수 있다.
    scored_run(example_copy, now=NOW + timedelta(minutes=30), scenario_id="competitor-chinese-discount", weights_from=first.record.run_id)

    estimate(example_copy, "sample", first.record.run_id)
    with pytest.raises(ValueError, match="estimated"):
        scored_run(example_copy, now=NOW + timedelta(hours=1), scenario_id="competitor-chinese-discount", weights_from=first.record.run_id)


def test_calibration_refuses_a_baseline_from_before_the_estimate(example_copy):
    add_thebuffet_people(example_copy)
    first = Played(example_copy, scored_run(example_copy), {})
    estimate(example_copy, "sample", first.record.run_id)
    with pytest.raises(ValueError, match="estimated"):
        calibrate(example_copy, "sample", first.record.run_id)


def test_estimate_refuses_a_run_without_scores(example_copy):
    run_dir = run(
        example_copy,
        data_mode="sample",
        now=NOW,
        provider=PROVIDER,
        model=MODEL,
        prompt_version="p1",
        answers=[],
        persona_ids=[ELDERS],
        condition_ids=[DINNER],
        engine_commit="0000000",
        llm=Fake(),
        call_limit=10,
    )
    assert load_json(run_dir / "run.json")["share_method"] == "single"
    with pytest.raises(ValueError, match="share_method"):
        estimate(example_copy, "sample", run_dir.name)
    assert not sample_estimated(example_copy).exists()


# ── 기본 데이터로 점수를 묻는 판: 추정한 상수 파일이 없으면 멈춘다 ──────


def to_private_layout(root: Path) -> None:
    """지어낸 집계 파일을 기본 데이터의 자리(임시 사본의 private/base/)에 베낀다."""
    target = root / "private" / "base" / "summary.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / "data" / "samples" / "base_summary.csv", target)


def private_scored_run(root: Path, **more) -> Path:
    return scored_run(root, data_mode="private", base_profile_confirmed_for=PROVIDER, **more)


def test_private_scored_run_without_the_estimated_file_stops(example_copy):
    to_private_layout(example_copy)
    with pytest.raises(ValueError, match="--before-estimate"):
        private_scored_run(example_copy)
    assert not (example_copy / "private" / "runs").exists()


def test_private_scored_run_before_estimate_runs_with_constants_of_one(example_copy):
    to_private_layout(example_copy)
    run_dir = private_scored_run(example_copy, before_estimate=True)
    record = load_json(run_dir / "run.json")
    assert record["status"] == "ok" and "estimated" not in record["inputs"]
    assert not any(c["constant_id"].startswith(VENUE_CONSTANT_PREFIX) for c in record["constants"])


def test_private_scored_run_with_the_estimated_file_runs(example_copy):
    to_private_layout(example_copy)
    estimated = constants_file(constant_entry(f"{VENUE_CONSTANT_PREFIX}geumryong", 0.8))
    save_json(example_copy / "private" / "base" / "estimated_constants.json", estimated.model_dump(mode="json"))
    record = load_json(private_scored_run(example_copy) / "run.json")
    assert "estimated" in record["inputs"]
    assert [c["file"] for c in record["constants"] if c["constant_id"].startswith(VENUE_CONSTANT_PREFIX)] == [
        "private/base/estimated_constants.json"
    ]


def test_private_single_answer_run_does_not_need_the_estimated_file(example_copy):
    to_private_layout(example_copy)
    run_dir = scored_run(
        example_copy, data_mode="private", base_profile_confirmed_for=PROVIDER, prompt_version="p1", llm=Fake()
    )
    assert json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["status"] == "ok"


# ── 독립 검토(11-20)가 찾은 것의 회귀 시험 ─────────────────────────────


def test_fit_ignores_scores_from_visits_that_represent_nobody():
    """대표하는 사람이 0 인 방문에서만 점수를 받은 업장은 맞추지 않는다 (상수가 한없이 커지던 것)."""
    visits = [*VISITS, visit("첫째", 0, d=80, none=20)]
    found = fit(visits, TARGET, 1.0, WALKERHILL | {"d"})
    assert "d" not in found.constants


def test_fit_stops_without_writing_when_the_shares_cannot_be_matched():
    """AI 가 거의 고르지 않는 업장의 실제 몫이 크면 맞출 수 없다. 그때는 값을 내지 않고 멈춘다."""
    visits = [visit("첫째", 100, a=99, c=1), visit("첫째", 100, a=100)]
    target = {"첫째": {"a": 1.0, "c": 99.0}}
    with pytest.raises(NotFitted, match="맞지 않는다"):
        fit(visits, target, 1.0, WALKERHILL)


def test_estimate_refuses_a_run_of_only_some_personas_or_conditions(example_copy):
    """시험으로 일부만 돌린 기준 실행으로 상수를 정하지 않는다."""
    add_thebuffet_people(example_copy)
    first = Played(example_copy, scored_run(example_copy), {})
    shutil.copy(EXAMPLE_ROOT / "personas" / "family-kids.json", example_copy / "personas" / "family-kids.json")
    with pytest.raises(ValueError, match="일부만"):
        estimate(example_copy, "sample", first.record.run_id)


def test_before_estimate_is_only_for_a_baseline_without_the_file(example_copy):
    only_elders_dinner(example_copy)
    save_json(sample_estimated(example_copy), constants_file(constant_entry(f"{VENUE_CONSTANT_PREFIX}geumryong", 0.8)).model_dump(mode="json"))
    with pytest.raises(ValueError, match="before-estimate"):
        scored_run(example_copy, before_estimate=True)
