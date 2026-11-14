"""실행하는 명령 (README.md 의 "실행 방법").

    uv run python -m engine --data sample

상황 하나를 돌려 실행 폴더를 쓴다. 방문마다 앞선 실행의 저장된 응답을 먼저 찾아 재생하고, 없는 것만 LLM 을 부른다.
공급자, 모델, 호출 상한, 키는 `.env` 에서 읽는다 (`.env.example`).
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from engine.formats.io import read_csv, read_model
from engine.formats.run import LEDGER_COLUMNS, RunRecord
from engine.llm import LlmFatal, make_provider, settings_from_env
from engine.runner import NotSupportedYet, run, runs_folder

EXIT_OK, EXIT_FAILED, EXIT_STOPPED_BY_LIMIT = 0, 1, 2


def earlier_answers(root: Path, data_mode: str) -> list[Path]:
    """앞선 실행들의 저장된 응답 폴더. 새 실행부터 본다.

    같은 `data_mode` 의 실행만 본다. 가상 예시로 돌릴 때 `private/` 를 읽지 않으려는 것이다.
    """
    folder = runs_folder(root, data_mode)
    return sorted((p for p in folder.glob("*/llm") if p.is_dir()), reverse=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine", description="상황 하나를 돌려 실행 결과를 쓴다.")
    parser.add_argument("--data", choices=("sample", "private"), required=True, help="sample 가상 예시 값, private 기본 데이터")
    parser.add_argument("--scenario", default="baseline", help="상황의 scenario_id (기본 baseline)")
    parser.add_argument("--prompt", default="p1", help="프롬프트의 판 이름. personas/prompts/<이름>.md 를 읽는다 (기본 p1)")
    parser.add_argument("--personas", nargs="+", metavar="ID", help="돌릴 페르소나. 적지 않으면 모두")
    parser.add_argument("--conditions", nargs="+", metavar="ID", help="돌릴 방문 조건. 적지 않으면 묶음의 모든 조건")
    parser.add_argument("--venues", nargs="+", metavar="ID", help="읽을 업장. 적지 않으면 모두")
    parser.add_argument("--answers", type=Path, action="append", default=[], metavar="폴더", help="저장된 응답을 더 찾을 폴더")
    parser.add_argument("--replay-only", action="store_true", help="LLM 을 부르지 않고 저장된 응답만 재생한다 (키가 없어도 된다)")
    parser.add_argument("--limit", type=int, metavar="N", help="새로 부를 수 있는 횟수. 적지 않으면 LLM_CALL_LIMIT")
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
            llm=provider,
            call_limit=call_limit,
        )
    except (LlmFatal, NotSupportedYet, FileNotFoundError, FileExistsError, ValueError) as exc:
        print(f"돌리지 못했다: {exc}", file=sys.stderr)
        return EXIT_FAILED

    record = read_model(run_dir / "run.json", RunRecord)
    print(f"실행 폴더: {run_dir}")
    print(f"공급자 {record.llm.provider} · 모델 {record.llm.model} · 프롬프트 {record.llm.prompt_version}")
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
