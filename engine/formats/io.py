"""파일을 읽고 쓰는 공통 규칙 (docs/FORMATS.md 2절).

- 모든 파일은 UTF-8, 줄바꿈은 LF 다.
- CSV 는 엑셀에서 한글이 깨지지 않도록 BOM 을 붙인다 (`utf-8-sig`).
- CSV 의 빈 칸은 "값이 없다"는 뜻이고, 한 칸의 여러 값은 세미콜론으로 나눈다.
"""

import csv
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

CSV_ENCODING = "utf-8-sig"
LIST_SEPARATOR = ";"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_model[M: BaseModel](path: Path, model: type[M]) -> M:
    """JSON 파일을 읽어 그 형식의 모델로 돌려준다. 형식에 맞지 않으면 pydantic 의 ValidationError 가 난다.

    파일에 적힌 그대로 엄격하게 본다. 따옴표로 감싼 숫자나 참·거짓, 소수점이 붙은 정수,
    시간대가 빠진 시각은 받지 않는다. 느슨하게 받으면 PC 마다 다른 모양의 파일이 통과해 버린다.
    """
    return model.model_validate_json(path.read_bytes(), strict=True)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def read_csv(path: Path, columns: list[str]) -> list[dict[str, str]]:
    """CSV 를 읽어 줄마다 사전으로 돌려준다. 머리글이 약속한 열과 다르면 오류를 낸다."""
    with path.open(encoding=CSV_ENCODING, newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        if header != columns:
            missing = [c for c in columns if c not in header]
            extra = [c for c in header if c not in columns]
            detail = []
            if missing:
                detail.append(f"빠진 열 {missing}")
            if extra:
                detail.append(f"약속에 없는 열 {extra}")
            if not detail:
                detail.append("열의 순서가 다르다")
            raise ValueError("머리글이 약속과 다르다: " + ", ".join(detail))
        rows = []
        for number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{number}번째 줄의 칸 수가 머리글과 다르다")
            rows.append(row)
        return rows


def write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=CSV_ENCODING, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: _to_cell(row.get(c)) for c in columns})


def blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def split_list(value: str | None) -> list[str]:
    """세미콜론으로 나눈 칸을 목록으로 바꾼다. 빈 칸은 빈 목록이다."""
    if value is None or not value.strip():
        return []
    return [part.strip() for part in value.split(LIST_SEPARATOR) if part.strip()]


def join_list(values: list[str]) -> str:
    return LIST_SEPARATOR.join(values)


def _to_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return join_list([str(v) for v in value])
    return str(value)
