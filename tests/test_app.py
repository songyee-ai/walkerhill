"""화면이 오류 없이 그려지는지만 본다 (서버를 띄우지 않고 Streamlit 의 테스트 도구로 돌린다).

화면의 내용(표, 결과, 비교)은 화면 담당의 테스트 `tests/app/` 가 본다. 여기서는 제목과 "가상" 표시만 본다.
"""

from conftest import REPO_ROOT
from streamlit.testing.v1 import AppTest


def test_app_renders_with_title_and_virtual_label():
    app = AppTest.from_file(str(REPO_ROOT / "app" / "main.py"), default_timeout=60).run()
    assert not app.exception
    assert app.title[0].value == "워커힐 다이닝 페르소나 시뮬레이터"
    # 모든 금액이 가상이라는 표시가 있다 (docs/PRD.md 10절).
    assert "가상" in app.caption[0].value
