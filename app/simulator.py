"""시뮬레이터 탭 (T202, 11-17 T204 로 "간편 시뮬레이터"에서 이름을 바꿈): 왼쪽 변수 패널(자료 → 누가 → 언제 → 적용할 변수)과 오른쪽 결과(기본 시나리오 대비 변수 적용 후).

전문 설정(실행 폴더, 프롬프트 같은 것)은 "상세 분석" 탭에 두고, 여기서는 고르기만 하면 돌아가게 한다.
돌리는 것은 app/runs.py 의 `simulate` (README 와 같은 엔진 명령), 견주는 것은 app/compare.py, 식당가 카드는 app/board.py 다.
"""

import json
from dataclasses import dataclass
from html import escape
from pathlib import Path

import streamlit as st

from app.board import WALKERHILL_NAMES, index_text, pct_change, venue_cards
from app.compare import Comparison, combine_months, compare, summary_groups, zero_groups
from app.icons import as_img, persona_icon
from app.results import (
    FILLED_PRICE,
    MASKED_AMOUNT_NOTE,
    load_run,
    names_from_files,
    shows_numbers,
    visit_view,
    won,
)
from app.runs import (
    AI_CHOICES,
    EXAMPLE_VENUES,
    ai_env,
    choices,
    data_roots,
    has_private_summary,
    make_example_copy,
    most_calls,
    simulate,
    summary_check,
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

# 기간은 "X월 ~ Y월"로 고른다 (11-17, 화면 담당 결정). 엔진의 "실행의 달"(--month, T112)은 달 하나를 받으므로
# 기간의 달마다 기본 시나리오와 변수 적용 후를 돌리고, 결과는 달 평균으로 합친다 (app/compare.py 의 combine_months).
MONTHS = list(range(1, 13))
# 달을 줘도 바뀌는 것은 그 달에 파는 메뉴와 AI 의 판단뿐이다. 가중치는 일 년 합계에 맞춘다 (FORMATS.md 10.1절 "실행의 달").
SEASON_NOTE = (
    "달은 그 달에 파는 메뉴와 AI 의 판단으로만 반영됩니다. 달에 따른 매출 변동은 아직 넣지 않았습니다 "
    "(매출 합계는 일 년 기준이라, 기간이 다른 결과끼리 합계를 견주지 마세요)."
)
# 11-17 회의 ④: 날씨는 근거 자료가 없어 이번에 넣지 않고 "다음 단계"로 둔다.
WEATHER_NOTE = "날씨는 다음 단계에서 넣습니다. 날씨와 매출을 같은 날짜로 묶은 자료가 있어야 근거 있게 반영할 수 있습니다."
# 11-17 회의 ④: 기준 실행의 가격은 10~11월 공식 가격이고, 12월 요금 같은 것은 상황으로 얹는다.
PRICE_NOTE = "기본 시나리오의 가격은 10~11월 공식 가격입니다. 12월 요금 같은 달별 가격은 '적용할 변수'로 얹습니다."
# 처음 고르는 페르소나 (11-17 팀장과 정함: 1명 기본, AI 호출을 줄인다. 시연은 "모두"를 눌러 저장된 답으로 재생한다).
# 앞에서부터 그 자료에 있는 것 하나를 고른다. 없으면 첫 페르소나.
DEFAULT_PERSONAS = ("family-parents", "family-elders")


def months_between(start: int | None, end: int | None) -> list[int]:
    """시작 달부터 끝 달까지 (해를 넘겨도 된다. 예: 11월 ~ 2월). 시작이 없으면 일 년 전체라 빈 목록이다."""
    if start is None:
        return []
    end = start if end is None else end
    return [(start - 1 + i) % 12 + 1 for i in range((end - start) % 12 + 1)]


def months_text(months: list[int]) -> str:
    if not months:
        return "일 년 전체"
    return f"{months[0]}월" if len(months) == 1 else f"{months[0]}월 ~ {months[-1]}월 ({len(months)}개월)"

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


def chosen_note(condition_ids: list[str], names: dict[str, str], allowed, catalog: dict, is_example: bool) -> str:
    """고급 설정의 "고른 방문 조건"을 식별자가 아니라 이름으로 적는다 (11-17 업장 데이터 담당이 찾아 줌)."""
    conditions = ", ".join(names.get(c, c) for c in condition_ids) or "없음"
    venues = ", ".join(catalog[v].name if v in catalog else v for v in allowed) if is_example else "모두"
    return f"고른 방문 조건: {conditions} · 업장: {venues}"


def newest_run_dir(results: list) -> Path | None:
    """달마다 돌린 기준·상황 실행 가운데 가장 새 실행 폴더 (`run_id` 가 날짜와 시각으로 시작한다)."""
    dirs = [o.run_dir for _, r in results for o in (r.baseline, r.scenario) if o is not None and o.run_dir]
    return max(dirs, key=lambda d: d.name) if dirs else None


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
    months: list[int]
    scenario: object
    scenario_id: str | None
    data_mode: str
    call_llm: bool
    llm_env: dict | None
    go: bool
    missing: list[str]
    ai_problem: str | None = None
    # 기본 데이터의 요약을 보내도 된다고 확인되지 않아 재생만 할 때, 그 받는 곳의 이름 (T115)
    replay_only: str | None = None
    # 그 자료의 페르소나 수. 고른 것이 그보다 적으면 "고른 페르소나만의 결과"라고 적는다
    all_personas: int = 0

    @property
    def problems(self) -> list[str]:
        found = []
        if not self.personas:
            found.append("페르소나를 한 명 이상 고르세요")
        if not self.condition_ids:
            found.append("요일과 때를 하나 이상 고르세요")
        if self.scenario_id is None:
            found.append("적용할 변수를 고르세요")
        if self.ai_problem:
            found.append(self.ai_problem)
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
    default = next(([p] for p in DEFAULT_PERSONAS if p in names), list(names)[:1])
    persona_key = f"sim_personas_{root.is_example}"
    personas = st.multiselect(
        "페르소나",
        list(names),
        default=default,
        format_func=lambda i: names[i],
        placeholder="페르소나를 고르세요",
        key=persona_key,
        label_visibility="collapsed",
        disabled=not cards,
    )
    if len(names) > 1:
        st.button(
            f"{len(names)}명 모두 고르기",
            key=f"sim_all_{root.is_example}",
            disabled=len(personas) == len(names),
            on_click=lambda: st.session_state.update({persona_key: list(names)}),
            help="AI 를 부를 수 있는 호출 수는 맨 아래 버튼 위에 보입니다.",
        )

    _section(3, "언제")
    days = st.pills("요일", list(DAY_TO_CODE), selection_mode="multi", default=["주말"], key="sim_days") or []
    whens = st.pills("때", list(WHEN_TO_CONDITION), selection_mode="multi", default=["저녁"], key="sim_whens") or []
    # 예시 묶음의 저장된 답은 달 없이 받은 것이라, 달을 주면 재생되지 않는다. 예시에서는 고르지 않게 한다.
    example_help = "예시 자료는 달 없이 받아 둔 답이라 고를 수 없습니다." if root.is_example else None
    left, right = st.columns(2)
    # "일 년 전체"는 0 으로 둔다. 선택지에 None 을 두면 Streamlit 이 "고르지 않음"으로 보고 영어 안내 글("Choose an option")을 띄웠다 (11-17 T206).
    start = left.selectbox(
        "기간 시작",
        [0, *MONTHS],
        format_func=lambda m: f"{m}월" if m else "일 년 전체",
        key=f"sim_month_{root.is_example}",
        disabled=root.is_example,
        help=example_help,
    ) or None
    end = right.selectbox(
        "기간 끝",
        MONTHS,
        index=(start or 1) - 1,
        format_func=lambda m: f"{m}월",
        key=f"sim_month_end_{root.is_example}_{start}",
        disabled=root.is_example or start is None,
        help=example_help,
    )
    months = months_between(start, end)
    st.selectbox("날씨", ["다음 단계에서 넣습니다"], key="sim_weather", disabled=True, help=WEATHER_NOTE)
    if months:
        how = (
            f"{months_text(months)}로 돌립니다. "
            if len(months) == 1
            else f"{months_text(months)}을 달마다 돌려 달 평균으로 보입니다. 처음 해 보는 조합이면 달 수만큼 시간이 더 걸립니다. "
        )
        st.caption(how + SEASON_NOTE)

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
    # 해 본 조합은 저장된 답을 불러오고, 처음 해 보는 조합만 AI 를 부른다 (엔진이 방문마다 그렇게 한다. README).
    # 그래서 AI 를 부를 수 있으면 늘 켠다 (11-17, 화면 담당 결정). 예시 묶음은 다른 모델로 받은 답이라 재생만 한다.
    llm_env = None
    ai_problem = None
    if not root.is_example:
        _section(5, "AI")
        ready = {key: ai_env(repo_root, key) for key in AI_CHOICES}
        usable = [key for key, env in ready.items() if env]
        # 두 가지를 늘 보이고, 설정이 된 것을 먼저 고른다. 설정이 안 된 것을 고르면 채울 것을 알리고 비교를 막는다.
        pick = st.radio(
            "AI",
            list(AI_CHOICES),
            index=list(AI_CHOICES).index(usable[0]) if usable else 0,
            format_func=lambda k: AI_CHOICES[k][0] + ("" if ready[k] else " · 설정 필요"),
            horizontal=True,
            key="sim_ai",
            label_visibility="collapsed",
        )
        llm_env = ready[pick]
        if llm_env:
            st.caption(
                f"모델 `{llm_env['LLM_MODEL']}` · 해 본 조합은 저장된 답을 불러오고, 처음 해 보는 조합만 AI 가 새로 답합니다."
                + (f" {OPENAI_NOTE}" if pick == "openai" else "")
            )
        else:
            ai_problem = f"{AI_CHOICES[pick][0]}: 쓰려면 이 PC 의 `.env` 에 {AI_SETUP[pick]}"
            st.warning(ai_problem)
    call_llm = llm_env is not None
    with st.expander("고급 설정"):
        modes = ["sample"] + (["private"] if has_private_summary(root.path) else [])
        data_mode = st.radio("값", modes, format_func=lambda m: {"sample": "가상 예시 값", "private": "기본 데이터 (이 PC 에만)"}[m], key="sim_mode")
        if root.is_example:
            st.caption("예시 자료는 미리 받아 둔 답으로만 돌립니다.")
        st.caption(chosen_note(condition_ids, names_from_files(root.path), allowed, catalog, root.is_example))

    # 기본 데이터의 요약은 받는 곳으로 보내도 된다고 확인한 PC 에서만 AI 를 새로 부른다 (T115, 11-17 팀장과 정함).
    # 확인 전에는 `--base-profile none` 으로 바꿔 돌리지 않고 재생만 한다. 팀장 PC 에서 받은 답과 요청이 같아야 재생되기 때문이다.
    replay_only = None
    if data_mode == "private" and llm_env is not None:
        confirmed, receiver = summary_check(repo_root, llm_env)
        if not confirmed:
            replay_only, call_llm = receiver, False
            st.info(
                f"기본 데이터의 요약을 `{receiver}` 로 보내도 되는지 이 PC 에서 확인되지 않아, AI 를 새로 부르지 않고 저장된 답만 재생합니다. "
                "저장된 답이 없는 방문은 결과에서 빠지고 그 수를 보여 줍니다."
            )
    n_months = max(len(months), 1)
    if call_llm and personas and condition_ids:
        calls = most_calls(len(personas), len(condition_ids), n_months)
        every = most_calls(len(names), len(condition_ids), n_months)
        all_text = f" · {len(names)}명 모두면 최대 {every:,}번" if len(personas) < len(names) else ""
        st.caption(
            f"AI 호출 최대 {calls:,}번 (페르소나 {len(personas)}명 × 방문 조건 {len(condition_ids)}개 × 기본·변수 2번"
            + (f" × {n_months}개월" if n_months > 1 else "")
            + f"){all_text}. 해 본 조합은 저장된 답을 불러와 실제로는 더 적습니다."
        )

    go = st.button(f"{BASE_LABEL}와 비교하기", type="primary", key="sim_go", width="stretch", disabled=bool(found.missing))
    return Inputs(
        root, catalog, allowed, cards, personas, days, whens, condition_ids, months,
        scenario, scenario_id, data_mode, call_llm, llm_env, go, list(found.missing), ai_problem,
        replay_only, len(names),
    )  # fmt: skip


def _chips(inputs: Inputs) -> str:
    names = {c["id"]: c["name"] for c in inputs.cards}
    when = " · ".join(inputs.days + inputs.whens) or "요일·때 없음"
    if inputs.months:
        when += f" · {months_text(inputs.months)}"
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
        f'<div class="tx"><div class="nm">{escape(c["name"])}</div>'
        f'<div class="ln" title="{escape(c["group"])} · {escape(c["line"])}">{escape(c["group"])} · {escape(c["line"])}</div></div></div>'
        for c in chosen
    )
    return f'<div class="sim-personas">{items}</div>' if items else ""


def render(repo_root: Path) -> None:
    # 패널은 페르소나 이름표가 한 줄에 들어갈 만큼 둔다 (11-17 T204, 창 폭 820px 에서 재어 정함)
    panel, main = st.columns([1.5, 2.5], gap="medium")
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
                results = []
                # 기간이면 달마다 기본 시나리오와 변수 적용 후를 돌린다. 엔진은 같은 달의 기준과 상황끼리만 견준다.
                for month in inputs.months or [None]:
                    where = "" if month is None else f"{month}월: "
                    with st.spinner(f"{where}{BASE_LABEL}와 {AFTER_LABEL}를 차례로 돌리는 중입니다…"):
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
                            llm_env=inputs.llm_env,
                            month=month,
                        )
                    results.append((month, result))
                # 방금 돌린 실행을 상세 분석의 "실행 (새것이 위)"에서 고른 상태로 둔다. 그러지 않으면 전에 고른 실행이
                # 그대로 남아 새로고침 전까지 예전 실행이 보였다 (11-17 업장 데이터 담당이 찾아 줌).
                # 상세 분석 탭은 이 탭 뒤에 그려져, 같은 그리기에서 main.apply_pick 이 이 값을 받는다.
                newest = newest_run_dir(results)
                if newest is not None:
                    st.session_state["pick"] = (newest.parent, newest.name)
                st.session_state["sim_result"] = (
                    results, inputs.root.path, inputs.data_mode, list(inputs.months), list(inputs.allowed),
                    inputs.replay_only, len(inputs.personas), inputs.all_personas,
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
    results, sim_root, sim_mode, sim_months, sim_allowed, replay_only, n_chosen, n_all = saved
    # 엔진이 남긴 말은 고쳐 쓰지 않고 그대로 보여 준다 (팀장 요청, 11-16).
    outputs = []
    for month, result in results:
        where = "" if month is None else f" ({month}월)"
        outputs.append((BASE_LABEL + where, result.baseline))
        if result.scenario:
            outputs.append((AFTER_LABEL + where, result.scenario))
    failed = any(not r.ok for _, r in results) or any(o.exit_code != 0 for _, o in outputs)
    bad = [m for m, r in results if not r.ok]
    if bad and len(bad) == len(results):
        st.error("비교할 결과를 만들지 못했습니다. 아래 '엔진이 남긴 말'을 보세요.")
    elif bad:
        st.warning(f"{', '.join(f'{m}월' for m in bad)}은 결과를 만들지 못해 빼고 보입니다. 아래 '엔진이 남긴 말'을 보세요.")
    scope = persona_scope(n_chosen, n_all)
    notes = [PRICE_NOTE]
    if n_chosen < n_all:
        notes.append(f"{scope}의 결과입니다. {ONE_PERSONA_NOTE}")
    if sim_months:
        notes.append(period_note(sim_months))
    st.caption("  \n".join(notes))
    per_month = [
        (
            month,
            compare(
                load_run(r.baseline.run_dir),
                load_run(r.scenario.run_dir),
                summary_groups(sim_root, sim_mode),
                names_from_files(sim_root),
            ),
        )
        for month, r in results
        if r.ok
    ]
    if replay_only:
        missing = sum(c.count("failed") for _, c in per_month)
        visits = sum(len(c.moves) for _, c in per_month)
        st.info(
            f"재생만 했습니다: 기본 데이터의 요약을 `{replay_only}` 로 보내도 되는지 이 PC 에서 확인되지 않아 AI 를 새로 부르지 않았습니다. "
            f"저장된 답이 없는 방문 {missing}건 / 전체 {visits}건"
            + (" — 그 방문은 매출과 그림에서 뺐습니다." if missing else ".")
        )
    zero = zero_groups(per_month)
    if zero:
        listed = ", ".join(
            f"{group} ({', '.join('일 년 전체' if m is None else f'{m}월' for m in months)})" for group, months in zero.items()
        )
        st.warning(
            f"워커힐 업장을 고른 방문이 없어 매출 규모를 맞추지 못한 고객군이 있습니다: {listed}. "
            "그 달에는 이 고객군의 가상 매출이 0 으로 들어가"
            + (" 달 평균이 그만큼 낮아집니다." if len(per_month) > 1 else " 합계에서 빠집니다.")
        )
    if per_month:
        comparison = combine_months(per_month)
        show_comparison(
            comparison,
            venue_catalog(sim_root),
            scenario_name(sim_root, comparison.scen.record.scenario_id),
            sim_allowed,
            per_month if len(per_month) > 1 else None,
            scope,
        )
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
    "failed": ("orange", "AI 답 못 받음"),
}


# 설정이 안 된 AI 를 골랐을 때 채울 것 (README 의 "시뮬레이션을 돌린다").
AI_SETUP = {
    "claude": "`LLM_MODEL`(또는 `CLAUDE_MODEL`)을 적고, 터미널에서 `claude auth login` 을 한 번 하세요.",
    "openai": "`OPENAI_MODEL`(쓸 OpenAI 모델)과 `LLM_API_KEY`(OpenAI 키)를 적으세요.",
}
# OpenAI 는 원청에 넘길 때 GPT 로 돌릴 수 있게 남긴 길이다 (11-17, 화면 담당). 팀의 보정·시연 답은 Claude 구독으로 받는다 (T114).
OPENAI_NOTE = "OpenAI 로 받은 답은 팀의 보정·시연 답(Claude)과 모델이 달라 서로 재생되지 않습니다."
# 고른 페르소나가 일부일 때 (11-17 팀장 요청). 고객군 배수는 고른 페르소나의 방문으로 맞추므로,
# 한 고객군에서 한 명만 고르면 그 고객군의 매출 전체가 그 사람의 선택으로 나온다 (PRD 7.2절).
ONE_PERSONA_NOTE = "한 고객군에서 한 명만 고르면 그 고객군의 매출 전체가 그 사람의 선택으로 나옵니다."


def period_note(months: list[int]) -> str:
    """기간을 골랐을 때 결과 위의 안내 (11-17 팀장 회신 ①): 달 평균, 같은 무게는 설계 가정, 금액은 일 년 규모."""
    return (
        f"{months_text(months)}: 달마다 돌려 평균했습니다 (달마다 같은 무게로 평균한 것은 설계 가정입니다). "
        f"금액은 그 기간의 매출이 아니라 일 년 규모로 맞춘 가상 값이라, 볼 것은 변화율입니다. {SEASON_NOTE}"
    )


def persona_scope(chosen: int, total: int) -> str:
    """결과가 누구의 것인가. 머리 숫자 위와 안내에 적는다."""
    return f"페르소나 {total}명 모두" if total and chosen >= total else f"고른 페르소나 {chosen}명만"

# AI 답을 받지 못했을 때의 안내. 엔진은 받은 답을 저장해 두어, 다시 돌리면 빠진 방문만 다시 묻는다.
RETRY_HINT = "다시 비교하면 빠진 방문만 AI 에게 다시 묻습니다. 계속 안 되면 아래 '엔진이 남긴 말'에서 이유를 보세요."


def badge(move: str) -> str:
    color, text = MOVE_BADGE[move]
    return f":{color}-badge[{text}]"


def show_comparison(
    comparison: Comparison,
    catalog: dict[str, VenueInfo],
    scenario_name: str = "",
    allowed: list[str] | None = None,
    per_month: list[tuple[int, Comparison]] | None = None,
    scope: str = "",
) -> None:
    names = {v.venue_id: v.name for v in catalog.values()} | comparison.names
    record = comparison.scen.record
    # 기본 데이터 실행이면 금액과 손님 수를 가린다 (PRD 17절, 11-18 팀장 회신. app/results.py 의 `shows_numbers`)
    masked = not (shows_numbers(record) and shows_numbers(comparison.base.record))
    if masked:
        st.caption(MASKED_AMOUNT_NOTE)

    # 식당가 그림: 페르소나가 기본 시나리오 → 변수 적용 후로 옮겨 가는 모습 (app/street.py)
    shown = [v for v in (allowed or list(catalog)) if v in catalog]
    scene = scene_from_comparison(
        comparison,
        names,
        {v.venue_id: v.cuisine for v in catalog.values()},
        [v for v in shown if not catalog[v].is_competitor],
        [v for v in shown if catalog[v].is_competitor],
        scenario_name or record.scenario_id,
        scope,
        masked,
    )
    html, _ = render_scene(scene)
    # st.components.v1.html 는 없어질 기능이라 st.iframe 으로 넣는다 (11-17 T206, hojitea-ui 알림). 이름과 이유는 render_scene 이 escape 한다.
    # 높이는 st.iframe 이 내용을 재어 맞춘다. 어림한 높이(height)를 주면 페르소나가 많을 때 안쪽에 스크롤이 생겼다.
    st.iframe(html, height="content")

    with st.expander("숫자와 카드로 자세히 보기"):
        _show_cards(comparison, catalog, names, allowed, masked)
    # 검증 결과는 그 안에 접는 칸이 있어 위의 접는 칸 밖에 둔다 (접는 칸 안에 접는 칸은 둘 수 없다).
    if comparison.base.run_dir is not None:
        show_validation(comparison.base.run_dir, names)

    with st.expander("한 사람씩 자세히 보기"):
        if per_month:
            # 기간이면 달을 먼저 고른다. 방문의 자세한 답은 그 달의 실행에 있다.
            pick = st.selectbox("달", [m for m, _ in per_month], format_func=lambda m: f"{m}월", key="sim_detail_month")
            _show_person(dict(per_month)[pick])
        else:
            _show_person(comparison)


def _show_cards(
    comparison: Comparison, catalog: dict[str, VenueInfo], names: dict[str, str], allowed: list[str] | None, masked: bool = False
) -> None:
    # 한눈에: 워커힐 가상 매출과 옮긴 사람
    diff = comparison.total_after - comparison.total_before
    a, b, c = st.columns(3)
    if masked:
        a.metric(
            "워커힐 가상 매출 변화",
            pct_change(comparison.total_before, comparison.total_after) if diff else "변화 없음",
            help=MASKED_AMOUNT_NOTE,
        )
    else:
        a.metric(
            "워커힐 가상 매출 변화",
            pct_change(comparison.total_before, comparison.total_after) if diff else "변화 없음",
            delta=f"{diff:+,}원 (가상 · 일 년 규모)" if diff else None,
            delta_color="normal" if diff else "off",
            help=f"{BASE_LABEL} {won(comparison.total_before)} → {AFTER_LABEL} {won(comparison.total_after)}. "
            "금액은 기본 데이터의 일 년 매출 규모에 맞춘 가상 값입니다.",
        )
    b.metric("워커힐 밖으로 나간 방문", f"{comparison.count('out')}건", delta=-comparison.count("out") or None)
    c.metric("워커힐로 들어온 방문", f"{comparison.count('in')}건", delta=comparison.count("in") or None)

    changed = [m for m in comparison.moves if m.move not in ("same", "failed")]
    unknown = [m for m in comparison.moves if m.move == "failed"]
    # 모든 방문이 답을 못 받았으면 "선택이 같다"고 하지 않는다 (11-16, T109 에서 찾음).
    if not changed and len(unknown) < len(comparison.moves):
        st.info(f"{BASE_LABEL}와 선택이 같습니다. 이 변수로는 고른 페르소나의 선택이 바뀌지 않았습니다.")
    if unknown:
        st.warning(f"AI 답을 받지 못한 방문 {len(unknown)}건은 매출과 이동에서 뺐습니다. {RETRY_HINT}")

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
            if masked:
                # 금액과 손님 수 대신 기본 시나리오를 100 으로 둔 지수와 변화율 (PRD 17절)
                revenue = card.revenue_before is not None
                before = card.revenue_before if revenue else card.guests_before
                after = card.revenue_after if revenue else card.guests_after
                pct = pct_change(before, after)
                st.metric(
                    "가상 매출 (지수)" if revenue else "손님 (지수)",
                    index_text(before, after),
                    delta=pct if after != before else "변화 없음",
                    delta_color="normal" if after != before else "off",
                )
            elif card.revenue_before is not None:
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
                st.write(f"AI 답을 받지 못했습니다: {view.failed_reason or '이 실행에 없는 방문'}")
                continue
            # 내부 자료로 채운 단가가 든 방문은 금액을 가린다 (PRD 17절)
            st.write(f"{view.venue or KO['choice_kind']['none']} — {FILLED_PRICE if view.hidden else won(view.total_paid)}")
            st.write(view.reason_text or "")
            for item in view.not_chosen:
                st.caption(f"고르지 않음: {item.venue} — {item.text}")


def _place(place, names: dict[str, str]) -> str:
    if place.kind == "none":
        return KO["choice_kind"]["none"]
    if place.kind == "failed":
        return "AI 답 없음"
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
        st.caption(
            f"값은 비율이 아니라 건수입니다. 이유가 겹친 것은 고른 이유가 적힌 후기(이유를 잰 건수) 가운데에서 셉니다. "
            f"{validation.min_reviews}건 미만이면 일치 건수를 말하지 않습니다."
        )
        st.dataframe(validation_rows(validation, names), hide_index=True)
        for venue_id in limits_not_in(validation):
            st.caption(f"{names.get(venue_id, venue_id)} (이 결과에 없음) 한계: {VALIDATION_LIMITS[venue_id]}")
        st.caption(f"한계의 출처: {LIMITS_SOURCE}")


def scenario_name(root: Path, scenario_id: str) -> str:
    return _read(root / "scenarios" / f"{scenario_id}.json").get("name", scenario_id)
