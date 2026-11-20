"""집계 파일 옆의 상수 파일 (docs/FORMATS.md 6.1절 "집계 파일 옆의 상수 파일", T213).

집계를 만들 때 쓴 값(상품 한 개당 인원)을 근거와 함께 `ConstantsFile` 모양으로 적는다.
- 기본 데이터: `build_summary` 가 `private/base/summary_constants.json` 에 쓴다. 값은 `private/` 에만 남는다.
- 가상 예시: `make_sample --constants` 가 `data/samples/base_summary_constants.json` 에 쓴다. 공개된 업장 정의의 값만 쓴다.

`1인` 단위 상품은 수량이 곧 인원이라(FORMATS 8절의 정의) 상수로 적지 않는다.
사람이 아닌 상품(포장·추가 상품)의 빈 칸을 엔진이 어떻게 세는지는 엔진 상수(`engine/constants.json`)에 있다.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.formats.constants import ConstantsFile

OWNER = "hojitea-ui"


def load_venues(venues_dir: Path) -> dict[str, dict]:
    """venue_id → 업장 정의."""
    return {v["venue_id"]: v for v in (json.loads(f.read_text(encoding="utf-8")) for f in sorted(venues_dir.glob("*.json")))}


def product_source(venue: dict, product: dict) -> tuple[dict, str]:
    """상품의 출처(없으면 업장의 기본 출처)를 상수의 출처 자료 하나(`SourceRef`)와 그 확인일로 돌려준다. 업장 정의의 출처는 공식 자료다."""
    source_id = product.get("source_id") or venue["default_source_id"]
    source = next(s for s in venue["sources"] if s["source_id"] == source_id)
    return {"title": source["title"], "kind": "official", "url": source["url"]}, source["checked_on"]


def people_constant(venue: dict, product: dict, value: float, grade: str, sources: list[dict], checked_on: str,
                    note: str, used_in: str) -> dict:
    return {
        "constant_id": f"people-per-unit-{venue['venue_id']}-{product['product_id']}",
        "name": f"{venue['name']} {product['name']} 한 개당 인원",
        "value": value,
        "unit": "명",
        "used_in": used_in,
        "grade": grade,
        "sources": sources,
        "checked_on": checked_on,
        "note": note,
        "owner": OWNER,
    }


def write_constants(path: Path, constants: list[dict]) -> None:
    """형식(`ConstantsFile`)을 확인하고 쓴다. 상수가 하나도 없으면 쓰지 않는다 (형식이 하나 이상을 요구한다)."""
    if not constants:
        return
    data = {"format_version": 1, "constants": constants}
    ConstantsFile.model_validate(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 윈도우에서도 줄바꿈을 LF 로 둔다 (다시 만들 때 저장소의 파일과 차이가 생기지 않게)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
