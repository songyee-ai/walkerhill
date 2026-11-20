"""가격 민감도의 문턱 (T212, docs/FORMATS.md 9절의 `price_threshold`). 값은 지어낸 값이다."""

import math
from statistics import NormalDist

import pytest

from engine.constants import load_constants
from engine.formats.constants import ConstantsFile
from engine.thresholds import MEDIAN_ID, RANGE_ID, grade_thresholds, price_threshold, with_price_threshold
from tests.test_estimate import constant_entry


def constants(median, low, high) -> ConstantsFile:
    return ConstantsFile.model_validate(
        {
            "format_version": 1,
            "constants": [
                {**constant_entry(MEDIAN_ID, median), "unit": "%"},
                {**constant_entry(RANGE_ID, 0), "value": {"min": low, "max": high}, "unit": "%"},
            ],
        }
    )


def test_grades_are_the_middle_people_of_three_equal_groups():
    """가운데 10%, 90% 가 5 ~ 20% 인 로그정규 분포를 세 무리로 나눈 가운데 사람의 문턱."""
    found = grade_thresholds(constants(10, 5, 20))
    sigma = math.log(2) / NormalDist().inv_cdf(0.95)
    z = NormalDist().inv_cdf(1 / 6)
    assert found == {"high": round(10 * math.exp(sigma * z), 1), "mid": 10.0, "low": round(10 * math.exp(-sigma * z), 1)}
    assert found == {"high": 6.7, "mid": 10.0, "low": 15.0}


def test_engine_constants_give_the_documented_grades():
    assert grade_thresholds(load_constants()) == {"high": 6.7, "mid": 10.0, "low": 15.0}


@pytest.mark.parametrize("median, low, high", [(0, 5, 20), (10, 12, 20), (10, 5, 9)])
def test_grade_thresholds_refuse_a_median_outside_the_range(median, low, high):
    with pytest.raises(ValueError):
        grade_thresholds(constants(median, low, high))


PERSONA = {"persona_id": "x", "budget": {"basis": "per_person", "typical": 120000, "max": 160000}, "buying": {"price_sensitivity": "mid"}}
GRADES = {"high": 6.7, "mid": 10.0, "low": 15.0}


def test_price_threshold_gives_the_amount_in_the_budget_basis():
    assert price_threshold(PERSONA, GRADES) == {"sensitivity": "mid", "pct": 10.0, "basis": "per_person", "amount": 132000}
    high = {**PERSONA, "buying": {"price_sensitivity": "high"}}
    # 120,000 × 1.067 = 128,040 → 100원 단위로 128,000
    assert price_threshold(high, GRADES)["amount"] == 128000


def test_threshold_is_added_only_for_prompts_that_ask_scores():
    """옛 판(p1 ~ p3)의 요청은 그대로라 받아 둔 답이 재생된다."""
    for old in ("p1", "p2", "p3"):
        assert with_price_threshold(PERSONA, old, GRADES) is PERSONA
    added = with_price_threshold(PERSONA, "p4", GRADES)
    assert added["price_threshold"]["amount"] == 132000
    assert "price_threshold" not in PERSONA


def test_scoring_run_sends_the_threshold_in_the_request(example_copy):
    """점수를 묻는 판으로 돈 실행의 저장된 요청에 문턱이 들어 있다."""
    from engine.formats import SavedResponse, read_model
    from tests.test_estimate import add_thebuffet_people, scored_run

    add_thebuffet_people(example_copy)
    run_dir = scored_run(example_copy)
    saved = [read_model(p, SavedResponse) for p in (run_dir / "llm").glob("*.json")]
    assert saved
    for entry in saved:
        found = entry.request.persona["price_threshold"]
        budget = entry.request.persona["budget"]
        assert found["pct"] == GRADES[entry.request.persona["buying"]["price_sensitivity"]]
        assert found["basis"] == budget["basis"] and found["amount"] >= budget["typical"]
