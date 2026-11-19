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
