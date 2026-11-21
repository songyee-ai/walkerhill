"""시나리오 결과 묶음: 한 번 돌린 시나리오의 달마다 (기준 실행, 상황 실행) 짝을 적어 둔다 (T130).

엔진의 실행 기록에는 `scenario_id`·`month`·`weights_from` 만 있어, 같은 시나리오를 여러 달로 돌리면 어느 실행들이
한 결과인지와 기간의 순서(해를 넘으면 12월 → 1월)를 알 수 없다 (docs/FORMATS.md 10.1절 "달의 순서는 화면이 정한다").
그래서 화면이 시나리오를 돌릴 때마다 묶음 하나를 `private/results/<result_id>.json` 에 쓴다. 깃이 무시하는 곳이다.

묶음이 없는 옛 실행(11-21 전에 돌린 것, 엔진 명령으로 직접 돌린 것)은 상황 실행 하나를 한 달짜리 결과로 본다.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from app.results import list_runs, run_sources
from engine.formats import RunRecord, read_model

RESULTS_FOLDER = Path("private") / "results"


@dataclass(frozen=True)
class Pair:
    """한 달의 기준 실행과 상황 실행 (실행 폴더 이름)."""

    month: int | None
    baseline: str
    scenario: str


@dataclass
class ResultRecord:
    """시나리오 결과 하나. `runs` 는 실행 폴더들이 든 곳(저장소 맨 위에서 본 경로)이다."""

    result_id: str
    scenario_id: str
    runs: str
    data_mode: str
    pairs: list[Pair]
    created_at: str
    # 묶음 파일 없이 상황 실행 하나에서 찾아낸 결과인가 (옛 실행)
    found_from_run: bool = field(default=False)

    @property
    def months(self) -> list[int | None]:
        return [p.month for p in self.pairs]


def _relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def runs_path(record: ResultRecord, repo_root: Path) -> Path:
    path = Path(record.runs)
    return path if path.is_absolute() else repo_root / path


def data_root(record: ResultRecord, repo_root: Path) -> Path:
    """그 실행들을 낸 자료의 맨 위 (상황 정의 `scenarios/`, 업장 `data/venues/` 가 있는 곳).

    엔진은 가상 예시 값이면 `<맨 위>/engine/samples/runs`, 기본 데이터면 `<맨 위>/private/runs` 에 쓴다 (engine.runner.runs_folder).
    """
    folder = runs_path(record, repo_root)
    return folder.parents[2] if record.data_mode == "sample" else folder.parents[1]


def new_record(repo_root: Path, runs: Path, data_mode: str, scenario_id: str, pairs: list[Pair]) -> ResultRecord:
    """방금 돌린 실행들로 묶음을 만든다. 이름은 첫 달의 상황 실행 이름이다 (`<날짜>-<시각>-<scenario_id>`)."""
    if not pairs:
        raise ValueError("묶을 실행이 없다")
    return ResultRecord(
        result_id=pairs[0].scenario,
        scenario_id=scenario_id,
        runs=_relative(runs, repo_root),
        data_mode=data_mode,
        pairs=list(pairs),
        created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def save_record(repo_root: Path, record: ResultRecord) -> Path:
    folder = repo_root / RESULTS_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{record.result_id}.json"
    data = asdict(record)
    data.pop("found_from_run")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_record(path: Path) -> ResultRecord | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pairs = [Pair(p["month"], p["baseline"], p["scenario"]) for p in data["pairs"]]
        return ResultRecord(data["result_id"], data["scenario_id"], data["runs"], data["data_mode"], pairs, data["created_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _complete(record: ResultRecord, repo_root: Path) -> bool:
    """묶음의 실행 폴더가 모두 남아 있는가. 지운 결과는 목록에서 뺀다."""
    folder = runs_path(record, repo_root)
    return all((folder / p.baseline / "run.json").is_file() and (folder / p.scenario / "run.json").is_file() for p in record.pairs)


def read_record(run_dir: Path) -> RunRecord:
    """실행 기록만 읽는다. 원장과 저장된 답은 읽지 않아 목록을 빨리 만든다."""
    return read_model(run_dir / "run.json", RunRecord)


def _from_run(repo_root: Path, folder: Path, run_id: str) -> ResultRecord | None:
    """묶음이 없는 상황 실행 하나를 한 달짜리 결과로 본다."""
    try:
        record = read_record(folder / run_id)
    except (OSError, ValueError):
        return None
    if record.weights_from is None or not (folder / record.weights_from / "run.json").is_file():
        return None
    return ResultRecord(
        result_id=run_id,
        scenario_id=record.scenario_id,
        runs=_relative(folder, repo_root),
        data_mode=record.data_mode,
        pairs=[Pair(record.month, record.weights_from, run_id)],
        created_at=record.created_at.isoformat(timespec="seconds"),
        found_from_run=True,
    )


def list_records(repo_root: Path) -> list[ResultRecord]:
    """저장된 결과. 새것이 앞에 온다. 묶음에 든 상황 실행은 따로 한 달짜리 결과로 다시 세지 않는다."""
    saved = []
    folder = repo_root / RESULTS_FOLDER
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            record = _read_record(path)
            if record is not None and _complete(record, repo_root):
                saved.append(record)
    taken = {(runs_path(r, repo_root).resolve(), p.scenario) for r in saved for p in r.pairs}
    found = []
    for source in run_sources(repo_root):
        for run_id in list_runs(source.folder):
            if run_id.endswith("-baseline") or (source.folder.resolve(), run_id) in taken:
                continue
            record = _from_run(repo_root, source.folder, run_id)
            if record is not None:
                found.append(record)
    return sorted(saved + found, key=lambda r: r.created_at, reverse=True)


def find_record(repo_root: Path, result_id: str | None) -> ResultRecord | None:
    """주소의 결과. 없으면 가장 새 결과."""
    records = list_records(repo_root)
    if result_id:
        for record in records:
            if record.result_id == result_id:
                return record
    return records[0] if records else None
