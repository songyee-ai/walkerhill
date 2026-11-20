"""상수 추정: 업장 상수를 기본 데이터의 업장 몫에 맞춘다 (T212, docs/FORMATS.md 6.1절의 "추정한 상수 파일").

    uv run python -m engine.estimate --data private

점수를 받은 기준 실행 하나의 방문마다, AI 점수로 낸 몫이 고객군의 실제 업장 몫(집계 파일의 사람 수)에 가까워지게
업장마다 상수 하나를 정한다. 선택 모형에서 대안별 상수(ASC)를 시장의 몫에 맞추는 방법과 같다 (11-20 wilstein91 결정).

- 잣대: 고객군마다 워커힐 업장의 사람 수 몫, 모든 이용 상황 (가중치와 같은 줄을 같은 몫으로 센다. `engine.weights.group_venue_people`).
  업장 상수는 "어디로 가나"를 고치는 값이라 사람 수로 맞춘다. "얼마를 시키나"는 보정의 대조(매출 비중, `engine.calibration`)가 따로 본다.
- 업장 상수는 고객군과 상관없이 워커힐 업장마다 하나다. 고객군마다 두면 그 고객군에는 꼭 맞지만, 다른 고객군에 써 보는 검증을 할 수 없다.
  그래서 페르소나가 있는 고객군을 모두 모은(사람 수로 더한) 몫에 맞추고, 고객군마다 남는 차이는 검증에 쓴다.
- 경쟁 업장과 "이용하지 않음"은 상수를 정하지 않는다 (1). 기본 데이터에는 워커힐의 판매만 있어 밖으로 간 몫을 알 수 없다.
  워커힐 업장 상수 전체의 크기는 실제 몫으로 정해지지 않아, 맞춘 몫(사람 수)으로 가중한 기하 평균이 1 이 되게 둔다
  (워커힐과 밖 사이의 나뉨은 AI 의 판단 그대로 둔다).
- 날카로움 k 는 정하지 않는다. 업장 몫만으로는 k 가 정해지지 않는다 (11-20 실험). 지금의 k (`engine/constants.json`)로 몫을 낸다.
- 추정에 쓴 자료(같은 기준 실행, 같은 집계 파일)로 다시 맞았다고 하지 않는다 (PRD 12절). 맞음은 검증으로 따로 본다.

추정한 값은 기본 데이터로 돌리면 `private/base/estimated_constants.json` 에, 가상 예시로 돌리면 `data/samples/base_estimated_constants.json` 에 쓴다.
기본 데이터에서 계산한 값이라 저장소에 올리지 않는다. 다른 PC 는 답 폴더처럼 저장소 밖으로 받아 같은 자리에 둔다.
LLM 을 부르지 않는다. 같은 실행으로 다시 추정하면 파일을 덮어쓴다.
"""

import argparse
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from engine.formats.constants import ConstantsFile
from engine.formats.io import read_csv, read_model, write_json
from engine.formats.persona import Persona
from engine.formats.run import LEDGER_COLUMNS, RUN_ID_RE, SEASON_GAP_REASON, LedgerRow, RunRecord
from engine.formats.scenario import BASELINE_ID
from engine.runner import latest_baseline_run, load_inputs, month_label, runs_folder
from engine.shares import VENUE_CONSTANT_PREFIX
from engine.weights import average_parties, estimated_constants_path, group_venue_people, party_size

EXIT_OK, EXIT_FAILED = 0, 1

# 맞추기를 멈추는 때: 모은 몫의 차이가 모두 이것보다 작거나, 이만큼 되풀이했을 때.
TOLERANCE = 1e-9
MAX_ROUNDS = 5000
# 실제 몫이 0 인데 AI 가 그곳을 고르는 업장의 상수는 0 으로 갈 수 없어(몫을 내지 못한다) 여기서 멈춘다.
MIN_CONSTANT = 1e-3
# 파일에 적는 상수의 유효숫자.
CONSTANT_DIGITS = 6

# 기준 실행 뒤에 달라지면 추정이 어긋나는 입력 (보정의 대조와 같다. 업장을 골라 돌린 실행도 여기서 걸린다).
COMPARED_INPUTS = ("venues", "personas", "conditions", "scenario", "vocab", "summary", "constants")


@dataclass
class ScoredVisit:
    """점수를 받은 방문 하나: 고객군, 대표하는 사람 수, 곳마다의 (점수, 파는 달의 몫). "이용하지 않음"은 None 이다."""

    group: str
    people: float
    places: dict[str | None, tuple[int, float]] = field(default_factory=dict)


def scored_visits(rows: list[LedgerRow], personas: dict[str, Persona]) -> tuple[list[ScoredVisit], int]:
    """원장에서 점수를 받은 방문을 읽는다. (방문들, 점수가 없어 뺀 방문의 수)를 돌려준다.

    원장에는 점수가 0 보다 큰 곳마다 줄이 있다 (FORMATS 10.2절). 그래서 원장만으로 어떤 k·상수로도 몫을 다시 낼 수 있다.
    실패한 방문, 후보가 없던 방문, 점수가 없는 답(1단계 방식)의 방문은 뺀다.
    """
    by_visit: dict[str, list[LedgerRow]] = defaultdict(list)
    for row in rows:
        by_visit[row.visit_id].append(row)
    found: list[ScoredVisit] = []
    skipped = 0
    for visit_rows in by_visit.values():
        first = visit_rows[0]
        if any(r.status != "ok" for r in visit_rows) or not any(r.score is not None for r in visit_rows):
            skipped += first.request_hash is not None and all(r.status == "ok" for r in visit_rows)
            continue
        persona = personas.get(first.persona_id)
        if persona is None:
            raise ValueError(f"원장의 페르소나 '{first.persona_id}' 의 정의가 없다")
        visit = ScoredVisit(group=first.customer_group, people=first.represented * party_size(persona))
        for row in visit_rows:
            if row.choice_kind == "none":
                if row.season_gap_of is None and row.reason_text != SEASON_GAP_REASON and row.score is not None:
                    visit.places[None] = (row.score, 1.0)
                continue
            if row.score is not None:
                visit.places[row.venue_id] = (row.score, row.counted_share)
        found.append(visit)
    return found, skipped


def simulate(visits: list[ScoredVisit], k: float, constants: dict[str, float], walkerhill: set[str]) -> dict[str, dict[str, float]]:
    """방문들의 몫으로 고객군마다 워커힐 업장의 사람 수를 낸다. 몫은 (점수 ^ k) × 상수를 합이 1 이 되게 나눈 것이다 (`engine.shares`).

    파는 달이 아닌 몫(`counted_share` 의 나머지)은 그 업장에 세지 않는다 (원장에서 "이용하지 않음"으로 센 것과 같다).
    """
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for visit in visits:
        weights = {
            place: (score**k) * (1.0 if place is None else constants.get(place, 1.0))
            for place, (score, _) in visit.places.items()
            if score > 0
        }
        total = sum(weights.values())
        if total <= 0:
            continue
        for place, weight in weights.items():
            if place in walkerhill:
                out[visit.group][place] += visit.people * weight / total * visit.places[place][1]
    return {group: dict(by_venue) for group, by_venue in out.items()}


def _pooled(by_group: dict[str, dict[str, float]], groups: list[str], venues: list[str]) -> dict[str, float]:
    """고객군들을 사람 수로 더한 업장 몫 (`venues` 안에서 합이 1)."""
    summed = {v: sum(by_group.get(g, {}).get(v, 0.0) for g in groups) for v in venues}
    total = sum(summed.values())
    return {v: summed[v] / total if total > 0 else 0.0 for v in venues}


@dataclass
class Estimate:
    constants: dict[str, float]
    # 맞춘 업장 (실제 몫이 0 보다 크고 점수를 받은 업장), 실제 몫은 있는데 점수를 받은 방문이 없어 맞추지 못한 업장,
    # 실제 몫이 0 인데 AI 가 고르는 업장 (상수를 아래 한도에 둔다).
    fitted: list[str]
    unscored: list[str]
    zero_target: list[str]
    groups: list[str]
    rounds: int
    target: dict[str, float]


class NotFitted(ValueError):
    """업장 상수가 실제 몫에 맞춰지지 않았다. 파일을 쓰지 않는다."""


def fit(
    visits: list[ScoredVisit],
    target: dict[str, dict[str, float]],
    k: float,
    walkerhill: set[str],
    fixed: dict[str, float] | None = None,
) -> Estimate:
    """업장 상수를 모은 몫에 맞춘다: 상수 ← 상수 × (실제 몫 ÷ 시뮬레이션 몫)을 몫이 같아질 때까지 되풀이한다 (대안별 상수를 맞추는 흔한 방법).

    - `target` 은 고객군마다 워커힐 업장의 실제 사람 수다. 점수를 받은 방문이 있는 고객군만 모은다.
    - `fixed` 는 맞추지 않고 그대로 쓰는 업장 상수다 (`engine/constants.json` 의 것. 엔진과 같은 몫을 내려고 함께 쓴다).
    - 점수는 대표하는 사람 수와 파는 달의 몫이 0 보다 큰 방문의 것만 본다 (그렇지 않은 방문은 몫에 들지 않아 상수를 정할 수 없다).
    - 실제 몫이 0 인데 AI 가 고르는 업장은 상수를 `MIN_CONSTANT` 에 두고 맞추기에서 뺀다. 나머지 업장은 그 업장들을 뺀 몫으로 맞춘다.
    - 맞추지 못하면(`MAX_ROUNDS` 안에 몫의 차이가 `TOLERANCE` 아래로 내려가지 않으면) `NotFitted` 로 멈춘다.
    """
    fixed = dict(fixed or {})
    groups = sorted({v.group for v in visits if v.group in target})
    if not groups:
        raise NotFitted("점수를 받은 방문의 고객군이 집계 파일에 없다. 페르소나의 customer_group 이 집계 파일의 고객군 이름과 같은지 본다")
    scored = {
        place
        for v in visits
        if v.group in groups and v.people > 0
        for place, (score, counted) in v.places.items()
        if score > 0 and counted > 0 and place in walkerhill and place not in fixed
    }
    wanted = {venue for g in groups for venue, people in target[g].items() if people > 0}
    unscored = sorted(wanted - scored)
    zero_target = sorted(scored - wanted)
    fitted = sorted(scored & wanted)
    if not fitted:
        raise NotFitted("실제 몫이 있고 점수를 받은 워커힐 업장이 없어 맞출 것이 없다")
    goal = _pooled(target, groups, fitted)
    constants = {**dict.fromkeys(zero_target, MIN_CONSTANT), **dict.fromkeys(fitted, 1.0)}
    rounds = 0
    while True:
        now = _pooled(simulate(visits, k, {**fixed, **constants}, walkerhill), groups, fitted)
        if max(abs(now[v] - goal[v]) for v in fitted) < TOLERANCE:
            break
        if rounds >= MAX_ROUNDS:
            worst = max(fitted, key=lambda v: abs(now[v] - goal[v]))
            raise NotFitted(
                f"{MAX_ROUNDS}번 되풀이해도 업장 몫이 맞지 않는다 (가장 큰 차이 {worst}). 점수를 받은 방문이 적은 업장이 있으면 "
                "AI 가 그곳을 거의 고르지 않아 상수로 맞출 수 없다. 추정한 상수 파일은 쓰지 않았다"
            )
        rounds += 1
        for venue in fitted:
            if now[venue] > 0:
                constants[venue] = max(constants[venue] * goal[venue] / now[venue], MIN_CONSTANT)
        # 크기는 맞춘 몫으로 가중한 기하 평균이 1 이 되게 둔다 (모듈 설명). 실제 몫이 0 인 업장은 한도에 둔 채 둔다.
        mean = math.exp(sum(goal[v] * math.log(constants[v]) for v in fitted) / sum(goal[v] for v in fitted))
        constants.update({v: max(constants[v] / mean, MIN_CONSTANT) for v in fitted})
    return Estimate(
        # 유효숫자로 적는다 (작은 상수도 같은 정밀도로 남게).
        constants={v: float(f"{c:.{CONSTANT_DIGITS}g}") for v, c in constants.items()},
        fitted=fitted,
        unscored=unscored,
        zero_target=zero_target,
        groups=groups,
        rounds=rounds,
        target=goal,
    )


def _record(root: Path, data_mode: str, run_id: str | None, data_until: int | None = None) -> RunRecord:
    """추정할 기준 실행의 실행 기록. 끝까지 돌았고, 달을 주지 않았고, 실패한 방문이 없어야 한다 (보정의 대조와 같다).

    `run_id` 를 주지 않으면 `data_until` 이 같은 가장 새 기준 실행이다. 주면 그 실행의 `data_until` 로 추정한다 (T224).
    """
    if run_id is None:
        run_id = latest_baseline_run(root, data_mode, month=None, data_until=data_until)
        if run_id is None:
            what = "일 년 전체" if data_until is None else f"{data_until}월까지의 자료"
            raise ValueError(f"{what}로 끝까지 돈 기준 실행이 없다. 기준 상황을 먼저 돌린다")
    if not RUN_ID_RE.match(run_id):
        raise ValueError(f"run_id 가 아니다: {run_id!r}")
    path = runs_folder(root, data_mode) / run_id / "run.json"
    if not path.is_file():
        raise FileNotFoundError(f"실행 기록이 없다: {path}")
    record = read_model(path, RunRecord)
    if record.scenario_id != BASELINE_ID:
        raise ValueError(f"실행 '{run_id}' 는 기준 상황의 실행이 아니다. 상수 추정은 기준 상황으로 한다")
    if record.status != "ok":
        raise ValueError(f"기준 실행 '{run_id}' 는 끝까지 돌지 않았다 (status 가 {record.status})")
    if record.month is not None:
        raise ValueError(f"기준 실행 '{run_id}' 는 {month_label(record.month)}로 돌린 것이다. 상수 추정은 달을 주지 않은 기준 실행으로 한다")
    if record.counts.failed:
        raise ValueError(f"기준 실행 '{run_id}' 에 실패한 방문이 {record.counts.failed}건 있어 추정하지 않는다. 그 방문이 빠지면 몫이 어긋난다")
    if data_until is not None and record.data_until != data_until:
        raise ValueError(f"기준 실행 '{run_id}' 의 data_until 은 {record.data_until} 인데 {data_until} 을 주었다")
    return record


def estimate(
    root: Path, data_mode: str, run_id: str | None = None, today: date | None = None, data_until: int | None = None
) -> tuple[Path, Estimate, RunRecord, dict]:
    """기준 실행 하나로 업장 상수를 추정해 추정한 상수 파일을 쓴다. (파일 자리, 추정, 실행 기록, 화면에 보일 고객군별 몫)을 돌려준다.

    기준 실행이 집계 파일을 어느 달까지 읽었으면(`data_until`, T224) 같은 달까지의 자료로 맞추고, 그 달의 추정한 상수 파일에 쓴다.
    """
    record = _record(root, data_mode, run_id, data_until)
    until = record.data_until
    if record.share_method not in ("scores", "mixed"):
        raise ValueError(
            f"기준 실행 '{record.run_id}' 에는 점수를 받은 답이 없다 (share_method 가 {record.share_method or '없음'}). "
            "점수를 묻는 판의 프롬프트로 기준 상황을 돌린 뒤에 추정한다"
        )
    # 이미 있는 추정한 상수 파일은 읽지 않는다 (추정은 점수에서 처음부터 다시 맞추고, 깨진 파일이 있어도 다시 추정해 고칠 수 있게).
    inputs = load_inputs(
        root, data_mode, BASELINE_ID, None, record.persona_ids, record.base_profile_mode, with_estimated=False, data_until=until
    )
    changed = [key for key in COMPARED_INPUTS if record.inputs.get(key) != inputs.hashes[key]]
    if changed:
        raise ValueError(
            f"기준 실행 '{record.run_id}' 과 달라진 것이 있다: {', '.join(changed)}. 실행 뒤에 입력을 고쳤거나 업장을 골라 돌린 실행이다. "
            "기준 상황을 업장을 고르지 않고 다시 돌린 뒤에 추정한다"
        )
    conditions = [inputs.conditions.condition(condition_id) for condition_id in record.condition_ids]
    if None in conditions:
        raise ValueError("방문 조건 묶음에 없는 조건이 실행 기록에 있다. 화면에서 조건을 직접 넣어 돌린 실행은 추정하지 않는다")
    # 페르소나나 조건을 일부만 돌린 시험 실행으로 상수를 정하지 않는다 (보정의 대조와 같다).
    everyone = load_inputs(
        root, data_mode, BASELINE_ID, None, None, record.base_profile_mode, with_estimated=False, data_until=until
    ).personas
    missing_personas = sorted(set(everyone) - set(record.persona_ids))
    missing_conditions = sorted({c.condition_id for c in inputs.conditions.conditions} - set(record.condition_ids))
    if missing_personas or missing_conditions:
        raise ValueError(
            f"기준 실행 '{record.run_id}' 은 페르소나나 조건을 일부만 돌렸다 "
            f"(빠진 페르소나 {missing_personas or '없음'}, 빠진 조건 {missing_conditions or '없음'}). "
            "상수 추정은 모두 돌린 기준 실행으로 한다 (--run 으로 가리킨다)"
        )
    rows = [LedgerRow.from_row(row) for row in read_csv(runs_folder(root, data_mode) / record.run_id / "ledger.csv", LEDGER_COLUMNS)]
    visits, skipped = scored_visits(rows, inputs.personas)
    if skipped:
        raise ValueError(f"점수가 없는 답의 방문이 {skipped}건 섞여 있다 (1단계 방식). 모든 방문이 점수를 받은 기준 실행으로 추정한다")
    walkerhill = {venue_id for venue_id, venue in inputs.venues.items() if not venue.is_competitor}
    target = group_venue_people(
        inputs.summary, conditions, inputs.conditions.assumed_splits, inputs.venues, average_parties(list(inputs.personas.values()))
    )
    k = inputs.shares.k
    fixed = inputs.shares.venue_constants  # engine/constants.json 의 업장 상수 (추정한 파일은 읽지 않았다)
    found = fit(visits, target, k, walkerhill, fixed)
    before = simulate(visits, k, fixed, walkerhill)
    after = simulate(visits, k, {**fixed, **found.constants}, walkerhill)
    shown = {
        group: {
            "actual": _pooled(target, [group], found.fitted),
            "before": _pooled(before, [group], found.fitted),
            "after": _pooled(after, [group], found.fitted),
        }
        for group in found.groups
    }
    path = estimated_constants_path(root, data_mode, until)
    write_json(path, _file(found, record, inputs.venues, data_mode, k, today or date.today()).model_dump(mode="json"))
    return path, found, record, shown


def _file(found: Estimate, record: RunRecord, venues: dict, data_mode: str, k: float, today: date) -> ConstantsFile:
    """추정한 상수 파일 (6.1절의 결정 상수 모양). 기본 데이터로 낸 값은 `internal`, 가상 예시로 낸 값은 `assumption` 이다."""
    grade = "internal" if data_mode == "private" else "assumption"
    note = (
        f"상수 추정 (engine/estimate.py): 기준 실행 {record.run_id} 의 AI 점수로 낸 몫을 고객군 {', '.join(found.groups)} 의 "
        f"워커힐 업장 사람 수 몫(모든 이용 상황, 고객군을 사람 수로 더함)에 맞춤. k={k:g}. "
        "추정에 쓴 자료로 다시 맞았다고 하지 않는다 (PRD 12절)"
        + ("" if record.data_until is None else f" 집계 파일은 {record.data_until}월까지만 읽음 (되돌려 맞혀 보기, T224).")
    )
    return ConstantsFile.model_validate(
        {
            "format_version": 1,
            "constants": [
                {
                    "constant_id": f"{VENUE_CONSTANT_PREFIX}{venue_id}",
                    "name": f"{venues[venue_id].name} 의 업장 상수",
                    "value": value,
                    "unit": None,
                    "used_in": "engine/shares.py 의 places (FORMATS 9절의 \"점수와 몫\", 6.1절의 \"추정한 상수 파일\")",
                    "grade": grade,
                    "sources": [],
                    "checked_on": today.isoformat(),
                    "note": note + (" 실제 몫이 0 이라 아래 한도에 둠" if venue_id in found.zero_target else ""),
                    "owner": "wilstein91",
                }
                for venue_id, value in sorted(found.constants.items())
            ],
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine.estimate", description="업장 상수를 기본 데이터의 업장 몫에 맞춰 추정한 상수 파일을 쓴다 (T212).")
    parser.add_argument("--data", choices=("sample", "private"), required=True, help="sample 가상 예시 값, private 기본 데이터")
    parser.add_argument("--run", metavar="RUN_ID", help="추정할 기준 실행. 적지 않으면 일 년 전체로 끝까지 돈 가장 새 기준 실행")
    parser.add_argument(
        "--data-until",
        type=int,
        choices=range(1, 12),
        metavar="1~11",
        help="이 달까지의 자료로 돈 기준 실행으로 추정한다 (6단계의 되돌려 맞혀 보기, T224). --run 을 주면 그 실행의 값을 따른다",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="자료를 읽고 결과를 쓸 폴더 (기본은 지금 폴더)")
    args = parser.parse_args(argv)
    try:
        path, found, record, shown = estimate(args.root.resolve(), args.data, args.run, data_until=args.data_until)
    except (FileNotFoundError, ValueError) as exc:
        print(f"추정하지 못했다: {exc}", file=sys.stderr)
        return EXIT_FAILED

    print(f"추정한 상수 파일: {path}")
    print(f"기준 실행 {record.run_id} · 고객군 {', '.join(found.groups)} · {found.rounds}번 되풀이해 맞춤")
    for venue_id in found.fitted:
        print(f"- {venue_id}: 업장 상수 {found.constants[venue_id]:g} · 모은 실제 몫 {100 * found.target[venue_id]:.1f}%")
    print("고객군마다 업장 몫 (실제 / 추정 전 / 추정 뒤, %). 추정에 쓴 자료라 이것으로 맞았다고 하지 않는다 (검증은 따로):")
    for group, entry in shown.items():
        worst_before = max(abs(entry["before"][v] - entry["actual"][v]) for v in found.fitted)
        worst_after = max(abs(entry["after"][v] - entry["actual"][v]) for v in found.fitted)
        print(f"- {group}: 가장 큰 차이 추정 전 {100 * worst_before:.1f}%p → 추정 뒤 {100 * worst_after:.1f}%p")
        for v in found.fitted:
            print(f"    {v}: {100 * entry['actual'][v]:.1f} / {100 * entry['before'][v]:.1f} / {100 * entry['after'][v]:.1f}")
    if found.unscored:
        print(f"실제 몫은 있는데 점수를 받은 방문이 없어 맞추지 못한 업장: {', '.join(found.unscored)}", file=sys.stderr)
    if found.zero_target:
        print(f"실제 몫이 0 인데 AI 가 고르는 업장 (상수를 {MIN_CONSTANT:g} 에 둠): {', '.join(found.zero_target)}", file=sys.stderr)
    if args.data == "private":
        print("이 파일은 기본 데이터에서 계산한 값이다. 저장소·커밋·연락판에 옮겨 적지 않고, 다른 PC 에는 저장소 밖으로 넘긴다.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
