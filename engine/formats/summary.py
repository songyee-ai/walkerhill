"""기본 데이터 집계 파일 (docs/FORMATS.md 8절).

진짜 집계 파일은 `private/base/summary.csv` 에만 둔다. 저장소에는 같은 열을 가진
가상 예시 값(`data/samples/base_summary.csv`)만 둔다.
"""

from typing import Literal, Self

from pydantic import Field

from engine.formats.codes import DayType, FormatModel, Id, Meal, Occasion, Text, Won
from engine.formats.io import blank_to_none

SUMMARY_COLUMNS = [
    "customer_group",
    "venue_id",
    "product_id",
    "occasion",
    "meal",
    "day_type",
    "unit",
    "quantity",
    "revenue_net",
    "price_unconfirmed",
]


class SummaryRow(FormatModel):
    """기준 기간 전체에서 "그 고객군이 그 상품을 그 조건에서 산 것"의 합."""

    customer_group: Text
    venue_id: Id
    product_id: Id
    occasion: Occasion
    meal: Meal | None
    day_type: DayType
    unit: Text
    quantity: float = Field(ge=0)
    revenue_net: Won
    price_unconfirmed: Literal["Y", "N"]

    @classmethod
    def from_row(cls, row: dict[str, str]) -> Self:
        data: dict[str, object] = dict(row)
        data["meal"] = blank_to_none(row.get("meal"))
        return cls.model_validate(data)
