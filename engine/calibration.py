"""보정의 대조 (docs/PRD.md 6.5절, docs/FORMATS.md 10.4절).

    uv run python -m engine.calibration --data sample

끝까지 돈 기준 실행 하나를 기본 데이터와 견줘 그 실행 폴더에 `calibration.json` 을 쓴다.
페르소나가 있는 고객군마다, 워커힐 업장별 매출 비중을 가상 매출(원장)과 기본 데이터(집계 파일)에서 내어 견준다.
LLM 을 부르지 않는다. 같은 실행을 다시 대조하면 파일을 덮어쓴다.
"""

import argparse
import sys
from pathlib import Path

from engine.constants import constant
from engine.formats.codes import BASE_SEGMENT
from engine.formats.io import read_csv, read_model, write_json
from engine.formats.run import LEDGER_COLUMNS, RUN_ID_RE, Calibration, LedgerRow, RunRecord
from engine.formats.scenario import BASELINE_ID
from engine.ledger import venue_shares
from engine.runner import latest_baseline_run, load_inputs, month_label, runs_folder
from engine.weights import group_venue_revenue

EXIT_OK, EXIT_FAILED = 0, 1

# 통과 기준 (docs/PRD.md 6.5절). 첫 대조(11-17) 뒤 한 번만 고칠 수 있고, 고치면 이유를 진행 문서의 T18 절에 적는다.
# 명령의 인자로 두지 않은 까닭: 돌릴 때마다 바꿔 가며 통과시키지 못하게 한다.
# 값과 근거는 engine/constants.json 에 있다 (T210).
TOP_VENUE_MUST_MATCH = bool(constant("calibration-top-venue-must-match"))
MAX_DIFF_PP = constant("calibration-max-diff-pp")
# 11-17 의 첫 대조 뒤 한 번 고친 것 (T18, T119): 페르소나가 이 수보다 적은 고객군은 업장별 차이를 적기만 하고 통과를 가르지 않는다.
# 페르소나가 한 명이면 고르기 하나가 그 고객군 비중의 약 4분의 1 이라, 차이를 맞추려면 끼니마다 업장을 적어 넣어야 한다.
DIFF_MIN_PERSONAS = int(constant("calibration-diff-min-personas"))

# 비중은 소수 넷째 자리, 차이(%p)는 둘째 자리까지 적는다. 통과 여부는 적힌 차이로 정한다.
SHARE_DIGITS = 4
DIFF_DIGITS = 2

# 기준 실행 뒤에 달라지면 대조가 어긋나는 입력. 업장을 골라 돌린 실행(`--venues`)도 여기서 걸린다 (읽은 업장이 달라 해시가 다르다).
# 프롬프트는 견주지 않는다. 대조는 원장만 보고 LLM 을 부르지 않는다.
COMPARED_INPUTS = ("venues", "personas", "conditions", "scenario", "vocab", "summary", "constants")


def _top(shares: dict[str, float]) -> str | None:
    """비중이 가장 큰 업장. 매출이 없으면 None. 적힌 비중이 같으면 업장 정의의 차례에서 앞의 것이다."""
    best = max(shares.values(), default=0.0)
    return next((venue_id for venue_id, share in shares.items() if share == best), None) if best > 0 else None


def compare(sim: dict[str, float], base: dict[str, float], venue_ids: list[str], check_diffs: bool = True) -> dict:
    """한 고객군의 대조 결과. `sim`, `base` 는 업장마다의 매출이다 (단위는 상관없다. 비중만 본다).

    `check_diffs` 가 거짓이면 업장별 차이는 적기만 하고 통과는 가장 큰 업장으로만 가른다 (페르소나가 한 명인 고객군).
    """
    sim_total, base_total = sum(sim.values()), sum(base.values())
    sim_share = {v: sim.get(v, 0.0) / sim_total if sim_total > 0 else 0.0 for v in venue_ids}
    base_share = {v: base.get(v, 0.0) / base_total if base_total > 0 else 0.0 for v in venue_ids}
    # 가장 큰 업장도 적는 자릿수의 비중으로 정한다. 파일에는 같게 적히는데 끝자리 차이로 가장 큰 업장이 갈리는 일이 없다.
    sim_written = {v: round(share, SHARE_DIGITS) for v, share in sim_share.items()}
    base_written = {v: round(share, SHARE_DIGITS) for v, share in base_share.items()}
    # 차이는 적는 자릿수로 반올림한 값으로 견준다. 파일에 적힌 값만으로 통과 여부를 다시 낼 수 있고,
    # 소수 계산의 끝자리(0.40 − 0.25 가 15.000000000000002 %p 가 되는 것) 때문에 경계에서 갈리지 않는다.
    # 0.0 을 더해 −0.0 이 적히지 않게 한다.
    diffs = {v: round((sim_share[v] - base_share[v]) * 100, DIFF_DIGITS) + 0.0 for v in venue_ids}
    top_sim, top_base = _top(sim_written), _top(base_written)
    # 어느 한쪽에 매출이 없으면 견줄 수 없어 통과가 아니다.
    comparable = top_sim is not None and top_base is not None
    small = not check_diffs or all(abs(d) <= MAX_DIFF_PP for d in diffs.values())
    passed = comparable and (top_sim == top_base or not TOP_VENUE_MUST_MATCH) and small
    return {
        "venues": {
            v: {
                "sim_share": sim_written[v],
                "base_share": base_written[v],
                "diff_pp": diffs[v],
            }
            for v in venue_ids
        },
        "top_sim": top_sim,
        "top_base": top_base,
        "pass": passed,
    }


def _record(root: Path, data_mode: str, run_id: str | None) -> RunRecord:
    """대조할 기준 실행의 실행 기록. 적지 않으면 일 년 전체로 끝까지 돈 가장 새 기준 실행이다."""
    if run_id is None:
        run_id = latest_baseline_run(root, data_mode, None)
        if run_id is None:
            raise ValueError("대조할 기준 실행이 없다. 기준 상황을 달을 주지 않고 끝까지 돌린 뒤에 대조한다")
    if not RUN_ID_RE.match(run_id):
        raise ValueError(f"기준 실행의 run_id 가 아니다: {run_id!r}")
    path = runs_folder(root, data_mode) / run_id / "run.json"
    if not path.is_file():
        raise FileNotFoundError(f"실행 기록이 없다: {path}")
    record = read_model(path, RunRecord)
    if record.scenario_id != BASELINE_ID:
        raise ValueError(f"실행 '{run_id}' 는 기준 상황의 실행이 아니다. 보정은 기준 상황으로 한다")
    if record.status != "ok":
        raise ValueError(f"기준 실행 '{run_id}' 는 끝까지 돌지 않았다 (status 가 {record.status}). 기준 상황을 다시 돌린다")
    if record.month is not None:
        raise ValueError(
            f"기준 실행 '{run_id}' 는 {month_label(record.month)}로 돌린 것이다. 보정은 달을 주지 않은 기준 실행으로 한다 "
            "(달을 준 실행의 가상 매출은 그 달의 매출이 아니다. docs/FORMATS.md 10.1절의 \"실행의 달\")"
        )
    if record.counts.failed:
        # 실패한 방문은 금액이 0 인 줄이다. 그 방문이 빠진 채로 견주면 비중이 그만큼 어긋난다.
        raise ValueError(
            f"기준 실행 '{run_id}' 에 실패한 방문이 {record.counts.failed}건 있어 대조하지 않는다. "
            "이유는 그 실행의 원장(ledger.csv)의 fail_reason 에 있다. 기준 상황을 --replay-only 없이 다시 돌리면 받은 답은 재생하고 그 방문만 새로 부른다. "
            "실패가 없는 앞선 실행을 대조하려면 --run 으로 가리킨다"
        )
    return record


def calibrate(root: Path, data_mode: str, run_id: str | None = None) -> tuple[Path, Calibration, dict[str, list[str]]]:
    """기준 실행 하나를 기본 데이터와 견줘 `calibration.json` 을 쓰고, 그 파일의 자리와 결과, 고객군마다 돌리지 않은 페르소나를 돌려준다.

    - `run_id` 를 주지 않으면 일 년 전체로 끝까지 돈 가장 새 기준 실행을 고른다.
    - 실패한 방문이 있거나, 달을 주고 돌렸거나, 실행 뒤에 입력(업장 정의, 페르소나, 조건 묶음, 값 목록, 집계 파일)이 달라졌으면 대조하지 않고 `ValueError` 로 멈춘다.
      업장을 골라 돌린 실행도 멈춘다. 비중의 분모가 워커힐 업장 전체여야 하기 때문이다 (docs/PRD.md 6.5절).
    - 가상 매출 쪽은 원장의 `weighted_revenue`, 기본 데이터 쪽은 같은 줄과 몫으로 센 매출이다 (`engine.weights.group_venue_revenue`).
      견주는 것은 고객군마다 매출이 업장 사이에 나뉜 모양(비중)이다. 11-19(T210)부터 가중치를 인원으로 정해,
      고객군의 합계는 두 쪽이 같지 않을 수 있다 (그 차이는 맞추지 않고 남긴다).
    - 대조하는 고객군은 저장소에 워커힐 고객 페르소나가 있는 고객군 모두다 (docs/PRD.md 6.5절, 다른 무리는 넣지 않는다 T220). 그 고객군의 페르소나 가운데 실행에 빠진 것이 있으면
      비중은 돌린 페르소나만으로 적되 통과가 아니다. 한 고객군을 일부 페르소나로 맞춘 결과는 보정의 근거가 아니기 때문이다.
    """
    record = _record(root, data_mode, run_id)
    inputs = load_inputs(root, data_mode, BASELINE_ID, None, record.persona_ids, record.base_profile_mode)
    changed = [key for key in COMPARED_INPUTS if record.inputs.get(key) != inputs.hashes[key]]
    # 추정한 상수 파일(T212)은 있을 때만 해시가 남는다. 실행 뒤에 생기거나 바뀌었으면 원장의 몫이 지금 상수와 다르다.
    if record.inputs.get("estimated") != inputs.hashes.get("estimated"):
        changed.append("estimated")
    if changed:
        raise ValueError(
            f"기준 실행 '{record.run_id}' 과 달라진 것이 있다: {', '.join(changed)}. "
            "실행 뒤에 입력을 고쳤거나 업장을 골라 돌린 실행이다. 기준 상황을 업장을 고르지 않고 다시 돌린 뒤에 대조한다"
        )
    run_dir = runs_folder(root, data_mode) / record.run_id
    # 기본 데이터와 견주는 것은 워커힐 고객 페르소나의 방문뿐이다. 다른 무리는 기본 데이터에 없는 손님이다 (11-20 T220).
    base_ids = {persona_id for persona_id, persona in inputs.personas.items() if persona.segment == BASE_SEGMENT}
    rows = [row for row in (LedgerRow.from_row(r) for r in read_csv(run_dir / "ledger.csv", LEDGER_COLUMNS)) if row.persona_id in base_ids]
    conditions = [inputs.conditions.condition(condition_id) for condition_id in record.condition_ids]
    if None in conditions:
        raise ValueError(
            f"방문 조건 묶음에 없는 조건이 실행 기록에 있다: {record.condition_ids}. "
            "화면에서 조건을 직접 넣어 돌린 실행(manual-)은 가중치가 없어 대조하지 않는다"
        )

    venue_ids = [venue_id for venue_id, venue in inputs.venues.items() if not venue.is_competitor]
    base = group_venue_revenue(inputs.summary, conditions, inputs.conditions.assumed_splits, inputs.venues)
    # 저장소의 페르소나를 모두 읽어, 고객군마다 실행에 빠진 페르소나를 찾는다. 실행은 페르소나의 일부만 돌렸을 수 있다.
    everyone = {
        persona_id: persona
        for persona_id, persona in load_inputs(root, data_mode, BASELINE_ID, None, None, record.base_profile_mode).personas.items()
        if persona.segment == BASE_SEGMENT
    }
    not_run: dict[str, list[str]] = {}
    for persona_id, persona in everyone.items():
        if persona_id not in inputs.personas:
            not_run.setdefault(persona.customer_group, []).append(persona_id)
    covered = sorted({persona.customer_group for persona in everyone.values()})
    # 고객군의 페르소나 수는 저장소의 수다. 실행에서 일부만 돌린 고객군은 위에서 미달로 적힌다.
    sizes = {group: sum(persona.customer_group == group for persona in everyone.values()) for group in covered}
    groups = {}
    for group in covered:
        sim = {venue_id: entry["weighted_revenue"] for venue_id, entry in venue_shares(rows, group)["walkerhill"].items()}
        found = compare(sim, base.get(group, {}), venue_ids, check_diffs=sizes[group] >= DIFF_MIN_PERSONAS)
        if group in not_run:
            found["pass"] = False
        # 파일의 키 차례: venues, top_sim, top_base, personas, pass (FORMATS.md 10.4절의 예시).
        groups[group] = {**{k: v for k, v in found.items() if k != "pass"}, "personas": sizes[group], "pass": found["pass"]}
    result = Calibration.model_validate(
        {
            "format_version": 1,
            "run_id": record.run_id,
            "criteria": {"top_venue_must_match": TOP_VENUE_MUST_MATCH, "max_diff_pp": MAX_DIFF_PP, "diff_min_personas": DIFF_MIN_PERSONAS},
            "groups": groups,
            # 기본 데이터에 매출이 있는데 페르소나가 없어 다루지 않은 고객군.
            "uncovered_groups": sorted(group for group, by_venue in base.items() if group not in covered and sum(by_venue.values()) > 0),
            "pass": bool(groups) and all(group["pass"] for group in groups.values()),
        }
    )
    path = run_dir / "calibration.json"
    write_json(path, result.model_dump(mode="json", by_alias=True))
    return path, result, {group: sorted(persona_ids) for group, persona_ids in sorted(not_run.items())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine.calibration", description="기준 실행 하나를 기본 데이터와 견줘 calibration.json 을 쓴다.")
    parser.add_argument("--data", choices=("sample", "private"), required=True, help="sample 가상 예시 값, private 기본 데이터")
    parser.add_argument("--run", metavar="RUN_ID", help="대조할 기준 실행. 적지 않으면 일 년 전체로 끝까지 돈 가장 새 기준 실행")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="자료를 읽고 결과를 쓸 폴더 (기본은 지금 폴더)")
    args = parser.parse_args(argv)
    try:
        path, result, not_run = calibrate(args.root.resolve(), args.data, args.run)
    except (FileNotFoundError, ValueError) as exc:
        print(f"대조하지 못했다: {exc}", file=sys.stderr)
        return EXIT_FAILED

    print(f"대조 결과: {path}")
    print(
        f"통과 기준: 비중이 가장 큰 업장이 같다 ({'본다' if result.criteria.top_venue_must_match else '보지 않는다'}) · "
        f"업장별 비중의 차이가 모두 {result.criteria.max_diff_pp:g}%p 이내 "
        f"(페르소나가 {result.criteria.diff_min_personas}명보다 적은 고객군, 곧 페르소나가 한 명인 고객군은 가장 큰 업장만 본다)"
    )
    for group, found in result.groups.items():
        worst = max(found.venues.items(), key=lambda item: abs(item[1].diff_pp), default=None)
        gap = f"{worst[0]} {worst[1].diff_pp:+.2f}%p" if worst else "없음"
        few = found.personas is not None and found.personas < result.criteria.diff_min_personas
        print(
            f"- {group}: {'통과' if found.passed else '미달'} · 가장 큰 업장 가상 {found.top_sim or '없음'} / 기본 {found.top_base or '없음'} · "
            f"가장 큰 차이 {gap}" + (f" (페르소나 {found.personas}명이라 차이는 보지 않음)" if few else "")
        )
        if group in not_run:
            print(
                f"  이 고객군의 페르소나 가운데 돌리지 않은 것이 있어 통과로 보지 않는다: {', '.join(not_run[group])}. "
                "보정은 페르소나를 모두 돌린 기준 실행으로 한다",
                file=sys.stderr,
            )
        if found.top_sim is None:
            print("  가상 매출이 없다. 이 고객군이 워커힐 업장을 고른 방문이 없거나 고객군 배수를 정하지 못했다", file=sys.stderr)
        if found.top_base is None:
            print("  기본 데이터에 이 고객군의 매출이 없다. 페르소나의 customer_group 이 집계 파일의 고객군 이름과 같은지 본다", file=sys.stderr)
    if result.uncovered_groups:
        print(f"다루지 않은 고객군 (페르소나가 없다): {', '.join(result.uncovered_groups)}")
    print(f"전체: {'통과' if result.passed else '미달'}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
