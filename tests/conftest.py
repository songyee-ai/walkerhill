"""테스트가 함께 쓰는 것.

- EXAMPLE_ROOT: 형식 문서의 예시를 파일로 만든 한 벌 (tests/fixtures/example).
- example_copy: 그 한 벌을 임시 폴더에 베낀 것. 일부러 망가뜨려 검사 도구가 잡는지 볼 때 쓴다.
- doc: 형식 문서(docs/FORMATS.md)의 예시를 읽은 것.
"""

import csv
import io
import json
import re
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = REPO_ROOT / "tests" / "fixtures" / "example"
FORMATS_DOC = REPO_ROOT / "docs" / "FORMATS.md"

BASELINE_RUN = "20261117-101500-baseline"
COMPETITOR_RUN = "20261117-103000-competitor-chinese-discount"


class DocExamples:
    """형식 문서의 예시 블록."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.json = [json.loads(b) for b in re.findall(r"```json\n(.*?)```", text, flags=re.S)]
        self.csv = [
            list(csv.DictReader(io.StringIO(b))) for b in re.findall(r"```csv\n(.*?)```", text, flags=re.S)
        ]

    def one(self, predicate) -> dict:
        found = [o for o in self.json if predicate(o)]
        assert len(found) == 1, f"문서에서 예시를 하나만 찾아야 하는데 {len(found)}개다"
        return found[0]

    @property
    def venues(self) -> list[dict]:
        return [o for o in self.json if "venue_id" in o and "products" in o]

    @property
    def vocab(self) -> dict:
        return self.one(lambda o: "reasons_chosen" in o and "purpose" in o)

    @property
    def persona(self) -> dict:
        return self.one(lambda o: "persona_id" in o and "visit" in o)

    @property
    def persona_private(self) -> dict:
        return self.one(lambda o: "persona_id" in o and "visit" not in o and "candidates" not in o)

    @property
    def conditions(self) -> dict:
        return self.one(lambda o: "conditions" in o)

    @property
    def scenarios(self) -> list[dict]:
        return [o for o in self.json if "scenario_id" in o and "changes" in o]

    @property
    def request(self) -> dict:
        return self.one(lambda o: "candidates" in o)

    @property
    def response(self) -> dict:
        return self.one(lambda o: "choice" in o and "reason_labels" in o)

    @property
    def run(self) -> dict:
        return self.one(lambda o: "run_id" in o and "weights" in o)

    @property
    def calibration(self) -> dict:
        return self.one(lambda o: "criteria" in o)

    @property
    def validation(self) -> dict:
        return self.one(lambda o: "min_reviews" in o)

    @property
    def reviews(self) -> list[dict]:
        return self.csv[0]

    @property
    def summary(self) -> list[dict]:
        return self.csv[1]

    @property
    def ledger(self) -> list[dict]:
        return self.csv[2]


@pytest.fixture(scope="session")
def doc() -> DocExamples:
    return DocExamples(FORMATS_DOC.read_text(encoding="utf-8"))


@pytest.fixture
def example_copy(tmp_path: Path) -> Path:
    target = tmp_path / "example"
    shutil.copytree(EXAMPLE_ROOT, target)
    return target


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def save_csv(path: Path, rows: list[dict[str, str]], bom: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
