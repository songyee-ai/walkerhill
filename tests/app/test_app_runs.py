"""화면의 "돌리기"가 README 와 같은 엔진 명령을 만들고, 그 명령이 실제로 도는지 본다 (T09, app/runs.py)."""

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.results import load_run, visit_view  # noqa: E402
from app.runs import (  # noqa: E402
    DEFAULT_PROMPT,
    EXAMPLE_LLM,
    EXAMPLE_SOURCE,
    EXAMPLE_VENUES,
    ai_env,
    choices,
    default_prompt,
    engine_command,
    key_ready,
    make_example_copy,
    most_calls,
    replay_env,
    run_engine,
    summary_check,
)

EXAMPLE = REPO_ROOT / EXAMPLE_SOURCE


def _tail(command: list[str]) -> list[str]:
    """`python -m engine` 뒤의 인자."""
    assert command[1:3] == ["-m", "engine"]
    return command[3:]


def test_baseline_command_matches_readme():
    command = engine_command(
        EXAMPLE, REPO_ROOT, "sample", "baseline", "p1", ["family-elders"], ["meal-dinner-weekend"], list(EXAMPLE_VENUES), False
    )
    assert _tail(command) == [
        "--data", "sample", "--scenario", "baseline", "--prompt", "p1",
        "--root", str(EXAMPLE),
        "--personas", "family-elders",
        "--conditions", "meal-dinner-weekend",
        "--venues", *EXAMPLE_VENUES,
        "--replay-only",
    ]  # fmt: skip


def test_other_scenario_does_not_pass_personas_or_conditions():
    # 기준이 아닌 상황은 기준 실행의 페르소나와 조건으로 돈다 (README).
    command = engine_command(REPO_ROOT, REPO_ROOT, "sample", "competitor-x", "p1", ["a"], ["b"], [], True)
    tail = _tail(command)
    assert "--personas" not in tail and "--conditions" not in tail
    assert "--root" not in tail  # 저장소 자료는 지금 폴더라 --root 를 적지 않는다
    assert "--replay-only" not in tail  # AI 를 새로 부른다


def test_example_has_everything_to_run():
    found = choices(EXAMPLE)
    assert found.missing == []
    assert "baseline" in found.scenarios and "family-elders" in found.personas
    assert "meal-dinner-weekend" in found.conditions and "p1" in found.prompts


def test_missing_parts_are_named(tmp_path: Path):
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "baseline.json").write_text("{}", encoding="utf-8")
    missing = choices(tmp_path).missing
    assert not any("상황" in m for m in missing)
    assert any("페르소나" in m for m in missing) and any("프롬프트" in m for m in missing)


def test_key_ready_needs_a_filled_key(tmp_path: Path):
    assert not key_ready(tmp_path)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=\n", encoding="utf-8")
    assert not key_ready(tmp_path)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=test-value\n", encoding="utf-8")
    assert key_ready(tmp_path)
    (tmp_path / ".env").write_text("LLM_PROVIDER=openai-compatible\nLLM_BASE_URL=http://localhost:1\nLLM_MODEL=m\n", encoding="utf-8")
    assert key_ready(tmp_path)  # 이 PC 의 로컬 모델은 키가 없어도 된다


def test_key_ready_for_openai_needs_the_key_and_the_model(tmp_path: Path):
    """OpenAI 처럼 밖의 주소는 키와 모델이 있어야 켜진다. 주소만 있으면 부르는 순간 실패한다 (11-16, T103)."""
    env = tmp_path / ".env"
    openai = "LLM_PROVIDER=openai-compatible\nLLM_BASE_URL=https://api.openai.com/v1\n"
    env.write_text(openai, encoding="utf-8")
    assert not key_ready(tmp_path)
    env.write_text(openai + "LLM_MODEL=m\n", encoding="utf-8")
    assert not key_ready(tmp_path)  # 키가 없다
    env.write_text(openai + "LLM_MODEL=m\nLLM_API_KEY=\n", encoding="utf-8")
    assert not key_ready(tmp_path)  # 키가 비었다
    env.write_text(openai + "LLM_API_KEY=test-value\n", encoding="utf-8")
    assert not key_ready(tmp_path)  # 모델이 없다 (엔진이 멈춘다)
    env.write_text(openai + "LLM_MODEL=m\nLLM_API_KEY=test-value\n", encoding="utf-8")
    assert key_ready(tmp_path)
    env.write_text("LLM_PROVIDER=openai-compatible\nLLM_BASE_URL=http://localhost:1\n", encoding="utf-8")
    assert not key_ready(tmp_path)  # 로컬 모델이어도 모델 이름은 있어야 한다
    # 엔진이 멈출 설정이면 키가 있어도 켜지 않는다.
    filled = "LLM_MODEL=m\nLLM_API_KEY=test-value\n"
    for wrong in (
        "LLM_PROVIDER=openai\nLLM_BASE_URL=https://api.openai.com/v1\n",  # 공급자 이름의 오타
        "LLM_PROVIDER=openai-compatible\nLLM_BASE_URL=http://example.com/v1\n",  # 이 PC 가 아닌데 http
        "LLM_PROVIDER=openai-compatible\nLLM_BASE_URL=api.openai.com/v1\n",  # 주소에 https:// 가 없다
        "LLM_PROVIDER=openai-compatible\nLLM_BASE_URL=https://api.openai.com/v1\nLLM_RESPONSE_FORMAT=yaml\n",
    ):
        env.write_text(wrong + filled, encoding="utf-8")
        assert not key_ready(tmp_path), wrong


def test_example_copy_keeps_runs_and_refreshes_example_files(tmp_path: Path):
    shutil.copytree(EXAMPLE, tmp_path / EXAMPLE_SOURCE)
    target = make_example_copy(tmp_path)
    marker = target / "engine" / "samples" / "runs" / "남겨 둘 실행"
    marker.mkdir()
    # 예시의 형식이 바뀌기 전에 만든 사본 (11-19 T210 에 집계 파일에 people 열이 생겼다. T124 에서 찾음)
    summary = target / "data" / "samples" / "base_summary.csv"
    summary.write_text("customer_group,venue_id\n", encoding="utf-8")
    make_example_copy(tmp_path)
    assert marker.exists()  # 앞서 돌린 실행은 남는다
    assert summary.read_bytes() == (tmp_path / EXAMPLE_SOURCE / "data" / "samples" / "base_summary.csv").read_bytes()


def test_engine_runs_from_the_screen_without_a_key(tmp_path: Path):
    # 화면의 "돌리기"와 같은 명령으로 예시 사본을 돌리면, 저장된 답을 재생해 새 실행 폴더가 생기고 결과를 읽을 수 있다.
    root = tmp_path / "try-example"
    shutil.copytree(EXAMPLE, root)
    command = engine_command(
        root, REPO_ROOT, "sample", "baseline", "p1", ["family-elders"], ["meal-dinner-weekend"], list(EXAMPLE_VENUES), False
    )
    # 화면처럼, 예시를 재생만 할 때는 이 PC 의 .env 와 상관없이 예시를 받은 공급자·모델로 돌린다.
    outcome = run_engine(command, REPO_ROOT, timeout=120, env_overrides=replay_env(True, False))
    assert outcome.exit_code == 0, outcome.output
    assert outcome.run_dir is not None and (outcome.run_dir / "run.json").is_file()
    view = visit_view(load_run(outcome.run_dir), "family-elders", "meal-dinner-weekend")
    assert view.venue == "금룡" and view.llm_call == "replay"


def test_engine_failure_is_reported(tmp_path: Path):
    # 기준 실행이 없는 곳에서 다른 상황을 돌리면 엔진이 1 로 끝나고 이유를 남긴다.
    root = tmp_path / "empty"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("runs"))
    command = engine_command(root, REPO_ROOT, "sample", "competitor-chinese-discount", "p1", [], [], [], False)
    outcome = run_engine(command, REPO_ROOT, timeout=120)
    assert outcome.exit_code == 1
    assert outcome.run_dir is None
    assert "돌리지 못했다" in outcome.output


def test_replay_env_only_for_example_replay():
    # 예시의 저장된 답은 Claude 로 받은 것이라, .env 가 다른 공급자여도 예시 재생은 그 값으로 돌려야 재생된다.
    assert replay_env(True, False) == EXAMPLE_LLM
    assert replay_env(True, True) is None  # AI 를 새로 부를 때는 .env 를 따른다
    assert replay_env(False, False) is None  # 팀 자료는 .env 를 따른다


def test_key_ready_for_claude_code_needs_the_program_and_the_model(tmp_path: Path):
    """자기 Claude 구독으로 Claude Code 를 부르는 공급자(T104)는 키가 없다. 실행 파일과 모델이 있으면 켜진다."""
    program = tmp_path / "claude.exe"
    program.write_text("", encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text(f"LLM_PROVIDER=claude-code\nLLM_MODEL=m\nCLAUDE_CODE_PATH={program}\n", encoding="utf-8")
    assert key_ready(tmp_path)
    env.write_text(f"LLM_PROVIDER=claude-code\nCLAUDE_CODE_PATH={program}\n", encoding="utf-8")
    assert not key_ready(tmp_path)  # 모델이 없다
    env.write_text(f"LLM_PROVIDER=claude-code\nLLM_MODEL=m\nCLAUDE_CODE_PATH={tmp_path / 'none.exe'}\n", encoding="utf-8")
    assert not key_ready(tmp_path)  # 실행 파일이 없다


def test_default_prompt_is_p3_and_falls_back_to_p1_for_the_example():
    # 팀 자료는 엔진 명령과 같은 판으로 처음 고른다 (T108, 11-17 T113 으로 p3). 예시 묶음에는 p1 만 있어 p1 로 돌아야 저장된 답이 재생된다.
    assert DEFAULT_PROMPT == "p3"
    assert default_prompt(["p1", "p2", "p3"]) == "p3"
    assert default_prompt(choices(EXAMPLE).prompts) == "p1"
    assert default_prompt(["p4"]) == "p4"
    assert default_prompt(choices(REPO_ROOT).prompts) == "p3"


def test_ai_menu_offers_only_the_ai_this_pc_can_call(tmp_path: Path):
    """화면의 AI 메뉴 (11-17): 고른 AI 의 공급자와 모델을 그 실행에만 넘긴다. 모델은 .env 에서 읽는다."""
    assert ai_env(tmp_path, "claude") is None  # .env 가 없다
    program = tmp_path / "claude.exe"
    program.write_text("", encoding="utf-8")
    lines = ["LLM_PROVIDER=claude-code", "LLM_MODEL=claude-test", f"CLAUDE_CODE_PATH={program}"]
    base = "\n".join([*lines, "LLM_BASE_URL=https://api.openai.com/v1", ""])
    env = tmp_path / ".env"
    env.write_text(base, encoding="utf-8")
    assert ai_env(tmp_path, "claude") == {"LLM_PROVIDER": "claude-code", "LLM_MODEL": "claude-test"}
    assert ai_env(tmp_path, "openai") is None  # OpenAI 의 모델과 키가 없다
    env.write_text(base + "OPENAI_MODEL=gpt-test\n", encoding="utf-8")
    assert ai_env(tmp_path, "openai") is None  # 키가 없다
    env.write_text(base + "OPENAI_MODEL=gpt-test\nLLM_API_KEY=not-a-real-key\n", encoding="utf-8")
    assert ai_env(tmp_path, "openai") == {"LLM_PROVIDER": "openai-compatible", "LLM_MODEL": "gpt-test"}
    assert ai_env(tmp_path, "claude") == {"LLM_PROVIDER": "claude-code", "LLM_MODEL": "claude-test"}
    assert ai_env(tmp_path, "nothing") is None


def test_summary_check_matches_the_engine_receiver(tmp_path: Path, monkeypatch):
    """기본 데이터의 요약을 보내도 되는가 (T115): `.env` 의 BASE_PROFILE_CONFIRMED_FOR 와 엔진의 receiver_of 를 견준다."""
    monkeypatch.delenv("BASE_PROFILE_CONFIRMED_FOR", raising=False)
    program = tmp_path / "claude.exe"
    program.write_text("", encoding="utf-8")
    lines = ["LLM_PROVIDER=claude-code", "LLM_MODEL=claude-test", f"CLAUDE_CODE_PATH={program}", "LLM_BASE_URL=https://api.openai.com/v1"]
    base = "\n".join([*lines, ""])
    env = tmp_path / ".env"
    env.write_text(base, encoding="utf-8")
    claude = {"LLM_PROVIDER": "claude-code", "LLM_MODEL": "claude-test"}
    openai = {"LLM_PROVIDER": "openai-compatible", "LLM_MODEL": "gpt-test"}
    assert summary_check(tmp_path, claude) == (False, "claude-code")  # 비어 있으면 확인 전
    env.write_text(base + "BASE_PROFILE_CONFIRMED_FOR=claude-code\n", encoding="utf-8")
    assert summary_check(tmp_path, claude) == (True, "claude-code")
    # 확인 값은 하나라 다른 받는 곳(OpenAI)은 따로 확인해야 한다. OpenAI 는 주소의 호스트까지가 이름이다
    assert summary_check(tmp_path, openai) == (False, "openai-compatible:api.openai.com")
    # 엔진처럼 이미 있는 환경 변수가 .env 보다 먼저다
    monkeypatch.setenv("BASE_PROFILE_CONFIRMED_FOR", "openai-compatible:api.openai.com")
    assert summary_check(tmp_path, openai) == (True, "openai-compatible:api.openai.com")
    assert summary_check(tmp_path, claude)[0] is False


def test_most_calls_counts_both_runs_and_every_month():
    """버튼을 누르기 전에 보이는 예상 호출 수: 페르소나 × 방문 조건 × 기본·변수 2번 × 달 수."""
    assert most_calls(1, 2, 0) == 4  # 일 년 전체는 한 번
    assert most_calls(6, 2, 1) == 24
    assert most_calls(6, 2, 4) == 96


def test_month_goes_to_the_engine_only_when_chosen():
    """화면의 계절(달)은 엔진의 --month 로 넘긴다 (T112). 고르지 않으면 적지 않아 저장된 답이 그대로 재생된다."""
    args = (EXAMPLE, REPO_ROOT, "sample", "baseline", "p2", ["family-elders"], ["meal-dinner-weekend"], [], False)
    assert "--month" not in engine_command(*args)
    tail = _tail(engine_command(*args, month=12))
    assert tail[tail.index("--month") + 1] == "12"
