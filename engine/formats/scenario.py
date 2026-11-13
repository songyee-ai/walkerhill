"""상황 정의 (docs/FORMATS.md 7절).

비교하려고 돌리는 조건 한 벌이다. 상황은 업장 정의 파일을 고치지 않는다.
엔진이 실행할 때 업장 정의의 사본에 `changes` 를 순서대로 적용한다.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from engine.formats.codes import FormatModel, Id, ScenarioKind, Text, Won
from engine.formats.venue import Product, Promotion

BASELINE_ID = "baseline"


class SetPrice(FormatModel):
    """가격을 정한 값으로 바꾼다."""

    op: Literal["set_price"]
    venue_id: Id
    product_id: Id
    price: Won


class ChangePricePct(FormatModel):
    """가격을 퍼센트로 올리거나 내린다 (내리면 음수). `product_id` 가 null 이면 업장의 모든 상품이다."""

    op: Literal["change_price_pct"]
    venue_id: Id
    product_id: Id | None
    pct: float = Field(gt=-100)


class AddProduct(FormatModel):
    op: Literal["add_product"]
    venue_id: Id
    product: Product


class RemoveProduct(FormatModel):
    op: Literal["remove_product"]
    venue_id: Id
    product_id: Id


class AddPromotion(FormatModel):
    op: Literal["add_promotion"]
    venue_id: Id
    promotion: Promotion


class RemovePromotion(FormatModel):
    op: Literal["remove_promotion"]
    venue_id: Id
    promo_id: Id


Change = Annotated[
    SetPrice | ChangePricePct | AddProduct | RemoveProduct | AddPromotion | RemovePromotion,
    Field(discriminator="op"),
]


class Scenario(FormatModel):
    """상황 하나가 파일 하나다. 기준 상황은 `changes` 가 비어 있다."""

    format_version: Literal[1]
    scenario_id: Id
    name: Text
    kind: ScenarioKind
    description: Text
    changes: list[Change]
    note: str

    @model_validator(mode="after")
    def _baseline(self) -> Self:
        if self.kind == "baseline" and self.changes:
            raise ValueError("기준 상황의 changes 는 비어 있어야 한다")
        if self.kind != "baseline" and not self.changes:
            raise ValueError("기준이 아닌 상황에는 changes 가 하나 이상 있어야 한다")
        if (self.scenario_id == BASELINE_ID) != (self.kind == "baseline"):
            raise ValueError("기준 상황의 scenario_id 는 baseline 이고, 다른 상황은 baseline 을 쓸 수 없다")
        return self
