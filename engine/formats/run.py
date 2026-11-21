"""실행 결과 (docs/FORMATS.md 10절).

상황 하나를 돌린 것이 실행 하나다. 기본 데이터로 돌린 결과는 `private/runs/` 에만 두고,
가상 예시 값으로 돌린 결과만 `engine/samples/runs/` 에 둔다.
"""

import hashlib
import json
import re
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from engine.formats.choice import ChoiceRequest, ChoiceResponse
from engine.formats.codes import (
    BaseProfileMode,
    ChoiceKind,
    DataMode,
    FormatModel,
    Grade,
    Id,
    Month,
    Text,
    Won,
)
from engine.formats.constants import UsedConstant
from engine.formats.io import blank_to_none, split_list
from engine.formats.money import net_of_tax, weighted_amount

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
    """가중치의 근거 등급. 값마다 적는다: 고객군 배수는 고객군마다, 가중치는 페르소나마다, 묶음의 비율은 고객군과 조건마다."""

    group_multiplier: dict[str, Grade]
    persona_weight: dict[str, Grade]
    condition_ratio: dict[str, dict[str, Grade]]


# 한 고객군의 묶음의 비율을 더한 값이 1 과 이만큼까지 다르면 같은 것으로 본다 (소수로 나눈 끝자리).
RATIO_SUM_TOLERANCE = 1e-6


class Weights(FormatModel):
    """가중 합산에 쓴 값 (docs/PRD.md 7.2절). 기준 상황에서 한 번 정하고 다른 상황에서도 그대로 쓴다.

    11-19(T210)부터 방문 수(인원)로 낸다: 고객군 배수 = 고객군의 인원 ÷ Σ(페르소나의 몫 × 일행 수), 묶음의 비율 = 조건의 인원 ÷ 고객군의 인원.
    그래서 페르소나의 가중치 × 묶음의 비율이 그 방문이 대표하는 팀 수다. 그 전의 실행은 매출로 맞춘 배수가 적혀 있다.
    """

    group_multiplier: dict[str, float]
    persona_weight: dict[str, float]
    condition_ratio: dict[str, dict[str, float]]
    grades: WeightGrades
    # 집계 파일의 인원 가운데 페르소나가 있는 고객군의 인원이 차지하는 몫 (0 ~ 1). 페르소나가 없는 고객군은 시뮬레이션에 나오지 않는다.
    # 11-19(T210) 전의 실행에는 없다.
    people_coverage: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _rules(self) -> Self:
        values = (self.group_multiplier, self.persona_weight, self.condition_ratio)
        if any(value < 0 for value in (*self.group_multiplier.values(), *self.persona_weight.values())):
            raise ValueError("고객군 배수와 페르소나의 가중치는 0 이상이다")
        grades = (self.grades.group_multiplier, self.grades.persona_weight, self.grades.condition_ratio)
        for name, value, grade in zip(("group_multiplier", "persona_weight", "condition_ratio"), values, grades, strict=True):
            if set(value) != set(grade):
                raise ValueError(f"weights.{name} 와 weights.grades.{name} 의 키가 다르다 (값마다 등급을 적는다)")
        for group, ratios in self.condition_ratio.items():
            if set(ratios) != set(self.grades.condition_ratio[group]):
                raise ValueError(f"고객군 '{group}' 의 묶음 비율과 그 등급의 조건이 다르다")
            if any(ratio < 0 or ratio > 1 for ratio in ratios.values()):
                raise ValueError(f"고객군 '{group}' 의 묶음 비율은 0 ~ 1 이다")
            total = sum(ratios.values())
            # 그 고객군의 기본 데이터 매출이 없으면 비율을 낼 수 없어 모두 0 이다. 그 밖에는 더하면 1 이다.
            if ratios and total != 0 and abs(total - 1) > RATIO_SUM_TOLERANCE:
                raise ValueError(f"고객군 '{group}' 의 묶음 비율을 더하면 1 이어야 한다 (매출이 없어 낼 수 없으면 모두 0)")
        return self


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
    # 실행의 달 (명령의 `--month`). 묶음의 조건을 모두 이 달의 방문으로 돌렸다. 일 년 전체로 돌렸으면 null 이다.
    # 이 칸이 생기기 전(T112, 11-17)에 돌린 실행 기록에는 없다. 그 실행은 달을 주지 않고 돌린 것이라 null 로 읽는다.
    month: Month | None = None
    llm: LlmInfo
    base_profile_mode: BaseProfileMode
    inputs: dict[str, str]
    weights: Weights
    # 가격이 비어 있어 집계 파일로 단가를 채운 상품, 채우지 못해 후보에서 뺀 상품. 둘 다 `<venue_id>:<product_id>` 다.
    filled_products: list[str]
    skipped_products: list[str]
    weights_from: str | None
    counts: Counts
    status: Literal["ok", "stopped_by_limit", "failed"]
    # 이 실행이 쓴 결정 상수와 그 값·근거 (docs/FORMATS.md 6.1절). 11-19(T210) 전의 실행 기록에는 없다.
    constants: list[UsedConstant] | None = None
    # 기준이 아닌 상황에서, 바꾼 업장과 상관없어 원장을 기준의 답으로 적은 방문 (10.1절, T210 의 임시 규칙). 기준 상황은 null 이다.
    # 11-19 전의 실행 기록에는 없다.
    baseline_answers: list[Text] | None = None
    # 방문의 몫을 낸 방식 (T212): `single` 모든 방문이 답 하나(점수 없음, 1단계 방식)라 고른 곳의 몫이 1,
    # `scores` 모든 방문이 점수를 받은 답(2단계 방식), `mixed` 둘이 섞였다. 답이 하나도 없으면(후보 없음·실패뿐) `single` 이다.
    # 11-20 전의 실행 기록에는 없다 (그 실행은 모두 1단계 방식이다).
    share_method: Literal["single", "scores", "mixed"] | None = None

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
        if self.llm.stopped_by_limit != (self.status == "stopped_by_limit"):
            raise ValueError("llm.stopped_by_limit 과 status 가 서로 다른 말을 한다")
        if self.llm.calls_new > self.llm.call_limit:
            raise ValueError("llm.calls_new 가 llm.call_limit 보다 크다")
        if set(self.filled_products) & set(self.skipped_products):
            raise ValueError("같은 상품이 filled_products 와 skipped_products 에 함께 있다 (채웠으면 빼지 않는다)")
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
    "choice_share",
    "score",
    "season_gap_of",
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
    # 이 곳으로 간 방문의 몫 (2단계 방식, T212). 답 하나로 고른 방문(1단계 방식)은 1 이다.
    # 11-20 전의 원장에는 이 열이 없어 1 로 읽는다 (`engine.formats.io.ADDED_LATER`).
    choice_share: float = Field(default=1.0, ge=0, le=1)
    # 이 곳에 AI 가 적은 점수 (0 ~ 100). 1단계 방식의 답과 응답 없이 엔진이 정한 줄은 빈 칸이다.
    score: int | None = Field(default=None, ge=0, le=100)
    # 일부 달에만 파는 곳의 나머지 몫을 센 "이용하지 않음" 줄이면 그 곳의 venue_id. 그 밖에는 빈 칸이다.
    season_gap_of: Id | None = None
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
        if self.season_gap_of is not None and self.choice_kind != "none":
            raise ValueError("season_gap_of 는 파는 달이 아닌 몫을 센 '이용하지 않음' 줄에만 적는다")
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
        # 원장에는 원 단위로 반올림한 값을 적는다. 그래서 반올림 폭(0.5)까지는 같은 것으로 본다.
        expected = weighted_amount(self.revenue_net, self.represented, self.counted_share, self.choice_share)
        if abs(expected - Decimal(str(self.weighted_revenue))) > Decimal("0.5"):
            raise ValueError("weighted_revenue 가 revenue_net × represented × counted_share × choice_share 와 다르다")
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


class RejectedResponse(FormatModel):
    """검사에서 어긋난 LLM 응답 `llm_rejected/<request_hash>.json`. 프롬프트를 고칠 때 보려고 남긴다. 재생에는 쓰지 않는다."""

    format_version: Literal[1]
    request_hash: Text
    provider: Text
    model: Text
    created_at: AwareDatetime
    # 이번 실행에서 새로 받은 답인가, 저장된 응답을 재생하다 어긋난 것인가.
    llm_call: Literal["new", "replay"]
    request: ChoiceRequest
    raw_text: str
    problems: list[Text] = Field(min_length=1)
    usage: Usage


class VenueShare(FormatModel):
    sim_share: float = Field(ge=0, le=1)
    base_share: float = Field(ge=0, le=1)
    diff_pp: float


class GroupCalibration(FormatModel):
    venues: dict[str, VenueShare]
    top_sim: Id | None
    top_base: Id | None
    # 저장소에 있는 그 고객군의 페르소나 수 (11-17, T119). 첫 대조의 옛 파일에는 없어 모르는 것(None)으로 읽는다.
    personas: int | None = Field(default=None, ge=0)
    passed: bool = Field(alias="pass")


class CalibrationCriteria(FormatModel):
    top_venue_must_match: bool
    max_diff_pp: float = Field(ge=0)
    # 업장별 차이는 페르소나가 이 수 이상인 고객군에만 본다 (11-17, T119). 옛 파일에는 없어 1(모든 고객군)로 읽는다.
    diff_min_personas: int = Field(default=1, ge=1)


class Calibration(FormatModel):
    """보정의 대조 결과 `calibration.json` (docs/PRD.md 6.5절). 기준 상황에만 있다."""

    format_version: Literal[1]
    run_id: Text
    criteria: CalibrationCriteria
    groups: dict[str, GroupCalibration]
    uncovered_groups: list[str]
    passed: bool = Field(alias="pass")


# 다른 고객군에 써 보기·단순 기준과 견주기에서 견주는 방법 (docs/FORMATS.md 10.7절, T212).
CrossCheckMethod = Literal["no_constants", "held_out", "simple"]


class GroupCrossCheck(FormatModel):
    """한 고객군의 견주기. 몫은 워커힐 업장의 사람 수 몫이고, 잴 수 없는 방법은 null 이다."""

    actual: dict[str, Annotated[float, Field(ge=0, le=1)]]
    no_constants: dict[str, Annotated[float, Field(ge=0, le=1)]]
    held_out: dict[str, Annotated[float, Field(ge=0, le=1)]] | None
    simple: dict[str, Annotated[float, Field(ge=0, le=1)]] | None
    max_diff_pp: dict[CrossCheckMethod, Annotated[float, Field(ge=0, le=100)] | None]
    misplaced_pct: dict[CrossCheckMethod, Annotated[float, Field(ge=0, le=100)] | None]
    # 단순 기준을 낸 공개 후기의 수.
    simple_reviews: int = Field(ge=0)
    # 다른 고객군으로 상수를 추정하지 못했으면 그 까닭.
    held_out_note: str | None

    @model_validator(mode="after")
    def _rules(self) -> Self:
        for name in ("max_diff_pp", "misplaced_pct"):
            found = getattr(self, name)
            if set(found) != {"no_constants", "held_out", "simple"}:
                raise ValueError(f"{name} 에는 세 방법이 모두 있어야 한다")
            if found["no_constants"] is None:
                raise ValueError(f"{name}.no_constants 는 늘 적는다")
            for method in ("held_out", "simple"):
                if (getattr(self, method) is None) != (found[method] is None):
                    raise ValueError(f"{name}.{method} 는 {method} 의 몫이 있을 때만 적는다")
        if (self.held_out is None) != (self.held_out_note is not None):
            raise ValueError("held_out 이 null 이면 held_out_note 에 까닭을 적고, 아니면 null 이다")
        if (self.simple is None) != (self.simple_reviews == 0):
            raise ValueError("simple 은 공개 후기가 있을 때만 적는다")
        return self


class CrossCheck(FormatModel):
    """다른 고객군에 써 보기와 단순 기준과 견주기 `crosscheck.json` (docs/FORMATS.md 10.7절, T212). 점수를 받은 기준 실행에만 있다."""

    format_version: Literal[1]
    run_id: Text
    k: float = Field(gt=0)
    # 그 기준 실행이 기본 데이터의 요약을 LLM 에 보냈는가 (10.1절). `none` 이 아니면 페르소나마다 자기 고객군의 업장 몫 요약이 프롬프트에 들어가,
    # "다른 고객군으로 추정"도 완전히 떼어 둔 검증이 아니다 (10.7절).
    base_profile_mode: BaseProfileMode
    venues: list[Id] = Field(min_length=1)
    groups: dict[str, GroupCrossCheck] = Field(min_length=2)

    @model_validator(mode="after")
    def _venues(self) -> Self:
        if self.venues != sorted(set(self.venues)):
            raise ValueError("venues 는 겹치지 않고 차례대로 적는다")
        for group, found in self.groups.items():
            for name in ("actual", "no_constants", "held_out", "simple"):
                value = getattr(found, name)
                if value is not None and set(value) != set(self.venues):
                    raise ValueError(f"고객군 '{group}' 의 {name} 업장이 venues 와 다르다")
        return self

    def held_out_better_than_simple(self) -> tuple[int, int]:
        """(다른 고객군으로 추정한 상수의 어긋난 몫이 단순 기준보다 작은 고객군 수, 둘 다 잴 수 있는 고객군 수)."""
        both = [g for g in self.groups.values() if g.misplaced_pct["held_out"] is not None and g.misplaced_pct["simple"] is not None]
        return sum(g.misplaced_pct["held_out"] < g.misplaced_pct["simple"] for g in both), len(both)


class VenueValidation(FormatModel):
    """업장 하나의 검증 결과. 값은 비율이 아니라 건수다.

    업장 일치는 `n` 건으로, 이유 일치는 고른 이유 라벨이 있는 `reason_n` 건으로 잰다.
    5건 기준도 둘을 따로 본다 (`enough`, `reason_enough`. PRD 6.6절, T117).
    """

    n: int = Field(ge=0)
    enough: bool
    venue_match: int | None = Field(ge=0)
    venue_match_baseline: int | None = Field(ge=0)
    # 기대 일치 건수: 후기마다 그 후기의 업장에 시뮬레이션이 준 몫(`validation_reviews.csv` 의 `venue_share`)의 합 (11-21, T226).
    # `enough` 가 false 면 null 이다. 11-21 전의 결과에는 없다 (임시 호환, `Validation` 이 본다).
    venue_expected: float | None = Field(default=None, ge=0)
    reason_n: int = Field(ge=0)
    reason_enough: bool
    reason_match: int | None = Field(ge=0)
    reason_match_baseline: int | None = Field(ge=0)

    @model_validator(mode="after")
    def _rules(self) -> Self:
        if self.reason_n > self.n:
            raise ValueError("reason_n 이 n 보다 크다 (이유 일치는 n 건 가운데 고른 이유 라벨이 있는 후기로 잰다)")
        if self.venue_expected is not None:
            _check_expected(self.venue_expected, self.n, "venue_expected")
            if not self.enough:
                raise ValueError("enough 가 false 면 venue_expected 는 null 이다 (검증 건수 부족)")
        _check_counts(self.enough, self.n, (self.venue_match, self.venue_match_baseline), "enough", "n")
        _check_counts(
            self.reason_enough,
            self.reason_n,
            (self.reason_match, self.reason_match_baseline),
            "reason_enough",
            "reason_n",
        )
        return self


def _check_counts(enough: bool, total: int, counts: tuple[int | None, ...], flag: str, total_name: str) -> None:
    if enough and any(c is None for c in counts):
        raise ValueError(f"{flag} 가 true 면 건수를 모두 적는다")
    if not enough and any(c is not None for c in counts):
        raise ValueError(f"{flag} 가 false 면 건수는 null 이다 (검증 건수 부족)")
    if any(c is not None and c > total for c in counts):
        raise ValueError(f"건수가 {total_name} 보다 크다")


# 기대 일치 건수(`venue_expected`)는 소수 둘째 자리까지 적는다 (T226).
# 후기마다의 몫(`venue_share`)은 원장의 `choice_share` 처럼 반올림하지 않는다 (상수가 아주 작은 곳의 몫이 반올림으로 0 이 되지 않게).
EXPECTED_DIGITS = 2
# 소수를 반올림해 적은 값끼리 견줄 때 반올림 한 번의 폭 (둘째 자리의 반).
EXPECTED_ROUNDING = 0.5 * 10**-EXPECTED_DIGITS
_FLOAT_NOISE = 1e-9


def _check_digits(value: float, digits: int, name: str) -> None:
    if abs(value - round(value, digits)) > _FLOAT_NOISE:
        raise ValueError(f"{name} 은 소수점 아래 {digits}자리까지 반올림해 적는다")


def _check_expected(value: float, n: int, name: str) -> None:
    _check_digits(value, EXPECTED_DIGITS, name)
    if value > n + _FLOAT_NOISE:
        raise ValueError(f"{name} 이 n 보다 크다 (후기마다의 몫은 1 을 넘지 않는다)")


class ValidationTotal(FormatModel):
    """모든 업장을 합친 검증 건수. 검증 건수가 모자란 업장의 후기도 들어간다 (PRD 6.6절, T117)."""

    # 칸끼리의 한계(일치 건수 ≤ 분모, reason_n ≤ n)는 업장들과 함께 `Validation` 에서 본다.
    n: int = Field(ge=0)
    venue_match: int = Field(ge=0)
    venue_match_baseline: int = Field(ge=0)
    reason_n: int = Field(ge=0)
    reason_match: int = Field(ge=0)
    reason_match_baseline: int = Field(ge=0)
    # 모든 후기의 몫을 더한 기대 일치 건수 (T226). 11-21 전의 결과에는 없다.
    venue_expected: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _rules(self) -> Self:
        if self.venue_expected is not None:
            _check_expected(self.venue_expected, self.n, "total 의 venue_expected")
        return self


# total 의 일치 건수마다, 그 건수를 잰 분모의 칸
_TOTAL_DENOMINATORS = {
    "venue_match": "n",
    "venue_match_baseline": "n",
    "reason_match": "reason_n",
    "reason_match_baseline": "reason_n",
}


class Validation(FormatModel):
    """검증 결과 `validation.json` (docs/PRD.md 6.6절)."""

    format_version: Literal[1]
    created_at: AwareDatetime
    min_reviews: int = Field(ge=1)
    venues: dict[str, VenueValidation]
    total: ValidationTotal

    @model_validator(mode="after")
    def _enough(self) -> Self:
        for venue_id, venue in self.venues.items():
            if venue.enough != (venue.n >= self.min_reviews):
                raise ValueError(f"업장 '{venue_id}' 의 enough 가 n 과 min_reviews 로 정한 것과 다르다")
            if venue.reason_enough != (venue.reason_n >= self.min_reviews):
                raise ValueError(f"업장 '{venue_id}' 의 reason_enough 가 reason_n 과 min_reviews 로 정한 것과 다르다")
        venues = list(self.venues.values())
        for name in ("n", "reason_n"):
            if getattr(self.total, name) != sum(getattr(v, name) for v in venues):
                raise ValueError(f"total 의 {name} 이 업장들의 {name} 을 합친 것과 다르다")
        # 검증 건수가 모자란 업장은 건수가 null 이다. 그래서 total 은 적힌 업장의 합 이상이고,
        # 그 합에 null 인 업장의 분모를 더한 것 이하다. 모든 업장이 적혔으면 둘이 같아 합과 같아야 한다.
        for name, denominator in _TOTAL_DENOMINATORS.items():
            low = sum(getattr(v, name) for v in venues if getattr(v, name) is not None)
            high = low + sum(getattr(v, denominator) for v in venues if getattr(v, name) is None)
            total = getattr(self.total, name)
            if not low <= total <= high:
                raise ValueError(
                    f"total 의 {name} 은 업장들에 적힌 건수의 합 {low} 이상, "
                    f"건수가 모자란 업장의 {denominator} 까지 더한 {high} 이하다 (지금 {total})"
                )
        self._expected(venues)
        return self

    def _expected(self, venues: list[VenueValidation]) -> None:
        """기대 일치 건수(T226): 새 결과면 total 과 검증 건수가 넉넉한 업장에 모두 있고, 옛 결과면 어디에도 없다.

        total 의 한계는 일치 건수와 같다. 다만 값마다 반올림해 적어, 반올림 폭만큼은 같은 것으로 본다.
        """
        total = self.total.venue_expected
        if total is None:
            if any(v.venue_expected is not None for v in venues):
                raise ValueError("total 에 venue_expected 가 없는데 업장에는 있다 (새 칸은 total 과 업장에 함께 적는다)")
            return
        for venue_id, venue in self.venues.items():
            if venue.enough and venue.venue_expected is None:
                raise ValueError(f"업장 '{venue_id}' 의 venue_expected 가 없다 (total 에 적었으면 enough 인 업장에도 적는다)")
        written = [v.venue_expected for v in venues if v.venue_expected is not None]
        low = sum(written)
        high = low + sum(v.n for v in venues if v.venue_expected is None)
        slack = EXPECTED_ROUNDING * (len(written) + 1) + _FLOAT_NOISE
        if not low - slack <= total <= high + slack:
            raise ValueError(
                f"total 의 venue_expected 는 업장들에 적힌 값의 합 {low:.2f} 이상, "
                f"건수가 모자란 업장의 n 까지 더한 {high:.2f} 이하다 (반올림 폭은 봐줌, 지금 {total})"
            )


class ValidationReview(FormatModel):
    """후기 한 건마다의 검증 결과 `validation_reviews.csv` 의 한 줄 (docs/FORMATS.md 10.5절)."""

    review_id: Text
    venue_id: Id
    customer_group: str | None
    persona_id: Id | None
    occasion: str | None
    meal: str | None
    day_type: str | None
    # 페르소나가 고른 곳: 답의 `choice` 의 곳이다 (점수를 받은 답이어도 같다). "이용하지 않음"이면 빈 칸.
    chosen_venue_id: Id | None
    # 고른 곳이 후기의 업장인가 (`Y`, `N`). 단순 기준과 견주는 0/1 건수다.
    venue_match: Literal["Y", "N"] | None
    # 후기의 업장에 시뮬레이션이 준 몫 (0 ~ 1, 반올림하지 않음. 11-21, T226). 그 방문의 원장에서 그 업장 줄들이 함께 갖는 `choice_share` 다.
    # 점수가 없는 답(1단계 방식)이면 Y 는 1, N 은 0 이다.
    # 11-21 전의 파일에는 이 열이 없어 빈 칸으로 읽는다 (`engine.formats.io.ADDED_LATER`, 임시 호환).
    venue_share: float | None = Field(default=None, ge=0, le=1)
    reason_match: Literal["Y", "N"] | None
    baseline_venue_id: Id | None
    baseline_venue_match: Literal["Y", "N"] | None
    baseline_reason_match: Literal["Y", "N"] | None
    skipped: str | None

    @model_validator(mode="after")
    def _rules(self) -> Self:
        results = [name for name in VALIDATION_REVIEW_COLUMNS[3:-1] if getattr(self, name) is not None]
        if self.skipped is not None:
            if results:
                raise ValueError(f"돌리지 못한 후기(skipped)는 돌린 결과의 칸이 빈 칸이다 (적힌 칸 {results})")
            return self
        if self.venue_match is None or self.baseline_venue_match is None:
            raise ValueError("돌린 후기에는 venue_match 와 baseline_venue_match 를 적는다")
        if (self.venue_match == "Y") != (self.chosen_venue_id == self.venue_id):
            raise ValueError("venue_match 는 chosen_venue_id 가 후기의 venue_id 와 같을 때만 Y 다")
        if (self.baseline_venue_match == "Y") != (self.baseline_venue_id == self.venue_id):
            raise ValueError("baseline_venue_match 는 baseline_venue_id 가 후기의 venue_id 와 같을 때만 Y 다")
        # `choice` 의 곳은 점수가 0 보다 크고(9절) 업장 상수도 0 보다 커서, 고른 곳이 후기의 업장이면 몫이 0 보다 크다.
        # 파는 달의 몫은 `counted_share` 에 따로 들어 `choice_share` 를 줄이지 않는다 (10.2절).
        if self.venue_match == "Y" and self.venue_share is not None and self.venue_share <= 0:
            raise ValueError("venue_match 가 Y 면 venue_share 는 0 보다 크다 (choice 의 곳은 점수가 0 보다 크다)")
        # 다른 곳(또는 "이용하지 않음")을 골랐으면 그 곳도 점수가 0 보다 커 몫을 받으므로, 후기의 업장의 몫은 1 보다 작다.
        if self.venue_match == "N" and self.venue_share is not None and self.venue_share >= 1:
            raise ValueError("venue_match 가 N 이면 venue_share 는 1 보다 작다 (choice 의 곳도 몫을 받는다)")
        return self

    @classmethod
    def from_row(cls, row: dict[str, str]) -> Self:
        return cls.model_validate({key: blank_to_none(value) for key, value in row.items()})


def validation_problems(
    validation: Validation, reviews: list[ValidationReview], share_method: str | None = None
) -> list[str]:
    """`validation.json` 과 `validation_reviews.csv` 가 서로 맞는지 본다 (T226). 맞으면 빈 목록이다.

    형식 검사(`tools/check_formats.py`)는 검증 결과를 저장소에서 찾으면 오류만 내고 내용을 읽지 않는다 (저장소에 둘 수 없다).
    그래서 두 파일을 쓰는 검증 스크립트가 쓴 뒤 이것으로 본다. `share_method` 는 그 실행 기록의 것이다 (10.1절).
    """
    problems: list[str] = []
    ran = [r for r in reviews if r.skipped is None]
    # n 은 그 업장의 돌린 후기(skipped 가 빈 후기) 수다 (10.5절).
    counts: dict[str, int] = {}
    for review in ran:
        counts[review.venue_id] = counts.get(review.venue_id, 0) + 1
    unknown = sorted(set(counts) - set(validation.venues))
    if unknown:
        problems.append(f"validation.json 의 venues 에 없는 업장의 돌린 후기가 있다: {unknown}")
    for venue_id, venue in validation.venues.items():
        if counts.get(venue_id, 0) != venue.n:
            problems.append(f"업장 '{venue_id}' 의 n {venue.n} 이 돌린 후기 수 {counts.get(venue_id, 0)} 와 다르다")
    if validation.total.n != len(ran):
        problems.append(f"total 의 n {validation.total.n} 이 돌린 후기 수 {len(ran)} 와 다르다")

    total = validation.total.venue_expected
    if total is None:
        # 옛 모양(11-18 T19)은 모두 1단계 답이다. 점수를 받은 실행의 결과는 몫 칸이 있어야 한다.
        if share_method in ("scores", "mixed"):
            problems.append(f"점수를 받은 실행(share_method {share_method})의 검증 결과인데 venue_expected 가 없다")
        if any(r.venue_share is not None for r in reviews):
            problems.append("validation.json 에 venue_expected 가 없는데 validation_reviews.csv 에 venue_share 가 있다")
        return problems
    missing = [r.review_id for r in ran if r.venue_share is None]
    if missing:
        problems.append(f"돌린 후기의 venue_share 가 비어 있다: {missing}")
        return problems
    shares: dict[str, float] = {}
    for review in ran:
        shares[review.venue_id] = shares.get(review.venue_id, 0.0) + review.venue_share
    for venue_id, venue in validation.venues.items():
        found = shares.get(venue_id, 0.0)
        if venue.venue_expected is not None and abs(venue.venue_expected - found) > EXPECTED_ROUNDING + _FLOAT_NOISE:
            problems.append(f"업장 '{venue_id}' 의 venue_expected {venue.venue_expected} 가 후기들의 venue_share 합 {found:.4f} 와 다르다")
    found = sum(shares.values())
    if abs(total - found) > EXPECTED_ROUNDING + _FLOAT_NOISE:
        problems.append(f"total 의 venue_expected {total} 가 후기들의 venue_share 합 {found:.4f} 와 다르다")
    if share_method == "single":
        # 점수가 없는 답은 고른 곳의 몫이 1 이다. 그래서 Y 면 1, N 이면 0 이다.
        wrong = [r.review_id for r in ran if r.venue_share != (1 if r.venue_match == "Y" else 0)]
        if wrong:
            problems.append(f"점수가 없는 답(share_method single)인데 venue_share 가 Y 면 1, N 이면 0 이 아니다: {wrong}")
    return problems


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
    "venue_share",
    "reason_match",
    "baseline_venue_id",
    "baseline_venue_match",
    "baseline_reason_match",
    "skipped",
]
