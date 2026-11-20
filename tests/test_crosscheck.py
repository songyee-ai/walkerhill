"""다른 고객군에 써 보기와 단순 기준과 견주기 (T212, `engine/crosscheck.py`, docs/FORMATS.md 10.7절).

- 몫 내기(`shares`), 차이 재기(`gaps`), 공개 후기 세기(`review_counts`)는 손으로 지은 값과 임시 폴더의 후기 파일로 본다.
- 다른 고객군으로 추정(`held_out`)은 손으로 지은 방문으로 본다: 상수는 그 고객군을 뺀 나머지에서만 나온다.
- 결과 파일의 모양(`GroupCrossCheck`, `CrossCheck`)은 손으로 지은 묶음으로 본다.
- 끝까지: 예시 묶음의 사본에서 두 고객군(가족·친족, 지어낸 "직장·모임")에 페르소나를 하나씩 두고, 주말 저녁 한 조건만 남겨
  점수를 묻는 판(`p4`, 사본에만 둔다)으로 기준 상황을 돌린 뒤 잰다. LLM 대신 테스트가 끼운 공급자가 점수를 나눈 답을 준다.
- 형식 검사(`tools.check_formats`)가 점수를 받은 기준 실행이 아닌 곳의 `crosscheck.json` 을 잡는지 본다.
값은 모두 지어낸 것이다.
"""

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from engine.crosscheck import crosscheck, gaps, held_out, review_counts, shares
from engine.estimate import ScoredVisit, fit, simulate
from engine.formats import read_model
from engine.formats.evidence import REVIEW_COLUMNS
from engine.formats.run import CrossCheck, GroupCrossCheck
from engine.runner import run
from tests.conftest import BASELINE_RUN, COMPETITOR_RUN, load_csv, load_json, save_csv, save_json
from tests.test_check_shares import Scoring
from tests.test_engine import DINNER, LUNCH, MODEL, NOW, PROVIDER
from tests.test_llm import Fake
from tools.check_formats import check

WALKERHILL = {"a", "b", "c"}
ELDERS, KIDS = "family-elders", "family-kids"
FAMILY = "가족·친족"
WORK = "직장·모임"  # 사본의 값 목록에만 더하는 지어낸 고객군
PROMPT = "p4"  # 점수를 묻는 판 (SINGLE_ANSWER_PROMPTS 밖)
# 금룡 50, 더뷔페 20, 예시호텔 중식당 20, 이용하지 않음 10 (지어낸 점수). 두 고객군이 같은 점수를 받는다.
PERCENTS: dict[str | None, int] = {"geumryong": 50, "thebuffet": 20, "examplehotel-chinese": 20, None: 10}
# 고객군마다 주말 저녁의 실제 사람 수 (지어낸 값). 가족·친족의 금룡 420 은 예시 집계 파일의 것이다 (끼니가 빈 주말 줄 480 의 반 + 주말 저녁 180).
ACTUAL = {FAMILY: {"geumryong": 0.6, "thebuffet": 0.4}, WORK: {"geumryong": 0.25, "thebuffet": 0.75}}


# ── 도우미 ──────────────────────────────────────────────────────────────


def visit(group: str, people: float, **places: int) -> ScoredVisit:
    """점수를 받은 방문 하나 (파는 달의 몫은 모두 1). `none` 은 "이용하지 않음"의 점수다."""
    return ScoredVisit(group=group, people=people, places={(None if p == "none" else p): (s, 1.0) for p, s in places.items()})


def review(review_id: str, venue_id: str, group: str = "") -> dict[str, str]:
    """후기 라벨 한 줄 (지어낸 값). 적지 않은 칸은 비운다."""
    row = dict.fromkeys(REVIEW_COLUMNS, "")
    row.update(
        review_id=review_id,
        venue_id=venue_id,
        source_kind="map",
        posted_ym="2026-06",
        customer_group=group,
        occasion="meal",
        meal="dinner",
        would_return="yes",
        summary="테스트가 지어낸 후기",
        labeler="wilstein91",
        labeled_on="2026-11-20",
    )
    return row


def summary_line(base: dict[str, str], group: str, venue_id: str, product_id: str, people: int, unit_price: int) -> dict[str, str]:
    """집계 파일의 주말 저녁 줄 하나 (지어낸 값)."""
    return dict(
        base,
        customer_group=group,
        venue_id=venue_id,
        product_id=product_id,
        meal="dinner",
        day_type="weekend",
        quantity=str(people),
        people=str(people),
        paid=str(unit_price * people),
        revenue_net=str(round(unit_price / 1.1) * people),
    )


def two_groups(root: Path, *, work_people: bool = True, keep: tuple[str, ...] = (DINNER,)) -> None:
    """예시 사본을 두 고객군·조건 `keep` 으로 바꾼다.

    아이 동반 가족을 지어낸 고객군 "직장·모임"으로 옮기고 두 페르소나의 몫을 1 로 둔다 (고객군마다 페르소나가 하나).
    예시의 저장된 실행은 지금의 입력과 맞지 않아 지운다.
    """
    vocab_path = root / "data" / "evidence" / "vocab.json"
    vocab = load_json(vocab_path)
    vocab["customer_group"].append(WORK)
    save_json(vocab_path, vocab)
    for persona_id, group in ((ELDERS, FAMILY), (KIDS, WORK)):
        path = root / "personas" / f"{persona_id}.json"
        persona = load_json(path)
        persona["customer_group"] = group
        persona["share_in_group"]["value"] = 1.0
        save_json(path, persona)
    bundle_path = root / "engine" / "conditions.json"
    bundle = load_json(bundle_path)
    bundle["conditions"] = [c for c in bundle["conditions"] if c["condition_id"] in keep]
    save_json(bundle_path, bundle)

    summary_path = root / "data" / "samples" / "base_summary.csv"
    rows = load_csv(summary_path)
    base = rows[-1]
    rows.append(summary_line(base, FAMILY, "thebuffet", "dinner-adult", 280, 180000))
    if work_people:
        rows.append(summary_line(base, WORK, "geumryong", "course-b", 100, 200000))
        rows.append(summary_line(base, WORK, "thebuffet", "dinner-adult", 300, 180000))
    save_csv(summary_path, rows)

    # 공개 후기: 예시의 금룡 후기에 가족·친족이 둘 있다. 더뷔페에 가족·친족 둘, 직장·모임 하나를 더하고, 금룡에 직장·모임 셋을 더한다.
    reviews = root / "data" / "evidence" / "reviews"
    save_csv(
        reviews / "thebuffet.csv",
        [review("R-thebuffet-0001", "thebuffet", FAMILY), review("R-thebuffet-0002", "thebuffet", FAMILY), review("R-thebuffet-0003", "thebuffet", WORK)],
    )
    geumryong = load_csv(reviews / "geumryong.csv")
    geumryong += [review(f"R-geumryong-01{n:02d}", "geumryong", WORK) for n in range(3)]
    save_csv(reviews / "geumryong.csv", geumryong)

    shutil.rmtree(root / "engine" / "samples" / "runs")
    prompts = root / "personas" / "prompts"
    shutil.copy(prompts / "p1.md", prompts / f"{PROMPT}.md")


def baseline(root: Path, *, prompt: str = PROMPT, llm=None, persona_ids=None, condition_ids=None) -> Path:
    """기준 상황을 돌린다. 페르소나와 조건을 적지 않으면 모두 돌린다."""
    return run(
        root,
        data_mode="sample",
        now=NOW,
        provider=PROVIDER,
        model=MODEL,
        prompt_version=prompt,
        answers=[],
        persona_ids=persona_ids,
        condition_ids=condition_ids,
        engine_commit="0000000",
        llm=llm or Scoring(PERCENTS),
        call_limit=20,
    )


def errors(root: Path) -> list[str]:
    return [str(p) for p in check(root, strict=True)]


def group_entry(**more) -> dict:
    """고객군 하나의 견주기 (지어낸 값). 세 방법을 모두 잴 수 있다."""
    entry = {
        "actual": {"a": 0.6, "b": 0.4},
        "no_constants": {"a": 0.7, "b": 0.3},
        "held_out": {"a": 0.65, "b": 0.35},
        "simple": {"a": 0.5, "b": 0.5},
        "max_diff_pp": {"no_constants": 10.0, "held_out": 5.0, "simple": 10.0},
        "misplaced_pct": {"no_constants": 10.0, "held_out": 5.0, "simple": 10.0},
        "simple_reviews": 4,
        "held_out_note": None,
    }
    return entry | more


def crosscheck_data(run_id: str = "20261120-090000-baseline", **groups: dict) -> dict:
    return {"format_version": 1, "run_id": run_id, "k": 1.0, "base_profile_mode": "none", "venues": ["a", "b"], "groups": groups or {"첫째": group_entry(), "둘째": group_entry()}}


# ── 몫과 차이 (shares, gaps) ─────────────────────────────────────────────


def test_shares_divide_amounts_within_the_given_venues():
    # c 는 venues 밖이라 나누는 데 들지 않고, d 는 양이 없어 0 이다.
    assert shares({"a": 30.0, "b": 10.0, "c": 60.0}, ["a", "b", "d"]) == pytest.approx({"a": 0.75, "b": 0.25, "d": 0.0})


def test_shares_are_all_zero_when_nothing_is_in_the_venues():
    assert shares({"c": 5.0}, ["a", "b"]) == {"a": 0.0, "b": 0.0}


def test_gaps_give_the_largest_difference_in_points():
    predicted = {"a": 0.5, "b": 0.3, "c": 0.2}
    actual = {"a": 0.6, "b": 0.1, "c": 0.3}
    assert gaps(predicted, actual)[0] == pytest.approx(20.0)


def test_gaps_give_half_the_summed_differences_as_misplaced_percent():
    # 차이 10, 20, 10 → 합 40 의 반 = 손님 20% 를 옮기면 같아진다.
    predicted = {"a": 0.5, "b": 0.3, "c": 0.2}
    actual = {"a": 0.6, "b": 0.1, "c": 0.3}
    assert gaps(predicted, actual)[1] == pytest.approx(20.0)


def test_gaps_count_a_venue_missing_on_one_side_as_zero():
    assert gaps({"a": 1.0}, {"a": 0.25, "b": 0.75}) == pytest.approx((75.0, 75.0))


def test_gaps_round_to_two_decimals():
    assert gaps({"a": 0.123456, "b": 0.876544}, {"a": 0.1, "b": 0.9}) == (2.35, 2.35)


# ── 공개 후기 세기 (review_counts) ───────────────────────────────────────


def test_review_counts_count_walkerhill_reviews_per_group(tmp_path):
    folder = tmp_path / "data" / "evidence" / "reviews"
    save_csv(folder / "a.csv", [review("R-a-0001", "a", "첫째"), review("R-a-0002", "a", "첫째"), review("R-a-0003", "a", "둘째")])
    save_csv(folder / "b.csv", [review("R-b-0001", "b", "첫째")])
    assert review_counts(tmp_path, {"a", "b"}) == {"첫째": {"a": 2, "b": 1}, "둘째": {"a": 1}}


def test_review_counts_skip_reviews_without_a_group(tmp_path):
    folder = tmp_path / "data" / "evidence" / "reviews"
    save_csv(folder / "a.csv", [review("R-a-0001", "a", "첫째"), review("R-a-0002", "a", ""), review("R-a-0003", "a", "  ")])
    assert review_counts(tmp_path, {"a"}) == {"첫째": {"a": 1}}


def test_review_counts_skip_competitor_venues(tmp_path):
    folder = tmp_path / "data" / "evidence" / "reviews"
    save_csv(folder / "a.csv", [review("R-a-0001", "a", "첫째")])
    save_csv(folder / "x.csv", [review("R-x-0001", "x", "첫째"), review("R-x-0002", "x", "둘째")])
    assert review_counts(tmp_path, {"a"}) == {"첫째": {"a": 1}}


def test_review_counts_are_empty_without_a_review_folder(tmp_path):
    assert review_counts(tmp_path, {"a"}) == {}


# ── 다른 고객군으로 추정 (held_out) ──────────────────────────────────────

# 세 고객군. 점수는 같은 꼴이라 상수가 고객군마다 다른 몫을 낸다 (지어낸 값).
VISITS = [
    visit("첫째", 100, a=50, b=30, none=20),
    visit("둘째", 80, a=40, b=40, c=10, none=10),
    visit("셋째", 60, a=60, c=30, none=10),
]
TARGET = {"첫째": {"a": 300.0, "b": 100.0}, "둘째": {"a": 100.0, "b": 200.0, "c": 50.0}, "셋째": {"a": 120.0, "c": 80.0}}


def test_held_out_applies_constants_fitted_on_the_other_groups():
    people, why = held_out(VISITS, TARGET, "첫째", 1.0, WALKERHILL, {})
    found = fit(VISITS[1:], {g: t for g, t in TARGET.items() if g != "첫째"}, 1.0, WALKERHILL, {})
    assert why is None
    assert people == pytest.approx(simulate(VISITS[:1], 1.0, found.constants, WALKERHILL)["첫째"])


def test_held_out_prediction_does_not_depend_on_the_held_out_groups_target():
    before, _ = held_out(VISITS, TARGET, "첫째", 1.0, WALKERHILL, {})
    changed = dict(TARGET, 첫째={"a": 1.0, "b": 999.0})
    after, _ = held_out(VISITS, changed, "첫째", 1.0, WALKERHILL, {})
    assert after == pytest.approx(before)


def test_held_out_prediction_changes_with_the_other_groups_targets():
    before, _ = held_out(VISITS, TARGET, "첫째", 1.0, WALKERHILL, {})
    changed = dict(TARGET, 둘째={"a": 10.0, "b": 900.0, "c": 50.0})
    after, _ = held_out(VISITS, changed, "첫째", 1.0, WALKERHILL, {})
    assert after["b"] > before["b"]


def test_held_out_keeps_the_fixed_constants():
    fixed = {"b": 3.0}
    people, _ = held_out(VISITS, TARGET, "첫째", 1.0, WALKERHILL, fixed)
    found = fit(VISITS[1:], {g: t for g, t in TARGET.items() if g != "첫째"}, 1.0, WALKERHILL, fixed)
    assert "b" not in found.constants
    assert people == pytest.approx(simulate(VISITS[:1], 1.0, {**fixed, **found.constants}, WALKERHILL)["첫째"])


def test_held_out_gives_a_reason_when_no_other_group_has_scores():
    people, why = held_out(VISITS[:1], TARGET, "첫째", 1.0, WALKERHILL, {})
    assert people is None
    assert why and "customer_group" in why


def test_held_out_gives_a_reason_when_the_other_groups_cannot_be_fitted():
    # 둘째의 실제 몫은 d 에만 있는데 d 는 점수를 받지 않아 맞출 업장이 없다.
    visits = [visit("첫째", 100, a=50, none=50), visit("둘째", 100, a=50, none=50)]
    people, why = held_out(visits, {"첫째": {"a": 1.0}, "둘째": {"d": 1.0}}, "첫째", 1.0, WALKERHILL | {"d"}, {})
    assert people is None
    assert why and why.startswith("나머지 고객군으로 상수를 추정하지 못했다")


# ── 결과 파일의 모양 (GroupCrossCheck, CrossCheck) ───────────────────────


def test_group_crosscheck_accepts_a_full_entry():
    GroupCrossCheck.model_validate(group_entry())


def test_group_crosscheck_accepts_held_out_and_simple_left_out_with_a_reason():
    GroupCrossCheck.model_validate(
        group_entry(
            held_out=None,
            simple=None,
            simple_reviews=0,
            held_out_note="나머지 고객군으로 상수를 추정하지 못했다: 지어낸 까닭",
            max_diff_pp={"no_constants": 10.0, "held_out": None, "simple": None},
            misplaced_pct={"no_constants": 10.0, "held_out": None, "simple": None},
        )
    )


@pytest.mark.parametrize("name", ["max_diff_pp", "misplaced_pct"])
def test_group_crosscheck_needs_all_three_methods(name):
    with pytest.raises(ValidationError, match="세 방법"):
        GroupCrossCheck.model_validate(group_entry(**{name: {"no_constants": 1.0, "held_out": 1.0}}))


@pytest.mark.parametrize("name", ["max_diff_pp", "misplaced_pct"])
def test_group_crosscheck_refuses_a_metric_for_a_method_left_out(name):
    # 다른 잣대는 바르게 비우고, `name` 에만 held_out 의 값을 남긴다.
    left_out = {"no_constants": 1.0, "held_out": None, "simple": 1.0}
    other = "misplaced_pct" if name == "max_diff_pp" else "max_diff_pp"
    with pytest.raises(ValidationError, match=f"{name}.held_out"):
        GroupCrossCheck.model_validate(group_entry(held_out=None, held_out_note="까닭", **{other: left_out}))


@pytest.mark.parametrize("name", ["max_diff_pp", "misplaced_pct"])
def test_group_crosscheck_refuses_a_missing_metric_for_a_method_given(name):
    metrics = {"no_constants": 1.0, "held_out": 1.0, "simple": None}
    with pytest.raises(ValidationError, match=f"{name}.simple"):
        GroupCrossCheck.model_validate(group_entry(**{name: metrics}))


def test_group_crosscheck_needs_a_reason_when_held_out_is_left_out():
    metrics = {"no_constants": 1.0, "held_out": None, "simple": 1.0}
    with pytest.raises(ValidationError, match="held_out_note"):
        GroupCrossCheck.model_validate(group_entry(held_out=None, max_diff_pp=metrics, misplaced_pct=metrics))


def test_group_crosscheck_refuses_a_reason_when_held_out_is_given():
    with pytest.raises(ValidationError, match="held_out_note"):
        GroupCrossCheck.model_validate(group_entry(held_out_note="적으면 안 되는 까닭"))


def test_group_crosscheck_refuses_simple_without_reviews():
    with pytest.raises(ValidationError, match="공개 후기"):
        GroupCrossCheck.model_validate(group_entry(simple_reviews=0))


def test_group_crosscheck_refuses_reviews_without_simple():
    metrics = {"no_constants": 1.0, "held_out": 1.0, "simple": None}
    with pytest.raises(ValidationError, match="공개 후기"):
        GroupCrossCheck.model_validate(group_entry(simple=None, max_diff_pp=metrics, misplaced_pct=metrics))


def test_group_crosscheck_refuses_negative_reviews():
    with pytest.raises(ValidationError):
        GroupCrossCheck.model_validate(group_entry(simple_reviews=-1))


def test_crosscheck_accepts_two_groups():
    found = CrossCheck.model_validate(crosscheck_data())
    assert set(found.groups) == {"첫째", "둘째"}


def test_crosscheck_needs_at_least_two_groups():
    with pytest.raises(ValidationError):
        CrossCheck.model_validate(crosscheck_data(첫째=group_entry()))


@pytest.mark.parametrize("name", ["actual", "no_constants", "held_out", "simple"])
def test_crosscheck_refuses_shares_whose_venues_differ_from_venues(name):
    groups = {"첫째": group_entry(**{name: {"a": 0.5, "c": 0.5}}), "둘째": group_entry()}
    with pytest.raises(ValidationError, match=f"'첫째' 의 {name}"):
        CrossCheck.model_validate(crosscheck_data(**groups))


def test_crosscheck_refuses_a_k_that_is_not_positive():
    with pytest.raises(ValidationError):
        CrossCheck.model_validate(crosscheck_data() | {"k": 0})


def test_held_out_better_than_simple_counts_groups_measured_both_ways():
    left_out = {"no_constants": 1.0, "held_out": 1.0, "simple": None}
    groups = {
        "첫째": group_entry(misplaced_pct={"no_constants": 9.0, "held_out": 2.0, "simple": 8.0}),  # 나았다
        "둘째": group_entry(misplaced_pct={"no_constants": 9.0, "held_out": 8.0, "simple": 8.0}),  # 같으면 낫지 않다
        "셋째": group_entry(simple=None, simple_reviews=0, max_diff_pp=left_out, misplaced_pct=left_out),  # 견줄 수 없다
    }
    assert CrossCheck.model_validate(crosscheck_data(**groups)).held_out_better_than_simple() == (1, 2)


# ── 끝까지: 두 고객군의 기준 실행 → 견주기 ──────────────────────────────


@pytest.fixture
def measured(example_copy: Path) -> tuple[Path, Path, CrossCheck]:
    two_groups(example_copy)
    run_dir = baseline(example_copy)
    assert load_json(run_dir / "run.json")["share_method"] == "scores"
    path, found = crosscheck(example_copy, "sample", run_dir.name)
    return example_copy, run_dir, found


def test_crosscheck_writes_the_file_in_the_run_folder(measured):
    root, run_dir, found = measured
    assert (run_dir / "crosscheck.json").is_file()
    assert read_model(run_dir / "crosscheck.json", CrossCheck) == found
    assert found.run_id == run_dir.name


def test_crosscheck_file_passes_the_format_check(measured):
    root, _, _ = measured
    assert errors(root) == []


def test_crosscheck_measures_both_groups_on_the_venues_with_actual_people(measured):
    _, _, found = measured
    assert set(found.groups) == {FAMILY, WORK}
    assert found.venues == ["geumryong", "thebuffet"]


def test_crosscheck_actual_shares_come_from_the_summary(measured):
    _, _, found = measured
    for group, actual in ACTUAL.items():
        assert found.groups[group].actual == pytest.approx(actual, abs=1e-4)


def test_crosscheck_no_constants_shares_are_the_ai_scores(measured):
    _, _, found = measured
    # 업장 상수가 없으면 금룡 50 : 더뷔페 20 (예시호텔 중식당과 이용하지 않음은 워커힐 업장이 아니라 빠진다).
    for entry in found.groups.values():
        assert entry.no_constants == pytest.approx({"geumryong": 50 / 70, "thebuffet": 20 / 70}, abs=1e-4)


def test_crosscheck_held_out_shares_come_from_the_other_group(measured):
    """두 고객군이 같은 점수를 받으므로, 다른 고객군에 맞춘 상수를 쓰면 그 고객군의 실제 몫이 나온다."""
    _, _, found = measured
    assert found.groups[FAMILY].held_out == pytest.approx(ACTUAL[WORK], abs=1e-4)
    assert found.groups[WORK].held_out == pytest.approx(ACTUAL[FAMILY], abs=1e-4)
    assert all(entry.held_out_note is None for entry in found.groups.values())


def test_crosscheck_simple_shares_are_review_counts(measured):
    _, _, found = measured
    # 가족·친족: 금룡 1, 더뷔페 2. 직장·모임: 금룡 3, 더뷔페 1. 고객군이 빈 예시 후기는 세지 않고,
    # 돌린 조건(주말 저녁)에 들지 않는 예시 후기(금룡 주말 점심)도 세지 않는다 (실제 몫과 같은 범위).
    assert found.groups[FAMILY].simple == pytest.approx({"geumryong": 1 / 3, "thebuffet": 2 / 3}, abs=1e-4)
    assert found.groups[FAMILY].simple_reviews == 3
    assert found.groups[WORK].simple == pytest.approx({"geumryong": 0.75, "thebuffet": 0.25})
    assert found.groups[WORK].simple_reviews == 4


def test_crosscheck_metrics_match_the_shares_in_the_file(measured):
    _, _, found = measured
    for entry in found.groups.values():
        for method in ("no_constants", "held_out", "simple"):
            predicted = getattr(entry, method)
            diffs = [abs(predicted[v] - entry.actual[v]) for v in found.venues]
            # 몫은 소수 넷째 자리로 적어 둔 것이라 0.02 까지 어긋날 수 있다.
            assert entry.max_diff_pp[method] == pytest.approx(100 * max(diffs), abs=0.02)
            assert entry.misplaced_pct[method] == pytest.approx(100 * sum(diffs) / 2, abs=0.02)


def test_crosscheck_counts_groups_where_held_out_beats_simple(measured):
    _, _, found = measured
    # 가족·친족: 다른 고객군으로 추정 35% 어긋남, 단순 기준 26.67%. 직장·모임: 35% 와 50%.
    assert found.groups[FAMILY].misplaced_pct == pytest.approx({"no_constants": 11.43, "held_out": 35.0, "simple": 26.67}, abs=0.01)
    assert found.groups[WORK].misplaced_pct == pytest.approx({"no_constants": 46.43, "held_out": 35.0, "simple": 50.0}, abs=0.01)
    assert found.held_out_better_than_simple() == (1, 2)


def test_crosscheck_again_overwrites_the_file(measured):
    root, run_dir, found = measured
    (run_dir / "crosscheck.json").write_text("{}", encoding="utf-8")
    _, again = crosscheck(root, "sample", run_dir.name)
    assert again == found
    assert read_model(run_dir / "crosscheck.json", CrossCheck) == found


def test_crosscheck_refuses_a_single_answer_run(example_copy):
    two_groups(example_copy)
    run_dir = baseline(example_copy, prompt="p1", llm=Fake(), persona_ids=[ELDERS])
    assert load_json(run_dir / "run.json")["share_method"] == "single"
    with pytest.raises(ValueError, match="share_method"):
        crosscheck(example_copy, "sample", run_dir.name)
    assert not (run_dir / "crosscheck.json").exists()


def test_crosscheck_refuses_a_run_of_only_some_personas(example_copy):
    two_groups(example_copy)
    run_dir = baseline(example_copy, persona_ids=[ELDERS])
    with pytest.raises(ValueError, match="일부만"):
        crosscheck(example_copy, "sample", run_dir.name)
    assert not (run_dir / "crosscheck.json").exists()


def test_crosscheck_refuses_a_run_of_only_some_conditions(example_copy):
    two_groups(example_copy, keep=(DINNER, LUNCH))
    run_dir = baseline(example_copy, condition_ids=[DINNER])
    with pytest.raises(ValueError, match="일부만"):
        crosscheck(example_copy, "sample", run_dir.name)
    assert not (run_dir / "crosscheck.json").exists()


def test_crosscheck_refuses_a_run_whose_inputs_changed(example_copy):
    two_groups(example_copy)
    run_dir = baseline(example_copy)
    rows = load_csv(example_copy / "data" / "samples" / "base_summary.csv")
    save_csv(example_copy / "data" / "samples" / "base_summary.csv", [*rows, dict(rows[-1], people="301", quantity="301")])
    with pytest.raises(ValueError, match="summary"):
        crosscheck(example_copy, "sample", run_dir.name)


def test_crosscheck_needs_two_groups_with_actual_people(example_copy):
    two_groups(example_copy, work_people=False)
    run_dir = baseline(example_copy)
    with pytest.raises(ValueError, match="둘보다 적어"):
        crosscheck(example_copy, "sample", run_dir.name)
    assert not (run_dir / "crosscheck.json").exists()


# ── 형식 검사: 점수를 받은 기준 실행에만 둔다 ─────────────────────────────


def place_crosscheck(root: Path, run_id: str) -> Path:
    """예시의 실행 폴더에 그 실행의 run_id 로 지은 crosscheck.json 을 둔다."""
    path = root / "engine" / "samples" / "runs" / run_id / "crosscheck.json"
    save_json(path, crosscheck_data(run_id))
    return path


def test_checker_passes_the_example_before_a_crosscheck_is_placed(example_copy):
    assert errors(example_copy) == []


@pytest.mark.parametrize("run_id", [BASELINE_RUN, COMPETITOR_RUN], ids=["single-answer-baseline", "scenario"])
def test_checker_reports_a_crosscheck_outside_a_scored_baseline(example_copy, run_id):
    place_crosscheck(example_copy, run_id)
    problems = errors(example_copy)
    assert any("crosscheck.json" in p and "점수를 받은 기준 실행에만" in p for p in problems), problems


def test_checker_reports_a_crosscheck_with_another_run_id(measured):
    root, run_dir, _ = measured
    data = load_json(run_dir / "crosscheck.json")
    save_json(run_dir / "crosscheck.json", data | {"run_id": "20261120-090000-baseline"})
    problems = errors(root)
    assert any("crosscheck.json" in p and "run_id 가 실행 기록과 다르다" in p for p in problems), problems


def test_checker_reports_a_crosscheck_that_breaks_the_model(measured):
    root, run_dir, _ = measured
    data = load_json(run_dir / "crosscheck.json")
    save_json(run_dir / "crosscheck.json", data | {"venues": ["geumryong"]})
    problems = errors(root)
    assert any("crosscheck.json" in p for p in problems), problems


def test_review_counts_keep_only_reviews_inside_the_run_conditions(tmp_path):
    """실제 몫과 같은 범위로 센다: 조식 후기와, 적힌 이용 상황·끼니·평일 주말이 돌린 조건에 들지 않는 후기는 뺀다. 빈 칸은 따지지 않는다."""
    from engine.formats.conditions import Condition

    folder = tmp_path / "data" / "evidence" / "reviews"
    folder.mkdir(parents=True)
    rows = [review("R-a-0001", "a", "첫째"), review("R-a-0002", "a", "첫째"), review("R-a-0003", "a", "첫째"), review("R-a-0004", "a", "첫째")]
    rows[1].update(meal="lunch")
    rows[2].update(meal="breakfast")
    rows[3].update(occasion="", meal="")
    save_csv(folder / "a.csv", rows)
    dinner = Condition.model_validate(
        {"condition_id": "c", "occasion": "meal", "meal": "dinner", "day_type": "weekend", "stay": None, "month": None}
    )
    assert review_counts(tmp_path, {"a"}, [dinner]) == {"첫째": {"a": 2}}
    assert review_counts(tmp_path, {"a"}) == {"첫째": {"a": 3}}


def test_metrics_of_a_prediction_with_no_share_count_everything_as_misplaced():
    """워커힐 업장에 아무 몫도 주지 않은 예측은 하나도 맞히지 못한 것이라 어긋난 몫이 100% 다."""
    assert gaps({"a": 0.0, "b": 0.0}, {"a": 0.6, "b": 0.4}) == (60.0, 100.0)
