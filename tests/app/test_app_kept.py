"""기본 시나리오의 답을 그대로 쓴 방문을 화면에 보인다 (T128, 실행 기록의 `baseline_answers`, FORMATS.md 10.1절 "상관없는 방문의 답").

예시 실행을 임시 폴더에 베껴 상황 실행의 `baseline_answers` 에 방문 하나를 적어 본다. 값은 모두 예시 묶음의 지어낸 값이다.
"""

import json
import shutil
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.compare import combine_months, compare  # noqa: E402
from app.results import load_run  # noqa: E402
from app.simulator import KEPT_VISIT_NOTE, kept_note  # noqa: E402

RUNS = REPO_ROOT / "tests" / "fixtures" / "example" / "engine" / "samples" / "runs"
BASE, SCEN = "20261117-101500-baseline", "20261117-103000-competitor-chinese-discount"
VISIT = "family-elders__meal-dinner-weekend"


def _kept_copy(tmp_path: Path) -> Path:
    runs = tmp_path / "runs"
    shutil.copytree(RUNS, runs)
    path = runs / SCEN / "run.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["baseline_answers"] = [VISIT]
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return runs


def test_no_note_when_no_visit_kept_the_baseline_answer():
    # 예시 상황 실행은 목록이 비어 있다. 11-19 T210 전의 실행에는 목록이 없다(null). 둘 다 줄을 보이지 않는다.
    comparison = compare(load_run(RUNS / BASE), load_run(RUNS / SCEN))
    assert comparison.kept_count == 0 and kept_note(comparison) is None


def test_kept_visits_are_counted_and_marked(tmp_path: Path):
    runs = _kept_copy(tmp_path)
    comparison = compare(load_run(runs / BASE), load_run(runs / SCEN))
    [move] = comparison.moves
    assert move.kept_baseline and comparison.kept_count == 1
    note = kept_note(comparison)
    assert note is not None and note.startswith("방문 1건 가운데 1건은") and "임시 규칙" in note and "2단계에서 없앱니다" in note
    assert "원" not in note  # 방문 수만 말한다. 기본 데이터 실행에서도 가리지 않는다
    # 기간이면 달마다의 방문을 모두 센다.
    both = combine_months([(11, comparison), (12, comparison)])
    assert kept_note(both) is not None and kept_note(both).startswith("방문 2건 가운데 2건은")


def _show(runs_dir: str) -> None:
    from pathlib import Path as _Path

    from app.compare import compare as _compare
    from app.results import load_run as _load_run
    from app.simulator import show_comparison

    runs = _Path(runs_dir)
    comparison = _compare(_load_run(runs / "20261117-101500-baseline"), _load_run(runs / "20261117-103000-competitor-chinese-discount"))
    show_comparison(comparison, {}, "할인")


def test_screen_shows_the_count_and_marks_the_visit(tmp_path: Path):
    runs = _kept_copy(tmp_path)
    app = AppTest.from_function(_show, args=(str(runs),), default_timeout=60)
    app.run()
    assert not app.exception
    captions = [c.value for c in app.caption]
    assert any(c.startswith("방문 1건 가운데 1건은") for c in captions)
    assert KEPT_VISIT_NOTE in captions  # "한 사람씩 자세히 보기"에서 고른 방문에 붙는다
