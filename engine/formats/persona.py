"""페르소나 정의 (docs/FORMATS.md 5절).

공개 층(`personas/`)과 비공개 층(`private/personas/`)이 같은 형식을 쓴다.
기본 데이터에서 계산하는 값은 파일에 적지 않는다. 엔진이 실행할 때 붙인다.
"""

import copy
import json
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from engine.formats.codes import (
    BudgetBasis,
    DayType,
    FormatModel,
    Grade,
    Id,
    Level,
    Meal,
    Occasion,
    Text,
    Won,
    has_duplicates,
)

# 근거를 적어야 하는 묶음 일곱 개.
EVIDENCE_KEYS = ("share_in_group", "visit", "budget", "preferences", "buying", "revisit", "compares_with")

# 이 묶음들에 후기 번호가 하나도 없으면 화면이 "이유 근거 부족"으로 보여 준다.
REASON_EVIDENCE_KEYS = ("visit", "preferences", "buying")


class ShareInGroup(FormatModel):
    """고객군 안의 몫. 한 고객군의 페르소나 몫을 더하면 1 이어야 한다."""

    value: float = Field(ge=0, le=1)
    grade: Grade
    basis: Text


class Party(FormatModel):
    label: Text
    adults: int = Field(ge=1)
    children: int = Field(ge=0)


class Visit(FormatModel):
    """방문 모습."""

    purposes: list[Text] = Field(min_length=1)
    party: Party
    occasions: list[Occasion] = Field(min_length=1)
    meals: list[Meal]
    day_types: list[DayType] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> Self:
        for name in ("purposes", "occasions", "meals", "day_types"):
            if has_duplicates(getattr(self, name)):
                raise ValueError(f"visit.{name} 에 같은 값이 두 번 있다")
        return self


class Budget(FormatModel):
    """예산. 엔진은 `max` 를 넘는 주문만 후보에서 뺀다. `typical` 은 LLM 이 판단할 때 쓴다."""

    basis: BudgetBasis
    typical: Won
    max: Won

    @model_validator(mode="after")
    def _order(self) -> Self:
        if self.typical > self.max:
            raise ValueError("budget.typical 이 budget.max 보다 크다")
        return self


class Preferences(FormatModel):
    """기호와 제약. `atmosphere` 는 항목마다 중요도 1 ~ 3 이다."""

    cuisines_like: list[Text]
    cuisines_avoid: list[Text]
    dietary: list[Text]
    atmosphere: dict[str, Literal[1, 2, 3]]
    needs: list[Text]


class Buying(FormatModel):
    """구매 성향. `promo_response` 와 `reservation` 은 한국어 한 문장이다."""

    price_sensitivity: Level
    promo_response: Text
    reservation: Text
    wait_tolerance: Level


class Revisit(FormatModel):
    returns_for: list[Text]
    leaves_for: list[Text]


class EvidenceItem(FormatModel):
    """묶음 하나의 근거. `refs` 는 후기 번호나 `<venue_id>:<source_id>` 다."""

    grade: Grade
    refs: list[Text]
    note: str


class Evidence(FormatModel):
    share_in_group: EvidenceItem
    visit: EvidenceItem
    budget: EvidenceItem
    preferences: EvidenceItem
    buying: EvidenceItem
    revisit: EvidenceItem
    compares_with: EvidenceItem


class Persona(FormatModel):
    """페르소나 한 명이 파일 하나다."""

    format_version: Literal[1]
    persona_id: Id
    name: Text
    customer_group: Text
    share_in_group: ShareInGroup
    visit: Visit
    budget: Budget
    preferences: Preferences
    buying: Buying
    revisit: Revisit
    compares_with: list[Id]
    evidence: Evidence
    # 두 층을 합쳤을 때만 생긴다. 파일에는 적지 않는다.
    overridden_by_private: list[str] = Field(default_factory=list)

    def review_refs(self) -> list[str]:
        """근거로 든 후기 번호를 모두 모은다."""
        refs: list[str] = []
        for key in EVIDENCE_KEYS:
            refs.extend(r for r in getattr(self.evidence, key).refs if ":" not in r)
        return refs

    def lacks_reason_evidence(self) -> bool:
        """방문 모습·기호·구매 성향에 후기 번호가 하나도 없으면 "이유 근거 부족"이다."""
        return not any(
            ":" not in ref for key in REASON_EVIDENCE_KEYS for ref in getattr(self.evidence, key).refs
        )


# 비공개 층에 적을 수 있는 맨 위의 키. 식별에 쓰는 두 키와 내용 키다.
PRIVATE_LAYER_KEYS = frozenset(Persona.model_fields) - {"overridden_by_private"}

# 페르소나 형식의 판. 비공개 층에도 같은 값을 적는다.
PERSONA_FORMAT_VERSION = 1


def merge_persona_layers(public: dict[str, Any], private: dict[str, Any] | None) -> dict[str, Any]:
    """공개 층에 비공개 층을 합친 새 사전을 돌려준다 (docs/FORMATS.md 5절의 합치는 규칙).

    - 묶음 안에 묶음이 있으면 끝까지 내려가 키마다 따로 합친다.
    - 값이 하나인 키는 비공개 층의 값을 쓴다.
    - 값이 목록인 키는 두 목록을 합치고 겹치는 값은 하나만 남긴다.
    - 비공개 층으로 값을 지우거나(null) 값의 종류를 바꿀 수는 없다.
    - 비공개 층 때문에 달라진 키를 모두 `overridden_by_private` 에 적는다: 값이 바뀐 키, 새로 생긴 키, 값이 더해진 목록.
      이 목록이 비어 있으면 합친 결과는 공개 층과 같다.

    비공개 층이 없어도 `overridden_by_private` 는 빈 목록으로 들어간다 (쓰는 쪽이 키가 있는지 따로 보지 않게).
    두 층은 고치지 않는다. 돌려준 사전을 고쳐도 두 층은 그대로다.
    합친 결과가 페르소나의 형식에 맞는지는 `merged_persona` 가 본다.
    """
    merged = copy.deepcopy(public)
    overridden: list[str] = []
    if private is not None:
        version = private.get("format_version")
        if type(version) is not int or version != PERSONA_FORMAT_VERSION:
            raise ValueError(f"비공개 층의 format_version 이 {PERSONA_FORMAT_VERSION} 이 아니다")
        persona_id = private.get("persona_id")
        if not isinstance(persona_id, str) or persona_id != public.get("persona_id"):
            raise ValueError("비공개 층의 persona_id 가 없거나 공개 층과 다르다")
        unknown = set(private) - PRIVATE_LAYER_KEYS
        if unknown:
            raise ValueError(f"비공개 층에 약속에 없는 키가 있다: {sorted(unknown)}")
        body = {k: v for k, v in private.items() if k not in ("format_version", "persona_id")}
        _merge_into(merged, body, "", overridden)
    merged["overridden_by_private"] = overridden
    return merged


def merged_persona(public: dict[str, Any], private: dict[str, Any] | None) -> Persona:
    """두 층을 합치고, 합친 결과가 페르소나의 형식에 맞는지 본 뒤 돌려준다.

    형식에 맞지 않으면 pydantic 의 ValidationError 가 난다 (파일을 읽을 때처럼 엄격하게 본다).
    """
    merged = merge_persona_layers(public, private)
    return Persona.model_validate_json(json.dumps(merged, ensure_ascii=False), strict=True)


def _merge_into(base: dict[str, Any], over: dict[str, Any], prefix: str, overridden: list[str]) -> None:
    """`base` 에 `over` 를 합쳐 넣는다. `base` 는 호출한 쪽이 미리 베껴 둔 사본이다."""
    for key, value in over.items():
        path = f"{prefix}{key}"
        if value is None:
            raise ValueError(f"비공개 층의 '{path}' 가 null 이다. 비공개 층으로 값을 지울 수는 없다")
        if base.get(key) is None:
            # 공개 층에 없거나 비어 있는 키다. 비공개 층의 값을 통째로 베껴 넣는다.
            base[key] = copy.deepcopy(value)
            overridden.append(path)
            continue
        current = base[key]
        if _kind(current) != _kind(value):
            raise ValueError(
                f"비공개 층의 '{path}' 는 {_kind(value)}인데 공개 층에서는 {_kind(current)}이다. 값의 종류는 바꿀 수 없다"
            )
        if isinstance(value, dict):
            _merge_into(current, value, path + ".", overridden)
        elif isinstance(value, list):
            added = False
            for item in value:
                if item not in current:
                    current.append(copy.deepcopy(item))
                    added = True
            if added:
                overridden.append(path)
        elif current != value:
            base[key] = value
            overridden.append(path)


def _kind(value: Any) -> str:
    if isinstance(value, dict):
        return "묶음"
    if isinstance(value, list):
        return "목록"
    if isinstance(value, bool):
        return "참·거짓"
    if isinstance(value, int | float):
        return "숫자"
    if isinstance(value, str):
        return "글자"
    return "null"
