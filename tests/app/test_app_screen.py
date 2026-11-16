"""화면이 오류 없이 그려지고, 고른 것이 바뀌면 결과가 바뀌는지 본다 (T09).

서버를 띄우지 않고 Streamlit 의 테스트 도구로 돌린다.
"""

import shutil
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.results import EXAMPLE_LABEL, RunSource  # noqa: E402

MAIN = str(REPO_ROOT / "app" / "main.py")
EXAMPLE_RUNS = REPO_ROOT / "tests" / "fixtures" / "example" / "engine" / "samples" / "runs"


def _app() -> AppTest:
    return AppTest.from_file(MAIN, default_timeout=60)


def _choose_example(app: AppTest, run_id: str) -> AppTest:
    # 이 PC 에 엔진으로 돌린 실행이 있어도 예시 실행을 고르게 한다. selectbox 의 값은 RunSource 다.
    app.selectbox(key="source").set_value(RunSource(EXAMPLE_LABEL, EXAMPLE_RUNS)).run()
    app.selectbox(key="run_id").set_value(run_id).run()
    return app


def _all_text(app: AppTest) -> str:
    parts = [m.value for m in app.markdown] + [s.value for s in app.subheader] + [h.value for h in app.header]
    parts += [str(m.value) for m in app.metric] + [c.value for c in app.caption]
    return "\n".join(parts)


def test_screen_renders_and_every_amount_column_is_virtual():
    app = _app().run()
    assert not app.exception
    assert app.title[0].value == "워커힐 다이닝 페르소나 시뮬레이터"
    assert "가상" in app.caption[0].value
    for frame in app.dataframe:
        for column in frame.value.columns:
            if "원" in column.split()[-1] or "금액" in column or "매출" in column:
                assert "가상" in column, column
    for metric in app.metric:
        assert "가상" in metric.label and "가상" in metric.value


def test_example_baseline_shows_choice_and_not_chosen():
    app = _app().run()
    app = _choose_example(app, "20261117-101500-baseline")
    assert not app.exception
    text = _all_text(app)
    assert "금룡" in text
    assert "고르지 않은 업장" in text
    assert "600,000원 (가상)" in text


def test_example_competitor_run_switches_the_result():
    app = _app().run()
    app = _choose_example(app, "20261117-103000-competitor-chinese-discount")
    assert not app.exception
    text = _all_text(app)
    assert "경쟁 업장" in text
    assert "상황 `competitor-chinese-discount`" in text


def test_other_folder_reads_runs_written_elsewhere(tmp_path: Path):
    # 엔진을 --root 로 다른 곳에서 돌린 결과도 경로를 적으면 읽는다.
    runs = tmp_path / "runs"
    shutil.copytree(EXAMPLE_RUNS, runs)
    app = _app().run()
    app.sidebar.text_input[0].set_value(str(runs)).run()
    assert not app.exception
    assert app.selectbox(key="source").value.folder == runs


def test_unknown_other_folder_warns_instead_of_failing(tmp_path: Path):
    app = _app().run()
    app.sidebar.text_input[0].set_value(str(tmp_path / "없음")).run()
    assert not app.exception
    assert any("찾지 못했습니다" in w.value for w in app.sidebar.warning)


def test_run_panel_says_what_is_missing_in_the_repository():
    # 저장소에 페르소나나 프롬프트가 아직 없으면 돌리기 버튼 대신 모자란 것을 알린다.
    app = _app().run()
    app.radio(key="run_root").set_value(app.radio(key="run_root").options[0]).run()
    assert not app.exception
    from app.runs import choices

    missing = choices(REPO_ROOT).missing
    if missing:
        assert any("아직 없는 것" in w.value for w in app.sidebar.warning)
    else:
        assert any(b.label == "돌리기" for b in app.sidebar.button)
