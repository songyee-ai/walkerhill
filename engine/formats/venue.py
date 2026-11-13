"""업장 정의 (docs/FORMATS.md 3절). 워커힐 업장과 경쟁 업장이 같은 형식을 쓴다."""

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from engine.formats.codes import (
    HHMM,
    Audience,
    DayType,
    DayTypeOrAll,
    FormatModel,
    Grade,
    Id,
    Meal,
    Month,
    Occasion,
    PriceBasis,
    QtyRule,
    Stay,
    Text,
    Won,
    has_duplicates,
)


class Source(FormatModel):
    """출처 한 건. 확인일은 그 값을 마지막으로 확인한 날이다."""

    source_id: Text
    title: Text
    url: Text
    checked_on: date


class Hours(FormatModel):
    """영업 시간 한 줄. 식사가 아닌 업장은 `meal` 을 null 로 둔다.

    `source_id` 가 null 이면 업장의 `default_source_id` 를 쓴다 (영업 시간은 메뉴판과 출처가 다를 수 있다).
    """

    meal: Meal | None
    day_type: DayTypeOrAll
    open: HHMM
    last_order: HHMM | None
    close: HHMM
    source_id: str | None


class Reservation(FormatModel):
    """예약 조건. `source_id` 가 null 이면 업장의 `default_source_id` 를 쓴다."""

    required: bool
    party_min: int | None = Field(ge=1)
    party_max: int | None = Field(ge=1)
    note: str
    source_id: str | None

    @model_validator(mode="after")
    def _range(self) -> Self:
        if self.party_min is not None and self.party_max is not None and self.party_min > self.party_max:
            raise ValueError("party_min 이 party_max 보다 크다")
        return self


class Slot(FormatModel):
    """상품을 파는 때 하나: 끼니와 평일·주말의 짝. 식사가 아닌 상품은 `meal` 이 null 이다."""

    meal: Meal | None
    day_type: DayTypeOrAll

    def covers(self, meal: str | None, day_type: str) -> bool:
        """그 끼니, 그 요일(weekday 나 weekend)이 이 짝에 드는가."""
        return self.meal == meal and self.day_type in (day_type, "all")


# 짝 하나가 덮는 요일.
_DAYS_OF = {"weekday": ("weekday",), "weekend": ("weekend",), "all": ("weekday", "weekend")}


class Product(FormatModel):
    """상품 한 줄."""

    product_id: Id
    name: Text
    occasion: Occasion
    # 파는 때. 끼니 목록과 요일 목록을 따로 적어 곱하면 "주말 점심과 모든 요일 저녁" 같은 상품을 적을 수 없어 짝으로 적는다.
    slots: list[Slot] = Field(min_length=1)
    months: list[Month] | None
    audience: Audience
    unit: Text
    serves: int = Field(ge=1)
    qty_rule: QtyRule
    qty_max: int | None = Field(ge=1)
    price: Won | None
    price_basis: PriceBasis
    grade: Grade
    source_id: str | None

    @model_validator(mode="after")
    def _rules(self) -> Self:
        if self.occasion == "meal" and any(slot.meal is None for slot in self.slots):
            raise ValueError("식사 상품의 slots 에는 meal 을 적는다")
        if self.occasion != "meal" and any(slot.meal is not None for slot in self.slots):
            raise ValueError("식사가 아닌 상품의 slots 는 meal 을 null 로 둔다")
        # 같은 때를 두 번 적지 않는다 (예: 점심·모든 요일과 점심·주말은 주말 점심이 겹친다).
        if has_duplicates([(slot.meal, day) for slot in self.slots for day in _DAYS_OF[slot.day_type]]):
            raise ValueError("slots 에 같은 때가 두 번 들어 있다 (all 은 평일과 주말을 모두 덮는다)")
        if self.months is not None and (not self.months or has_duplicates(self.months)):
            raise ValueError("months 는 null 이거나, 겹치지 않는 달이 하나 이상 든 목록이어야 한다")
        if self.qty_rule == "choice" and self.qty_max is None:
            raise ValueError("qty_rule 이 choice 면 qty_max 가 있어야 한다")
        if self.qty_rule != "choice" and self.qty_max is not None:
            raise ValueError("qty_rule 이 choice 가 아니면 qty_max 는 null 이다")
        if self.price is None and self.grade != "unknown":
            raise ValueError("price 가 null 이면 grade 는 unknown 이어야 한다")
        return self

    def sold_at(self, meal: str | None, day_type: str) -> bool:
        """그 끼니(식사가 아니면 None), 그 요일(weekday 나 weekend)에 이 상품을 파는가."""
        return any(slot.covers(meal, day_type) for slot in self.slots)

    def sold_on(self, day_type: str) -> bool:
        """끼니와 상관없이, 그 요일에 이 상품을 파는 때가 있는가."""
        return any(slot.day_type in (day_type, "all") for slot in self.slots)


class Benefit(FormatModel):
    """프로모션의 혜택. 할인은 숫자, 증정은 무엇을 주는지 한국어로 적는다."""

    type: Literal["discount_pct", "discount_amount", "gift"]
    value: int | float | str

    @model_validator(mode="after")
    def _value(self) -> Self:
        if self.type == "gift":
            if not isinstance(self.value, str) or not self.value.strip():
                raise ValueError("gift 의 value 에는 무엇을 주는지 한국어로 적는다")
        elif isinstance(self.value, str) or isinstance(self.value, bool):
            raise ValueError("할인의 value 는 숫자다")
        elif self.type == "discount_pct" and not 0 < self.value <= 100:
            raise ValueError("discount_pct 의 value 는 0 보다 크고 100 이하다")
        elif self.type == "discount_amount" and (self.value <= 0 or self.value != int(self.value)):
            raise ValueError("discount_amount 의 value 는 0 보다 큰 원 단위 정수다")
        return self


class PromotionConditions(FormatModel):
    """프로모션의 적용 조건. 조건이 없는 키는 null 이다."""

    day_type: DayType | None
    meal: Meal | None
    stay: Stay | None
    party_min: int | None = Field(ge=1)


class Period(FormatModel):
    from_: date = Field(alias="from")
    to: date

    @model_validator(mode="after")
    def _order(self) -> Self:
        if self.from_ > self.to:
            raise ValueError("period 의 from 이 to 보다 늦다")
        return self


class Promotion(FormatModel):
    """프로모션 한 줄. 상황 정의에서 프로모션을 더할 때도 이 모양을 쓴다."""

    promo_id: Id
    name: Text
    benefit: Benefit
    applies_to: list[Id] | None
    conditions: PromotionConditions
    period: Period | None
    grade: Grade
    source_id: str | None


class Venue(FormatModel):
    """업장 하나가 파일 하나다."""

    format_version: Literal[1]
    venue_id: Id
    name: Text
    hotel: Text
    is_competitor: bool
    competes_with: list[Id]
    cuisine: Text
    occasions: list[Occasion] = Field(min_length=1)
    months: list[Month] | None
    hours: list[Hours] | None
    reservation: Reservation | None
    products: list[Product]
    promotions: list[Promotion]
    sources: list[Source] = Field(min_length=1)
    default_source_id: Text

    @model_validator(mode="after")
    def _rules(self) -> Self:
        if has_duplicates(self.occasions):
            raise ValueError("occasions 에 같은 값이 두 번 있다")
        if self.months is not None and (not self.months or has_duplicates(self.months)):
            raise ValueError("months 는 null 이거나, 겹치지 않는 달이 하나 이상 든 목록이어야 한다")
        if self.is_competitor and not self.competes_with:
            raise ValueError("경쟁 업장은 competes_with 에 견주는 워커힐 업장을 적는다")
        if not self.is_competitor and self.competes_with:
            raise ValueError("워커힐 업장의 competes_with 는 빈 목록이다")

        product_ids = [p.product_id for p in self.products]
        if has_duplicates(product_ids):
            raise ValueError("product_id 가 겹친다")
        if has_duplicates([p.promo_id for p in self.promotions]):
            raise ValueError("promo_id 가 겹친다")
        source_ids = [s.source_id for s in self.sources]
        if has_duplicates(source_ids):
            raise ValueError("source_id 가 겹친다")
        if self.default_source_id not in source_ids:
            raise ValueError(f"default_source_id '{self.default_source_id}' 가 sources 에 없다")

        for product in self.products:
            if product.occasion not in self.occasions:
                raise ValueError(f"상품 '{product.product_id}' 의 occasion 이 업장의 occasions 에 없다")
            if product.source_id is not None and product.source_id not in source_ids:
                raise ValueError(f"상품 '{product.product_id}' 의 source_id 가 sources 에 없다")
            if product.months is not None and self.months is not None:
                if not set(product.months) <= set(self.months):
                    raise ValueError(f"상품 '{product.product_id}' 의 months 가 업장의 months 를 벗어난다")
        for index, hours in enumerate(self.hours or []):
            if hours.source_id is not None and hours.source_id not in source_ids:
                raise ValueError(f"hours[{index}] 의 source_id 가 sources 에 없다")
        if self.reservation is not None and self.reservation.source_id is not None:
            if self.reservation.source_id not in source_ids:
                raise ValueError("reservation 의 source_id 가 sources 에 없다")
        for promo in self.promotions:
            if promo.source_id is not None and promo.source_id not in source_ids:
                raise ValueError(f"프로모션 '{promo.promo_id}' 의 source_id 가 sources 에 없다")
            for product_id in promo.applies_to or []:
                if product_id not in product_ids:
                    raise ValueError(f"프로모션 '{promo.promo_id}' 의 applies_to 에 없는 상품 '{product_id}'")
        return self

    def product(self, product_id: str) -> Product | None:
        return next((p for p in self.products if p.product_id == product_id), None)
