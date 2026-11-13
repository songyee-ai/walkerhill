"""데이터 파일이 형식 약속(docs/FORMATS.md)에 맞는지 검사한다.

쓰는 법 (저장소 맨 위에서):

    uv run python -m tools.check_formats            # 저장소의 데이터 파일
    uv run python -m tools.check_formats --strict   # 다 만든 뒤의 기준으로 (주의도 오류로 본다)
    uv run python -m tools.check_formats --root tests/fixtures/example --strict

보는 것은 네 가지다.

1. 파일 하나하나가 약속한 모양인가 (engine/formats 의 모델). JSON 은 적힌 그대로 엄격하게 본다.
2. 파일끼리 서로 가리키는 식별자가 실제로 있는가. 원장이 저장된 응답과 맞는가.
3. 데이터 폴더에 약속에 없는 파일이나 폴더가 없는가. 이 도구가 읽지 않는 파일을 데이터 폴더에 둘 수 없게 한다.
4. 저장소에 올리면 안 되는 것(떼어 둔 후기, 받은 참고 소스의 후기, 주소 목록, 기본 데이터로 돌린 결과)이
   섞이지 않았는가. 깃에 올라갈 수 있는 모든 파일을 훑어서 본다. 파일의 이름이나 자리가 아니라 내용으로 알아본다.

"주의"는 아직 덜 만든 것일 수 있는 항목이다 (예: 한 고객군의 몫을 더한 값이 1 보다 작다).
`--strict` 를 주면 주의도 오류로 본다.

이 도구가 보지 못하는 것: 지어낸 값이라고 적은 파일의 값이 정말 지어낸 것인지, 발표 자료와 그림 안의 내용.
그것은 사람이 지킨다 (CLAUDE.md 의 "비밀값과 공개 저장소").
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from collections.abc import Collection, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from engine.formats.choice import problems_in_response
from engine.formats.codes import WALKERHILL_VENUE_IDS
from engine.formats.conditions import MANUAL_CONDITION_PREFIX, ConditionBundle
from engine.formats.evidence import FREE_NAME_PREFIX, REVIEW_COLUMNS, URL_LIST_FILENAMES, ReviewLabel, Vocab
from engine.formats.io import read_csv
from engine.formats.persona import EVIDENCE_KEYS, Persona
from engine.formats.run import (
    LEDGER_COLUMNS,
    REQUEST_HASH_RE,
    SEASON_GAP_REASON,
    VISIT_ID_SEPARATOR,
    Calibration,
    LedgerRow,
    RunRecord,
    SavedResponse,
    compute_request_hash,
)
from engine.formats.scenario import BASELINE_ID, Scenario
from engine.formats.summary import SUMMARY_COLUMNS, SummaryRow
from engine.formats.venue import Venue

REPO_ROOT = Path(__file__).resolve().parents[1]

README = "README.md"
BOM = b"\xef\xbb\xbf"
SHARE_TOLERANCE = 1e-6

# ── 깃이 무시하는 것 ─────────────────────────────────────────────────────────
# 저장소를 훑을 때 이것만 건너뛴다. .gitignore 와 같아야 한다 (tests/test_check_rules.py 가 견준다).
# 깃이 무시하지 않는 것을 건너뛰면, 올라가는 파일인데 검사하지 않는 구멍이 생긴다.

PRIVATE_DIR = "private"
IGNORED_DIR_NAMES = frozenset(
    {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".omc", ".vscode", ".idea", "dist", "build"}
)
IGNORED_FILE_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})
IGNORED_SUFFIXES = (".pyc", ".log")


def ignored_by_git(parts: tuple[str, ...], is_dir: bool) -> bool:
    """저장소 맨 위에서 본 경로 `parts` 를 깃이 무시하는가 (.gitignore 를 그대로 옮긴 것)."""
    name = parts[-1]
    if parts[0] == PRIVATE_DIR and len(parts) > 1:
        # 맨 위의 private/ 는 안내 파일만 빼고 모두 무시한다. 더 깊은 곳의 private/ 는 무시하지 않는다.
        return parts != (PRIVATE_DIR, README)
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    if is_dir:
        return name in IGNORED_DIR_NAMES or name.endswith(".egg-info")
    if parts == (".claude", "settings.local.json"):
        return True
    return name in IGNORED_FILE_NAMES or name.endswith(IGNORED_SUFFIXES)


# ── 올리면 안 되는 것을 알아보는 표시 ────────────────────────────────────────

# 저장소에 있으면 안 되는 후기 번호: H 떼어 둔 후기, P 받은 참고 소스의 후기.
# 글자 인코딩과 상관없이 찾도록 바이트로 본다.
# 업장 식별자는 영어 글자로 시작하고 세 글자 이상이라고 본다 (check_venues 가 업장 정의에 그것을 요구한다).
# 그보다 짧은 것까지 번호로 보면, 번호가 아닌 낱말이 걸려 문서를 못 올리는 일이 생긴다.
VENUE_ID_RE = re.compile(r"^[a-z][a-z0-9]{2,}(-[a-z0-9]+)*$")
PRIVATE_REVIEW_ID_RE = re.compile(rb"(?<![A-Za-z0-9])[HP]-[a-z][a-z0-9]{2,}(?:-[a-z0-9]+)*-[0-9]{4}(?![0-9])")
# 주소의 끝이 우연히 후기 번호와 같은 모양일 수 있다. 그것은 후기 번호가 아니므로, 번호를 찾기 전에 주소를 지운다.
# (이 파일도 훑는 대상이라 여기에 번호 모양의 예시를 적지 않는다. 예시는 tests/test_check_rules.py 에 있다.)
# 주소는 공백, 따옴표, 쉼표, 세미콜론, 세로줄, 꺾쇠, 대괄호, 중괄호에서 끊는다.
# 쉼표에서 끊어야 CSV 의 다음 칸까지 지우지 않는다. 한글과 둥근 괄호는 주소에 들 수 있어 끊지 않는다.
URL_RE = re.compile(rb"https?://[^\s\"'<>,;|`\\\[\]{}]+")
# 기본 데이터로 돌린 실행 기록의 표시. 문서나 메모에 글로 붙여 넣은 실행 기록을 찾는다.
# 엔진 코드나 안내 문서가 이 값을 설명하는 것까지 막지 않도록, 실행 기록의 다른 키가 함께 있을 때만 본다.
PRIVATE_RUN_RE = re.compile(rb'"data_mode"\s*:\s*"private"')
RUN_RECORD_KEY_RES = (re.compile(rb'"run_id"\s*:'), re.compile(rb'"weights"\s*:'))
# 후기 라벨에 적으면 안 되는 주소.
ADDRESS_RE = re.compile(r"https?://|www\.", re.IGNORECASE)

# 후기 번호와 실행 기록의 예시를 적어도 되는 곳은 형식 문서와 테스트 코드뿐이다.
EXAMPLE_DOC = ("docs", "FORMATS.md")
# 테스트의 예시 묶음(tests/fixtures/<이름>/)은 저장소와 같은 폴더 모양을 쓰고, 저장소와 같은 검사를 받는다.
FIXTURES = ("tests", "fixtures")
# 데이터 폴더 어디에나 둘 수 있는 파일: 안내 파일과, 빈 폴더를 깃에 남길 때 쓰는 파일.
GUIDE_FILES = frozenset({README, ".gitkeep"})

TABLE_SUFFIXES = (".csv", ".tsv", ".txt")
MARKDOWN_SUFFIXES = (".md", ".markdown")
JSON_SUFFIXES = (".json", ".jsonl", ".ndjson")
DATA_SUFFIXES = frozenset({".csv", ".tsv", ".json", ".jsonl", ".ndjson"})
# 안을 볼 수 없는 데이터 파일과 묶은 파일. 저장소의 데이터는 CSV 와 JSON 으로만 둔다 (CLAUDE.md 의 "스택").
OPAQUE_SUFFIXES = frozenset(
    {".xlsx", ".xlsm", ".xls", ".parquet", ".feather", ".pkl", ".pickle", ".db", ".sqlite", ".sqlite3"}
    | {".zip", ".7z", ".gz", ".tar", ".rar"}
)
MAX_DATA_BYTES = 5_000_000
MAX_SCAN_BYTES = 100_000_000


@dataclass(frozen=True)
class Kind:
    """내용이나 이름으로 알아본 파일의 종류와, 그 파일을 둘 수 있는 자리."""

    label: str
    place: str | None  # 저장소 맨 위에서 본 경로의 모양(정규식). None 이면 저장소 어디에도 둘 수 없다.
    where: str  # 오류에 적을 안내


_RUN = r"engine/samples/runs/[^/]+"
_RUN_WHERE = "가상 예시 값으로 돌린 것은 engine/samples/runs/<run_id>/ 에, 기본 데이터로 돌린 것은 private/runs/ 에 둔다"
# 자리 밖에 있다고 알릴 때 덧붙이는 말. 테스트용 파일을 tests/<폴더>/ 에 두다가 걸리기 쉽다.
FIXTURE_HINT = "테스트에 쓸 예시는 tests/fixtures/<이름>/ 아래에 저장소와 같은 폴더 모양으로 둔다"

BASE_DATA = Kind(
    "기본 데이터",
    None,
    "기본 데이터는 저장소에 올리지 않는다. 일부만 떼어 낸 것이나 집계한 것도 같다 (private/ 에만 둔다). "
    "지어낸 값의 표라면 열 이름을 형식 약속의 영어 이름(revenue_net 같은 것)으로 적는다",
)
# 기본 데이터의 파일 이름에 든 말과, 금액을 담는 열 이름 둘. 공개된 docs/PRD.md 에 이미 적혀 있는 것만 쓴다.
# 집계하거나 일부만 떼어 내면 열이 하나만 남기 쉽다. 그래서 둘 가운데 하나만 있어도 기본 데이터로 본다.
BASE_DATA_NAME_PART = "구매상세"
BASE_DATA_COLUMNS = ("순매출", "총결제액")

# 후기 주소 목록은 주소를 담는 열과 후기를 가리키는 열이 함께 있는 표다.
# 주소 열만 있는 표(공식 메뉴의 출처 목록 같은 것)까지 막지 않으려고 둘을 함께 본다.
ADDRESS_COLUMNS = frozenset({"url", "link", "주소", "링크"})
REVIEW_HINT_COLUMNS = frozenset({"review_id", "source_kind", "dropped"})

URL_LIST = Kind("후기 주소 목록", None, "후기 주소 목록은 저장소에 올리지 않는다 (private/evidence/ 에만 둔다)")
VALIDATION = Kind(
    "검증 결과", None, "검증 결과는 저장소에 두지 않는다. 떼어 둔 후기로 잰 것이라 private/ 의 실행에만 있다"
)
REVIEW_LABELS = Kind(
    "후기 라벨",
    r"data/evidence/(?:reviews|extra)/[^/]+\.csv",
    "후기 라벨은 data/evidence/reviews/ 와 data/evidence/extra/ 에만 둔다",
)
SUMMARY = Kind(
    "기본 데이터 집계 파일",
    r"data/samples/base_summary\.csv",
    "지어낸 값은 data/samples/base_summary.csv 에만, 진짜 집계 파일은 private/base/ 에만 둔다",
)
LEDGER = Kind("소비 원장", _RUN + r"/ledger\.csv", _RUN_WHERE)
RUN_RECORD = Kind("실행 기록", _RUN + r"/run\.json", _RUN_WHERE)
SAVED_RESPONSE = Kind("저장된 LLM 응답", _RUN + r"/llm/[^/]+\.json", _RUN_WHERE)
CALIBRATION = Kind("보정의 대조 결과", _RUN + r"/calibration\.json", _RUN_WHERE)

# 표의 머리글이나 JSON 묶음의 키에 이 이름이 모두 있으면 그 종류다.
# 표는 CSV·TSV·글 파일의 첫 줄과 마크다운 표의 머리글을 본다. JSON 은 맨 위뿐 아니라 안쪽의 묶음도 모두 본다
# (응답 여럿을 목록 하나에 모은 파일, 한 줄에 하나씩 적은 jsonl, 표를 레코드로 바꾼 파일).
NAME_SET_MARKS = (
    (frozenset({"baseline_venue_match"}), VALIDATION),
    (frozenset({"min_reviews", "venues", "created_at"}), VALIDATION),
    (frozenset({"visit_id", "weighted_revenue"}), LEDGER),
    (frozenset({"review_id", "labeler"}), REVIEW_LABELS),
    (frozenset({"price_unconfirmed", "revenue_net"}), SUMMARY),
    (frozenset({"data_mode", "run_id"}), RUN_RECORD),
    (frozenset({"request_hash", "raw_text"}), SAVED_RESPONSE),
    (frozenset({"criteria", "groups", "uncovered_groups"}), CALIBRATION),
)

PRIVATE_RUN_NOTE = "기본 데이터로 돌린 실행 기록이 들어 있다 (data_mode 가 private). 그런 결과는 private/runs/ 에만 둔다"
BASE_PROFILE_NOTE = (
    "기본 데이터에서 계산한 값(base_profile)이 들어 있다. 가상 예시로 돌릴 때는 붙이지 않는 값이다. "
    "기본 데이터로 돌린 결과는 private/runs/ 에만 둔다"
)
PRIVATE_LAYER_NOTE = (
    "비공개 층이 합쳐진 페르소나가 들어 있다 (overridden_by_private 에 값이 있다). "
    "가상 예시로 돌릴 때는 공개 층만 쓰고, 합친 결과는 private/ 에만 둔다"
)
# 이름만으로 그 종류로 보는 파일.
NAME_MARKS = {
    "run.json": RUN_RECORD,
    "ledger.csv": LEDGER,
    "calibration.json": CALIBRATION,
    "validation.json": VALIDATION,
    "validation_reviews.csv": VALIDATION,
    **dict.fromkeys(URL_LIST_FILENAMES, URL_LIST),
}
# 실행 하나의 폴더에 둘 수 있는 파일. 검증 결과는 이름을 알아보고 따로 오류를 낸다.
RUN_FILES = ("run.json", "ledger.csv", "calibration.json", "validation.json", "validation_reviews.csv")


@dataclass(frozen=True)
class Problem:
    level: str  # "error" 또는 "warning"
    path: str
    message: str

    def __str__(self) -> str:
        label = "오류" if self.level == "error" else "주의"
        return f"[{label}] {self.path}: {self.message}"


@dataclass
class Checker:
    root: Path
    problems: list[Problem] = field(default_factory=list)
    files_checked: int = 0  # 형식을 본 데이터 파일의 수
    files_scanned: int = 0  # 올리면 안 되는 것이 있는지 훑어본 파일의 수

    venues: dict[str, Venue] = field(default_factory=dict)
    vocab: Vocab | None = None
    reviews: dict[str, ReviewLabel] = field(default_factory=dict)
    personas: dict[str, Persona] = field(default_factory=dict)
    conditions: ConditionBundle | None = None
    scenarios: dict[str, Scenario] = field(default_factory=dict)

    # ── 기록 ────────────────────────────────────────────────────────────────

    def error(self, path: Path | str, message: str) -> None:
        self.problems.append(Problem("error", self._rel(path), message))

    def warning(self, path: Path | str, message: str) -> None:
        self.problems.append(Problem("warning", self._rel(path), message))

    def _rel(self, path: Path | str) -> str:
        if isinstance(path, Path):
            try:
                return path.relative_to(self.root).as_posix()
            except ValueError:
                return path.as_posix()
        return path

    def _model_errors(self, path: Path, exc: ValidationError, prefix: str = "") -> None:
        for err in exc.errors():
            where = prefix + _location(err["loc"])
            self.error(path, f"{where + ' — ' if where else ''}{_korean(err)}")

    # ── 읽기 ────────────────────────────────────────────────────────────────

    def _raw_json(self, path: Path) -> bytes | None:
        self.files_checked += 1
        try:
            raw = path.read_bytes()
        except OSError as exc:
            self.error(path, f"읽을 수 없다: {exc}")
            return None
        if raw.startswith(BOM):
            self.error(path, "JSON 파일 앞에 BOM 이 있다. BOM 없이 UTF-8 로 저장한다")
            return None
        return raw

    def _csv(self, path: Path, columns: list[str]) -> list[dict[str, str]] | None:
        self.files_checked += 1
        try:
            if not path.read_bytes().startswith(BOM):
                self.warning(path, 'CSV 앞에 BOM 이 없다. 엑셀에서 한글이 깨진다 (encoding="utf-8-sig" 로 저장한다)')
            return read_csv(path, columns)
        except (OSError, ValueError, csv.Error) as exc:  # UnicodeDecodeError 는 ValueError 에 든다
            self.error(path, f"CSV 를 읽을 수 없다: {exc}")
            return None

    def _load(self, path: Path, model: type) -> Any | None:
        """JSON 파일을 모델로 읽는다. 적힌 그대로 엄격하게 본다 (따옴표로 감싼 숫자는 숫자가 아니다)."""
        raw = self._raw_json(path)
        if raw is None:
            return None
        try:
            return model.model_validate_json(raw, strict=True)
        except ValidationError as exc:
            self._model_errors(path, exc)
            return None

    def _managed(
        self,
        folder: Path,
        holds: str,
        *,
        suffix: str = "",
        files: Collection[str] = (),
        dirs: Collection[str] = (),
    ) -> list[Path]:
        """데이터 폴더 하나를 읽어 `suffix` 로 끝나는 데이터 파일을 돌려준다.

        이 폴더에는 그 데이터 파일, `files` 의 파일, 안내 파일(README.md), `dirs` 의 폴더만 둘 수 있다.
        그 밖의 것은 이 도구가 읽지 않으므로 오류로 적는다. 읽지 않는 파일에는 틀린 데이터나
        올리면 안 되는 것이 들어 있어도 알 수 없다. `holds` 는 오류에 적을 "이 폴더에 두는 것"이다.
        """
        if not folder.is_dir():
            return []
        found: list[Path] = []
        for path in sorted(folder.iterdir()):
            parts = path.relative_to(self.root).parts
            if path.is_dir():
                if path.name not in dirs and not ignored_by_git(parts, is_dir=True):
                    self.error(path, f"약속에 없는 폴더다. 이 폴더에는 {holds} 만 둔다 (형식 약속 1절)")
            elif ignored_by_git(parts, is_dir=False) or path.name in GUIDE_FILES or path.name in files:
                continue
            elif suffix and path.suffix == suffix:
                found.append(path)
            else:
                hint = " 확장자는 소문자로 적는다" if suffix and path.suffix.lower() == suffix else ""
                self.error(path, f"약속에 없는 파일이다. 이 폴더에는 {holds} 만 둔다 (형식 약속 1절).{hint}")
        return found

    # ── 데이터 폴더의 구조 ──────────────────────────────────────────────────

    def check_layout(self) -> None:
        """데이터 폴더의 윗단에 약속에 없는 것이 있는지 본다. 끝 폴더는 그 형식의 검사에서 본다."""
        data = self.root / "data"
        self._managed(data, "venues, evidence, samples 폴더", dirs=("venues", "evidence", "samples"))
        self._managed(
            data / "evidence",
            "라벨 값 목록 `vocab.json` 과 reviews, extra 폴더",
            files=("vocab.json",),
            dirs=("reviews", "extra"),
        )
        self._managed(data / "samples", "가상 예시 값 `base_summary.csv`", files=("base_summary.csv",))
        self._managed(self.root / "engine" / "samples", "runs 폴더", dirs=("runs",))

    # ── 업장 정의 (3절) ─────────────────────────────────────────────────────

    def check_venues(self) -> None:
        folder = self.root / "data" / "venues"
        for path in self._managed(folder, "업장 정의 `<venue_id>.json`", suffix=".json"):
            venue = self._load(path, Venue)
            if venue is None:
                continue
            if path.stem != venue.venue_id:
                self.error(path, f"파일 이름이 venue_id '{venue.venue_id}' 와 다르다")
            if not VENUE_ID_RE.match(venue.venue_id):
                self.error(path, f"venue_id '{venue.venue_id}' 는 영어 글자로 시작하고 세 글자 이상이어야 한다")
            if venue.venue_id in self.venues:
                self.error(path, f"venue_id '{venue.venue_id}' 가 다른 파일에도 있다")
            if not venue.is_competitor and venue.venue_id not in WALKERHILL_VENUE_IDS:
                self.error(path, f"워커힐 업장의 venue_id 가 아니다 (쓸 수 있는 값: {sorted(WALKERHILL_VENUE_IDS)})")
            if venue.is_competitor and venue.venue_id in WALKERHILL_VENUE_IDS:
                self.error(path, "워커힐 업장의 venue_id 인데 is_competitor 가 true 다")
            if not venue.is_competitor and venue.hours is None:
                self.warning(path, "워커힐 업장인데 hours 가 null 이다. 영업 시간을 모른다고 둘 수 있는 것은 경쟁 업장뿐이다")
            self.venues[venue.venue_id] = venue

        for venue in self.venues.values():
            path = folder / f"{venue.venue_id}.json"
            for target in venue.competes_with:
                other = self.venues.get(target)
                if other is None:
                    self.error(path, f"competes_with 의 '{target}' 정의 파일이 없다")
                elif other.is_competitor:
                    self.error(path, f"competes_with 의 '{target}' 는 워커힐 업장이 아니다")
                elif not set(venue.occasions) & set(other.occasions):
                    self.error(path, f"견주는 업장 '{target}' 와 겹치는 이용 상황이 없다")

        rivals: dict[str, int] = defaultdict(int)
        for venue in self.venues.values():
            for target in venue.competes_with:
                rivals[target] += 1
        for venue in self.venues.values():
            if not venue.is_competitor and rivals[venue.venue_id] == 0:
                path = folder / f"{venue.venue_id}.json"
                self.warning(path, "이 업장과 견주는 경쟁 업장이 아직 없다 (업장마다 하나 이상 있어야 한다)")

    # ── 후기 라벨과 값 목록 (4절) ───────────────────────────────────────────

    def check_evidence(self) -> None:
        evidence = self.root / "data" / "evidence"
        vocab_path = evidence / "vocab.json"
        if vocab_path.is_file():
            self.vocab = self._load(vocab_path, Vocab)

        folders = [(evidence / "reviews", 1, 4999), (evidence / "extra", 5000, 9999)]
        for folder, low, high in folders:
            for path in self._managed(folder, "후기 라벨 `<venue_id>.csv`", suffix=".csv"):
                rows = self._csv(path, REVIEW_COLUMNS)
                if rows is None:
                    continue
                for number, row in enumerate(rows, start=2):
                    self._check_review(path, number, row, low, high)

    def _check_review(self, path: Path, line: int, row: dict[str, str], low: int, high: int) -> None:
        prefix = f"{line}번째 줄 "
        if any(ADDRESS_RE.search(value) for value in row.values()):
            self.error(path, f"{prefix}— 주소가 적혀 있다. 후기 라벨에는 후기의 주소를 적지 않는다 (4.1절)")
        try:
            review = ReviewLabel.from_row(row)
        except ValidationError as exc:
            self._model_errors(path, exc, prefix)
            return

        def bad(message: str) -> None:
            self.error(path, f"{prefix}({review.review_id}) {message}")

        if review.kind != "R":
            bad("H 와 P 로 시작하는 후기는 저장소에 올리지 않는다 (떼어 둔 후기, 받은 참고 소스의 후기)")
        if review.source_kind == "reference":
            bad("받은 참고 소스의 후기는 저장소에 올리지 않는다")
        if review.venue_id != path.stem:
            bad(f"파일 이름의 업장과 venue_id '{review.venue_id}' 가 다르다")
        if not low <= review.number <= high:
            bad(f"이 폴더의 번호대는 {low:04d} ~ {high:04d} 다")
        if review.review_id in self.reviews:
            bad("같은 후기 번호가 또 있다")
        self.reviews[review.review_id] = review

        venue = self.venues.get(review.venue_id)
        if venue is None:
            bad(f"업장 '{review.venue_id}' 의 정의 파일이 없다")
        else:
            product_ids = {p.product_id for p in venue.products}
            for item in review.ordered:
                if not item.startswith(FREE_NAME_PREFIX) and item not in product_ids:
                    bad(f"ordered 의 '{item}' 가 업장 정의에 없다 (정의에 없는 메뉴는 '{FREE_NAME_PREFIX}' 뒤에 적는다)")
        for item in review.compared_with:
            if item.startswith(FREE_NAME_PREFIX):
                continue
            other = self.venues.get(item)
            if other is None or not other.is_competitor:
                bad(f"compared_with 의 '{item}' 가 경쟁 업장 정의에 없다 (정의에 없는 곳은 '{FREE_NAME_PREFIX}' 뒤에 적는다)")

        if self.vocab is None:
            self.error(path, "라벨 값 목록 data/evidence/vocab.json 이 없거나 읽을 수 없다")
            return
        if review.customer_group is not None and review.customer_group not in self.vocab.customer_group:
            bad(f"customer_group '{review.customer_group}' 가 값 목록에 없다")
        if review.purpose not in self.vocab.purpose:
            bad(f"purpose '{review.purpose}' 가 값 목록에 없다")
        if review.party not in self.vocab.party:
            bad(f"party '{review.party}' 가 값 목록에 없다")
        for label in review.reasons_chosen:
            if label not in self.vocab.reasons_chosen:
                bad(f"reasons_chosen 의 '{label}' 가 값 목록에 없다")
        for label in review.pain_points:
            if label not in self.vocab.pain_points:
                bad(f"pain_points 의 '{label}' 가 값 목록에 없다")

    # ── 페르소나 정의 (5절) ─────────────────────────────────────────────────

    def check_personas(self) -> None:
        folder = self.root / "personas"
        holds = "페르소나 정의 `<persona_id>.json` 과 프롬프트를 두는 prompts 폴더"
        for path in self._managed(folder, holds, suffix=".json", dirs=("prompts",)):
            persona = self._load(path, Persona)
            if persona is None:
                continue
            if path.stem != persona.persona_id:
                self.error(path, f"파일 이름이 persona_id '{persona.persona_id}' 와 다르다")
            if persona.overridden_by_private:
                self.error(path, "overridden_by_private 는 파일에 적지 않는다 (엔진이 두 층을 합칠 때 채운다)")
            self.personas[persona.persona_id] = persona
            self._check_persona(path, persona)

        shares: dict[str, float] = defaultdict(float)
        for persona in self.personas.values():
            shares[persona.customer_group] += persona.share_in_group.value
        for group, total in shares.items():
            if total > 1 + SHARE_TOLERANCE:
                self.error(folder, f"고객군 '{group}' 의 몫을 더하면 {total:g} 다. 1 을 넘을 수 없다")
            elif total < 1 - SHARE_TOLERANCE:
                self.warning(folder, f"고객군 '{group}' 의 몫을 더하면 {total:g} 다. 다 만들면 1 이어야 한다")

    def _check_persona(self, path: Path, persona: Persona) -> None:
        for target in persona.compares_with:
            other = self.venues.get(target)
            if other is None or not other.is_competitor:
                self.error(path, f"compares_with 의 '{target}' 가 경쟁 업장 정의에 없다")

        for key in EVIDENCE_KEYS:
            item = getattr(persona.evidence, key)
            if item.grade == "internal":
                self.error(path, f"evidence.{key} — 공개 층에는 내부 매출 자료(internal) 등급을 쓸 수 없다")
            review_refs = 0
            for ref in item.refs:
                if ":" in ref:
                    venue_id, _, source_id = ref.partition(":")
                    venue = self.venues.get(venue_id)
                    if venue is None or source_id not in {s.source_id for s in venue.sources}:
                        self.error(path, f"evidence.{key} — 출처 '{ref}' 가 업장 정의에 없다")
                    continue
                review_refs += 1
                if ref[:2] in ("H-", "P-"):
                    self.error(path, f"evidence.{key} — '{ref}' 는 저장소에 올릴 수 없는 후기다 (비공개 층에 적는다)")
                elif ref not in self.reviews:
                    self.error(path, f"evidence.{key} — 후기 '{ref}' 가 후기 라벨 파일에 없다")
            if item.grade == "review" and review_refs == 0:
                self.error(path, f"evidence.{key} — 등급이 review 인데 근거로 든 후기 번호가 없다")

        if self.vocab is None:
            self.error(path, "라벨 값 목록 data/evidence/vocab.json 이 없거나 읽을 수 없다")
            return
        if persona.customer_group not in self.vocab.customer_group:
            self.error(path, f"customer_group '{persona.customer_group}' 가 값 목록에 없다")
        for label in persona.visit.purposes:
            if label not in self.vocab.purpose:
                self.error(path, f"visit.purposes 의 '{label}' 가 값 목록에 없다")
        if persona.visit.party.label not in self.vocab.party:
            self.error(path, f"visit.party.label '{persona.visit.party.label}' 가 값 목록에 없다")
        for label in persona.revisit.returns_for:
            if label not in self.vocab.reasons_chosen:
                self.error(path, f"revisit.returns_for 의 '{label}' 가 값 목록(reasons_chosen)에 없다")
        for label in persona.revisit.leaves_for:
            if label not in self.vocab.pain_points:
                self.error(path, f"revisit.leaves_for 의 '{label}' 가 값 목록(pain_points)에 없다")

    # ── 방문 조건 묶음 (6절) ────────────────────────────────────────────────

    def check_conditions(self) -> None:
        path = self.root / "engine" / "conditions.json"
        if path.is_file():
            self.conditions = self._load(path, ConditionBundle)

    # ── 상황 정의 (7절) ─────────────────────────────────────────────────────

    def check_scenarios(self) -> None:
        folder = self.root / "scenarios"
        for path in self._managed(folder, "상황 정의 `<scenario_id>.json`", suffix=".json"):
            scenario = self._load(path, Scenario)
            if scenario is None:
                continue
            if path.stem != scenario.scenario_id:
                self.error(path, f"파일 이름이 scenario_id '{scenario.scenario_id}' 와 다르다")
            self.scenarios[scenario.scenario_id] = scenario
            self._check_scenario(path, scenario)
        if self.scenarios and BASELINE_ID not in self.scenarios:
            self.error(folder, "기준 상황 scenarios/baseline.json 이 없다")

    def _check_scenario(self, path: Path, scenario: Scenario) -> None:
        # 바꾸는 것을 순서대로 적용해 가며, 그 시점에 가리키는 상품과 프로모션이 있는지 본다.
        products = {v.venue_id: {p.product_id for p in v.products} for v in self.venues.values()}
        promos = {v.venue_id: {p.promo_id for p in v.promotions} for v in self.venues.values()}
        for index, change in enumerate(scenario.changes):
            where = f"changes[{index}] ({change.op})"
            venue = self.venues.get(change.venue_id)
            if venue is None:
                self.error(path, f"{where} — 업장 '{change.venue_id}' 의 정의 파일이 없다")
                continue
            if scenario.kind in ("our_price", "our_promo") and venue.is_competitor:
                self.error(path, f"{where} — 우리 쪽 상황({scenario.kind})은 워커힐 업장만 바꾼다")
            if scenario.kind == "competitor" and not venue.is_competitor:
                self.error(path, f"{where} — 경쟁 쪽 상황(competitor)은 경쟁 업장만 바꾼다")

            known_products = products[venue.venue_id]
            known_promos = promos[venue.venue_id]
            if change.op in ("set_price", "remove_product") or (
                change.op == "change_price_pct" and change.product_id is not None
            ):
                if change.product_id not in known_products:
                    self.error(path, f"{where} — 상품 '{change.product_id}' 가 업장 '{venue.venue_id}' 에 없다")
                elif change.op == "remove_product":
                    known_products.discard(change.product_id)
            elif change.op == "add_product":
                product = change.product
                if product.product_id in known_products:
                    self.error(path, f"{where} — 상품 '{product.product_id}' 가 이미 있다")
                if product.occasion not in venue.occasions:
                    self.error(path, f"{where} — 상품의 occasion 이 업장의 occasions 에 없다")
                if product.source_id is not None and product.source_id not in {s.source_id for s in venue.sources}:
                    self.error(path, f"{where} — 상품의 source_id 가 업장의 sources 에 없다")
                known_products.add(product.product_id)
            elif change.op == "add_promotion":
                promotion = change.promotion
                if promotion.promo_id in known_promos:
                    self.error(path, f"{where} — 프로모션 '{promotion.promo_id}' 가 이미 있다")
                for product_id in promotion.applies_to or []:
                    if product_id not in known_products:
                        self.error(path, f"{where} — applies_to 의 상품 '{product_id}' 가 업장에 없다")
                if promotion.source_id is not None and promotion.source_id not in {
                    s.source_id for s in venue.sources
                }:
                    self.error(path, f"{where} — 프로모션의 source_id 가 업장의 sources 에 없다")
                known_promos.add(promotion.promo_id)
            elif change.op == "remove_promotion":
                if change.promo_id not in known_promos:
                    self.error(path, f"{where} — 프로모션 '{change.promo_id}' 가 업장 '{venue.venue_id}' 에 없다")
                known_promos.discard(change.promo_id)

    def _products_in(self, scenario_id: str) -> dict[str, set[str]]:
        """그 상황에서 업장마다 있을 수 있는 상품 (기준의 상품과 상황이 더한 상품)."""
        products = {v.venue_id: {p.product_id for p in v.products} for v in self.venues.values()}
        scenario = self.scenarios.get(scenario_id)
        for change in scenario.changes if scenario else []:
            if change.op == "add_product" and change.venue_id in products:
                products[change.venue_id].add(change.product.product_id)
        return products

    # ── 가상 예시 값 (8절) ──────────────────────────────────────────────────

    def check_sample_summary(self) -> None:
        path = self.root / "data" / "samples" / "base_summary.csv"
        if not path.is_file():
            return
        rows = self._csv(path, SUMMARY_COLUMNS)
        if rows is None:
            return
        seen: set[tuple] = set()
        for number, row in enumerate(rows, start=2):
            prefix = f"{number}번째 줄 "
            try:
                item = SummaryRow.from_row(row)
            except ValidationError as exc:
                self._model_errors(path, exc, prefix)
                continue
            key = (item.customer_group, item.venue_id, item.product_id, item.occasion, item.meal, item.day_type)
            if key in seen:
                self.error(path, f"{prefix}— 같은 고객군·업장·상품·조건의 줄이 또 있다")
            seen.add(key)
            venue = self.venues.get(item.venue_id)
            product = venue.product(item.product_id) if venue else None
            if venue is None:
                self.error(path, f"{prefix}— 업장 '{item.venue_id}' 의 정의 파일이 없다")
            elif product is None:
                self.error(path, f"{prefix}— 상품 '{item.product_id}' 가 업장 '{item.venue_id}' 에 없다")
            else:
                if item.occasion != product.occasion:
                    self.error(path, f"{prefix}— occasion 이 상품 정의와 다르다")
                if item.unit != product.unit:
                    self.error(path, f"{prefix}— unit 이 상품 정의와 다르다")
                if item.meal is not None and item.meal not in product.meals:
                    self.error(path, f"{prefix}— meal '{item.meal}' 은 그 상품을 파는 끼니가 아니다")
            if self.vocab is None:
                self.error(path, "라벨 값 목록 data/evidence/vocab.json 이 없거나 읽을 수 없다")
            elif item.customer_group not in self.vocab.customer_group:
                self.error(path, f"{prefix}— customer_group '{item.customer_group}' 가 값 목록에 없다")

    # ── 가상 예시로 돌린 실행 결과 (10절) ───────────────────────────────────

    def check_sample_runs(self) -> None:
        runs = self.root / "engine" / "samples" / "runs"
        if not runs.is_dir():
            return
        run_dirs = sorted(
            p for p in runs.iterdir() if p.is_dir() and not ignored_by_git(p.relative_to(self.root).parts, is_dir=True)
        )
        self._managed(runs, "실행마다의 폴더 `<run_id>/`", dirs=[p.name for p in run_dirs])

        records: dict[str, RunRecord] = {}
        for run_dir in run_dirs:
            self._managed(
                run_dir, "실행 기록, 소비 원장, 보정의 대조 결과와 저장된 응답의 llm 폴더", files=RUN_FILES, dirs=("llm",)
            )
            record_path = run_dir / "run.json"
            if not record_path.is_file():
                self.error(run_dir, "실행 기록 run.json 이 없다")
                continue
            record = self._load(record_path, RunRecord)
            if record is None:
                continue
            records[run_dir.name] = record
            self._check_run_record(record_path, run_dir.name, record)

        for run_dir in run_dirs:
            record = records.get(run_dir.name)
            if record is None:
                continue
            if record.weights_from is not None:
                base = records.get(record.weights_from)
                path = run_dir / "run.json"
                if base is None:
                    self.error(path, f"weights_from 의 실행 '{record.weights_from}' 가 없다")
                elif base.scenario_id != BASELINE_ID:
                    self.error(path, f"weights_from 의 실행 '{record.weights_from}' 는 기준 상황이 아니다")
                elif base.weights != record.weights:
                    self.error(path, "weights 가 weights_from 의 실행과 다르다 (가중치는 기준 상황에서 한 번 정하고 그대로 쓴다)")
            stems, saved = self._check_saved_responses(run_dir, record)
            self._check_ledger(run_dir, record, stems, saved)
            self._check_calibration(run_dir, record)

    def _check_run_record(self, path: Path, dir_name: str, record: RunRecord) -> None:
        if record.run_id != dir_name:
            self.error(path, f"폴더 이름이 run_id '{record.run_id}' 와 다르다")
        if record.data_mode != "sample":
            self.error(path, "저장소에는 가상 예시 값으로 돌린 결과(data_mode 가 sample)만 둔다")
        if record.base_profile_mode != "none":
            self.error(path, "가상 예시로 돌릴 때는 기본 데이터에서 나온 값을 쓰지 않는다 (base_profile_mode 는 none)")
        grades = record.weights.grades
        used = {grades.group_multiplier, grades.persona_weight}
        used.update(grade for by_condition in grades.condition_ratio.values() for grade in by_condition.values())
        if "internal" in used:
            self.error(
                path,
                "가상 예시로 돌린 실행인데 가중치의 등급에 내부 매출 자료(internal)가 있다. "
                "지어낸 값에서 낸 가중치의 등급은 assumption 이다",
            )
        if record.scenario_id not in self.scenarios:
            self.error(path, f"상황 '{record.scenario_id}' 의 정의 파일이 없다")
        for persona_id in record.persona_ids:
            if persona_id not in self.personas:
                self.error(path, f"페르소나 '{persona_id}' 의 정의 파일이 없다")
        for condition_id in record.condition_ids:
            if not self._known_condition(condition_id):
                self.error(path, f"조건 '{condition_id}' 가 방문 조건 묶음에 없다")
        for persona_id in record.weights.persona_weight:
            if persona_id not in record.persona_ids:
                self.error(path, f"weights.persona_weight 의 '{persona_id}' 가 persona_ids 에 없다")

        # 묶음의 조건으로 돌렸으면 가중치가 빠짐없이 있어야 한다. 없으면 원장의 represented 를 확인할 수 없다.
        planned = [c for c in record.condition_ids if not c.startswith(MANUAL_CONDITION_PREFIX)]
        for persona_id in record.persona_ids if planned else []:
            if persona_id not in record.weights.persona_weight:
                self.error(path, f"weights.persona_weight 에 페르소나 '{persona_id}' 의 가중치가 없다")
            persona = self.personas.get(persona_id)
            if persona is None:
                continue
            ratios = record.weights.condition_ratio.get(persona.customer_group, {})
            for condition_id in planned:
                if condition_id not in ratios:
                    self.error(
                        path,
                        f"weights.condition_ratio 에 고객군 '{persona.customer_group}' 의 조건 '{condition_id}' 비율이 없다",
                    )

    def _known_condition(self, condition_id: str) -> bool:
        if condition_id.startswith(MANUAL_CONDITION_PREFIX):
            return True
        return self.conditions is not None and self.conditions.condition(condition_id) is not None

    def _check_saved_responses(self, run_dir: Path, record: RunRecord) -> tuple[set[str], dict[str, SavedResponse]]:
        """저장된 응답을 검사한다. 돌려주는 것은 (있는 파일의 이름, 읽는 데 성공한 응답)이다."""
        stems: set[str] = set()
        saved: dict[str, SavedResponse] = {}
        for path in self._managed(run_dir / "llm", "저장된 응답 `<request_hash>.json`", suffix=".json"):
            stems.add(path.stem)
            raw = self._raw_json(path)
            if raw is None:
                continue
            try:
                entry = SavedResponse.model_validate_json(raw, strict=True)
            except ValidationError as exc:
                self._model_errors(path, exc)
                continue
            saved[path.stem] = entry
            if path.stem != entry.request_hash:
                self.error(path, "파일 이름이 request_hash 와 다르다")
            if not REQUEST_HASH_RE.match(entry.request_hash):
                self.error(path, "request_hash 는 16진수 16글자다")
            # 해시는 모델을 거친 값이 아니라 파일에 적힌 요청 그대로에서 낸다.
            expected = compute_request_hash(entry.provider, entry.model, json.loads(raw)["request"])
            if entry.request_hash != expected:
                self.error(path, f"request_hash 가 요청으로 다시 낸 값 '{expected}' 와 다르다 (요청을 손으로 고쳤는가)")
            if (entry.provider, entry.model) != (record.llm.provider, record.llm.model):
                self.error(path, "provider 나 model 이 실행 기록과 다르다")
            if entry.request.scenario_id != record.scenario_id:
                self.error(path, "요청의 scenario_id 가 실행 기록과 다르다")
            # 요청에 비공개 층이나 기본 데이터에서 나온 값이 섞였는지는 check_nothing_private 가 본다.
            # 그 검사는 이 폴더뿐 아니라 저장소의 모든 JSON 을 본다.
            for problem in problems_in_response(entry.request, entry.response):
                self.error(path, f"응답 — {problem}")
        return stems, saved

    def _check_ledger(
        self, run_dir: Path, record: RunRecord, stems: set[str], saved: dict[str, SavedResponse]
    ) -> None:
        path = run_dir / "ledger.csv"
        if not path.is_file():
            self.error(run_dir, "소비 원장 ledger.csv 가 없다")
            return
        rows = self._csv(path, LEDGER_COLUMNS)
        if rows is None:
            return
        products = self._products_in(record.scenario_id)
        visits: dict[str, list[tuple[int, LedgerRow]]] = defaultdict(list)
        unreadable = 0
        for number, row in enumerate(rows, start=2):
            prefix = f"{number}번째 줄 "
            try:
                item = LedgerRow.from_row(row)
            except ValidationError as exc:
                self._model_errors(path, exc, prefix)
                unreadable += 1
                continue
            visits[item.visit_id].append((number, item))

            def bad(message: str, prefix: str = prefix) -> None:
                self.error(path, f"{prefix}— {message}")

            if item.run_id != record.run_id:
                bad("run_id 가 실행 기록과 다르다 (원장 파일 하나에는 실행 하나의 줄만 들어간다)")
            if item.scenario_id != record.scenario_id:
                bad("scenario_id 가 실행 기록과 다르다")
            persona = self.personas.get(item.persona_id)
            if persona is None or item.persona_id not in record.persona_ids:
                bad(f"페르소나 '{item.persona_id}' 가 정의나 실행 기록에 없다")
            elif persona.customer_group != item.customer_group:
                bad("customer_group 이 페르소나 정의와 다르다")
            if item.condition_id not in record.condition_ids:
                bad(f"조건 '{item.condition_id}' 가 실행 기록에 없다")
            # 실패한 줄은 LLM 을 부르다 실패한 것일 수 있어, 저장된 응답이 없어도 된다.
            if item.status == "ok" and item.request_hash is not None and item.request_hash not in stems:
                bad(f"저장된 응답 llm/{item.request_hash}.json 이 없다")

            if item.venue_id is not None:
                venue = self.venues.get(item.venue_id)
                if venue is None:
                    bad(f"업장 '{item.venue_id}' 의 정의 파일이 없다")
                else:
                    kind = "competitor" if venue.is_competitor else "walkerhill"
                    if item.choice_kind != kind:
                        bad(f"choice_kind 가 업장 정의와 다르다 ('{item.venue_id}' 는 {kind})")
                    if item.product_id not in products.get(item.venue_id, set()):
                        bad(f"상품 '{item.product_id}' 가 업장 '{item.venue_id}' 에 없다")

            # 화면에서 조건을 직접 넣어 돌린 방문(manual-)에는 가중치가 없다. 그 밖에는 반드시 견준다.
            if not item.condition_id.startswith(MANUAL_CONDITION_PREFIX):
                weight = record.weights.persona_weight.get(item.persona_id)
                ratio = record.weights.condition_ratio.get(item.customer_group, {}).get(item.condition_id)
                if weight is None or ratio is None:
                    bad("실행 기록의 weights 에 이 페르소나의 가중치나 이 조건의 비율이 없어 represented 를 확인할 수 없다")
                elif abs(weight * ratio - item.represented) > 1e-6:
                    bad("represented 가 실행 기록의 페르소나 가중치 × 묶음 비율과 다르다")

            if self.vocab is not None and item.status == "ok":
                allowed = self.vocab.pain_points if item.choice_kind == "none" else self.vocab.reasons_chosen
                for label in item.reason_labels:
                    if label not in allowed:
                        bad(f"reason_labels 의 '{label}' 가 값 목록에 없다")

        for visit_rows in visits.values():
            self._check_visit(path, visit_rows, saved)

        # 읽지 못한 줄이 있으면 방문을 제대로 셀 수 없다. 그 줄의 오류는 위에서 이미 적었으므로,
        # 같은 원인에서 나오는 "방문 수가 다르다"를 겹쳐 적지 않는다. 그 줄을 고친 뒤 다시 돌리면 아래를 본다.
        if unreadable:
            return

        # 원장의 방문이 실행 기록과 맞는지 본다. 모든 합계를 이 원장에서 내므로, 빠지거나 남는 방문이 있으면 합계가 달라진다.
        failed = sum(1 for visit_rows in visits.values() if any(row.status == "failed" for _, row in visit_rows))
        if len(visits) != record.counts.visits:
            self.error(path, f"원장의 방문이 {len(visits)}건인데 실행 기록의 counts.visits 는 {record.counts.visits} 다")
        if failed != record.counts.failed:
            self.error(path, f"원장의 실패한 방문이 {failed}건인데 실행 기록의 counts.failed 는 {record.counts.failed} 다")
        if record.status == "ok":
            planned = {
                f"{persona_id}{VISIT_ID_SEPARATOR}{condition_id}"
                for persona_id in record.persona_ids
                for condition_id in record.condition_ids
            }
            missing, extra = planned - set(visits), set(visits) - planned
            if missing or extra:
                self.error(
                    path,
                    "끝까지 돌린 실행(status 가 ok)의 원장에는 페르소나 × 조건마다 방문이 하나씩 있어야 한다: "
                    f"빠진 방문 {len(missing)}건, 실행 기록에 없는 방문 {len(extra)}건",
                )

    def _check_visit(self, path: Path, rows: list[tuple[int, LedgerRow]], saved: dict[str, SavedResponse]) -> None:
        """한 방문의 줄들이 앞뒤가 맞는지, 저장된 응답과 같은지 본다.

        원장은 저장된 응답에서 만든 것이라, 누가 어느 조건에서 무엇을 골랐는지가 응답과 같아야 한다.
        금액을 업장 정의의 가격과 프로모션으로 다시 계산하는 것은 엔진의 몫이라 여기서는 하지 않는다.
        """
        line, first = rows[0]

        def bad(message: str) -> None:
            self.error(path, f"{line}번째 줄 (방문 {first.visit_id}) — {message}")

        # 실패한 방문은 금액이 없는 줄 하나로만 남는다 (줄의 금액이 0 인지는 모델이 본다).
        statuses = {row.status for _, row in rows}
        if "failed" in statuses:
            if len(statuses) > 1:
                bad("한 방문에 ok 인 줄과 failed 인 줄이 섞여 있다. 실패한 방문은 failed 인 줄 하나로만 남긴다")
            elif len(rows) > 1:
                bad("실패한 방문은 줄 하나로만 남긴다")
            return
        if len({row.request_hash for _, row in rows}) > 1:
            bad("같은 방문의 줄인데 request_hash 가 서로 다르다")
            return

        # 방문 하나의 몫은 고른 곳의 몫과 "이용하지 않음"의 몫을 더해 1 이다 (10.2절).
        picked = [row for _, row in rows if row.choice_kind != "none"]
        nothing = [row for _, row in rows if row.choice_kind == "none"]
        if not picked:
            if len(nothing) != 1 or abs(nothing[0].counted_share - 1) > SHARE_TOLERANCE:
                bad("'이용하지 않음'인 방문은 counted_share 가 1 인 줄 하나다")
        elif len({row.counted_share for row in picked}) > 1:
            bad("한 방문에서 고른 줄들의 counted_share 가 서로 다르다")
        else:
            share = picked[0].counted_share
            if share > 1 - SHARE_TOLERANCE:
                if nothing:
                    bad("일 년 내내 파는 곳을 고른 방문인데 '이용하지 않음' 줄이 더 있다")
            elif (
                len(nothing) != 1
                or abs(nothing[0].counted_share - (1 - share)) > SHARE_TOLERANCE
                or nothing[0].reason_text != SEASON_GAP_REASON
            ):
                bad(
                    "일부 달에만 파는 곳을 고른 방문에는 '이용하지 않음' 줄이 하나 더 있어야 한다: "
                    f"counted_share 는 1 에서 고른 줄의 몫을 뺀 값, reason_text 는 '{SEASON_GAP_REASON}'"
                )

        entry = saved.get(first.request_hash or "")
        if entry is None:
            return  # 응답 없이 엔진이 정한 "이용하지 않음"이거나, 저장된 응답이 없다고 이미 적은 방문이다
        request, response = entry.request, entry.response
        if request.persona.get("persona_id") != first.persona_id:
            bad("저장된 응답의 요청은 다른 페르소나의 것이다")
        if request.condition.condition_id != first.condition_id:
            bad("저장된 응답의 요청은 다른 조건의 것이다")

        choice = response.choice
        if choice.venue_id is None:
            if picked:
                bad("저장된 응답은 '이용하지 않음'인데 원장에는 업장을 고른 줄이 있다")
            told = nothing
        else:
            candidate = request.candidate(choice.venue_id)
            option = candidate.option(choice.option_id) if candidate else None
            if candidate is None or option is None:
                return  # 응답이 후보 밖을 골랐다. 저장된 응답의 검사에서 이미 적었다.
            if not picked:
                bad("저장된 응답은 업장을 골랐는데 원장에는 업장을 고른 줄이 없다")
                return
            if any(row.venue_id != choice.venue_id for row in picked):
                bad("원장의 업장이 저장된 응답에서 고른 업장과 다르다")
            # 고른 주문의 줄은 금액까지 견준다. 추가 상품은 요청에 할인이 없어 상품, 수량, 단위, 표시가만 견준다
            # (추가 상품에 프로모션 할인을 적용할지는 아직 정하지 않았다. docs/FORMATS.md 12절).
            line_ids = {ordered.product_id for ordered in option.lines}
            addons = {addon.product_id: addon for addon in candidate.addons}
            extra = {
                p.product_id: p.quantity
                for p in choice.addons
                if p.quantity > 0 and p.product_id in addons and p.product_id not in line_ids
            }
            want_lines = sorted(
                (o.product_id, o.quantity, o.unit, o.unit_price, o.discount, o.line_total) for o in option.lines
            )
            want_extra = sorted((pid, qty, addons[pid].unit, addons[pid].unit_price) for pid, qty in extra.items())
            have_lines = sorted(
                (r.product_id or "", r.quantity, r.unit or "", r.list_price, r.discount, r.paid)
                for r in picked
                if r.product_id not in extra
            )
            have_extra = sorted(
                (r.product_id or "", r.quantity, r.unit or "", r.list_price) for r in picked if r.product_id in extra
            )
            if have_lines != want_lines or have_extra != want_extra:
                bad("원장의 줄이 저장된 응답에서 고른 주문과 다르다 (상품, 수량, 단위, 표시가, 할인, 낸 금액을 견준다)")
            # 일부 달에만 파는 곳을 골라 더 생긴 "이용하지 않음" 줄(10.2절)은 이유가 따로라 견주지 않는다.
            told = picked
        answer = (response.reason_labels, response.reason_text, response.used_attributes)
        if any((row.reason_labels, row.reason_text, row.used_attributes) != answer for row in told):
            bad("고른 이유(reason_labels, reason_text, used_attributes)가 저장된 응답과 다르다")

    def _check_calibration(self, run_dir: Path, record: RunRecord) -> None:
        path = run_dir / "calibration.json"
        if not path.is_file():
            return
        calibration = self._load(path, Calibration)
        if calibration is None:
            return
        if record.scenario_id != BASELINE_ID:
            self.error(path, "보정의 대조 결과는 기준 상황의 실행에만 둔다")
        if calibration.run_id != record.run_id:
            self.error(path, "run_id 가 실행 기록과 다르다")
        groups = set(calibration.groups) | set(calibration.uncovered_groups)
        if self.vocab is not None:
            for group in groups - set(self.vocab.customer_group):
                self.error(path, f"고객군 '{group}' 가 값 목록에 없다")
        for group, result in calibration.groups.items():
            for venue_id in result.venues:
                venue = self.venues.get(venue_id)
                if venue is None or venue.is_competitor:
                    self.error(path, f"고객군 '{group}' — '{venue_id}' 가 워커힐 업장 정의에 없다")

    # ── 저장소에 올리면 안 되는 것 ──────────────────────────────────────────

    def _walk(self, folder: Path) -> Iterator[Path]:
        """깃에 올라갈 수 있는 파일을 모두 돌려준다 (깃이 무시하는 것만 건너뛴다)."""
        for path in sorted(folder.iterdir()):
            if path.is_symlink():
                continue  # 깃은 바로 가기가 가리키는 곳의 내용이 아니라 바로 가기만 올린다
            parts = path.relative_to(self.root).parts
            if path.is_dir():
                if ignored_by_git(parts, is_dir=True):
                    continue
                if path.name.lower() == PRIVATE_DIR and parts != (PRIVATE_DIR,):
                    if len(parts) == 1:
                        self.error(
                            path,
                            "내부 자료의 폴더 이름은 소문자 private 이다. 대문자가 섞이면 "
                            "리눅스(자동 검사가 도는 곳)에서는 깃이 이 폴더를 무시하지 않는다",
                        )
                    else:
                        self.error(
                            path,
                            "깃이 무시하는 것은 저장소 맨 위의 private/ 뿐이다. 이 폴더의 파일은 그대로 올라간다. "
                            "내부 자료는 맨 위의 private/ 로 옮긴다",
                        )
                yield from self._walk(path)
            elif path.is_file() and not ignored_by_git(parts, is_dir=False):
                yield path

    def check_nothing_private(self) -> None:
        """깃에 올라갈 수 있는 모든 파일을 훑어, 올리면 안 되는 것이 섞였는지 본다.

        확장자, 크기, 글자 인코딩, 폴더의 깊이에 기대지 않는다. 볼 수 없는 파일은 건너뛰지 않고 오류로 적는다.
        """
        for path in self._walk(self.root):
            self.files_scanned += 1
            parts = path.relative_to(self.root).parts
            suffix = path.suffix.lower()
            folders = set(parts[:-1])
            if "evidence" in folders and folders & {"holdout", "reference"}:
                self.error(path, "떼어 둔 후기와 받은 참고 소스의 후기는 저장소에 올리지 않는다")
            elif "holdout" in folders and (suffix in DATA_SUFFIXES or suffix in TABLE_SUFFIXES):
                # 번호도 주소도 없이 옮겨 적은 후기는 내용으로 알아볼 수 없다. 폴더 이름으로라도 본다.
                self.error(path, "holdout 이라는 폴더에 데이터 파일이 있다. 떼어 둔 후기는 저장소에 올리지 않는다 (private/evidence/holdout/ 에만 둔다)")
            if suffix in OPAQUE_SUFFIXES:
                self.error(
                    path, "안을 검사할 수 없는 형식이다. 저장소의 데이터는 CSV 와 JSON 으로만 두고, 묶은 파일은 올리지 않는다"
                )
                continue
            try:
                size = path.stat().st_size
                if size > MAX_SCAN_BYTES:
                    self.error(path, "100MB 를 넘어 검사하지 못했다. 저장소에 올릴 파일이 아니다")
                    continue
                data = path.read_bytes()
            except OSError as exc:
                self.error(path, f"읽을 수 없어 검사하지 못했다: {exc}")
                continue
            if suffix in DATA_SUFFIXES:
                if size > MAX_DATA_BYTES:
                    self.error(
                        path, "데이터 파일이 5MB 를 넘는다. 기본 데이터나 실행 결과가 아닌지 확인한다 (그런 것은 private/ 에 둔다)"
                    )
                if not _is_utf8(data):
                    self.error(path, "UTF-8 이 아니다. 모든 파일은 UTF-8 로 저장한다 (엑셀이라면 'CSV UTF-8' 로 저장한다)")

            text = _as_utf8(data)
            notes: list[str] = []
            if not _may_hold_examples(parts):
                ids = sorted({m.decode("ascii") for m in PRIVATE_REVIEW_ID_RE.findall(URL_RE.sub(b" ", text))})
                if ids:
                    notes.append(f"H 나 P 로 시작하는 후기 번호가 있다: {', '.join(ids[:5])}")
                if PRIVATE_RUN_RE.search(text) and all(key.search(text) for key in RUN_RECORD_KEY_RES):
                    notes.append(PRIVATE_RUN_NOTE)
            # 5MB 를 넘는 데이터 파일은 위에서 이미 오류로 적었다. 그런 파일의 JSON 까지 풀어 읽지는 않는다.
            found = inspect_content(path.name, suffix, text, parse_json=size <= MAX_DATA_BYTES)
            for note in dict.fromkeys(notes + found.notes):
                self.error(path, note)
            place = tree_path(parts)
            for kind in found.kinds:
                if kind.place is None:
                    self.error(path, f"'{kind.label}'의 모양이다. {kind.where}")
                elif not re.fullmatch(kind.place, place):
                    self.error(path, f"'{kind.label}'의 모양인데 둘 수 없는 자리에 있다. {kind.where}. {FIXTURE_HINT}")

    # ── 전체 ────────────────────────────────────────────────────────────────

    def check_formats(self) -> None:
        """이 폴더를 저장소의 모양으로 보고 데이터 파일의 형식을 검사한다."""
        self.check_layout()
        self.check_venues()
        self.check_evidence()
        self.check_personas()
        self.check_conditions()
        self.check_scenarios()
        self.check_sample_summary()
        self.check_sample_runs()

    def run(self) -> list[Problem]:
        self.check_formats()
        self.check_nothing_private()
        # 테스트의 예시 묶음(tests/fixtures/<이름>/)도 저장소와 같은 형식 검사를 받는다.
        # 자리 규칙을 그 묶음 안의 경로로 봐 주는 만큼, 그 안의 실행 결과도 가상 예시 값으로 돌린 것인지 확인해야 한다.
        # 올리면 안 되는 것은 위에서 이미 모든 파일을 훑었으므로 다시 훑지 않는다.
        fixtures = self.root.joinpath(*FIXTURES)
        for tree in sorted(fixtures.iterdir()) if fixtures.is_dir() else []:
            if not tree.is_dir() or ignored_by_git(tree.relative_to(self.root).parts, is_dir=True):
                continue
            nested = Checker(tree)
            nested.check_formats()
            prefix = tree.relative_to(self.root).as_posix()
            self.problems += [Problem(p.level, f"{prefix}/{p.path}", p.message) for p in nested.problems]
            self.files_checked += nested.files_checked
        return self.problems


def check(root: Path, strict: bool = False) -> list[Problem]:
    """root 아래의 데이터 파일을 검사해 문제를 돌려준다. strict 면 주의도 오류로 본다."""
    problems = Checker(root.resolve()).run()
    if strict:
        problems = [Problem("error", p.path, p.message) for p in problems]
    return problems


def tree_path(parts: tuple[str, ...]) -> str:
    """파일을 둘 수 있는 자리인지 견줄 때 쓰는 경로.

    테스트의 예시 묶음(tests/fixtures/<이름>/)은 저장소와 같은 폴더 모양이라, 그 묶음 안에서의 경로로 본다.
    """
    if parts[:2] == FIXTURES and len(parts) > 3:
        parts = parts[3:]
    return "/".join(parts)


def _may_hold_examples(parts: tuple[str, ...]) -> bool:
    return parts == EXAMPLE_DOC or (parts[0] == "tests" and parts[-1].endswith(".py"))


def _is_utf8(data: bytes) -> bool:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _as_utf8(data: bytes) -> bytes:
    """표시를 찾기 좋게 글자를 UTF-8 로 맞춘다.

    엑셀의 "유니코드 텍스트"처럼 UTF-16 으로 저장한 파일도 읽으려는 것이다.

    - 맨 앞에 UTF-16 의 표시(BOM)가 있으면 UTF-16 이다.
    - 표시가 없어도, UTF-8 로 읽히지 않는데 0 이 들어 있으면 UTF-16 으로 본다 (UTF-8 이나 cp949 로 적은 글에는 0 이 없다).
      영어 글자와 줄바꿈의 0 이 홀수 자리에 많으면 작은 끝(LE), 짝수 자리에 많으면 큰 끝(BE)이다.
    - 그 밖에는 그대로 두고 0 만 지운다. 영어 글자뿐인 UTF-16 은 0 만 지워도 글자가 이어진다.

    그림 같은 이진 파일은 엉뚱하게 풀리지만, 그런 파일에서 찾을 표시는 없으니 상관없다.
    """
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace").encode("utf-8")
    if b"\x00" not in data:
        return data
    if not _is_utf8(data):
        head = data[:65536]
        encoding = "utf-16-le" if head[1::2].count(0) >= head[0::2].count(0) else "utf-16-be"
        return data.decode(encoding, errors="replace").encode("utf-8")
    return data.replace(b"\x00", b"")


@dataclass
class Found:
    """파일 하나의 이름과 내용에서 알아낸 것."""

    kinds: list[Kind] = field(default_factory=list)  # 자리가 정해진 종류
    notes: list[str] = field(default_factory=list)  # 그 밖에 오류로 적을 문장


def inspect_content(name: str, suffix: str, text: bytes, parse_json: bool = True) -> Found:
    """파일의 이름과 내용으로, 자리가 정해진 종류인지와 올리면 안 되는 값이 들었는지 알아본다.

    - 표: CSV·TSV·글 파일의 첫 줄과 마크다운 표의 머리글을 열 이름으로 본다.
    - JSON: 맨 위뿐 아니라 안쪽의 묶음을 모두 본다. 한 줄에 하나씩 적은 파일(.jsonl)은 줄마다 읽는다.
    """
    found = Found()
    named = NAME_MARKS.get(name.lower())
    if named is not None:
        found.kinds.append(named)
    if BASE_DATA_NAME_PART in name:
        found.kinds.append(BASE_DATA)
    if suffix in TABLE_SUFFIXES:
        cells = _first_line_cells(text)
        # 글 파일(.txt)은 첫 줄이 여러 칸으로 나뉠 때만 표로 본다. 한 칸이면 표가 아니라 글의 첫 문장이다.
        if suffix != ".txt" or len(cells) > 1:
            found.kinds += _kinds_of_names(cells, loose=True)
    elif suffix in MARKDOWN_SUFFIXES:
        # 문서는 기본 데이터의 열을 글로 설명할 수 있다. 그래서 표의 머리글이 그 이름과 똑같을 때만 본다.
        for header in _markdown_headers(text):
            found.kinds += _kinds_of_names(header, loose=False)
    elif suffix in JSON_SUFFIXES and parse_json:
        for node in _dicts_in(_json_values(suffix, text)):
            _inspect_dict(node, found)
    found.kinds = list(dict.fromkeys(found.kinds))
    found.notes = list(dict.fromkeys(found.notes))
    return found


def _kinds_of_names(names: frozenset[str], loose: bool) -> list[Kind]:
    """표의 열 이름이나 JSON 묶음의 키로 종류를 알아본다."""
    kinds = [kind for marks, kind in NAME_SET_MARKS if marks <= names]
    if names & ADDRESS_COLUMNS and names & REVIEW_HINT_COLUMNS:
        kinds.append(URL_LIST)
    # 집계하면 열 이름 뒤에 말이 붙기도 한다. 그래서 데이터 파일에서는 이름에 그 말이 들어 있기만 해도 본다.
    if any(column in name if loose else column == name for column in BASE_DATA_COLUMNS for name in names):
        kinds.append(BASE_DATA)
    return kinds


def _inspect_dict(node: dict, found: Found) -> None:
    """JSON 의 묶음 하나를 본다."""
    found.kinds += _kinds_of_names(frozenset(str(key).strip().lower() for key in node), loose=True)
    columns = node.get("columns")
    if isinstance(columns, list):  # 표를 columns 와 data 로 나눠 적은 JSON
        found.kinds += _kinds_of_names(frozenset(str(column).strip().lower() for column in columns), loose=True)
    if node.get("data_mode") == "private" and "run_id" in node:
        found.notes.append(PRIVATE_RUN_NOTE)
    if node.get("base_profile"):  # 키만 있고 비어 있는 것(null, 빈 묶음)은 값이 없는 것이다
        found.notes.append(BASE_PROFILE_NOTE)
    if node.get("overridden_by_private"):
        found.notes.append(PRIVATE_LAYER_NOTE)


def _first_line_cells(text: bytes) -> frozenset[str]:
    """표로 본 파일의 첫 줄에 있는 열 이름 (소문자로).

    UTF-8 로 읽히지 않으면 한국어 엑셀이 기본으로 쓰는 cp949 로 읽어 본다. 한글로 된 열 이름을 알아보려는 것이다.
    """
    raw = text.lstrip(BOM).split(b"\n", 1)[0]
    try:
        first = raw.decode("utf-8")
    except UnicodeDecodeError:
        first = raw.decode("cp949", errors="replace")
    delimiter = "\t" if first.count("\t") > first.count(",") else ","
    try:
        row = next(csv.reader([first], delimiter=delimiter), [])
    except csv.Error:
        return frozenset()
    return frozenset(cell.strip().lower() for cell in row)


# 마크다운 표에서 머리글 바로 아래에 오는 구분선 (예: |---|---|).
MARKDOWN_RULE_RE = re.compile(r"^\s*\|?\s*:?-{3,}")


def _markdown_headers(text: bytes) -> list[frozenset[str]]:
    """마크다운 표의 머리글들 (소문자로). 바로 아래 줄이 구분선인 줄을 머리글로 본다."""
    lines = text.decode("utf-8", errors="replace").splitlines()
    headers = []
    for line, below in zip(lines, lines[1:], strict=False):
        if "|" in line and MARKDOWN_RULE_RE.match(below):
            cells = (cell.strip().strip("`*_ ").lower() for cell in line.strip().strip("|").split("|"))
            headers.append(frozenset(cell for cell in cells if cell))
    return headers


def _json_values(suffix: str, text: bytes) -> list[Any]:
    """파일에 든 JSON 값들. `.json` 은 값 하나이고, 한 줄에 하나씩 적은 파일은 줄마다 값이 하나다."""
    decoded = text.decode("utf-8-sig", errors="replace")
    if suffix == ".json":
        try:
            return [json.loads(decoded)]
        except (ValueError, RecursionError):
            pass  # 이름은 .json 인데 한 줄에 하나씩 적은 파일일 수 있다. 아래에서 줄마다 읽어 본다
    values = []
    for line in decoded.splitlines():
        line = line.strip()
        if line[:1] in ("{", "["):
            try:
                values.append(json.loads(line))
            except (ValueError, RecursionError):
                continue  # 읽히지 않는 JSON 은 형식 검사가 따로 적는다
    return values


def _dicts_in(values: list[Any]) -> Iterator[dict]:
    """JSON 값 안의 묶음을 모두 돌려준다 (맨 위의 것, 목록 안의 것, 묶음 안의 것)."""
    stack = list(values)
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            yield node
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def _location(loc: tuple) -> str:
    text = ""
    for part in loc:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += ("." if text else "") + str(part)
    return text


def _korean(err: dict[str, Any]) -> str:
    """pydantic 의 오류를 한국어 문장으로 바꾼다. 모르는 종류는 원문을 그대로 둔다."""
    kind = err["type"]
    ctx = err.get("ctx") or {}
    value = err.get("input")
    if kind == "json_invalid":
        return f"JSON 으로 읽을 수 없다: {ctx.get('error', err['msg'])}"
    if kind == "missing":
        return "키가 빠졌다"
    if kind == "extra_forbidden":
        return "약속에 없는 키다 (오타인지 확인한다)"
    if kind in ("literal_error", "enum"):
        return f"쓸 수 없는 값 {value!r} (쓸 수 있는 값: {ctx.get('expected', '')})"
    if kind == "string_pattern_mismatch":
        return f"{value!r} 의 모양이 규칙과 다르다"
    if kind in ("int_type", "float_type") and isinstance(value, str):
        return f"{value!r} 는 글자다. 숫자는 따옴표 없이 적는다"
    if kind in ("int_type", "int_from_float") and isinstance(value, float):
        return f"{value!r} 는 정수가 아니다. 소수점 없이 적는다"
    if kind in ("int_parsing", "int_type", "int_from_float", "float_parsing", "float_type"):
        return f"{value!r} 는 숫자가 아니다"
    if kind == "finite_number":
        return f"{value!r} 는 끝이 있는 수가 아니다 (Infinity 와 NaN 은 쓸 수 없다)"
    if kind in ("bool_type", "bool_parsing"):
        return f"{value!r} 는 참·거짓이 아니다. 따옴표 없이 true 나 false 로 적는다"
    if kind in ("string_type", "string_too_short"):
        return "글자가 있어야 하는데 비어 있거나 글자가 아니다"
    if kind in ("date_from_datetime_parsing", "date_parsing", "date_type", "date_from_datetime_inexact"):
        return f"{value!r} 는 날짜가 아니다 (예: 2026-11-13)"
    if kind in ("datetime_type", "datetime_parsing", "datetime_from_date_parsing"):
        return f"{value!r} 는 날짜와 시각이 아니다 (예: 2026-11-17T10:15:00+09:00)"
    if kind == "timezone_aware":
        return f"{value!r} 에 시간대가 없다 (예: 2026-11-17T10:15:00+09:00)"
    if kind in ("greater_than_equal", "greater_than", "less_than_equal", "less_than"):
        return f"{value!r} 는 쓸 수 있는 범위를 벗어난다"
    if kind in ("too_short", "too_long"):
        return "항목의 수가 맞지 않는다 (하나 이상 있어야 하는 목록이 비어 있는지 확인한다)"
    if kind == "list_type":
        return "목록([ ])이어야 한다"
    if kind in ("dict_type", "model_type", "model_attributes_type"):
        return "묶음({ })이어야 한다"
    if kind == "union_tag_invalid":
        return f"op 에 쓸 수 없는 값 {ctx.get('tag')!r} (쓸 수 있는 값: {ctx.get('expected_tags', '')})"
    if kind == "value_error":
        return str(err["msg"]).removeprefix("Value error, ")
    return str(err["msg"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="데이터 파일이 형식 약속(docs/FORMATS.md)에 맞는지 검사한다.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="검사할 폴더 (기본: 저장소 맨 위)")
    parser.add_argument("--strict", action="store_true", help="다 만든 뒤의 기준으로 검사한다 (주의도 오류로 본다)")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = args.root.resolve()
    if not root.is_dir():
        print(f"폴더가 없다: {root}")
        return 2

    checker = Checker(root)
    problems = checker.run()
    if args.strict:
        problems = [Problem("error", p.path, p.message) for p in problems]
    for problem in problems:
        print(problem)
    errors = sum(1 for p in problems if p.level == "error")
    warnings = len(problems) - errors
    print(
        f"형식을 본 데이터 파일 {checker.files_checked}개, 훑어본 파일 {checker.files_scanned}개: "
        f"오류 {errors}건, 주의 {warnings}건"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
