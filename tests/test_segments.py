"""페르소나의 무리 `segment` (T220, docs/FORMATS.md 5절의 "무리").

개선 3단계(PRD 8절)의 경쟁 호텔 고객·가끔만 쓰는 사람의 페르소나를 저장소에 올려도, 3단계가 켜기 전까지는
지금의 실행(돌리는 페르소나, 가중치, 요청, 입력의 해시)과 기본 데이터에 맞춰 보는 것(요약, 보정 대조, 상수 추정)이 그대로인지 본다.
경쟁 호텔 고객 페르소나는 예시 묶음의 페르소나를 베껴 무리만 바꾼 지어낸 것이다.
"""

from datetime import timedelta
from pathlib import Path

import pytest

import engine.__main__ as cli
from engine import runner
from engine.answers import save_answer
from engine.calibration import calibrate
from engine.estimate import estimate, scored_visits
from engine.formats import Persona, read_model
from engine.formats.persona import merge_persona_layers
from engine.runner import load_inputs, run, skipped_by_segment
from engine.weights import average_parties, decide_weights, group_people
from tests.conftest import EXAMPLE_ROOT, load_json, save_json
from tests.test_calibration import both, ready
from tests.test_check_rules import found, messages
from tests.test_engine import DINNER, LUNCH, MODEL, NOW, PROVIDER, Played, answer, persona_file, requests_in
from tests.test_estimate import add_thebuffet_people, ledger_row, scored_run
from tests.test_llm import clean_env  # noqa: F401 (픽스처)
from tests.test_weights import GROUP, to_private
from tools.check_formats import check

ELDERS, KIDS = "family-elders", "family-kids"
RIVAL_FAMILY, RIVAL_COUPLE = "rival-family", "rival-couple"


def add_rival(root: Path, persona_id: str = RIVAL_FAMILY, source: str = ELDERS, share: float = 0.6, segment: str = "rival") -> None:
    """예시 페르소나 하나를 베껴 다른 무리의 페르소나로 만든다 (지어낸 것). 고객군은 원래 것(가족·친족) 그대로다."""
    data = load_json(persona_file(root, source))
    data.update(persona_id=persona_id, name="경쟁 호텔을 평소에 다니는 손님", segment=segment)
    data["share_in_group"].update(value=share)
    save_json(persona_file(root, persona_id), data)


# ── 형식 ────────────────────────────────────────────────────────────────


def test_segment_defaults_to_walkerhill_without_writing_it():
    for path in (EXAMPLE_ROOT / "personas").glob("*.json"):
        assert "segment" not in load_json(path)
        assert read_model(path, Persona).segment == "walkerhill"


def test_unknown_segment_is_a_format_error(example_copy):
    add_rival(example_copy, segment="rivel")
    problems = check(example_copy)
    assert found(problems, "segment"), messages(problems)


def test_writing_the_default_segment_is_a_warning(example_copy):
    """`"segment": "walkerhill"` 을 적으면 요청이 달라져 받아 둔 답이 재생되지 않아 주의로 알린다. 적지 않은 파일은 주의가 없다."""
    assert not found(check(example_copy), "segment 가 walkerhill 이면 적지 않는다", level="warning")
    path = persona_file(example_copy, ELDERS)
    save_json(path, {**load_json(path), "segment": "walkerhill"})
    problems = check(example_copy)
    assert found(problems, "segment 가 walkerhill 이면 적지 않는다", level="warning"), messages(problems)
    assert not found(problems, "segment 가 walkerhill 이면 적지 않는다"), messages(problems)  # 오류는 아니다


def test_private_layer_cannot_change_the_segment(doc):
    with pytest.raises(ValueError, match="약속에 없는 키"):
        merge_persona_layers(doc.persona, {**doc.persona_private, "segment": "rival"})


def test_shares_add_up_per_segment_and_group(example_copy):
    """경쟁 호텔 고객의 가족·친족 몫은 워커힐 고객의 가족·친족 몫(0.5 + 0.5)에 더해지지 않는다."""
    add_rival(example_copy, RIVAL_FAMILY, ELDERS, share=0.6)
    problems = check(example_copy)
    assert not found(problems, "1 을 넘을 수 없다"), messages(problems)
    assert found(problems, f"고객군 '{GROUP}'(경쟁 호텔 고객)의 몫을 더하면 0.6 다", level="warning"), messages(problems)
    assert found(check(example_copy, strict=True), "(경쟁 호텔 고객)의 몫을 더하면 0.6 다")

    add_rival(example_copy, RIVAL_COUPLE, KIDS, share=0.6)
    problems = check(example_copy)
    assert found(problems, f"고객군 '{GROUP}'(경쟁 호텔 고객)의 몫을 더하면 1.2 다. 1 을 넘을 수 없다"), messages(problems)
    assert not any("(워커힐 고객)" in str(p) for p in problems), messages(problems)


# ── 3단계 전에는 워커힐 고객만 돌린다 ─────────────────────────────────


def test_rival_personas_leave_the_baseline_run_as_it_was(example_copy):
    """경쟁 호텔 고객 페르소나를 올려도 기준 실행의 페르소나, 가중치, 입력의 해시, 요청이 그대로이고 저장된 답이 모두 재생된다."""
    conditions = [DINNER, LUNCH]
    answers = example_copy.parent / "answers"
    requests = requests_in(example_copy, None, conditions)
    for request in requests.values():
        save_answer(answers, PROVIDER, MODEL, request, answer(request, None), NOW)

    def baseline(now) -> Played:
        settings = dict(provider=PROVIDER, model=MODEL, prompt_version="p1", answers=[answers], engine_commit="0000000")
        return Played(example_copy, run(example_copy, data_mode="sample", now=now, condition_ids=conditions, **settings), requests)

    before = baseline(NOW)
    add_rival(example_copy, RIVAL_FAMILY, ELDERS, share=0.6)
    add_rival(example_copy, RIVAL_COUPLE, KIDS, share=0.4)
    after = baseline(NOW + timedelta(hours=1))

    assert after.record.persona_ids == before.record.persona_ids == [ELDERS, KIDS]
    assert after.record.weights == before.record.weights
    assert after.record.inputs == before.record.inputs
    assert [r.request_hash for r in after.rows] == [r.request_hash for r in before.rows]
    assert (after.record.counts.failed, after.record.llm.calls_new) == (0, 0)
    assert after.record.llm.calls_replayed == len(requests)
    assert requests_in(example_copy, None, conditions).keys() == requests.keys()
    assert skipped_by_segment(example_copy) == {"rival": [RIVAL_COUPLE, RIVAL_FAMILY]}
    # 기준 실행 뒤에 올렸어도 그 기준 실행으로 상황을 돌릴 수 있다 (입력이 달라졌다고 멈추지 않는다).
    run(
        example_copy,
        data_mode="sample",
        now=NOW + timedelta(hours=2),
        provider=PROVIDER,
        model=MODEL,
        prompt_version="p1",
        answers=[answers],
        scenario_id="competitor-chinese-discount",
        weights_from=before.record.run_id,
        engine_commit="0000000",
    )
    # 무리마다 몫이 1 이라 형식 검사도 통과한다 (새로 쓴 실행 폴더까지).
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_asking_for_a_rival_persona_stops_before_stage_three(example_copy):
    add_rival(example_copy)
    with pytest.raises(ValueError, match="3단계"):
        load_inputs(example_copy, "sample", persona_ids=[ELDERS, RIVAL_FAMILY])


def test_run_command_reports_the_personas_left_out_by_segment(example_copy, clean_env, capsys):  # noqa: F811
    add_rival(example_copy)
    add_rival(example_copy, "occasional-family", KIDS, share=1, segment="occasional")
    cli.main(["--data", "sample", "--root", str(example_copy), "--prompt", "p1", "--replay-only", "--personas", ELDERS, "--conditions", DINNER])
    out = capsys.readouterr().out
    assert f"3단계 전이라 돌리지 않은 경쟁 호텔 고객 페르소나 1명: {RIVAL_FAMILY}" in out
    assert "3단계 전이라 돌리지 않은 가끔만 쓰는 사람 페르소나 1명: occasional-family" in out


# ── 기본 데이터와 맞춰 보는 것은 워커힐 고객만 ──────────────────────────


def test_base_profile_and_weights_use_only_walkerhill_personas(example_copy, monkeypatch):
    """3단계가 다른 무리를 켠 뒤에도 기본 데이터의 요약, 평균 일행 수, 가중치는 워커힐 고객 페르소나로만 낸다."""
    add_rival(example_copy)
    to_private(example_copy)
    assert sorted(load_inputs(example_copy, "private", base_profile_mode="bucketed").personas) == [ELDERS, KIDS]

    monkeypatch.setattr(runner, "RUN_SEGMENTS", frozenset({"walkerhill", "rival"}))
    inputs = load_inputs(example_copy, "private", base_profile_mode="bucketed")
    assert RIVAL_FAMILY in inputs.personas
    assert "base_profile" in inputs.persona_json[ELDERS] and "base_profile" in inputs.persona_json[KIDS]
    assert "base_profile" not in inputs.persona_json[RIVAL_FAMILY]

    everyone = list(inputs.personas.values())
    walkerhill = [p for p in everyone if p.segment == "walkerhill"]
    assert average_parties(everyone) == average_parties(walkerhill)
    conditions = [inputs.conditions.condition(DINNER)]
    people = group_people(inputs.summary, conditions, inputs.conditions.assumed_splits, inputs.venues, average_parties(walkerhill))
    weights = decide_weights(everyone, people, [DINNER], "private")
    assert weights == decide_weights(walkerhill, people, [DINNER], "private")
    assert RIVAL_FAMILY not in weights.persona_weight


def test_calibration_ignores_rival_personas(example_copy):
    ready(example_copy)
    played = both(example_copy)
    _, before, _ = calibrate(example_copy, "sample", played.run_dir.name)
    add_rival(example_copy)
    _, after, not_run = calibrate(example_copy, "sample", played.run_dir.name)
    assert not_run == {}
    assert after == before
    assert after.groups[GROUP].personas == 2


def test_constant_estimation_ignores_rival_personas(example_copy):
    add_thebuffet_people(example_copy)
    first = scored_run(example_copy)
    _, before, _, _ = estimate(example_copy, "sample", first.name)
    add_rival(example_copy, share=1)
    _, after, _, _ = estimate(example_copy, "sample", first.name)
    assert after == before


def test_scored_visits_leave_out_rival_personas():
    elders = read_model(EXAMPLE_ROOT / "personas" / f"{ELDERS}.json", Persona)
    rival = elders.model_copy(update={"persona_id": RIVAL_FAMILY, "segment": "rival"})
    rows = [
        ledger_row(ELDERS, DINNER, "walkerhill", "geumryong", 60),
        ledger_row(ELDERS, DINNER, "none", None, 40),
        ledger_row(RIVAL_FAMILY, DINNER, "walkerhill", "geumryong", 90),
        ledger_row(RIVAL_FAMILY, DINNER, "none", None, 10),
    ]
    visits, skipped = scored_visits(rows, {ELDERS: elders, RIVAL_FAMILY: rival})
    assert skipped == 0
    assert [v.places for v in visits] == [{"geumryong": (60, 1.0), None: (40, 1.0)}]
