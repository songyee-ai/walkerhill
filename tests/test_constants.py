"""결정 상수 (T210, docs/FORMATS.md 6.1절).

엔진의 숫자 가운데 결과에 영향을 주는 것은 `engine/constants.json` 에 값과 근거를 함께 적고, 엔진은 그 값을 쓴다.
실행 기록에는 그 실행이 쓴 상수를 값까지 남긴다.
"""

import json
from dataclasses import replace
from datetime import timedelta

import pytest

from engine import calibration, runner, weights
from engine import constants as constants_module
from engine.constants import (
    CONSTANTS_PATH,
    RunUse,
    applied,
    has_rule,
    load_constants,
    used_constants,
    values_hash,
)
from engine.formats import ConditionBundle, RunRecord, read_model
from engine.formats.constants import ConstantsFile
from engine.formats.summary import SummaryRow
from engine.shares import VENUE_CONSTANT_PREFIX
from engine.weights import blank_people_kinds, read_summary
from tests.conftest import BASELINE_RUN, EXAMPLE_ROOT, load_csv, load_json, save_csv, save_json
from tests.test_check_shares import play_scored
from tests.test_engine import DINNER, NOW, edit, pick_geumryong, play, product_of, venue_file
from tests.test_estimate import constant_entry, constants_file, sample_estimated
from tests.test_scenarios import PRICE_UP, run_scenario
from tools.check_formats import check

RUNS = EXAMPLE_ROOT / "engine" / "samples" / "runs"


def test_engine_uses_the_values_of_the_constants_file():
    """엔진의 숫자는 파일의 값이다. 파일을 고치면 엔진이 그 값으로 돈다."""
    found = load_constants()
    assert weights.FILLED_PRICE_UNIT == found.value("filled-price-unit")
    assert weights.TOP_PRODUCTS == found.value("base-profile-top-products")
    assert (weights.BUCKET_HIGH, weights.BUCKET_MID) == (found.value("base-profile-bucket-high"), found.value("base-profile-bucket-mid"))
    assert weights.TAKEOUT_TEAMS_PER_ITEM == found.value("takeout-teams-per-item")
    assert weights.ADD_ON_PEOPLE_PER_ITEM == found.value("add-on-people-per-item")
    assert calibration.MAX_DIFF_PP == found.value("calibration-max-diff-pp")
    assert calibration.DIFF_MIN_PERSONAS == found.value("calibration-diff-min-personas")
    assert calibration.TOP_VENUE_MUST_MATCH == found.value("calibration-top-venue-must-match")
    with pytest.raises(KeyError, match="engine/constants.json 에 없다"):
        found.value("no-such-constant")


def test_constants_file_refuses_duplicates():
    data = json.loads(CONSTANTS_PATH.read_text(encoding="utf-8"))
    data["constants"].append(data["constants"][0])
    with pytest.raises(ValueError, match="constant_id 가 겹친다"):
        ConstantsFile.model_validate(data)


def test_run_record_keeps_every_constant_with_its_value():
    """실행 기록에는 결정 상수 파일의 모두와 방문 조건 묶음의 나누는 비율이 값까지 남는다 (11-19 결정)."""
    record = read_model(RUNS / BASELINE_RUN / "run.json", RunRecord)
    bundle = read_model(EXAMPLE_ROOT / "engine" / "conditions.json", ConditionBundle)
    # 예시 기준 실행: 가상 예시 값, 요약을 보내지 않음, 채운 단가 없음, 점수가 없는 판(p1), 끼니가 빈 금룡 코스 A 의 주말 줄을 점심·저녁으로 나눔.
    use = RunUse(
        filled_prices=False,
        base_profile_mode="none",
        blank_people=frozenset(),
        splits=frozenset({"meal-lunch-dinner"}),
        scored=False,
        scored_venues=frozenset(),
        scores_asked=False,
        requests=True,
    )
    assert record.constants == used_constants(bundle, use=use)
    assert [c.applied for c in used_constants(bundle)] == [None] * len(record.constants)
    by_id = {c.constant_id: c for c in record.constants}
    assert by_id["filled-price-unit"].value == 100 and by_id["filled-price-unit"].file == "engine/constants.json"
    assert by_id["meal-lunch-dinner"].value == {"lunch": 0.5, "dinner": 0.5}
    assert by_id["meal-lunch-dinner"].file == "engine/conditions.json"
    assert "constants" in record.inputs


def test_scenario_is_refused_when_the_constants_changed_after_the_baseline_run(example_copy):
    """기준 실행 뒤에 결정 상수가 바뀌었으면 상황을 돌리지 않는다. 기준의 해시를 바꿔 같은 일을 만든다."""
    base = play(example_copy, pick_geumryong)
    record = load_json(base.run_dir / "run.json")
    record["inputs"]["constants"] = "0" * 16
    save_json(base.run_dir / "run.json", record)
    with pytest.raises(ValueError, match="달라진 것이 있다: constants"):
        run_scenario(example_copy, PRICE_UP, weights_from=base.run_dir.name, now=NOW + timedelta(hours=3))


def test_check_wants_a_source_for_values_from_public_material(example_copy):
    """공개 자료에서 가져온 값(학술 자료, 통계, 업계 보고서, 기사, 공식)은 그 종류의 출처 자료를 적어야 한다 (11-20 목록으로 바꿈, T214)."""
    target = example_copy / "engine" / "constants.json"
    data = json.loads(CONSTANTS_PATH.read_text(encoding="utf-8"))
    save_json(target, data)
    assert [str(p) for p in check(example_copy, strict=True)] == []
    data["constants"][0].update(grade="literature")
    save_json(target, data)
    problems = [str(p) for p in check(example_copy, strict=True)]
    assert any("등급이 literature 인데 sources 에 그 종류의 자료가 없다" in p for p in problems)
    # 다른 종류의 자료만 있어도 막는다: 기사만 있는데 학술 자료라고 적을 수 없다.
    data["constants"][0].update(sources=[{"title": "어느 기사 (2026-11-16 게재)", "kind": "article", "url": None}])
    save_json(target, data)
    assert any("등급이 literature 인데 sources 에 그 종류의 자료가 없다" in str(p) for p in check(example_copy, strict=True))
    data["constants"][0].update(sources=[
        {"title": "Andreyeva, Long & Brownell 2010, AJPH 100(2)", "kind": "literature", "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC2804646"},
        {"title": "어느 기사 (2026-11-16 게재)", "kind": "article", "url": None},
    ])
    save_json(target, data)
    assert [str(p) for p in check(example_copy, strict=True)] == []
    # 다른 곳에서 잰 범위를 빌려 와 정한 값은 설계 가정이고, 빌려 온 자료를 sources 에 적을 수 있다 (11-19 songyee-ai 지적).
    data["constants"][0].update(grade="assumption")
    save_json(target, data)
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_sources_are_listed_strongest_first():
    """출처 목록은 센 자료부터 적는다 (공식 > 학술 자료 = 통계 > 업계 보고서 = 기사 > 직접 잰 값). 화면이 앞의 것을 대표로 보여도 근거가 세 보이지 않게 한다."""
    data = json.loads(CONSTANTS_PATH.read_text(encoding="utf-8"))
    paper = {"title": "어느 논문", "kind": "literature", "url": None}
    news = {"title": "어느 기사", "kind": "article", "url": None}
    data["constants"][0]["sources"] = [news, paper]
    with pytest.raises(ValueError, match="센 자료부터"):
        ConstantsFile.model_validate(data)
    data["constants"][0]["sources"] = [paper, news, {"title": "지도 도구로 잰 거리", "kind": "measurement", "url": None}]
    assert ConstantsFile.model_validate(data).constants[0].sources[2].kind == "measurement"


def test_borrowed_values_keep_each_material_with_its_kind():
    """T306 의 값 여덟은 빌려 온 자료를 하나씩 종류와 함께 적는다. 학술 자료와 기사가 섞인 것은 둘 다 남는다."""
    by_id = {c.constant_id: c for c in load_constants().constants}
    assert [s.kind for s in by_id["price-sensitivity-threshold-high"].sources] == ["literature", "article"]
    assert [s.kind for s in by_id["price-elasticity-upscale-weekday"].sources] == ["statistic", "literature"]
    assert all(c.grade == "assumption" for c in by_id.values() if c.sources)
    assert by_id["filled-price-unit"].sources == []


def test_old_run_records_without_sources_are_still_read():
    """11-20 전의 실행 기록은 출처를 글 한 줄(source)로 적었고 모두 null 이었다. 빈 목록으로 읽고, 다시 쓸 때는 sources 만 남는다 (임시 호환, T212 에서 없앰)."""
    data = json.loads((RUNS / BASELINE_RUN / "run.json").read_text(encoding="utf-8"))
    for item in data["constants"]:
        del item["sources"]
        item["source"] = None
    record = RunRecord.model_validate_json(json.dumps(data, ensure_ascii=False), strict=True)
    assert all(c.sources == [] for c in record.constants)
    dumped = record.model_dump(mode="json")["constants"][0]
    assert "source" not in dumped and dumped["sources"] == []
    data["constants"][0]["source"] = "옛 글 한 줄"
    with pytest.raises(ValueError):
        RunRecord.model_validate_json(json.dumps(data, ensure_ascii=False), strict=True)


def test_constants_hash_sees_only_what_changes_results(tmp_path):
    """상수 파일의 해시는 식별자·값·단위·쓰는지만 본다. 출처나 설명만 고치면 그대로라 기준 상황을 다시 돌리지 않아도 된다 (11-20, T214)."""
    data = json.loads(CONSTANTS_PATH.read_text(encoding="utf-8"))
    path = tmp_path / "constants.json"
    save_json(path, data)
    before = values_hash(path)
    data["constants"][0]["note"] = "설명만 고침"
    data["constants"][0]["sources"] = [{"title": "새로 찾은 자료", "kind": "article", "url": None}]
    data["constants"][0]["checked_on"] = "2026-11-20"
    save_json(path, data)
    assert values_hash(path) == before
    data["constants"][0]["value"] = data["constants"][0]["value"] + 1
    save_json(path, data)
    assert values_hash(path) != before
    data["constants"][0]["value"] -= 1
    data["constants"][-1]["in_use"] = not data["constants"][-1].get("in_use", True)
    save_json(path, data)
    assert values_hash(path) != before


def test_constants_not_in_use_are_kept_out_of_the_run_record():
    """정해 두었지만 아직 엔진이 쓰지 않는 값(in_use 가 false)은 실행 기록에 남지 않는다. 범위 값도 적을 수 있다."""
    found = load_constants()
    waiting = [c for c in found.constants if not c.in_use]
    assert waiting, "2단계·4단계에서 쓸 값이 파일에 있다"
    recorded = {c.constant_id for c in used_constants(read_model(EXAMPLE_ROOT / "engine" / "conditions.json", ConditionBundle))}
    assert not recorded & {c.constant_id for c in waiting}
    low = next(c for c in found.constants if c.constant_id == "price-sensitivity-threshold-low")
    assert (low.value.min, low.value.max) == (15, 20)
    data = json.loads(CONSTANTS_PATH.read_text(encoding="utf-8"))
    data["constants"][0]["value"] = {"min": 2, "max": 1}
    with pytest.raises(ValueError, match="min 이 max 보다 크다"):
        ConstantsFile.model_validate(data)


def test_constants_next_to_the_summary_are_recorded_with_their_file(example_copy):
    """집계 파일 옆의 상수 파일(한 개당 인원 등)이 있으면 실행 기록에 그 자리와 함께 남는다 (가상 예시 값으로 시험)."""
    data = json.loads(CONSTANTS_PATH.read_text(encoding="utf-8"))
    item = dict(data["constants"][0], constant_id="people-per-unit-geumryong-course-a", name="금룡 코스 A 한 개당 인원", value=1, unit="명",
                used_in="집계 파일의 people", note="지어낸 값", owner="hojitea-ui")
    save_json(example_copy / "data" / "samples" / "base_summary_constants.json", {"format_version": 1, "constants": [item]})
    played = play(example_copy, pick_geumryong)
    by_id = {c.constant_id: c for c in played.record.constants}
    assert by_id["people-per-unit-geumryong-course-a"].file == "data/samples/base_summary_constants.json"
    assert by_id["people-per-unit-geumryong-course-a"].applied is True  # 집계 쪽 상수는 집계 파일에 이미 들어 있어 늘 쓰인다
    assert [str(p) for p in check(example_copy, strict=True)] == []
    item.update(grade="statistic")
    save_json(example_copy / "data" / "samples" / "base_summary_constants.json", {"format_version": 1, "constants": [item]})
    assert any("등급이 statistic 인데 sources 에 그 종류의 자료가 없다" in str(p) for p in check(example_copy, strict=True))


# ── 이 실행의 계산에 쓰였는가 (applied, 11-20, T212·T130 ②) ─────────────────

NOTHING = RunUse(
    filled_prices=False,
    base_profile_mode="none",
    blank_people=frozenset(),
    splits=frozenset(),
    scored=False,
    scored_venues=frozenset(),
    scores_asked=False,
    requests=False,
)
# 가중치를 낼 때 쓰이는 상수 (기준이 아닌 상황은 기준 실행의 것을 따른다).
WEIGHT_IDS = ("takeout-teams-per-item", "add-on-people-per-item", "meal-lunch-dinner")


def applied_in(use: RunUse) -> set[str]:
    """`engine/constants.json` 의 상수 가운데 (쓰지 않는 것까지) 그 사실이면 쓰인 것."""
    return {c.constant_id for c in load_constants().constants if applied(c.constant_id, use)}


def applied_by_id(record: RunRecord) -> dict[str, bool | None]:
    return {c.constant_id: c.applied for c in record.constants}


def blank_course_b_people(root) -> None:
    """가상 예시 집계 파일의 금룡 코스 B 줄(주말 저녁)의 인원을 비운다. 엔진은 그 줄을 추가 상품처럼 한 개당 사람 수 상수로 센다."""
    summary = root / "data" / "samples" / "base_summary.csv"
    rows = load_csv(summary)
    for row in rows:
        if row["product_id"] == "course-b":
            row["people"] = ""
    save_csv(summary, rows)
    assert any(r.people is None for r in read_summary(summary))


def test_every_constant_in_the_file_has_a_rule_for_applied():
    """`engine/constants.json` 의 상수는 아직 쓰지 않는 것까지 모두 "계산에 쓰였는가"를 가르는 규칙이 있다.
    엔진은 규칙이 없는 상수에서 멈추지 않으므로(쓰인 것으로 적음), 빠뜨리지 않게 지키는 것은 이 테스트다."""
    missing = [c.constant_id for c in load_constants().constants if not has_rule(c.constant_id)]
    assert missing == []
    assert not has_rule("no-such-constant")


def test_each_rule_turns_on_only_its_constants():
    """규칙마다 켜지는 상수 (FORMATS 10.1절의 "쓴 결정 상수")."""
    ids = {c.constant_id for c in load_constants().constants}
    assert applied_in(NOTHING) == set()
    assert applied_in(replace(NOTHING, filled_prices=True)) == {"filled-price-unit"}
    # 요약을 소수로 보내면(raw) 상품 순위만, 범주로 보내면(bucketed) 범주의 선까지 쓴다.
    assert applied_in(replace(NOTHING, base_profile_mode="raw")) == {"base-profile-top-products"}
    assert applied_in(replace(NOTHING, base_profile_mode="bucketed")) == {
        "base-profile-top-products",
        "base-profile-bucket-high",
        "base-profile-bucket-mid",
    }
    assert applied_in(replace(NOTHING, blank_people=frozenset({"takeout"}))) == {"takeout-teams-per-item"}
    assert applied_in(replace(NOTHING, blank_people=frozenset({"other"}))) == {"add-on-people-per-item"}
    assert applied_in(replace(NOTHING, scored=True)) == {"share-sharpness-k"}
    # 가격 민감도의 문턱 분포와 2단계에서 요청에 넣을 값은 점수를 묻는 판으로 요청을 만들었을 때만 쓰인다.
    in_request = {i for i in ids if i.startswith(("price-threshold-", "budget-spread-", "sensitivity-threshold-spread-"))}
    assert {"price-threshold-median-pct", "price-threshold-90pct-range"} <= in_request
    assert applied_in(replace(NOTHING, scores_asked=True, requests=True)) == in_request
    assert applied_in(replace(NOTHING, scores_asked=True)) == applied_in(replace(NOTHING, requests=True)) == set()
    # 보정의 통과 기준, 분포로 바뀐 처음의 등급별 문턱, 4단계의 탄력성 범위는 실행의 계산에 들지 않는다. 사실이 모두 참이어도 쓰이지 않는다.
    everything = RunUse(
        filled_prices=True,
        base_profile_mode="bucketed",
        blank_people=frozenset({"takeout", "other"}),
        splits=frozenset({"meal-lunch-dinner"}),
        scored=True,
        scored_venues=frozenset({"geumryong"}),
        scores_asked=True,
        requests=True,
    )
    never = ("calibration-", "price-sensitivity-threshold-", "price-elasticity-")
    assert ids - applied_in(everything) == {i for i in ids if i.startswith(never)}
    # 업장 상수는 점수가 있는 답에서 그 업장에 몫이 갔을 때다.
    use = replace(NOTHING, scored=True, scored_venues=frozenset({"geumryong"}))
    assert applied(f"{VENUE_CONSTANT_PREFIX}geumryong", use) is True
    assert applied(f"{VENUE_CONSTANT_PREFIX}thebuffet", use) is False


def test_blank_people_kinds_sees_only_rows_inside_the_run(example_copy):
    """인원이 빈 칸인 줄의 갈래는 가중치를 내는 줄(그 달, 읽은 워커힐 업장, 돌리는 조건)에서만 센다."""
    inputs = runner.load_inputs(example_copy, "sample")
    bundle = inputs.conditions
    dinner, takeout = bundle.condition(DINNER), bundle.condition("takeout-weekend")
    course_b = next(r for r in inputs.summary if r.product_id == "course-b")  # 금룡 코스 B, 주말 저녁
    blank = course_b.model_copy(update={"people": None})
    blank_takeout = blank.model_copy(update={"occasion": "takeout", "meal": None})
    other_month = 1 if course_b.month != 1 else 2

    def kinds(rows: list[SummaryRow], conditions=(dinner,), month=None, venues=inputs.venues) -> set[str]:
        return blank_people_kinds(rows, list(conditions), bundle.assumed_splits, venues, month)

    assert kinds(inputs.summary) == set()
    assert kinds([blank]) == {"other"}
    assert kinds([blank], month=course_b.month) == {"other"}
    assert kinds([blank], month=other_month) == set()  # 다른 달로 돌린 실행
    assert kinds([blank], conditions=[bundle.condition("meal-dinner-weekday")]) == set()  # 그 줄이 들 조건을 돌리지 않음
    assert kinds([blank_takeout]) == set()
    assert kinds([blank_takeout], conditions=[dinner, takeout]) == {"takeout"}
    assert kinds([blank], venues={k: v for k, v in inputs.venues.items() if k != "geumryong"}) == set()  # 읽지 않은 업장


def test_engine_records_whether_each_constant_was_applied(example_copy):
    """예시 사본으로 돈 기준 실행은 예시 묶음의 기준 실행과 같은 표시다. 형식 검사도 통과한다."""
    played = play(example_copy, pick_geumryong)
    expected = applied_by_id(read_model(RUNS / BASELINE_RUN / "run.json", RunRecord))
    assert applied_by_id(played.record) == expected
    assert expected["meal-lunch-dinner"] is True and expected["share-sharpness-k"] is False
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_filled_price_and_blank_people_are_applied_when_the_run_used_them(example_copy):
    """가격이 빈 상품을 채우고, 인원이 빈 줄을 상수로 센 실행은 그 상수가 쓰였다고 적는다."""
    edit(venue_file(example_copy, "geumryong"), lambda d: product_of(d, "course-b").update(price=None, grade="unknown"))
    blank_course_b_people(example_copy)
    played = play(example_copy, pick_geumryong)
    assert played.record.filled_products == ["geumryong:course-b"]
    by_id = applied_by_id(played.record)
    assert by_id["filled-price-unit"] is True
    assert (by_id["add-on-people-per-item"], by_id["takeout-teams-per-item"]) == (True, False)
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_scenario_takes_the_weight_constants_from_its_baseline_run(example_copy):
    """기준이 아닌 상황은 기준 실행의 가중치를 쓰므로 가중치 쪽 상수의 표시도 기준 실행의 것이다.
    11-20 전의 기준 실행(applied 가 없음)이면 같은 집계 파일로 다시 낸다."""
    blank_course_b_people(example_copy)
    base = play(example_copy, pick_geumryong)
    wanted = {i: applied_by_id(base.record)[i] for i in WEIGHT_IDS}
    assert wanted == {"takeout-teams-per-item": False, "add-on-people-per-item": True, "meal-lunch-dinner": True}
    first = read_model(run_scenario(example_copy, PRICE_UP, weights_from=base.run_dir.name) / "run.json", RunRecord)
    assert {i: applied_by_id(first)[i] for i in WEIGHT_IDS} == wanted

    record = load_json(base.run_dir / "run.json")
    for item in record["constants"]:
        del item["applied"]
    save_json(base.run_dir / "run.json", record)
    again = run_scenario(example_copy, PRICE_UP, weights_from=base.run_dir.name, now=NOW + timedelta(hours=4))
    assert {i: applied_by_id(read_model(again / "run.json", RunRecord))[i] for i in WEIGHT_IDS} == wanted


def test_share_constants_are_applied_when_a_scored_answer_reaches_the_venue(example_copy):
    """점수가 있는 답이면 k 가 쓰이고, 업장 상수는 몫이 간 업장의 것만 쓰인다 (추정한 상수 파일의 것도)."""
    estimated = constants_file(
        constant_entry(f"{VENUE_CONSTANT_PREFIX}geumryong", 1.2),
        constant_entry(f"{VENUE_CONSTANT_PREFIX}thebuffet", 0.9),
    )
    save_json(sample_estimated(example_copy), estimated.model_dump(mode="json"))
    played = play_scored(example_copy)
    assert played.record.share_method == "scores"
    by_id = applied_by_id(played.record)
    assert by_id["share-sharpness-k"] is True
    assert by_id[f"{VENUE_CONSTANT_PREFIX}geumryong"] is True
    assert by_id[f"{VENUE_CONSTANT_PREFIX}thebuffet"] is False  # 점수가 0 이라 몫이 가지 않았다
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_check_compares_applied_with_the_record_and_the_ledger(example_copy):
    """형식 검사: applied 는 모두 적거나 모두 비운다. 실행 기록과 원장으로 다시 낼 수 있는 것은 견준다."""
    path = RUNS.relative_to(EXAMPLE_ROOT) / BASELINE_RUN / "run.json"
    path = example_copy / path
    original = load_json(path)
    constants = load_json(path)["constants"]
    constants[0]["applied"] = None
    save_json(path, original | {"constants": constants})
    assert any("applied 가 적힌 상수와 없는 상수가 섞여" in str(p) for p in check(example_copy, strict=True))
    constants = load_json(path)["constants"]
    constants[0]["applied"] = False
    next(c for c in constants if c["constant_id"] == "share-sharpness-k")["applied"] = True
    save_json(path, original | {"constants": constants})
    assert any("'share-sharpness-k' 의 applied 가 True 인데" in str(p) for p in check(example_copy, strict=True))
    # 11-20 전의 기록(모두 없음)은 그대로 읽힌다.
    for item in constants:
        del item["applied"]
    save_json(path, original | {"constants": constants})
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_a_constant_without_a_rule_does_not_stop_the_run(example_copy, monkeypatch, capsys):
    """쓰는 상수에 규칙이 없어도 실행은 멈추지 않는다. 그 상수는 쓰인 것(true)으로 적고 경고를 낸다 (빠뜨리지 않게 지키는 것은 위의 테스트)."""
    data = json.loads(CONSTANTS_PATH.read_text(encoding="utf-8"))
    data["constants"].append(dict(data["constants"][0], constant_id="new-rule-less-constant"))
    found = ConstantsFile.model_validate(data)
    monkeypatch.setattr(runner, "load_constants", lambda: found)
    monkeypatch.setattr(constants_module, "load_constants", lambda: found)
    played = play(example_copy, pick_geumryong)
    assert played.record.status == "ok"
    assert applied_by_id(played.record)["new-rule-less-constant"] is True
    assert "new-rule-less-constant" in capsys.readouterr().err
