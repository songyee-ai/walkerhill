"""상황별 비교: 기준 실행과 상황 실행을 짝지어 "누가 어디서 어디로 옮겼나"를 낸다 (T21, docs/PRD.md 9절의 3).

두 실행은 같은 페르소나, 같은 방문 조건, 같은 가중치로 돈다 (상황 실행의 `weights_from` 이 기준 실행이다).
그래서 방문(페르소나 × 방문 조건)마다 두 실행의 선택을 그대로 견줄 수 있다. 금액은 원장에서만 낸다.
"""

from dataclasses import dataclass, field
from pathlib import Path

from app.results import LoadedRun, condition_names, load_run, persona_names, visit_view
from engine.formats import SUMMARY_COLUMNS
from engine.formats.io import read_csv
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
    # 그 방문이 대표하는 손님 수 (가상). 지도의 점 크기에 쓴다.
    represented: float
    reason_after: str | None
    fail_reason: str | None = None


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

    def count(self, move: str) -> int:
        return sum(1 for m in self.moves if m.move == move)


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
    )


def summary_groups(root: Path, data_mode: str) -> list[str]:
    """집계 파일에 있는 고객군. 페르소나가 없는 고객군을 "다루지 않은 고객군"으로 보여 주려고 읽는다 (PRD 4절)."""
    path = root / ("data/samples/base_summary.csv" if data_mode == "sample" else "private/base/summary.csv")
    if not path.is_file():
        return []
    return sorted({row["customer_group"] for row in read_csv(path, SUMMARY_COLUMNS) if row["customer_group"]})
