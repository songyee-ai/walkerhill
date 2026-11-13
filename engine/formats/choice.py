"""선택 요청과 응답 (docs/FORMATS.md 9절).

엔진은 이 한 가지 형식으로만 LLM 을 부른다. 수량과 금액은 엔진이 미리 계산해 요청에 넣고,
LLM 의 답에는 금액을 넣지 않는다.
"""

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from engine.formats.codes import (
    DayType,
    FormatModel,
    Id,
    Meal,
    Month,
    Occasion,
    Stay,
    Text,
    Won,
    has_duplicates,
)
from engine.formats.persona import Budget
from engine.formats.venue import Benefit


class RunCondition(FormatModel):
    """이번 방문 조건. 묶음의 조건에 인원, 예산, (검증할 때만) 후기의 라벨을 더한 것이다."""

    condition_id: Id
    occasion: Occasion
    meal: Meal | None
    day_type: DayType
    stay: Stay | None
    month: Month | None
    adults: int = Field(ge=1)
    children: int = Field(ge=0)
    budget: Budget
    purpose: str | None
    party: str | None


class Line(FormatModel):
    """주문의 한 줄. `line_total` 은 수량 × 단가에서 할인을 뺀 값이다."""

    product_id: Id
    name: Text
    unit: Text
    quantity: int = Field(ge=1)
    unit_price: Won
    discount: Won
    line_total: Won

    @model_validator(mode="after")
    def _total(self) -> Self:
        if self.quantity * self.unit_price - self.discount != self.line_total:
            raise ValueError(f"상품 '{self.product_id}' 의 line_total 이 수량 × 단가 − 할인과 다르다")
        return self


class Option(FormatModel):
    """고를 수 있는 주문 하나. 함께 사야 하는 상품은 `lines` 에 여러 줄로 넣는다."""

    option_id: Text
    lines: list[Line] = Field(min_length=1)
    total: Won

    @model_validator(mode="after")
    def _total(self) -> Self:
        if sum(line.line_total for line in self.lines) != self.total:
            raise ValueError(f"주문 '{self.option_id}' 의 total 이 줄의 합과 다르다")
        return self


class Addon(FormatModel):
    """고객이 수량을 정하는 추가 상품. 금액은 주문의 `total` 에 들어 있지 않다."""

    product_id: Id
    name: Text
    unit: Text
    unit_price: Won
    qty_max: int = Field(ge=1)


class CandidatePromotion(FormatModel):
    """이번 조건에 해당하는 프로모션. `applied` 가 true 면 할인이 이미 `discount` 에 들어 있다."""

    promo_id: Id
    name: Text
    benefit: Benefit
    applied: bool


class Candidate(FormatModel):
    """규칙으로 추린 후보 업장."""

    venue_id: Id
    name: Text
    hotel: Text
    is_competitor: bool
    cuisine: Text
    options: list[Option] = Field(min_length=1)
    addons: list[Addon]
    promotions: list[CandidatePromotion]

    def option(self, option_id: str | None) -> Option | None:
        return next((o for o in self.options if o.option_id == option_id), None)


class RequestVocab(FormatModel):
    """이유로 쓸 수 있는 라벨."""

    reasons_chosen: list[Text] = Field(min_length=1)
    pain_points: list[Text] = Field(min_length=1)


class ChoiceRequest(FormatModel):
    prompt_version: Text
    scenario_id: Id
    # 두 층을 합친 페르소나. 엔진이 붙인 base_profile 이 들어갈 수 있어 모양을 묶어 두지 않는다.
    persona: dict[str, Any]
    condition: RunCondition
    candidates: list[Candidate]
    allow_none: Literal[True]
    vocab: RequestVocab

    @model_validator(mode="after")
    def _rules(self) -> Self:
        if not isinstance(self.persona.get("persona_id"), str):
            raise ValueError("persona 에 persona_id 가 있어야 한다")
        if has_duplicates([c.venue_id for c in self.candidates]):
            raise ValueError("후보에 같은 업장이 두 번 있다")
        option_ids = [o.option_id for c in self.candidates for o in c.options]
        if has_duplicates(option_ids):
            raise ValueError("option_id 가 겹친다")
        # 예산으로 거르기: 1인 기준이면 total ÷ 사람 수, 일행 기준이면 total 을 max 와 견준다.
        budget = self.condition.budget
        people = self.condition.adults + self.condition.children
        limit = budget.max * people if budget.basis == "per_person" else budget.max
        for candidate in self.candidates:
            if has_duplicates([a.product_id for a in candidate.addons]):
                raise ValueError(f"업장 '{candidate.venue_id}' 의 addons 에 같은 상품이 두 번 있다")
            for option in candidate.options:
                if option.total > limit:
                    raise ValueError(
                        f"주문 '{option.option_id}' 가 예산의 max 를 넘는다 (max 를 넘는 주문은 후보에 넣지 않는다)"
                    )
        return self

    def candidate(self, venue_id: str) -> Candidate | None:
        return next((c for c in self.candidates if c.venue_id == venue_id), None)


class AddonChoice(FormatModel):
    product_id: Id
    quantity: int = Field(ge=0)


class Choice(FormatModel):
    """고른 것. "이용하지 않음"이면 `venue_id` 와 `option_id` 가 null 이다."""

    venue_id: Id | None
    option_id: str | None
    addons: list[AddonChoice]

    @model_validator(mode="after")
    def _both(self) -> Self:
        if (self.venue_id is None) != (self.option_id is None):
            raise ValueError("venue_id 와 option_id 는 둘 다 있거나 둘 다 null 이다")
        if self.venue_id is None and self.addons:
            raise ValueError("이용하지 않음을 골랐는데 addons 가 있다")
        return self


class Rejected(FormatModel):
    """고르지 않은 후보와 그 이유."""

    venue_id: Id
    pain_labels: list[Text]
    text: Text


class ChoiceResponse(FormatModel):
    choice: Choice
    reason_labels: list[Text] = Field(min_length=1)
    reason_text: Text
    used_attributes: list[Text]
    rejected: list[Rejected]


def problems_in_response(request: ChoiceRequest, response: ChoiceResponse) -> list[str]:
    """엔진이 답을 다시 검사한다 (docs/FORMATS.md 9절). 어긋난 곳을 문장으로 돌려준다.

    금액을 업장 정의로 다시 계산하는 검사는 여기 없다. 업장 정의가 필요해서 엔진이 따로 한다.
    """
    problems: list[str] = []
    choice = response.choice
    chose_none = choice.venue_id is None

    if not chose_none:
        candidate = request.candidate(choice.venue_id)
        if candidate is None:
            problems.append(f"고른 업장 '{choice.venue_id}' 가 후보에 없다")
        else:
            if choice.option_id not in {o.option_id for o in candidate.options}:
                problems.append(f"고른 주문 '{choice.option_id}' 가 업장 '{choice.venue_id}' 의 주문에 없다")
            addons = {a.product_id: a for a in candidate.addons}
            if has_duplicates([picked.product_id for picked in choice.addons]):
                problems.append("choice.addons 에 같은 추가 상품이 두 번 있다")
            for picked in choice.addons:
                addon = addons.get(picked.product_id)
                if addon is None:
                    problems.append(f"추가 상품 '{picked.product_id}' 가 업장 '{choice.venue_id}' 의 addons 에 없다")
                elif picked.quantity > addon.qty_max:
                    problems.append(f"추가 상품 '{picked.product_id}' 의 수량이 qty_max 를 넘는다")

    allowed = request.vocab.pain_points if chose_none else request.vocab.reasons_chosen
    for label in response.reason_labels:
        if label not in allowed:
            where = "pain_points" if chose_none else "reasons_chosen"
            problems.append(f"이유 라벨 '{label}' 이 vocab.{where} 에 없다")

    # rejected 에는 고르지 않은 후보가 빠짐없이 한 번씩 있어야 한다.
    candidate_ids = [c.venue_id for c in request.candidates]
    seen: list[str] = []
    for rejected in response.rejected:
        if rejected.venue_id not in candidate_ids:
            problems.append(f"rejected 의 업장 '{rejected.venue_id}' 가 후보에 없다")
        elif rejected.venue_id == choice.venue_id:
            problems.append(f"고른 업장 '{rejected.venue_id}' 가 rejected 에도 있다")
        elif rejected.venue_id in seen:
            problems.append(f"rejected 에 업장 '{rejected.venue_id}' 가 두 번 있다")
        seen.append(rejected.venue_id)
        for label in rejected.pain_labels:
            if label not in request.vocab.pain_points:
                problems.append(f"걸린 점 라벨 '{label}' 이 vocab.pain_points 에 없다")
    for venue_id in candidate_ids:
        if venue_id != choice.venue_id and venue_id not in seen:
            problems.append(f"고르지 않은 후보 '{venue_id}' 가 rejected 에 없다")

    for path in response.used_attributes:
        if not _has_path(request.persona, path):
            problems.append(f"used_attributes 의 '{path}' 가 페르소나에 없는 속성이다")
    return problems


def _has_path(data: dict[str, Any], dotted: str) -> bool:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True
