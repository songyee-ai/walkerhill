"""6단계의 되돌려 맞혀 보기: 사건 목록과 채점 결과 (docs/FORMATS.md 10.9절, T224).

사건 목록은 "언제, 어느 워커힐 업장이, 무엇을 바꿨나"와 그것을 시뮬레이터에 넣을 상황 파일의 짝이다.
채점 결과는 사건마다 실제 변화와 예측 변화의 방향·크기, 그리고 모은 합격 판정이다.
기본 데이터나 실제 판매 자료로 만든 사건 목록과 결과에는 내부 수치가 들어 있어 `private/` 에만 둔다.
"""

from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from engine.formats.codes import (
    WALKERHILL_VENUE_IDS,
    DataMode,
    DayType,
    FormatModel,
    Id,
    Month,
    Occasion,
    Text,
    has_duplicates,
)

# 사건이 어디서 왔나: 자료에서 찾아 검토함(`detected`), 공개 자료(`public`), 자료를 준 쪽이 알려 줌(`given`).
EventSource = Literal["detected", "public", "given"]
EventKind = Literal["price", "promotion"]
Direction = Literal["up", "down", "none"]
# 채점 결과의 합격 판정: 합격, 불합격, 건수 부족 (채점한 사건이 `min_events` 에 못 미침).
Verdict = Literal["pass", "fail", "too_few"]


class BacktestEvent(FormatModel):
    """사건 하나. `start_month` 부터 바뀐 것이 `scenario_id` 의 상황이다."""

    event_id: Id
    name: Text
    kind: EventKind
    venue_id: Id
    start_month: Month
    scenario_id: Id
    source: EventSource
    # 넣은 이유 (자료에서 찾은 사건이면 무엇을 보고 가격 변경으로 봤는지).
    note: Text

    @model_validator(mode="after")
    def _ours(self) -> Self:
        if self.venue_id not in WALKERHILL_VENUE_IDS:
            raise ValueError(f"사건의 업장은 워커힐 업장이다: '{self.venue_id}'")
        return self


class BacktestEvents(FormatModel):
    """사건 목록 파일."""

    format_version: Literal[1]
    events: list[BacktestEvent] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> Self:
        if has_duplicates([e.event_id for e in self.events]):
            raise ValueError("event_id 가 겹친다")
        if has_duplicates([(e.venue_id, e.start_month) for e in self.events]):
            raise ValueError("같은 업장, 같은 달의 사건이 둘이다. 한 사건으로 합친다")
        return self


class Criteria(FormatModel):
    """채점의 기준 (PRD 6.6절의 "6단계의 통과 기준"). 돌려 본 뒤에 바꾸지 않는다."""

    metric: Literal["people"]
    window_before: int = Field(ge=1)
    window_after: int = Field(ge=1)
    magnitude_low: float = Field(gt=0)
    magnitude_high: float = Field(gt=0)
    direction_pass: float = Field(gt=0, le=1)
    magnitude_pass: float = Field(gt=0, le=1)
    min_events: int = Field(ge=1)


class Measure(FormatModel):
    """한 잣대(사람 수 또는 매출)의 실제와 예측. 변화는 바뀌지 않은 업장과 견준 비율이다 (0.1 이면 10% 늘었다)."""

    actual: float | None
    actual_band: float | None
    actual_direction: Direction | None
    predicted: float | None
    predicted_band: float | None
    predicted_direction: Direction | None
    direction_correct: bool | None


class Magnitude(FormatModel):
    """크기 채점. 4단계에서 맞춘 구간과 겹치는 방문을 뺀 나머지로 잰다."""

    status: Literal["scored", "excluded", "no_change", "unmeasured"]
    reason: str | None
    excluded_slices: list[tuple[Occasion, DayType]]
    actual: float | None
    actual_band: float | None
    predicted: float | None
    ratio: float | None
    correct: bool | None

    @model_validator(mode="after")
    def _status(self) -> Self:
        if (self.status == "scored") != (self.correct is not None):
            raise ValueError("크기를 채점했을 때만 correct 가 있다")
        if self.status != "scored" and self.reason is None:
            raise ValueError("크기를 채점하지 않았으면 reason 을 적는다")
        return self


class EventResult(FormatModel):
    """사건 하나의 채점."""

    event_id: Id
    venue_id: Id
    start_month: Month
    scenario_id: Id
    status: Literal["scored", "skipped"]
    skip_reason: str | None
    baseline_run: str | None
    scenario_run: str | None
    control_venues: list[Id]
    people: Measure | None
    revenue: Measure | None
    people_magnitude: Magnitude | None
    revenue_magnitude: Magnitude | None

    @model_validator(mode="after")
    def _status(self) -> Self:
        scored = self.status == "scored"
        if scored == (self.skip_reason is not None):
            raise ValueError("건너뛴 사건만 skip_reason 이 있다")
        if scored and (self.people is None or self.people.direction_correct is None or self.people_magnitude is None):
            raise ValueError("채점한 사건에는 사람 수의 방향과 크기가 있다")
        return self


class Tally(FormatModel):
    """한 잣대의 모은 결과."""

    scored: int = Field(ge=0)
    direction_correct: int = Field(ge=0)
    magnitude_scored: int = Field(ge=0)
    magnitude_correct: int = Field(ge=0)

    @model_validator(mode="after")
    def _counts(self) -> Self:
        if self.direction_correct > self.scored or self.magnitude_correct > self.magnitude_scored or self.magnitude_scored > self.scored:
            raise ValueError("맞은 수가 채점한 수보다 많다")
        return self


class BacktestSummary(FormatModel):
    events: int = Field(ge=0)
    people: Tally
    revenue: Tally
    verdict: Verdict
    # 크기를 말할 수 있는가 (크기를 채점한 사건이 하나라도 있는가. 없으면 방향만 말한다, PRD 12절).
    magnitude_said: bool


class FittedOn(FormatModel):
    """4단계(`elasticity.json`)에서 k 를 맞추는 데 쓴 것 가운데 6단계가 빼는 데 쓰는 것 (10.8절의 `fitted_on`)."""

    elasticity_file: Text
    price_scenarios: list[Id]
    segments: list[Id]


class BacktestResult(FormatModel):
    """채점 결과 파일."""

    format_version: Literal[1]
    created_at: AwareDatetime
    data_mode: DataMode
    events_file: Text
    summary_hash: Text
    fitted_on: FittedOn | None
    criteria: Criteria
    events: list[EventResult]
    summary: BacktestSummary

    @model_validator(mode="after")
    def _summary(self) -> Self:
        if self.summary.events != len(self.events):
            raise ValueError("summary.events 가 사건 수와 다르다")
        if self.summary.people.scored != sum(e.status == "scored" for e in self.events):
            raise ValueError("summary.people.scored 가 채점한 사건 수와 다르다")
        return self
