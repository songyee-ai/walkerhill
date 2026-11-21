"""결과 페이지 (T130): 시나리오 결과 하나를 시안 final-v14 의 화면으로 보인다.

화면은 app/report/ 의 HTML·CSS·JS 를 Streamlit 컴포넌트(st.components.v2)로 띄운다. 파이썬은 세 가지만 한다.
1. 주소의 `?result=<result_id>` 로 결과 묶음을 찾는다 (app/result_store.py). 없으면 가장 새 결과.
2. 그 결과를 데이터 묶음으로 바꿔 넘긴다 (app/result_model.py). 기간 고르기·지도 재생·표 거르기는 브라우저에서 한다.
3. 화면이 보낸 동작을 받는다: 다른 결과 열기, 시나리오 만들기로 가기.
"""

from pathlib import Path

import streamlit as st

from app.result_model import build
from app.result_store import find_record

REPORT = Path(__file__).parent / "report"
# Streamlit 의 머리·여백을 걷어 시안의 머리가 맨 위에 오게 한다. 이 페이지에만 넣는다.
PAGE_STYLE = """<style>
[data-testid="stHeader"]{display:none}
[data-testid="stMainBlockContainer"],.block-container{padding:0!important;max-width:none!important}
[data-testid="stMain"]{padding:0}
</style>"""


@st.cache_resource
def _component(stamp: tuple[float, ...]):
    """화면 조각을 한 번 등록한다. 파일을 고치면(수정 시각이 바뀌면) 다시 읽는다."""

    def read(name: str) -> str:
        return (REPORT / name).read_text(encoding="utf-8")

    return st.components.v2.component(
        "walkerhill_report", html=read("report.html"), css=read("report.css"), js=read("report.js"), isolate_styles=True
    )


def render(repo_root: Path, builder_page: st.Page) -> None:
    st.html(PAGE_STYLE)
    wanted = st.query_params.get("result")
    record = find_record(repo_root, wanted)
    if record is None:
        st.info("아직 돌린 결과가 없습니다. 시나리오를 만들어 돌리면 여기에 결과가 뜹니다.")
        st.page_link(builder_page, label="시나리오 만들기로 가기")
        return
    if wanted and wanted != record.result_id:
        st.warning("주소의 결과를 찾지 못해 가장 새 결과를 엽니다. 지웠거나 다른 PC 에서 돌린 결과일 수 있습니다.")
    try:
        data = build(record, repo_root)
    except (OSError, ValueError) as error:
        st.error(f"결과 `{record.result_id}` 를 읽지 못했습니다. 형식이 바뀌기 전에 돌린 실행이면 다시 돌려 주세요.\n\n{error}")
        return
    # 결과마다 화면 조각을 따로 띄운다 (key). 같은 조각을 다른 결과로 다시 채우지 않아도 된다.
    stamp = tuple((REPORT / name).stat().st_mtime for name in ("report.html", "report.css", "report.js"))
    shown = _component(stamp)(data=data, key=f"report-{record.result_id}", on_action_change=lambda: None)
    action = shown.action if shown is not None else None
    if not isinstance(action, dict):
        return
    kind = action.get("type")
    if kind == "open_result" and action.get("result_id"):
        st.query_params["result"] = action["result_id"]
        st.rerun()
    elif kind in ("open_builder", "edit"):
        st.switch_page(builder_page)
