"""매출 변화 나누기 `changes.json` (docs/FORMATS.md 10.6절, T210).

기준 실행과 상황 실행을 방문(페르소나 × 조건)마다 견줘, 워커힐 업장마다 가상 매출의 변화를 다섯 갈래로 나눈다.
갈래를 모두 더하면 그 업장의 변화와 같다 (남는 금액이 없다). 금액은 원장의 `weighted_revenue` 를 더한 것이라 세금을 뺀 가상 매출이다.

- 새로 들어온 매출 (`new`): 기준에서 이용하지 않던 방문이 이 업장을 골랐다.
- 옮겨 온 매출 (`moved_in`): 기준에서 경쟁 업장(`from_competitor`)이나 다른 워커힐 업장(`from_walkerhill`)을 고르던 방문이 이 업장을 골랐다.
- 잃은 매출 (`lost`): 기준에서 이 업장을 고르던 방문이 경쟁 업장(`to_competitor`), 다른 워커힐 업장(`to_walkerhill`), 이용하지 않음(`to_none`)으로 갔다. 음수다.
- 가격 효과 (`price`): 두 실행에서 같은 업장의 같은 상품을 같은 수량으로 골랐고, 가격이나 할인만 달랐다.
- 주문 변화 (`order`): 두 실행에서 같은 업장을 골랐지만 상품이나 수량이 달랐다.
"""

from typing import Literal, Self

from pydantic import Field, model_validator

from engine.formats.codes import FormatModel, Id, Text

Part = Literal["new", "from_competitor", "from_walkerhill", "to_competitor", "to_walkerhill", "to_none", "price", "order"]
PARTS: tuple[Part, ...] = ("new", "from_competitor", "from_walkerhill", "to_competitor", "to_walkerhill", "to_none", "price", "order")
# 잃은 매출의 갈래. 금액이 0 이하다.
LOST_PARTS = frozenset({"to_competitor", "to_walkerhill", "to_none"})
# 그 밖의 갈래 가운데 금액이 0 이상인 것. 가격 효과와 주문 변화는 늘 수도 줄 수도 있다.
GAIN_PARTS = frozenset({"new", "from_competitor", "from_walkerhill"})


class ChangeParts(FormatModel):
    """갈래마다의 금액과 그 합 (원, 세금을 뺀 가상 매출)."""

    new: int = Field(ge=0)
    from_competitor: int = Field(ge=0)
    from_walkerhill: int = Field(ge=0)
    to_competitor: int = Field(le=0)
    to_walkerhill: int = Field(le=0)
    to_none: int = Field(le=0)
    price: int
    order: int
    total: int

    @model_validator(mode="after")
    def _sum(self) -> Self:
        if sum(getattr(self, part) for part in PARTS) != self.total:
            raise ValueError("갈래를 더한 값이 total 과 다르다")
        return self


class VenueChange(FormatModel):
    """워커힐 업장 하나의 변화. `parts.total` 은 상황의 가상 매출(`after`) − 기준의 가상 매출(`before`)이다."""

    venue_id: Id
    before: int = Field(ge=0)
    after: int = Field(ge=0)
    parts: ChangeParts

    @model_validator(mode="after")
    def _difference(self) -> Self:
        if self.after - self.before != self.parts.total:
            raise ValueError(f"업장 '{self.venue_id}' 의 parts.total 이 after − before 와 다르다")
        return self


class Place(FormatModel):
    """방문이 간 곳. 워커힐이나 경쟁 업장이면 `venue_id` 가 있다."""

    kind: Literal["walkerhill", "competitor", "none"]
    venue_id: Id | None

    @model_validator(mode="after")
    def _venue(self) -> Self:
        if (self.kind == "none") != (self.venue_id is None):
            raise ValueError("이용하지 않음이면 venue_id 가 null 이고, 그 밖에는 venue_id 가 있다")
        return self


class VisitChangePart(FormatModel):
    venue_id: Id
    part: Part
    amount: int


class VisitChange(FormatModel):
    """방문 하나의 변화. 금액이 바뀌지 않은 방문도 적는다 (`parts` 가 비거나 0 이다)."""

    visit_id: Text
    represented: float = Field(ge=0)
    before: Place
    after: Place
    parts: list[VisitChangePart]


class Changes(FormatModel):
    """상황 실행 폴더의 `changes.json`. 상황 실행을 쓸 때 엔진이 함께 쓴다."""

    format_version: Literal[1]
    run_id: Text
    baseline_run_id: Text
    # 두 실행 가운데 한쪽이라도 AI 답을 받지 못한 방문. 두 실행 모두에서 뺐다.
    excluded_visits: list[Text]
    walkerhill: ChangeParts
    venues: list[VenueChange]
    visits: list[VisitChange]

    @model_validator(mode="after")
    def _totals(self) -> Self:
        for part in (*PARTS, "total"):
            if sum(getattr(v.parts, part) for v in self.venues) != getattr(self.walkerhill, part):
                raise ValueError(f"업장들의 {part} 를 더한 값이 walkerhill.{part} 와 다르다")
        by_venue: dict[tuple[str, str], int] = {}
        for visit in self.visits:
            for item in visit.parts:
                by_venue[(item.venue_id, item.part)] = by_venue.get((item.venue_id, item.part), 0) + item.amount
        for venue in self.venues:
            for part in PARTS:
                if by_venue.get((venue.venue_id, part), 0) != getattr(venue.parts, part):
                    raise ValueError(f"방문들의 '{venue.venue_id}' {part} 를 더한 값이 업장의 값과 다르다")
        return self
