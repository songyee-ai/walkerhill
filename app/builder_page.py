"""시나리오 만들기 페이지 (T130): 시안 scenario-builder-v4 의 화면으로 시나리오를 만들고 돌린다.

화면은 app/builder/ 의 HTML·CSS·JS 를 Streamlit 컴포넌트(st.components.v2)로 띄운다. 입력은 모두 브라우저에 있고, 파이썬은 세 가지만 한다.
1. 자료(업장·메뉴·페르소나·준비된 상황)와 결과 있는 시나리오 목록을 데이터 묶음으로 넘긴다 (app/builder_model.py).
2. "시뮬레이션 실행"이 보낸 상황 정의와 입력을 확인해 달마다 돌리고, 결과 묶음을 적고, 결과 페이지로 넘어간다.
3. 저장된 시나리오 창에서 "결과 보기"를 누르면 그 결과 페이지로 넘어간다.
"""

import time
from pathlib import Path

import streamlit as st

from app.builder_model import RunError, build, plan_run, run_plan
from app.result_page import PAGE_STYLE

BUILDER = Path(__file__).parent / "builder"
# 결과 페이지의 "고쳐서 새로 만들기"가 넣는 값 (어느 결과로 입력을 채울지)
PRELOAD_KEY = "builder_preload"
ERROR_KEY = "builder_error"


@st.cache_resource
def _component(stamp: tuple[float, ...]):
    """화면 조각을 한 번 등록한다. 파일을 고치면(수정 시각이 바뀌면) 다시 읽는다."""

    def read(name: str) -> str:
        return (BUILDER / name).read_text(encoding="utf-8")

    return st.components.v2.component(
        "walkerhill_builder", html=read("builder.html"), css=read("builder.css"), js=read("builder.js"), isolate_styles=True
    )


def render(repo_root: Path, result_page) -> None:
    st.html(PAGE_STYLE)
    preload = st.session_state.pop(PRELOAD_KEY, None)
    data = build(repo_root, preload, st.session_state.get(ERROR_KEY))
    stamp = tuple((BUILDER / name).stat().st_mtime for name in ("builder.html", "builder.css", "builder.js"))
    # 미리 채울 결과가 있으면 화면 조각을 새로 띄운다 (같은 조각이면 입력이 그대로 남는다)
    key = f"builder-{preload}" if preload else "builder"
    shown = _component(stamp)(data=data, key=key, on_action_change=lambda: None)
    action = shown.action if shown is not None else None
    if not isinstance(action, dict):
        return
    kind = action.get("type")
    if kind == "open_result" and action.get("result_id"):
        st.switch_page(result_page, query_params={"result": action["result_id"]})
    if kind == "run":
        try:
            plan = plan_run(repo_root, action.get("definition") or {}, action.get("input") or {})
            result_id = run_plan(repo_root, plan)
        except RunError as error:
            # 화면은 실행 중 창을 띄워 두고 있다. 다시 그리며 이유를 넘기면 화면이 창을 바꿔 보인다
            st.session_state[ERROR_KEY] = {"message": str(error), "at": time.time()}
            st.rerun()
        st.session_state.pop(ERROR_KEY, None)
        st.switch_page(result_page, query_params={"result": result_id})
