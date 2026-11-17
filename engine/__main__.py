"""실행하는 명령 (README.md 의 "실행 방법").

    uv run python -m engine --data sample

상황 하나를 돌려 실행 폴더를 쓴다. 방문마다 앞선 실행의 저장된 응답을 먼저 찾아 재생하고, 없는 것만 LLM 을 부른다.
기준이 아닌 상황(`--scenario`)은 끝까지 돈 가장 새 기준 실행의 페르소나, 방문 조건, 가중치로 돌린다.
공급자, 모델, 호출 상한, 키는 `.env` 에서 읽는다 (`.env.example`).
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from engine.formats.io import read_csv, read_model
from engine.formats.run import LEDGER_COLUMNS, RunRecord
from engine.formats.scenario import BASELINE_ID
from engine.llm import LlmFatal, make_provider, settings_from_env
from engine.runner import latest_baseline_run, month_label, run, runs_folder

EXIT_OK, EXIT_FAILED, EXIT_STOPPED_BY_LIMIT = 0, 1, 2

# `--prompt` 를 적지 않았을 때 읽는 판. 팀이 쓰는 가장 새 판이다 (personas/prompts/, 페르소나 담당이 올린다).
# 예시 묶음(tests/fixtures/example)에는 p1 만 있어, 그 사본을 돌릴 때는 `--prompt p1` 을 적는다 (README.md).
# p3 은 방문 조건의 달(`condition.month`)을 읽는 법과 값 목록의 "이용 시간 제한"을 적은 판이다 (T304, T113).
DEFAULT_PROMPT = "p3"


def earlier_answers(root: Path, data_mode: str) -> list[Path]:
    """앞선 실행들의 저장된 응답 폴더. 새 실행부터 본다.

    같은 `data_mode` 의 실행만 본다. 가상 예시로 돌릴 때 `private/` 를 읽지 않으려는 것이다.
    """
    folder = runs_folder(root, data_mode)
    return sorted((p for p in folder.glob("*/llm") if p.is_dir()), reverse=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine", description="상황 하나를 돌려 실행 결과를 쓴다.")
    parser.add_argument("--data", choices=("sample", "private"), required=True, help="sample 가상 예시 값, private 기본 데이터")
    parser.add_argument("--scenario", default=BASELINE_ID, help="상황의 scenario_id (기본 baseline)")
    parser.add_argument(
        "--baseline",
        metavar="RUN_ID",
        help="기준이 아닌 상황이 페르소나·방문 조건·가중치를 가져올 기준 실행. 적지 않으면 끝까지 돈 가장 새 기준 실행",
    )
    parser.add_argument(
        "--prompt", default=DEFAULT_PROMPT, help=f"프롬프트의 판 이름. personas/prompts/<이름>.md 를 읽는다 (기본 {DEFAULT_PROMPT})"
    )
    parser.add_argument("--personas", nargs="+", metavar="ID", help="돌릴 페르소나. 적지 않으면 모두")
    parser.add_argument("--conditions", nargs="+", metavar="ID", help="돌릴 방문 조건. 적지 않으면 묶음의 모든 조건")
    parser.add_argument("--venues", nargs="+", metavar="ID", help="읽을 업장. 적지 않으면 모두")
    parser.add_argument(
        "--month",
        type=int,
        choices=range(1, 13),
        metavar="1~12",
        help="실행의 달. 묶음의 조건을 모두 그 달의 방문으로 돌린다. 적지 않으면 일 년 전체로 본다. "
        "기준이 아닌 상황은 달이 같은 가장 새 기준 실행을 고른다 (--baseline 으로 가리키면 그 실행의 달을 따른다)",
    )
    parser.add_argument("--answers", type=Path, action="append", default=[], metavar="폴더", help="저장된 응답을 더 찾을 폴더")
    parser.add_argument("--replay-only", action="store_true", help="LLM 을 부르지 않고 저장된 응답만 재생한다 (키가 없어도 된다)")
    parser.add_argument("--limit", type=int, metavar="N", help="새로 부를 수 있는 횟수. 적지 않으면 LLM_CALL_LIMIT")
    parser.add_argument(
        "--base-profile",
        choices=("bucketed", "raw", "none"),
        help="기본 데이터의 요약을 LLM 에 보내는 방식 (--data private 만). 적지 않으면 bucketed (범주로 바꿔 보냄). "
        "기준이 아닌 상황은 기준 실행의 방식을 따른다",
    )
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="자료를 읽고 결과를 쓸 폴더 (기본은 지금 폴더). .env 는 늘 지금 폴더의 것을 읽는다"
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    # 설정과 키는 명령을 돌리는 폴더의 .env 하나에서만 읽는다. --root 로 가리킨 폴더의 .env 는 읽지 않는다
    # (그 폴더의 파일이 주소를 바꿔 이 PC 의 키를 다른 곳으로 보내게 할 수 있다).
    load_dotenv(Path.cwd() / ".env")
    try:
        settings = settings_from_env()
        provider = None if args.replay_only else make_provider(settings)
        call_limit = settings.call_limit if args.limit is None else args.limit
        if call_limit < 0:
            raise LlmFatal("--limit 은 0 이상의 정수다")
        weights_from = args.baseline
        if weights_from is None and args.scenario != BASELINE_ID:
            # 달이 같은 기준 실행만 고른다. 달을 적지 않았으면 일 년 전체로 돌린 것이다 (적지 않은 달이 조용히 따라오지 않게 한다).
            weights_from = latest_baseline_run(root, args.data, args.month)
            if weights_from is None:
                how = "" if args.month is None else f" --month {args.month} 로"
                raise ValueError(
                    f"{month_label(args.month)}로 끝까지 돈 기준 실행이 없다. 기준 상황을{how} 먼저 끝까지 돌린다 "
                    "(다른 달로 돌린 기준 실행을 쓰려면 --month 나 --baseline 으로 가리킨다)"
                )
        run_dir = run(
            root,
            data_mode=args.data,
            now=datetime.now().astimezone(),
            provider=settings.provider,
            model=settings.model,
            prompt_version=args.prompt,
            answers=[*args.answers, *earlier_answers(root, args.data)],
            scenario_id=args.scenario,
            venue_ids=args.venues,
            persona_ids=args.personas,
            condition_ids=args.conditions,
            weights_from=weights_from,
            llm=provider,
            call_limit=call_limit,
            base_profile_mode=args.base_profile,
            month=args.month,
        )
    except (LlmFatal, FileNotFoundError, FileExistsError, ValueError) as exc:
        print(f"돌리지 못했다: {exc}", file=sys.stderr)
        return EXIT_FAILED

    record = read_model(run_dir / "run.json", RunRecord)
    print(f"실행 폴더: {run_dir}")
    if record.weights_from is not None:
        print(f"상황 {record.scenario_id} · 페르소나, 방문 조건, 가중치는 기준 실행 {record.weights_from} 의 것")
    print(f"공급자 {record.llm.provider} · 모델 {record.llm.model} · 프롬프트 {record.llm.prompt_version}")
    print(f"달 {month_label(record.month)}")
    print(
        f"기본 데이터의 요약 {record.base_profile_mode} · "
        f"가격을 집계 파일로 채운 상품 {len(record.filled_products)}개 · 채우지 못해 뺀 상품 {len(record.skipped_products)}개"
    )
    if record.weights_from is None:
        # 배수를 정하지 못한 고객군은 가중치가 0 이라 그 고객군의 방문이 가상 매출에 들지 않는다. 상황에도 그대로 간다.
        grades = record.weights.grades
        unfitted = [group for group, grade in grades.group_multiplier.items() if grade == "unknown"]
        # 묶음의 비율도 낼 수 없었으면 집계 파일에 그 고객군의 매출이 없는 것이다. 가장 흔한 까닭은 고객군 이름이 다른 것이다.
        missing = [g for g in unfitted if set(grades.condition_ratio.get(g, {}).values()) <= {"unknown"}]
        unchosen = [g for g in unfitted if g not in missing]
        if missing:
            print(
                f"집계 파일에서 이 실행의 조건에 해당하는 매출을 찾지 못한 고객군이 있다: {', '.join(missing)}. "
                "페르소나의 customer_group 이 집계 파일의 고객군 이름과 글자까지 같은지 본다. 그 고객군의 가중치는 0 이다.",
                file=sys.stderr,
            )
        if unchosen:
            print(
                f"고객군 배수를 정하지 못한 고객군이 있다: {', '.join(unchosen)}. "
                "이 실행에서 그 고객군이 묶음의 비율이 0 이 아닌 조건에서 워커힐 업장을 고른 방문이 없다 (실패한 방문은 세지 않는다). "
                "그 고객군의 가중치는 0 이다.",
                file=sys.stderr,
            )
    print(
        f"방문 {record.counts.visits}건 (실패 {record.counts.failed}건) · "
        f"새로 부름 {record.llm.calls_new}번 · 재생 {record.llm.calls_replayed}번 · 호출 상한 {record.llm.call_limit}번"
    )
    if record.status == "stopped_by_limit":
        print(
            f"호출 상한({record.llm.call_limit}번)에 닿아 멈췄다. 남은 방문은 돌리지 않았다. "
            "다시 돌리면 받은 답은 재생하고 남은 방문만 새로 부른다.",
            file=sys.stderr,
        )
        return EXIT_STOPPED_BY_LIMIT
    if record.status == "failed":
        # 멈춘 이유는 마지막으로 돌린 방문의 실패한 줄에 있다.
        reason = read_csv(run_dir / "ledger.csv", LEDGER_COLUMNS)[-1]["fail_reason"]
        print(f"LLM 을 부를 수 없어 멈췄다: {reason}", file=sys.stderr)
        return EXIT_FAILED
    if record.counts.failed:
        print("실패한 방문이 있다. 이유는 원장(ledger.csv)의 fail_reason 에 있다. 검사에서 어긋난 응답은 llm_rejected/ 에 남는다.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
