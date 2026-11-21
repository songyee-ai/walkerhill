"""결정 상수 (docs/FORMATS.md 6.1절).

시뮬레이션 결과에 영향을 주는 엔진의 숫자를 값과 근거와 함께 한 파일(`engine/constants.json`)에 적는다.
엔진은 이 파일의 값을 쓰고, 실행마다 쓴 상수를 실행 기록의 `constants` 에 값까지 남긴다 (11-19 wilstein91 결정, T210).
프로그램 동작에만 쓰는 숫자(호출 시간 제한 같은 것)는 넣지 않는다.
"""

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from engine.formats.codes import MATERIAL_STRENGTH, FormatModel, Grade, Id, MaterialKind, Text, has_duplicates


class Range(FormatModel):
    """값이 하나가 아니라 범위인 상수 (예: 15 ~ 20%, 가격 탄력성 −1.0 ~ −0.7). 4단계에서 범위 안의 값을 바꿔 가며 돌린다 (11-19 wilstein91 결정)."""

    min: float
    max: float

    @model_validator(mode="after")
    def _order(self) -> Self:
        if self.min > self.max:
            raise ValueError("범위의 min 이 max 보다 크다")
        return self


class SourceRef(FormatModel):
    """결정 상수의 출처 자료 하나 (11-20 wilstein91 결정, T214). 화면이 "설계 가정 · 학술 자료"처럼 등급과 자료의 종류를 함께 보이게 한다."""

    # 자료의 이름. 논문은 저자·연도·학술지(권·호), 기사·보고서는 매체와 날짜를 적는다.
    title: Text
    kind: MaterialKind
    # 원문을 여는 주소. 정확한 주소가 없으면 null 이고, 아는 만큼(도메인 등)은 title 에 적는다.
    url: Text | None


def _strongest_first(sources: list[SourceRef]) -> list[SourceRef]:
    strengths = [MATERIAL_STRENGTH[s.kind] for s in sources]
    if strengths != sorted(strengths, reverse=True):
        raise ValueError("sources 는 센 자료부터 적는다 (공식 > 학술 자료 = 통계 > 업계 보고서 = 기사 > 직접 잰 값)")
    return sources


# 상수의 값. 숫자, 예·아니오, 범위({"min", "max"}) 가운데 하나다. 나누는 비율처럼 갈래마다 값이 있으면 갈래 이름을 키로 둔다 (실행 기록에서만).
ConstantValue = bool | int | float | Range


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
    # 근거의 출처 자료들 (센 것부터). 그 대상을 직접 다룬 자료면 그 등급으로 적고 그 종류의 자료가 목록에 있어야 한다 (형식 검사).
    # 다른 곳에서 잰 범위를 빌려 와 정한 값은 `assumption` 으로 적고 여기에 빌려 온 자료를 적는다.
    # 빌려 온 자료 없이 팀이 정한 값이면 빈 목록이다 (FORMATS 2절·6.1절. 11-20 에 글 한 줄 `source` 에서 바꿈, T214).
    sources: list[SourceRef]
    # 출처를 확인한 날. 출처가 없으면 정한 날이다.
    checked_on: date
    note: Text
    owner: Text
    # 엔진이 지금 이 값을 쓰는가. 정해 두었지만 아직 쓰지 않는 값(다음 단계에서 쓸 값)은 false 이고 실행 기록에 남지 않는다.
    in_use: bool = True

    @model_validator(mode="after")
    def _sources(self) -> Self:
        _strongest_first(self.sources)
        return self


class ConstantsFile(FormatModel):
    """결정 상수 파일: 엔진의 `engine/constants.json` 과, 집계 파일 옆의 `summary_constants.json` (6.1절)."""

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
    # 11-20 전의 실행 기록에는 이 칸이 없다 (빈 목록으로 읽는다. 아래 `source` 와 같은 임시 호환).
    sources: list[SourceRef] = Field(default_factory=list)
    checked_on: date
    file: Text
    # 이 실행의 계산에 실제로 쓰였는가 (11-20 wilstein91 결정, T212·T130 ②). 가르는 규칙은 `engine/constants.py` 의 `RunUse` 와 FORMATS 10.1절.
    # "값을 바꿨다면 결과가 달라졌는가"가 아니다. 이 칸이 생기기 전(11-20)의 실행 기록에는 없어 null 로 읽는다 (모름).
    applied: bool | None = None
    # 11-20 전의 실행 기록은 출처를 글 한 줄(`source`)로 적었고, 그때 기록에 남은 상수는 모두 null 이었다. 읽을 때만 받고 쓰지 않는다.
    # 임시 호환이다 (`CLAUDE.md` "임시 허용"). 없애는 조건과 확인은 진행 문서 T212 의 완료 조건에 있다.
    source: None = Field(default=None, exclude=True)
