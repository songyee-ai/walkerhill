"""코드 값과 식별자 규칙 (docs/FORMATS.md 2절).

프로그램이 갈래를 나누는 값은 여기 있는 영어 코드로만 적는다.
화면에 보여 줄 한국어 뜻은 KO 에 있다.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Occasion = Literal["meal", "dessert", "takeout"]
Meal = Literal["lunch", "dinner", "breakfast"]
DayType = Literal["weekday", "weekend"]
DayTypeOrAll = Literal["weekday", "weekend", "all"]
Stay = Literal["guest", "visitor"]
PriceBasis = Literal["included", "excluded", "unknown"]
Grade = Literal["internal", "official", "review", "assumption", "unknown"]
ScenarioKind = Literal["baseline", "our_price", "our_promo", "competitor"]
ChoiceKind = Literal["walkerhill", "competitor", "none"]
QtyRule = Literal["per_person", "per_serves", "choice"]
Audience = Literal["adult", "child", "all"]
SourceKind = Literal["blog", "map", "booking", "reference"]
Level = Literal["low", "mid", "high"]
BudgetBasis = Literal["per_person", "party"]
DataMode = Literal["private", "sample"]
BaseProfileMode = Literal["none", "bucketed", "raw"]

# 식별자: 영어 소문자, 숫자, 하이픈만 쓴다.
ID_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
Id = Annotated[str, StringConstraints(pattern=ID_PATTERN)]

Month = Annotated[int, Field(ge=1, le=12)]
Won = Annotated[int, Field(ge=0)]
HHMM = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
YearMonth = Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
Text = Annotated[str, StringConstraints(min_length=1)]

# 워커힐 업장의 식별자. 이 밖의 업장은 모두 경쟁 업장이어야 한다.
WALKERHILL_VENUE_IDS = frozenset(
    {
        "geumryong",
        "pizzahill",
        "thebuffet",
        "ondal",
        "lepassage",
        "myongwolgwan",
        "pavilion",
        "moegi",
    }
)

# 화면에 보여 줄 한국어 뜻.
KO: dict[str, dict[str, str]] = {
    "occasion": {"meal": "식사", "dessert": "디저트·차", "takeout": "포장·구매"},
    "meal": {"lunch": "점심", "dinner": "저녁", "breakfast": "조식"},
    "day_type": {"weekday": "평일", "weekend": "주말", "all": "평일·주말"},
    "stay": {"guest": "투숙객", "visitor": "비투숙 방문객"},
    "price_basis": {"included": "세금·봉사료 포함", "excluded": "세금·봉사료 별도", "unknown": "표기 모름"},
    "grade": {
        "internal": "내부 매출 자료",
        "official": "공식 사실",
        "review": "후기에서 관찰",
        "assumption": "설계 가정",
        "unknown": "미확인",
    },
    "kind": {
        "baseline": "기준",
        "our_price": "우리 가격·구성 변경",
        "our_promo": "우리 프로모션",
        "competitor": "경쟁 호텔의 변경",
    },
    "choice_kind": {"walkerhill": "워커힐 업장", "competitor": "경쟁 업장", "none": "이용하지 않음"},
    "audience": {"adult": "성인", "child": "어린이", "all": "구분 없음"},
    "source_kind": {"blog": "블로그", "map": "지도 서비스", "booking": "예약 서비스", "reference": "받은 참고 소스"},
    "level": {"low": "낮음", "mid": "보통", "high": "높음"},
}


class FormatModel(BaseModel):
    """모든 형식의 바탕.

    약속에 없는 키가 들어오면 틀린 것으로 본다 (오타를 잡기 위해서다).
    숫자 칸에 Infinity 와 NaN 은 받지 않는다 (금액과 비율의 계산이 조용히 망가진다).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True, allow_inf_nan=False)


def has_duplicates(values: list) -> bool:
    return len(values) != len(set(values))
