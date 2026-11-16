"""화면: 조건 입력과 실행 결과 (T09).

1. 돌리기 — 조건을 골라 엔진을 돌린다 (app/runs.py. README 와 같은 `python -m engine` 명령이다).
2. 결과 보기 — 엔진이 쓴 실행 폴더를 읽어, 고른 페르소나와 방문 조건의 결과를 보여 준다 (app/results.py).
키와 기본 데이터가 없어도 돈다 (저장된 답을 재생하고, 실행 폴더가 없으면 저장소의 예시 실행을 보여 준다).

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

from app import simulator, style  # noqa: E402
from app.compare import venue_names  # noqa: E402
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
from app.runs import (  # noqa: E402
    EXAMPLE_VENUES,
    choices,
    data_roots,
    engine_command,
    has_private_summary,
    key_ready,
    make_example_copy,
    replay_env,
    run_engine,
)
from engine.formats import KO  # noqa: E402


def money_table(rows: list[dict]) -> None:
    """표를 그린다. 금액 열("…원)"으로 끝나는 열)에는 천 단위 쉼표를 넣는다."""
    money = {key: st.column_config.NumberColumn(format="localized") for key in (rows[0] if rows else {}) if key.endswith("원)")}
    st.dataframe(rows, hide_index=True, column_config=money)


st.set_page_config(page_title="워커힐 다이닝 페르소나 시뮬레이터", layout="wide")
style.inject()
style.header()

def run_panel() -> None:
    """1. 돌리기 — 조건을 골라 엔진을 돌린다. 끝나면 새 실행을 2. 결과 보기에서 고른 상태로 다시 그린다."""
    st.subheader("1. 돌리기")
    with st.expander("조건을 골라 새로 돌리기", expanded=False):
        roots = data_roots(REPO_ROOT)
        root = st.radio("돌릴 자료", roots, format_func=lambda r: r.label, key="run_root")
        if root.is_example and not root.path.exists():
            st.info("예시 사본이 아직 없습니다. 예시 파일을 깃이 무시하는 private/ 에 베껴 씁니다.")
            if st.button("예시 사본 만들기"):
                make_example_copy(REPO_ROOT)
                st.rerun()
            return

        found = choices(root.path)
        if found.missing:
            st.warning("아직 없는 것이 있어 돌릴 수 없습니다:\n\n" + "\n".join(f"- {name}" for name in found.missing))
            st.caption("예시 사본으로는 지금도 연습할 수 있습니다.")
            return

        modes = ["sample"] + (["private"] if has_private_summary(root.path) else [])
        data_mode = st.radio(
            "값", modes, format_func=lambda m: {"sample": "가상 예시 값", "private": "기본 데이터 (이 PC 에만)"}[m], key="run_mode"
        )
        scenarios = sorted(found.scenarios, key=lambda s: (s != "baseline", s))
        scenario_id = st.selectbox("상황", scenarios, key="run_scenario")
        prompt = st.selectbox("프롬프트", found.prompts, index=found.prompts.index("p1") if "p1" in found.prompts else 0)
        persona_ids: list[str] = []
        condition_ids: list[str] = []
        if scenario_id == "baseline":
            persona_ids = st.multiselect(
                "페르소나 (비우면 모두)", found.personas, default=["family-elders"] if root.is_example else []
            )
            condition_ids = st.multiselect(
                "방문 조건 (비우면 모두)", found.conditions, default=["meal-dinner-weekend"] if root.is_example else []
            )
        else:
            st.caption("기준이 아닌 상황은 가장 새 기준 실행의 페르소나와 방문 조건으로 돕니다. 기준 상황을 먼저 돌려 두세요.")
        venue_default = [v for v in EXAMPLE_VENUES if v in found.venues] if root.is_example else []
        venue_ids = st.multiselect(
            "업장 (비우면 모두)",
            found.venues,
            default=venue_default,
            help="기준 상황을 일부 업장으로 돌렸으면 다른 상황도 같은 업장으로 돌립니다. 예시의 저장된 답은 두 업장으로 받은 것입니다.",
        )
        ready = key_ready(REPO_ROOT)
        call_llm = st.checkbox(
            "AI 를 새로 부르기",
            value=False,
            disabled=not ready,
            help="끄면 앞서 저장된 답만 재생합니다 (키가 필요 없고 바로 끝납니다). 저장된 답이 없는 방문은 실패로 남습니다.",
        )
        if not ready:
            st.caption("이 PC 에 .env 의 키가 없어 저장된 답 재생으로만 돌립니다.")

        if st.button("돌리기", type="primary"):
            command = engine_command(
                root.path, REPO_ROOT, data_mode, scenario_id, prompt, persona_ids, condition_ids, venue_ids, call_llm
            )
            with st.spinner("엔진을 돌리는 중입니다…"):
                outcome = run_engine(command, REPO_ROOT, env_overrides=replay_env(root.is_example, call_llm))
            st.session_state["last_outcome"] = outcome
            if outcome.run_dir is not None:
                st.session_state["pick"] = (outcome.run_dir.parent, outcome.run_dir.name)
            st.rerun()


def show_last_outcome() -> None:
    """방금 돌린 결과를 화면 맨 위에 알린다."""
    outcome = st.session_state.get("last_outcome")
    if outcome is None:
        return
    if outcome.exit_code == 0:
        st.success(f"돌리기: {outcome.meaning} 아래에 새 실행을 열었습니다.")
    else:
        st.error(f"돌리기: {outcome.meaning}")
    with st.expander("엔진이 남긴 말", expanded=outcome.exit_code != 0):
        st.code(outcome.output or "(남긴 말 없음)", language=None)


def apply_pick(sources: list[RunSource]) -> None:
    """방금 돌린 실행을 결과 보기의 선택 칸에 넣는다. 선택 칸을 그리기 전에 불러야 한다."""
    pick = st.session_state.pop("pick", None)
    if pick is None:
        return
    folder, run_id = pick
    source = next((s for s in sources if s.folder.resolve() == Path(folder).resolve()), None)
    if source is not None:
        st.session_state["source"] = source
        st.session_state["run_id"] = run_id



def detail_view() -> None:
    """실행 하나 자세히 보기 (T09): 1. 돌리기, 2. 결과 보기."""
    run_panel()
    show_last_outcome()

    # ── 결과 보기 ──────────────────────────────────────────────
    st.subheader("2. 결과 보기")
    sources = run_sources(REPO_ROOT)
    other = st.text_input(
        "다른 실행 폴더 (선택)",
        key="other_folder",
        help="엔진을 --root 로 다른 곳에서 돌렸으면 그 아래의 engine/samples/runs 나 private/runs 경로를 적습니다.",
    )
    if other.strip():
        folder = Path(other.strip())
        folder = folder if folder.is_absolute() else REPO_ROOT / folder
        if list_runs(folder):
            typed = RunSource(f"직접 적은 폴더 ({other.strip()})", folder)
            sources.insert(0, typed)
            # 경로를 새로 적었으면 그 폴더를 고른 상태로 한다. 같은 경로면 사람이 고른 값을 그대로 둔다.
            if st.session_state.get("other_seen") != other.strip():
                st.session_state["other_seen"] = other.strip()
                st.session_state["source"] = typed
        else:
            st.warning("그 폴더에서 실행을 찾지 못했습니다. run.json 이 든 실행 폴더들의 상위 폴더를 적어 주세요.")

    if not sources:
        st.error("보여 줄 실행이 없습니다. 저장소의 예시 파일(tests/fixtures/example)이 있는지 확인해 주세요.")
        return

    apply_pick(sources)
    # 고른 값이 목록에서 사라졌으면(폴더를 지웠거나 출처를 바꿈) 처음 것으로 돌아간다.
    if st.session_state.get("source") not in sources:
        st.session_state.pop("source", None)
    source = st.selectbox("결과를 읽을 곳", sources, format_func=lambda s: s.label, key="source")
    run_ids = list_runs(source.folder)
    if st.session_state.get("run_id") not in run_ids:
        st.session_state.pop("run_id", None)
    run_id = st.selectbox("실행 (새것이 위)", run_ids, key="run_id")

    try:
        run = load_run(source.folder / run_id)
    except (OSError, ValueError) as error:
        st.error(f"실행 `{run_id}` 를 읽지 못했습니다. 형식이 바뀌기 전에 돌린 실행이면 엔진으로 다시 돌려 주세요.\n\n{error}")
        return

    record = run.record
    personas = persona_names(run)
    conditions = condition_names(run)
    persona_id = st.selectbox("페르소나", record.persona_ids, format_func=lambda p: personas[p])
    condition_id = st.selectbox("방문 조건", record.condition_ids, format_func=lambda c: conditions[c])

    # ── 실행 정보 ──────────────────────────────────────────────
    scenario = "기준 상황" if record.scenario_id == "baseline" else f"상황 `{record.scenario_id}`"
    st.markdown(
        f"**{scenario}** · 실행 `{record.run_id}` · 모델 `{record.llm.model}` · 프롬프트 `{record.llm.prompt_version}` · "
        f"방문 {record.counts.visits}건"
    )
    for notice in run_notices(run):
        st.warning(notice)
    simulator.show_validation(source.folder / run_id, venue_names(run))

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


tab_sim, tab_detail = st.tabs(["간편 시뮬레이터", "실행 하나 자세히 보기"])
with tab_sim:
    simulator.render(REPO_ROOT)
with tab_detail:
    detail_view()
