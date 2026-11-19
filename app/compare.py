"""상황별 비교: 기준 실행과 상황 실행을 짝지어 "누가 어디서 어디로 옮겼나"를 낸다 (T21, docs/PRD.md 9절의 3).

두 실행은 같은 페르소나, 같은 방문 조건, 같은 가중치로 돈다 (상황 실행의 `weights_from` 이 기준 실행이다).
그래서 방문(페르소나 × 방문 조건)마다 두 실행의 선택을 그대로 견줄 수 있다. 금액은 원장에서만 낸다.
"""

from dataclasses import dataclass, field, replace
from pathlib import Path

from app.breakdown import Breakdown, average, load_breakdown
from app.results import LoadedRun, condition_names, load_run, persona_names, visit_view
from engine.formats import SUMMARY_COLUMNS
from engine.formats.io import read_csv
from engine.formats.run import VISIT_ID_SEPARATOR
from engine.ledger import venue_shares

# 선택이 어떻게 바뀌었나. 순서는 화면에 보여 주는 순서다.
MOVE_LABEL = {
    "out": "워커힐 밖으로 나감",
    "in": "워커힐로 들어옴",
    "inside": "워커힐 안에서 옮김",
    "other": "워커힐 밖에서 옮김",
    "same": "그대로",
    "failed": "AI 답 못 받음",
}


@dataclass(frozen=True)
class Place:
    """방문이 간 곳. kind 는 walkerhill / competitor / none / failed 다."""

    kind: str
    venue_id: str | None = None


@dataclass
class Move:
    persona_id: str
    condition_id: str
    persona: str
    condition: str
    before: Place
    after: Place
    move: str
    # 그 방문이 대표하는 방문 수(팀 수, 가상). 11-19 T210 뒤로 방문의 무게가 인원에서 낸 팀 수다. 지도의 점 크기에 쓴다.
    represented: float
    reason_after: str | None
    fail_reason: str | None = None
    # 상황과 상관없어 기본 시나리오의 답을 그대로 쓴 방문 (실행 기록의 `baseline_answers`, T210 의 임시 규칙. FORMATS.md 10.1절).
    # 화면에 그 수와 표시를 보인다 (T128). T212 에서 규칙이 없어지면 엔진이 목록을 쓰지 않아 저절로 False 다.
    kept_baseline: bool = False


@dataclass
class VenueChange:
    venue_id: str
    name: str
    before: int
    after: int

    @property
    def diff(self) -> int:
        return self.after - self.before


@dataclass
class Comparison:
    base: LoadedRun
    scen: LoadedRun
    moves: list[Move]
    venues: list[VenueChange]
    names: dict[str, str]
    total_before: int
    total_after: int
    uncovered_groups: list[str] = field(default_factory=list)
    # 엔진이 쓴 매출 변화 나누기 (app/breakdown.py, T124). 11-19 T210 전의 실행에는 없다.
    breakdown: Breakdown | None = None

    def count(self, move: str) -> int:
        return sum(1 for m in self.moves if m.move == move)

    @property
    def kept_count(self) -> int:
        """기본 시나리오의 답을 그대로 쓴 방문의 수 (T128)."""
        return sum(1 for m in self.moves if m.kept_baseline)


def baseline_dir_of(scen_dir: Path) -> Path:
    """상황 실행이 가중치를 가져온 기준 실행의 폴더. 같은 실행 폴더들 안에 있다."""
    record = load_run(scen_dir).record
    if record.weights_from is None:
        raise ValueError(f"실행 '{record.run_id}' 는 기준 상황의 실행이라 견줄 기준이 없다")
    return scen_dir.parent / record.weights_from


def _named(names: dict[str, str]) -> dict[str, str]:
    """이름을 찾은 것만 남긴다 (찾지 못하면 식별자를 그대로 이름으로 쓴다)."""
    return {k: v for k, v in names.items() if k != v}


def classify(before: Place, after: Place) -> str:
    if "failed" in (before.kind, after.kind):
        return "failed"
    if before == after:
        return "same"
    if before.kind == "walkerhill" and after.kind == "walkerhill":
        return "inside"
    if before.kind == "walkerhill":
        return "out"
    if after.kind == "walkerhill":
        return "in"
    return "other"


def venue_names(*runs: LoadedRun) -> dict[str, str]:
    """venue_id → 업장 이름. 저장된 답의 후보에서 모은다."""
    names: dict[str, str] = {}
    for run in runs:
        for saved in run.responses.values():
            for candidate in saved.request.candidates:
                names[candidate.venue_id] = candidate.name
    return names


def _place(run: LoadedRun, persona_id: str, condition_id: str) -> tuple[Place, float, str | None, str | None]:
    view = visit_view(run, persona_id, condition_id)
    rows = [r for r in run.rows if r.persona_id == persona_id and r.condition_id == condition_id]
    represented = max((r.represented for r in rows), default=0.0)
    if not view.found:
        return Place("failed"), represented, None, "이 실행에 없는 방문"
    if view.failed_reason:
        return Place("failed"), represented, None, view.failed_reason
    venue_id = next((r.venue_id for r in rows if r.choice_kind == view.choice_kind and r.venue_id), None)
    return Place(view.choice_kind, venue_id), represented, view.reason_text, None


def compare(
    base: LoadedRun, scen: LoadedRun, summary_groups: list[str] | None = None, file_names: dict[str, str] | None = None
) -> Comparison:
    """방문마다 두 실행의 선택을 견주고, 업장별 가상 매출의 변화를 낸다.

    `file_names` 는 정의 파일에서 읽은 페르소나·방문 조건의 이름이다 (`app.results.names_from_files`).
    AI 답을 받지 못한 방문도 식별자가 아니라 이름으로 보이게 한다.
    """
    file_names = file_names or {}
    personas = {k: file_names.get(k, v) for k, v in persona_names(base).items()} | _named(persona_names(scen))
    conditions = {k: file_names.get(k, v) for k, v in condition_names(base).items()} | _named(condition_names(scen))
    kept = set(scen.record.baseline_answers or [])
    moves = []
    for persona_id in base.record.persona_ids:
        for condition_id in base.record.condition_ids:
            before, represented, _, fail_before = _place(base, persona_id, condition_id)
            after, represented_after, reason, fail_after = _place(scen, persona_id, condition_id)
            moves.append(
                Move(
                    persona_id,
                    condition_id,
                    personas.get(persona_id, persona_id),
                    conditions.get(condition_id, condition_id),
                    before,
                    after,
                    classify(before, after),
                    represented or represented_after,
                    reason,
                    fail_after or fail_before,
                    f"{persona_id}{VISIT_ID_SEPARATOR}{condition_id}" in kept,
                )
            )
    # AI 답을 받지 못한 방문은 두 실행 모두에서 매출에 넣지 않는다. 넣으면 답이 없는 쪽만 0원이 되어
    # 매출이 -100% 처럼 보인다 (11-16, T109 에서 찾음). 화면은 빠진 건수를 따로 알린다.
    missing = {(m.persona_id, m.condition_id) for m in moves if m.move == "failed"}
    shares_before = venue_shares([r for r in base.rows if (r.persona_id, r.condition_id) not in missing])
    shares_after = venue_shares([r for r in scen.rows if (r.persona_id, r.condition_id) not in missing])
    names = venue_names(base, scen)
    ids = sorted(set(shares_before["walkerhill"]) | set(shares_after["walkerhill"]))
    venues = [
        VenueChange(
            venue_id,
            names.get(venue_id, venue_id),
            shares_before["walkerhill"].get(venue_id, {}).get("weighted_revenue", 0),
            shares_after["walkerhill"].get(venue_id, {}).get("weighted_revenue", 0),
        )
        for venue_id in ids
    ]
    groups = {r.customer_group for r in base.rows}
    uncovered = sorted(set(summary_groups or []) - groups)
    return Comparison(
        base,
        scen,
        moves,
        venues,
        names,
        shares_before["walkerhill_total"],
        shares_after["walkerhill_total"],
        uncovered,
        _matching_breakdown(scen, base, shares_after["walkerhill_total"] - shares_before["walkerhill_total"]),
    )


def _matching_breakdown(scen: LoadedRun, base: LoadedRun, diff: int) -> Breakdown | None:
    """상황 실행의 매출 변화 나누기. 두 원장으로 낸 매출 변화와 같을 때만 쓴다 (빼는 방문이 같아야 같다. FORMATS.md 10.6절)."""
    found = load_breakdown(scen.run_dir, scen.record.run_id, base.record.run_id)
    return found if found is not None and found.total == diff else None


def combine_months(per_month: list[tuple[int, "Comparison"]]) -> "Comparison":
    """기간의 달마다 낸 비교를 하나로 합친다 (11-17, 화면의 "X월 ~ Y월").

    엔진은 달 하나로 돌고, 달을 주면 그 달의 인원으로 가중치를 낸다 (FORMATS.md 10.1절 "실행의 달". 11-19 T210 전에는 일 년 합계에 맞췄다).
    화면은 달마다의 매출을 더하지 않고 **달 평균**을 낸다 (한 달 규모). 같은 달의 기준과 상황끼리만 견준 값을 평균하므로
    "달이 다른 실행끼리 합계를 견주지 않는다"는 엔진 담당의 당부를 지킨다. 방문은 달을 붙여 모두 보이고,
    방문 수가 달 수만큼 불지 않게 방문이 대표하는 팀 수도 달 수로 나눈다.
    """
    if len(per_month) == 1:
        return per_month[0][1]
    n = len(per_month)
    moves = [
        replace(m, condition=m.condition if f"{month}월" in m.condition else f"{m.condition} · {month}월", represented=m.represented / n)
        for month, comparison in per_month
        for m in comparison.moves
    ]
    before: dict[str, int] = {}
    after: dict[str, int] = {}
    names: dict[str, str] = {}
    for _, comparison in per_month:
        names |= comparison.names
        for change in comparison.venues:
            before[change.venue_id] = before.get(change.venue_id, 0) + change.before
            after[change.venue_id] = after.get(change.venue_id, 0) + change.after
    venues = [
        VenueChange(venue_id, names.get(venue_id, venue_id), round(before[venue_id] / n), round(after.get(venue_id, 0) / n))
        for venue_id in sorted(before)
    ]
    first = per_month[0][1]
    found = [c.breakdown for _, c in per_month]
    return Comparison(
        first.base,
        first.scen,
        moves,
        venues,
        names,
        round(sum(c.total_before for _, c in per_month) / n),
        round(sum(c.total_after for _, c in per_month) / n),
        first.uncovered_groups,
        # 한 달이라도 나누기가 없으면 평균을 내지 않는다 (빠진 달이 0 으로 섞이면 갈래가 작아 보인다)
        average([b for b in found if b is not None]) if all(found) else None,
    )


def zero_groups(per_month: list[tuple[int | None, "Comparison"]]) -> dict[str, list[int | None]]:
    """고객군 배수가 0 인 고객군과 그 달 (팀장 요청, 11-17).

    그 달의 집계 파일에 인원이 없는 고객군은 배수가 0 이고, 그 실행에서 그 고객군의 가상 매출은 0 이다
    (FORMATS.md 10.1절 "실행의 달". 11-19 T210 전에는 "워커힐 업장을 고른 방문이 없어 배수를 맞출 수 없음"이었다. T127). 기간의 달 평균에 0 이 섞이면 평균이 낮아지므로 화면에 알린다. 달 없이 돌렸으면 달은 None 이다.
    """
    found: dict[str, list[int | None]] = {}
    for month, comparison in per_month:
        for group, value in comparison.base.record.weights.group_multiplier.items():
            if value == 0:
                found.setdefault(group, []).append(month)
    return found


def summary_groups(root: Path, data_mode: str) -> list[str]:
    """집계 파일에 있는 고객군. 페르소나가 없는 고객군을 "다루지 않은 고객군"으로 보여 주려고 읽는다 (PRD 4절)."""
    path = root / ("data/samples/base_summary.csv" if data_mode == "sample" else "private/base/summary.csv")
    if not path.is_file():
        return []
    return sorted({row["customer_group"] for row in read_csv(path, SUMMARY_COLUMNS) if row["customer_group"]})
