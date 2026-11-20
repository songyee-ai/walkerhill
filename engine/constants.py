"""결정 상수를 읽는다 (docs/FORMATS.md 6.1절, T210).

결정 상수는 엔진 코드와 같은 저장소의 `engine/constants.json` 에 있다. `--root` 로 다른 폴더의 자료를 돌려도 이 파일을 쓴다
(엔진 코드가 그 폴더의 것이 아닌 것과 같다). 엔진은 이 파일의 해시를 실행 기록의 `inputs.constants` 에 남기고,
기준 실행 뒤에 바뀌면 상황을 돌리지 않는다.
해시는 파일 전체가 아니라 결과를 바꾸는 부분(식별자, 값, 단위, 쓰는지)으로만 낸다. 출처·설명·주인만 고치면 해시가 그대로라
기준 상황을 다시 돌리지 않아도 된다 (11-20 wilstein91 결정, T214).
"""

import hashlib
import json
from functools import cache
from pathlib import Path

from engine.formats.conditions import ConditionBundle
from engine.formats.constants import ConstantsFile, ConstantValue, Range, UsedConstant
from engine.formats.io import read_model

CONSTANTS_PATH = Path(__file__).resolve().parent / "constants.json"


@cache
def load_constants(path: Path = CONSTANTS_PATH) -> ConstantsFile:
    return read_model(path, ConstantsFile)


def values_hash(path: Path = CONSTANTS_PATH) -> str:
    """결정 상수 파일의 해시. 결과를 바꾸는 부분만 본다 (모듈 설명). 고친 파일을 바로 보도록 캐시하지 않고 다시 읽는다."""
    found = read_model(path, ConstantsFile)
    rows = sorted(
        [c.constant_id, c.value.model_dump() if isinstance(c.value, Range) else c.value, c.unit, c.in_use] for c in found.constants
    )
    text = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def constant(constant_id: str) -> ConstantValue:
    """결정 상수 하나의 값. 파일에 없으면 KeyError 다."""
    return load_constants().value(constant_id)


def _used(found: ConstantsFile, file: str) -> list[UsedConstant]:
    return [
        UsedConstant(
            constant_id=c.constant_id,
            name=c.name,
            value=c.value,
            unit=c.unit,
            grade=c.grade,
            sources=c.sources,
            checked_on=c.checked_on,
            file=file,
        )
        for c in found.constants
        if c.in_use
    ]


def used_from(found: ConstantsFile, file: str) -> list[UsedConstant]:
    """한 상수 파일에서 엔진이 쓰는 것(`in_use`)을 실행 기록에 남길 모양으로 (추정한 상수 파일 등)."""
    return _used(found, file)


def used_constants(
    bundle: ConditionBundle, summary_constants: ConstantsFile | None = None, summary_file: str | None = None
) -> list[UsedConstant]:
    """실행 기록에 남길 결정 상수: `engine/constants.json` 가운데 엔진이 지금 쓰는 것(`in_use`), 방문 조건 묶음의 나누는 비율(`assumed_splits`),
    그리고 집계 파일 옆의 상수 파일(`summary_constants`, 한 개당 인원처럼 집계를 만들 때 쓴 값)이 있으면 그 모두.
    """
    used = _used(load_constants(), "engine/constants.json")
    used += [
        UsedConstant(
            constant_id=split.split_id,
            name=split.applies_when,
            value=dict(split.parts),
            unit=None,
            grade=split.grade,
            sources=[],
            checked_on=split.decided_on,
            file="engine/conditions.json",
        )
        for split in bundle.assumed_splits
    ]
    if summary_constants is not None and summary_file is not None:
        used += _used(summary_constants, summary_file)
    return used
