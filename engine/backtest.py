"""6단계의 되돌려 맞혀 보기: 과거의 사건을 그 전까지의 자료로 돌려 실제와 견준다 (docs/PRD.md 8절의 6단계, 6.6절, 12절. T224).

    uv run python -m engine.backtest find --data private
    uv run python -m engine.backtest score --data private --events private/backtest/events.json

시뮬레이터에게 답을 가린 시험을 보게 한다. 과거에 실제로 있었던 가격 변경·프로모션(사건)마다,
사건이 있던 달의 앞 달까지의 자료만으로 기준 상황과 그 사건의 상황을 돌리고(엔진의 `--data-until`),
그 예측을 사건 뒤에 실제로 일어난 일과 견준다. LLM 을 부르지 않는다 (엔진이 돌려 둔 실행 폴더를 읽는다).

- **실제 변화** (11-20 wilstein91 결정): 집계 파일(FORMATS 8절)에서 사건 업장의 사람 수를 사건 전 3달과 사건 달부터 3달로 견주고,
  같은 동안의 바뀌지 않은 워커힐 업장의 변화로 나눈다 (이중 차분: (사건 업장의 뒤 ÷ 앞) ÷ (견줄 업장들의 뒤 ÷ 앞) − 1). 철 효과가 빠진다.
- **예측 변화**: 같은 셈을 시뮬레이터의 두 실행에 한다. 앞은 기준 실행, 뒤는 사건의 상황 실행이다 (양쪽을 같은 잣대로 잰다).
- **잣대**: 사람 수로 채점하고 합격을 정한다. 매출(세금 뺀)도 같은 셈으로 채점해 적는다. 매출의 방향은 "가격에 민감한 곳인가"를 맞혔는지 보는 해석용이다.
- **변화 없음**: 실제 쪽은 같은 업장에서 사건이 없던 달들로 같은 셈을 해 본 가짜 사건의 가장 큰 흔들림보다 작으면 변화 없음이다.
  예측 쪽은 기준 실행을 한 번 더 물은 답(`repeat_ledger.csv`, 2단계의 흔들림 폭)으로 잰 폭보다 작으면 변화 없음이다. 그 답이 없으면 폭을 0 으로 보고 결과에 `null` 로 남긴다.
- **크기**: 실제가 변화 없음이 아닐 때, 예측 ÷ 실제가 0.5 ~ 2 면 맞음이다. 4단계(T222)가 k 를 맞추는 데 쓴 상황은 통째로 빼고,
  쓴 구간(이용 상황 × 평일 주말)과 겹치는 방문은 빼고 나머지로 잰다 (`elasticity.json` 의 `fitted_on`).
- **합격**: 채점한 사건이 5건 이상이고, 사람 수의 방향을 2/3 이상 맞히고, 크기를 채점한 사건의 절반 이상이 맞으면 합격이다.
  크기를 채점한 사건이 없으면 방향만 본다 (그때는 크기를 말하지 않는다, PRD 12절).

사건 목록은 `find` 가 자료에서 가격이 바뀐 달을 찾아 초안을 쓰고, 사람(또는 클로드)이 검토해 확정한다.
기본 데이터로 만든 사건 목록, 상황, 결과에는 내부 수치가 들어 있어 `private/` 에만 둔다.
"""

import argparse
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from engine.constants import constant
from engine.formats.backtest import (
    BacktestEvent,
    BacktestEvents,
    BacktestResult,
    Criteria,
    EventResult,
    FittedOn,
    Magnitude,
    Measure,
    Tally,
)
from engine.formats.codes import WALKERHILL_VENUE_IDS
from engine.formats.io import read_csv, read_json, read_model, write_json
from engine.formats.persona import Persona
from engine.formats.run import LEDGER_COLUMNS, LedgerRow, RunRecord
from engine.formats.scenario import BASELINE_ID, Scenario
from engine.formats.summary import SummaryRow
from engine.formats.venue import Venue
from engine.runner import load_inputs, runs_folder, scenario_path, summary_hash
from engine.weights import average_parties, party_size, people_of, read_summary, summary_path

EXIT_OK, EXIT_FAILED = 0, 1

# ── 채점의 기준 (PRD 6.6절. 11-20 wilstein91 결정. 돌려 본 뒤에 바꾸지 않는다) ──
WINDOW_BEFORE = 3
WINDOW_AFTER = 3
MAGNITUDE_LOW, MAGNITUDE_HIGH = 0.5, 2.0
DIRECTION_PASS = 2 / 3  # `verdict` 는 정수로 견준다 (3 × 맞음 ≥ 2 × 채점)
MAGNITUDE_PASS = 0.5  # `verdict` 는 2 × 맞음 ≥ 크기 채점
MIN_EVENTS = 5
CRITERIA = Criteria(
    metric="people",
    window_before=WINDOW_BEFORE,
    window_after=WINDOW_AFTER,
    magnitude_low=MAGNITUDE_LOW,
    magnitude_high=MAGNITUDE_HIGH,
    direction_pass=round(DIRECTION_PASS, 6),
    magnitude_pass=MAGNITUDE_PASS,
    min_events=MIN_EVENTS,
)
# 집계 파일은 한 해의 1 ~ 12월이다 (8절). 앞뒤 3달씩이 들어가는 사건 달은 4 ~ 10월이다.
FIRST_MONTH = 1 + WINDOW_BEFORE
LAST_MONTH = 12 - WINDOW_AFTER + 1
# 다른 사건이 이 거리(달) 안에 있으면 창이 섞인다: 사건 달이 [m − 2, m + 2] 이면 앞 창(첫 달 뒤)이나 뒤 창에 걸린다.
OVERLAP = WINDOW_BEFORE - 1

# ── 사건 찾기의 기준 (11-20 wilstein91 결정) ──
# 상품의 평균 가격(낸 금액 ÷ 수량)이 이만큼 바뀌어 머물면 가격 변경 후보다.
STEP_MIN = 0.03
# 한 수준에 머무는 것으로 보는 폭 (할인 쿠폰이 섞여 달마다 조금씩 흔들리는 것).
LEVEL_TOL = 0.015
# 가격 변경이 아니라 한두 달만 바뀌었다 돌아온 것 (할인·프로모션 후보)의 길이.
TEMPORARY_MAX = 2

Slice = tuple[str, str]  # (이용 상황, 평일 주말)


# ── 셈 ────────────────────────────────────────────────────────────────────


def did(target_before: float, target_after: float, control_before: float, control_after: float) -> float | None:
    """이중 차분: (사건 업장의 뒤 ÷ 앞) ÷ (견줄 업장의 뒤 ÷ 앞) − 1. 하나라도 0 이면 낼 수 없다 (None)."""
    if min(target_before, target_after, control_before, control_after) <= 0:
        return None
    return (target_after / target_before) / (control_after / control_before) - 1


def direction(change: float, band: float) -> str:
    """변화가 폭보다 크면 늘었다(up)·줄었다(down), 아니면 변화 없음(none)."""
    if change > band:
        return "up"
    if change < -band:
        return "down"
    return "none"


def magnitude_correct(predicted: float, actual: float) -> tuple[float, bool]:
    """(예측 ÷ 실제, 0.5 ~ 2 안인가). 방향이 반대면 비율이 0 보다 작아 늘 틀림이다."""
    ratio = predicted / actual
    return ratio, MAGNITUDE_LOW <= ratio <= MAGNITUDE_HIGH


def windows(month: int) -> tuple[list[int], list[int]]:
    """사건 달의 앞 창(사건 전 3달)과 뒤 창(사건 달부터 3달)."""
    return list(range(month - WINDOW_BEFORE, month)), list(range(month, month + WINDOW_AFTER))


def verdict(scored: int, direction_ok: int, magnitude_scored: int, magnitude_ok: int) -> str:
    """합격(pass), 불합격(fail), 건수 부족(too_few)."""
    if scored < MIN_EVENTS:
        return "too_few"
    # 2/3 은 소수로 끝나지 않아 정수로 견준다 (결과 파일의 `direction_pass` 는 소수 여섯째 자리까지 적은 같은 값이다).
    if 3 * direction_ok < 2 * scored:
        return "fail"
    if magnitude_scored and 2 * magnitude_ok < magnitude_scored:
        return "fail"
    return "pass"


# ── 실제 자료 (집계 파일) ─────────────────────────────────────────────────


@dataclass
class Table:
    """업장·달·(이용 상황, 평일 주말)마다의 사람 수와 매출."""

    people: dict[tuple[str, int, Slice], float] = field(default_factory=lambda: defaultdict(float))
    revenue: dict[tuple[str, int, Slice], float] = field(default_factory=lambda: defaultdict(float))

    def total(self, metric: str, venues: list[str] | set[str], months: list[int], excluded: set[Slice]) -> float:
        cells = self.people if metric == "people" else self.revenue
        return sum(v for (venue, month, sl), v in cells.items() if venue in venues and month in months and sl not in excluded)

    def venues(self) -> set[str]:
        return {venue for venue, _, _ in self.people} | {venue for venue, _, _ in self.revenue}


def actual_table(rows: list[SummaryRow], parties: dict[str, float]) -> Table:
    """집계 파일의 워커힐 업장 줄을 업장·달·조각마다 더한다. 사람 수는 가중치와 같은 셈이다 (`engine.weights.people_of`).

    조식은 넣지 않는다. 방문 조건 묶음에 없어 시뮬레이터가 돌리지 않으므로, 넣으면 실제 쪽에만 다른 손님이 섞인다 (가중치도 조식을 뺀다, 8절).
    """
    fallback = sum(parties.values()) / len(parties) if parties else 1.0
    table = Table()
    for row in rows:
        if row.venue_id not in WALKERHILL_VENUE_IDS or row.meal == "breakfast":
            continue
        key = (row.venue_id, row.month, (row.occasion, row.day_type))
        table.people[key] += people_of(row, parties.get(row.customer_group, fallback))
        table.revenue[key] += row.revenue_net
    return table


def busy(venue: str, month: int, events: list[BacktestEvent], skip: BacktestEvent | None = None) -> bool:
    """그 업장에 이 달의 창과 섞이는 사건이 있는가 (`skip` 은 빼고).

    가격 변경은 바뀐 뒤에 머물러, 사건 달이 [이 달 − 2, 이 달 + 2] 일 때만 창이 섞인다. 프로모션은 끝나면 원래대로 돌아가
    이 달의 앞 창이 프로모션 동안(사건 달부터 3달로 본다)에 걸려도 섞인다: 사건 달이 [이 달 − 5, 이 달 + 2] 다.
    """
    def near(e: BacktestEvent) -> bool:
        after = OVERLAP + (WINDOW_AFTER if e.kind == "promotion" else 0)
        return -OVERLAP <= month - e.start_month <= after

    return any(e is not skip and e.venue_id == venue and near(e) for e in events)


def controls(month: int, target: str, events: list[BacktestEvent], changed: set[str], present: set[str]) -> list[str]:
    """견줄 업장: 자료에 있는 워커힐 업장 가운데 사건 업장, 상황이 바꾼 업장, 창과 섞이는 사건이 있는 업장을 뺀 것."""
    return sorted(v for v in present if v != target and v not in changed and not busy(v, month, events))


def actual_change(table: Table, metric: str, target: str, control: list[str], month: int, excluded: set[Slice]) -> float | None:
    before, after = windows(month)
    return did(
        table.total(metric, [target], before, excluded),
        table.total(metric, [target], after, excluded),
        table.total(metric, control, before, excluded),
        table.total(metric, control, after, excluded),
    )


def actual_band(table: Table, metric: str, target: str, events: list[BacktestEvent], excluded: set[Slice]) -> float | None:
    """가짜 사건의 가장 큰 흔들림: 사건 업장에 사건이 없던 달마다 같은 셈을 해 본 값의 절댓값 가운데 가장 큰 것. 낼 수 없으면 None."""
    present = table.venues()
    found = []
    for month in range(FIRST_MONTH, LAST_MONTH + 1):
        if busy(target, month, events):
            continue
        control = controls(month, target, events, set(), present)
        change = actual_change(table, metric, target, control, month, excluded) if control else None
        if change is not None:
            found.append(abs(change))
    return max(found) if found else None


# ── 시뮬레이터 (실행 폴더) ────────────────────────────────────────────────


def sim_table(
    rows: list[LedgerRow], parties: dict[str, int], slices: dict[str, Slice], visits: set[str] | None = None
) -> tuple[dict[tuple[str, Slice], float], dict[tuple[str, Slice], float]]:
    """원장에서 업장·조각마다의 사람 수와 가중 매출. 사람 수 = 대표하는 수 × 일행 수 × 파는 달의 몫 × 고른 몫 (방문·업장마다 한 번).

    `visits` 를 주면 그 방문만 센다 (흔들림 폭을 짝지은 방문으로만 잴 때).
    """
    people: dict[tuple[str, Slice], float] = defaultdict(float)
    revenue: dict[tuple[str, Slice], float] = defaultdict(float)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if row.status != "ok" or row.choice_kind != "walkerhill" or row.venue_id is None:
            continue
        if visits is not None and row.visit_id not in visits:
            continue
        sl = slices.get(row.condition_id)
        if sl is None:
            raise ValueError(f"원장의 방문 조건 '{row.condition_id}' 이 조건 묶음에 없다")
        key = (row.venue_id, sl)
        revenue[key] += row.weighted_revenue
        if (row.visit_id, row.venue_id) not in seen:
            seen.add((row.visit_id, row.venue_id))
            party = parties.get(row.persona_id)
            if party is None:
                raise ValueError(f"원장의 페르소나 '{row.persona_id}' 의 정의가 없다")
            people[key] += row.represented * party * row.counted_share * row.choice_share
    return people, revenue


def _sum(cells: dict[tuple[str, Slice], float], venues: list[str], excluded: set[Slice]) -> float:
    return sum(v for (venue, sl), v in cells.items() if venue in venues and sl not in excluded)


def _ledger(run_dir: Path, name: str = "ledger.csv") -> list[LedgerRow]:
    return [LedgerRow.from_row(row) for row in read_csv(run_dir / name, LEDGER_COLUMNS)]


def predicted_band(
    base_dir: Path, base_rows: list[LedgerRow], target: str, parties: dict[str, int], slices: dict[str, Slice], metric: str
) -> float | None:
    """2단계의 흔들림 폭(10.6절)과 같은 짝 셈을 사람 수로: z × √Σ(다시 물은 답 − 기준 답)² ÷ 기준의 사건 업장 값.

    기준 실행 폴더에 다시 물은 원장(`repeat_ledger.csv`)이 없으면 None 이다 (폭을 재지 못함).
    """
    path = base_dir / "repeat_ledger.csv"
    if not path.is_file():
        return None
    try:
        z = float(constant("wobble-band-z"))
    except KeyError as exc:
        raise ValueError("다시 물은 원장이 있는데 결정 상수 wobble-band-z 가 없다 (engine/constants.json)") from exc
    pick = 0 if metric == "people" else 1
    by_visit: dict[str, tuple[list[LedgerRow], list[LedgerRow]]] = defaultdict(lambda: ([], []))
    for row in base_rows:
        by_visit[row.visit_id][0].append(row)
    repeated = set()
    for row in _ledger(base_dir, "repeat_ledger.csv"):
        if row.status == "ok":
            by_visit[row.visit_id][1].append(row)
            repeated.add(row.visit_id)
    squares = 0.0
    for visit in repeated:
        base, again = by_visit[visit]
        squares += (_sum(sim_table(again, parties, slices)[pick], [target], set()) - _sum(sim_table(base, parties, slices)[pick], [target], set())) ** 2
    whole = sim_table(base_rows, parties, slices)[pick]
    level = _sum(whole, [target], set())
    return None if level <= 0 else z * math.sqrt(squares) / level


def find_runs(root: Path, data_mode: str, event: BacktestEvent) -> tuple[RunRecord | None, RunRecord | None, str | None]:
    """사건의 기준 실행(`data_until` = 사건 달 − 1, 일 년 전체, 끝까지 돎, 실패 없음)과 그 가중치로 돈 상황 실행. 가장 새것이다."""
    until = event.start_month - 1
    records = []
    for path in sorted(runs_folder(root, data_mode).glob("*/run.json"), reverse=True):
        try:
            records.append(read_model(path, RunRecord))
        except (OSError, ValueError):
            continue
    good = [r for r in records if r.status == "ok" and not r.counts.failed and r.month is None]
    base = next((r for r in good if r.scenario_id == BASELINE_ID and r.data_until == until), None)
    if base is None:
        return None, None, f"{until}월까지의 자료로 끝까지 돈 기준 실행이 없다 (엔진을 --data-until {until} 으로 돌린다)"
    scen = next((r for r in good if r.scenario_id == event.scenario_id and r.weights_from == base.run_id), None)
    if scen is None:
        return base, None, f"기준 실행 {base.run_id} 의 가중치로 돈 상황 '{event.scenario_id}' 의 실행이 없다"
    return base, scen, None


# ── 4단계에서 맞춘 것 ─────────────────────────────────────────────────────


def read_fitted(elasticity_file: Path, segments_file: Path, root: Path) -> tuple[FittedOn, dict[str, set[Slice]]]:
    """`elasticity.json` 의 `fitted_on`(10.8절)과 구간의 정의 파일에서, 빼야 할 상황과 업장마다 빼야 할 조각을 읽는다.

    구간의 페르소나 조건(`personas`, `exclude_personas`)은 보지 않는다: 집계 파일에는 페르소나가 없어 실제 쪽에서 가를 수 없다.
    그래서 양쪽 모두 그 업장의 (이용 상황, 평일 주말) 조각을 통째로 뺀다 (더 넓게 빼는 쪽이다).
    """
    fitted = read_json(elasticity_file).get("fitted_on")
    if not isinstance(fitted, dict):
        raise ValueError(f"{elasticity_file} 에 fitted_on 이 없다 (4단계 결과 파일이 아니다)")
    scenarios = sorted({run["scenario_id"] for run in fitted.get("price_runs", [])})
    segment_ids = list(fitted.get("segments", []))
    defined = {s["segment_id"]: s for s in read_json(segments_file).get("segments", [])}
    excluded: dict[str, set[Slice]] = defaultdict(set)
    for segment_id in segment_ids:
        segment = defined.get(segment_id)
        if segment is None:
            raise ValueError(f"fitted_on 의 구간 '{segment_id}' 가 {segments_file} 에 없다")
        for venue in segment["venues"]:
            for occasion in segment["occasions"]:
                for day_type in segment["day_types"]:
                    excluded[venue].add((occasion, day_type))
    try:
        shown = elasticity_file.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        shown = elasticity_file.name
    return FittedOn(elasticity_file=shown, price_scenarios=scenarios, segments=segment_ids), dict(excluded)


# ── 채점 ──────────────────────────────────────────────────────────────────


@dataclass
class Context:
    root: Path
    data_mode: str
    events: list[BacktestEvent]
    table: Table
    persona_party: dict[str, int]
    slices: dict[str, Slice]
    fitted: FittedOn | None
    fitted_slices: dict[str, set[Slice]]


def _measure(
    ctx: Context, metric: str, event: BacktestEvent, control: list[str], sim: tuple, base_dir: Path, base_rows: list[LedgerRow]
) -> Measure:
    a = actual_change(ctx.table, metric, event.venue_id, control, event.start_month, set())
    a_band = actual_band(ctx.table, metric, event.venue_id, ctx.events, set())
    (b_people, b_rev), (s_people, s_rev) = sim
    b, s = (b_people, s_people) if metric == "people" else (b_rev, s_rev)
    p = did(_sum(b, [event.venue_id], set()), _sum(s, [event.venue_id], set()), _sum(b, control, set()), _sum(s, control, set()))
    p_band = predicted_band(base_dir, base_rows, event.venue_id, ctx.persona_party, ctx.slices, metric)
    a_dir = direction(a, a_band) if a is not None and a_band is not None else None
    p_dir = direction(p, p_band or 0.0) if p is not None else None
    return Measure(
        actual=_r(a),
        actual_band=_r(a_band),
        actual_direction=a_dir,
        predicted=_r(p),
        predicted_band=_r(p_band),
        predicted_direction=p_dir,
        direction_correct=None if a_dir is None or p_dir is None else a_dir == p_dir,
    )


def _magnitude(ctx: Context, metric: str, event: BacktestEvent, control: list[str], sim: tuple) -> Magnitude:
    excluded = sorted(ctx.fitted_slices.get(event.venue_id, set()))
    empty = {"excluded_slices": excluded, "actual": None, "actual_band": None, "predicted": None, "ratio": None, "correct": None}
    if ctx.fitted is not None and event.scenario_id in ctx.fitted.price_scenarios:
        return Magnitude(status="excluded", reason="4단계에서 k 를 맞추는 데 쓴 상황이다", **empty)
    ex = set(excluded)
    before, after = windows(event.start_month)
    if ctx.table.total(metric, [event.venue_id], before + after, ex) <= 0:
        return Magnitude(status="excluded", reason="사건 업장의 방문이 모두 4단계에서 맞춘 구간과 겹친다", **empty)
    a = actual_change(ctx.table, metric, event.venue_id, control, event.start_month, ex)
    a_band = actual_band(ctx.table, metric, event.venue_id, ctx.events, ex)
    (b_people, b_rev), (s_people, s_rev) = sim
    b, s = (b_people, s_people) if metric == "people" else (b_rev, s_rev)
    p = did(_sum(b, [event.venue_id], ex), _sum(s, [event.venue_id], ex), _sum(b, control, ex), _sum(s, control, ex))
    values = {"excluded_slices": excluded, "actual": _r(a), "actual_band": _r(a_band), "predicted": _r(p)}
    if a is None or p is None:
        return Magnitude(status="unmeasured", reason="남은 방문으로 실제나 예측의 변화를 낼 수 없다 (어느 쪽이 0)", ratio=None, correct=None, **values)
    if a_band is None:
        return Magnitude(status="unmeasured", reason="흔들림을 잴 가짜 사건이 없다", ratio=None, correct=None, **values)
    if direction(a, a_band) == "none":
        return Magnitude(status="no_change", reason="실제가 변화 없음이라 크기를 견주지 않는다", ratio=None, correct=None, **values)
    ratio, ok = magnitude_correct(p, a)
    return Magnitude(status="scored", reason=None, ratio=_r(ratio), correct=ok, **values)


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _skip(event: BacktestEvent, reason: str, base: str | None = None, scen: str | None = None) -> EventResult:
    return EventResult(
        event_id=event.event_id,
        venue_id=event.venue_id,
        start_month=event.start_month,
        scenario_id=event.scenario_id,
        status="skipped",
        skip_reason=reason,
        baseline_run=base,
        scenario_run=scen,
        control_venues=[],
        people=None,
        revenue=None,
        people_magnitude=None,
        revenue_magnitude=None,
    )


def score_event(ctx: Context, event: BacktestEvent) -> EventResult:
    """사건 하나를 채점한다. 상황 파일이나 실행이 잘못돼 낼 수 없으면 그 사건만 이유를 적고 건너뛴다 (나머지 사건은 채점한다)."""
    try:
        return _score_event(ctx, event)
    except (FileNotFoundError, ValueError) as exc:
        return _skip(event, f"채점하지 못했다: {exc}")


def _score_event(ctx: Context, event: BacktestEvent) -> EventResult:
    if not FIRST_MONTH <= event.start_month <= LAST_MONTH:
        return _skip(event, f"사건 달이 {FIRST_MONTH} ~ {LAST_MONTH}월 밖이라 앞뒤 {WINDOW_BEFORE}달씩을 견줄 수 없다")
    if busy(event.venue_id, event.start_month, ctx.events, skip=event):
        return _skip(event, f"같은 업장의 다른 사건이 앞뒤 {OVERLAP}달 안에 있어 섞인다 (겹침)")
    scenario = read_model(scenario_path(ctx.root, ctx.data_mode, event.scenario_id), Scenario)
    changed = {c.venue_id for c in scenario.changes}
    if event.venue_id not in changed:
        return _skip(event, f"상황 '{event.scenario_id}' 이 사건 업장 '{event.venue_id}' 을 바꾸지 않는다")
    base, scen, why = find_runs(ctx.root, ctx.data_mode, event)
    if why is not None:
        return _skip(event, why, base.run_id if base else None)
    expected = summary_hash(summary_path(ctx.root, ctx.data_mode), event.start_month - 1)
    if base.inputs.get("summary") != expected:
        return _skip(event, "기준 실행 뒤에 집계 파일이 바뀌었다 (그 실행은 지금의 자료로 돈 것이 아니다)", base.run_id, scen.run_id)
    control = controls(event.start_month, event.venue_id, ctx.events, changed, ctx.table.venues())
    if not control:
        return _skip(event, "견줄 워커힐 업장이 없다", base.run_id, scen.run_id)
    base_dir = runs_folder(ctx.root, ctx.data_mode) / base.run_id
    base_rows = _ledger(base_dir)
    scen_rows = _ledger(runs_folder(ctx.root, ctx.data_mode) / scen.run_id)
    sim = (sim_table(base_rows, ctx.persona_party, ctx.slices), sim_table(scen_rows, ctx.persona_party, ctx.slices))
    people = _measure(ctx, "people", event, control, sim, base_dir, base_rows)
    if people.direction_correct is None:
        reason = "흔들림을 잴 가짜 사건이 없다" if people.actual is not None and people.actual_band is None else "실제나 예측의 변화를 낼 수 없다 (어느 쪽이 0)"
        result = _skip(event, reason, base.run_id, scen.run_id)
        return result.model_copy(update={"control_venues": control, "people": people})
    return EventResult(
        event_id=event.event_id,
        venue_id=event.venue_id,
        start_month=event.start_month,
        scenario_id=event.scenario_id,
        status="scored",
        skip_reason=None,
        baseline_run=base.run_id,
        scenario_run=scen.run_id,
        control_venues=control,
        people=people,
        revenue=_measure(ctx, "revenue", event, control, sim, base_dir, base_rows),
        people_magnitude=_magnitude(ctx, "people", event, control, sim),
        revenue_magnitude=_magnitude(ctx, "revenue", event, control, sim),
    )


def _tally(results: list[EventResult], metric: str) -> Tally:
    scored = [r for r in results if r.status == "scored"]
    measures = [getattr(r, metric) for r in scored]
    mags = [getattr(r, f"{metric}_magnitude") for r in scored]
    return Tally(
        scored=len(scored),
        direction_correct=sum(bool(m and m.direction_correct) for m in measures),
        magnitude_scored=sum(m is not None and m.status == "scored" for m in mags),
        magnitude_correct=sum(bool(m and m.correct) for m in mags),
    )


def score(
    root: Path,
    data_mode: str,
    events_file: Path,
    now: datetime,
    elasticity_file: Path | None = None,
    segments_file: Path | None = None,
) -> BacktestResult:
    """사건 목록을 채점한다. 실행 폴더는 엔진이 미리 돌려 둔 것을 찾는다 (`find_runs`)."""
    if now.tzinfo is None:
        raise ValueError("now 에는 시간대가 있어야 한다")
    found = read_model(events_file, BacktestEvents)
    inputs = load_inputs(root, data_mode, BASELINE_ID, base_profile_mode="none", with_estimated=False)
    personas: list[Persona] = list(inputs.personas.values())
    table = actual_table(inputs.summary, average_parties(personas))
    fitted, fitted_slices = (None, {})
    if elasticity_file is not None:
        fitted, fitted_slices = read_fitted(elasticity_file, segments_file or root / "engine" / "elasticity_segments.json", root)
    ctx = Context(
        root=root,
        data_mode=data_mode,
        events=found.events,
        table=table,
        persona_party={p.persona_id: party_size(p) for p in personas},
        slices={c.condition_id: (c.occasion, c.day_type) for c in inputs.conditions.conditions},
        fitted=fitted,
        fitted_slices=fitted_slices,
    )
    results = [score_event(ctx, event) for event in found.events]
    people, revenue = _tally(results, "people"), _tally(results, "revenue")
    try:
        shown = events_file.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        shown = events_file.name
    return BacktestResult.model_validate(
        {
            "format_version": 1,
            "created_at": now,
            "data_mode": data_mode,
            "events_file": shown,
            "summary_hash": summary_hash(summary_path(root, data_mode), None),
            "fitted_on": fitted,
            "criteria": CRITERIA,
            "events": results,
            "summary": {
                "events": len(results),
                "people": people,
                "revenue": revenue,
                "verdict": verdict(people.scored, people.direction_correct, people.magnitude_scored, people.magnitude_correct),
                "magnitude_said": people.magnitude_scored > 0,
            },
        }
    )


# ── 사건 찾기 ─────────────────────────────────────────────────────────────


@dataclass
class Step:
    """상품 하나의 가격 변경 후보: `month` 부터 평균 가격이 `before` 에서 `after` 로 바뀌어 머문다."""

    venue_id: str
    product_id: str
    month: int
    before: float
    after: float
    # 달 중간에 바뀌어 그 달의 평균 가격이 두 수준 사이에 있다 (새 수준은 다음 달부터).
    mid_month: bool = False

    @property
    def pct(self) -> float:
        return self.after / self.before - 1


@dataclass
class Temporary:
    """한두 달만 평균 가격이 바뀌었다 돌아온 것 (할인·프로모션 후보). 가격 변경으로 세지 않는다."""

    venue_id: str
    product_id: str
    months: list[int]
    level: float
    low: float


@dataclass
class Edge:
    """자료의 끝 달(들)에서만 바뀐 것. 뒤 달이 없어 가격 변경인지 잠깐의 바뀜인지 가를 수 없다 (사건으로 쓰지 않고 따로 적는다)."""

    venue_id: str
    product_id: str
    months: list[int]
    level: float
    last: float


def unit_prices(rows: list[SummaryRow]) -> dict[tuple[str, str], dict[int, float]]:
    """워커힐 업장의 상품마다, 달마다의 평균 가격 = Σ 낸 금액 ÷ Σ 수량 (고객군·조건을 모두 더한다)."""
    paid: dict[tuple[str, str], dict[int, float]] = defaultdict(lambda: defaultdict(float))
    qty: dict[tuple[str, str], dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        if row.venue_id not in WALKERHILL_VENUE_IDS or row.quantity <= 0 or row.paid <= 0:
            continue
        paid[(row.venue_id, row.product_id)][row.month] += row.paid
        qty[(row.venue_id, row.product_id)][row.month] += row.quantity
    return {key: {m: paid[key][m] / qty[key][m] for m in sorted(paid[key])} for key in paid}


def _near(a: float, b: float) -> bool:
    return abs(a / b - 1) <= LEVEL_TOL


def find_edges(prices: dict[tuple[str, str], dict[int, float]]) -> list[Edge]:
    """마지막 한두 달만 그 앞의 수준(앞 3달의 가운데 값, 둘 이상이 그 수준)과 STEP_MIN 넘게 다른 상품."""
    edges = []
    for (venue, product), series in sorted(prices.items()):
        months = sorted(series)
        for length in range(1, TEMPORARY_MAX + 1):
            tail = months[-length:]
            head = [t for t in months if t < tail[0]][-WINDOW_BEFORE:]
            if len(tail) < length or len(head) < 2 or tail[0] - 1 not in series:
                continue
            level = statistics.median(series[t] for t in head)
            if sum(_near(series[t], level) for t in head) < 2 or not _near(series[tail[0] - 1], level):
                continue
            if all(abs(series[t] / level - 1) >= STEP_MIN for t in tail):
                edges.append(Edge(venue, product, tail, level, series[tail[-1]]))
                break
    return edges


def _step(series: dict[int, float], months: list[int], m: int, shift: int) -> tuple[float, float] | None:
    """`m` 에서 시작하는 가격 변경의 (앞 수준, 새 수준). `shift` 가 1 이면 `m` 은 달 중간에 바뀐 달이라 두 수준 사이에 있고 새 수준은 다음 달부터다."""
    start = m + shift
    before_months = [t for t in range(m - WINDOW_BEFORE, m) if t in series]
    after_months = [t for t in range(start, start + WINDOW_AFTER) if t in series]
    # 뒤 창이 자료의 끝을 넘으면 머무는지 알 수 없다 (끝 달의 바뀜, `find_edges`).
    if len(before_months) < 2 or len(after_months) < 2 or (m - 1) not in series or start not in series:
        return None
    if start + WINDOW_AFTER - 1 > months[-1]:
        return None
    lo = statistics.median(series[t] for t in before_months)
    hi = statistics.median(series[t] for t in after_months)
    if abs(hi / lo - 1) < STEP_MIN or not _near(series[m - 1], lo) or not _near(series[start], hi):
        return None
    if sum(_near(series[t], lo) for t in before_months) < 2 or sum(_near(series[t], hi) for t in after_months) < 2:
        return None
    if not _near(series[after_months[-1]], hi):
        return None
    if shift:
        middle = series.get(m)
        if middle is None or _near(middle, lo) or _near(middle, hi) or not min(lo, hi) < middle < max(lo, hi):
            return None
    return lo, hi


def find_changes(prices: dict[tuple[str, str], dict[int, float]]) -> tuple[list[Step], list[Temporary]]:
    """평균 가격의 흐름에서 가격 변경(바뀌어 머묾)과 잠깐의 바뀜(할인·프로모션 후보)을 가른다. 수준은 가운데 값이다.

    - 가격 변경: 바로 앞 달을 포함해 앞 3달 가운데 둘 이상이 한 수준(lo)에 있다가, 그 달부터 STEP_MIN 넘게 다른 수준(hi)으로 바뀌어
      뒤 3달 가운데 둘 이상과 마지막 달이 hi 에 머문다. 그다음 3달 안에 lo 로 돌아오면 가격 변경이 아니라 잠깐의 바뀜이다
      (석 달짜리 프로모션이 가격 변경처럼 보이지 않게). 잠깐의 바뀜이 끝나 원래 가격으로 돌아온 것도 가격 변경으로 세지 않는다.
      달 중간에 바뀌어 그 달의 평균이 두 수준 사이에 있으면 그 달을 사건 달로 보고 `mid_month` 로 표시한다 (새 수준은 다음 달부터 3달로 본다).
    - 잠깐의 바뀜: 앞뒤 달이 같은 수준인데 그 사이의 한두 달만 STEP_MIN 넘게 다르다 (할인 쿠폰, 짧은 프로모션).
    """
    steps: list[Step] = []
    temps: list[Temporary] = []

    def taken(venue: str, product: str, months: list[int]) -> bool:
        return any(t.venue_id == venue and t.product_id == product and set(months) & set(t.months) for t in temps)

    for (venue, product), series in sorted(prices.items()):
        months = sorted(series)
        for m in months:
            for shift in (0, 1):
                found = _step(series, months, m, shift)
                if found is None:
                    continue
                lo, hi = found
                start = m + shift  # 새 수준이 처음 온전히 보이는 달
                # 잠깐의 바뀜이 끝나 원래 가격으로 돌아온 것이면 가격 변경이 아니다: lo 에 머문 달이 짧고(다섯 달 이하) 그 앞이 hi 다.
                run_start = m - 1
                while run_start - 1 in series and _near(series[run_start - 1], lo):
                    run_start -= 1
                if m - run_start < 2 * WINDOW_AFTER and run_start - 1 in series and _near(series[run_start - 1], hi):
                    continue
                back = [t for t in range(start + WINDOW_AFTER, start + 2 * WINDOW_AFTER) if t in series and _near(series[t], lo)]
                if back:
                    inside = list(range(m, back[0]))
                    if not taken(venue, product, inside):
                        temps.append(Temporary(venue, product, inside, lo, min(series[t] for t in inside if t in series)))
                    continue
                steps.append(Step(venue, product, m, lo, hi, mid_month=bool(shift)))
        for length in range(1, TEMPORARY_MAX + 1):
            for m in months:
                inside = list(range(m, m + length))
                left, right = m - 1, m + length
                if left not in series or right not in series or any(t not in series for t in inside):
                    continue
                if not _near(series[left], series[right]):
                    continue
                level = (series[left] + series[right]) / 2
                if all(abs(series[t] / level - 1) >= STEP_MIN for t in inside) and not taken(venue, product, inside):
                    temps.append(Temporary(venue, product, inside, level, min(series[t] for t in inside)))
    return steps, temps


def draft_events(steps: list[Step]) -> list[dict[str, Any]]:
    """상품의 가격 변경을 업장·달마다 묶은 사건 초안. 같은 업장·달에 오른 것과 내린 것이 섞이면 나눠 적지 않고 표시한다."""
    grouped: dict[tuple[str, int], list[Step]] = defaultdict(list)
    for step in steps:
        grouped[(step.venue_id, step.month)].append(step)
    drafts = []
    for (venue, month), found in sorted(grouped.items()):
        signs = {step.pct > 0 for step in found}
        pct = statistics.median(step.pct for step in found)
        drafts.append(
            {
                "venue_id": venue,
                "start_month": month,
                "products": [
                    {"product_id": s.product_id, "pct": round(100 * s.pct, 1), "after": round(s.after), "mid_month": s.mid_month}
                    for s in found
                ],
                "pct": round(100 * pct, 1),
                "mixed": len(signs) > 1,
            }
        )
    return drafts


def draft_scenario(draft: dict[str, Any], priced: set[tuple[str, str]]) -> dict[str, Any]:
    """사건 초안 하나의 상황 파일 초안 (`our_price`).

    업장 정의에 가격이 있는 상품(`priced`)은 `change_price_pct` 로, 가격이 비어 집계 파일로 채우는 상품은 `set_price` 로 새 평균 가격을 적는다
    (빈 가격에는 퍼센트를 걸 수 없다, 7절). 업장 정의의 가격은 자르지 않으므로, 그 가격이 사건 전의 것인지 검토할 때 확인한다.
    """
    venue, month = draft["venue_id"], draft["start_month"]
    return {
        "format_version": 1,
        "scenario_id": f"backtest-{venue}-{month:02d}",
        "name": f"{venue} {month}월 가격 변경 (되돌려 맞혀 보기)",
        "kind": "our_price",
        "description": f"{month}월부터 바뀐 평균 가격을 그 전까지의 자료로 돌려 본다 (T224).",
        "changes": [
            {"op": "change_price_pct", "venue_id": venue, "product_id": p["product_id"], "pct": p["pct"]}
            if (venue, p["product_id"]) in priced
            else {"op": "set_price", "venue_id": venue, "product_id": p["product_id"], "price": p["after"]}
            for p in draft["products"]
        ],
        "note": "engine.backtest find 가 집계 파일의 달마다 평균 가격(낸 금액 ÷ 수량)에서 찾은 초안이다. 검토한 뒤에 쓴다.",
    }


# ── 명령 ──────────────────────────────────────────────────────────────────


def _default_folder(root: Path, data_mode: str) -> Path:
    """사건 목록·상황 초안·결과를 두는 곳. 기본 데이터는 `private/backtest/`, 가상 예시는 깃이 무시하는 실행 폴더 자리의 `engine/samples/runs/backtest/`.

    가상 예시는 `.gitignore` 의 `engine/samples/runs/*/` 에 걸리는 자리에 둔다 (실행 기록 `run.json` 이 없어 실행 폴더로 읽히지 않는다).
    """
    return root / "private" / "backtest" if data_mode == "private" else runs_folder(root, data_mode) / "backtest"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine.backtest", description="6단계의 되돌려 맞혀 보기 (T224).")
    sub = parser.add_subparsers(dest="command", required=True)
    find = sub.add_parser("find", help="집계 파일에서 가격 변경과 한두 달짜리 바뀜(할인·프로모션 후보)을 찾아 초안을 쓴다")
    find.add_argument("--data", choices=("sample", "private"), required=True)
    find.add_argument("--root", type=Path, default=Path.cwd())
    sc = sub.add_parser("score", help="사건 목록을 채점한다 (엔진으로 사건마다 --data-until 실행을 먼저 돌려 둔다)")
    sc.add_argument("--data", choices=("sample", "private"), required=True)
    sc.add_argument("--events", type=Path, required=True, help="사건 목록 파일")
    sc.add_argument("--elasticity", type=Path, help="4단계 결과 elasticity.json. 주면 거기 적힌 상황과 구간을 빼고 크기를 잰다")
    sc.add_argument("--segments", type=Path, help="4단계 구간의 정의 (기본 engine/elasticity_segments.json)")
    sc.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    root = args.root.resolve()
    folder = _default_folder(root, args.data)
    try:
        if args.command == "find":
            rows = read_summary(summary_path(root, args.data))
            prices = unit_prices(rows)
            steps, temps = find_changes(prices)
            edges = find_edges(prices)
            drafts = draft_events(steps)
            out = folder / "candidates.json"
            write_json(
                out,
                {
                    "price_changes": drafts,
                    "temporary": [
                        {"venue_id": t.venue_id, "product_id": t.product_id, "months": t.months, "pct": round(100 * (t.low / t.level - 1), 1)}
                        for t in temps
                    ],
                    "edge": [
                        {"venue_id": e.venue_id, "product_id": e.product_id, "months": e.months, "pct": round(100 * (e.last / e.level - 1), 1)}
                        for e in edges
                    ],
                },
            )
            venues = [read_model(path, Venue) for path in sorted((root / "data" / "venues").glob("*.json"))]
            priced = {(v.venue_id, item.product_id) for v in venues for item in v.products if item.price is not None}
            for draft in drafts:
                name = f"backtest-{draft['venue_id']}-{draft['start_month']:02d}.json"
                write_json(folder / "scenarios" / name, draft_scenario(draft, priced))
            print(f"후보: {out}")
            print(f"가격 변경 후보 {len(drafts)}건 (업장·달), 잠깐의 바뀜 {len(temps)}건, 끝 달에만 바뀌어 가를 수 없는 것 {len(edges)}건")
            print(f"상황 초안: {folder / 'scenarios'}")
            print("검토한 뒤에 사건 목록(events.json)과 상황 파일을 확정한다. 기본 데이터는 상황을 private/scenarios/ 에 둔다")
        else:
            result = score(root, args.data, args.events.resolve(), datetime.now().astimezone(), args.elasticity, args.segments)
            out = folder / f"result-{result.created_at:%Y%m%d-%H%M%S}.json"
            write_json(out, result.model_dump(mode="json"))
            s = result.summary
            print(f"결과: {out}")
            print(f"사건 {s.events}건 · 채점 {s.people.scored}건 · 사람 수 방향 맞음 {s.people.direction_correct}건 · "
                  f"크기 채점 {s.people.magnitude_scored}건 중 맞음 {s.people.magnitude_correct}건 · 판정 {s.verdict}")
            for r in result.events:
                if r.status == "skipped":
                    print(f"- 건너뜀 {r.event_id}: {r.skip_reason}", file=sys.stderr)
    except (FileNotFoundError, ValueError) as exc:
        print(f"하지 못했다: {exc}", file=sys.stderr)
        return EXIT_FAILED
    if args.data == "private":
        print("기본 데이터에서 계산한 값이다. 저장소·커밋·연락판에 옮겨 적지 않는다 (판정과 건수만 적는다).")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
