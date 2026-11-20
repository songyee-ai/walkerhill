"""LLM 연결과 응답 저장 (T05).

실제 LLM 은 부르지 않는다. 엔진이 부르는 자리에는 테스트가 만든 공급자를 끼우고, 진짜 공급자 코드
(Anthropic SDK, OpenAI 호환 주소)는 이 PC 안에 띄운 가짜 주소(127.0.0.1)로 보내 요청과 응답의 모양을 본다.
"""

import json
import re
import subprocess
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from pydantic import ValidationError

import engine.__main__ as cli
import engine.llm as llm_module
from engine.answers import AnswerBook, read_reply
from engine.formats import (
    ChoiceRequest,
    ChoiceResponse,
    RejectedResponse,
    RunRecord,
    SavedResponse,
    read_model,
)
from engine.formats.choice import AddonChoice, Choice, Rejected, problems_in_response
from engine.llm import (
    DEFAULT_CALL_LIMIT,
    RESPONSE_SCHEMA,
    AnthropicProvider,
    ClaudeCodeProvider,
    LlmError,
    LlmFatal,
    LlmReply,
    LlmSettings,
    OpenAICompatibleProvider,
    _attribute_paths,
    _one_of,
    load_prompt,
    make_provider,
    prompt_path,
    receiver_of,
    response_schema,
    settings_from_env,
    user_message,
)
from engine.runner import MAX_FAILED_CALLS_IN_A_ROW, _engine_commit, run
from tests.conftest import REPO_ROOT, load_json, save_json
from tests.test_engine import (
    DINNER,
    LUNCH,
    NOW,
    TAKEOUT,
    Played,
    answer,
    edit,
    first_option,
    make_takeout,
    product_of,
    requests_in,
    venue_file,
)
from tools.check_formats import check

PROVIDER, MODEL = "fake", "fake-model"
ELDERS, KIDS = "family-elders", "family-kids"
ELDERS_DINNER = f"{ELDERS}__{DINNER}"
LLM_ENV = (
    "BASE_PROFILE_CONFIRMED_FOR",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_CALL_LIMIT",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_RESPONSE_FORMAT",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
)


# ── 도우미 ──────────────────────────────────────────────────────────────


def as_text(response: ChoiceResponse) -> str:
    return json.dumps(response.model_dump(mode="json"), ensure_ascii=False)


def geumryong(request: ChoiceRequest) -> str:
    return as_text(first_option(request, "geumryong"))


class Fake:
    """테스트가 끼우는 공급자. `reply(요청)` 이 돌려준 글을 답으로 준다. 부른 것을 `calls`, 받은 응답 스키마를 `schemas` 에 남긴다."""

    def __init__(self, reply=geumryong) -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []
        self.schemas: list[dict] = []

    def complete(self, system: str, user: str, schema: dict) -> LlmReply:
        self.calls.append((system, user))
        self.schemas.append(schema)
        return LlmReply(self.reply(ChoiceRequest.model_validate_json(user)), 11, 7)


class NeverCalled:
    def complete(self, system: str, user: str, schema: dict) -> LlmReply:
        raise AssertionError("저장된 응답이 있는데 LLM 을 불렀다")


def go(root, llm, *, now=NOW, limit=10, answers=(), persona_ids=(ELDERS,), condition_ids=(DINNER,), prompt="p1") -> Played:
    run_dir = run(
        root,
        data_mode="sample",
        now=now,
        provider=PROVIDER,
        model=MODEL,
        prompt_version=prompt,
        answers=list(answers),
        persona_ids=list(persona_ids),
        condition_ids=list(condition_ids),
        engine_commit="0000000",
        llm=llm,
        call_limit=limit,
    )
    return Played(root, run_dir, requests_in(root, list(persona_ids), list(condition_ids)))


def later(minutes: int) -> datetime:
    return NOW + timedelta(minutes=minutes)


def without_run_columns(rows) -> list[dict]:
    """실행마다 다른 칸(run_id, 새로 불렀는지)을 뺀 원장."""
    return [row.model_dump(exclude={"run_id", "llm_call"}) for row in rows]


def no_format_errors(root) -> None:
    assert [str(p) for p in check(root, strict=True)] == []


# ── 새로 부르고, 저장하고, 재생한다 ─────────────────────────────────────


def test_new_call_is_checked_saved_and_written_to_the_ledger(example_copy):
    fake = Fake()
    played = go(example_copy, fake)

    assert [(row.venue_id, row.llm_call, row.status) for row in played.rows] == [("geumryong", "new", "ok")]
    request = played.requests[ELDERS_DINNER]
    # 엔진은 프롬프트 파일의 글과 요청만 보낸다. 덧붙이는 글이 없다.
    assert fake.calls == [(load_prompt(example_copy, "p1"), user_message(request))]

    request_hash = played.rows[0].request_hash
    saved = played.saved[request_hash]
    assert (saved.provider, saved.model, saved.created_at) == (PROVIDER, MODEL, NOW)
    assert saved.request == request
    assert saved.raw_text == geumryong(request)
    assert (saved.usage.input_tokens, saved.usage.output_tokens) == (11, 7)
    assert not (played.run_dir / "llm_rejected").exists()

    llm = played.record.llm
    assert (llm.calls_new, llm.calls_replayed, llm.call_limit, llm.stopped_by_limit) == (1, 0, 10, False)
    assert played.record.status == "ok"
    assert played.record.counts.model_dump() == {"visits": 1, "failed": 0}
    assert "prompt" in played.record.inputs
    no_format_errors(example_copy)


def test_saved_response_is_replayed_and_the_ledger_is_the_same(example_copy):
    first = go(example_copy, Fake(), persona_ids=(ELDERS, KIDS), condition_ids=(DINNER, LUNCH))
    again = go(
        example_copy,
        NeverCalled(),
        now=later(5),
        answers=[first.run_dir / "llm"],
        persona_ids=(ELDERS, KIDS),
        condition_ids=(DINNER, LUNCH),
    )

    assert {row.llm_call for row in first.rows} == {"new"}
    assert {row.llm_call for row in again.rows} == {"replay"}
    assert without_run_columns(again.rows) == without_run_columns(first.rows)
    assert (again.record.llm.calls_new, again.record.llm.calls_replayed) == (0, 4)
    assert (first.record.llm.calls_new, first.record.llm.calls_replayed) == (4, 0)
    # 재생한 응답은 그 실행의 llm/ 에도 베껴 둔다. 원장이 가리키는 파일이 실행 폴더 안에 있어야 한다.
    assert set(again.saved) == set(first.saved)
    no_format_errors(example_copy)


def test_changed_prompt_text_is_recorded_in_the_run(example_copy):
    first = go(example_copy, Fake())
    path = prompt_path(example_copy, "p1")
    path.write_text(path.read_text(encoding="utf-8") + "\n한 줄 더.\n", encoding="utf-8")
    second = go(example_copy, Fake(), now=later(5))
    assert first.record.inputs["prompt"] != second.record.inputs["prompt"]


def test_replay_only_run_does_not_need_the_prompt(example_copy):
    prompt_path(example_copy, "p1").unlink()
    played = go(example_copy, None, limit=0)
    assert [row.status for row in played.rows] == ["failed"]
    assert "prompt" not in played.record.inputs
    assert (played.record.llm.calls_new, played.record.llm.call_limit) == (0, 0)


def test_missing_prompt_stops_before_anything_is_written(example_copy):
    with pytest.raises(FileNotFoundError, match="프롬프트 파일이 없다"):
        go(example_copy, Fake(), prompt="p9")
    assert not (example_copy / "engine" / "samples" / "runs" / f"{NOW:%Y%m%d-%H%M%S}-baseline").exists()


@pytest.mark.parametrize("version", ["../p1", "P1", "", "a/b", "p1.md/../x"])
def test_prompt_version_is_a_plain_file_name(example_copy, version):
    with pytest.raises(ValueError, match="prompt_version"):
        prompt_path(example_copy, version)


def test_empty_prompt_file_is_refused(example_copy):
    prompt_path(example_copy, "p1").write_text("  \n", encoding="utf-8")
    with pytest.raises(ValueError, match="비어 있다"):
        go(example_copy, Fake())


# ── 어긋난 답 ───────────────────────────────────────────────────────────


def outside_candidates(request: ChoiceRequest) -> str:
    return as_text(answer(request, "not-a-candidate", "not-a-candidate-o1"))


def label_outside_vocab(request: ChoiceRequest) -> str:
    response = first_option(request, "geumryong").model_dump(mode="json")
    response["reason_labels"] = ["값 목록에 없는 라벨"]
    return json.dumps(response, ensure_ascii=False)


def two_things_wrong(request: ChoiceRequest) -> str:
    response = first_option(request, "geumryong").model_dump(mode="json")
    response["reason_labels"] = ["값 목록에 없는 라벨"]
    response["rejected"] = response["rejected"][1:]
    return json.dumps(response, ensure_ascii=False)


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (outside_candidates, "후보에 없다"),
        (label_outside_vocab, "vocab.reasons_chosen 에 없다"),
        (two_things_wrong, "vocab.reasons_chosen 에 없다; 고르지 않은 후보"),
        (lambda request: "죄송하지만 고를 수 없습니다.", "응답에 JSON 이 없다"),
        (lambda request: '{"choice": {"venue_id": null}}', "응답이 형식에 맞지 않는다"),
        (lambda request: geumryong(request).replace('"addons": []', '"addons": [], "total": 600000'), "응답이 형식에 맞지 않는다"),
    ],
)
def test_reply_that_breaks_the_rules_fails_the_visit_and_is_kept_aside(example_copy, reply, reason):
    played = go(example_copy, Fake(reply))

    (row,) = played.rows
    assert (row.status, row.llm_call, row.choice_kind, row.paid) == ("failed", "new", "none", 0)
    assert reason in row.fail_reason
    # 어긋난 답은 재생할 llm/ 에 두지 않는다. 따로 남긴다.
    assert played.saved == {}
    kept = read_model(played.run_dir / "llm_rejected" / f"{row.request_hash}.json", RejectedResponse)
    assert kept.llm_call == "new"
    assert kept.request == played.requests[ELDERS_DINNER]
    assert kept.raw_text == reply(played.requests[ELDERS_DINNER])
    assert "; ".join(kept.problems) == row.fail_reason
    assert (kept.usage.input_tokens, kept.usage.output_tokens) == (11, 7)
    assert played.record.counts.model_dump() == {"visits": 1, "failed": 1}
    assert played.record.status == "ok"
    no_format_errors(example_copy)


def test_new_reply_is_also_checked_against_the_venue_definition(example_copy):
    """요청만 보아서는 알 수 없는 어긋남(함께 파는 달이 없는 상품들)도 새로 받은 답에서 잡는다."""
    make_takeout(example_copy)

    def sold_apart(venue: dict) -> None:
        product_of(venue, "gift-box")["months"] = [1, 2, 3]
        product_of(venue, "tea-tin")["months"] = [7, 8, 9]

    edit(venue_file(example_copy, "geumryong"), sold_apart)

    def both(request: ChoiceRequest) -> str:
        return as_text(answer(request, "geumryong", None, [("gift-box", 1), ("tea-tin", 1)]))

    played = go(example_copy, Fake(both), condition_ids=(TAKEOUT,))

    (row,) = played.rows
    assert (row.status, row.llm_call) == ("failed", "new")
    assert row.fail_reason == "고른 상품들을 함께 파는 달이 없다"
    assert played.saved == {}
    assert (played.run_dir / "llm_rejected" / f"{row.request_hash}.json").is_file()
    no_format_errors(example_copy)


def test_rejected_reply_is_not_replayed_next_time(example_copy):
    first = go(example_copy, Fake(outside_candidates))
    fake = Fake()
    again = go(example_copy, fake, now=later(5), answers=[first.run_dir / "llm", first.run_dir / "llm_rejected"])
    # llm_rejected/ 를 찾는 폴더에 넣어도 읽지 못하는 파일로 남을 뿐, 답으로 쓰이지 않는다.
    assert [row.status for row in again.rows] == ["failed"]
    assert again.rows[0].llm_call == "replay"
    again = go(example_copy, fake, now=later(10), answers=[first.run_dir / "llm"])
    assert [(row.status, row.llm_call) for row in again.rows] == [("ok", "new")]
    assert len(fake.calls) == 1


def test_saved_answer_that_breaks_the_rules_is_kept_aside_as_a_replay(example_copy):
    first = go(example_copy, Fake())
    request_hash = first.rows[0].request_hash
    # 저장된 응답의 답만 고친다 (요청은 그대로라 해시는 맞다).
    answers = example_copy.parent / "edited"
    saved = load_json(first.run_dir / "llm" / f"{request_hash}.json")
    saved["response"]["reason_labels"] = ["값 목록에 없는 라벨"]
    save_json(answers / f"{request_hash}.json", saved)

    again = go(example_copy, NeverCalled(), now=later(5), answers=[answers])
    (row,) = again.rows
    assert (row.status, row.llm_call) == ("failed", "replay")
    kept = read_model(again.run_dir / "llm_rejected" / f"{request_hash}.json", RejectedResponse)
    assert (kept.llm_call, kept.raw_text) == ("replay", saved["raw_text"])
    assert (kept.usage.input_tokens, kept.usage.output_tokens) == (11, 7)
    assert again.saved == {}
    assert again.record.llm.calls_replayed == 1
    no_format_errors(example_copy)


@pytest.mark.parametrize(
    "wrap",
    [
        lambda text: f"```json\n{text}\n```",
        lambda text: f"고른 결과입니다.\n{text}\n이상입니다.",
        lambda text: f"\n\n  {text}  \n",
    ],
)
def test_json_wrapped_in_other_text_is_still_read(example_copy, wrap):
    played = go(example_copy, Fake(lambda request: wrap(geumryong(request))))
    assert [(row.venue_id, row.status) for row in played.rows] == [("geumryong", "ok")]
    # LLM 이 돌려준 글은 손대지 않고 그대로 남긴다.
    (saved,) = played.saved.values()
    assert saved.raw_text == wrap(geumryong(played.requests[ELDERS_DINNER]))


def test_reply_is_read_strictly():
    response, problems = read_reply('{"choice": {"venue_id": null, "option_id": null, "addons": [{"product_id": "tea", "quantity": "2"}]}}')
    assert response is None
    assert "choice.addons.0.quantity" in problems[0]


# ── 호출 상한과 실패 ────────────────────────────────────────────────────


def test_call_limit_stops_the_run_and_says_so(example_copy):
    fake = Fake()
    stopped = go(example_copy, fake, limit=2, persona_ids=(ELDERS, KIDS), condition_ids=(DINNER, LUNCH))

    assert stopped.record.status == "stopped_by_limit"
    llm = stopped.record.llm
    assert (llm.calls_new, llm.call_limit, llm.stopped_by_limit) == (2, 2, True)
    assert len(fake.calls) == 2
    # 멈추기 전까지 돌린 방문만 원장에 있다.
    assert [row.visit_id for row in stopped.rows] == [f"{ELDERS}__{DINNER}", f"{ELDERS}__{LUNCH}"]
    assert stopped.record.counts.model_dump() == {"visits": 2, "failed": 0}
    no_format_errors(example_copy)

    # 다시 돌리면 받은 답은 재생하고 남은 방문만 새로 부른다.
    resumed = go(
        example_copy,
        fake,
        now=later(5),
        limit=2,
        answers=[stopped.run_dir / "llm"],
        persona_ids=(ELDERS, KIDS),
        condition_ids=(DINNER, LUNCH),
    )
    assert resumed.record.status == "ok"
    assert (resumed.record.llm.calls_new, resumed.record.llm.calls_replayed) == (2, 2)
    assert resumed.record.counts.model_dump() == {"visits": 4, "failed": 0}
    no_format_errors(example_copy)


def test_limit_of_zero_calls_nothing(example_copy):
    fake = Fake()
    played = go(example_copy, fake, limit=0)
    assert fake.calls == []
    assert (played.record.status, played.rows, played.record.counts.visits) == ("stopped_by_limit", [], 0)


def test_failed_calls_count_against_the_limit(example_copy):
    def broken(request):
        raise LlmError("연결이 끊겼다")

    played = go(example_copy, Fake(broken), limit=1, condition_ids=(DINNER, LUNCH))
    assert played.record.status == "stopped_by_limit"
    assert played.record.llm.calls_new == 1
    assert [row.status for row in played.rows] == ["failed"]


def test_failed_call_fails_that_visit_and_the_run_goes_on(example_copy):
    def flaky(request):
        if request.condition.condition_id == DINNER:
            raise LlmError("연결이 끊겼다\n다시 해 본다")
        return geumryong(request)

    played = go(example_copy, Fake(flaky), condition_ids=(DINNER, LUNCH))

    dinner, lunch = played.visit(ELDERS, DINNER), played.visit(ELDERS, LUNCH)
    assert [(row.status, row.llm_call) for row in dinner] == [("failed", "new")]
    assert "연결이 끊겼다" in dinner[0].fail_reason
    assert [(row.status, row.venue_id) for row in lunch] == [("ok", "geumryong")]
    assert played.record.status == "ok"
    assert played.record.llm.calls_new == 2
    assert played.record.counts.model_dump() == {"visits": 2, "failed": 1}
    # 답을 받지 못한 방문에는 남길 응답이 없다.
    assert not (played.run_dir / "llm_rejected").exists()
    no_format_errors(example_copy)


def test_wrong_settings_stop_the_run_at_the_first_call(example_copy):
    def refused(request):
        raise LlmFatal("키를 확인한다")

    fake = Fake(refused)
    played = go(example_copy, fake, persona_ids=(ELDERS, KIDS), condition_ids=(DINNER, LUNCH))

    assert len(fake.calls) == 1
    assert played.record.status == "failed"
    assert played.record.llm.stopped_by_limit is False
    assert [(row.status, row.fail_reason, row.llm_call) for row in played.rows] == [("failed", "키를 확인한다", "new")]
    # 부르다 실패한 줄에도 어느 요청이었는지가 남는다.
    assert played.rows[0].request_hash == AnswerBook([], PROVIDER, MODEL).hash_of(played.requests[ELDERS_DINNER])
    assert played.record.counts.model_dump() == {"visits": 1, "failed": 1}
    no_format_errors(example_copy)


def test_calls_failing_in_a_row_stop_the_run(example_copy):
    """닿지 않는 주소나 멈춘 공급자를 상한까지 계속 부르지 않는다."""

    def down(request):
        raise LlmError("연결할 수 없다")

    fake = Fake(down)
    played = go(example_copy, fake, limit=50, persona_ids=(ELDERS, KIDS), condition_ids=(DINNER, LUNCH))

    assert len(fake.calls) == MAX_FAILED_CALLS_IN_A_ROW == 3
    assert played.record.status == "failed"
    assert played.record.counts.model_dump() == {"visits": 3, "failed": 3}
    reasons = [row.fail_reason for row in played.rows]
    assert reasons[:2] == ["연결할 수 없다", "연결할 수 없다"]
    assert reasons[2] == "연결할 수 없다 (호출이 연달아 3번 실패해 멈춘다)"
    no_format_errors(example_copy)


def test_a_reply_between_failed_calls_keeps_the_run_going(example_copy):
    seen = []

    def on_and_off(request):
        seen.append(request.condition.condition_id)
        if len(seen) in (1, 2, 4, 5):
            raise LlmError("연결할 수 없다")
        return geumryong(request)

    conditions = (DINNER, LUNCH, "meal-dinner-weekday")
    played = go(example_copy, Fake(on_and_off), limit=50, persona_ids=(ELDERS, KIDS), condition_ids=conditions)

    assert [row.status for row in played.rows] == ["failed", "failed", "ok", "failed", "failed", "ok"]
    assert played.record.status == "ok"
    assert played.record.llm.calls_new == 6


def test_a_reply_that_breaks_the_rules_also_ends_the_streak_of_failed_calls(example_copy):
    """읽을 글을 받았으면 공급자는 살아 있다. 검사에서 어긋난 답이어도 연달아 실패한 수를 0 으로 되돌린다."""
    seen = []

    def on_and_off(request):
        seen.append(request.condition.condition_id)
        if len(seen) in (1, 2, 4, 5):
            raise LlmError("연결할 수 없다")
        return outside_candidates(request)

    conditions = (DINNER, LUNCH, "meal-dinner-weekday")
    played = go(example_copy, Fake(on_and_off), limit=50, persona_ids=(ELDERS, KIDS), condition_ids=conditions)

    assert len(seen) == 6
    assert (played.record.status, played.record.counts.failed) == ("ok", 6)


def test_unexpected_error_still_leaves_a_run_record(example_copy):
    """받은 답만 있고 실행 기록이 없는 폴더를 남기지 않는다. 그런 폴더는 형식 검사가 막는다."""

    def breaks_on_the_second(request):
        if request.condition.condition_id == LUNCH:
            raise RuntimeError("코드의 잘못")
        return geumryong(request)

    with pytest.raises(RuntimeError, match="코드의 잘못"):
        go(example_copy, Fake(breaks_on_the_second), condition_ids=(DINNER, LUNCH))

    run_dir = example_copy / "engine" / "samples" / "runs" / f"{NOW:%Y%m%d-%H%M%S}-baseline"
    record = read_model(run_dir / "run.json", RunRecord)
    assert record.status == "failed"
    assert record.counts.model_dump() == {"visits": 1, "failed": 0}
    assert (record.llm.calls_new, record.llm.stopped_by_limit) == (2, False)
    assert len(list((run_dir / "llm").glob("*.json"))) == 1
    no_format_errors(example_copy)


def test_limit_defaults_to_the_documented_value_when_an_llm_is_given(example_copy):
    run_dir = run(
        example_copy,
        data_mode="sample",
        now=NOW,
        provider=PROVIDER,
        model=MODEL,
        prompt_version="p1",
        answers=[],
        persona_ids=[ELDERS],
        condition_ids=[DINNER],
        llm=Fake(),
    )
    record = read_model(run_dir / "run.json", RunRecord)
    assert (record.status, record.llm.calls_new, record.llm.call_limit) == ("ok", 1, DEFAULT_CALL_LIMIT)
    # 실행 기록의 커밋은 자료의 폴더가 아니라 돌아가는 엔진 코드의 것이다.
    assert record.engine_commit == _engine_commit(REPO_ROOT)


# ── 가상 예시로 돌릴 때 private/ 를 읽지 않는다 ─────────────────────────


def test_sample_run_with_llm_does_not_read_or_write_private(example_copy):
    private = example_copy / "private"
    (private / "personas").mkdir(parents=True)
    (private / "personas" / f"{ELDERS}.json").write_text("읽으면 오류가 나는 파일", encoding="utf-8")
    (private / "runs" / "20261101-000000-baseline" / "llm").mkdir(parents=True)

    fake = Fake()
    played = go(example_copy, fake)

    sent = json.loads(fake.calls[0][1])
    assert "overridden_by_private" not in sent["persona"]
    assert not sent["persona"].get("base_profile")
    assert played.run_dir.parent == example_copy / "engine" / "samples" / "runs"
    assert sorted(p.name for p in (private / "runs").iterdir()) == ["20261101-000000-baseline"]
    # 실행하는 명령이 찾는 앞선 실행도 같은 쪽의 것뿐이다.
    assert all(example_copy / "private" not in folder.parents for folder in cli.earlier_answers(example_copy, "sample"))
    assert cli.earlier_answers(example_copy, "private") == [private / "runs" / "20261101-000000-baseline" / "llm"]


# ── 설정 ────────────────────────────────────────────────────────────────


def test_settings_default_to_the_values_in_env_example():
    settings = settings_from_env({})
    # .env.example 은 변수마다 그 위의 줄 끝에 기본값을 괄호로 적어 둔다. 코드의 기본값이 그것과 같아야 한다.
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    written = {name: value for value, name in re.findall(r"\(([^()\n]+)\)[^\n]*\n(LLM_[A-Z_]+)=", example)}
    assert written["LLM_PROVIDER"] == settings.provider
    assert written["LLM_MODEL"] == settings.model
    assert written["LLM_CALL_LIMIT"] == str(settings.call_limit)
    assert written["LLM_RESPONSE_FORMAT"] == "json_schema"
    assert (settings.provider, settings.call_limit) == ("anthropic", DEFAULT_CALL_LIMIT)
    # 값이 비어 있으면 기본값을 쓴다.
    assert settings_from_env({"LLM_PROVIDER": "", "LLM_MODEL": " ", "LLM_CALL_LIMIT": ""}) == settings


def test_env_example_copied_as_it_is_calls_claude_with_the_team_model(fake_claude, monkeypatch):
    """팀 설정(11-17, T114): .env.example 을 그대로 베끼면 각자의 Claude 구독(`claude -p`)으로 팀이 정한 모델을 부른다. 키는 쓰지 않는다."""
    _, _, executable = fake_claude
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    env = dict(re.findall(r"^([A-Z_]+)=(.*)$", example, re.M))
    assert env["LLM_PROVIDER"] == "claude-code"
    # 팀이 정한 모델이 적혀 있다. 모두 같은 모델이어야 저장된 답을 서로 재생한다.
    assert re.fullmatch(r"claude-[a-z0-9-]+", env["LLM_MODEL"])
    # 비밀값은 적혀 있지 않다.
    assert env["LLM_API_KEY"] == env["ANTHROPIC_API_KEY"] == ""
    settings = settings_from_env(env)
    assert (settings.provider, settings.model) == ("claude-code", env["LLM_MODEL"])
    # 실행 파일의 경로를 비워 두면 PATH 의 claude 를 부른다. 테스트에서는 PATH 에 가짜 claude 가 있는 것으로 둔다.
    assert env["CLAUDE_CODE_PATH"] == ""
    monkeypatch.setattr(llm_module.shutil, "which", lambda name: executable if name == "claude" else None)
    provider = make_provider(settings, env)
    assert isinstance(provider, ClaudeCodeProvider)
    assert (provider.model, provider.executable) == (env["LLM_MODEL"], executable)
    # 화면의 AI 메뉴가 읽는 이름이 있다 (T202). 팀 설정에서는 비워 둔다 (비우면 LLM_MODEL 을 쓴다).
    assert env["CLAUDE_MODEL"] == env["OPENAI_MODEL"] == ""


def test_env_example_can_still_be_pointed_at_openai():
    """팀 설정이 아닌 길: 공급자를 openai-compatible 로 바꾸고 키와 모델을 넣으면 적혀 있는 주소로 부른다 (그 답은 보정과 시연에 쓰지 않는다)."""
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    env = dict(re.findall(r"^([A-Z_]+)=(.*)$", example, re.M))
    assert env["LLM_BASE_URL"] == "https://api.openai.com/v1"
    with pytest.raises(LlmFatal, match="LLM_MODEL"):
        settings_from_env({**env, "LLM_PROVIDER": "openai-compatible", "LLM_MODEL": ""})  # 이 공급자는 모델을 꼭 적는다
    filled = {**env, "LLM_PROVIDER": "openai-compatible", "LLM_API_KEY": "test-key", "LLM_MODEL": "other-model"}
    settings = settings_from_env(filled)
    assert (settings.provider, settings.model) == ("openai-compatible", "other-model")
    provider = make_provider(settings, filled)
    assert isinstance(provider, OpenAICompatibleProvider)
    assert (provider.url, provider.api_key, provider.response_format) == (
        "https://api.openai.com/v1/chat/completions",
        "test-key",
        "json_schema",
    )


def test_receiver_is_the_provider_and_for_an_address_also_its_host():
    """요약을 보내도 된다는 확인은 받는 곳의 이름으로 적는다 (T115). 주소로 받는 곳이 갈리는 공급자는 호스트까지 든다."""
    assert receiver_of(LlmSettings("anthropic", "m", 1), {}) == "anthropic"
    # 주소가 적혀 있어도 그 공급자가 쓰지 않으면 보지 않는다.
    assert receiver_of(LlmSettings("claude-code", "m", 1), {"LLM_BASE_URL": "https://api.openai.com/v1"}) == "claude-code"
    openai = LlmSettings("openai-compatible", "m", 1)
    assert receiver_of(openai, {"LLM_BASE_URL": "https://api.openai.com/v1"}) == "openai-compatible:api.openai.com"
    # 호스트만 본다: 대소문자, 포트, 경로는 받는 곳을 가르지 않는다.
    assert receiver_of(openai, {"LLM_BASE_URL": " https://API.OpenAI.com:443/v1/ "}) == "openai-compatible:api.openai.com"
    assert receiver_of(openai, {"LLM_BASE_URL": "http://localhost:11434/v1"}) == "openai-compatible:localhost"
    # 주소가 없으면 어느 확인과도 맞지 않는 이름이 된다 (공급자의 이름만 적은 확인으로는 통하지 않는다).
    assert receiver_of(openai, {}) == "openai-compatible:"


def test_settings_are_read_from_the_environment():
    env = {"LLM_PROVIDER": "openai-compatible", "LLM_MODEL": "local-model", "LLM_CALL_LIMIT": "3"}
    assert settings_from_env(env) == LlmSettings("openai-compatible", "local-model", 3)


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"LLM_PROVIDER": "other"}, "LLM_PROVIDER"),
        ({"LLM_PROVIDER": "openai-compatible"}, "LLM_MODEL"),
        ({"LLM_CALL_LIMIT": "many"}, "LLM_CALL_LIMIT"),
        ({"LLM_CALL_LIMIT": "-1"}, "LLM_CALL_LIMIT"),
    ],
)
def test_wrong_settings_are_refused(env, message):
    with pytest.raises(LlmFatal, match=message):
        settings_from_env(env)


@pytest.mark.parametrize(
    "base_url", ["", "file:///etc/passwd", "localhost:8000/v1", "http://example.com/v1", "http://192.168.0.10:8000/v1", "https://"]
)
def test_openai_compatible_needs_an_https_or_local_address(base_url):
    with pytest.raises(LlmFatal, match="LLM_BASE_URL"):
        make_provider(LlmSettings("openai-compatible", "local-model", 3), {"LLM_BASE_URL": base_url})


@pytest.mark.parametrize(
    "base_url", ["https://example.com/v1", "http://localhost:8000/v1", "http://127.0.0.1:8000", "http://[::1]:8000/v1/"]
)
def test_openai_compatible_accepts_https_and_local_http(base_url):
    provider = make_provider(LlmSettings("openai-compatible", "local-model", 3), {"LLM_BASE_URL": base_url})
    assert provider.url == base_url.rstrip("/") + "/chat/completions"


def test_response_schema_has_the_keys_of_the_response_model(doc):
    def keys(schema: dict) -> set[str]:
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        return set(schema["properties"])

    top = RESPONSE_SCHEMA["properties"]
    choice, addon, rejected = top["choice"], top["choice"]["properties"]["addons"]["items"], top["rejected"]["items"]
    # `scores` 는 점수를 묻는 판의 요청에만 더한다 (T212). 문서의 응답 예시는 점수를 묻지 않던 판(p1)의 답이라 `scores` 가 없고, 따로 적은 예시에 있다.
    assert keys(RESPONSE_SCHEMA) | {"scores"} == set(ChoiceResponse.model_fields) == set(doc.response) | {"scores"}
    assert keys(choice) == set(Choice.model_fields)
    assert keys(addon) == set(AddonChoice.model_fields)
    assert keys(rejected) == set(Rejected.model_fields)

    # 값의 종류도 모델과 같다. "이용하지 않음"은 업장과 주문이 null 이고, 수량은 정수다.
    text, texts = {"type": "string"}, {"type": "array", "items": {"type": "string"}}
    text_or_null = {"anyOf": [text, {"type": "null"}]}
    assert choice["properties"]["venue_id"] == choice["properties"]["option_id"] == text_or_null
    assert addon["properties"] == {"product_id": text, "quantity": {"type": "integer"}}
    assert rejected["properties"] == {"venue_id": text, "pain_labels": texts, "text": text}
    assert (top["reason_labels"], top["reason_text"], top["used_attributes"]) == (texts, text, texts)


# ── 진짜 공급자 코드를 이 PC 안의 가짜 주소로 보낸다 ───────────────────


class Stub:
    """127.0.0.1 에 띄운 가짜 LLM 주소. 받은 요청을 `seen` 에 남기고 `answer(경로, 본문)` 이 돌려준 것을 답한다."""

    def __init__(self) -> None:
        self.seen: list[dict] = []
        self.answer = lambda path, body: (500, {})
        # 3xx 로 답할 때 넘길 주소.
        self.redirect_to: str | None = None
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.do_POST()

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                stub.seen.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                status, payload = stub.answer(self.path, body)
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
                self.send_response(status)
                if 300 <= status < 400 and stub.redirect_to:
                    self.send_header("Location", stub.redirect_to)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub():
    server = Stub()
    yield server
    server.close()


@pytest.fixture
def clean_env(monkeypatch):
    """이 PC 의 .env 와 환경 변수가 테스트에 섞이지 않게 한다."""
    for name in LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "load_dotenv", lambda *args, **kwargs: False)
    return monkeypatch


def chat_completion(text, finish_reason: str = "stop") -> dict:
    return {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 21, "completion_tokens": 9},
    }


def anthropic_message(text: str, stop_reason: str = "end_turn") -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "stub-model",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 31, "output_tokens": 13},
    }


def openai_answers(path: str, body: dict) -> tuple[int, dict]:
    request = ChoiceRequest.model_validate_json(body["messages"][1]["content"])
    return 200, chat_completion(geumryong(request))


def anthropic_answers(path: str, body: dict) -> tuple[int, dict]:
    request = ChoiceRequest.model_validate_json(body["messages"][0]["content"])
    return 200, anthropic_message(geumryong(request))


def test_openai_compatible_request_and_reply(stub):
    stub.answer = lambda path, body: (200, chat_completion('{"ok": true}'))
    provider = OpenAICompatibleProvider("local-model", stub.url + "/v1/", "test-key")

    reply = provider.complete("시스템 프롬프트", "사용자 메시지")

    assert reply == LlmReply('{"ok": true}', 21, 9)
    (seen,) = stub.seen
    assert seen["path"] == "/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer test-key"
    assert seen["body"] == {
        "model": "local-model",
        "messages": [{"role": "system", "content": "시스템 프롬프트"}, {"role": "user", "content": "사용자 메시지"}],
        # 응답의 모양을 엄격한 스키마로 묶어 보낸다 (11-16, T103). 스키마를 주지 않으면 기본 응답 스키마다.
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "choice_response", "schema": RESPONSE_SCHEMA, "strict": True},
        },
    }


def test_openai_compatible_sends_the_given_schema_or_only_json_object(stub):
    """주어진 스키마를 그대로 보내고, 스키마를 받지 않는 주소는 `json_object` 로 바꿀 수 있다 (LLM_RESPONSE_FORMAT)."""
    stub.answer = lambda path, body: (200, chat_completion("{}"))
    narrowed = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    OpenAICompatibleProvider("local-model", stub.url, None).complete("s", "u", narrowed)
    assert stub.seen[0]["body"]["response_format"]["json_schema"]["schema"] == narrowed
    OpenAICompatibleProvider("local-model", stub.url, None, "json_object").complete("s", "u", narrowed)
    assert stub.seen[1]["body"]["response_format"] == {"type": "json_object"}
    with pytest.raises(LlmFatal, match="LLM_RESPONSE_FORMAT"):
        OpenAICompatibleProvider("local-model", stub.url, None, "text")


def test_make_provider_reads_the_response_format():
    env = {"LLM_BASE_URL": "https://api.openai.com/v1", "LLM_API_KEY": "test-key"}
    settings = LlmSettings("openai-compatible", "m", 1)
    assert make_provider(settings, env).response_format == "json_schema"
    assert make_provider(settings, {**env, "LLM_RESPONSE_FORMAT": "json_object"}).response_format == "json_object"
    with pytest.raises(LlmFatal, match="LLM_RESPONSE_FORMAT"):
        make_provider(settings, {**env, "LLM_RESPONSE_FORMAT": "yaml"})


def test_response_schema_only_takes_what_the_request_offers(example_copy):
    """요청마다 만든 스키마는 후보, 값 목록, 페르소나의 속성 경로에 있는 값만 받는다 (11-16, T103).

    11-16 에 실제 LLM 의 답이 값 목록에 없는 라벨과 점으로 잇지 않은 속성 이름으로 어긋났다. 그 두 가지를 스키마가 먼저 막는다.
    엔진이 받는 답은 스키마도 받는다 (스키마가 엔진보다 좁으면 맞는 답을 공급자가 만들 수 없다).
    """
    import jsonschema  # 건너뛰지 않는다: 없으면 이 테스트가 실패해야 스키마가 엔진보다 좁아진 것을 놓치지 않는다
    fake = Fake()
    go(example_copy, fake)
    request = ChoiceRequest.model_validate_json(fake.calls[0][1])
    schema = fake.schemas[0]
    assert schema == response_schema(request)
    # 고를 값(enum)을 빼면 기본 응답 스키마와 같다: 모양은 그대로이고 글 칸만 좁혔다.
    assert without_enums(schema) == RESPONSE_SCHEMA
    assert request.candidates[0].venue_id in schema["properties"]["rejected"]["items"]["properties"]["venue_id"]["enum"]

    good = json.loads(geumryong(request))
    jsonschema.validate(good, schema)
    assert problems_in_response(request, ChoiceResponse.model_validate(good)) == []

    attribute = good["used_attributes"][0] if good["used_attributes"] else None
    bad_answers = [
        {**good, "reason_labels": ["값 목록에 없는 라벨"]},
        {**good, "used_attributes": ["점으로 잇지 않은 속성"]},
        {**good, "choice": {**good["choice"], "venue_id": "후보에-없는-업장"}},
        {**good, "rejected": [{"venue_id": "후보에-없는-업장", "pain_labels": [], "text": "t"}]},
    ]
    for bad in bad_answers:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)
    if attribute and "." in attribute:
        leaf = attribute.split(".")[-1]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**good, "used_attributes": [leaf]}, schema)


def without_enums(node):
    if isinstance(node, dict):
        return {key: without_enums(value) for key, value in node.items() if key != "enum"}
    if isinstance(node, list):
        return [without_enums(value) for value in node]
    return node


def test_response_schema_without_values_to_offer_still_takes_text():
    """고를 값이 없는 칸은 빈 enum 대신 글로 둔다 (공급자는 빈 enum 을 받지 않는다). 엔진이 답을 받은 뒤에 검사한다."""
    assert _one_of([]) == {"type": "string"}
    assert _one_of(["a", "b", "a"]) == {"type": "string", "enum": ["a", "b"]}  # 겹친 값은 하나만 (공급자가 받지 않는다)


def test_attribute_paths_cover_every_level_of_the_persona():
    assert _attribute_paths({"a": 1, "b": {"c": [1], "d": {"e": "x"}}}) == ["a", "b", "b.c", "b.d", "b.d.e"]


def test_openai_compatible_without_a_key_sends_no_authorization(stub):
    stub.answer = lambda path, body: (200, chat_completion("{}"))
    OpenAICompatibleProvider("local-model", stub.url, None).complete("s", "u")
    assert "authorization" not in stub.seen[0]["headers"]


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ((400, {"error": "bad request"}), LlmFatal),
        ((401, {"error": "bad key"}), LlmFatal),
        ((403, {"error": "not allowed"}), LlmFatal),
        ((404, {"error": "no such model"}), LlmFatal),
        ((429, {"error": "slow down"}), LlmError),
        ((500, {"error": "oops"}), LlmError),
        ((200, b"not json"), LlmError),
        ((200, {"choices": []}), LlmError),
        ((200, chat_completion("{", finish_reason="length")), LlmError),
        # 글이 아닌 것을 답으로 주는 주소도 있다. 엔진까지 올라가 실행을 끊지 않게 여기서 실패한 호출로 바꾼다.
        ((200, chat_completion([{"type": "text", "text": "{}"}])), LlmError),
        ((200, chat_completion(None)), LlmError),
        ((200, {**chat_completion("{}"), "usage": "none"}), LlmError),
        ((200, {**chat_completion("{}"), "usage": {"prompt_tokens": "many"}}), LlmError),
        ((200, {**chat_completion("{}"), "usage": {"prompt_tokens": -5}}), LlmError),
        ((200, {**chat_completion("{}"), "usage": {"completion_tokens": -1}}), LlmError),
        ((200, ["not", "an", "object"]), LlmError),
    ],
)
def test_openai_compatible_failures(stub, answer, error):
    stub.answer = lambda path, body: answer
    with pytest.raises(LlmError) as caught:
        OpenAICompatibleProvider("local-model", stub.url, "test-key").complete("s", "u")
    assert type(caught.value) is error
    assert "test-key" not in str(caught.value)


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_openai_compatible_does_not_follow_redirects_with_the_key(stub, status):
    elsewhere = Stub()
    elsewhere.answer = lambda path, body: (200, chat_completion("{}"))
    stub.redirect_to = elsewhere.url + "/v1/chat/completions"
    stub.answer = lambda path, body: (status, {})
    try:
        with pytest.raises(LlmFatal, match="다른 곳으로 넘기려 한다"):
            OpenAICompatibleProvider("local-model", stub.url, "test-key").complete("s", "u")
    finally:
        elsewhere.close()
    assert len(stub.seen) == 1
    assert elsewhere.seen == []


def test_openai_compatible_calls_a_local_address_without_the_proxy(stub, monkeypatch):
    """PC 에 프록시가 설정돼 있어도 이 PC 의 주소는 바로 부른다. 프록시로 가면 키가 든 요청이 암호화되지 않은 채 나간다."""
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    stub.answer = lambda path, body: (200, chat_completion("{}"))
    assert OpenAICompatibleProvider("local-model", stub.url, "test-key").complete("s", "u").text == "{}"
    assert len(stub.seen) == 1


def test_files_the_format_check_would_refuse_are_not_written(example_copy):
    """공급자가 틀린 값을 주더라도, 실행은 끝났는데 형식 검사가 막는 파일이 남지 않는다."""

    class NegativeTokens(Fake):
        def complete(self, system: str, user: str, schema: dict) -> LlmReply:
            return LlmReply(super().complete(system, user, schema).text, -5, 7)

    with pytest.raises(ValidationError):
        go(example_copy, NegativeTokens())
    run_dir = example_copy / "engine" / "samples" / "runs" / f"{NOW:%Y%m%d-%H%M%S}-baseline"
    assert list((run_dir / "llm").glob("*.json")) == []
    assert read_model(run_dir / "run.json", RunRecord).status == "failed"
    no_format_errors(example_copy)


def test_openai_compatible_usage_may_be_missing(stub):
    stub.answer = lambda path, body: (200, {"choices": chat_completion("{}")["choices"]})
    assert OpenAICompatibleProvider("local-model", stub.url, None).complete("s", "u") == LlmReply("{}", 0, 0)


# ── Claude Code 명령 (T104. 11-17 부터 팀이 쓰는 공급자, T114) ─────────────────────────────────


def claude_code_result(structured=None, **more) -> str:
    """`claude -p --output-format json` 의 결과 모양 (공식 문서의 headless 절)."""
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "",
        "usage": {"input_tokens": 40, "cache_read_input_tokens": 2, "cache_creation_input_tokens": 3, "output_tokens": 9},
        **more,
    }
    if structured is not None:
        payload["structured_output"] = structured
    return json.dumps(payload, ensure_ascii=False)


@pytest.fixture
def fake_claude(monkeypatch, tmp_path):
    """Claude Code 를 띄우는 대신 받은 명령, 입력, 폴더, 환경을 남기고 정해 둔 결과를 돌려준다."""
    seen: dict = {}
    reply = {"stdout": claude_code_result({"ok": True}), "returncode": 0}

    def run(command, **kwargs):
        seen.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, reply["returncode"], reply["stdout"], "")

    monkeypatch.setattr(llm_module.subprocess, "run", run)
    executable = tmp_path / "claude.exe"
    executable.write_text("", encoding="utf-8")
    return seen, reply, str(executable)


def test_claude_code_runs_the_official_command_with_everything_else_off(fake_claude, monkeypatch):
    seen, _, executable = fake_claude
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")  # 있으면 구독 대신 키로 부르므로 넘기지 않는다
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "host-session")  # 이 프로그램을 띄운 Claude Code 세션의 것
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "token-from-setup-token")  # 구독 토큰은 넘긴다
    schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}

    reply = ClaudeCodeProvider("claude-sonnet-5-5", executable).complete("시스템 프롬프트", "사용자 메시지", schema)

    assert reply == LlmReply('{"ok": true}', 45, 9)
    command = seen["command"]
    assert command[:2] == [executable, "-p"]
    flag = {command[i]: command[i + 1] for i in range(2, len(command) - 1) if command[i].startswith("--")}
    assert flag["--model"] == "claude-sonnet-5-5"
    assert flag["--system-prompt"] == "시스템 프롬프트"  # Claude Code 의 시스템 프롬프트를 통째로 바꾼다
    assert flag["--tools"] == "" and flag["--setting-sources"] == ""  # 도구와 설정 파일(훅, 플러그인)을 끈다
    assert flag["--output-format"] == "json" and json.loads(flag["--json-schema"]) == schema
    assert {"--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"} <= set(command)
    assert seen["input"] == "사용자 메시지"  # 요청은 표준 입력으로 (명령줄 길이 한도를 피한다)
    assert not Path(seen["cwd"]).resolve().is_relative_to(REPO_ROOT.resolve())  # 저장소의 지침 파일이 끼어들지 않게
    env = seen["env"]
    assert not {"ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_SESSION_ID"} & set(env)
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "token-from-setup-token"


@pytest.mark.parametrize(
    ("stdout", "returncode", "error", "words"),
    [
        (claude_code_result(is_error=True, result="Not logged in · Please run /login"), 1, LlmFatal, "로그인"),
        (claude_code_result(is_error=True, result="You've hit your session limit · resets 3pm"), 1, LlmFatal, "사용 한도"),
        (claude_code_result(is_error=True, result="API Error: 500 overloaded"), 1, LlmError, "실패했다"),
        ("not json", 1, LlmError, "읽지 못했다"),
        (claude_code_result(), 0, LlmError, "structured_output"),  # 답이 없다 (거절 등)
    ],
)
def test_claude_code_failures(fake_claude, stdout, returncode, error, words):
    _, reply, executable = fake_claude
    reply.update(stdout=stdout, returncode=returncode)
    with pytest.raises(LlmError, match=words) as caught:
        ClaudeCodeProvider("m", executable).complete("s", "u", RESPONSE_SCHEMA)
    assert type(caught.value) is error


def test_claude_code_passes_a_text_answer_on_for_the_engine_to_check(fake_claude):
    """검증된 답이 없고 글로 된 답만 있으면 그대로 넘긴다. 엔진이 다시 검사해 어긋나면 실패로 남긴다."""
    _, reply, executable = fake_claude
    reply.update(stdout=claude_code_result(result='{"choice": null}'))
    assert ClaudeCodeProvider("m", executable).complete("s", "u").text == '{"choice": null}'


def test_claude_code_needs_the_program_and_fits_the_command_line(fake_claude, tmp_path):
    _, _, executable = fake_claude
    with pytest.raises(LlmFatal, match="CLAUDE_CODE_PATH"):
        ClaudeCodeProvider("m", str(tmp_path / "없는-claude.exe"))
    with pytest.raises(LlmFatal, match="명령줄"):
        ClaudeCodeProvider("m", executable).complete("가" * 40000, "u")
    settings = LlmSettings("claude-code", "claude-sonnet-5-5", 1)
    provider = make_provider(settings, {"CLAUDE_CODE_PATH": executable})
    assert isinstance(provider, ClaudeCodeProvider) and provider.executable == executable
    # 모델은 정해 둔 기본값이 없다. 각자 .env 에 적는다.
    with pytest.raises(LlmFatal, match="LLM_MODEL"):
        settings_from_env({"LLM_PROVIDER": "claude-code"})


def test_openai_compatible_address_that_does_not_answer_is_a_failed_call():
    closed = Stub()
    closed.close()
    with pytest.raises(LlmError) as caught:
        OpenAICompatibleProvider("local-model", closed.url, None).complete("s", "u")
    assert type(caught.value) is LlmError


def anthropic_provider(stub, monkeypatch) -> AnthropicProvider:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", stub.url)
    provider = AnthropicProvider("stub-model")
    # 실패를 볼 때 SDK 가 다시 불러 보느라 기다리지 않게 한다.
    provider.client = provider.client.with_options(max_retries=0)
    return provider


def test_anthropic_request_and_reply(stub, clean_env):
    stub.answer = lambda path, body: (200, anthropic_message('{"ok": true}'))

    reply = anthropic_provider(stub, clean_env).complete("시스템 프롬프트", "사용자 메시지")

    assert reply == LlmReply('{"ok": true}', 31, 13)
    (seen,) = stub.seen
    assert seen["path"] == "/v1/messages"
    assert seen["headers"]["x-api-key"] == "test-key"
    body = seen["body"]
    assert body["model"] == "stub-model"
    assert body["system"] == "시스템 프롬프트"
    assert body["messages"] == [{"role": "user", "content": "사용자 메시지"}]
    assert body["output_config"] == {"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}}
    assert body["max_tokens"] > 0
    # 지금 모델은 받지 않는 인자다. 보내면 요청이 거절된다.
    assert not {"temperature", "top_p", "top_k", "tool_choice"} & set(body)


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ((401, {"type": "error", "error": {"type": "authentication_error", "message": "bad key"}}), LlmFatal),
        ((403, {"type": "error", "error": {"type": "permission_error", "message": "not allowed"}}), LlmFatal),
        ((404, {"type": "error", "error": {"type": "not_found_error", "message": "no such model"}}), LlmFatal),
        ((400, {"type": "error", "error": {"type": "invalid_request_error", "message": "bad schema"}}), LlmFatal),
        ((429, {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}), LlmError),
        ((500, {"type": "error", "error": {"type": "api_error", "message": "oops"}}), LlmError),
        ((200, anthropic_message("", stop_reason="refusal")), LlmError),
        ((200, anthropic_message("{", stop_reason="max_tokens")), LlmError),
    ],
)
def test_anthropic_failures(stub, clean_env, answer, error):
    stub.answer = lambda path, body: answer
    with pytest.raises(LlmError) as caught:
        anthropic_provider(stub, clean_env).complete("s", "u")
    assert type(caught.value) is error
    assert "test-key" not in str(caught.value)


def test_anthropic_without_credentials_is_a_wrong_setting(stub, clean_env):
    provider = anthropic_provider(stub, clean_env)

    def no_credentials(**kwargs):
        raise TypeError("Could not resolve authentication method.")

    clean_env.setattr(provider.client.messages, "create", no_credentials)
    with pytest.raises(LlmFatal, match="ANTHROPIC_API_KEY"):
        provider.complete("s", "u")
    assert stub.seen == []

    # 다른 TypeError 는 코드의 잘못이다. 키가 없다는 말로 바꾸지 않고 그대로 올린다.
    def wrong_call(**kwargs):
        raise TypeError("create() got an unexpected keyword argument")

    clean_env.setattr(provider.client.messages, "create", wrong_call)
    with pytest.raises(TypeError, match="unexpected keyword"):
        provider.complete("s", "u")


# ── 실행하는 명령: 설정만 바꿔 공급자를 바꾼다 ──────────────────────────


class Clock:
    """실행하는 명령이 보는 시각. 부를 때마다 5분씩 간다 (run_id 가 겹치지 않게)."""

    def __init__(self) -> None:
        self.minutes = 0

    def now(self) -> datetime:
        self.minutes += 5
        return (NOW + timedelta(minutes=self.minutes)).replace(tzinfo=None)


EXAMPLE_PROMPT = ("--prompt", "p1")  # 예시 묶음에는 p1 만 있다. 명령의 기본값은 팀이 쓰는 판이다 (T108)


def command(root, *more: str) -> int:
    return cli.main(["--data", "sample", "--root", str(root), *EXAMPLE_PROMPT, "--personas", ELDERS, "--conditions", DINNER, *more])


def runs_in(root) -> list[RunRecord]:
    folder = root / "engine" / "samples" / "runs"
    return [read_model(path / "run.json", RunRecord) for path in sorted(folder.iterdir())]


def test_same_command_runs_to_the_end_on_another_provider_by_settings_only(example_copy, stub, clean_env, capsys):
    clean_env.setattr(cli, "datetime", Clock())

    clean_env.setenv("ANTHROPIC_API_KEY", "test-key")
    clean_env.setenv("ANTHROPIC_BASE_URL", stub.url)
    clean_env.setenv("LLM_MODEL", "stub-model")
    stub.answer = anthropic_answers
    assert command(example_copy) == cli.EXIT_OK

    clean_env.setenv("LLM_PROVIDER", "openai-compatible")
    clean_env.setenv("LLM_MODEL", "local-model")
    clean_env.setenv("LLM_BASE_URL", stub.url + "/v1")
    stub.answer = openai_answers
    assert command(example_copy) == cli.EXIT_OK

    first, second = runs_in(example_copy)[-2:]
    assert (first.llm.provider, first.llm.model) == ("anthropic", "stub-model")
    assert (second.llm.provider, second.llm.model) == ("openai-compatible", "local-model")
    for record in (first, second):
        assert (record.status, record.llm.calls_new, record.counts.failed) == ("ok", 1, 0)
    assert [seen["path"] for seen in stub.seen] == ["/v1/messages", "/v1/chat/completions"]
    # 두 공급자가 받은 시스템 프롬프트와 요청은 같다.
    assert stub.seen[0]["body"]["system"] == stub.seen[1]["body"]["messages"][0]["content"]
    assert stub.seen[0]["body"]["messages"][0]["content"] == stub.seen[1]["body"]["messages"][1]["content"]
    # 두 공급자 모두 이 요청으로 만든 응답 스키마(고를 값이 든 것)를 받았다. 둘이 받은 스키마는 같다 (T103).
    request = ChoiceRequest.model_validate_json(stub.seen[1]["body"]["messages"][1]["content"])
    anthropic_schema = stub.seen[0]["body"]["output_config"]["format"]["schema"]
    openai_format = stub.seen[1]["body"]["response_format"]
    assert anthropic_schema == openai_format["json_schema"]["schema"] == response_schema(request)
    assert openai_format["json_schema"]["strict"] is True
    assert "enum" in json.dumps(anthropic_schema)
    assert "test-key" not in capsys.readouterr().out
    no_format_errors(example_copy)


def test_command_replays_earlier_runs_without_calling(example_copy, stub, clean_env, capsys):
    clean_env.setattr(cli, "datetime", Clock())
    clean_env.setenv("LLM_PROVIDER", "openai-compatible")
    clean_env.setenv("LLM_MODEL", "local-model")
    clean_env.setenv("LLM_BASE_URL", stub.url)
    stub.answer = openai_answers

    assert command(example_copy) == cli.EXIT_OK
    assert command(example_copy) == cli.EXIT_OK
    assert command(example_copy, "--replay-only") == cli.EXIT_OK

    assert len(stub.seen) == 1
    calls = [(record.llm.calls_new, record.llm.calls_replayed) for record in runs_in(example_copy)[-3:]]
    assert calls == [(1, 0), (0, 1), (0, 1)]
    assert "재생 1번" in capsys.readouterr().out


def test_default_prompt_is_a_file_the_team_has():
    """명령의 기본 판은 저장소의 `personas/prompts/` 에 있는 판이어야 한다. 없으면 `--prompt` 없이 돌린 명령이 모두 멈춘다 (T108)."""
    assert (REPO_ROOT / "personas" / "prompts" / f"{cli.DEFAULT_PROMPT}.md").is_file()


def test_command_without_prompt_reads_the_default_and_stops_where_it_is_missing(example_copy, stub, clean_env, capsys):
    """`--prompt` 를 적지 않으면 기본 판을 읽는다. 그 판이 없는 폴더에서는 다른 판으로 돌리지 않고 이유를 알리고 멈춘다 (T108)."""
    clean_env.setattr(cli, "datetime", Clock())
    clean_env.setenv("LLM_PROVIDER", "openai-compatible")
    clean_env.setenv("LLM_MODEL", "local-model")
    clean_env.setenv("LLM_BASE_URL", stub.url)
    stub.answer = openai_answers
    plain = ["--data", "sample", "--root", str(example_copy), "--personas", ELDERS, "--conditions", DINNER]
    default_file = example_copy / "personas" / "prompts" / f"{cli.DEFAULT_PROMPT}.md"

    # 예시 묶음에는 기본 판이 없다.
    assert not default_file.exists()
    before = runs_in(example_copy)
    assert cli.main(plain) == cli.EXIT_FAILED
    assert "프롬프트 파일이 없다" in capsys.readouterr().err
    assert stub.seen == [] and runs_in(example_copy) == before

    default_file.write_text("기본 판의 글", encoding="utf-8")
    assert cli.main(plain) == cli.EXIT_OK
    assert runs_in(example_copy)[-1].llm.prompt_version == cli.DEFAULT_PROMPT
    assert stub.seen[-1]["body"]["messages"][0]["content"] == "기본 판의 글"


def test_command_without_a_key_or_saved_answers_fails_the_visits_and_says_why(example_copy, clean_env, capsys):
    """키가 없어도 재생만 하는 명령은 끝까지 돈다. 저장된 응답이 없는 방문은 실패로 남는다."""
    clean_env.setattr(cli, "datetime", Clock())
    assert command(example_copy, "--replay-only") == cli.EXIT_OK
    record = runs_in(example_copy)[-1]
    assert (record.llm.provider, record.llm.calls_new, record.llm.call_limit) == ("anthropic", 0, 0)
    assert record.counts.model_dump() == {"visits": 1, "failed": 1}
    assert "실패한 방문이 있다" in capsys.readouterr().out


def test_command_says_when_the_limit_stopped_it(example_copy, stub, clean_env, capsys):
    clean_env.setattr(cli, "datetime", Clock())
    clean_env.setenv("LLM_PROVIDER", "openai-compatible")
    clean_env.setenv("LLM_MODEL", "local-model")
    clean_env.setenv("LLM_BASE_URL", stub.url)
    clean_env.setenv("LLM_CALL_LIMIT", "1")
    stub.answer = openai_answers

    code = cli.main(["--data", "sample", "--root", str(example_copy), *EXAMPLE_PROMPT, "--personas", ELDERS, "--conditions", DINNER, LUNCH])

    assert code == cli.EXIT_STOPPED_BY_LIMIT
    assert "호출 상한(1번)에 닿아 멈췄다" in capsys.readouterr().err
    assert runs_in(example_copy)[-1].status == "stopped_by_limit"

    # --limit 은 LLM_CALL_LIMIT 보다 앞선다. 남은 방문 셋을 새로 부르려면 상한 1 로는 모자란다.
    more = ("--conditions", DINNER, LUNCH, "meal-dinner-weekday", "meal-lunch-weekday")
    assert command(example_copy, *more, "--limit", "5") == cli.EXIT_OK
    last = runs_in(example_copy)[-1]
    assert (last.status, last.llm.calls_new, last.llm.calls_replayed, last.llm.call_limit) == ("ok", 3, 1, 5)

    # --limit 0 은 "부르지 않는다"는 뜻이다. 환경 변수의 값으로 돌아가지 않는다.
    asked = len(stub.seen)
    assert command(example_copy, "--conditions", "meal-dinner-weekend", "meal-lunch-weekend", "--personas", KIDS, "--limit", "0") == cli.EXIT_STOPPED_BY_LIMIT
    last = runs_in(example_copy)[-1]
    assert (last.status, last.llm.calls_new, last.llm.call_limit, last.counts.visits) == ("stopped_by_limit", 0, 0, 0)
    assert len(stub.seen) == asked
    capsys.readouterr()

    assert command(example_copy, "--scenario", "baseline", "--limit", "-1") == cli.EXIT_FAILED
    assert "--limit 은 0 이상의 정수다" in capsys.readouterr().err


def test_command_looks_in_given_answers_first_and_then_earlier_runs_first(example_copy, stub, clean_env):
    clean_env.setattr(cli, "datetime", Clock())
    clean_env.setenv("LLM_PROVIDER", "openai-compatible")
    clean_env.setenv("LLM_MODEL", "local-model")
    clean_env.setenv("LLM_BASE_URL", stub.url)
    stub.answer = openai_answers
    assert command(example_copy) == cli.EXIT_OK

    runs = example_copy / "engine" / "samples" / "runs"
    first = sorted(runs.iterdir())[-1]
    (saved_path,) = (first / "llm").glob("*.json")

    def copy_choosing(folder: Path, venue_id: str) -> None:
        """같은 요청에 다른 업장을 고른 저장 응답을 그 폴더에 둔다."""
        saved = load_json(saved_path)
        request = ChoiceRequest.model_validate(saved["request"])
        saved["response"] = first_option(request, venue_id).model_dump(mode="json")
        save_json(folder / saved_path.name, saved)

    # 이름으로 보아 먼저 돌린 실행의 응답이 먼저 쓰인다 (T121). 나중에 돌린 실행의 다른 답은 끼어들지 않는다.
    copy_choosing(runs / "20991231-000000-baseline" / "llm", "examplehotel-buffet")
    copy_choosing(runs / "20000101-000000-baseline" / "llm", "thebuffet")
    assert command(example_copy, "--replay-only") == cli.EXIT_OK
    rows = Played(example_copy, sorted(p for p in runs.iterdir() if (p / "run.json").is_file())[-1], {}).rows
    assert [row.venue_id for row in rows] == ["thebuffet"]

    # --answers 로 준 폴더는 앞선 실행보다 먼저 본다.
    given = example_copy.parent / "given"
    copy_choosing(given, "examplehotel-chinese")
    assert command(example_copy, "--replay-only", "--answers", str(given)) == cli.EXIT_OK
    rows = Played(example_copy, sorted(p for p in runs.iterdir() if (p / "run.json").is_file())[-1], {}).rows
    assert [row.venue_id for row in rows] == ["examplehotel-chinese"]
    assert len(stub.seen) == 1


def test_command_reads_only_the_env_file_of_the_folder_it_runs_in(example_copy, clean_env):
    """--root 로 가리킨 폴더의 .env 는 읽지 않는다. 그 파일이 주소를 바꾸면 이 PC 의 키가 다른 곳으로 간다."""
    loaded = []
    clean_env.setattr(cli, "load_dotenv", lambda path, **kwargs: loaded.append((Path(path), kwargs)))
    clean_env.setattr(cli, "datetime", Clock())
    (example_copy / ".env").write_text("LLM_BASE_URL=http://127.0.0.1:9\n", encoding="utf-8")
    assert command(example_copy, "--replay-only") == cli.EXIT_OK
    assert loaded == [(Path.cwd() / ".env", {})]


def test_command_stops_on_wrong_settings(example_copy, stub, clean_env, capsys):
    clean_env.setattr(cli, "datetime", Clock())
    clean_env.setenv("LLM_PROVIDER", "openai-compatible")
    assert command(example_copy) == cli.EXIT_FAILED
    assert "LLM_MODEL" in capsys.readouterr().err

    clean_env.setenv("LLM_MODEL", "local-model")
    clean_env.setenv("LLM_BASE_URL", stub.url)
    clean_env.setenv("LLM_API_KEY", "test-key")
    stub.answer = lambda path, body: (401, {"error": "bad key"})
    assert command(example_copy) == cli.EXIT_FAILED
    err = capsys.readouterr().err
    assert "LLM 을 부를 수 없어 멈췄다: 주소가 요청을 받지 않았다" in err
    assert "HTTP 401" in err
    assert "test-key" not in err
    assert runs_in(example_copy)[-1].status == "failed"


# ── 형식 검사: 어긋난 응답의 폴더 ───────────────────────────────────────


def errors_of(root) -> str:
    return "\n".join(str(p) for p in check(root))


def rejected_run(root) -> tuple[Played, str]:
    played = go(root, Fake(outside_candidates))
    return played, played.rows[0].request_hash


def test_check_refuses_a_rejected_reply_whose_request_was_edited(example_copy):
    played, request_hash = rejected_run(example_copy)
    path = played.run_dir / "llm_rejected" / f"{request_hash}.json"
    data = load_json(path)
    data["request"]["condition"]["adults"] += 1
    save_json(path, data)
    assert "request_hash 가 요청으로 다시 낸 값" in errors_of(example_copy)


def test_check_refuses_a_rejected_reply_from_another_model(example_copy):
    played, request_hash = rejected_run(example_copy)
    path = played.run_dir / "llm_rejected" / f"{request_hash}.json"
    data = load_json(path)
    data["model"] = "another-model"
    save_json(path, data)
    assert "provider 나 model 이 실행 기록과 다르다" in errors_of(example_copy)


def test_check_refuses_a_rejected_reply_under_another_name(example_copy):
    played, request_hash = rejected_run(example_copy)
    folder = played.run_dir / "llm_rejected"
    (folder / f"{request_hash}.json").rename(folder / "0123456789abcdef.json")
    errors = errors_of(example_copy)
    assert "llm_rejected/0123456789abcdef.json: 파일 이름이 request_hash 와 다르다" in errors


def test_check_reads_a_rejected_reply_strictly(example_copy):
    played, request_hash = rejected_run(example_copy)
    path = played.run_dir / "llm_rejected" / f"{request_hash}.json"
    data = load_json(path)
    data["usage"]["input_tokens"] = "11"
    save_json(path, data)
    assert f"llm_rejected/{request_hash}.json: usage.input_tokens" in errors_of(example_copy)


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda data: data.update(llm_call="replay"), "llm_call 이 어긋난 응답"),
        (lambda data: data.update(problems=["다른 이유"]), "fail_reason 이 어긋난 응답"),
        (lambda data: data["problems"].append("덧붙인 이유"), "fail_reason 이 어긋난 응답"),
    ],
)
def test_check_refuses_a_rejected_reply_that_disagrees_with_the_ledger(example_copy, change, error):
    played, request_hash = rejected_run(example_copy)
    path = played.run_dir / "llm_rejected" / f"{request_hash}.json"
    data = load_json(path)
    change(data)
    save_json(path, data)
    assert error in errors_of(example_copy)


def test_check_refuses_a_rejected_reply_without_problems(example_copy):
    played, request_hash = rejected_run(example_copy)
    path = played.run_dir / "llm_rejected" / f"{request_hash}.json"
    data = load_json(path)
    data["problems"] = []
    save_json(path, data)
    assert f"llm_rejected/{request_hash}.json" in errors_of(example_copy)


def test_check_refuses_a_rejected_reply_no_failed_visit_points_to(example_copy):
    played = go(example_copy, Fake())
    ok_hash = played.rows[0].request_hash
    other = go(example_copy, Fake(outside_candidates), now=later(5), condition_ids=(LUNCH,))
    lunch_hash = other.rows[0].request_hash
    # 실패한 방문이 없는 실행에 어긋난 응답을 끼워 넣는다.
    data = load_json(other.run_dir / "llm_rejected" / f"{lunch_hash}.json")
    save_json(played.run_dir / "llm_rejected" / f"{lunch_hash}.json", data)
    errors = errors_of(example_copy)
    assert f"어긋난 응답 llm_rejected/{lunch_hash}.json 을 가리키는 실패한 줄이 원장에 없다" in errors
    assert ok_hash not in errors


def test_check_refuses_the_same_request_in_both_folders(example_copy):
    played = go(example_copy, Fake())
    request_hash = played.rows[0].request_hash
    data = load_json(played.run_dir / "llm" / f"{request_hash}.json")
    del data["response"]
    save_json(played.run_dir / "llm_rejected" / f"{request_hash}.json", {**data, "llm_call": "new", "problems": ["끼워 넣은 것"]})
    assert f"같은 요청의 응답이 llm/{request_hash}.json 에도 있다" in errors_of(example_copy)


def test_check_refuses_other_files_in_the_rejected_folder(example_copy):
    played, _ = rejected_run(example_copy)
    (played.run_dir / "llm_rejected" / "notes.txt").write_text("메모", encoding="utf-8")
    assert "약속에 없는 파일이다" in errors_of(example_copy)


def test_check_refuses_a_rejected_reply_outside_a_run_folder(example_copy):
    played, request_hash = rejected_run(example_copy)
    data = load_json(played.run_dir / "llm_rejected" / f"{request_hash}.json")
    save_json(example_copy / "docs" / "kept.json", data)
    assert "'저장된 LLM 응답'의 모양인데 둘 수 없는 자리에 있다" in errors_of(example_copy)


@pytest.mark.parametrize(
    "change",
    [
        lambda record: record["llm"].update(stopped_by_limit=True),
        lambda record: record.update(status="stopped_by_limit"),
        lambda record: record["llm"].update(calls_new=record["llm"]["call_limit"] + 1),
    ],
)
def test_run_record_must_agree_with_itself_about_the_limit(doc, change):
    record = json.loads(json.dumps(doc.run))
    RunRecord.model_validate(record)
    change(record)
    with pytest.raises(ValidationError):
        RunRecord.model_validate(record)


def test_saved_and_rejected_replies_have_different_shapes(example_copy):
    played, request_hash = rejected_run(example_copy)
    raw = (played.run_dir / "llm_rejected" / f"{request_hash}.json").read_bytes()
    with pytest.raises(ValidationError):
        SavedResponse.model_validate_json(raw, strict=True)
