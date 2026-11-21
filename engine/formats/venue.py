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
    MaterialKind,
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
    """출처 한 건. 확인일은 그 값을 마지막으로 확인한 날이다 (직접 잰 값이면 잰 날).

    `kind` 는 자료의 종류다 (6.1절과 같은 값). 빠지면 정하지 않은 것이고, 지금은 지도로 잰 거리의 출처에만 `measurement` 를 적는다 (11-20, T221).
    """

    source_id: Text
    title: Text
    url: Text
    checked_on: date
    kind: MaterialKind | None = None


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


class TextTrait(FormatModel):
    """글로 적는 업장 특성 하나 (위치, 전망·공간). 공식 문구를 줄여 한국어로 적는다."""

    value: Text
    source_id: str | None


class SeatsTrait(FormatModel):
    """좌석 수."""

    value: int = Field(ge=1)
    source_id: str | None


class PrivateRooms(FormatModel):
    """별실. `max_people` 은 가장 큰 별실이 받는 인원이다. 둘 가운데 모르는 것은 null 이고, 둘 다 모르면 별실 칸 전체를 null 로 둔다.

    별실이 없다고 확인했으면 `count` 를 0 으로, `max_people` 을 null 로 둔다 (null 은 모른다는 뜻이라 "없음"과 가른다).
    """

    count: int | None = Field(ge=0)
    max_people: int | None = Field(ge=1)
    source_id: str | None

    @model_validator(mode="after")
    def _known(self) -> Self:
        if self.count is None and self.max_people is None:
            raise ValueError("private_rooms 의 count 와 max_people 을 둘 다 모르면 private_rooms 를 null 로 둔다")
        if self.count == 0 and self.max_people is not None:
            raise ValueError("private_rooms 의 count 가 0 (별실 없음)이면 max_people 은 null 이다")
        return self


class Booking(FormatModel):
    """예약을 받는 조건. `opens_months_before` 는 몇 달 전부터 예약을 받는지, `deposit` 은 보증금(예약금)을 공식 문구를 줄여 적은 것이다."""

    opens_months_before: int | None = Field(ge=1)
    deposit: Text | None
    source_id: str | None

    @model_validator(mode="after")
    def _known(self) -> Self:
        if self.opens_months_before is None and self.deposit is None:
            raise ValueError("booking 의 opens_months_before 와 deposit 을 둘 다 모르면 booking 을 null 로 둔다")
        return self


class DistanceTrait(FormatModel):
    """그랜드 워커힐에서 이 업장의 호텔까지 자동차 경로 거리(km). 지도 서비스로 잰 값이라 출처는 `measurement` 자료이고 확인일이 잰 날이다."""

    value: float = Field(gt=0)
    source_id: str | None


class Traits(FormatModel):
    """업장 특성 (11-20, T221). 개선 3·5단계에서 쓴다. 지금은 LLM 요청에 싣지 않는다.

    공식 페이지에 없는 값은 null 로 두고 지어내지 않는다. 거리는 경쟁 업장만 적는다.
    """

    location: TextTrait | None
    seats: SeatsTrait | None
    private_rooms: PrivateRooms | None
    view: TextTrait | None
    booking: Booking | None
    distance_km: DistanceTrait | None


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
    # 업장 특성 (11-20, T221). 그 전에 만든 업장 정의에는 없어 빠지면 null 로 읽는다.
    traits: Traits | None = None

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

        # 지도로 잰 출처(`measurement`)는 거리(traits.distance_km)에만 쓴다 (T221). 다른 값은 공식 자료에서 온다.
        measured = {s.source_id for s in self.sources if s.kind == "measurement"}
        if self.default_source_id in measured:
            raise ValueError("default_source_id 가 measurement 자료다. 지도로 잰 출처는 traits.distance_km 에만 쓴다")
        cited = (
            [(f"상품 '{p.product_id}'", p.source_id) for p in self.products]
            + [(f"hours[{index}]", h.source_id) for index, h in enumerate(self.hours or [])]
            + [("reservation", self.reservation.source_id if self.reservation else None)]
            + [(f"프로모션 '{p.promo_id}'", p.source_id) for p in self.promotions]
        )
        for where, source_id in cited:
            if source_id in measured:
                raise ValueError(f"{where} 의 출처가 measurement 자료다. 지도로 잰 출처는 traits.distance_km 에만 쓴다")
        if self.traits is not None:
            self._check_traits(self.traits, {s.source_id: s for s in self.sources})
        return self

    def _check_traits(self, traits: Traits, sources: dict[str, Source]) -> None:
        if traits.distance_km is not None and not self.is_competitor:
            raise ValueError("traits.distance_km 은 경쟁 업장만 적는다 (그랜드 워커힐에서 경쟁 호텔까지의 거리)")
        for key in Traits.model_fields:
            trait = getattr(traits, key)
            if trait is None:
                continue
            # 빈 글자("")는 기본 출처로 넘기지 않고 오류로 본다 (상품의 source_id 와 같다).
            source = sources.get(self.default_source_id if trait.source_id is None else trait.source_id)
            if source is None:
                raise ValueError(f"traits.{key} 의 source_id 가 sources 에 없다")
            # 거리는 지도로 잰 값이고, 나머지는 공식 페이지에서 옮긴 값이다.
            if key == "distance_km" and source.kind != "measurement":
                raise ValueError("traits.distance_km 의 출처는 kind 가 measurement 인 자료다 (지도로 잰 거리)")
            if key != "distance_km" and source.kind == "measurement":
                raise ValueError(f"traits.{key} 의 출처가 measurement 자료다. 지도로 잰 출처는 거리에만 쓴다")

    def product(self, product_id: str) -> Product | None:
        return next((p for p in self.products if p.product_id == product_id), None)
