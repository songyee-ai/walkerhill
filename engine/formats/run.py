"""실행 결과 (docs/FORMATS.md 10절).

상황 하나를 돌린 것이 실행 하나다. 기본 데이터로 돌린 결과는 `private/runs/` 에만 두고,
가상 예시 값으로 돌린 결과만 `engine/samples/runs/` 에 둔다.
"""

import hashlib
import json
import re
from typing import Any, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from engine.formats.choice import ChoiceRequest, ChoiceResponse
from engine.formats.codes import BaseProfileMode, ChoiceKind, DataMode, FormatModel, Grade, Id, Text, Won
from engine.formats.io import blank_to_none, split_list
from engine.formats.money import net_of_tax

# run_id: <날짜>-<시각>-<scenario_id>  (예: 20261117-101500-baseline)
RUN_ID_RE = re.compile(r"^(?P<date>\d{8})-(?P<time>\d{6})-(?P<scenario_id>[a-z0-9]+(?:-[a-z0-9]+)*)$")

# 요청 해시의 길이 (16진수 글자 수).
REQUEST_HASH_LENGTH = 16
REQUEST_HASH_RE = re.compile(rf"^[0-9a-f]{{{REQUEST_HASH_LENGTH}}}$")

VISIT_ID_SEPARATOR = "__"

# 일부 달에만 파는 곳을 골랐을 때 더 생기는 "이용하지 않음" 줄의 reason_text (docs/FORMATS.md 10.2절).
SEASON_GAP_REASON = "파는 달이 아님"


def compute_request_hash(provider: str, model: str, request: dict[str, Any]) -> str:
    """저장된 응답을 찾는 열쇠. 공급자, 모델, 요청 전체를 한데 묶어 낸다.

    키를 정렬하고 공백 없이 적은 JSON 의 SHA-256 에서 앞 16글자를 쓴다.
    하나라도 다르면 다른 값이 나온다.
    """
    canonical = json.dumps(
        {"provider": provider, "model": model, "request": request},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:REQUEST_HASH_LENGTH]


class LlmInfo(FormatModel):
    provider: Text
    model: Text
    prompt_version: Text
    calls_new: int = Field(ge=0)
    calls_replayed: int = Field(ge=0)
    call_limit: int = Field(ge=0)
    stopped_by_limit: bool


class WeightGrades(FormatModel):
    """가중치의 근거 등급. 묶음의 비율은 조건마다 적는다."""

    group_multiplier: Grade
    persona_weight: Grade
    condition_ratio: dict[str, dict[str, Grade]]


class Weights(FormatModel):
    """가중 합산에 쓴 값 (docs/PRD.md 7.2절). 기준 상황에서 한 번 정하고 다른 상황에서도 그대로 쓴다."""

    group_multiplier: dict[str, float]
    persona_weight: dict[str, float]
    condition_ratio: dict[str, dict[str, float]]
    grades: WeightGrades


class Counts(FormatModel):
    visits: int = Field(ge=0)
    failed: int = Field(ge=0)


class RunRecord(FormatModel):
    """실행 기록 `run.json`."""

    format_version: Literal[1]
    run_id: Text
    # 시각에는 시간대를 붙인다 (예: 2026-11-17T10:15:00+09:00). 시간대가 없으면 PC 마다 다르게 읽힌다.
    created_at: AwareDatetime
    engine_commit: Text
    data_mode: DataMode
    scenario_id: Id
    persona_ids: list[Id] = Field(min_length=1)
    condition_ids: list[Id] = Field(min_length=1)
    llm: LlmInfo
    base_profile_mode: BaseProfileMode
    inputs: dict[str, str]
    weights: Weights
    skipped_products: list[str]
    weights_from: str | None
    counts: Counts
    status: Literal["ok", "stopped_by_limit", "failed"]

    @model_validator(mode="after")
    def _rules(self) -> Self:
        match = RUN_ID_RE.match(self.run_id)
        if not match:
            raise ValueError("run_id 는 <날짜>-<시각>-<scenario_id> 다 (예: 20261117-101500-baseline)")
        if match["scenario_id"] != self.scenario_id:
            raise ValueError("run_id 끝의 상황이 scenario_id 와 다르다")
        if self.scenario_id == "baseline" and self.weights_from is not None:
            raise ValueError("기준 상황의 weights_from 은 null 이다")
        if self.scenario_id != "baseline" and self.weights_from is None:
            raise ValueError("기준이 아닌 상황은 weights_from 에 가중치를 정한 기준 상황의 run_id 를 적는다")
        if self.counts.failed > self.counts.visits:
            raise ValueError("counts.failed 가 counts.visits 보다 크다")
        return self


LEDGER_COLUMNS = [
    "run_id",
    "scenario_id",
    "visit_id",
    "persona_id",
    "customer_group",
    "condition_id",
    "choice_kind",
    "venue_id",
    "product_id",
    "quantity",
    "unit",
    "list_price",
    "discount",
    "paid",
    "revenue_net",
    "represented",
    "counted_share",
    "weighted_revenue",
    "reason_labels",
    "reason_text",
    "used_attributes",
    "llm_call",
    "request_hash",
    "status",
    "fail_reason",
]


class LedgerRow(FormatModel):
    """소비 원장의 한 줄. 주문한 상품 한 줄이 원장의 한 줄이다."""

    run_id: Text
    scenario_id: Id
    visit_id: Text
    persona_id: Id
    customer_group: Text
    condition_id: Id
    choice_kind: ChoiceKind
    venue_id: Id | None
    product_id: Id | None
    quantity: int = Field(ge=0)
    unit: str | None
    list_price: Won
    discount: Won
    paid: Won
    revenue_net: Won
    represented: float = Field(ge=0)
    counted_share: float = Field(ge=0, le=1)
    weighted_revenue: float = Field(ge=0)
    reason_labels: list[str]
    reason_text: str | None
    used_attributes: list[str]
    llm_call: Literal["new", "replay"] | None
    request_hash: str | None
    status: Literal["ok", "failed"]
    fail_reason: str | None

    @model_validator(mode="after")
    def _rules(self) -> Self:
        if self.visit_id != f"{self.persona_id}{VISIT_ID_SEPARATOR}{self.condition_id}":
            raise ValueError("visit_id 는 <persona_id>__<condition_id> 다")
        if (self.llm_call is None) != (self.request_hash is None):
            raise ValueError("llm_call 과 request_hash 는 둘 다 있거나 둘 다 비어 있다")
        if self.request_hash is not None and not REQUEST_HASH_RE.match(self.request_hash):
            raise ValueError("request_hash 는 16진수 16글자다")
        amounts = (self.quantity, self.list_price, self.discount, self.paid, self.revenue_net, self.weighted_revenue)
        if self.status == "failed":
            # 실패한 방문은 합계에 들어가면 안 된다. 그래서 고른 곳도 금액도 없는 줄 하나로만 남긴다.
            if not self.fail_reason:
                raise ValueError("실패한 줄에는 fail_reason 을 적는다")
            if self.choice_kind != "none" or self.venue_id or self.product_id:
                raise ValueError("실패한 줄은 choice_kind 가 none 이고 업장·상품이 비어 있다")
            if any(amounts):
                raise ValueError("실패한 줄의 수량과 금액은 모두 0 이다")
            return self
        if self.fail_reason:
            raise ValueError("fail_reason 은 실패한 줄에만 적는다")
        if self.quantity * self.list_price - self.discount != self.paid:
            raise ValueError("paid 가 수량 × 표시가 − 할인과 다르다")
        if self.choice_kind == "none":
            if self.venue_id or self.product_id or any(amounts):
                raise ValueError("이용하지 않음인 줄은 업장·상품이 비어 있고 수량과 금액이 0 이다")
        else:
            if not self.venue_id or not self.product_id:
                raise ValueError("업장을 고른 줄에는 venue_id 와 product_id 가 있어야 한다")
            if self.request_hash is None:
                # 업장을 고르는 것은 LLM 의 응답뿐이다. 응답이 없는 줄은 어디서 나왔는지 확인할 수 없다.
                raise ValueError("업장을 고른 줄에는 request_hash 가 있어야 한다 (저장된 응답에서 나온 줄이다)")
        if self.choice_kind == "walkerhill" and self.revenue_net != net_of_tax(self.paid):
            raise ValueError("revenue_net 이 낸 금액 ÷ 1.1 을 반올림한 값과 다르다")
        if self.choice_kind != "walkerhill" and self.revenue_net != 0:
            raise ValueError("경쟁 업장과 이용하지 않음의 revenue_net 은 0 이다")
        expected = self.revenue_net * self.represented * self.counted_share
        if abs(expected - self.weighted_revenue) > 0.5:
            raise ValueError("weighted_revenue 가 revenue_net × represented × counted_share 와 다르다")
        return self

    @classmethod
    def from_row(cls, row: dict[str, str]) -> Self:
        data: dict[str, object] = {key: blank_to_none(value) for key, value in row.items()}
        for key in ("reason_labels", "used_attributes"):
            data[key] = split_list(row.get(key))
        return cls.model_validate(data)


class Usage(FormatModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class SavedResponse(FormatModel):
    """저장된 LLM 응답 `llm/<request_hash>.json`. 같은 해시의 파일이 있으면 LLM 을 부르지 않고 이 응답을 쓴다."""

    format_version: Literal[1]
    request_hash: Text
    provider: Text
    model: Text
    created_at: AwareDatetime
    request: ChoiceRequest
    response: ChoiceResponse
    raw_text: str
    usage: Usage


class VenueShare(FormatModel):
    sim_share: float = Field(ge=0, le=1)
    base_share: float = Field(ge=0, le=1)
    diff_pp: float


class GroupCalibration(FormatModel):
    venues: dict[str, VenueShare]
    top_sim: Id | None
    top_base: Id | None
    passed: bool = Field(alias="pass")


class CalibrationCriteria(FormatModel):
    top_venue_must_match: bool
    max_diff_pp: float = Field(ge=0)


class Calibration(FormatModel):
    """보정의 대조 결과 `calibration.json` (docs/PRD.md 6.5절). 기준 상황에만 있다."""

    format_version: Literal[1]
    run_id: Text
    criteria: CalibrationCriteria
    groups: dict[str, GroupCalibration]
    uncovered_groups: list[str]
    passed: bool = Field(alias="pass")


class VenueValidation(FormatModel):
    """업장 하나의 검증 결과. 값은 비율이 아니라 건수다."""

    n: int = Field(ge=0)
    enough: bool
    venue_match: int | None = Field(ge=0)
    venue_match_baseline: int | None = Field(ge=0)
    reason_match: int | None = Field(ge=0)
    reason_match_baseline: int | None = Field(ge=0)

    @model_validator(mode="after")
    def _rules(self) -> Self:
        counts = (self.venue_match, self.venue_match_baseline, self.reason_match, self.reason_match_baseline)
        if self.enough and any(c is None for c in counts):
            raise ValueError("enough 가 true 면 건수를 모두 적는다")
        if not self.enough and any(c is not None for c in counts):
            raise ValueError("enough 가 false 면 건수는 null 이다 (검증 건수 부족)")
        if any(c is not None and c > self.n for c in counts):
            raise ValueError("건수가 n 보다 크다")
        return self


class Validation(FormatModel):
    """검증 결과 `validation.json` (docs/PRD.md 6.6절)."""

    format_version: Literal[1]
    created_at: AwareDatetime
    min_reviews: int = Field(ge=1)
    venues: dict[str, VenueValidation]

    @model_validator(mode="after")
    def _enough(self) -> Self:
        for venue_id, venue in self.venues.items():
            if venue.enough != (venue.n >= self.min_reviews):
                raise ValueError(f"업장 '{venue_id}' 의 enough 가 n 과 min_reviews 로 정한 것과 다르다")
        return self


VALIDATION_REVIEW_COLUMNS = [
    "review_id",
    "venue_id",
    "customer_group",
    "persona_id",
    "occasion",
    "meal",
    "day_type",
    "chosen_venue_id",
    "venue_match",
    "reason_match",
    "baseline_venue_id",
    "baseline_venue_match",
    "baseline_reason_match",
    "skipped",
]
