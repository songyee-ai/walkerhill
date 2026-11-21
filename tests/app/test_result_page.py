"""새 결과 화면 (T130): 결과 묶음(app/result_store.py), 데이터 묶음(app/result_model.py), 화면 파일(app/report/), 그림(app/static/).

값은 모두 예시 묶음(tests/fixtures/example)의 지어낸 값이다. 실제 기본 데이터로 돌린 실행은 쓰지 않는다.
"""

import json
import re
import shutil
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.result_model import (  # noqa: E402
    BANNER_VENUES,
    NAME_LINES,
    VENUE_ICON,
    banner_of,
    build,
    condition_texts,
    months_label,
    persona_icon,
)
from app.result_store import Pair, find_record, list_records, new_record, save_record  # noqa: E402

EXAMPLE = REPO_ROOT / "tests" / "fixtures" / "example"
STATIC = REPO_ROOT / "app" / "static"
REPORT = REPO_ROOT / "app" / "report"
SCEN = "20261117-103000-competitor-chinese-discount"
BASE = "20261117-101500-baseline"


def _repo(tmp_path: Path) -> Path:
    """예시 묶음만 든 저장소 흉내. 결과 묶음은 그 안의 private/results/ 에 쓴다."""
    shutil.copytree(EXAMPLE, tmp_path / "tests" / "fixtures" / "example")
    return tmp_path


def _runs(repo: Path) -> Path:
    return repo / "tests" / "fixtures" / "example" / "engine" / "samples" / "runs"


def test_old_run_is_found_as_one_month_result(tmp_path):
    repo = _repo(tmp_path)
    records = list_records(repo)
    assert [r.result_id for r in records] == [SCEN]
    assert records[0].found_from_run
    assert records[0].pairs == [Pair(None, BASE, SCEN)]


def test_saved_record_keeps_month_order_and_replaces_the_found_one(tmp_path):
    repo = _repo(tmp_path)
    # 해를 넘는 기간: 12월 → 1월 순서를 묶음이 지킨다 (FORMATS.md 10.1절 "달의 순서는 화면이 정한다")
    record = new_record(repo, _runs(repo), "sample", "competitor-chinese-discount", [Pair(12, BASE, SCEN), Pair(1, BASE, SCEN)])
    save_record(repo, record)
    records = list_records(repo)
    assert [r.result_id for r in records] == [SCEN]
    assert records[0].months == [12, 1]
    assert not records[0].found_from_run
    assert find_record(repo, "없는-결과").result_id == SCEN


def test_record_with_missing_run_is_left_out(tmp_path):
    repo = _repo(tmp_path)
    record = new_record(repo, _runs(repo), "sample", "competitor-chinese-discount", [Pair(12, BASE, "20261117-999999-지운-실행")])
    save_record(repo, record)
    assert all(r.months != [12] for r in list_records(repo))


def test_build_has_every_part_the_screen_reads(tmp_path):
    repo = _repo(tmp_path)
    record = new_record(repo, _runs(repo), "sample", "competitor-chinese-discount", [Pair(12, BASE, SCEN), Pair(1, BASE, SCEN)])
    data = build(record, repo)
    for key in ("title", "venues", "personas", "conditions", "condition_short", "months", "scenario", "assets", "persona_info", "evidence", "notes", "saved", "grade_names"):
        assert key in data, key
    assert [m["label"] for m in data["months"]] == ["12월", "1월"]
    assert data["scenario"]["period_label"] == "12월~1월"
    assert data["scenario"]["side"] == "outside"
    assert data["scenario"]["banner"] == "outside"
    month = data["months"][0]
    visit = month["visits"][0]
    assert visit["visit_no"] == "V01"
    for side in ("before", "after"):
        assert {"kind", "venue_id", "order", "order_key", "paid", "reason"} <= set(visit[side])
    # 매출 나누기가 있으면 갈래를 더한 값이 두 원장의 차이와 같다
    sales = month["sales"]
    assert sales is not None
    assert sales["after"] - sales["before"] == sales["parts"]["total"]
    assert sum(v for k, v in sales["parts"].items() if k != "total") == sales["parts"]["total"]
    # 데이터 묶음은 JSON 으로 넘어간다
    json.dumps(data, ensure_ascii=False)


def test_condition_texts_and_month_labels():
    long, short = condition_texts(EXAMPLE)
    assert long["meal-dinner-weekend"] == "주말 저녁 식사"
    assert short["meal-dinner-weekend"] == "주말 저녁"
    assert months_label([None]) == "일 년 전체"
    assert months_label([12]) == "12월"
    assert months_label([12, 1, 2]) == "12월~2월"


def test_banner_rule():
    class Change:
        def __init__(self, venue_id):
            self.venue_id = venue_id

    assert banner_of("outside", [Change("geumryong")]) == "outside"
    assert banner_of("inside", [Change("geumryong"), Change("thebuffet")]) == "geumryong"
    assert banner_of("inside", [Change("examplehotel-chinese")]) == "common"
    assert banner_of("inside", []) == "common"


def test_every_picture_the_screen_asks_for_exists():
    for name in [*BANNER_VENUES, "outside", "common"]:
        assert (STATIC / "banners" / f"banner-{name}.webp").is_file(), name
    for icon in set(VENUE_ICON.values()) | {"home"}:
        assert (STATIC / "icons" / "buildings" / f"{icon}.svg").is_file(), icon
    for persona_id in [*NAME_LINES, "family-elders", "someone-new"]:
        assert (STATIC / "icons" / "personas" / f"{persona_icon(persona_id)}.svg").is_file(), persona_id
    for plate in ("plate-in", "plate-new", "plate-leave", "plate-move", "plate-order"):
        assert (STATIC / "icons" / "plates" / f"{plate}.svg").is_file(), plate


def test_report_files_have_no_mock_leftovers():
    html = (REPORT / "report.html").read_text(encoding="utf-8")
    css = (REPORT / "report.css").read_text(encoding="utf-8")
    js = (REPORT / "report.js").read_text(encoding="utf-8")
    for text in (html, css, js):
        # 시안 폴더의 상대 경로와 시안 주소가 남으면 그림자 영역에서 깨진다
        assert '"icon-set/' not in text and "report-v14/" not in text and "8765" not in text
        assert "scenario-builder-v4" not in text and "compare-page-v3" not in text
    # 가림 흔적 (T131 에서 거둠)
    assert "wh-mask" not in html and "data-amounts" not in html
    # 그림자 영역 안에서는 :root 와 body 가 맞지 않는다 (맨 앞 설명 주석은 빼고 본다)
    rules = css.split("*/", 1)[1]
    assert ":root" not in rules
    assert not re.search(r"(^|[}\s,])body\s*[{:]", rules)
    assert js.startswith("// 결과 페이지 스크립트") and "export default function" in js


def _result_screen(repo: str) -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, repo)
    from app import result_page

    result_page.render(Path(repo), None)


def test_result_page_renders_without_error():
    # 서버 없이 결과 화면만 띄운다. 이 PC 의 결과가 없으면 저장소의 예시 실행을 연다
    app = AppTest.from_function(_result_screen, args=(str(REPO_ROOT),), default_timeout=60).run()
    assert not app.exception
