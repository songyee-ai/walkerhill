"""화면: 조건 입력과 실행 결과 (T09).

엔진이 쓴 실행 폴더를 읽어, 고른 페르소나와 방문 조건의 결과를 보여 준다. 키와 기본 데이터가 없어도 돈다
(실행 폴더가 하나도 없으면 저장소의 예시 실행을 보여 준다). 무엇을 보여 줄지는 app/results.py 가 정한다.

띄우는 법 (저장소 맨 위에서):

    uv run python -m streamlit run app/main.py
"""

import sys
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
# Streamlit 은 이 파일의 폴더(app/)만 경로에 넣는다. `import app.results` 가 되게 저장소 맨 위를 넣는다.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.results import (  # noqa: E402
    RunSource,
    condition_names,
    list_runs,
    load_run,
    party_label,
    persona_names,
    run_notices,
    run_sources,
    visit_table,
    visit_view,
    won,
)
from engine.formats import KO  # noqa: E402


def money_table(rows: list[dict]) -> None:
    """표를 그린다. 금액 열("…원)"으로 끝나는 열)에는 천 단위 쉼표를 넣는다."""
    money = {key: st.column_config.NumberColumn(format="localized") for key in (rows[0] if rows else {}) if key.endswith("원)")}
    st.dataframe(rows, hide_index=True, column_config=money)


st.set_page_config(page_title="워커힐 다이닝 페르소나 시뮬레이터", layout="wide")
st.title("워커힐 다이닝 페르소나 시뮬레이터")
st.caption("화면의 모든 금액은 가상 값입니다. 실제 매출이나 실제 구매율이 아닙니다.")

# ── 조건 입력 ──────────────────────────────────────────────
st.sidebar.header("조건 고르기")
sources = run_sources(REPO_ROOT)
other = st.sidebar.text_input(
    "다른 실행 폴더 (선택)",
    help="엔진을 --root 로 다른 곳에서 돌렸으면 그 아래의 engine/samples/runs 나 private/runs 경로를 적습니다.",
)
if other.strip():
    folder = Path(other.strip())
    folder = folder if folder.is_absolute() else REPO_ROOT / folder
    if list_runs(folder):
        sources.insert(0, RunSource(f"직접 적은 폴더 ({other.strip()})", folder))
    else:
        st.sidebar.warning("그 폴더에서 실행을 찾지 못했습니다. run.json 이 든 실행 폴더들의 상위 폴더를 적어 주세요.")

if not sources:
    st.error("보여 줄 실행이 없습니다. 저장소의 예시 파일(tests/fixtures/example)이 있는지 확인해 주세요.")
    st.stop()

source = st.sidebar.selectbox("결과를 읽을 곳", sources, format_func=lambda s: s.label)
run_ids = list_runs(source.folder)
run_id = st.sidebar.selectbox("실행 (새것이 위)", run_ids)

try:
    run = load_run(source.folder / run_id)
except (OSError, ValueError) as error:
    st.error(f"실행 `{run_id}` 를 읽지 못했습니다. 형식이 바뀌기 전에 돌린 실행이면 엔진으로 다시 돌려 주세요.\n\n{error}")
    st.stop()

record = run.record
personas = persona_names(run)
conditions = condition_names(run)
persona_id = st.sidebar.selectbox("페르소나", record.persona_ids, format_func=lambda p: personas[p])
condition_id = st.sidebar.selectbox("방문 조건", record.condition_ids, format_func=lambda c: conditions[c])

# ── 실행 정보 ──────────────────────────────────────────────
scenario = "기준 상황" if record.scenario_id == "baseline" else f"상황 `{record.scenario_id}`"
st.markdown(
    f"**{scenario}** · 실행 `{record.run_id}` · 모델 `{record.llm.model}` · 프롬프트 `{record.llm.prompt_version}` · "
    f"방문 {record.counts.visits}건"
)
for notice in run_notices(run):
    st.warning(notice)

# ── 실행 결과 ──────────────────────────────────────────────
view = visit_view(run, persona_id, condition_id)
st.header(f"{personas[persona_id]} · {conditions[condition_id]}")
if view.condition is not None:
    st.caption(party_label(view.condition))

if not view.found:
    st.info("이 실행에는 이 페르소나와 방문 조건의 방문이 없습니다 (호출 상한에 닿아 멈춘 실행일 수 있습니다).")
elif view.failed_reason:
    st.error(f"이 방문은 실패했습니다: {view.failed_reason}")
else:
    st.subheader("고른 곳")
    if view.choice_kind == "none":
        st.markdown(f"**{KO['choice_kind']['none']}**")
    else:
        st.markdown(f"**{view.venue}** — {view.venue_detail}")
        left, right = st.columns(2)
        left.metric("낸 금액 (가상)", won(view.total_paid))
        right.metric("워커힐 매출 (가상, 세금 뺀 값)", won(view.revenue_net))
        money_table(
            [
                {
                    "상품": line.product,
                    "수량": line.quantity,
                    "단위": line.unit,
                    "표시가 (가상, 원)": line.list_price,
                    "할인 (가상, 원)": line.discount,
                    "낸 금액 (가상, 원)": line.paid,
                }
                for line in view.lines
            ]
        )
        if view.counted_share < 1:
            st.caption(
                f"일부 달에만 파는 상품이라 이 방문의 {view.counted_share:.0%} 만 이 업장으로 셉니다. "
                "나머지는 이용하지 않음으로 셉니다."
            )

    st.subheader("고른 이유")
    if view.reason_labels:
        st.markdown(" ".join(f"`{label}`" for label in view.reason_labels))
    st.write(view.reason_text or "이유가 적혀 있지 않습니다.")
    if view.used_attributes:
        st.caption("판단에 쓴 페르소나 속성: " + ", ".join(view.used_attributes))
    if view.llm_call == "replay":
        st.caption("앞선 실행에서 저장한 응답을 재생한 결과입니다.")

    st.subheader("고르지 않은 업장")
    if view.not_chosen:
        money_table(
            [
                {
                    "업장": item.venue,
                    "구분": item.kind,
                    "가장 싼 주문 (가상, 원)": item.cheapest,
                    "걸린 점": ", ".join(item.pain_labels),
                    "고르지 않은 이유": item.text,
                }
                for item in view.not_chosen
            ]
        )
    else:
        st.write("다른 후보가 없었습니다.")

with st.expander("이 실행의 모든 방문", expanded=False):
    money_table(visit_table(run))
