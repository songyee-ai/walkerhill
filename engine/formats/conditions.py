"""방문 조건 묶음 (docs/FORMATS.md 6절).

집계하려고 미리 정해 둔 방문 조건의 목록이다. 페르소나마다 이 목록의 조건마다 한 번씩 돌린다.
"""

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from engine.formats.codes import (
    DayType,
    FormatModel,
    Grade,
    Id,
    Meal,
    Month,
    Occasion,
    Stay,
    Text,
    has_duplicates,
)

# 화면에서 조건을 직접 넣어 한 번만 돌릴 때 붙이는 condition_id 의 머리말 (docs/FORMATS.md 10.2절).
# 묶음의 조건에는 쓰지 않는다. 이 머리말이 붙은 조건은 묶음에 없어도 되고 가중치도 없다.
MANUAL_CONDITION_PREFIX = "manual-"


class Condition(FormatModel):
    """방문 조건 하나. 묶음의 조건에는 인원과 예산을 넣지 않는다 (페르소나의 값을 쓴다)."""

    condition_id: Id
    occasion: Occasion
    meal: Meal | None
    day_type: DayType
    stay: Stay | None
    month: Month | None

    @model_validator(mode="after")
    def _meal(self) -> Self:
        if self.occasion == "meal" and self.meal is None:
            raise ValueError("식사 조건에는 meal 이 있어야 한다")
        if self.occasion != "meal" and self.meal is not None:
            raise ValueError("식사가 아닌 조건의 meal 은 null 이다")
        return self


class AssumedSplit(FormatModel):
    """기본 데이터로 나눌 수 없어 팀이 정한 비율."""

    split_id: Id
    applies_when: Text
    parts: dict[str, float]
    grade: Grade
    decided_on: date
    note: str

    @model_validator(mode="after")
    def _sum(self) -> Self:
        if not self.parts:
            raise ValueError("parts 가 비어 있다")
        if any(value < 0 for value in self.parts.values()):
            raise ValueError("parts 에 음수가 있다")
        if abs(sum(self.parts.values()) - 1) > 1e-9:
            raise ValueError("parts 의 값을 더하면 1 이어야 한다")
        return self


class ConditionBundle(FormatModel):
    format_version: Literal[1]
    conditions: list[Condition] = Field(min_length=1)
    assumed_splits: list[AssumedSplit]

    @model_validator(mode="after")
    def _unique(self) -> Self:
        if has_duplicates([c.condition_id for c in self.conditions]):
            raise ValueError("condition_id 가 겹친다")
        if has_duplicates([s.split_id for s in self.assumed_splits]):
            raise ValueError("split_id 가 겹친다")
        fixed = [c.condition_id for c in self.conditions if c.month is not None]
        if fixed:
            raise ValueError(f"묶음의 조건은 month 를 null 로 둔다 (일 년 전체로 본다): {fixed}")
        # 2026-11-13 결정: 기본 데이터에 투숙 여부가 없어 비율을 낼 수 없으므로 묶음에 넣지 않는다.
        staying = [c.condition_id for c in self.conditions if c.stay is not None]
        if staying:
            raise ValueError(f"묶음의 조건은 stay 를 null 로 둔다 (기본 데이터로 투숙 여부의 비율을 낼 수 없다): {staying}")
        # 2026-11-13 결정: 조식은 고를 업장이 하나뿐이라 묶음에 넣지 않는다. 조식 매출은 대조에서 뺀다.
        breakfast = [c.condition_id for c in self.conditions if c.meal == "breakfast"]
        if breakfast:
            raise ValueError(f"묶음에는 조식 조건을 넣지 않는다 (조식 매출은 대조에서 뺀다): {breakfast}")
        manual = [c.condition_id for c in self.conditions if c.condition_id.startswith(MANUAL_CONDITION_PREFIX)]
        if manual:
            raise ValueError(
                f"'{MANUAL_CONDITION_PREFIX}' 로 시작하는 condition_id 는 화면에서 직접 넣은 조건에만 쓴다: {manual}"
            )
        return self

    def condition(self, condition_id: str) -> Condition | None:
        return next((c for c in self.conditions if c.condition_id == condition_id), None)
