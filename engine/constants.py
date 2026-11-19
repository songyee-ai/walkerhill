"""결정 상수를 읽는다 (docs/FORMATS.md 6.1절, T210).

결정 상수는 엔진 코드와 같은 저장소의 `engine/constants.json` 에 있다. `--root` 로 다른 폴더의 자료를 돌려도 이 파일을 쓴다
(엔진 코드가 그 폴더의 것이 아닌 것과 같다). 엔진은 이 파일의 해시를 실행 기록의 `inputs.constants` 에 남기고,
기준 실행 뒤에 바뀌면 상황을 돌리지 않는다.
"""

from functools import cache
from pathlib import Path

from engine.formats.conditions import ConditionBundle
from engine.formats.constants import ConstantsFile, ConstantValue, UsedConstant
from engine.formats.io import read_model

CONSTANTS_PATH = Path(__file__).resolve().parent / "constants.json"


@cache
def load_constants(path: Path = CONSTANTS_PATH) -> ConstantsFile:
    return read_model(path, ConstantsFile)


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
            source=c.source,
            checked_on=c.checked_on,
            file=file,
        )
        for c in found.constants
        if c.in_use
    ]


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
            source=None,
            checked_on=split.decided_on,
            file="engine/conditions.json",
        )
        for split in bundle.assumed_splits
    ]
    if summary_constants is not None and summary_file is not None:
        used += _used(summary_constants, summary_file)
    return used
