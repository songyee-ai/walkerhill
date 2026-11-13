"""실행기: 상황 하나에서 페르소나마다, 방문 조건마다 한 번씩 돌려 실행 결과를 쓴다 (docs/FORMATS.md 10절).

지금은 LLM 을 부르지 않는다. 저장된 응답(정해 둔 답)이 있으면 재생하고, 없으면 그 방문을 실패로 남긴다.
LLM 연결은 T05, 상황 적용과 프로모션은 T10, 집계 파일로 가중치를 내는 것은 T11 에서 더한다.
"""

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from engine.answers import AnswerBook
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

# 저장된 응답이 없을 때의 fail_reason. LLM 을 부르는 것은 T05 에서 넣는다.
NO_SAVED_ANSWER = "저장된 응답이 없다 (LLM 을 부르지 않고 돌렸다)"


class NotSupportedYet(ValueError):
    """아직 만들지 않은 것이 필요한 입력이다. 틀린 금액을 내지 않으려고 멈춘다."""


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


def run_visit(
    *,
    run_id: str,
    inputs: Inputs,
    persona: Persona,
    condition: RunCondition,
    represented: float,
    prompt_version: str,
    book: AnswerBook,
) -> VisitResult:
    """방문 하나: 후보를 추리고, 저장된 응답을 찾아 다시 검사하고, 원장의 줄로 바꾼다 (docs/PRD.md 7.1절)."""
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

    request_hash, path, saved, unreadable = book.find(request)
    if path is None:
        return VisitResult([failed_row(base, NO_SAVED_ANSWER)], skipped)
    if saved is None:
        return VisitResult([failed_row(base, unreadable, "replay", request_hash)], skipped, used_saved=True)
    # 저장된 응답도 다시 검사한다. 하나라도 어긋나면 그 방문은 실패다 (docs/FORMATS.md 9절).
    problems = problems_in_response(request, saved.response) or amount_problems(request, saved.response, inputs.venues)
    if problems:
        # 어긋난 응답은 실행 폴더에 베껴 두지 않는다 (형식 검사가 저장된 응답의 어긋남을 오류로 본다).
        # 어긋난 응답을 어디에 어떻게 남길지는 LLM 을 부르는 T05 에서 정한다.
        return VisitResult([failed_row(base, "; ".join(problems), "replay", request_hash)], skipped, used_saved=True)
    rows = visit_rows(base, request, saved.response, inputs.venues, "replay", request_hash)
    return VisitResult(rows, skipped, replayed=path, used_saved=True)


def _git(root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return done.stdout.strip()


def _engine_commit(root: Path) -> str:
    """엔진 코드의 커밋. 엔진 코드에 커밋하지 않은 변경이 있으면 `+dirty` 를 붙인다 (그 커밋의 코드로 돌린 것이 아니다).

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
) -> Path:
    """상황 하나를 돌려 실행 폴더(`run.json`, `ledger.csv`, `llm/`)를 쓰고 그 경로를 돌려준다.

    - `answers`: 저장된 응답을 찾을 폴더들 (정해 둔 답이나 앞선 실행의 `llm/`).
    - `now`: 실행 시각. 시간대가 있어야 한다. `run_id` 와 `created_at` 이 여기서 나온다.
    - `weights` 를 주지 않으면 `even_weights` 를 쓴다.
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

    rows: list[LedgerRow] = []
    skipped: set[str] = set()
    replayed: dict[str, Path] = {}
    failed = calls_replayed = 0
    for persona in personas:
        for condition in conditions:
            result = run_visit(
                run_id=run_id,
                inputs=inputs,
                persona=persona,
                condition=run_condition(condition, persona),
                represented=represented(weights, persona, condition.condition_id),
                prompt_version=prompt_version,
                book=book,
            )
            rows.extend(result.rows)
            skipped.update(result.skipped)
            failed += any(row.status == "failed" for row in result.rows)
            calls_replayed += result.used_saved
            if result.replayed is not None:
                replayed[result.replayed.name] = result.replayed

    record = RunRecord.model_validate(
        {
            "format_version": 1,
            "run_id": run_id,
            "created_at": now,
            "engine_commit": engine_commit or _engine_commit(root),
            "data_mode": data_mode,
            "scenario_id": scenario_id,
            "persona_ids": [p.persona_id for p in personas],
            "condition_ids": condition_ids,
            "llm": {
                "provider": provider,
                "model": model,
                "prompt_version": prompt_version,
                "calls_new": 0,
                "calls_replayed": calls_replayed,
                "call_limit": 0,
                "stopped_by_limit": False,
            },
            # 기본 데이터에서 나온 값을 요청에 붙이는 것은 T11 이다. 지금은 어느 쪽으로 돌려도 보내지 않는다.
            "base_profile_mode": "none",
            "inputs": inputs.hashes,
            "weights": weights,
            "skipped_products": sorted(skipped),
            "weights_from": None,
            "counts": {"visits": len(personas) * len(conditions), "failed": failed},
            "status": "ok",
        }
    )
    write_json(run_dir / "run.json", record.model_dump(mode="json", by_alias=True))
    write_ledger(run_dir / "ledger.csv", rows)
    (run_dir / "llm").mkdir(exist_ok=True)
    for name, path in replayed.items():
        shutil.copyfile(path, run_dir / "llm" / name)
    return run_dir
