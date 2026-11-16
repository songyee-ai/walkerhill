"""화면에서 엔진을 돌린다 (T09 의 조건 입력, docs/PRD.md 9절).

엔진은 README 의 "시뮬레이션을 돌린다"와 같은 명령(`python -m engine`)으로 돌린다. 화면이 엔진의 안쪽을 따로 부르지 않아,
명령으로 돌린 것과 화면으로 돌린 것이 늘 같다. 결과는 엔진이 쓰는 실행 폴더에 남고, 화면은 그 폴더를 다시 읽어 보여 준다.

돌릴 자료는 두 가지다.
- 저장소: `data/`, `personas/`, `scenarios/`, `engine/conditions.json`. 페르소나와 프롬프트가 올라와야 돈다.
- 예시 사본: `tests/fixtures/example` 을 깃이 무시하는 `private/try-example` 에 베낀 것. 저장된 답이 들어 있어 키 없이 돈다.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

EXAMPLE_SOURCE = Path("tests") / "fixtures" / "example"
EXAMPLE_COPY = Path("private") / "try-example"
# 예시의 저장된 답은 이 두 업장만 읽어 받은 것이다 (README 의 "시뮬레이션을 돌린다"). 업장이 다르면 요청이 달라져 재생되지 않는다.
EXAMPLE_VENUES = ("geumryong", "examplehotel-chinese")
# 화면이 기다리는 가장 긴 시간(초). 넘으면 멈추고 알린다. 엔진의 호출 상한과 별개다.
RUN_TIMEOUT = 600

# 예시의 저장된 답을 받은 공급자와 모델. 저장된 답은 공급자·모델이 같아야 재생되므로(FORMATS 10절),
# 예시를 재생만 할 때는 이 PC 의 .env 가 다른 공급자를 가리켜도 이 값으로 돌린다.
# 엔진은 이미 있는 환경 변수를 .env 로 덮어쓰지 않는다 (python-dotenv 의 기본 동작).
EXAMPLE_LLM = {"LLM_PROVIDER": "anthropic", "LLM_MODEL": "claude-opus-5-5"}

RUN_DIR_RE = re.compile(r"^실행 폴더: (?P<path>.+)$", re.M)


@dataclass(frozen=True)
class DataRoot:
    """엔진이 자료를 읽고 결과를 쓸 폴더."""

    label: str
    path: Path
    is_example: bool


def data_roots(repo_root: Path) -> list[DataRoot]:
    return [
        DataRoot("저장소의 자료", repo_root, False),
        DataRoot(f"예시 사본 ({EXAMPLE_COPY.as_posix()}, 키 없이 연습)", repo_root / EXAMPLE_COPY, True),
    ]


def make_example_copy(repo_root: Path) -> Path:
    """예시 한 벌을 깃이 무시하는 private/ 에 베낀다. 이미 있으면 그대로 둔다 (앞서 돌린 실행을 지우지 않는다)."""
    target = repo_root / EXAMPLE_COPY
    if not target.exists():
        shutil.copytree(repo_root / EXAMPLE_SOURCE, target)
    return target


def _ids(folder: Path) -> list[str]:
    return sorted(path.stem for path in folder.glob("*.json")) if folder.is_dir() else []


@dataclass
class Choices:
    """폴더에 있어 고를 수 있는 것."""

    scenarios: list[str] = field(default_factory=list)
    personas: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    venues: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def choices(root: Path) -> Choices:
    """돌릴 수 있는 상황, 페르소나, 방문 조건, 업장, 프롬프트. 모자란 것은 `missing` 에 문장으로 적는다."""
    found = Choices(
        scenarios=_ids(root / "scenarios"),
        personas=_ids(root / "personas"),
        venues=_ids(root / "data" / "venues"),
        prompts=sorted(p.stem for p in (root / "personas" / "prompts").glob("*.md")),
    )
    bundle = root / "engine" / "conditions.json"
    if bundle.is_file():
        found.conditions = [c["condition_id"] for c in json.loads(bundle.read_text(encoding="utf-8"))["conditions"]]
    needs = [
        (found.scenarios, "상황 정의 (scenarios/*.json)"),
        (found.personas, "페르소나 정의 (personas/*.json)"),
        (found.conditions, "방문 조건 묶음 (engine/conditions.json)"),
        (found.venues, "업장 정의 (data/venues/*.json)"),
        (found.prompts, "프롬프트 (personas/prompts/*.md)"),
    ]
    found.missing = [name for values, name in needs if not values]
    return found


def has_private_summary(root: Path) -> bool:
    """기본 데이터로 돌리려면 집계 파일이 있어야 한다 (README)."""
    return (root / "private" / "base" / "summary.csv").is_file()


def key_ready(repo_root: Path) -> bool:
    """AI 를 새로 부를 수 있게 `.env` 가 채워져 있는가. 키의 값은 읽어서 있는지만 보고 어디에도 쓰지 않는다."""
    env_file = repo_root / ".env"
    if not env_file.is_file():
        return False
    env = {key: (value or "").strip() for key, value in dotenv_values(env_file).items()}
    if (env.get("LLM_PROVIDER") or "anthropic") == "anthropic":
        return bool(env.get("ANTHROPIC_API_KEY"))
    return bool(env.get("LLM_BASE_URL"))


def engine_command(
    root: Path,
    repo_root: Path,
    data_mode: str,
    scenario_id: str,
    prompt: str,
    persona_ids: list[str],
    condition_ids: list[str],
    venue_ids: list[str],
    call_llm: bool,
    baseline_run: str | None = None,
) -> list[str]:
    """README 와 같은 명령. 기준이 아닌 상황은 기준 실행의 페르소나와 조건으로 돌아 `--personas`, `--conditions` 를 적지 않는다.

    `baseline_run` 을 주면 그 기준 실행의 가중치로 돌린다. 주지 않으면 엔진이 가장 새 기준 실행을 고른다.
    """
    command = [sys.executable, "-m", "engine", "--data", data_mode, "--scenario", scenario_id, "--prompt", prompt]
    if root.resolve() != repo_root.resolve():
        command += ["--root", str(root)]
    if baseline_run and scenario_id != "baseline":
        command += ["--baseline", baseline_run]
    if scenario_id == "baseline":
        if persona_ids:
            command += ["--personas", *persona_ids]
        if condition_ids:
            command += ["--conditions", *condition_ids]
    if venue_ids:
        command += ["--venues", *venue_ids]
    if not call_llm:
        command.append("--replay-only")
    return command


# 엔진 명령이 끝날 때의 값 (README 의 "시뮬레이션을 돌린다").
EXIT_MEANING = {
    0: "끝까지 돌았습니다.",
    1: "돌리지 못했거나 AI 를 부를 수 없어 멈췄습니다.",
    2: "AI 호출 상한에 닿아 멈췄습니다. 다시 돌리면 받은 답은 재생하고 남은 방문만 부릅니다.",
}


@dataclass
class RunOutcome:
    exit_code: int
    run_dir: Path | None
    output: str

    @property
    def meaning(self) -> str:
        return EXIT_MEANING.get(self.exit_code, f"알 수 없는 끝 값 {self.exit_code} 입니다.")


def run_engine(
    command: list[str], repo_root: Path, timeout: int = RUN_TIMEOUT, env_overrides: dict[str, str] | None = None
) -> RunOutcome:
    """엔진 명령을 저장소 맨 위에서 돌린다 (`.env` 를 그 폴더에서 읽는다). `env_overrides` 는 .env 보다 먼저 쓴다."""
    try:
        done = subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_utf8_env() | (env_overrides or {}),
        )
    except subprocess.TimeoutExpired:
        return RunOutcome(1, None, f"{timeout}초 안에 끝나지 않아 멈췄습니다. 방문 수를 줄이거나 명령으로 돌려 주세요.")
    output = "\n".join(part for part in (done.stdout.strip(), done.stderr.strip()) if part)
    match = RUN_DIR_RE.search(done.stdout)
    return RunOutcome(done.returncode, Path(match["path"].strip()) if match else None, output)


def replay_env(is_example: bool, call_llm: bool) -> dict[str, str] | None:
    """예시를 재생만 할 때 쓸 공급자와 모델. 그 밖에는 None (이 PC 의 .env 를 따른다)."""
    return dict(EXAMPLE_LLM) if is_example and not call_llm else None


@dataclass
class Simulation:
    """간편 시뮬레이터의 한 번: 고른 조건으로 기준 상황을 돌리고, 그 가중치로 바뀐 상황을 돌린다."""

    baseline: RunOutcome
    scenario: RunOutcome | None

    @property
    def ok(self) -> bool:
        return self.scenario is not None and self.scenario.run_dir is not None


def simulate(
    root: Path,
    repo_root: Path,
    data_mode: str,
    scenario_id: str,
    persona_ids: list[str],
    condition_ids: list[str],
    venue_ids: list[str],
    call_llm: bool,
    prompt: str = "p1",
    is_example: bool = False,
) -> Simulation:
    """같은 페르소나·방문 조건·업장으로 기준과 상황을 차례로 돌린다 (PRD 7.2절: 상황은 기준의 가중치로 돈다).

    기준을 매번 새로 돌리는 것은, 고른 페르소나와 조건이 바뀌어도 늘 같은 것끼리 견주게 하려는 것이다.
    저장된 답을 재생하면 몇 초면 끝난다.
    """
    base_cmd = engine_command(root, repo_root, data_mode, "baseline", prompt, persona_ids, condition_ids, venue_ids, call_llm)
    env = replay_env(is_example, call_llm)
    baseline = run_engine(base_cmd, repo_root, env_overrides=env)
    if baseline.run_dir is None or baseline.exit_code != 0:
        return Simulation(baseline, None)
    scen_cmd = engine_command(
        root, repo_root, data_mode, scenario_id, prompt, [], [], venue_ids, call_llm, baseline_run=baseline.run_dir.name
    )
    return Simulation(baseline, run_engine(scen_cmd, repo_root, env_overrides=env))


def _utf8_env() -> dict[str, str]:
    """엔진의 한국어 출력이 윈도우에서 깨지지 않게 한다."""
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
