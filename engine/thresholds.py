"""가격 민감도의 문턱: 페르소나의 등급마다 "평소 금액보다 몇 % 비싸지면 망설이나"를 요청에 넣는다 (T212, docs/FORMATS.md 9절의 `price_threshold`).

정한 것 (11-20 wilstein91):
- 기준 하나에서 등급의 값을 낸다. 고급 외식 손님의 문턱을 "가운데가 `price-threshold-median-pct`(10%)이고 90% 가 `price-threshold-90pct-range`(5 ~ 20%) 안에 드는"
  로그정규 분포로 보고(공개 연구의 평균과 범위, T306), 손님을 문턱이 낮은 차례로 세 무리(3분의 1씩)로 나눠 무리마다 가운데 사람의 문턱을 쓴다.
  민감도 높음은 문턱이 낮은 무리(분위 1/6), 중간은 가운데 무리(1/2), 낮음은 문턱이 높은 무리(5/6)다.
  처음 T306 의 5 / 10 / 15 ~ 20% 는 등급마다 서로 다른 것을 잰 연구에서 하나씩 가져온 값이라 기준이 없었다.
- 연구는 손님 무리를 나눠 재지 않았다. 범위는 연구에 근거가 있고, 세 무리로 나눈 것과 어느 페르소나가 어느 무리인지는 설계 가정이다.
  전체 반응의 크기는 이 값이 아니라 4단계에서 k 를 가격 탄력성 범위에 맞춰 정한다.
- 요청에는 금액과 퍼센트를 함께 넣는다: 계산은 엔진이 하고(평소 금액 × (1 + 문턱)), 판단은 AI 가 한다. 후보마다 "넘음" 표시를 붙이지 않는다.
- 점수를 묻는 판(`p1` ~ `p3` 이 아닌 판)의 요청에만 넣는다. 옛 판의 요청은 그대로라 받아 둔 답이 계속 재생된다.
"""

import math
from decimal import ROUND_HALF_UP, Decimal
from statistics import NormalDist
from typing import Any

from engine.formats.choice import scores_required
from engine.formats.constants import ConstantsFile, Range
from engine.formats.money import round_half_up

MEDIAN_ID = "price-threshold-median-pct"
RANGE_ID = "price-threshold-90pct-range"
# 범위가 손님의 몇 % 를 담는가 (가운데 90%).
RANGE_COVERS = 0.90
# 등급마다 그 무리의 가운데 사람이 서는 분위.
GRADE_QUANTILES = {"high": 1 / 6, "mid": 1 / 2, "low": 5 / 6}
# 요청에 적는 퍼센트의 자릿수와 금액의 반올림 단위(원).
PCT_DIGITS = 1
AMOUNT_UNIT = 100


def grade_thresholds(constants: ConstantsFile) -> dict[str, float]:
    """등급마다 문턱(%). 가운데 값과 90% 범위에서 로그정규 분포를 정하고 무리마다 가운데 사람의 문턱을 낸다."""
    for constant_id in (MEDIAN_ID, RANGE_ID):
        found = next((c for c in constants.constants if c.constant_id == constant_id), None)
        if found is None or not found.in_use:
            # 쓰지 않는 값은 실행 기록에 남지 않는다. 기록에 없는 값으로 문턱을 내지 않게 막는다.
            raise ValueError(f"결정 상수 '{constant_id}' 가 없거나 쓰지 않는 값(in_use 가 false)이다")
    median = constants.value(MEDIAN_ID)
    spread = constants.value(RANGE_ID)
    if isinstance(median, bool) or not isinstance(median, (int, float)) or median <= 0:
        raise ValueError(f"결정 상수 '{MEDIAN_ID}' 는 0 보다 큰 수다")
    if not isinstance(spread, Range) or not 0 < spread.min < median < spread.max:
        raise ValueError(f"결정 상수 '{RANGE_ID}' 는 가운데 값을 사이에 둔 범위(min < 가운데 < max)다")
    z = NormalDist().inv_cdf(0.5 + RANGE_COVERS / 2)
    # 범위의 양 끝이 로그로 가운데에서 같은 거리가 아니어도 되게, 두 쪽의 평균 폭을 쓴다.
    sigma = (math.log(spread.max) - math.log(spread.min)) / (2 * z)
    step = Decimal(1).scaleb(-PCT_DIGITS)
    return {
        # 0.5 는 올린다 (금액의 반올림과 같은 규칙. Python 의 round 는 짝수 쪽으로 간다).
        grade: float(Decimal(str(median * math.exp(sigma * NormalDist().inv_cdf(q)))).quantize(step, rounding=ROUND_HALF_UP))
        for grade, q in GRADE_QUANTILES.items()
    }


def price_threshold(persona: dict[str, Any], thresholds: dict[str, float]) -> dict[str, Any]:
    """페르소나의 등급과 평소 금액으로 요청에 넣을 문턱: 등급, 퍼센트, 그 퍼센트를 더한 금액(평소 금액과 같은 기준, 100원 단위)."""
    grade = persona["buying"]["price_sensitivity"]
    budget = persona["budget"]
    pct = thresholds[grade]
    amount = round_half_up(Decimal(budget["typical"]) * (1 + Decimal(str(pct)) / 100) / AMOUNT_UNIT) * AMOUNT_UNIT
    return {"sensitivity": grade, "pct": pct, "basis": budget["basis"], "amount": amount}


def with_price_threshold(persona: dict[str, Any], prompt_version: str, thresholds: dict[str, float] | None) -> dict[str, Any]:
    """요청에 넣을 페르소나. 점수를 묻는 판이면 `price_threshold` 를 더한 사본, 아니면 그대로다 (받아 둔 답이 재생되게)."""
    if not scores_required(prompt_version):
        return persona
    if thresholds is None:
        raise ValueError("점수를 묻는 판의 요청에는 가격 민감도의 문턱이 있어야 한다 (load_inputs 가 낸다)")
    return {**persona, "price_threshold": price_threshold(persona, thresholds)}
