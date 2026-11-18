"""화면 전체의 모양 (T202). Streamlit 기본 모양 위에 덧입히는 CSS 와 머리글이다.

색과 간격은 Tailwind 의 기본 팔레트(indigo, slate)와 간격 단위를 따랐다. 밝은·어두운 화면에서 모두 읽히게
글자색은 Streamlit 의 것을 그대로 물려받고, 배경과 선은 반투명한 색을 쓴다.
`.streamlit/config.toml` 은 공통 틀이라 고치지 않고, 이 파일에서만 덧입힌다 (CLAUDE.md "파일 주인").
"""

import streamlit as st

CSS = """
<style>
.stApp { font-family:"Pretendard","Noto Sans KR","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif; }
.block-container { padding-top:1.6rem; padding-bottom:3rem; max-width:1560px; }
[data-testid="stHeader"] { background:transparent; }

/* 머리글 */
.app-eyebrow { font-size:.7rem; font-weight:700; letter-spacing:.16em; color:#6366f1; margin-bottom:-.6rem; }
.stApp h1 { font-size:1.6rem !important; font-weight:800 !important; letter-spacing:-.02em; padding:.2rem 0 0 !important; }
[data-testid="stCaptionContainer"] { font-size:.8rem; }

/* 탭: 글자끼리 붙어 보이지 않게 탭마다 안쪽 여백과 사이 간격을 둔다 (11-17, T204) */
[data-testid="stTabs"] [role="tablist"] { gap:6px; border-bottom:1px solid rgba(148,163,184,.25); margin-bottom:1rem; }
[data-testid="stTab"] { padding:0 18px !important; border-radius:10px 10px 0 0; transition:background-color .15s; }
[data-testid="stTab"]:hover { background-color:rgba(148,163,184,.10); }
[data-testid="stTab"][aria-selected="true"] { background-color:rgba(99,102,241,.10); }
[data-testid="stTab"] p { font-size:.95rem; }
[data-testid="stTab"][aria-selected="true"], [data-testid="stTab"][aria-selected="true"] p { color:#6366f1 !important; font-weight:700; }
[data-testid="stTabs"] .react-aria-SelectionIndicator { background-color:#6366f1 !important; border-color:#6366f1 !important; }

/* 주 버튼 */
.stButton button[kind="primary"] { background:#4f46e5; border-color:#4f46e5; font-weight:700; border-radius:10px; min-height:2.6rem; }
.stButton button[kind="primary"]:hover { background:#4338ca; border-color:#4338ca; }

/* 고른 것의 강조색: Streamlit 기본 빨강 대신 indigo (테마 설정은 공통 틀이라 여기서 덧입힌다) */
[data-testid="stButtonGroup"] button[aria-pressed="true"], [data-testid="stButtonGroup"] button[aria-pressed="true"] * {
  border-color:#6366f1 !important; background-color:rgba(99,102,241,.14) !important; color:#6366f1 !important; }
[data-testid="stButtonGroup"] button[aria-pressed="true"] * { background-color:transparent !important; }
[data-testid="stSlider"] [role="slider"] { background:#4f46e5; }

/* 지우는 버튼이 두 개로 보이지 않게 한다 (11-17, T204). 페르소나는 이름표마다 있는 × 로 빼고,
   계절(달)은 "정하지 않음"을 고른다. 그래서 칸 오른쪽의 "전부 지우기"·"값 지우기" 버튼은 숨긴다. */
[data-testid="stMultiSelect"] button[aria-label="Clear all"],
[data-testid="stSelectbox"] button[aria-label="Clear value"] { display:none !important; }

/* 페르소나 고르기: 이름이 길어도 잘리지 않게 태그가 줄을 바꾼다 */
[data-testid="stMultiSelect"] span[data-tag] { background:#4f46e5; font-size:13px; max-width:100% !important; height:auto !important;
  padding-top:3px; padding-bottom:3px; white-space:normal !important; }
[data-testid="stMultiSelect"] span[data-tag] span { white-space:normal !important; overflow:visible !important; text-overflow:clip !important; max-width:none !important; }

/* 왼쪽 변수 패널. 창이 좁아도 페르소나 이름표가 접히지 않을 만큼의 폭은 지킨다 (T204) */
[data-testid="stColumn"]:has(.st-key-sim_panel) { min-width:270px; }
.st-key-sim_panel { border-radius:14px !important; background:rgba(148,163,184,.05); }
.st-key-sim_panel [data-testid="stVerticalBlock"] { gap:.55rem; }
.st-key-sim_panel [data-testid="stWidgetLabel"] p { font-size:.8rem; opacity:.75; }
.sim-panel-title { font-size:1.02rem; font-weight:800; letter-spacing:-.01em; }
.sim-sec { display:flex; align-items:center; gap:8px; font-size:.8rem; font-weight:700;
  margin-top:.35rem; padding-top:.7rem; border-top:1px solid rgba(148,163,184,.25); }
.sim-sec span { display:inline-flex; align-items:center; justify-content:center; width:18px; height:18px; border-radius:5px;
  background:rgba(99,102,241,.14); color:#6366f1; font-size:.68rem; font-weight:800; }

/* 오른쪽 위: 지금 고른 것 */
.sim-chips { display:flex; flex-wrap:wrap; gap:8px; }
.sim-chip { display:inline-flex; align-items:center; gap:8px; font-size:.84rem; padding:5px 12px 5px 6px; border-radius:10px;
  border:1px solid rgba(148,163,184,.3); background:rgba(148,163,184,.06); }
.sim-chip b { font-size:.7rem; font-weight:800; padding:2px 8px; border-radius:6px; }
.sim-chip.base b { background:rgba(100,116,139,.18); }
.sim-chip.var b { background:rgba(99,102,241,.16); color:#6366f1; }

/* 고른 페르소나와 결과가 없을 때. 카드는 이름 한 줄, 설명 한 줄로 두고 넘치면 … 로 줄인다 (전체는 마우스를 올리면 보인다, T204) */
.sim-personas { display:grid; grid-template-columns:repeat(auto-fill,minmax(min(100%,340px),1fr)); gap:8px; margin:.25rem 0 .75rem; }
.sim-persona .tx { min-width:0; }
.sim-persona .nm, .sim-persona .ln { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.sim-persona { display:flex; gap:10px; align-items:center; padding:10px 12px; border-radius:12px;
  border:1px solid rgba(148,163,184,.3); background:rgba(148,163,184,.05); }
.sim-persona .ic { width:38px; height:38px; flex:none; border-radius:10px; display:flex; align-items:center; justify-content:center; background:rgba(99,102,241,.14); }
.sim-persona .nm { font-weight:700; font-size:.9rem; } .sim-persona .ln { font-size:.76rem; opacity:.65; }
.sim-empty { border:1.5px dashed rgba(148,163,184,.4); border-radius:14px; padding:36px 24px; text-align:center; }
.sim-empty .t { font-weight:700; font-size:1rem; } .sim-empty .s { font-size:.86rem; opacity:.65; margin-top:4px; }

/* 접는 칸 */
[data-testid="stExpander"] details { border-radius:12px; }
[data-testid="stExpander"] summary p { font-size:.88rem; font-weight:600; }
</style>
"""


def inject() -> None:
    st.html(CSS)


HEADER_NOTE = (
    "시뮬레이션이 낸 금액은 모두 가상 값입니다. 실제 매출이나 실제 구매율이 아닙니다. "
    "근거 보기의 공식 가격은 출처가 있는 공개 가격입니다."
)


def header() -> None:
    """머리글. 제목과 "가상" 안내는 테스트가 보는 Streamlit 요소(제목, 첫 캡션) 그대로 둔다 (tests/test_app.py)."""
    st.html('<div class="app-eyebrow">WALKERHILL DINING · PERSONA SIMULATOR</div>')
    st.title("워커힐 다이닝 페르소나 시뮬레이터")
    # 공식 가격은 출처가 있는 실제 공개 가격이라 "가상"이 아니다. "가상"은 시뮬레이션이 낸 금액에만 붙인다 (11-18 팀장 회신, PR 174)
    st.caption(HEADER_NOTE)
