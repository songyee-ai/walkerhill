"""새 시나리오 만들기 화면 (T130): 데이터 묶음(app/builder_model.py)과 화면 파일(app/builder/).

값은 모두 예시 묶음(tests/fixtures/example)의 지어낸 값이다. 실제 기본 데이터는 쓰지 않는다.
엔진을 돌려 결과 화면까지 가는 것은 브라우저로 확인했다 (진행 문서 T130 절).
"""

import json
import shutil
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.builder_model import (  # noqa: E402
    RunError,
    _input_of,
    build,
    condition_ids_of,
    months_of,
    plan_run,
    scenario_from,
)

EXAMPLE = REPO_ROOT / "tests" / "fixtures" / "example"
BUILDER = REPO_ROOT / "app" / "builder"


def _repo(tmp_path: Path) -> Path:
    """예시 묶음을 맨 위에 둔 저장소 흉내 (팀 자료). 연습용 사본은 tests/fixtures/example 에서 베낀다."""
    shutil.copytree(EXAMPLE, tmp_path, dirs_exist_ok=True)
    shutil.copytree(EXAMPLE, tmp_path / "tests" / "fixtures" / "example")
    return tmp_path


def test_months_keep_order_across_the_year():
    assert months_of("year", None, None) == [None]
    assert months_of("single", 4, 4) == [4]
    assert months_of("range", 11, 2) == [11, 12, 1, 2]
    assert months_of("range", 3, 5) == [3, 4, 5]


def test_condition_ids_come_from_days_and_occasions():
    assert condition_ids_of(EXAMPLE, ["weekend"], ["dinner"]) == ["meal-dinner-weekend"]
    found = condition_ids_of(EXAMPLE, ["weekday", "weekend"], ["lunch", "takeout"])
    assert set(found) <= {"meal-lunch-weekday", "meal-lunch-weekend", "takeout-weekday", "takeout-weekend"}
    assert "meal-lunch-weekend" in found


def test_input_round_trip_from_a_result():
    state = _input_of("practice", ["family-elders"], ["meal-dinner-weekend"], [12, 1], "p1")
    assert state["days"] == ["weekend"] and state["occasions"] == ["dinner"]
    assert (state["period"], state["start"], state["end"]) == ("range", 12, 1)
    assert months_of(state["period"], state["start"], state["end"]) == [12, 1]


def _promo_definition(promo_id: str, name: str = "시험 할인") -> dict:
    return {
        "name": name,
        "kind": "competitor",
        "description": "",
        "note": "",
        "changes": [
            {
                "op": "add_promotion",
                "venue_id": "examplehotel-chinese",
                "promotion": {
                    "promo_id": promo_id,
                    "name": "주말 10% 할인",
                    "benefit": {"type": "discount_pct", "value": 10},
                    "applies_to": None,
                    "conditions": {"day_type": "weekend", "meal": None, "party_min": None, "stay": None},
                    "period": None,
                    "grade": "assumption",
                    "source_id": None,
                },
            }
        ],
    }


def test_scenario_id_is_made_from_the_changes_only():
    first = scenario_from(_promo_definition("ui-3f2a9c1e-1111-4abc-8def-000000000001"), {})
    again = scenario_from(_promo_definition("ui-9a8b7c6d-2222-4abc-8def-000000000002", name="이름만 바꿈"), {})
    # 화면이 매번 만드는 UUID 는 내용으로 바뀌어, 같은 바꿀 것이면 같은 식별자가 나온다 (저장된 답을 다시 쓴다)
    assert first.scenario_id == again.scenario_id
    assert first.scenario_id.startswith("ui-")
    promo = first.changes[0].promotion
    assert promo.promo_id == again.changes[0].promotion.promo_id and promo.promo_id.startswith("ui-promo-")


def test_unchanged_preset_keeps_its_id():
    preset = json.loads((EXAMPLE / "scenarios" / "competitor-chinese-discount.json").read_text(encoding="utf-8"))
    presets = {preset["scenario_id"]: {"name": preset["name"], "kind": preset["kind"], "changes": preset["changes"]}}
    definition = {"name": preset["name"] + " 수정본", "kind": preset["kind"], "changes": preset["changes"]}
    assert scenario_from(definition, presets).scenario_id == "competitor-chinese-discount"


def test_build_gives_both_catalogs(tmp_path):
    repo = _repo(tmp_path)
    data = build(repo)
    for source in ("team", "practice"):
        catalog = data["catalogs"][source]
        assert {"venues", "people", "presets", "prompts", "default_prompt", "data_label", "data_note", "can_call"} <= set(catalog)
        assert catalog["people"] and all("icon" in p and "party" in p for p in catalog["people"])
    # 연습용 사본은 AI 를 부르지 않는다
    assert data["catalogs"]["practice"]["can_call"] is False
    json.dumps(data, ensure_ascii=False)


def test_plan_run_stops_with_a_reason(tmp_path):
    repo = _repo(tmp_path)
    definition = _promo_definition("ui-3f2a9c1e-1111-4abc-8def-000000000001")
    with pytest.raises(RunError, match="페르소나"):
        plan_run(repo, definition, {"source": "practice", "people": [], "days": ["weekend"], "occasions": ["dinner"], "period": "year"})
    plan = plan_run(
        repo,
        definition,
        {"source": "practice", "people": ["family-elders"], "days": ["weekend"], "occasions": ["dinner"], "period": "range", "start": 12, "end": 1},
    )
    # 예시 사본의 저장된 답은 달 없이 받은 것이라 늘 일 년 전체로 돈다
    assert plan.months == [None] and plan.practice and not plan.call_llm
    assert plan.condition_ids == ["meal-dinner-weekend"]


def test_builder_files_have_no_mock_leftovers():
    html = (BUILDER / "builder.html").read_text(encoding="utf-8")
    css = (BUILDER / "builder.css").read_text(encoding="utf-8")
    js = (BUILDER / "builder.js").read_text(encoding="utf-8")
    for text in (html, css, js):
        assert "icon-set/" not in text and "final-v14" not in text and "compare-page-v3" not in text
        assert "localhost:8765" not in text
    assert "history." not in js and "location." not in js and "document.body" not in js
    assert ":root" not in css.split("*/", 1)[1]
    assert "시안에서는" not in html


def _builder_screen(repo: str) -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, repo)
    from app import builder_page

    builder_page.render(Path(repo), None)


def test_builder_page_renders_without_error():
    app = AppTest.from_function(_builder_screen, args=(str(REPO_ROOT),), default_timeout=60).run()
    assert not app.exception
