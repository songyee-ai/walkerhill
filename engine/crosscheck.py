"""2단계의 검증 두 겹: 다른 고객군에 써 보기와 단순 기준과 견주기 (T212, docs/FORMATS.md 10.7절, docs/PRD.md 12절).

    uv run python -m engine.crosscheck --data private

점수를 받은 기준 실행 하나로, 고객군마다 워커힐 업장의 사람 수 몫을 넷으로 견준다 (11-20 wilstein91 결정).
- 실제: 집계 파일의 사람 수 몫 (상수 추정과 같은 잣대. `engine.weights.group_venue_people`).
- 상수 없음: AI 점수 그대로 (업장 상수를 쓰지 않는다. `engine/constants.json` 의 업장 상수는 쓴다).
- 다른 고객군으로 추정: 그 고객군을 빼고 나머지 고객군으로 업장 상수를 추정해(`engine.estimate.fit`) 그 고객군에 쓴 몫.
  추정에 쓰지 않은 고객군으로만 재므로 "추정에 쓴 자료로 다시 맞았다고 하지 않는다"(PRD 12절)를 지킨다.
- 단순 기준: AI 없이 공개 후기(`data/evidence/reviews/`)에서 그 고객군 라벨이 붙은 워커힐 업장 후기 수의 비율.

재는 숫자는 둘이다. 검증에만 쓰고 상수를 정하는 데는 쓰지 않는다 (상수 추정은 합친 몫으로 따로 한다).
- 가장 큰 차이(%p): 업장마다 몫의 차이 가운데 가장 큰 것. 보정의 대조와 같은 잣대다.
- 어긋난 몫(%): 업장마다 몫의 차이를 더해 반으로 나눈 것. 실제와 같아지려면 손님 몇 %를 다른 업장으로 옮겨야 하는지다.

떼어 둔 후기로 하는 검증(PRD 6.6절, T19)은 페르소나 담당의 채점 프로그램이 한다 (11-20 wilstein91 결정).
결과는 그 기준 실행 폴더에 `crosscheck.json` 으로 쓴다. 기본 데이터로 돌린 결과는 `private/` 에만 있고, 저장소와 연락판에는 단순 기준보다 나았는지와 잰 방법만 적는다.
LLM 을 부르지 않는다. 같은 실행을 다시 재면 파일을 덮어쓴다.
"""

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

from engine.estimate import NotFitted, ScoredVisit, _record, fit, scored_visits, simulate
from engine.formats.evidence import REVIEW_COLUMNS
from engine.formats.io import read_csv, write_json
from engine.formats.run import LEDGER_COLUMNS, CrossCheck, LedgerRow
from engine.formats.scenario import BASELINE_ID
from engine.runner import load_inputs, runs_folder
from engine.weights import average_parties, group_venue_people

EXIT_OK, EXIT_FAILED = 0, 1

# 견주는 방법의 이름 (파일의 키). 차례대로 보인다.
METHODS = ("no_constants", "held_out", "simple")
LABELS = {"no_constants": "상수 없음", "held_out": "다른 고객군으로 추정한 상수", "simple": "단순 기준(공개 후기 비율)"}
# 몫은 소수 넷째 자리, 차이는 둘째 자리까지 적는다.
SHARE_DIGITS = 4
DIFF_DIGITS = 2


def review_counts(root: Path, walkerhill: set[str], conditions: list | None = None) -> dict[str, dict[str, int]]:
    """공개 후기 라벨에서 고객군마다 워커힐 업장의 후기 수. 고객군이 빈 후기는 세지 않는다.

    실제 몫과 같은 범위로 센다: 조식 후기는 빼고, `conditions` (돌린 방문 조건)를 주면 이용 상황·끼니·평일 주말이 적힌 후기 가운데
    어느 조건에도 들지 않는 것은 뺀다. 적히지 않은 칸은 따지지 않는다 (후기에 빈 칸이 많아, 빈 후기를 모두 빼면 단순 기준이 지나치게 줄어든다).
    """
    counts: dict[str, Counter] = defaultdict(Counter)
    for path in sorted((root / "data" / "evidence" / "reviews").glob("*.csv")):
        for row in read_csv(path, REVIEW_COLUMNS):
            group, venue_id = row["customer_group"].strip(), row["venue_id"]
            if not group or venue_id not in walkerhill or row["meal"] == "breakfast":
                continue
            if conditions is not None and not _in_conditions(row, conditions):
                continue
            counts[group][venue_id] += 1
    return {group: dict(found) for group, found in counts.items()}


def _in_conditions(row: dict[str, str], conditions: list) -> bool:
    """후기의 이용 상황·끼니·평일 주말 가운데 적힌 칸이 돌린 조건 하나와 모두 맞는가."""
    for condition in conditions:
        if row["occasion"] and row["occasion"] != condition.occasion:
            continue
        if row["meal"] and condition.meal is not None and row["meal"] != condition.meal:
            continue
        if row["day_type"] and row["day_type"] != condition.day_type:
            continue
        return True
    return False


def shares(amounts: dict[str, float], venues: list[str]) -> dict[str, float]:
    """업장마다의 양을 `venues` 안에서 합이 1 인 몫으로. 합이 0 이면 모두 0 이다."""
    total = sum(amounts.get(v, 0.0) for v in venues)
    return {v: (amounts.get(v, 0.0) / total if total > 0 else 0.0) for v in venues}


def gaps(predicted: dict[str, float], actual: dict[str, float]) -> tuple[float, float]:
    """(가장 큰 차이 %p, 어긋난 몫 %).

    예측의 몫이 모두 0 이면(워커힐 업장에 아무 몫도 주지 않음) 하나도 맞히지 못한 것이라 어긋난 몫은 100% 다
    (차이 합의 반으로 재면 50% 가 나와, 아무것도 예측하지 않은 쪽이 반대로 맞힌 쪽보다 나아 보인다).
    """
    diffs = [abs(predicted.get(v, 0.0) - actual.get(v, 0.0)) for v in set(predicted) | set(actual)]
    worst = round(100 * max(diffs, default=0.0), DIFF_DIGITS)
    if sum(predicted.values()) <= 0 < sum(actual.values()):
        return worst, 100.0
    return worst, round(100 * sum(diffs) / 2, DIFF_DIGITS)


def held_out(
    visits: list[ScoredVisit], target: dict[str, dict[str, float]], group: str, k: float, walkerhill: set[str], fixed: dict[str, float]
) -> tuple[dict[str, float] | None, str | None]:
    """그 고객군을 빼고 나머지로 업장 상수를 추정해 그 고객군에 쓴 사람 수. 추정하지 못하면 (None, 까닭)."""
    others = [v for v in visits if v.group != group]
    rest = {g: people for g, people in target.items() if g != group}
    try:
        found = fit(others, rest, k, walkerhill, fixed)
    except NotFitted as exc:
        return None, f"나머지 고객군으로 상수를 추정하지 못했다: {exc}"
    mine = [v for v in visits if v.group == group]
    return simulate(mine, k, {**fixed, **found.constants}, walkerhill).get(group, {}), None


def crosscheck(root: Path, data_mode: str, run_id: str | None = None) -> tuple[Path, CrossCheck]:
    """기준 실행 하나로 두 겹의 검증을 재 `crosscheck.json` 을 쓴다. (파일 자리, 결과)를 돌려준다.

    기준 실행의 조건은 상수 추정과 같다 (점수를 받았고, 일 년 전체, 실패 없음, 페르소나와 조건을 모두 돌림, 입력이 그대로).
    """
    record = _record(root, data_mode, run_id)
    if record.share_method != "scores":
        raise ValueError(
            f"기준 실행 '{record.run_id}' 의 방문이 모두 점수를 받은 것이 아니다 (share_method 가 {record.share_method or '없음'}). "
            "점수를 묻는 판의 프롬프트로 돌린 기준 실행으로 잰다"
        )
    # 추정한 상수 파일은 읽지 않는다: 그 값은 이 실행의 모든 고객군으로 낸 것이라, 다른 고객군에 써 보는 검증에 섞이면 안 된다.
    inputs = load_inputs(root, data_mode, BASELINE_ID, None, record.persona_ids, record.base_profile_mode, with_estimated=False)
    everyone = load_inputs(root, data_mode, BASELINE_ID, None, None, record.base_profile_mode, with_estimated=False).personas
    missing = sorted(set(everyone) - set(record.persona_ids)) + sorted(
        {c.condition_id for c in inputs.conditions.conditions} - set(record.condition_ids)
    )
    if missing:
        raise ValueError(f"기준 실행 '{record.run_id}' 은 페르소나나 조건을 일부만 돌렸다 (빠진 것 {missing}). 모두 돌린 기준 실행으로 잰다")
    changed = [key for key in ("venues", "personas", "conditions", "scenario", "vocab", "summary", "constants") if record.inputs.get(key) != inputs.hashes[key]]
    if changed:
        raise ValueError(f"기준 실행 '{record.run_id}' 과 달라진 것이 있다: {', '.join(changed)}. 기준 상황을 다시 돌린 뒤에 잰다")
    conditions = [inputs.conditions.condition(condition_id) for condition_id in record.condition_ids]
    if None in conditions:
        raise ValueError("방문 조건 묶음에 없는 조건이 실행 기록에 있다. 화면에서 조건을 직접 넣어 돌린 실행은 재지 않는다")
    rows = [LedgerRow.from_row(row) for row in read_csv(runs_folder(root, data_mode) / record.run_id / "ledger.csv", LEDGER_COLUMNS)]
    visits, _ = scored_visits(rows, inputs.personas)
    walkerhill = {venue_id for venue_id, venue in inputs.venues.items() if not venue.is_competitor}
    target = group_venue_people(
        inputs.summary, conditions, inputs.conditions.assumed_splits, inputs.venues, average_parties(list(inputs.personas.values()))
    )
    # "상수 없음"은 engine/constants.json 의 업장 상수만 쓴다 (추정한 상수는 쓰지 않는다).
    k = inputs.shares.k
    fixed = inputs.shares.venue_constants
    no_constants = simulate(visits, k, fixed, walkerhill)
    reviews = review_counts(root, walkerhill, conditions)
    groups = sorted({v.group for v in visits if sum(target.get(v.group, {}).values()) > 0})
    if len(groups) < 2:
        raise ValueError("실제 몫이 있고 점수를 받은 고객군이 둘보다 적어 다른 고객군에 써 볼 수 없다")
    # 먼저 고객군마다 방법마다의 사람 수(또는 후기 수)를 모은다.
    raw: dict[str, dict[str, dict[str, float] | None]] = {}
    notes: dict[str, str | None] = {}
    for group in groups:
        people, notes[group] = held_out(visits, target, group, k, walkerhill, fixed)
        counted = {v: float(n) for v, n in reviews.get(group, {}).items()}
        raw[group] = {
            "actual": target[group],
            "no_constants": no_constants.get(group, {}),
            "held_out": people,
            "simple": counted if sum(counted.values()) > 0 else None,
        }
    # 견주는 업장: 어느 고객군, 어느 방법에서든 몫이 0 보다 큰 워커힐 업장. 실제로는 아무도 가지 않는데 AI 가 고르는 업장도 넣어야
    # 그 몫이 어긋난 몫에 잡힌다 (빼면 나머지 업장으로 다시 나눠져 오차가 숨는다).
    venues = sorted({v for by_method in raw.values() for amounts in by_method.values() if amounts for v, x in amounts.items() if x > 0})
    found = {}
    for group in groups:
        actual = shares(raw[group]["actual"] or {}, venues)
        predicted = {m: (shares(raw[group][m], venues) if raw[group][m] is not None else None) for m in METHODS}
        found[group] = {
            "actual": {v: round(x, SHARE_DIGITS) for v, x in actual.items()},
            **{m: ({v: round(x, SHARE_DIGITS) for v, x in p.items()} if p is not None else None) for m, p in predicted.items()},
            "max_diff_pp": {m: (gaps(p, actual)[0] if p is not None else None) for m, p in predicted.items()},
            "misplaced_pct": {m: (gaps(p, actual)[1] if p is not None else None) for m, p in predicted.items()},
            "simple_reviews": int(sum((raw[group]["simple"] or {}).values())),
            "held_out_note": notes[group],
        }
    result = CrossCheck.model_validate(
        {
            "format_version": 1,
            "run_id": record.run_id,
            "k": k,
            "base_profile_mode": record.base_profile_mode,
            "venues": venues,
            "groups": found,
        }
    )
    path = runs_folder(root, data_mode) / record.run_id / "crosscheck.json"
    write_json(path, result.model_dump(mode="json"))
    return path, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine.crosscheck", description="다른 고객군에 써 보기와 단순 기준과 견주기 (T212).")
    parser.add_argument("--data", choices=("sample", "private"), required=True, help="sample 가상 예시 값, private 기본 데이터")
    parser.add_argument("--run", metavar="RUN_ID", help="잴 기준 실행. 적지 않으면 일 년 전체로 끝까지 돈 가장 새 기준 실행")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="자료를 읽고 결과를 쓸 폴더 (기본은 지금 폴더)")
    args = parser.parse_args(argv)
    try:
        path, result = crosscheck(args.root.resolve(), args.data, args.run)
    except (FileNotFoundError, ValueError) as exc:
        print(f"재지 못했다: {exc}", file=sys.stderr)
        return EXIT_FAILED

    print(f"결과: {path}")
    if result.base_profile_mode != "none":
        print(
            f"주의: 이 기준 실행은 기본 데이터의 요약을 보냈다 (base_profile_mode {result.base_profile_mode}). 페르소나마다 자기 고객군의 업장 몫 요약이 "
            "프롬프트에 들어가 AI 점수가 이미 그 고객군의 분포를 보고 나왔다. 그래서 '다른 고객군으로 추정'도 완전히 떼어 둔 검증이 아니다. "
            "완전히 떼어 두려면 --base-profile none 으로 받은 기준 실행으로 잰다",
            file=sys.stderr,
        )
    print("고객군마다 실제와의 어긋난 몫(%) · 가장 큰 차이(%p). 작을수록 맞다:")
    for group, entry in result.groups.items():
        parts = []
        for method in METHODS:
            misplaced, worst = entry.misplaced_pct[method], entry.max_diff_pp[method]
            parts.append(f"{LABELS[method]} {'잴 수 없음' if misplaced is None else f'{misplaced:.1f}% · {worst:.1f}%p'}")
        print(f"- {group}: " + " / ".join(parts))
        if entry.held_out_note:
            print(f"  {entry.held_out_note}", file=sys.stderr)
        if entry.simple is None:
            print("  공개 후기에 이 고객군 라벨이 붙은 워커힐 업장 후기가 없어 단순 기준을 잴 수 없다", file=sys.stderr)
    better = result.held_out_better_than_simple()
    print(f"다른 고객군으로 추정한 상수가 단순 기준보다 어긋난 몫이 작은 고객군: {better[0]} / 견줄 수 있는 고객군 {better[1]}")
    if args.data == "private":
        print("이 결과는 기본 데이터에서 계산한 값이다. 저장소·커밋·연락판에는 단순 기준보다 나았는지와 잰 방법만 적는다.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
