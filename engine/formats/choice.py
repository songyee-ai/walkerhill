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

    def budget_limit(self) -> int:
        """이 방문에서 쓸 수 있는 가장 큰 금액. 1인 기준이면 max × 사람 수, 일행 기준이면 max 다."""
        people = self.adults + self.children
        return self.budget.max * people if self.budget.basis == "per_person" else self.budget.max


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
    """이번 조건에 해당하는 프로모션. `applied` 가 true 면 할인이 이미 주문의 `discount` 에 들어 있다.

    증정은 금액을 바꾸지 않아 늘 false 다. 더 큰 할인에 밀려 어느 주문에도 들어가지 않은 할인도 false 다.
    """

    promo_id: Id
    name: Text
    benefit: Benefit
    applied: bool


class Candidate(FormatModel):
    """규칙으로 추린 후보 업장.

    `options` 가 비어 있으면 추가 상품만으로 사는 업장이다 (포장·구매처럼 고객이 수량을 정하는 상품만 있는 곳).
    그때는 `addons` 가 하나 이상 있어야 한다.
    """

    venue_id: Id
    name: Text
    hotel: Text
    is_competitor: bool
    cuisine: Text
    options: list[Option]
    addons: list[Addon]
    promotions: list[CandidatePromotion]

    @model_validator(mode="after")
    def _something_to_buy(self) -> Self:
        if not self.options and not self.addons:
            raise ValueError(f"업장 '{self.venue_id}' 에 고를 주문도 추가 상품도 없다")
        if has_duplicates([p.promo_id for p in self.promotions]):
            raise ValueError(f"업장 '{self.venue_id}' 의 promotions 에 같은 프로모션이 두 번 있다")
        # 할인은 프로모션에서만 나온다. 깎인 줄이 있으면 적용된 할인이 있고, 없으면 적용된 것도 없다.
        applied = [p for p in self.promotions if p.applied]
        if any(p.benefit.type == "gift" for p in applied):
            raise ValueError(f"업장 '{self.venue_id}' — 증정은 금액을 바꾸지 않아 applied 가 false 다")
        discounted = any(line.discount for option in self.options for line in option.lines)
        if discounted != bool(applied):
            raise ValueError(f"업장 '{self.venue_id}' — 주문의 할인과 promotions 의 applied 가 서로 다른 말을 한다")
        return self

    def option(self, option_id: str | None) -> Option | None:
        return next((o for o in self.options if o.option_id == option_id), None)


class RequestVocab(FormatModel):
    """이유로 쓸 수 있는 라벨."""

    reasons_chosen: list[Text] = Field(min_length=1)
    pain_points: list[Text] = Field(min_length=1)


class ChoiceRequest(FormatModel):
    prompt_version: Text
    # 상황의 이름은 요청에 넣지 않는다 (11-18, T121). 후보가 같으면 어느 상황에서 돌려도 요청이 같아 저장된 응답이 재생되고,
    # LLM 이 상황의 이름에서 무엇이 바뀌었는지 짐작하지 못한다.
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
        limit = self.condition.budget_limit()
        for candidate in self.candidates:
            if has_duplicates([a.product_id for a in candidate.addons]):
                raise ValueError(f"업장 '{candidate.venue_id}' 의 addons 에 같은 상품이 두 번 있다")
            # 예산은 산 것 전부(주문 + 추가 상품)와 견준다. 가장 싼 주문에 하나만 더해도 넘는 추가 상품은 넣지 않는다.
            # 주문이 없는 후보는 추가 상품만으로 사므로 그 상품의 값만 본다.
            cheapest = min((option.total for option in candidate.options), default=0)
            for addon in candidate.addons:
                if cheapest + addon.unit_price > limit:
                    raise ValueError(
                        f"업장 '{candidate.venue_id}' 의 추가 상품 '{addon.product_id}' 는 하나만 사도 예산의 max 를 넘는다"
                    )
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
    """고른 것. "이용하지 않음"이면 `venue_id` 와 `option_id` 가 null 이다.

    업장은 골랐는데 `option_id` 가 null 이면 추가 상품만 고른 것이다. 주문이 없는 후보에서만 그렇게 고를 수 있다
    (그 후보인지는 요청이 있어야 알 수 있어 `problems_in_response` 가 본다).
    """

    venue_id: Id | None
    option_id: str | None
    addons: list[AddonChoice]

    @model_validator(mode="after")
    def _both(self) -> Self:
        if self.venue_id is None and self.option_id is not None:
            raise ValueError("venue_id 가 null 인데 option_id 가 있다")
        if self.venue_id is None and self.addons:
            raise ValueError("이용하지 않음을 골랐는데 addons 가 있다")
        return self


class Rejected(FormatModel):
    """고르지 않은 후보와 그 이유."""

    venue_id: Id
    pain_labels: list[Text]
    text: Text


# 점수의 합 (docs/FORMATS.md 9절의 `scores`). "이 손님이 같은 상황을 백 번 맞는다면 몇 번".
SCORE_TOTAL = 100

# 점수를 묻지 않고 답 하나만 받던 프롬프트 판 (11-20, T212 의 1단계 방식). 이 판의 답에는 `scores` 가 없어도 되고,
# 엔진은 고른 곳을 100점으로 읽는다. 그 밖의 판은 `scores` 가 꼭 있어야 한다.
# 임시 호환이다 (`CLAUDE.md` "임시 허용"): 팀이 쓰는 답과 예시 묶음을 점수를 받는 판으로 다시 받은 뒤 없앤다.
# 없애는 조건과 확인은 진행 문서 T212 의 완료 조건에 있다.
SINGLE_ANSWER_PROMPTS = frozenset({"p1", "p2", "p3"})


def scores_required(prompt_version: str) -> bool:
    """이 판의 답에 `scores` 가 꼭 있어야 하는가."""
    return prompt_version not in SINGLE_ANSWER_PROMPTS


class Score(FormatModel):
    """후보 하나(또는 "이용하지 않음")의 점수와, 그곳에 간다면 고를 주문 (11-20 wilstein91 결정, T212).

    "이용하지 않음"이면 `venue_id` 가 null 이다. 점수가 0 인 곳은 주문을 적지 않아도 된다 (`option_id` null, `addons` 빈 목록).
    점수가 0 보다 큰 곳의 주문은 `choice` 와 같은 규칙으로 검사한다 (`problems_in_response`).
    """

    venue_id: Id | None
    percent: int = Field(ge=0, le=SCORE_TOTAL)
    option_id: str | None
    addons: list[AddonChoice]

    def as_choice(self) -> Choice:
        return Choice(venue_id=self.venue_id, option_id=self.option_id, addons=self.addons)


class ChoiceResponse(FormatModel):
    choice: Choice
    reason_labels: list[Text] = Field(min_length=1)
    reason_text: Text
    used_attributes: list[Text]
    rejected: list[Rejected]
    # 후보마다(이용하지 않음 포함)의 점수와 주문 (2단계 방식, T212). 점수를 묻지 않던 판(`SINGLE_ANSWER_PROMPTS`)의 답에는 없다.
    # 없으면 저장할 때도 적지 않는다 (옛 답과 같은 모양으로 남게).
    scores: list[Score] | None = Field(default=None, exclude_if=lambda value: value is None)

    def score(self, venue_id: str | None) -> Score | None:
        return next((s for s in self.scores or [] if s.venue_id == venue_id), None)


def problems_in_response(request: ChoiceRequest, response: ChoiceResponse) -> list[str]:
    """엔진이 답을 다시 검사한다 (docs/FORMATS.md 9절). 어긋난 곳을 문장으로 돌려준다.

    금액을 업장 정의로 다시 계산하는 검사는 여기 없다. 업장 정의가 필요해서 엔진이 따로 한다.
    """
    choice = response.choice
    chose_none = choice.venue_id is None
    problems = order_problems(request, choice)
    problems += score_problems(request, response)

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
        if not has_path(request.persona, path):
            problems.append(f"used_attributes 의 '{path}' 가 페르소나에 없는 속성이다")
    return problems


def order_problems(request: ChoiceRequest, choice: Choice, where: str = "") -> list[str]:
    """고른 업장의 주문 하나가 요청에서 고를 수 있는 것인가. "이용하지 않음"이면 볼 것이 없다.

    `choice` 의 주문과, 점수가 0 보다 큰 곳의 주문(`scores`)에 같은 규칙을 쓴다. `where` 는 문장 앞에 붙일 자리다.
    """
    if choice.venue_id is None:
        return []
    problems: list[str] = []
    candidate = request.candidate(choice.venue_id)
    if candidate is None:
        return [f"{where}고른 업장 '{choice.venue_id}' 가 후보에 없다"]
    addons = {a.product_id: a for a in candidate.addons}
    if candidate.options:
        if choice.option_id is None:
            problems.append(f"{where}업장 '{choice.venue_id}' 는 주문을 하나 골라야 한다 (추가 상품만 고를 수 없다)")
        elif choice.option_id not in {o.option_id for o in candidate.options}:
            problems.append(f"{where}고른 주문 '{choice.option_id}' 가 업장 '{choice.venue_id}' 의 주문에 없다")
    else:
        # 주문이 없는 후보: 추가 상품만 고른다. 하나도 안 사면 "이용하지 않음"과 구분되지 않는다.
        if choice.option_id is not None:
            problems.append(f"{where}업장 '{choice.venue_id}' 에는 주문이 없는데 option_id 가 있다")
        if not any(picked.quantity > 0 for picked in choice.addons):
            problems.append(f"{where}업장 '{choice.venue_id}' 를 골랐는데 산 추가 상품이 없다")
    if has_duplicates([picked.product_id for picked in choice.addons]):
        problems.append(f"{where or 'choice.'}addons 에 같은 추가 상품이 두 번 있다")
    for picked in choice.addons:
        addon = addons.get(picked.product_id)
        if addon is None:
            problems.append(f"{where}추가 상품 '{picked.product_id}' 가 업장 '{choice.venue_id}' 의 addons 에 없다")
        elif picked.quantity > addon.qty_max:
            problems.append(f"{where}추가 상품 '{picked.product_id}' 의 수량이 qty_max 를 넘는다")
    # 예산의 max 는 산 것 전부와 견준다: 고른 주문의 total 에 추가 상품의 금액을 더한 값이다.
    option = candidate.option(choice.option_id)
    spent = (option.total if option else 0) + sum(
        p.quantity * addons[p.product_id].unit_price for p in choice.addons if p.product_id in addons
    )
    if spent > request.condition.budget_limit():
        problems.append(f"{where}고른 주문과 추가 상품의 금액을 더한 값이 예산의 max 를 넘는다")
    return problems


def score_problems(request: ChoiceRequest, response: ChoiceResponse) -> list[str]:
    """점수(`scores`)가 약속대로인가 (docs/FORMATS.md 9절, T212).

    후보마다 하나와 "이용하지 않음" 하나가 있고, 합이 100 이며, 점수가 0 보다 큰 곳의 주문을 고를 수 있고,
    `choice` 에 적은 곳은 점수가 0 보다 크고 그 주문이 `choice` 와 같다. 점수를 묻지 않던 판이면 없어도 된다.
    """
    if response.scores is None:
        return ["scores 가 없다 (이 판의 답에는 후보마다의 점수가 있어야 한다)"] if scores_required(request.prompt_version) else []
    problems: list[str] = []
    places: list[str | None] = [c.venue_id for c in request.candidates] + [None]
    seen = [s.venue_id for s in response.scores]
    if has_duplicates([str(v) for v in seen]):
        problems.append("scores 에 같은 곳이 두 번 있다")
    for venue_id in seen:
        if venue_id not in places:
            problems.append(f"scores 의 업장 '{venue_id}' 가 후보에 없다")
    for venue_id in places:
        if venue_id not in seen:
            problems.append(f"scores 에 '{venue_id or '이용하지 않음'}' 이 없다")
    if sum(s.percent for s in response.scores) != SCORE_TOTAL:
        problems.append(f"scores 의 percent 를 더하면 {SCORE_TOTAL} 이어야 한다")
    for entry in response.scores:
        label = entry.venue_id or "이용하지 않음"
        if entry.venue_id is None:
            if entry.option_id is not None or entry.addons:
                problems.append("scores 의 '이용하지 않음' 에는 주문이 없다 (option_id null, addons 빈 목록)")
        elif entry.percent > 0 and entry.venue_id in places:
            problems += order_problems(request, entry.as_choice(), f"scores 의 '{label}' — ")
    chosen = response.score(response.choice.venue_id)
    if chosen is not None:
        if chosen.percent == 0:
            problems.append("choice 에 적은 곳의 점수가 0 이다")
        elif _bought(chosen.as_choice()) != _bought(response.choice):
            problems.append("choice 의 주문이 scores 에 적은 그곳의 주문과 다르다")
    return problems


def _bought(choice: Choice) -> tuple[str | None, str | None, list[tuple[str, int]]]:
    """산 것만 남긴 주문: 업장, 주문, 수량이 0 보다 큰 추가 상품 (적은 순서와 수량 0 인 항목은 보지 않는다)."""
    return choice.venue_id, choice.option_id, sorted((a.product_id, a.quantity) for a in choice.addons if a.quantity > 0)


def has_path(data: dict[str, Any], dotted: str) -> bool:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True
