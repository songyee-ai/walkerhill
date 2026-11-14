"""실행기: 상황 하나에서 페르소나마다, 방문 조건마다 한 번씩 돌려 실행 결과를 쓴다 (docs/FORMATS.md 10절).

방문마다 저장된 응답을 먼저 찾는다. 있으면 재생하고, 없으면 LLM 을 불러 답을 받아 검사한 뒤 저장한다.
LLM 을 주지 않고 돌리면(재생만) 저장된 응답이 없는 방문은 실패로 남는다.
상황 적용과 프로모션은 T10, 집계 파일로 가중치를 내는 것은 T11 에서 더한다.
"""

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from engine.answers import AnswerBook, read_reply, save_rejected, save_response
from engine.candidates import build_request, run_condition
from engine.formats.choice import RunCondition, problems_in_response
from engine.formats.conditions import MANUAL_CONDITION_PREFIX, ConditionBundle
from engine.formats.evidence import Vocab
from engine.formats.io import read_json, read_model, write_json
from engine.formats.persona import Persona, merge_persona_layers, merged_persona
from engine.formats.run import VISIT_ID_SEPARATOR, LedgerRow, RunRecord, Weights
from engine.formats.scenario import Scenario
from engine.formats.venue import Venue
from engine.ledger import amount_problems, failed_row, no_candidate_row, visit_rows, write_ledger
from engine.llm import (
    DEFAULT_CALL_LIMIT,
    LlmError,
    LlmFatal,
    LlmReply,
    Provider,
    load_prompt,
    prompt_path,
    user_message,
)

# 실제로 돌아가는 엔진 코드가 있는 저장소. `--root` 로 다른 폴더의 자료를 돌려도 코드는 여기 것이다.
CODE_ROOT = Path(__file__).resolve().parents[1]

# 저장된 응답이 없는데 LLM 도 주지 않았을 때의 fail_reason.
NO_SAVED_ANSWER = "저장된 응답이 없다 (LLM 을 부르지 않고 돌렸다)"


class NotSupportedYet(ValueError):
    """아직 만들지 않은 것이 필요한 입력이다. 틀린 금액을 내지 않으려고 멈춘다."""


class CallLimitReached(Exception):
    """새로 부를 수 있는 횟수를 다 썼다. 실행을 멈춘다 (docs/PRD.md 7.3절)."""


# 호출이 연달아 이만큼 실패하면 실행을 멈춘다. 닿지 않는 주소나 멈춘 공급자를 상한까지 계속 부르지 않으려는 것이다.
MAX_FAILED_CALLS_IN_A_ROW = 3


@dataclass
class LlmSession:
    """실행 하나에서 LLM 을 부르는 데 쓰는 것. 새로 부른 수를 여기서 센다."""

    provider: Provider
    # 시스템 프롬프트: 프롬프트 파일의 글 그대로.
    system: str
    call_limit: int
    calls: int = 0
    # 답을 받지 못한 호출이 연달아 몇 번인가. 답을 받으면 0 으로 돌아간다.
    failed_in_a_row: int = 0

    def ask(self, request_text: str) -> LlmReply:
        """한 번 부른다. 실패한 호출도 부른 수에 센다 (상한은 비용을 막으려는 것이다).

        세는 것은 엔진이 공급자를 부른 수다. SDK 가 안에서 다시 보내 보는 요청은 세지 않는다.
        """
        if self.calls >= self.call_limit:
            raise CallLimitReached
        self.calls += 1
        return self.provider.complete(self.system, request_text)


@dataclass
class Inputs:
    """실행 하나가 읽는 것."""

    venues: dict[str, Venue]
    personas: dict[str, Persona]
    # 요청에 그대로 넣을 페르소나. 가상 예시는 공개 층 파일 그대로, 기본 데이터는 두 층을 합친 것이다.
    persona_json: dict[str, dict[str, Any]]
    conditions: ConditionBundle
    scenario: Scenario
    vocab: Vocab
    hashes: dict[str, str]


def runs_folder(root: Path, data_mode: str) -> Path:
    """실행 결과를 쓰는 곳. 가상 예시로 돌린 결과만 저장소에 둘 수 있다."""
    if data_mode == "sample":
        return root / "engine" / "samples" / "runs"
    if data_mode == "private":
        return root / "private" / "runs"
    raise ValueError(f"모르는 data_mode 다: {data_mode!r}")


def _hash_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def load_inputs(
    root: Path,
    data_mode: str,
    scenario_id: str = "baseline",
    venue_ids: list[str] | None = None,
    persona_ids: list[str] | None = None,
) -> Inputs:
    """입력 파일을 읽는다. `venue_ids`, `persona_ids` 를 주면 그것만 읽는다.

    가상 예시(`sample`)로 돌릴 때는 `private/` 를 읽지 않는다. 페르소나는 공개 층만 쓴다.
    """
    runs_folder(root, data_mode)  # data_mode 가 맞는지 먼저 본다

    venue_paths = sorted((root / "data" / "venues").glob("*.json"))
    if venue_ids is not None:
        venue_paths = [p for p in venue_paths if p.stem in venue_ids]
    persona_paths = sorted((root / "personas").glob("*.json"))
    if persona_ids is not None:
        persona_paths = [p for p in persona_paths if p.stem in persona_ids]
    for wanted, found, what in ((venue_ids, venue_paths, "업장"), (persona_ids, persona_paths, "페르소나")):
        missing = set(wanted or []) - {p.stem for p in found}
        if missing:
            raise FileNotFoundError(f"{what} 정의 파일이 없다: {sorted(missing)}")

    venues = {v.venue_id: v for v in (read_model(p, Venue) for p in venue_paths)}
    personas: dict[str, Persona] = {}
    persona_json: dict[str, dict[str, Any]] = {}
    hashed = list(persona_paths)
    for path in persona_paths:
        public = read_json(path)
        persona = read_model(path, Persona)
        layered = public
        if data_mode == "private":
            private_path = root / "private" / "personas" / path.name
            private = read_json(private_path) if private_path.is_file() else None
            if private is not None:
                hashed.append(private_path)
            persona = merged_persona(public, private)
            layered = merge_persona_layers(public, private)
        personas[persona.persona_id] = persona
        persona_json[persona.persona_id] = layered

    conditions_path = root / "engine" / "conditions.json"
    scenario_path = root / "scenarios" / f"{scenario_id}.json"
    vocab_path = root / "data" / "evidence" / "vocab.json"
    return Inputs(
        venues=venues,
        personas=personas,
        persona_json=persona_json,
        conditions=read_model(conditions_path, ConditionBundle),
        scenario=read_model(scenario_path, Scenario),
        vocab=read_model(vocab_path, Vocab),
        hashes={
            "venues": _hash_files(venue_paths),
            "personas": _hash_files(hashed),
            "conditions": _hash_files([conditions_path]),
            "scenario": _hash_files([scenario_path]),
            "vocab": _hash_files([vocab_path]),
        },
    )


def even_weights(personas: list[Persona], condition_ids: list[str]) -> Weights:
    """집계 파일 없이 쓰는 가중치: 고객군 배수는 1, 묶음의 비율은 조건마다 고르게 나눈다. 등급은 모두 설계 가정이다.

    집계 파일에서 계산한 값으로 바꾸는 것은 T11 이다. 그때까지 가상 매출의 크기에는 뜻이 없다.
    """
    planned = [c for c in condition_ids if not c.startswith(MANUAL_CONDITION_PREFIX)]
    groups = sorted({p.customer_group for p in personas})
    ratio = 1 / len(planned) if planned else 0.0
    return Weights.model_validate(
        {
            "group_multiplier": dict.fromkeys(groups, 1.0),
            "persona_weight": {p.persona_id: p.share_in_group.value for p in personas},
            "condition_ratio": {group: dict.fromkeys(planned, ratio) for group in groups},
            "grades": {
                "group_multiplier": "assumption",
                "persona_weight": "assumption",
                "condition_ratio": {group: dict.fromkeys(planned, "assumption") for group in groups},
            },
        }
    )


def represented(weights: Weights, persona: Persona, condition_id: str) -> float:
    """이 방문이 대표하는 크기 = 페르소나의 가중치 × 묶음의 비율. 화면에서 직접 넣은 조건에는 가중치가 없다."""
    if condition_id.startswith(MANUAL_CONDITION_PREFIX):
        return 0.0
    return weights.persona_weight[persona.persona_id] * weights.condition_ratio[persona.customer_group][condition_id]


@dataclass
class VisitResult:
    rows: list[LedgerRow]
    skipped: list[str]
    # 검사를 통과한 저장 응답의 파일. 실행 폴더의 llm/ 에 베껴 둔다.
    replayed: Path | None = None
    # 저장된 응답을 읽어 썼는가. 검사에서 어긋나 실패한 방문도 재생한 것으로 센다.
    used_saved: bool = False
    # 설정이 틀려 다시 불러도 같은 실패가 나는 오류였는가. 그러면 실행을 멈춘다.
    fatal: bool = False


def run_visit(
    *,
    run_id: str,
    inputs: Inputs,
    persona: Persona,
    condition: RunCondition,
    represented: float,
    prompt_version: str,
    book: AnswerBook,
    run_dir: Path | None = None,
    now: datetime | None = None,
    session: LlmSession | None = None,
) -> VisitResult:
    """방문 하나: 후보를 추리고, 답을 얻어 다시 검사하고, 원장의 줄로 바꾼다 (docs/PRD.md 7.1절).

    답은 저장된 응답에서 먼저 찾고, 없으면 `session` 으로 LLM 을 부른다. `session` 이 없으면 부르지 않는다.
    새로 받은 답과 어긋난 답을 저장하려면 `run_dir` 과 `now` 가 있어야 한다.
    호출 상한에 닿으면 `CallLimitReached` 가 난다.
    """
    base = {
        "run_id": run_id,
        "scenario_id": inputs.scenario.scenario_id,
        "visit_id": f"{persona.persona_id}{VISIT_ID_SEPARATOR}{condition.condition_id}",
        "persona_id": persona.persona_id,
        "customer_group": persona.customer_group,
        "condition_id": condition.condition_id,
        "represented": represented,
    }
    request, skipped = build_request(
        prompt_version=prompt_version,
        scenario_id=inputs.scenario.scenario_id,
        persona=inputs.persona_json[persona.persona_id],
        condition=condition,
        venues=list(inputs.venues.values()),
        vocab=inputs.vocab,
    )
    if request is None:
        return VisitResult([no_candidate_row(base)], skipped)

    def rejected(llm_call: str, raw_text: str, problems: list[str], tokens_in: int, tokens_out: int) -> LedgerRow:
        """어긋난 응답은 재생할 llm/ 이 아니라 llm_rejected/ 에 남기고, 그 방문을 실패로 적는다 (docs/FORMATS.md 10.3절)."""
        if run_dir is not None and now is not None:
            save_rejected(
                run_dir / "llm_rejected", book.provider, book.model, request, now, llm_call, raw_text, problems, tokens_in, tokens_out
            )
        return failed_row(base, "; ".join(problems), llm_call, request_hash)

    request_hash, path, saved, unreadable = book.find(request)
    if path is not None:
        if saved is None:
            return VisitResult([failed_row(base, unreadable, "replay", request_hash)], skipped, used_saved=True)
        # 저장된 응답도 다시 검사한다. 하나라도 어긋나면 그 방문은 실패다 (docs/FORMATS.md 9절).
        problems = problems_in_response(request, saved.response) or amount_problems(request, saved.response, inputs.venues)
        if problems:
            usage = saved.usage
            row = rejected("replay", saved.raw_text, problems, usage.input_tokens, usage.output_tokens)
            return VisitResult([row], skipped, used_saved=True)
        rows = visit_rows(base, request, saved.response, inputs.venues, "replay", request_hash)
        return VisitResult(rows, skipped, replayed=path, used_saved=True)

    if session is None:
        return VisitResult([failed_row(base, NO_SAVED_ANSWER)], skipped)
    if run_dir is None or now is None:
        raise ValueError("LLM 을 부르려면 답을 저장할 run_dir 과 now 가 있어야 한다")
    try:
        reply = session.ask(user_message(request))
    except LlmFatal as exc:
        return VisitResult([failed_row(base, str(exc), "new", request_hash)], skipped, fatal=True)
    except LlmError as exc:
        # 한 번의 실패는 그 방문만 실패로 남긴다. 연달아 실패하면 주소가 틀렸거나 공급자가 멈춘 것이라 실행을 멈춘다.
        session.failed_in_a_row += 1
        stop = session.failed_in_a_row >= MAX_FAILED_CALLS_IN_A_ROW
        reason = f"{exc} (호출이 연달아 {MAX_FAILED_CALLS_IN_A_ROW}번 실패해 멈춘다)" if stop else str(exc)
        return VisitResult([failed_row(base, reason, "new", request_hash)], skipped, fatal=stop)
    session.failed_in_a_row = 0
    response, problems = read_reply(reply.text)
    if response is not None:
        problems = problems_in_response(request, response) or amount_problems(request, response, inputs.venues)
    if response is None or problems:
        return VisitResult([rejected("new", reply.text, problems, reply.input_tokens, reply.output_tokens)], skipped)
    # 검사를 통과한 답만 llm/ 에 저장한다. 받자마자 저장해, 실행이 도중에 멈춰도 받은 답은 남는다.
    save_response(
        run_dir / "llm", book.provider, book.model, request, response, now, reply.text, reply.input_tokens, reply.output_tokens
    )
    return VisitResult(visit_rows(base, request, response, inputs.venues, "new", request_hash), skipped)


def _git(root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return done.stdout.strip()


def _engine_commit(root: Path) -> str:
    """엔진 코드의 커밋. 엔진 코드에 커밋하지 않은 변경이 있으면 `+dirty` 를 붙인다 (그 커밋의 코드로 돌린 것이 아니다).

    `root` 는 엔진 코드가 있는 저장소다. 실행기는 자료의 폴더가 아니라 돌아가는 코드의 자리(`CODE_ROOT`)를 준다.

    `engine/` 아래에서도 코드가 아닌 것은 보지 않는다: 가상 예시의 실행 결과(`engine/samples/`)와 방문 조건 묶음
    (`engine/conditions.json`. 입력이라 `inputs` 의 해시에 따로 남는다).
    """
    commit = _git(root, "rev-parse", "--short", "HEAD")
    if not commit:
        return "unknown"
    code = ("engine", ":(exclude)engine/samples", ":(exclude)engine/conditions.json")
    return commit + ("+dirty" if _git(root, "status", "--porcelain", "--", *code) else "")


def run(
    root: Path,
    *,
    data_mode: str,
    now: datetime,
    provider: str,
    model: str,
    prompt_version: str,
    answers: list[Path],
    scenario_id: str = "baseline",
    venue_ids: list[str] | None = None,
    persona_ids: list[str] | None = None,
    condition_ids: list[str] | None = None,
    weights: Weights | None = None,
    engine_commit: str | None = None,
    llm: Provider | None = None,
    call_limit: int | None = None,
) -> Path:
    """상황 하나를 돌려 실행 폴더(`run.json`, `ledger.csv`, `llm/`, `llm_rejected/`)를 쓰고 그 경로를 돌려준다.

    - `answers`: 저장된 응답을 찾을 폴더들 (정해 둔 답이나 앞선 실행의 `llm/`).
    - `now`: 실행 시각. 시간대가 있어야 한다. `run_id` 와 `created_at`, 저장하는 응답의 `created_at` 이 여기서 나온다.
    - `weights` 를 주지 않으면 `even_weights` 를 쓴다.
    - `llm`: 저장된 응답이 없는 방문에서 부를 공급자. 주지 않으면 부르지 않고 그 방문을 실패로 남긴다 (재생만).
      `provider` 와 `model` 은 `llm` 이 실제로 부르는 곳과 같아야 한다 (요청의 해시와 실행 기록에 들어간다).
    - `call_limit`: 이 실행에서 새로 부를 수 있는 횟수. 주지 않으면 `DEFAULT_CALL_LIMIT` 이다.
      닿으면 거기서 멈추고 `status` 가 `stopped_by_limit` 이 된다.
      설정이 틀려 부를 수 없거나(키, 모델 이름, 요청을 받지 않음) 호출이 연달아 실패하면 그 방문을 실패로 남기고 멈추며
      `status` 가 `failed` 다. 멈춘 실행의 원장에는 멈추기 전까지 돌린 방문만 있다.
    - 예상하지 못한 오류로 끊겨도 그때까지의 실행 기록과 원장은 쓴다 (`status` 는 `failed`). 오류는 그대로 올라간다.
    """
    if now.tzinfo is None:
        raise ValueError("now 에는 시간대가 있어야 한다 (예: +09:00)")
    private_root = (root / "private").resolve()
    if data_mode == "sample" and any(folder.resolve().is_relative_to(private_root) for folder in answers):
        raise ValueError("가상 예시로 돌릴 때는 private/ 아래의 저장된 응답을 쓰지 않는다")
    inputs = load_inputs(root, data_mode, scenario_id, venue_ids, persona_ids)
    if inputs.scenario.changes:
        raise NotSupportedYet(f"상황 '{scenario_id}' 에 바꾸는 것이 있다. 상황 적용은 아직 넣지 않았다 (T10)")
    promoted = sorted(v.venue_id for v in inputs.venues.values() if v.promotions)
    if promoted:
        raise NotSupportedYet(f"프로모션이 있는 업장이 있다: {promoted}. 프로모션 규칙은 아직 넣지 않았다 (T10)")
    if not inputs.personas:
        raise ValueError("돌릴 페르소나가 없다")

    if condition_ids is None:
        condition_ids = [c.condition_id for c in inputs.conditions.conditions]
    conditions = [inputs.conditions.condition(condition_id) for condition_id in condition_ids]
    if None in conditions:
        raise ValueError(f"방문 조건 묶음에 없는 조건이 있다: {condition_ids}")
    personas = list(inputs.personas.values())
    weights = weights or even_weights(personas, condition_ids)

    run_id = f"{now:%Y%m%d-%H%M%S}-{scenario_id}"
    run_dir = runs_folder(root, data_mode) / run_id
    if run_dir.exists():
        raise FileExistsError(f"실행 폴더가 이미 있다: {run_dir}")
    book = AnswerBook(answers, provider, model)
    session = None
    if llm is not None:
        # 프롬프트는 부를 때만 읽는다. 읽은 것만 입력의 해시에 적는다.
        limit = DEFAULT_CALL_LIMIT if call_limit is None else call_limit
        session = LlmSession(llm, load_prompt(root, prompt_version), limit)
        inputs.hashes["prompt"] = _hash_files([prompt_path(root, prompt_version)])

    rows: list[LedgerRow] = []
    skipped: set[str] = set()
    replayed: dict[str, Path] = {}
    visits = failed = calls_replayed = 0
    status = "ok"
    finished = False
    try:
        for persona, condition in ((p, c) for p in personas for c in conditions):
            try:
                result = run_visit(
                    run_id=run_id,
                    inputs=inputs,
                    persona=persona,
                    condition=run_condition(condition, persona),
                    represented=represented(weights, persona, condition.condition_id),
                    prompt_version=prompt_version,
                    book=book,
                    run_dir=run_dir,
                    now=now,
                    session=session,
                )
            except CallLimitReached:
                status = "stopped_by_limit"
                break
            visits += 1
            rows.extend(result.rows)
            skipped.update(result.skipped)
            failed += any(row.status == "failed" for row in result.rows)
            calls_replayed += result.used_saved
            if result.replayed is not None:
                replayed[result.replayed.name] = result.replayed
            if result.fatal:
                status = "failed"
                break
        finished = True
    finally:
        # 예상하지 못한 오류로 끊겨도 실행 기록과 그때까지의 원장을 쓴다. 받은 답(llm/)만 있고 실행 기록이 없는
        # 폴더가 남으면 형식 검사가 막고, 가상 예시로 돌린 것이면 그 폴더가 저장소 안이다.
        if not finished:
            status = "failed"
        _write_run(
            run_dir,
            rows,
            replayed,
            {
                "format_version": 1,
                "run_id": run_id,
                "created_at": now,
                "engine_commit": engine_commit or _engine_commit(CODE_ROOT),
                "data_mode": data_mode,
                "scenario_id": scenario_id,
                "persona_ids": [p.persona_id for p in personas],
                "condition_ids": condition_ids,
                "llm": {
                    "provider": provider,
                    "model": model,
                    "prompt_version": prompt_version,
                    "calls_new": session.calls if session else 0,
                    "calls_replayed": calls_replayed,
                    "call_limit": session.call_limit if session else 0,
                    "stopped_by_limit": status == "stopped_by_limit",
                },
                # 기본 데이터에서 나온 값을 요청에 붙이는 것은 T11 이다. 지금은 어느 쪽으로 돌려도 보내지 않는다.
                "base_profile_mode": "none",
                "inputs": inputs.hashes,
                "weights": weights,
                "skipped_products": sorted(skipped),
                "weights_from": None,
                "counts": {"visits": visits, "failed": failed},
                "status": status,
            },
        )
    return run_dir


def _write_run(run_dir: Path, rows: list[LedgerRow], replayed: dict[str, Path], record_data: dict[str, Any]) -> None:
    """실행 폴더에 실행 기록과 원장을 쓰고, 재생한 응답을 llm/ 에 베껴 둔다."""
    record = RunRecord.model_validate(record_data)
    write_json(run_dir / "run.json", record.model_dump(mode="json", by_alias=True))
    write_ledger(run_dir / "ledger.csv", rows)
    (run_dir / "llm").mkdir(exist_ok=True)
    for name, path in replayed.items():
        shutil.copyfile(path, run_dir / "llm" / name)
