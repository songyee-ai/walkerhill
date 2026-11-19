"""결정 상수 (docs/FORMATS.md 6.1절).

시뮬레이션 결과에 영향을 주는 엔진의 숫자를 값과 근거와 함께 한 파일(`engine/constants.json`)에 적는다.
엔진은 이 파일의 값을 쓰고, 실행마다 쓴 상수를 실행 기록의 `constants` 에 값까지 남긴다 (11-19 wilstein91 결정, T210).
프로그램 동작에만 쓰는 숫자(호출 시간 제한 같은 것)는 넣지 않는다.
"""

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from engine.formats.codes import FormatModel, Grade, Id, Text, has_duplicates

# 상수의 값. 숫자이거나 예·아니오다. 나누는 비율처럼 갈래마다 값이 있으면 갈래 이름을 키로 둔다 (실행 기록에서만).
ConstantValue = bool | int | float


class Constant(FormatModel):
    """결정 상수 하나."""

    constant_id: Id
    name: Text
    value: ConstantValue
    # 값의 단위 (원, 개, 배, %p, 팀, 명). 예·아니오이면 null 이다.
    unit: Text | None
    # 이 값을 쓰는 곳 (코드의 함수나 절).
    used_in: Text
    grade: Grade
    # 근거의 출처 (자료 이름이나 주소). 그 대상을 직접 다룬 자료면 그 등급으로 적는다. 다른 곳에서 잰 범위를 빌려 와 정한 값은
    # `assumption` 으로 적고 여기에 빌려 온 자료를 적는다. 빌려 온 자료 없이 팀이 정한 값이면 null 이다 (FORMATS 2절·6.1절).
    source: Text | None
    # 출처를 확인한 날. 출처가 없으면 정한 날이다.
    checked_on: date
    note: Text
    owner: Text


class ConstantsFile(FormatModel):
    """결정 상수 파일 `engine/constants.json`."""

    format_version: Literal[1]
    constants: list[Constant] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> Self:
        if has_duplicates([c.constant_id for c in self.constants]):
            raise ValueError("constant_id 가 겹친다")
        return self

    def value(self, constant_id: str) -> ConstantValue:
        for constant in self.constants:
            if constant.constant_id == constant_id:
                return constant.value
        raise KeyError(f"결정 상수 '{constant_id}' 가 engine/constants.json 에 없다")


class UsedConstant(FormatModel):
    """실행 기록에 남기는, 그 실행이 쓴 결정 상수 하나. 어느 파일에 적힌 값인지(`file`)를 함께 적는다."""

    constant_id: Id
    name: Text
    value: ConstantValue | dict[str, float]
    unit: Text | None
    grade: Grade
    source: Text | None
    checked_on: date
    file: Text
