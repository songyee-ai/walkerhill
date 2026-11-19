"""결정 상수 (T210, docs/FORMATS.md 6.1절).

엔진의 숫자 가운데 결과에 영향을 주는 것은 `engine/constants.json` 에 값과 근거를 함께 적고, 엔진은 그 값을 쓴다.
실행 기록에는 그 실행이 쓴 상수를 값까지 남긴다.
"""

import json
from datetime import timedelta

import pytest

from engine import calibration, weights
from engine.constants import CONSTANTS_PATH, load_constants, used_constants
from engine.formats import ConditionBundle, RunRecord, read_model
from engine.formats.constants import ConstantsFile
from tests.conftest import BASELINE_RUN, EXAMPLE_ROOT, load_json, save_json
from tests.test_engine import NOW, pick_geumryong, play
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
    assert record.constants == used_constants(bundle)
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
    """공개 자료에서 가져온 값(학술 자료, 통계, 업계 보고서, 기사, 공식)은 출처를 적어야 한다."""
    target = example_copy / "engine" / "constants.json"
    data = json.loads(CONSTANTS_PATH.read_text(encoding="utf-8"))
    save_json(target, data)
    assert [str(p) for p in check(example_copy, strict=True)] == []
    data["constants"][0].update(grade="literature")
    save_json(target, data)
    problems = [str(p) for p in check(example_copy, strict=True)]
    assert any("등급이 literature 인데 source 가 비어 있다" in p for p in problems)
    data["constants"][0].update(source="Andreyeva, Long & Brownell, 2010, AJPH 100(2)")
    save_json(target, data)
    assert [str(p) for p in check(example_copy, strict=True)] == []
    # 다른 곳에서 잰 범위를 빌려 와 정한 값은 설계 가정이고, 빌려 온 자료를 source 에 적을 수 있다 (11-19 songyee-ai 지적).
    data["constants"][0].update(grade="assumption")
    save_json(target, data)
    assert [str(p) for p in check(example_copy, strict=True)] == []


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
    assert [str(p) for p in check(example_copy, strict=True)] == []
    item.update(grade="statistic")
    save_json(example_copy / "data" / "samples" / "base_summary_constants.json", {"format_version": 1, "constants": [item]})
    assert any("등급이 statistic 인데 source 가 비어 있다" in str(p) for p in check(example_copy, strict=True))
