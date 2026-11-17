"""실행기: 상황 하나에서 페르소나마다, 방문 조건마다 한 번씩 돌려 실행 결과를 쓴다 (docs/FORMATS.md 10절).

방문마다 저장된 응답을 먼저 찾는다. 있으면 재생하고, 없으면 LLM 을 불러 답을 받아 검사한 뒤 저장한다.
LLM 을 주지 않고 돌리면(재생만) 저장된 응답이 없는 방문은 실패로 남는다.
기준이 아닌 상황은 업장 정의의 사본에 상황을 적용해 돌리고, 페르소나·방문 조건·가중치는 기준 실행의 것을 그대로 쓴다.
기준 상황의 가중치는 집계 파일에서 낸다: 묶음의 비율은 돌리기 전에, 고객군 배수는 방문을 다 돈 뒤 원장으로 맞춘다 (`engine.weights`).
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
from engine.formats.choice import ChoiceRequest, RunCondition, problems_in_response
from engine.formats.conditions import MANUAL_CONDITION_PREFIX, ConditionBundle
from engine.formats.evidence import Vocab
from engine.formats.io import read_json, read_model, write_json
from engine.formats.money import round_half_up, weighted_amount
from engine.formats.persona import Persona, merge_persona_layers, merged_persona
from engine.formats.run import RUN_ID_RE, VISIT_ID_SEPARATOR, LedgerRow, RunRecord, Weights
from engine.formats.scenario import BASELINE_ID, Scenario
from engine.formats.summary import SummaryRow
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
    response_schema,
    user_message,
)
from engine.scenarios import apply_scenario
from engine.weights import (
    base_profiles,
    condition_ratios,
    empty_profile,
    fill_prices,
    fit_weights,
    group_revenue,
    read_summary,
    summary_path,
)

# 실제로 돌아가는 엔진 코드가 있는 저장소. `--root` 로 다른 폴더의 자료를 돌려도 코드는 여기 것이다.
CODE_ROOT = Path(__file__).resolve().parents[1]

# 저장된 응답이 없는데 LLM 도 주지 않았을 때의 fail_reason.
NO_SAVED_ANSWER = "저장된 응답이 없다 (LLM 을 부르지 않고 돌렸다)"


class CallLimitReached(Exception):
    """새로 부를 수 있는 횟수를 다 썼다. 실행을 멈춘다 (docs/PRD.md 7.3절)."""


# 호출이 연달아 이만큼 실패하면 실행을 멈춘다. 닿지 않는 주소나 멈춘 공급자를 상한까지 계속 부르지 않으려는 것이다.
MAX_FAILED_CALLS_IN_A_ROW = 3

# `latest_baseline_run` 에 달을 가리지 않고 찾으라고 줄 때의 값. None 은 "일 년 전체로 돌린 실행"이라 따로 둔다.
ANY_MONTH = "any"


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

    def ask(self, request: ChoiceRequest) -> LlmReply:
        """한 번 부른다. 실패한 호출도 부른 수에 센다 (상한은 비용을 막으려는 것이다).

        세는 것은 엔진이 공급자를 부른 수다. SDK 가 안에서 다시 보내 보는 요청은 세지 않는다.
        답의 모양은 이 요청에서 고를 수 있는 값으로 묶어 보낸다 (`engine.llm.response_schema`).
        """
        if self.calls >= self.call_limit:
            raise CallLimitReached
        self.calls += 1
        return self.provider.complete(self.system, user_message(request), response_schema(request))


@dataclass
class Inputs:
    """실행 하나가 읽는 것."""

    # 상황을 적용하고 가격이 빈 상품을 집계 파일로 채운 업장 정의다. 파일에 적힌 그대로가 아니다.
    venues: dict[str, Venue]
    personas: dict[str, Persona]
    # 요청에 그대로 넣을 페르소나. 가상 예시는 공개 층 파일 그대로, 기본 데이터는 두 층을 합친 것이다.
    # 기본 데이터의 요약을 보내기로 했으면(base_profile_mode) 그 요약이 `base_profile` 로 붙어 있다.
    persona_json: dict[str, dict[str, Any]]
    conditions: ConditionBundle
    scenario: Scenario
    vocab: Vocab
    # 기본 데이터 집계 파일의 줄 (가상 예시로 돌릴 때는 가상 예시 값).
    summary: list[SummaryRow]
    # 가격이 비어 있어 집계 파일로 단가를 채운 상품 (`<venue_id>:<product_id>`).
    filled: list[str]
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


def default_base_profile_mode(data_mode: str) -> str:
    """기본 데이터로 돌릴 때는 범주로 바꿔 보내고(11-13 결정), 가상 예시로 돌릴 때는 보내지 않는다 (docs/FORMATS.md 10.1절)."""
    return "bucketed" if data_mode == "private" else "none"


def load_inputs(
    root: Path,
    data_mode: str,
    scenario_id: str = "baseline",
    venue_ids: list[str] | None = None,
    persona_ids: list[str] | None = None,
    base_profile_mode: str | None = None,
) -> Inputs:
    """입력 파일을 읽는다. `venue_ids`, `persona_ids` 를 주면 그것만 읽는다.

    가상 예시(`sample`)로 돌릴 때는 `private/` 를 읽지 않는다. 페르소나는 공개 층만 쓰고, 집계 파일은 가상 예시 값을 쓴다.
    돌려주는 업장 정의는 상황의 `changes` 를 적용한 뒤 가격이 빈 상품을 집계 파일로 채운 사본이다.
    업장 정의 파일은 바뀌지 않는다 (docs/FORMATS.md 3절·7절). 상황을 먼저 적용하므로 `change_price_pct` 는 채운 단가를 바꾸지 않는다.
    `venue_ids` 로 업장을 골랐으면 상황이 바꾸는 업장도 그 안에 있어야 한다.
    `base_profile_mode` 가 `bucketed` 나 `raw` 면 페르소나마다 그 고객군의 기본 데이터 요약을 `base_profile` 로 붙인다 (기본 데이터로 돌릴 때만).
    주지 않으면 실행과 같은 기본값이다 (`default_base_profile_mode`). 그래야 다른 영역이 이 함수로 만든 요청이 실행의 요청과 같다.
    """
    runs_folder(root, data_mode)  # data_mode 가 맞는지 먼저 본다
    if base_profile_mode is None:
        base_profile_mode = default_base_profile_mode(data_mode)
    if base_profile_mode not in ("none", "bucketed", "raw"):
        raise ValueError(f"모르는 base_profile_mode 다: {base_profile_mode!r}")
    if data_mode == "sample" and base_profile_mode != "none":
        raise ValueError("가상 예시로 돌릴 때는 기본 데이터의 요약을 보내지 않는다 (base_profile_mode 는 none)")

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
    summary_file = summary_path(root, data_mode)
    scenario = read_model(scenario_path, Scenario)
    summary = read_summary(summary_file)
    if base_profile_mode != "none":
        profiles = base_profiles(summary, base_profile_mode)
        for persona_id, layered in persona_json.items():
            layered["base_profile"] = profiles.get(personas[persona_id].customer_group, empty_profile())
    filled_venues, filled = fill_prices(apply_scenario(venues, scenario), summary, data_mode)
    return Inputs(
        venues=filled_venues,
        personas=personas,
        persona_json=persona_json,
        conditions=read_model(conditions_path, ConditionBundle),
        scenario=scenario,
        vocab=read_model(vocab_path, Vocab),
        summary=summary,
        filled=filled,
        hashes={
            "venues": _hash_files(venue_paths),
            "personas": _hash_files(hashed),
            "conditions": _hash_files([conditions_path]),
            "scenario": _hash_files([scenario_path]),
            "vocab": _hash_files([vocab_path]),
            "summary": _hash_files([summary_file]),
        },
    )


def latest_baseline_run(root: Path, data_mode: str, month: int | None | str = ANY_MONTH) -> str | None:
    """끝까지 돈 기준 실행 가운데 가장 새것의 `run_id`. 없으면 None. 같은 `data_mode` 의 실행만 본다.

    `month` 를 주면 실행의 달이 그것과 같은 기준 실행만 본다: 1 ~ 12 는 그 달로 돌린 실행, None 은 일 년 전체로 돌린 실행.
    주지 않으면(`ANY_MONTH`) 달을 가리지 않는다.
    실패한 방문이 있는 실행도 고른다. 그 실행으로 상황을 돌리면 `baseline_record` 가 막는다 (docs/FORMATS.md 10.1절).
    화면에서 쓸 기준 실행을 미리 보여 줄 때는 `counts.failed` 도 함께 본다.
    """
    folder = runs_folder(root, data_mode)
    for run_dir in sorted(folder.glob(f"*-{BASELINE_ID}"), reverse=True):
        try:
            record = read_model(run_dir / "run.json", RunRecord)
        except (OSError, ValueError):
            continue
        if record.scenario_id == BASELINE_ID and record.status == "ok" and month in (ANY_MONTH, record.month):
            return record.run_id
    return None


def month_label(month: int | None) -> str:
    """실행의 달을 사람이 읽는 글로 (실행 기록의 `month`)."""
    return "일 년 전체" if month is None else f"{month}월"


def baseline_record(root: Path, data_mode: str, run_id: str | None) -> RunRecord:
    """기준이 아닌 상황이 페르소나, 방문 조건, 가중치를 가져올 기준 실행의 실행 기록 (docs/PRD.md 7.2절)."""
    if run_id is None:
        raise ValueError("기준이 아닌 상황은 기준 실행의 가중치로 돌린다. 기준 상황을 먼저 끝까지 돌린다")
    if not RUN_ID_RE.match(run_id):
        raise ValueError(f"기준 실행의 run_id 가 아니다: {run_id!r}")
    path = runs_folder(root, data_mode) / run_id / "run.json"
    if not path.is_file():
        raise FileNotFoundError(f"기준 실행의 실행 기록이 없다: {path}")
    record = read_model(path, RunRecord)
    if record.scenario_id != BASELINE_ID:
        raise ValueError(f"실행 '{run_id}' 는 기준 상황의 실행이 아니다")
    if record.status != "ok":
        raise ValueError(f"기준 실행 '{run_id}' 는 끝까지 돌지 않았다 (status 가 {record.status}). 기준 상황을 다시 돌린다")
    if record.counts.failed:
        # 실패한 방문은 기준에서 금액이 0 인 줄이다. 상황에서 그 방문이 성공하면 차이에 상황의 변경이 아닌 것이 섞인다 (11-16 회의).
        raise ValueError(
            f"기준 실행 '{run_id}' 에 실패한 방문이 {record.counts.failed}건 있어 상황을 돌리지 않는다. "
            "실패한 방문에서는 기준과 상황을 견줄 수 없다. 이유는 그 실행의 원장(ledger.csv)의 fail_reason 에 있다. "
            "llm_call 이 new 이거나 비어 있는 실패는 기준 상황을 --replay-only 없이 다시 돌리면 그 방문만 LLM 을 새로 부른다. "
            "llm_call 이 replay 인 실패는 저장된 응답이 다시 재생돼 그대로 남으니 fail_reason 의 원인을 먼저 고친다"
        )
    return record


def _same_as_baseline(what: str, given: list[str] | None, base: list[str]) -> list[str]:
    """기준이 아닌 상황은 기준 실행과 같은 것을 돌린다. 따로 준 목록이 다르면 멈춘다."""
    if given is not None and set(given) != set(base):
        raise ValueError(f"기준 실행과 {what}의 목록이 다르다. 상황별 비교는 기준 실행과 같은 것으로 한다: {sorted(base)}")
    return list(base)


def _changed_since_baseline(base: RunRecord, hashes: dict[str, str], provider: str, model: str, prompt_version: str) -> list[str]:
    """기준 실행 뒤에 달라진 것. 하나라도 있으면 상황 사이의 차이에 상황의 변경이 아닌 것이 섞인다."""
    # 집계 파일이 바뀌면 채운 단가와 기본 데이터의 요약이 달라진다. 그래서 집계 파일도 견준다.
    keys = ("venues", "personas", "conditions", "vocab", "summary")
    changed = [key for key in keys if base.inputs.get(key) != hashes[key]]
    # 프롬프트의 글은 LLM 을 부를 수 있게 돌린 실행에만 해시가 남는다. 둘 다 있을 때만 견준다.
    if "prompt" in base.inputs and "prompt" in hashes and base.inputs["prompt"] != hashes["prompt"]:
        changed.append("prompt")
    for key, now in (("provider", provider), ("model", model), ("prompt_version", prompt_version)):
        if getattr(base.llm, key) != now:
            changed.append(f"llm.{key}")
    return changed


def represented(weights: Weights, persona: Persona, condition_id: str) -> float:
    """이 방문이 대표하는 크기 = 페르소나의 가중치 × 묶음의 비율. 화면에서 직접 넣은 조건에는 가중치가 없다."""
    if condition_id.startswith(MANUAL_CONDITION_PREFIX):
        return 0.0
    return weights.persona_weight[persona.persona_id] * weights.condition_ratio[persona.customer_group][condition_id]


def reweigh(rows: list[LedgerRow], weights: Weights, personas: dict[str, Persona]) -> list[LedgerRow]:
    """원장의 줄에 가중치를 다시 적는다: `represented` 와 `weighted_revenue`.

    기준 상황은 고객군 배수를 방문을 다 돈 뒤에 원장으로 맞추므로, 방문을 돌 때는 대표하는 크기를 0 으로 적어 두고 여기서 채운다.
    """
    out = []
    for row in rows:
        size = represented(weights, personas[row.persona_id], row.condition_id)
        weighted = round_half_up(weighted_amount(row.revenue_net, size, row.counted_share))
        out.append(LedgerRow.model_validate({**row.model_dump(), "represented": size, "weighted_revenue": weighted}))
    return out


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
        reply = session.ask(request)
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
    weights_from: str | None = None,
    engine_commit: str | None = None,
    llm: Provider | None = None,
    call_limit: int | None = None,
    base_profile_mode: str | None = None,
    month: int | None = None,
) -> Path:
    """상황 하나를 돌려 실행 폴더(`run.json`, `ledger.csv`, `llm/`, `llm_rejected/`)를 쓰고 그 경로를 돌려준다.

    - `answers`: 저장된 응답을 찾을 폴더들 (정해 둔 답이나 앞선 실행의 `llm/`).
    - `now`: 실행 시각. 시간대가 있어야 한다. `run_id` 와 `created_at`, 저장하는 응답의 `created_at` 이 여기서 나온다.
    - 기준 상황의 가중치는 집계 파일에서 낸다 (`engine.weights`, docs/FORMATS.md 10.1절의 "가중치를 내는 법").
      `weights` 를 주면 그 값을 그대로 쓴다 (테스트에서 쓴다). 기준 상황에만 줄 수 있다.
    - `weights_from`: 기준이 아닌 상황을 돌릴 때 꼭 준다. 끝까지 돈 기준 실행의 `run_id` 다 (`latest_baseline_run`).
      그 실행에 실패한 방문이 있으면 실행 폴더를 만들기 전에 `ValueError` 로 멈춘다. 화면은 그 글을 그대로 보여 준다.
      페르소나, 방문 조건, 가중치, `base_profile_mode` 를 그 실행에서 가져온다. `persona_ids`, `condition_ids` 를 따로 주면 그 실행과 같아야 한다.
      그 실행 뒤에 입력(업장 정의, 페르소나, 조건 묶음, 값 목록, 집계 파일, 프롬프트)이나 공급자·모델이 달라졌으면 돌리지 않는다.
      상황 사이의 차이에 상황의 변경만 남게 하려는 것이다 (docs/PRD.md 7.2절).
    - `base_profile_mode`: 기본 데이터의 요약을 LLM 에 어떻게 보낼지. 주지 않으면 기본 데이터로 돌릴 때 `bucketed`, 가상 예시로 돌릴 때 `none` 이다.
    - `month`: 실행의 달 (1 ~ 12). 주면 묶음의 조건을 모두 그 달의 방문으로 돌린다: 그 달에 팔지 않는 업장과 상품은 후보에서 빠지고,
      요청의 `condition.month` 에 그 달이 실린다. 주지 않으면 일 년 전체로 본다. 가중치는 달을 줘도 집계 파일의 일 년 합계에 맞춘다:
      고객군 배수를 이 실행의 원장으로 맞추므로 고객군의 가상 매출 합은 달과 상관없이 같다 (docs/FORMATS.md 10.1절의 "실행의 달").
      기준이 아닌 상황은 기준 실행의 달을 따른다. 다른 달을 따로 주면 돌리지 않는다.
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
    # bool 은 int 라서 True 가 1월로 읽히지 않게 따로 막는다.
    if month is not None and (isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12):
        raise ValueError(f"month 는 1 ~ 12 의 정수다: {month!r}")
    base: RunRecord | None = None
    if scenario_id == BASELINE_ID:
        if weights_from is not None:
            raise ValueError("기준 상황은 가중치를 스스로 정한다. weights_from 을 주지 않는다")
    else:
        if weights is not None:
            raise ValueError("기준이 아닌 상황의 가중치는 기준 실행에서 가져온다. weights 를 따로 주지 않는다")
        base = baseline_record(root, data_mode, weights_from)
        persona_ids = _same_as_baseline("페르소나", persona_ids, base.persona_ids)
        condition_ids = _same_as_baseline("방문 조건", condition_ids, base.condition_ids)
        weights = base.weights
        # 요약을 보내는 방식이 다르면 요청이 달라져, 상황의 변경이 아닌 것이 차이에 섞인다.
        if base_profile_mode is not None and base_profile_mode != base.base_profile_mode:
            raise ValueError(
                f"기준 실행의 base_profile_mode 는 {base.base_profile_mode} 다. 상황은 기준 실행과 같은 방식으로 돌린다"
            )
        base_profile_mode = base.base_profile_mode
        # 달이 다르면 후보와 요청이 달라져, 상황의 변경이 아닌 것이 차이에 섞인다.
        if month is not None and month != base.month:
            raise ValueError(
                f"기준 실행 '{base.run_id}' 의 달({month_label(base.month)})과 다른 달({month_label(month)})을 주었다. "
                "상황은 기준 실행과 같은 달로 돌린다. 다른 달로 보려면 기준 상황을 그 달로 먼저 돌린다"
            )
        month = base.month
    if base_profile_mode is None:
        base_profile_mode = default_base_profile_mode(data_mode)
    inputs = load_inputs(root, data_mode, scenario_id, venue_ids, persona_ids, base_profile_mode)
    if not inputs.personas:
        raise ValueError("돌릴 페르소나가 없다")

    if condition_ids is None:
        condition_ids = [c.condition_id for c in inputs.conditions.conditions]
    if len(set(condition_ids)) != len(condition_ids):
        raise ValueError(f"같은 방문 조건을 두 번 적었다: {condition_ids}")
    conditions = [inputs.conditions.condition(condition_id) for condition_id in condition_ids]
    if None in conditions:
        raise ValueError(f"방문 조건 묶음에 없는 조건이 있다: {condition_ids}")
    personas = list(inputs.personas.values())

    # 기준 상황은 가중치를 집계 파일에서 낸다. 묶음의 비율은 지금 내고, 고객군 배수는 방문을 다 돈 뒤에 원장으로 맞춘다.
    fitting = weights is None
    if fitting:
        revenue = group_revenue(inputs.summary, conditions, inputs.conditions.assumed_splits, inputs.venues)
        groups = sorted({p.customer_group for p in personas})
        ratios, ratio_grades = condition_ratios(revenue, groups, condition_ids, data_mode)

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
    if base is not None:
        changed = _changed_since_baseline(base, inputs.hashes, provider, model, prompt_version)
        if changed:
            raise ValueError(
                f"기준 실행 '{base.run_id}' 과 달라진 것이 있다: {', '.join(changed)}. "
                "기준 상황을 다시 돌린 뒤에 이 상황을 돌린다 (상황 사이의 차이에 상황의 변경만 남아야 한다)"
            )

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
                    condition=run_condition(condition, persona, month),
                    # 가중치를 맞추는 중이면 0 으로 적어 두고, 다 돈 뒤에 reweigh 로 채운다.
                    represented=0.0 if weights is None else represented(weights, persona, condition.condition_id),
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
        if fitting:
            weights = fit_weights(personas, ratios, ratio_grades, revenue, rows, data_mode)
            rows = reweigh(rows, weights, inputs.personas)
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
                "month": month,
                "llm": {
                    "provider": provider,
                    "model": model,
                    "prompt_version": prompt_version,
                    "calls_new": session.calls if session else 0,
                    "calls_replayed": calls_replayed,
                    "call_limit": session.call_limit if session else 0,
                    "stopped_by_limit": status == "stopped_by_limit",
                },
                "base_profile_mode": base_profile_mode,
                "inputs": inputs.hashes,
                "weights": weights,
                "filled_products": inputs.filled,
                "skipped_products": sorted(skipped),
                "weights_from": base.run_id if base else None,
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
