"""실행 폴더를 읽어 화면에 보여 줄 모양으로 바꾼다 (T09).

화면(main.py)은 그리기만 하고, 무엇을 보여 줄지는 여기서 정한다. 그래서 서버를 띄우지 않고 테스트할 수 있다.
읽는 것은 엔진이 쓴 실행 폴더 하나다 (docs/FORMATS.md 10절): `run.json`, `ledger.csv`, `llm/<request_hash>.json`.
금액은 원장에서만 가져온다. 저장된 응답에서는 업장과 상품의 이름, 고르지 않은 업장과 그 이유, 방문 조건만 가져온다.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from engine.formats import KO, LEDGER_COLUMNS, LedgerRow, RunCondition, RunRecord, SavedResponse, read_model
from engine.formats.io import read_csv
from engine.formats.run import SEASON_GAP_REASON
from engine.runner import runs_folder

# 엔진이 실행 결과를 쓰는 곳 (engine.runner.runs_folder). 기본 데이터로 돌린 결과를 먼저 보여 준다.
DATA_MODES = (("private", "기본 데이터로 돌린 실행"), ("sample", "가상 예시 값으로 돌린 실행"))
# 키와 기본 데이터가 없는 PC 에서도 화면이 돌게, 저장소에 든 예시 실행을 늘 마지막 출처로 둔다.
EXAMPLE_LABEL = "예시 파일 (tests/fixtures/example)"
EXAMPLE_COPY_LABEL = "예시 사본으로 돌린 실행 (private/try-example)"


@dataclass(frozen=True)
class RunSource:
    """실행 폴더들이 든 곳 하나."""

    label: str
    folder: Path


def run_sources(repo_root: Path) -> list[RunSource]:
    """실행이 하나라도 든 출처. 앞에 있는 것이 먼저 고른 값이다."""
    sources = [RunSource(label, runs_folder(repo_root, mode)) for mode, label in DATA_MODES]
    # 화면의 "돌리기"에서 예시 사본으로 돌린 실행 (app/runs.py 의 EXAMPLE_COPY).
    sources.append(RunSource(EXAMPLE_COPY_LABEL, runs_folder(repo_root / "private" / "try-example", "sample")))
    sources.append(RunSource(EXAMPLE_LABEL, runs_folder(repo_root / "tests" / "fixtures" / "example", "sample")))
    return [source for source in sources if list_runs(source.folder)]


def list_runs(folder: Path) -> list[str]:
    """실행 기록이 있는 실행의 `run_id`. 새것이 앞에 온다 (`run_id` 가 날짜와 시각으로 시작한다)."""
    if not folder.is_dir():
        return []
    return sorted((d.name for d in folder.iterdir() if (d / "run.json").is_file()), reverse=True)


@dataclass
class LoadedRun:
    record: RunRecord
    rows: list[LedgerRow]
    # request_hash → 저장된 응답. 원장의 줄에 적힌 해시로 찾는다.
    responses: dict[str, SavedResponse]
    # 검사에서 어긋난 응답의 수 (`llm_rejected/`). 원장에는 실패한 줄로 남는다.
    rejected_files: int
    # 읽은 실행 폴더. 같은 폴더의 검증 결과(validation.json)를 찾을 때 쓴다.
    run_dir: Path | None = None


def load_run(run_dir: Path) -> LoadedRun:
    record = read_model(run_dir / "run.json", RunRecord)
    rows = [LedgerRow.from_row(row) for row in read_csv(run_dir / "ledger.csv", LEDGER_COLUMNS)]
    responses: dict[str, SavedResponse] = {}
    llm_dir = run_dir / "llm"
    for request_hash in sorted({row.request_hash for row in rows if row.request_hash}):
        path = llm_dir / f"{request_hash}.json"
        if path.is_file():
            responses[request_hash] = read_model(path, SavedResponse)
    rejected_dir = run_dir / "llm_rejected"
    rejected_files = len(list(rejected_dir.glob("*.json"))) if rejected_dir.is_dir() else 0
    return LoadedRun(record, rows, responses, rejected_files, run_dir)


def won(amount: int | float) -> str:
    """금액을 "가상" 표시와 함께 적는다 (docs/PRD.md 10절)."""
    return f"{round(amount):,}원 (가상)"


def condition_label(condition: RunCondition) -> str:
    """방문 조건을 한국어로 적는다. 예: "식사 · 저녁 · 주말"."""
    return _condition_label(condition.occasion, condition.meal, condition.day_type, condition.stay, condition.month)


def _condition_label(occasion: str, meal: str | None, day_type: str, stay: str | None, month: int | None) -> str:
    parts = [KO["occasion"][occasion]]
    if meal:
        parts.append(KO["meal"][meal])
    parts.append(KO["day_type"][day_type])
    if stay:
        parts.append(KO["stay"][stay])
    if month:
        parts.append(f"{month}월")
    return " · ".join(parts)


def names_from_files(root: Path) -> dict[str, str]:
    """페르소나와 방문 조건의 이름을 자료 폴더의 정의 파일에서 읽는다 (식별자 → 이름).

    AI 답을 받지 못한 방문은 저장된 응답에 이름이 없어, 이것이 없으면 화면에 식별자가 그대로 나온다 (11-16, T109).
    """
    names: dict[str, str] = {}
    for path in sorted((root / "personas").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("persona_id"), str) and isinstance(data.get("name"), str):
            names[data["persona_id"]] = data["name"]
    bundle = root / "engine" / "conditions.json"
    try:
        conditions = json.loads(bundle.read_text(encoding="utf-8")).get("conditions", []) if bundle.is_file() else []
        for c in conditions:
            label = _condition_label(c["occasion"], c.get("meal"), c["day_type"], c.get("stay"), c.get("month"))
            names[c["condition_id"]] = label
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return names


def party_label(condition: RunCondition) -> str:
    people = f"어른 {condition.adults}명" + (f", 어린이 {condition.children}명" if condition.children else "")
    basis = "1인" if condition.budget.basis == "per_person" else "일행"
    return f"{people} · 예산 {basis} 보통 {won(condition.budget.typical)}, 최대 {won(condition.budget.max)}"


def persona_names(run: LoadedRun) -> dict[str, str]:
    """persona_id → 이름. 저장된 응답이 없는 페르소나(모든 방문이 실패)는 식별자를 그대로 쓴다."""
    names = {persona_id: persona_id for persona_id in run.record.persona_ids}
    for saved in run.responses.values():
        persona = saved.request.persona
        if isinstance(persona.get("name"), str):
            names[persona["persona_id"]] = persona["name"]
    return names


def condition_names(run: LoadedRun) -> dict[str, str]:
    """condition_id → 한국어 뜻. 저장된 응답이 없는 조건은 식별자를 그대로 쓴다."""
    names = {condition_id: condition_id for condition_id in run.record.condition_ids}
    for saved in run.responses.values():
        names[saved.request.condition.condition_id] = condition_label(saved.request.condition)
    return names


@dataclass
class BoughtLine:
    product: str
    quantity: int
    unit: str | None
    list_price: int
    discount: int
    paid: int


@dataclass
class NotChosen:
    venue: str
    kind: str
    cheapest: int | None
    pain_labels: list[str]
    text: str


@dataclass
class VisitView:
    """방문 하나의 실행 결과. 화면은 이것을 그리기만 한다."""

    persona_id: str
    condition_id: str
    found: bool = False
    failed_reason: str | None = None
    choice_kind: str = "none"
    venue: str | None = None
    venue_detail: str | None = None
    lines: list[BoughtLine] = field(default_factory=list)
    total_paid: int = 0
    revenue_net: int = 0
    # 일부 달에만 파는 상품을 골라 이 업장으로 센 몫 (1 이면 늘 판다).
    counted_share: float = 1.0
    reason_labels: list[str] = field(default_factory=list)
    reason_text: str | None = None
    used_attributes: list[str] = field(default_factory=list)
    llm_call: str | None = None
    condition: RunCondition | None = None
    not_chosen: list[NotChosen] = field(default_factory=list)


def visit_view(run: LoadedRun, persona_id: str, condition_id: str) -> VisitView:
    """페르소나와 방문 조건을 하나씩 골랐을 때의 결과."""
    view = VisitView(persona_id, condition_id)
    rows = [r for r in run.rows if r.persona_id == persona_id and r.condition_id == condition_id]
    if not rows:
        return view
    view.found = True
    failed = next((r for r in rows if r.status == "failed"), None)
    if failed is not None:
        view.failed_reason = failed.fail_reason
        return view

    # 파는 달이 아닌 몫을 "이용하지 않음"으로 센 줄은 고른 것이 아니다 (engine.ledger.visit_rows).
    chosen = [r for r in rows if r.reason_text != SEASON_GAP_REASON] or rows
    first = chosen[0]
    view.choice_kind = first.choice_kind
    view.reason_labels = first.reason_labels
    view.reason_text = first.reason_text
    view.used_attributes = first.used_attributes
    view.llm_call = first.llm_call
    view.counted_share = first.counted_share

    saved = run.responses.get(first.request_hash) if first.request_hash else None
    candidates = {c.venue_id: c for c in saved.request.candidates} if saved else {}
    if saved:
        view.condition = saved.request.condition

    if first.choice_kind != "none":
        candidate = candidates.get(first.venue_id or "")
        product_names: dict[str, str] = {}
        if candidate:
            view.venue = candidate.name
            view.venue_detail = f"{candidate.hotel} · {candidate.cuisine} · {KO['choice_kind'][first.choice_kind]}"
            product_names = {line.product_id: line.name for o in candidate.options for line in o.lines}
            product_names |= {addon.product_id: addon.name for addon in candidate.addons}
        else:
            view.venue = first.venue_id
            view.venue_detail = KO["choice_kind"][first.choice_kind]
        for row in chosen:
            view.lines.append(
                BoughtLine(
                    product=product_names.get(row.product_id or "", row.product_id or ""),
                    quantity=row.quantity,
                    unit=row.unit,
                    list_price=row.list_price,
                    discount=row.discount,
                    paid=row.paid,
                )
            )
        view.total_paid = sum(line.paid for line in view.lines)
        view.revenue_net = sum(row.revenue_net for row in chosen)

    if saved:
        mentioned = set()
        for rejected in saved.response.rejected:
            mentioned.add(rejected.venue_id)
            view.not_chosen.append(_not_chosen(candidates.get(rejected.venue_id), rejected.venue_id, rejected.pain_labels, rejected.text))
        # 후보였는데 고르지도, 고르지 않은 이유를 적지도 않은 업장도 빠뜨리지 않고 보여 준다.
        for venue_id, candidate in candidates.items():
            if venue_id != first.venue_id and venue_id not in mentioned:
                view.not_chosen.append(_not_chosen(candidate, venue_id, [], "이유를 적지 않았다"))
    return view


def _not_chosen(candidate, venue_id: str, pain_labels: list[str], text: str) -> NotChosen:
    if candidate is None:
        return NotChosen(venue_id, "후보에 없던 업장", None, pain_labels, text)
    kind = KO["choice_kind"]["competitor" if candidate.is_competitor else "walkerhill"]
    prices = [o.total for o in candidate.options] or [a.unit_price for a in candidate.addons]
    return NotChosen(candidate.name, kind, min(prices) if prices else None, pain_labels, text)


def run_notices(run: LoadedRun) -> list[str]:
    """실행 전체에 대해 화면 위에 알릴 것 (README 의 "시뮬레이션을 돌린다")."""
    record = run.record
    notices = []
    if record.status == "stopped_by_limit":
        notices.append("호출 상한에 닿아 멈춘 실행입니다. 원장에 방문이 일부만 있습니다.")
    elif record.status == "failed":
        notices.append("끝까지 돌지 못한 실행입니다. 원장에 방문이 일부만 있습니다.")
    if record.counts.failed:
        notices.append(f"실패한 방문이 {record.counts.failed}건 있습니다. 실패한 방문은 합계에 들어가지 않습니다.")
    if run.rejected_files:
        notices.append(f"검사에서 어긋난 응답이 {run.rejected_files}건 있습니다 (실행 폴더의 llm_rejected/).")
    return notices


def visit_table(run: LoadedRun) -> list[dict]:
    """실행의 모든 방문을 한 줄씩. 한 방문이 상품 여러 줄이면 금액을 더한다."""
    personas = persona_names(run)
    conditions = condition_names(run)
    table = []
    for persona_id in run.record.persona_ids:
        for condition_id in run.record.condition_ids:
            view = visit_view(run, persona_id, condition_id)
            if not view.found:
                continue
            if view.failed_reason:
                chosen = f"실패: {view.failed_reason}"
            elif view.choice_kind == "none":
                chosen = KO["choice_kind"]["none"]
            else:
                chosen = view.venue or ""
            table.append(
                {
                    "페르소나": personas[persona_id],
                    "방문 조건": conditions[condition_id],
                    "고른 곳": chosen,
                    "낸 금액 (가상, 원)": view.total_paid,
                    "워커힐 매출 (가상, 세금 뺀 원)": view.revenue_net,
                    "고른 이유": view.reason_text or "",
                }
            )
    return table
