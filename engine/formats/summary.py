"""기본 데이터 집계 파일 (docs/FORMATS.md 8절).

진짜 집계 파일은 `private/base/summary.csv` 에만 둔다. 저장소에는 같은 열을 가진
가상 예시 값(`data/samples/base_summary.csv`)만 둔다.
"""

from typing import Literal, Self

from pydantic import Field, model_validator

from engine.formats.codes import DayType, FormatModel, Id, Meal, Month, Occasion, Text, Won
from engine.formats.io import blank_to_none

SUMMARY_COLUMNS = [
    "customer_group",
    "venue_id",
    "product_id",
    "occasion",
    "meal",
    "day_type",
    "month",
    "unit",
    "quantity",
    "paid",
    "revenue_net",
    "price_unconfirmed",
]

# `revenue_net` 은 줄마다 반올림한 값을 더한 것이라 `paid ÷ 1.1` 과 조금 어긋날 수 있다. 이만큼까지는 같은 것으로 본다.
NET_TOLERANCE_RATIO = 0.001


class SummaryRow(FormatModel):
    """한 달 동안 "그 고객군이 그 상품을 그 조건에서 산 것"의 합. 일 년 전체는 엔진이 달을 더해서 낸다."""

    customer_group: Text
    venue_id: Id
    product_id: Id
    occasion: Occasion
    meal: Meal | None
    day_type: DayType
    month: Month
    unit: Text
    quantity: float = Field(ge=0)
    # 고객이 낸 금액의 합 (세금 포함). 가격이 비어 있는 상품의 단가는 paid ÷ quantity 로 채운다.
    paid: Won
    # 세금을 뺀 매출의 합. 낸 금액 ÷ 1.1 이다.
    revenue_net: Won
    price_unconfirmed: Literal["Y", "N"]

    @model_validator(mode="after")
    def _amounts(self) -> Self:
        if abs(self.paid / 1.1 - self.revenue_net) > max(1.0, self.paid * NET_TOLERANCE_RATIO):
            raise ValueError("revenue_net 이 paid ÷ 1.1 과 다르다 (paid 는 세금 포함, revenue_net 은 세금을 뺀 값이다)")
        # 금액이 작으면 위의 허용 폭(1원)에 묻힌다. 팔린 것이나 낸 금액이 없는데 매출만 있는 줄은 따로 잡는다.
        if self.quantity == 0 and (self.paid or self.revenue_net):
            raise ValueError("quantity 가 0 인데 paid 나 revenue_net 이 있다")
        if self.paid == 0 and self.revenue_net:
            raise ValueError("paid 가 0 인데 revenue_net 이 있다")
        return self

    def unit_price(self) -> float | None:
        """고객이 낸 단가 (세금 포함). 팔린 것이 없으면 None."""
        return self.paid / self.quantity if self.quantity else None

    @classmethod
    def from_row(cls, row: dict[str, str]) -> Self:
        data: dict[str, object] = dict(row)
        data["meal"] = blank_to_none(row.get("meal"))
        return cls.model_validate(data)
