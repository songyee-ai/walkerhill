"""간편 시뮬레이터 화면 (T202): 왼쪽 변수 패널(자료 → 누가 → 언제 → 적용할 변수)과 오른쪽 결과(기본 시나리오 대비 변수 적용 후).

전문 설정(실행 폴더, 프롬프트 같은 것)은 "실행 하나 자세히 보기" 탭에 두고, 여기서는 고르기만 하면 돌아가게 한다.
돌리는 것은 app/runs.py 의 `simulate` (README 와 같은 엔진 명령), 견주는 것은 app/compare.py, 식당가 카드는 app/board.py 다.
"""

import json
from dataclasses import dataclass
from html import escape
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from app.board import WALKERHILL_NAMES, pct_change, venue_cards
from app.compare import Comparison, compare, summary_groups
from app.icons import as_img, persona_icon
from app.results import load_run, visit_view, won
from app.runs import (
    EXAMPLE_VENUES,
    choices,
    data_roots,
    has_private_summary,
    key_ready,
    make_example_copy,
    simulate,
)
from app.scenario_builder import (
    DAY_TYPES,
    MENU_SLOTS,
    UI_PREFIX,
    competitor_discount,
    our_limited_menu,
    our_price,
    write_scenario,
)
from app.street import AFTER_LABEL, BASE_LABEL, render_scene, scene_from_comparison
from app.validation import LIMITS_SOURCE, VALIDATION_LIMITS, limits_not_in, load_validation, validation_rows
from engine.formats import KO

# 엔진이 아직 받지 않는 요소. 고를 수는 있지만 결과에는 들어가지 않는다고 분명히 알린다.
# 엔진(팀장)과 프롬프트(borigunbbang)가 받게 되면 여기서 빼고 엔진 명령에 넘긴다. (docs/PROGRESS.md "알릴 것" 11-16)
SEASONS = ["정하지 않음", "봄 (3~5월)", "여름 (6~8월)", "가을 (9~11월)", "겨울 (12~2월)"]
WEATHERS = ["정하지 않음", "맑음", "비", "눈", "폭염", "한파"]
PENDING_NOTE = "엔진이 아직 이 값을 받지 않아 결과에는 반영되지 않습니다. 엔진과 프롬프트 담당께 요청해 두었습니다."

CHANGE_KINDS = ["준비된 상황", "경쟁 호텔이 할인한다", "우리 가격을 바꾼다", "우리 한정 메뉴를 더한다"]

# 화면의 "언제" → 방문 조건 묶음의 (이용 상황, 끼니)
WHEN_TO_CONDITION = {"점심": ("meal", "lunch"), "저녁": ("meal", "dinner"), "디저트·차": ("dessert", None), "포장·구매": ("takeout", None)}
DAY_TO_CODE = {"평일": "weekday", "주말": "weekend"}


@dataclass
class VenueInfo:
    venue_id: str
    name: str
    is_competitor: bool
    occasions: tuple[str, ...] = ()
    cuisine: str = ""


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def venue_catalog(root: Path) -> dict[str, VenueInfo]:
    catalog = {}
    for path in sorted((root / "data" / "venues").glob("*.json")):
        data = _read(path)
        if data.get("venue_id"):
            catalog[data["venue_id"]] = VenueInfo(
                data["venue_id"],
                data.get("name", path.stem),
                bool(data.get("is_competitor")),
                tuple(data.get("occasions", [])),
                data.get("cuisine", ""),
            )
    return catalog


def persona_cards(root: Path) -> list[dict]:
    """페르소나 정의(공개 층)에서 카드에 보일 것만 읽는다."""
    cards = []
    for path in sorted((root / "personas").glob("*.json")):
        data = _read(path)
        if not data.get("persona_id"):
            continue
        visit = data.get("visit") or {}
        party = (visit.get("party") or {}).get("label", "")
        budget = data.get("budget") or {}
        basis = "1인" if budget.get("basis") == "per_person" else "일행"
        money = f"{basis} 보통 {won(budget['typical'])}" if isinstance(budget.get("typical"), int) else ""
        cards.append(
            {
                "id": data["persona_id"],
                "name": data.get("name", data["persona_id"]),
                "group": data.get("customer_group", ""),
                "line": " · ".join(part for part in (party, ", ".join(visit.get("purposes", [])), money) if part),
            }
        )
    return cards


def conditions_for(root: Path, days: list[str], whens: list[str]) -> list[str]:
    """고른 요일과 때에 맞는 방문 조건 묶음의 condition_id."""
    bundle = _read(root / "engine" / "conditions.json")
    wanted_days = {DAY_TO_CODE[d] for d in days}
    wanted = {WHEN_TO_CONDITION[w] for w in whens}
    return [
        c["condition_id"]
        for c in bundle.get("conditions", [])
        if c.get("day_type") in wanted_days and (c.get("occasion"), c.get("meal")) in wanted
    ]


def menu_slots_for(occasions: tuple[str, ...]) -> list[str]:
    """한정 메뉴를 팔 수 있는 때: 그 업장의 이용 상황(occasions)에 드는 것만."""
    return [label for label, (occasion, _) in MENU_SLOTS.items() if occasion in occasions]


def prepared_scenarios(root: Path) -> dict[str, str]:
    """사람이 만들어 둔 상황 (기준과 화면이 만든 `ui-` 파일은 뺀다). scenario_id → 이름."""
    found = {}
    for path in sorted((root / "scenarios").glob("*.json")):
        data = _read(path)
        scenario_id = data.get("scenario_id", "")
        if scenario_id and scenario_id != "baseline" and not scenario_id.startswith(UI_PREFIX):
            found[scenario_id] = data.get("name", scenario_id)
    return found


@dataclass
class Inputs:
    """왼쪽 변수 패널에서 고른 것."""

    root: object
    catalog: dict
    allowed: list[str]
    cards: list[dict]
    personas: list[str]
    days: list[str]
    whens: list[str]
    condition_ids: list[str]
    season: str
    weather: str
    scenario: object
    scenario_id: str | None
    data_mode: str
    call_llm: bool
    go: bool
    missing: list[str]

    @property
    def problems(self) -> list[str]:
        found = []
        if not self.personas:
            found.append("페르소나를 한 명 이상 고르세요")
        if not self.condition_ids:
            found.append("요일과 때를 하나 이상 고르세요")
        if self.scenario_id is None:
            found.append("적용할 변수를 고르세요")
        return found


def _section(number: int, title: str) -> None:
    st.html(f'<div class="sim-sec"><span>{number}</span>{title}</div>')


def variable_panel(repo_root: Path) -> Inputs:
    """화면 왼쪽의 변수 패널. 위에서 아래로 고르고 맨 아래 버튼을 누른다."""
    st.html('<div class="sim-panel-title">변수 설정</div>')

    _section(1, "자료")
    roots = data_roots(repo_root)
    repo_missing = choices(roots[0].path).missing
    root = st.radio(
        "자료",
        roots,
        index=1 if repo_missing else 0,
        format_func=lambda r: "예시로 연습" if r.is_example else "팀 자료",
        horizontal=True,
        key="sim_root",
        label_visibility="collapsed",
    )
    if root.is_example:
        make_example_copy(repo_root)
    found = choices(root.path)
    catalog = venue_catalog(root.path) if not found.missing else {}
    allowed = [v for v in EXAMPLE_VENUES if v in catalog] if root.is_example else list(catalog)
    cards = persona_cards(root.path) if not found.missing else []

    _section(2, "누가")
    names = {c["id"]: c["name"] for c in cards}
    default = ["family-elders"] if root.is_example and "family-elders" in names else list(names)
    personas = st.multiselect(
        "페르소나",
        list(names),
        default=default,
        format_func=lambda i: names[i],
        placeholder="페르소나를 고르세요",
        key=f"sim_personas_{root.is_example}",
        label_visibility="collapsed",
        disabled=not cards,
    )

    _section(3, "언제")
    days = st.pills("요일", list(DAY_TO_CODE), selection_mode="multi", default=["주말"], key="sim_days") or []
    whens = st.pills("때", list(WHEN_TO_CONDITION), selection_mode="multi", default=["저녁"], key="sim_whens") or []
    left, right = st.columns(2)
    season = left.selectbox("계절", SEASONS, key="sim_season")
    weather = right.selectbox("날씨", WEATHERS, key="sim_weather")
    if season != SEASONS[0] or weather != WEATHERS[0]:
        st.caption(f"계절·날씨: {PENDING_NOTE}")

    _section(4, "적용할 변수")
    change = st.selectbox("변수 종류", CHANGE_KINDS, key="sim_change")
    scenario = None
    scenario_id = None
    first_day = list(DAY_TYPES)[0]
    if not catalog:
        pass
    elif change == "준비된 상황":
        prepared = prepared_scenarios(root.path)
        if prepared:
            scenario_id = st.selectbox("상황", list(prepared), format_func=lambda s: prepared[s], key="sim_prepared")
        else:
            st.info("준비된 상황이 아직 없습니다. 다른 변수를 골라 직접 만들어 보세요.")
    elif change == "경쟁 호텔이 할인한다":
        rivals = [v for v in allowed if catalog[v].is_competitor]
        if rivals:
            venue_id = st.selectbox("경쟁 업장", rivals, format_func=lambda v: catalog[v].name, key="sim_rival")
            pct = st.number_input("할인율 (%)", 5, 50, 20, 5, key="sim_disc")
            when = st.segmented_control("언제 할인", list(DAY_TYPES), default=first_day, key="sim_disc_day")
            scenario = competitor_discount(venue_id, catalog[venue_id].name, int(pct), DAY_TYPES[when or first_day])
    else:
        ours = [v for v in allowed if not catalog[v].is_competitor]
        venue_id = st.selectbox("워커힐 업장", ours, format_func=lambda v: catalog[v].name, key="sim_ours") if ours else None
        if venue_id and change == "우리 가격을 바꾼다":
            pct = st.number_input("가격 변화 (%, 내리면 음수)", -30, 30, 10, 5, key="sim_price")
            if pct != 0:
                scenario = our_price(venue_id, catalog[venue_id].name, int(pct))
        elif venue_id:
            menu = st.text_input("한정 메뉴 이름", "겨울 한정 코스", key="sim_menu")
            price = st.number_input("1인 가격 (원, 가상)", 10000, 1000000, 120000, 10000, key="sim_menu_price")
            # 업장이 하는 이용 상황의 때만 고른다 (식사만 하는 업장에 디저트 메뉴를 더하면 엔진이 받지 않는다).
            slots = menu_slots_for(catalog[venue_id].occasions)
            when = st.segmented_control("파는 때", slots, default=slots[0], key="sim_menu_when") if slots else None
            day = st.segmented_control("파는 요일", list(DAY_TYPES), default=first_day, key="sim_menu_day")
            if not slots:
                st.info("이 업장의 이용 상황을 알 수 없어 한정 메뉴를 더할 수 없습니다.")
            elif menu.strip() and when:
                scenario = our_limited_menu(venue_id, catalog[venue_id].name, menu.strip(), int(price), when, DAY_TYPES[day or first_day])
    if scenario is not None:
        scenario_id = scenario.scenario_id

    condition_ids = conditions_for(root.path, days, whens) if catalog else []
    ready = key_ready(repo_root)
    with st.expander("고급 설정"):
        modes = ["sample"] + (["private"] if has_private_summary(root.path) else [])
        data_mode = st.radio("값", modes, format_func=lambda m: {"sample": "가상 예시 값", "private": "기본 데이터 (이 PC 에만)"}[m], key="sim_mode")
        call_llm = st.checkbox("AI 를 새로 부르기 (키 필요, 처음 해 보는 조합에 필요)", value=False, disabled=not ready, key="sim_llm")
        if not ready:
            st.caption("이 PC 에는 키가 없어 저장된 답만 재생합니다. 처음 해 보는 조합은 '견줄 수 없음'으로 나옵니다.")
        st.caption(f"고른 방문 조건: {', '.join(condition_ids) or '없음'} · 업장: {', '.join(allowed) if root.is_example else '모두'}")

    go = st.button(f"{BASE_LABEL}와 비교하기", type="primary", key="sim_go", width="stretch", disabled=bool(found.missing))
    return Inputs(
        root, catalog, allowed, cards, personas, days, whens, condition_ids, season, weather,
        scenario, scenario_id, data_mode, call_llm, go, list(found.missing),
    )  # fmt: skip


def _chips(inputs: Inputs) -> str:
    names = {c["id"]: c["name"] for c in inputs.cards}
    when = " · ".join(inputs.days + inputs.whens) or "요일·때 없음"
    who = ", ".join(names.get(p, p) for p in inputs.personas) or "페르소나 없음"
    if inputs.scenario is not None:
        change = inputs.scenario.name
    elif inputs.scenario_id:
        change = prepared_scenarios(inputs.root.path).get(inputs.scenario_id, inputs.scenario_id)
    else:
        change = "변수 없음"
    return (
        '<div class="sim-chips">'
        f'<span class="sim-chip base"><b>{BASE_LABEL}</b>{escape(who)} · {escape(when)}</span>'
        f'<span class="sim-chip var"><b>{AFTER_LABEL}</b>{escape(change)}</span></div>'
    )


def _persona_strip(inputs: Inputs) -> str:
    chosen = [c for c in inputs.cards if c["id"] in inputs.personas]
    items = "".join(
        f'<div class="sim-persona"><div class="ic">{as_img(persona_icon(c["name"], 30), "#6366f1", 30)}</div>'
        f'<div><div class="nm">{escape(c["name"])}</div><div class="ln">{escape(c["group"])} · {escape(c["line"])}</div></div></div>'
        for c in chosen
    )
    return f'<div class="sim-personas">{items}</div>' if items else ""


def render(repo_root: Path) -> None:
    panel, main = st.columns([1.3, 2.7], gap="medium")
    with panel, st.container(border=True, key="sim_panel"):
        inputs = variable_panel(repo_root)

    with main:
        if inputs.missing:
            st.warning(
                "팀 자료에 아직 없는 것이 있어 돌릴 수 없습니다: "
                + ", ".join(inputs.missing)
                + ". 페르소나와 프롬프트가 올라오면 바로 돌아갑니다. 그동안은 왼쪽에서 '예시로 연습'을 고르세요."
            )
            return
        st.html(_chips(inputs))
        if inputs.go:
            if inputs.problems:
                st.error(" · ".join(inputs.problems))
            else:
                if inputs.scenario is not None:
                    write_scenario(inputs.root.path, inputs.scenario)
                with st.spinner(f"{BASE_LABEL}와 {AFTER_LABEL}를 차례로 돌리는 중입니다…"):
                    result = simulate(
                        inputs.root.path,
                        repo_root,
                        inputs.data_mode,
                        inputs.scenario_id,
                        inputs.personas,
                        inputs.condition_ids,
                        list(inputs.allowed) if inputs.root.is_example else [],
                        inputs.call_llm,
                        is_example=inputs.root.is_example,
                    )
                st.session_state["sim_result"] = (
                    result, inputs.root.path, inputs.data_mode, inputs.season, inputs.weather, list(inputs.allowed),
                )  # fmt: skip

        saved = st.session_state.get("sim_result")
        if saved is None:
            st.html(
                _persona_strip(inputs) + '<div class="sim-empty"><div class="t">아직 돌린 결과가 없습니다</div>'
                f'<div class="s">왼쪽 패널에서 페르소나, 요일·때, 적용할 변수를 고르고 <b>{BASE_LABEL}와 비교하기</b>를 누르세요.</div></div>'
            )
            return
        show_result(saved)


def show_result(saved: tuple) -> None:
    result, sim_root, sim_mode, sim_season, sim_weather, sim_allowed = saved
    # 엔진이 남긴 말은 고쳐 쓰지 않고 그대로 보여 준다 (팀장 요청, 11-16).
    outputs = [(BASE_LABEL, result.baseline)] + ([(AFTER_LABEL, result.scenario)] if result.scenario else [])
    failed = not result.ok or any(o.exit_code != 0 for _, o in outputs)
    if not result.ok:
        st.error("비교할 결과를 만들지 못했습니다. 아래 '엔진이 남긴 말'을 보세요.")
    if sim_season != SEASONS[0] or sim_weather != WEATHERS[0]:
        st.info(f"고른 계절·날씨({sim_season}, {sim_weather}): {PENDING_NOTE}")
    if result.ok:
        comparison = compare(load_run(result.baseline.run_dir), load_run(result.scenario.run_dir), summary_groups(sim_root, sim_mode))
        show_comparison(comparison, venue_catalog(sim_root), scenario_name(sim_root, comparison.scen.record.scenario_id), sim_allowed)
    with st.expander("엔진이 남긴 말", expanded=failed):
        for label, outcome in outputs:
            run_id = f" · 실행 `{outcome.run_dir.name}`" if outcome.run_dir else ""
            st.markdown(f"**{label}**{run_id} — {outcome.meaning}")
            st.code(outcome.output or "(남긴 말 없음)", language=None)


# 결과 보기 (11-16 팀 결정: 지도 대신 식당가 카드와 페르소나로 행동 변화를 보여 준다)
MOVE_BADGE = {
    "out": ("red", "▼ 워커힐 밖으로"),
    "in": ("green", "▲ 워커힐로"),
    "inside": ("blue", "↔ 워커힐 안에서"),
    "other": ("violet", "↔ 밖에서 옮김"),
    "same": ("gray", "그대로"),
    "failed": ("orange", "견줄 수 없음"),
}


def badge(move: str) -> str:
    color, text = MOVE_BADGE[move]
    return f":{color}-badge[{text}]"


def show_comparison(
    comparison: Comparison, catalog: dict[str, VenueInfo], scenario_name: str = "", allowed: list[str] | None = None
) -> None:
    names = {v.venue_id: v.name for v in catalog.values()} | comparison.names
    record = comparison.scen.record

    # 식당가 그림: 페르소나가 기본 시나리오 → 변수 적용 후로 옮겨 가는 모습 (app/street.py)
    shown = [v for v in (allowed or list(catalog)) if v in catalog]
    scene = scene_from_comparison(
        comparison,
        names,
        {v.venue_id: v.cuisine for v in catalog.values()},
        [v for v in shown if not catalog[v].is_competitor],
        [v for v in shown if catalog[v].is_competitor],
        scenario_name or record.scenario_id,
    )
    html, height = render_scene(scene)
    components.html(html, height=height, scrolling=False)

    with st.expander("숫자와 카드로 자세히 보기"):
        _show_cards(comparison, catalog, names, allowed)
    # 검증 결과는 그 안에 접는 칸이 있어 위의 접는 칸 밖에 둔다 (접는 칸 안에 접는 칸은 둘 수 없다).
    if comparison.base.run_dir is not None:
        show_validation(comparison.base.run_dir, names)

    with st.expander("한 사람씩 자세히 보기"):
        _show_person(comparison)


def _show_cards(comparison: Comparison, catalog: dict[str, VenueInfo], names: dict[str, str], allowed: list[str] | None) -> None:
    # 한눈에: 워커힐 가상 매출과 옮긴 사람
    diff = comparison.total_after - comparison.total_before
    a, b, c = st.columns(3)
    a.metric(
        "워커힐 가상 매출",
        f"{comparison.total_after:,}원",
        delta=f"{diff:+,}원 ({pct_change(comparison.total_before, comparison.total_after)})" if diff else "변화 없음",
        delta_color="normal" if diff else "off",
        help=f"{BASE_LABEL} {won(comparison.total_before)} → {AFTER_LABEL} {won(comparison.total_after)}",
    )
    b.metric("워커힐 밖으로 나간 방문", f"{comparison.count('out')}건", delta=-comparison.count("out") or None)
    c.metric("워커힐로 들어온 방문", f"{comparison.count('in')}건", delta=comparison.count("in") or None)

    changed = [m for m in comparison.moves if m.move not in ("same", "failed")]
    if not changed:
        st.info(f"{BASE_LABEL}와 선택이 같습니다. 이 변수로는 고른 페르소나의 선택이 바뀌지 않았습니다.")
    unknown = [m for m in comparison.moves if m.move == "failed"]
    if unknown:
        st.warning(
            f"견줄 수 없는 방문이 {len(unknown)}건 있습니다. 대개 처음 해 보는 조합이라 저장된 답이 없어서입니다 "
            "(키가 있는 PC 에서 'AI 를 새로 부르기'로 돌리면 생깁니다)."
        )

    # 페르소나: 사람마다 기본 시나리오 → 변수 적용 후
    st.markdown("#### 페르소나는 어떻게 움직였나")
    for move in sorted(comparison.moves, key=lambda m: list(MOVE_BADGE).index(m.move)):
        with st.container(border=True):
            st.markdown(
                f"{badge(move.move)} **{move.persona}** · {move.condition}  \n"
                f"{_place(move.before, names)} → **{_place(move.after, names)}**"
            )
            if move.reason_after or move.fail_reason:
                st.caption(move.reason_after or move.fail_reason)

    # 식당가: 식당마다 매출과 손님의 변화
    st.markdown("#### 식당가는 어떻게 바뀌었나")
    always = [v for v in (allowed or list(catalog)) if v in catalog and not catalog[v].is_competitor]
    cards = venue_cards(comparison, names, always)
    columns = st.columns(3)
    for i, card in enumerate(cards):
        with columns[i % 3].container(border=True):
            st.markdown(f"**{card.name}**  \n:small[{card.kind_label}]")
            if card.revenue_before is not None:
                change = card.revenue_after - card.revenue_before
                st.metric(
                    "가상 매출",
                    f"{card.revenue_after:,}원",
                    delta=f"{change:+,}원 ({pct_change(card.revenue_before, card.revenue_after)})" if change else "변화 없음",
                    delta_color="normal" if change else "off",
                )
            else:
                change = card.guests_after - card.guests_before
                st.metric(
                    "손님 수 (가상)",
                    f"{card.guests_after:,.0f}명",
                    delta=f"{change:+,.0f}명" if change else "변화 없음",
                    delta_color="normal" if change else "off",
                )
            lines = [f":green-badge[▲ 새로 옴] {m.persona} (← {_place(m.before, names)})" for m in card.arrived]
            lines += [f":red-badge[▼ 떠남] {m.persona} (→ {_place(m.after, names)})" for m in card.left]
            lines += [f":gray-badge[그대로] {m.persona}" for m in card.stayed]
            st.markdown("  \n".join(lines) if lines else ":small[고른 페르소나 중 온 사람 없음]")
    if comparison.uncovered_groups:
        st.caption("다루지 않은 고객군 (페르소나가 없어 이 비교에 들지 않음): " + ", ".join(comparison.uncovered_groups))


def _show_person(comparison: Comparison) -> None:
    options = [(m.persona_id, m.condition_id) for m in comparison.moves]
    labels = {(m.persona_id, m.condition_id): f"{m.persona} · {m.condition}" for m in comparison.moves}
    pick = st.selectbox("방문", options, format_func=lambda o: labels[o], key="sim_detail")
    left, right = st.columns(2)
    for column, title, run in ((left, BASE_LABEL, comparison.base), (right, AFTER_LABEL, comparison.scen)):
        with column:
            st.markdown(f"**{title}**")
            view = visit_view(run, *pick)
            if view.failed_reason or not view.found:
                st.write(f"견줄 수 없음: {view.failed_reason or '방문이 없음'}")
                continue
            st.write(f"{view.venue or KO['choice_kind']['none']} — {won(view.total_paid)}")
            st.write(view.reason_text or "")
            for item in view.not_chosen:
                st.caption(f"고르지 않음: {item.venue} — {item.text}")


def _place(place, names: dict[str, str]) -> str:
    if place.kind == "none":
        return KO["choice_kind"]["none"]
    if place.kind == "failed":
        return "견줄 수 없음"
    return names.get(place.venue_id or "", place.venue_id or "")


def show_validation(run_dir: Path, names: dict[str, str]) -> None:
    """검증 결과가 있는 실행이면 업장별 검증 건수와 한계를 함께 보여 준다 (app/validation.py)."""
    try:
        validation = load_validation(run_dir)
    except (OSError, ValueError) as error:
        st.warning(f"검증 결과를 읽지 못했습니다: {error}")
        return
    if validation is None:
        return
    names = WALKERHILL_NAMES | names
    with st.expander("검증 결과 (떼어 둔 후기로 잰 것)", expanded=True):
        st.caption(f"값은 비율이 아니라 건수입니다. {validation.min_reviews}건 미만인 업장은 일치 건수를 말하지 않습니다.")
        st.dataframe(validation_rows(validation, names), hide_index=True)
        for venue_id in limits_not_in(validation):
            st.caption(f"{names.get(venue_id, venue_id)} (이 결과에 없음) 한계: {VALIDATION_LIMITS[venue_id]}")
        st.caption(f"한계의 출처: {LIMITS_SOURCE}")


def scenario_name(root: Path, scenario_id: str) -> str:
    return _read(root / "scenarios" / f"{scenario_id}.json").get("name", scenario_id)
