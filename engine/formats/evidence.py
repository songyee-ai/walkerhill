"""후기 라벨과 라벨 값 목록 (docs/FORMATS.md 4절)."""

import re
from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from engine.formats.codes import (
    DayType,
    FormatModel,
    Id,
    Meal,
    Occasion,
    SourceKind,
    Stay,
    Text,
    Won,
    YearMonth,
    has_duplicates,
)
from engine.formats.io import blank_to_none, split_list

# 후기 번호: <종류>-<venue_id>-<네 자리 번호>
# 종류: R 만드는 데 쓰는 공개 후기, H 떼어 둔 후기, P 받은 참고 소스의 후기
REVIEW_ID_RE = re.compile(r"^(?P<kind>[RHP])-(?P<venue_id>[a-z0-9]+(?:-[a-z0-9]+)*)-(?P<number>\d{4})$")

# 정의에 없는 메뉴나 견준 곳은 이 머리말 뒤에 한국어로 적는다.
FREE_NAME_PREFIX = "이름:"

REVIEW_COLUMNS = [
    "review_id",
    "venue_id",
    "source_kind",
    "posted_ym",
    "customer_group",
    "purpose",
    "party",
    "adults",
    "children",
    "occasion",
    "meal",
    "day_type",
    "stay",
    "ordered",
    "paid_total",
    "reasons_chosen",
    "pain_points",
    "compared_with",
    "would_return",
    "summary",
    "labeler",
    "labeled_on",
]

# private/evidence/ 에 두는 주소 목록 세 개의 열 (저장소에는 올리지 않는다).
URL_LIST_COLUMNS = ["venue_id", "url", "source_kind", "review_id", "dropped"]
URL_LIST_FILENAMES = frozenset({"review_urls.csv", "holdout_urls.csv", "build_urls.csv"})


class ReviewLabel(FormatModel):
    """후기 한 건이 한 줄이다. 원문과 작성자 아이디와 주소는 적지 않는다."""

    review_id: Text
    venue_id: Id
    source_kind: SourceKind
    posted_ym: YearMonth | None
    customer_group: str | None
    purpose: Text
    party: Text
    adults: int | None = Field(ge=0)
    children: int | None = Field(ge=0)
    occasion: Occasion | None
    meal: Meal | None
    day_type: DayType | None
    stay: Stay | None
    ordered: list[str]
    paid_total: Won | None
    reasons_chosen: list[str]
    pain_points: list[str]
    compared_with: list[str]
    would_return: Literal["yes", "no"] | None
    summary: Text
    labeler: Text
    labeled_on: date

    @model_validator(mode="after")
    def _rules(self) -> Self:
        match = REVIEW_ID_RE.match(self.review_id)
        if not match:
            raise ValueError("review_id 는 <종류>-<venue_id>-<네 자리 번호> 다 (예: R-geumryong-0003)")
        if match["venue_id"] != self.venue_id:
            raise ValueError("review_id 안의 업장이 venue_id 와 다르다")
        return self

    @property
    def kind(self) -> str:
        """R, H, P 가운데 하나."""
        return self.review_id[0]

    @property
    def number(self) -> int:
        return int(self.review_id[-4:])

    @classmethod
    def from_row(cls, row: dict[str, str]) -> Self:
        """CSV 의 한 줄을 읽는다. 빈 칸은 null, 세미콜론으로 나눈 칸은 목록이 된다."""
        data: dict[str, object] = {key: blank_to_none(value) for key, value in row.items()}
        for key in ("ordered", "reasons_chosen", "pain_points", "compared_with"):
            data[key] = split_list(row.get(key))
        return cls.model_validate(data)


class Vocab(FormatModel):
    """라벨 값 목록. 목록에 없는 값이 필요하면 이 파일에 먼저 더한 뒤 쓴다."""

    format_version: Literal[1]
    customer_group: list[Text] = Field(min_length=1)
    purpose: list[Text] = Field(min_length=1)
    party: list[Text] = Field(min_length=1)
    reasons_chosen: list[Text] = Field(min_length=1)
    pain_points: list[Text] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> Self:
        for name in ("customer_group", "purpose", "party", "reasons_chosen", "pain_points"):
            if has_duplicates(getattr(self, name)):
                raise ValueError(f"{name} 에 같은 값이 두 번 있다")
        return self
