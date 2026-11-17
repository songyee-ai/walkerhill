"""보정의 대조 (T116. docs/PRD.md 6.5절, docs/FORMATS.md 10.4절).

기준 실행의 원장에서 낸 업장별 가상 매출 비중을 집계 파일의 비중과 견줘 `calibration.json` 을 쓰는 것을 본다.
엔진은 정해 둔 답을 재생하고, 집계 파일은 테스트가 지어낸 값으로 쓴다.
"""

import shutil
from datetime import timedelta

import pytest

import engine.calibration as tool
from engine.calibration import DIFF_MIN_PERSONAS, MAX_DIFF_PP, calibrate, compare
from engine.formats import Calibration, read_model
from engine.formats.io import read_csv
from engine.formats.run import LEDGER_COLUMNS, LedgerRow
from engine.ledger import venue_shares
from engine.weights import group_revenue, group_venue_revenue
from tests.conftest import BASELINE_RUN, EXAMPLE_ROOT, load_json
from tests.test_engine import DINNER, LUNCH, NOW, answer, edit, first_option, persona_file, play
from tests.test_scenarios import PRICE_UP, play_scenario
from tests.test_weights import (
    BUNDLE,
    EIGHT,
    ELDERS,
    GROUP,
    KIDS,
    RUNS,
    VENUES,
    line,
    only,
    persona_like,
    private_run,
    rows_of,
    to_private,
    write_summary,
)
from tools.check_formats import check

OTHER = "커플·기념일"  # 집계 파일에는 있지만 페르소나가 없는 고객군 (지어낸 것)

# 지어낸 집계 값. 가족·친족은 주말 저녁에 금룡 1 : 더뷔페 3 으로 썼다. 다른 고객군의 매출은 이 고객군의 비중에 들지 않는다.
SUMMARY = (
    line("geumryong", "course-a", "dinner", "weekend", 100, 100000),
    line("thebuffet", "dinner-adult", "dinner", "weekend", 300, 100000),
    line("geumryong", "course-a", "dinner", "weekend", 500, 100000, group=OTHER),
    # 돌리지 않는 조건(주말 점심)의 매출. 들어가면 더뷔페의 비중이 0.75 가 아니게 된다.
    line("thebuffet", "lunch-adult", "lunch", "weekend", 1000, 100000),
)


def ready(root, *lines) -> None:
    """지어낸 집계 파일을 쓰고, 다른 집계 값으로 낸 예시 묶음의 실행을 뺀다. 값 목록에 둘째 고객군을 더한다."""
    write_summary(root, *(lines or SUMMARY))
    shutil.rmtree(root / RUNS)
    edit(root / "data" / "evidence" / "vocab.json", lambda d: d["customer_group"].append(OTHER))


def pick_by_persona(visit_id: str, request):
    """어르신 가족은 금룡, 아이 동반 가족은 더뷔페의 첫 주문을 고른다."""
    venue_id = "geumryong" if visit_id.startswith(ELDERS) else "thebuffet"
    return first_option(request, venue_id) if request.candidate(venue_id) else answer(request, None)


def both(root, pick=pick_by_persona, **more):
    return play(root, pick, persona_ids=(ELDERS, KIDS), condition_ids=(DINNER,), **more)


# ── 한 고객군의 대조 ────────────────────────────────────────────────────


def test_compare_gives_the_example_in_the_format_doc(doc):
    """가상 3 : 7, 기본 1 : 3 이면 문서의 예시(10.4절)와 같은 결과가 나온다."""
    found = compare({"geumryong": 30, "thebuffet": 70}, {"geumryong": 25, "thebuffet": 75}, ["geumryong", "thebuffet"])
    # 페르소나 수(`personas`)는 대조 명령이 저장소의 페르소나를 세어 붙인다. 한 고객군의 견줌에는 없다.
    assert found == {key: value for key, value in doc.calibration["groups"][GROUP].items() if key != "personas"}


def test_compare_needs_the_same_top_venue_and_small_differences():
    venues = ["a", "b", "c"]
    # 차이가 모두 15%p 이내이고 가장 큰 업장이 같으면 통과다. 딱 15%p 도 통과다.
    assert compare({"a": 40, "b": 60}, {"a": 25, "b": 75}, venues)["pass"] is True
    assert compare({"a": 40, "b": 60}, {"a": 25, "b": 75}, venues)["venues"]["a"]["diff_pp"] == MAX_DIFF_PP
    # 15%p 를 넘으면 미달이다.
    over = compare({"a": 41, "b": 59}, {"a": 25, "b": 75}, venues)
    assert (over["pass"], over["venues"]["a"]["diff_pp"], over["venues"]["b"]["diff_pp"]) == (False, 16.0, -16.0)
    # 차이가 작아도 가장 큰 업장이 다르면 미달이다.
    flipped = compare({"a": 51, "b": 49}, {"a": 49, "b": 51}, venues)
    assert (flipped["pass"], flipped["top_sim"], flipped["top_base"]) == (False, "a", "b")
    # 어느 쪽에도 없는 업장은 0 으로 적힌다. 한쪽에만 있는 업장도 빠지지 않는다.
    one_sided = compare({"a": 90, "c": 10}, {"a": 100}, venues)
    assert one_sided["venues"]["b"] == {"sim_share": 0.0, "base_share": 0.0, "diff_pp": 0.0}
    assert one_sided["venues"]["c"] == {"sim_share": 0.1, "base_share": 0.0, "diff_pp": 10.0}


def test_compare_decides_by_the_numbers_it_writes():
    """가장 큰 업장과 통과 여부는 파일에 적는 자릿수의 값으로 정한다. 적힌 값이 같은데 끝자리 차이로 갈리지 않는다."""
    venues = ["a", "b"]
    # 적힌 비중이 같으면(0.5 대 0.5) 두 쪽 모두 업장 정의의 차례에서 앞의 것이 가장 큰 업장이다.
    tie = compare({"a": 50, "b": 50}, {"a": 50, "b": 50.00001}, venues)
    assert (tie["top_sim"], tie["top_base"], tie["pass"]) == ("a", "a", True)
    assert tie["venues"]["b"] == {"sim_share": 0.5, "base_share": 0.5, "diff_pp": 0.0}
    # 차이가 0 으로 반올림될 때 −0.0 을 적지 않는다.
    close = compare({"a": 1, "b": 3}, {"a": 1, "b": 3.0000000001}, venues)
    assert [str(entry["diff_pp"]) for entry in close["venues"].values()] == ["0.0", "0.0"]


def test_compare_without_differences_needs_only_the_same_top_venue():
    """페르소나가 한 명인 고객군(11-17 에 고친 기준)은 차이를 적기만 하고 가장 큰 업장이 같은지만 본다."""
    venues = ["a", "b"]
    far = compare({"a": 100}, {"a": 60, "b": 40}, venues, check_diffs=False)
    assert (far["pass"], far["venues"]["a"]["diff_pp"], far["venues"]["b"]["diff_pp"]) == (True, 40.0, -40.0)
    assert compare({"a": 100}, {"a": 60, "b": 40}, venues)["pass"] is False  # 차이를 보면 미달이다
    flipped = compare({"b": 100}, {"a": 60, "b": 40}, venues, check_diffs=False)
    assert (flipped["top_sim"], flipped["top_base"], flipped["pass"]) == ("b", "a", False)
    assert compare({}, {"a": 1}, venues, check_diffs=False)["pass"] is False  # 견줄 수 없으면 여전히 미달이다


@pytest.mark.parametrize(("sim", "base"), [({}, {"a": 1}), ({"a": 1}, {}), ({"a": 0}, {"a": 1}), ({}, {})])
def test_compare_fails_when_one_side_has_no_revenue(sim, base):
    """가상 매출이나 기본 데이터의 매출이 없으면 견줄 수 없다. 비중은 0 으로 적고 통과가 아니다."""
    found = compare(sim, base, ["a", "b"])
    assert found["pass"] is False
    assert (found["top_sim"] is None) == (not sum(sim.values())) and (found["top_base"] is None) == (not sum(base.values()))
    assert all(0 <= entry[key] <= 1 for entry in found["venues"].values() for key in ("sim_share", "base_share"))


# ── 기본 데이터 쪽의 업장별 매출 ────────────────────────────────────────


@pytest.mark.parametrize("condition_ids", [EIGHT, [DINNER], [LUNCH, "meal-lunch-weekday"]])
def test_venue_revenue_adds_up_to_the_revenue_the_weights_are_fitted_to(condition_ids):
    """업장별 매출을 더하면 가중치를 맞춘 그 고객군의 매출과 같다. 조식과 돌리지 않는 조건은 두 쪽 모두 뺀다."""
    rows = rows_of(
        line("geumryong", "course-a", None, "weekday", 100, 136364),  # 끼니가 빈 줄: 점심과 저녁에 나눈다
        line("geumryong", "course-b", "dinner", "weekend", 50, 181818),
        line("thebuffet", "lunch-adult", "lunch", "weekend", 100, 145455),
        line("thebuffet", "lunch-adult", "breakfast", "weekend", 30, 50000),  # 조식은 어디에도 들지 않는다
        line("thebuffet", "dinner-adult", "dinner", "weekend", 10, 100000, group=OTHER),
        line("examplehotel-chinese", "course", "dinner", "weekend", 10, 100000),  # 경쟁 업장은 보지 않는다
    )
    conditions = [BUNDLE.condition(condition_id) for condition_id in condition_ids]
    venues = only("geumryong", "thebuffet", "examplehotel-chinese")
    by_venue = group_venue_revenue(rows, conditions, BUNDLE.assumed_splits, venues)
    totals = group_revenue(rows, conditions, BUNDLE.assumed_splits, venues)
    assert set(by_venue) == set(totals)
    for group, found in by_venue.items():
        assert sum(found.values()) == pytest.approx(totals[group].total())
        assert "examplehotel-chinese" not in found
    if condition_ids == [DINNER]:
        # 주말 저녁만 돌리면 금룡의 평일 줄과 더뷔페의 점심·조식 줄은 들지 않는다.
        assert by_venue == {GROUP: {"geumryong": 50 * 181818}, OTHER: {"thebuffet": 10 * 100000}}


def test_venue_revenue_reads_only_the_venues_given():
    rows = rows_of(line("geumryong", "course-a", "dinner", "weekend", 1, 100), line("thebuffet", "dinner-adult", "dinner", "weekend", 1, 300))
    conditions = [BUNDLE.condition(DINNER)]
    assert group_venue_revenue(rows, conditions, BUNDLE.assumed_splits, only("thebuffet")) == {GROUP: {"thebuffet": 300}}
    assert VENUES["geumryong"].is_competitor is False


# ── 기준 실행을 대조한다 ────────────────────────────────────────────────


def test_calibration_compares_the_ledger_with_the_summary(example_copy):
    """어르신 가족이 금룡, 아이 동반 가족이 더뷔페를 고른 기준 실행을 금룡 1 : 더뷔페 3 인 기본 데이터와 견준다."""
    ready(example_copy)
    played = both(example_copy)
    path, result, not_run = calibrate(example_copy, "sample")  # 적지 않으면 일 년 전체로 끝까지 돈 가장 새 기준 실행이다

    assert path == played.run_dir / "calibration.json"
    assert read_model(path, Calibration) == result
    assert result.run_id == played.run_dir.name
    assert not_run == {}  # 저장소의 페르소나를 모두 돌렸다
    assert result.criteria.model_dump() == {"top_venue_must_match": True, "max_diff_pp": 15, "diff_min_personas": 2}
    assert list(result.groups) == [GROUP]
    assert result.groups[GROUP].personas == 2  # 저장소의 가족·친족 페르소나는 둘이라 차이도 본다
    assert result.uncovered_groups == [OTHER]  # 집계 파일에 매출이 있는데 페르소나가 없다

    found = load_json(path)["groups"][GROUP]
    # 가상 매출: 두 페르소나의 몫이 반반이라 세금을 뺀 금액의 비로 나뉜다. 어르신 가족 4명 × 15만 원, 아이 동반 가족 2명 × 18만 원 + 2명 × 9만 원.
    elders, kids = 600000 / 1.1, 540000 / 1.1
    sim = elders / (elders + kids)
    assert found["venues"]["geumryong"] == {"sim_share": pytest.approx(sim, abs=1e-4), "base_share": 0.25, "diff_pp": pytest.approx((sim - 0.25) * 100, abs=0.01)}
    assert found["venues"]["thebuffet"]["base_share"] == 0.75
    assert found["venues"]["thebuffet"]["sim_share"] == pytest.approx(1 - sim, abs=1e-4)
    assert list(found["venues"]) == ["geumryong", "thebuffet"]  # 읽은 워커힐 업장 모두. 경쟁 업장은 없다
    # 가상은 금룡이 가장 크고 기본 데이터는 더뷔페가 가장 커서 미달이다. 차이도 15%p 를 넘는다.
    assert (found["top_sim"], found["top_base"], found["pass"]) == ("geumryong", "thebuffet", False)
    assert result.passed is False
    # 가상 쪽은 원장에서 낸 값 그대로다.
    rows = [LedgerRow.from_row(row) for row in read_csv(played.run_dir / "ledger.csv", LEDGER_COLUMNS)]
    assert found["venues"]["geumryong"]["sim_share"] == round(venue_shares(rows, GROUP)["walkerhill"]["geumryong"]["share"], 4)
    assert [str(problem) for problem in check(example_copy, strict=True)] == []

    # 같은 실행을 다시 대조하면 같은 파일을 다시 쓴다.
    before = path.read_bytes()
    assert calibrate(example_copy, "sample", played.run_dir.name)[1] == result and path.read_bytes() == before


def test_calibration_passes_when_the_shares_are_close(example_copy):
    """기본 데이터의 비중이 가상 매출의 비중과 가까우면 통과다."""
    ready(
        example_copy,
        line("geumryong", "course-a", "dinner", "weekend", 500, 100000),
        line("thebuffet", "dinner-adult", "dinner", "weekend", 500, 100000),
    )
    both(example_copy)
    _, result, _ = calibrate(example_copy, "sample")
    found = result.groups[GROUP]
    assert (found.top_sim, found.top_base, found.passed, result.passed) == ("geumryong", "geumryong", True, True)
    assert abs(found.venues["geumryong"].diff_pp) < MAX_DIFF_PP and result.uncovered_groups == []


def test_group_without_walkerhill_visits_or_without_base_revenue_does_not_pass(example_copy):
    """워커힐 업장을 고른 방문이 없는 고객군과, 집계 파일에 매출이 없는 고객군은 견줄 수 없어 미달이다."""
    ready(example_copy)
    both(example_copy, lambda visit_id, request: answer(request, None))
    _, result, _ = calibrate(example_copy, "sample")
    found = result.groups[GROUP]
    assert (found.top_sim, found.top_base, found.passed) == (None, "thebuffet", False)
    assert all(entry.sim_share == 0 for entry in found.venues.values())

    write_summary(example_copy, line("geumryong", "course-a", "dinner", "weekend", 500, 100000, group=OTHER))
    both(example_copy, now=NOW + timedelta(hours=1))
    _, result, _ = calibrate(example_copy, "sample")
    found = result.groups[GROUP]
    assert (found.top_sim, found.top_base, found.passed) == (None, None, False)  # 매출이 없어 고객군 배수도 0 이다
    assert result.uncovered_groups == [OTHER] and result.passed is False


def test_calibration_is_refused_for_runs_that_cannot_be_compared(example_copy):
    ready(example_copy)
    with pytest.raises(ValueError, match="대조할 기준 실행이 없다"):
        calibrate(example_copy, "sample")

    # 실패한 방문이 있는 실행: 그 방문이 빠진 채로 견주면 비중이 어긋난다.
    failed = both(example_copy, lambda visit_id, request: None if visit_id.startswith(KIDS) else first_option(request, "geumryong"))
    with pytest.raises(ValueError, match="실패한 방문이 1건 있어 대조하지 않는다"):
        calibrate(example_copy, "sample")
    assert not (failed.run_dir / "calibration.json").exists()

    # 달을 주고 돌린 실행: 그 달의 매출이 아니다. 적지 않고 고르면 일 년 전체로 돌린 실행만 본다.
    december = both(example_copy, now=NOW + timedelta(hours=1), month=12)
    with pytest.raises(ValueError, match="12월로 돌린 것이다"):
        calibrate(example_copy, "sample", december.run_dir.name)
    with pytest.raises(ValueError, match="실패한 방문이 1건"):
        calibrate(example_copy, "sample")  # 12월 실행을 건너뛰고 그 앞의 일 년 전체 실행을 고른다

    # 기준이 아닌 상황의 실행.
    base = both(example_copy, now=NOW + timedelta(hours=2))
    scenario = play_scenario(example_copy, PRICE_UP, pick_by_persona, base, now=NOW + timedelta(hours=3))
    with pytest.raises(ValueError, match="기준 상황의 실행이 아니다"):
        calibrate(example_copy, "sample", scenario.run_dir.name)
    with pytest.raises(ValueError, match="run_id 가 아니다"):
        calibrate(example_copy, "sample", "../outside")
    with pytest.raises(FileNotFoundError, match="실행 기록이 없다"):
        calibrate(example_copy, "sample", "20200101-000000-baseline")

    # 업장을 골라 돌린 실행: 비중의 분모가 워커힐 업장 전체가 아니다.
    subset = both(example_copy, now=NOW + timedelta(hours=4), venue_ids=["geumryong", "examplehotel-chinese"])
    with pytest.raises(ValueError, match="달라진 것이 있다: venues"):
        calibrate(example_copy, "sample", subset.run_dir.name)

    # 실행 뒤에 페르소나나 집계 파일을 고친 실행.
    assert calibrate(example_copy, "sample", base.run_dir.name)[1].run_id == base.run_dir.name
    edit(persona_file(example_copy, ELDERS), lambda d: d["share_in_group"].update(basis="고침"))
    with pytest.raises(ValueError, match="달라진 것이 있다: personas"):
        calibrate(example_copy, "sample", base.run_dir.name)


def test_calibration_of_the_fixture_run_is_refused_because_it_read_two_venues(example_copy):
    """예시 묶음의 기준 실행은 업장 두 곳만 읽어 돌린 것이다. 그 대조 결과 파일은 문서의 예시이고 이 도구가 쓴 것이 아니다."""
    example = (example_copy / RUNS / BASELINE_RUN / "calibration.json").read_bytes()
    with pytest.raises(ValueError, match="달라진 것이 있다: venues"):
        calibrate(example_copy, "sample", BASELINE_RUN)
    assert (example_copy / RUNS / BASELINE_RUN / "calibration.json").read_bytes() == example  # 멈출 때는 아무것도 쓰지 않는다
    assert example == (EXAMPLE_ROOT / RUNS / BASELINE_RUN / "calibration.json").read_bytes()


@pytest.mark.parametrize(
    ("path", "change", "changed"),
    [
        ("data/venues/thebuffet.json", lambda d: d.update(cuisine="뷔페 (고침)"), "venues"),
        ("engine/conditions.json", lambda d: d["assumed_splits"][0].update(note="고침"), "conditions"),
        ("scenarios/baseline.json", lambda d: d.update(note="고침"), "scenario"),
        ("data/evidence/vocab.json", lambda d: d["pain_points"].append("새 라벨"), "vocab"),
    ],
)
def test_calibration_is_refused_when_an_input_changed_after_the_run(example_copy, path, change, changed):
    """실행 뒤에 입력이 달라졌으면 원장과 지금의 입력이 서로 다른 것을 말하므로 대조하지 않는다."""
    ready(example_copy)
    played = both(example_copy)
    assert calibrate(example_copy, "sample")[1].run_id == played.run_dir.name  # 그대로면 대조한다
    edit(example_copy / path, change)
    with pytest.raises(ValueError, match=f"달라진 것이 있다: {changed}"):
        calibrate(example_copy, "sample")
    # 집계 파일을 고쳐도 같다.
    write_summary(example_copy, *SUMMARY[:2])
    with pytest.raises(ValueError, match="summary"):
        calibrate(example_copy, "sample")


def test_group_with_one_persona_is_judged_by_its_top_venue_only(example_copy, capsys):
    """페르소나가 한 명인 고객군은 업장별 차이가 15%p 를 넘어도 가장 큰 업장이 같으면 통과다 (PRD 6.5절, 11-17 에 고침)."""
    assert DIFF_MIN_PERSONAS == 2
    # 둘째 고객군은 더뷔페 6 : 금룡 4 로 썼다. 그 고객군의 한 명은 더뷔페만 골라 더뷔페 +40%p 가 된다.
    ready(
        example_copy,
        *SUMMARY[:2],
        line("thebuffet", "dinner-adult", "dinner", "weekend", 600, 100000, group=OTHER),
        line("geumryong", "course-a", "dinner", "weekend", 400, 100000, group=OTHER),
    )
    persona_like(example_copy, ELDERS, "couple", OTHER)
    played = play(example_copy, pick_by_persona, persona_ids=(ELDERS, KIDS, "couple"), condition_ids=(DINNER,))

    path, result, not_run = calibrate(example_copy, "sample")
    assert not_run == {}
    one = result.groups[OTHER]
    assert (one.personas, one.top_sim, one.top_base, one.venues["thebuffet"].diff_pp, one.passed) == (1, "thebuffet", "thebuffet", 40.0, True)
    # 페르소나가 둘인 고객군은 그대로 두 가지를 모두 본다.
    family = result.groups[GROUP]
    assert (family.personas, family.passed) == (2, False)
    assert result.passed is False and result.uncovered_groups == []
    assert [str(problem) for problem in check(example_copy, strict=True)] == []

    assert tool.main(["--data", "sample", "--root", str(example_copy), "--run", played.run_dir.name]) == tool.EXIT_OK
    said = capsys.readouterr().out
    assert "페르소나가 한 명인 고객군은 가장 큰 업장만" in said
    assert f"- {OTHER}: 통과 · 가장 큰 업장 가상 thebuffet / 기본 thebuffet · 가장 큰 차이 geumryong -40.00%p (페르소나 1명이라 차이는 보지 않음)" in said
    assert path.is_file()


def test_old_calibration_file_without_the_new_fields_still_reads():
    """11-17 의 첫 대조 결과처럼 새 칸이 없는 파일도 읽힌다. 모든 고객군의 차이를 본 것으로 둔다."""
    old = Calibration.model_validate(
        {
            "format_version": 1,
            "run_id": "20261117-101500-baseline",
            "criteria": {"top_venue_must_match": True, "max_diff_pp": 15},
            "groups": {GROUP: {"venues": {}, "top_sim": None, "top_base": None, "pass": False}},
            "uncovered_groups": [],
            "pass": False,
        }
    )
    assert old.criteria.diff_min_personas == 1 and old.groups[GROUP].personas is None


def test_group_with_a_persona_that_was_not_run_does_not_pass(example_copy, capsys):
    """보정은 페르소나를 모두 돌린 기준 실행으로 한다. 고객군의 페르소나 가운데 돌리지 않은 것이 있으면 비중이 맞아도 통과가 아니다."""
    ready(example_copy, line("geumryong", "course-a", "dinner", "weekend", 100, 100000), SUMMARY[2])
    persona_like(example_copy, ELDERS, "couple", OTHER)  # 둘째 고객군에도 페르소나가 있다. 이번 실행에서는 돌리지 않는다
    played = play(example_copy, pick_by_persona, persona_ids=(ELDERS,), condition_ids=(DINNER,))

    path, result, not_run = calibrate(example_copy, "sample")
    assert not_run == {GROUP: [KIDS], OTHER: ["couple"]}
    # 가족·친족: 돌린 한 명은 금룡만 골랐고 기본 데이터도 금룡뿐이라 비중은 같다. 그래도 한 명이 빠져 통과가 아니다.
    family = result.groups[GROUP]
    assert (family.top_sim, family.top_base, family.venues["geumryong"].diff_pp, family.passed) == ("geumryong", "geumryong", 0.0, False)
    # 둘째 고객군: 페르소나가 있으니 대조하는 고객군이다. 하나도 돌리지 않아 가상 매출이 없다. "다루지 않은 고객군"이 아니다.
    other = result.groups[OTHER]
    assert (other.top_sim, other.top_base, other.passed) == (None, "geumryong", False)
    assert result.uncovered_groups == [] and result.passed is False
    assert [str(problem) for problem in check(example_copy, strict=True)] == []

    assert tool.main(["--data", "sample", "--root", str(example_copy), "--run", played.run_dir.name]) == tool.EXIT_OK
    said = capsys.readouterr()
    assert f"돌리지 않은 것이 있어 통과로 보지 않는다: {KIDS}" in said.err and "돌리지 않은 것이 있어 통과로 보지 않는다: couple" in said.err
    assert "전체: 미달" in said.out and path.is_file()


def test_private_run_is_calibrated_inside_private(example_copy):
    """기본 데이터로 돌린 실행의 대조 결과는 `private/runs/` 에만 쓴다."""
    to_private(example_copy)
    run_dir = private_run(example_copy, base_profile_mode="none", base_profile_confirmed_for=None)
    path, result, not_run = calibrate(example_copy, "private")
    assert path == run_dir / "calibration.json" and (example_copy / "private" / "runs") in path.parents
    assert result.groups[GROUP].top_base == "geumryong"
    with pytest.raises(ValueError, match="대조할 기준 실행이 없다"):
        calibrate(example_copy.parent / "empty", "private")


# ── 명령 ────────────────────────────────────────────────────────────────


def test_command_writes_the_result_and_tells_it(example_copy, capsys):
    ready(example_copy)
    assert tool.main(["--data", "sample", "--root", str(example_copy)]) == tool.EXIT_FAILED
    assert "대조하지 못했다: 대조할 기준 실행이 없다" in capsys.readouterr().err

    played = both(example_copy)
    assert tool.main(["--data", "sample", "--root", str(example_copy), "--run", played.run_dir.name]) == tool.EXIT_OK
    said = capsys.readouterr().out
    assert f"대조 결과: {played.run_dir / 'calibration.json'}" in said
    assert "업장별 비중의 차이가 모두 15%p 이내" in said
    assert f"- {GROUP}: 미달 · 가장 큰 업장 가상 geumryong / 기본 thebuffet" in said
    assert f"다루지 않은 고객군 (페르소나가 없다): {OTHER}" in said and "전체: 미달" in said
    assert (played.run_dir / "calibration.json").is_file()
