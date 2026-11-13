"""화면의 뼈대가 오류 없이 그려지는지 본다 (서버를 띄우지 않고 Streamlit 의 테스트 도구로 돌린다)."""

from conftest import REPO_ROOT
from streamlit.testing.v1 import AppTest


def test_app_skeleton_renders_example_data():
    app = AppTest.from_file(str(REPO_ROOT / "app" / "main.py"), default_timeout=60).run()
    assert not app.exception
    assert app.title[0].value == "워커힐 다이닝 페르소나 시뮬레이터"
    # 모든 금액이 가상이라는 표시가 있다 (docs/PRD.md 10절).
    assert "가상" in app.caption[0].value
    # 업장 표 하나와 실행 결과 표 둘.
    assert len(app.dataframe) == 3
