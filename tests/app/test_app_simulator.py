"""간편 시뮬레이터: 상황 만들기와 기본 시나리오 대비 비교 (T202, app/scenario_builder.py, app/simulator.py)."""

import shutil
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.compare import compare  # noqa: E402
from app.results import load_run  # noqa: E402
from app.runs import EXAMPLE_VENUES, simulate  # noqa: E402
from app.scenario_builder import (  # noqa: E402
    UI_PREFIX,
    competitor_discount,
    our_limited_menu,
    our_price,
    write_scenario,
)
from app.simulator import conditions_for, menu_slots_for, persona_cards, prepared_scenarios, venue_catalog  # noqa: E402
from engine.formats import Scenario, Venue, read_model  # noqa: E402
from engine.scenarios import ScenarioError, apply_scenario  # noqa: E402

EXAMPLE = REPO_ROOT / "tests" / "fixtures" / "example"


def _venues() -> dict[str, Venue]:
    return {p.stem: read_model(p, Venue) for p in (EXAMPLE / "data" / "venues").glob("*.json")}


@pytest.mark.parametrize(
    "scenario",
    [
        competitor_discount("examplehotel-chinese", "예시호텔 중식당", 20, "weekend"),
        competitor_discount("examplehotel-chinese", "예시호텔 중식당", 15),
        our_price("geumryong", "금룡", -10),
        our_price("geumryong", "금룡", 15),
        our_limited_menu("geumryong", "금룡", "겨울 한정 코스", 120000, "저녁", "weekend"),
    ],
    ids=lambda s: s.scenario_id,
)
def test_built_scenarios_follow_the_format_and_apply_to_the_venues(scenario: Scenario, tmp_path: Path):
    assert scenario.scenario_id.startswith(UI_PREFIX)
    # 엔진과 형식 검사가 쓰는 같은 코드로 적용해 본다 (업장의 종류, 상품 규칙).
    apply_scenario(_venues(), scenario)
    path = write_scenario(tmp_path, scenario)
    assert read_model(path, Scenario) == scenario  # 파일로 쓴 것이 엄격한 읽기를 통과한다


def test_limited_menu_is_a_new_product_not_a_discount():
    # 팀장 요청(11-16): 우리 프로모션은 할인보다 한정 메뉴를 더하는 방식.
    scenario = our_limited_menu("geumryong", "금룡", "겨울 한정 코스", 120000)
    assert scenario.kind == "our_promo"
    [change] = scenario.changes
    assert change.op == "add_product" and change.product.price == 120000
    # 같은 메뉴면 같은 식별자라 저장된 답을 다시 쓸 수 있다.
    assert our_limited_menu("geumryong", "금룡", "겨울 한정 코스", 120000).scenario_id == scenario.scenario_id
    assert our_limited_menu("geumryong", "금룡", "겨울 한정 코스", 130000).scenario_id != scenario.scenario_id


def test_limited_menu_offers_only_the_venues_occasions():
    # 식사만 하는 업장에 디저트 메뉴를 더하면 엔진이 받지 않는다. 그래서 화면은 그 업장이 하는 때만 보여 준다.
    occasions = venue_catalog(EXAMPLE)["geumryong"].occasions
    assert menu_slots_for(occasions) == ["점심", "저녁"]
    with pytest.raises(ScenarioError):
        apply_scenario(_venues(), our_limited_menu("geumryong", "금룡", "빙수 세트", 30000, "디저트·차"))


def test_example_choices_for_the_screen():
    assert {c["id"] for c in persona_cards(EXAMPLE)} == {"family-elders", "family-kids"}
    assert conditions_for(EXAMPLE, ["주말"], ["저녁"]) == ["meal-dinner-weekend"]
    assert set(conditions_for(EXAMPLE, ["평일", "주말"], ["저녁"])) == {"meal-dinner-weekday", "meal-dinner-weekend"}
    prepared = prepared_scenarios(EXAMPLE)
    assert "competitor-chinese-discount" in prepared and "baseline" not in prepared


def _copy(tmp_path: Path) -> Path:
    root = tmp_path / "try-example"
    shutil.copytree(EXAMPLE, root)
    return root


def test_prepared_scenario_compares_without_a_key(tmp_path: Path):
    # 화면의 "기본 시나리오와 비교하기"와 같은 흐름: 기준을 돌리고 그 가중치로 상황을 돌린다. 저장된 답을 재생한다.
    root = _copy(tmp_path)
    result = simulate(
        root, REPO_ROOT, "sample", "competitor-chinese-discount",
        ["family-elders"], ["meal-dinner-weekend"], list(EXAMPLE_VENUES), False, is_example=True,
    )  # fmt: skip
    assert result.ok, result.baseline.output + (result.scenario.output if result.scenario else "")
    assert load_run(result.scenario.run_dir).record.weights_from == result.baseline.run_dir.name
    comparison = compare(load_run(result.baseline.run_dir), load_run(result.scenario.run_dir))
    assert [m.move for m in comparison.moves] == ["out"]


def test_new_scenario_without_saved_answers_is_reported_not_hidden(tmp_path: Path):
    # 처음 해 보는 조합은 저장된 답이 없어 키 없이는 "견줄 수 없음"으로 남는다. 조용히 기준과 같다고 하지 않는다.
    root = _copy(tmp_path)
    scenario = our_limited_menu("geumryong", "금룡", "겨울 한정 코스", 120000, "저녁", "weekend")
    write_scenario(root, scenario)
    result = simulate(
        root, REPO_ROOT, "sample", scenario.scenario_id,
        ["family-elders"], ["meal-dinner-weekend"], list(EXAMPLE_VENUES), False, is_example=True,
    )  # fmt: skip
    assert result.ok
    comparison = compare(load_run(result.baseline.run_dir), load_run(result.scenario.run_dir))
    assert [m.move for m in comparison.moves] == ["failed"]
    assert "저장된 응답이 없다" in comparison.moves[0].fail_reason


def test_simulator_tab_renders_with_season_and_weather_marked_pending():
    app = AppTest.from_file(str(REPO_ROOT / "app" / "main.py"), default_timeout=60).run()
    assert not app.exception
    app.selectbox(key="sim_weather").set_value("비").run()
    assert not app.exception
    assert any("반영되지 않습니다" in c.value for c in app.caption)
    assert any(b.label == "기본 시나리오와 비교하기" for b in app.button)
