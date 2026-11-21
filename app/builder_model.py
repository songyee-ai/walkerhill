"""시나리오 만들기 페이지 (T130): 화면 스크립트(app/builder/)에 넘길 데이터 묶음과, 화면이 보낸 시나리오를 돌리는 일.

데이터 묶음은 시안의 모양을 따른다 (`catalogs`, `runs`). 자료는 두 벌이다: 팀 자료(저장소 맨 위)와 연습용 예시 사본(private/try-example).
돌리기는 이전 화면의 시뮬레이터와 같다: 달마다 기본 시나리오와 바꾼 뒤를 돌리고(app/runs.py 의 simulate),
달마다의 실행 짝을 결과 묶음으로 적는다(app/result_store.py). 끝나면 화면이 결과 페이지로 넘어간다.
금액은 모두 시뮬레이션이 낸 가상 값이다. 업장 정의의 공개 가격만 넘기고, 기본 데이터의 집계로 채운 단가는 넘기지 않는다.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.evidence import venues as load_venues
from app.result_model import DATA_MODE_LABEL, _condition_line, condition_texts, months_label, persona_icon
from app.result_store import Pair, data_root, list_records, new_record, read_record, runs_path, save_record
from app.runs import (
    EXAMPLE_VENUES,
    ai_env,
    data_roots,
    default_prompt,
    has_private_summary,
    make_example_copy,
    prompt_versions,
    replay_only_pc,
    runnable_persona,
    simulate,
    summary_check,
)
from app.scenario_builder import UI_PREFIX, _short_hash, write_scenario
from engine.formats import Scenario, read_model
from engine.scenarios import apply_scenario

# 화면의 이용 상황 칩 → 방문 조건의 앞부분 (engine/conditions.json)
OCCASION_CONDITION = {"lunch": "meal-lunch", "dinner": "meal-dinner", "dessert": "dessert", "takeout": "takeout"}
DAYS = ("weekday", "weekend")
# 화면이 새로 만든 상품·프로모션의 식별자 (시안의 uid(): "ui-" + UUID). 내용으로 다시 만든다
RANDOM_ID = re.compile(r"^ui-[0-9a-f]{8}-[0-9a-f]{4}-")
PRACTICE_NOTE = "예시 사본은 가상 예시 데이터로만 돕니다. 업장 두 곳과 일 년 전체로 받은 저장된 답을 재생합니다."


class RunError(Exception):
    """화면에 그대로 보일 실행 실패의 이유."""


def _json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def team_data_mode(root: Path) -> str:
    """팀 자료로 돌릴 값의 종류: 이 PC 에 기본 데이터의 집계가 있으면 기본 데이터, 없으면 가상 예시 값."""
    return "private" if has_private_summary(root) else "sample"


def can_call_ai(repo_root: Path, data_mode: str) -> bool:
    """이 PC 에서 AI 를 새로 부를 수 있는가: AI 설정이 있고, 재생 전용 PC 가 아니고, 기본 데이터면 받는 곳이 확인돼 있다 (T115)."""
    env = ai_env(repo_root, "claude")
    if env is None or replay_only_pc(repo_root):
        return False
    return data_mode != "private" or summary_check(repo_root, env)[0]


def _venues(root: Path, practice: bool) -> dict:
    found = {}
    for venue in load_venues(root).values():
        if practice and venue.venue_id not in EXAMPLE_VENUES:
            continue
        found[venue.venue_id] = {
            "name": venue.name,
            "is_competitor": venue.is_competitor,
            "occasions": list(venue.occasions),
            "months": list(venue.months) if venue.months else None,
            "promotions": [{"promo_id": p.promo_id, "applies_to": p.applies_to} for p in venue.promotions],
            "products": [{"product_id": p.product_id, "name": p.name, "unit": p.unit, "price": p.price} for p in venue.products],
        }
    return found


def _people(root: Path) -> list[dict]:
    people = []
    for path in sorted((root / "personas").glob("*.json")):
        if not runnable_persona(path):
            continue
        data = _json(path)
        if not data.get("persona_id"):
            continue
        party = (data.get("visit") or {}).get("party") or {}
        people.append(
            {
                "id": data["persona_id"],
                "name": data.get("name", data["persona_id"]),
                "group": data.get("customer_group", ""),
                "party": {"label": party.get("label", ""), "adults": party.get("adults", 1), "children": party.get("children", 0)},
                "icon": persona_icon(data["persona_id"]),
            }
        )
    return people


def _definition(path: Path) -> Scenario | None:
    try:
        return read_model(path, Scenario)
    except (OSError, ValueError):
        return None


def _presets(root: Path, venue_ids: set[str]) -> dict:
    """준비된 상황 (기준 상황과 화면이 만든 ui- 상황은 뺀다). 자료에 없는 업장을 바꾸는 상황도 뺀다 (예시 사본)."""
    found = {}
    for path in sorted((root / "scenarios").glob("*.json")):
        if path.stem == "baseline" or path.stem.startswith(UI_PREFIX):
            continue
        scenario = _definition(path)
        if scenario is None or any(c.venue_id not in venue_ids for c in scenario.changes):
            continue
        found[scenario.scenario_id] = _short_definition(scenario)
    return found


def _short_definition(scenario: Scenario) -> dict:
    dumped = scenario.model_dump(mode="json", by_alias=True)
    return {"name": dumped["name"], "kind": dumped["kind"], "changes": dumped["changes"]}


def _catalog(repo_root: Path, root: Path, practice: bool) -> dict:
    venues = _venues(root, practice)
    prompts = prompt_versions(root)
    data_mode = "sample" if practice else team_data_mode(root)
    if practice:
        note = PRACTICE_NOTE
    elif data_mode == "private":
        note = "이 PC 의 기본 데이터로 돕니다. 결과에는 내부 자료로 계산한 값이 들어 있습니다."
    else:
        note = "이 PC 에 기본 데이터가 없어 가상 예시 데이터로 돕니다."
    return {
        "venues": venues,
        "people": _people(root),
        "presets": _presets(root, set(venues)),
        "prompts": prompts,
        "default_prompt": default_prompt(prompts) if prompts else "",
        "data_label": DATA_MODE_LABEL.get(data_mode, data_mode),
        "data_note": note,
        "can_call": not practice and can_call_ai(repo_root, data_mode),
    }


def _source_of(record_root: Path, repo_root: Path) -> str | None:
    roots = data_roots(repo_root)
    if record_root.resolve() == roots[0].path.resolve():
        return "team"
    if record_root.resolve() == roots[1].path.resolve():
        return "practice"
    return None


def _input_of(source: str, persona_ids: list[str], condition_ids: list[str], months: list[int | None], prompt: str) -> dict:
    """결과를 돌릴 때의 입력을 화면의 입력 모양(시안의 state)으로 되돌린다. 방문 조건은 요일 × 이용 상황으로 푼다."""
    days = [d for d in DAYS if any(c.endswith(f"-{d}") for c in condition_ids)]
    occasions = [o for o, prefix in OCCASION_CONDITION.items() if any(c.startswith(prefix + "-") for c in condition_ids)]
    real = [m for m in months if m is not None]
    if not real:
        period, start, end = "year", None, None
    elif len(real) == 1:
        period, start, end = "single", real[0], real[0]
    else:
        period, start, end = "range", real[0], real[-1]
    return {
        "source": source, "name": "", "nameEdited": False, "preset": None, "side": "in", "changes": [],
        "people": list(persona_ids), "days": days, "occasions": occasions,
        "period": period, "start": start, "end": end, "extendOnNext": False,
        "loadedKey": None, "loadedHasResult": False, "modified": False, "answer": "replay", "prompt": prompt,
    }  # fmt: skip


def _runs(repo_root: Path) -> list[dict]:
    """결과 있는 시나리오 (결과 묶음마다 하나). 모양은 시안의 runs 와 같다."""
    rows = []
    long_conditions: dict[Path, dict[str, str]] = {}
    for record in list_records(repo_root):
        root = data_root(record, repo_root)
        source = _source_of(root, repo_root)
        scenario = _definition(root / "scenarios" / f"{record.scenario_id}.json")
        if source is None or scenario is None:
            continue
        try:
            run = read_record(runs_path(record, repo_root) / record.pairs[-1].scenario)
        except (OSError, ValueError):
            continue
        if root not in long_conditions:
            long_conditions[root] = condition_texts(root)[0]
        line = (
            f"{DATA_MODE_LABEL.get(record.data_mode, record.data_mode)} · 페르소나 {len(run.persona_ids)}명 · "
            f"{months_label(record.months)} · {_condition_line(list(run.condition_ids), long_conditions[root])}"
        )
        created = record.created_at
        rows.append(
            {
                "id": record.result_id,
                "config": _short_definition(scenario),
                "input": _input_of(source, run.persona_ids, run.condition_ids, record.months, run.llm.prompt_version),
                "source": source,
                "date": f"{int(created[5:7])}-{created[8:10]} {created[11:16]}",
                "from": "run",
                "condition_line": line,
            }
        )
    return rows


def build(repo_root: Path, preload: str | None = None, run_error: dict | None = None) -> dict:
    """화면 스크립트에 넘길 사전 하나. 예시 사본이 아직 없으면 연습용 자료는 비운다."""
    roots = data_roots(repo_root)
    catalogs = {"team": _catalog(repo_root, roots[0].path, False)}
    practice = roots[1].path
    catalogs["practice"] = _catalog(repo_root, practice, True) if practice.is_dir() else _catalog(repo_root, roots[0].path, True)
    return {"catalogs": catalogs, "runs": _runs(repo_root), "preload": preload, "run_error": run_error}


# ── 돌리기 ──────────────────────────────────────────────────


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _content_id(prefix: str, item: dict, key: str) -> str:
    return f"{UI_PREFIX}{prefix}-{_short_hash(_canonical({k: v for k, v in item.items() if k != key}))}"


def scenario_from(definition: dict, presets: dict) -> Scenario:
    """화면이 보낸 상황 정의를 엔진의 상황으로 만든다.

    화면이 만든 상품·프로모션의 식별자와 상황의 식별자는 매번 새 UUID 라, 내용으로 다시 만든다. 같은 내용이면 같은 식별자가 나와
    저장된 AI 응답을 다시 쓴다. 상황의 식별자는 바꿀 것(종류와 내용)만으로 만든다. 이름만 바꿔 다시 돌리면 같은 상황이다 (11-22 팀장 결정).
    준비된 상황을 고치지 않고 돌리면 그 상황의 식별자를 그대로 써서 기존 결과와 묶인다.
    """
    changes = []
    for change in definition.get("changes") or []:
        change = dict(change)
        if change.get("op") == "add_product" and RANDOM_ID.match(str(change["product"].get("product_id", ""))):
            change["product"] = dict(change["product"]) | {"product_id": _content_id("item", change["product"], "product_id")}
        if change.get("op") == "add_promotion" and RANDOM_ID.match(str(change["promotion"].get("promo_id", ""))):
            change["promotion"] = dict(change["promotion"]) | {"promo_id": _content_id("promo", change["promotion"], "promo_id")}
        changes.append(change)
    kind = definition.get("kind")
    same = [pid for pid, p in presets.items() if p["kind"] == kind and _canonical(p["changes"]) == _canonical(changes)]
    scenario_id = same[0] if same else f"{UI_PREFIX}{_short_hash(kind, _canonical(changes))}"
    name = (definition.get("name") or "").strip() or "이름 없는 시나리오"
    data = {
        "format_version": 1,
        "scenario_id": scenario_id,
        "name": name,
        "kind": kind,
        # 설명은 비울 수 없다 (엔진 형식). 화면은 바꿀 것 요약을 보내고, 없으면 이름을 쓴다
        "description": (definition.get("description") or "").strip() or name,
        "changes": changes,
        "note": definition.get("note") or "",
    }
    return Scenario.model_validate(data)


def condition_ids_of(root: Path, days: list[str], occasions: list[str]) -> list[str]:
    """요일 × 이용 상황 → 방문 조건. 자료의 방문 조건 묶음에 있는 것만."""
    known = {c.get("condition_id") for c in _json(root / "engine" / "conditions.json").get("conditions", [])}
    found = [f"{OCCASION_CONDITION[o]}-{d}" for o in OCCASION_CONDITION if o in occasions for d in DAYS if d in days]
    return [c for c in found if c in known]


def months_of(period: str, start: int | None, end: int | None) -> list[int | None]:
    """고른 기간의 달을 그 순서대로. 끝 달이 시작 달보다 이르면 다음 해로 이어진다 (12월 → 1월). 일 년 전체면 [None]."""
    if period == "year" or start is None:
        return [None]
    if period == "single" or end is None or end == start:
        return [start]
    count = (end - start) % 12 + 1
    return [(start - 1 + i) % 12 + 1 for i in range(count)]


@dataclass(frozen=True)
class Plan:
    root: Path
    practice: bool
    scenario: Scenario
    persona_ids: list[str]
    condition_ids: list[str]
    months: list[int | None]
    data_mode: str
    call_llm: bool
    prompt: str | None


def plan_run(repo_root: Path, definition: dict, state: dict) -> Plan:
    """돌리기 전에 모두 확인한다. 막히면 화면에 보일 말로 RunError 를 낸다."""
    practice = state.get("source") == "practice"
    roots = data_roots(repo_root)
    if practice:
        make_example_copy(repo_root)
    root = roots[1].path if practice else roots[0].path
    venue_ids = set(_venues(root, practice))
    try:
        scenario = scenario_from(definition, _presets(root, venue_ids))
    except ValueError as error:
        raise RunError(f"시나리오를 엔진이 받을 모양으로 만들지 못했습니다: {error}") from error
    if any(c.venue_id not in venue_ids for c in scenario.changes):
        raise RunError("이 자료에 없는 업장을 바꾸는 시나리오입니다. 업장을 다시 골라 주세요.")
    try:
        apply_scenario(load_venues(root), scenario)
    except ValueError as error:
        raise RunError(f"바꿀 것을 업장에 적용하지 못했습니다: {error}") from error
    persona_ids = [p for p in state.get("people") or [] if p in {x["id"] for x in _people(root)}]
    condition_ids = condition_ids_of(root, state.get("days") or [], state.get("occasions") or [])
    if not persona_ids or not condition_ids:
        raise RunError("페르소나와 방문 조건(요일·이용 상황)을 하나 이상 골라 주세요.")
    data_mode = "sample" if practice else team_data_mode(root)
    months = [None] if practice else months_of(state.get("period", "year"), state.get("start"), state.get("end"))
    call_llm = not practice and state.get("answer") == "ai" and can_call_ai(repo_root, data_mode)
    prompts = prompt_versions(root)
    prompt = state.get("prompt") if state.get("prompt") in prompts else None
    return Plan(root, practice, scenario, persona_ids, condition_ids, months, data_mode, call_llm, prompt)


def run_plan(repo_root: Path, plan: Plan, progress=None) -> str:
    """달마다 기본 시나리오와 바꾼 뒤를 돌리고 결과 묶음을 적는다. 돌려준 것은 결과 묶음의 이름이다."""
    # 준비된 상황과 바꿀 것이 같으면 그 파일(저장소에 올라 있는 것)을 그대로 쓴다. 화면이 만든 상황만 ui- 파일로 쓴다 (깃이 무시함)
    if plan.scenario.scenario_id.startswith(UI_PREFIX):
        write_scenario(plan.root, plan.scenario)
    llm_env = ai_env(repo_root, "claude") if not plan.practice else None
    pairs = []
    folder = None
    failed = []
    for i, month in enumerate(plan.months, start=1):
        if progress is not None:
            progress(month, i, len(plan.months))
        result = simulate(
            plan.root,
            repo_root,
            plan.data_mode,
            plan.scenario.scenario_id,
            plan.persona_ids,
            plan.condition_ids,
            list(EXAMPLE_VENUES) if plan.practice else [],
            plan.call_llm,
            prompt=plan.prompt,
            is_example=plan.practice,
            llm_env=llm_env,
            month=month,
        )
        if result.ok and result.baseline.run_dir is not None:
            pairs.append(Pair(month, result.baseline.run_dir.name, result.scenario.run_dir.name))
            folder = result.scenario.run_dir.parent
        else:
            failed.append((month, result))
    if failed:
        # 일부 달만 된 결과는 기간의 합이 작아 보인다. 묶음을 만들지 않고 어느 달이 왜 멈췄는지 알린다
        reasons = []
        for month, result in failed:
            outcome = result.scenario or result.baseline
            reasons.append(f"{'일 년 전체' if month is None else f'{month}월'}: {outcome.meaning}")
        raise RunError("실행이 끝나지 못했습니다. " + " / ".join(reasons))
    record = new_record(repo_root, folder, plan.data_mode, plan.scenario.scenario_id, pairs)
    save_record(repo_root, record)
    return record.result_id
