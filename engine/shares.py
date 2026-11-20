"""방문의 몫: AI 점수를 업장마다의 몫으로 바꾼다 (T212, docs/FORMATS.md 10.2절의 `choice_share`).

2단계 방식(11-20 wilstein91 결정): 방문마다 그곳의 몫 = (AI 점수 ^ k) × 그곳의 상수를, 모든 곳의 합이 1 이 되게 나눈 것이다.
- AI 점수는 응답의 `scores` 다 ("이 손님이 같은 상황을 백 번 맞는다면 몇 번", 합 100).
- k (날카로움)와 업장 상수는 결정 상수다 (`engine/constants.json`). 받은 자료로 추정한다 ("상수 추정", 선택 모형의 대안별 상수와 같은 방법).
  업장 상수가 적히지 않은 곳과 "이용하지 않음"은 1 이다 ("이용하지 않음"은 기준이라 늘 1).
- 점수를 묻지 않던 판의 답(`scores` 가 없음, 1단계 방식)은 고른 곳의 몫이 1 이다.
"""

from dataclasses import dataclass

from engine.formats.choice import Choice, ChoiceRequest, ChoiceResponse
from engine.formats.constants import ConstantsFile

# 날카로움 k 의 결정 상수. 1 이면 점수를 그대로 몫으로 쓰고, 클수록 가장 큰 점수로 몰린다.
SHARPNESS_ID = "share-sharpness-k"
# 업장 상수의 결정 상수: `share-venue-constant-<venue_id>`. 적히지 않은 업장은 1 이다.
VENUE_CONSTANT_PREFIX = "share-venue-constant-"


@dataclass(frozen=True)
class ShareParams:
    """몫을 내는 데 쓰는 값."""

    k: float
    venue_constants: dict[str, float]

    def constant(self, venue_id: str | None) -> float:
        return 1.0 if venue_id is None else self.venue_constants.get(venue_id, 1.0)


def share_params(constants: ConstantsFile) -> ShareParams:
    """결정 상수 파일에서 k 와 업장 상수를 읽는다. 쓰지 않는(`in_use` 가 false) 업장 상수는 1 로 본다."""
    sharpness = next((c for c in constants.constants if c.constant_id == SHARPNESS_ID), None)
    if sharpness is None or not sharpness.in_use:
        # 쓰지 않는 값은 실행 기록에 남지 않는다. 기록에 없는 값으로 몫을 내지 않게 막는다.
        raise ValueError(f"결정 상수 '{SHARPNESS_ID}' 가 없거나 쓰지 않는 값(in_use 가 false)이다")
    k = sharpness.value
    if isinstance(k, bool) or not isinstance(k, (int, float)) or k <= 0:
        raise ValueError(f"결정 상수 '{SHARPNESS_ID}' 는 0 보다 큰 수다")
    venue_constants: dict[str, float] = {}
    for c in constants.constants:
        if not c.constant_id.startswith(VENUE_CONSTANT_PREFIX) or not c.in_use:
            continue
        if isinstance(c.value, bool) or not isinstance(c.value, (int, float)) or c.value <= 0:
            raise ValueError(f"결정 상수 '{c.constant_id}' 는 0 보다 큰 수다")
        venue_constants[c.constant_id.removeprefix(VENUE_CONSTANT_PREFIX)] = float(c.value)
    return ShareParams(k=float(k), venue_constants=venue_constants)


@dataclass(frozen=True)
class Place:
    """방문 하나가 나뉘어 간 곳 하나. "이용하지 않음"이면 `venue_id` 가 None 이다."""

    venue_id: str | None
    # AI 가 적은 점수. 1단계 방식의 답이면 None 이다.
    score: int | None
    share: float
    # 그곳에 간다면 고를 주문.
    choice: Choice


def places(request: ChoiceRequest, response: ChoiceResponse, params: ShareParams) -> list[Place]:
    """방문의 몫을 곳마다 낸다. 몫이 0 인 곳은 넣지 않는다. 순서는 요청의 후보 순서이고 "이용하지 않음"이 맨 뒤다.

    검사를 통과한 응답만 준다 (`problems_in_response`). 점수의 합이 100 이 아니면 몫의 합도 1 이 되지 않는다.
    """
    if response.scores is None:
        return [Place(response.choice.venue_id, None, 1.0, response.choice)]
    weights = {
        s.venue_id: (s.percent**params.k) * params.constant(s.venue_id) if s.percent > 0 else 0.0 for s in response.scores
    }
    total = sum(weights.values())
    order: list[str | None] = [c.venue_id for c in request.candidates] + [None]
    found = []
    for venue_id in order:
        entry = response.score(venue_id)
        if entry is None or weights.get(venue_id, 0.0) <= 0:
            continue
        found.append(Place(venue_id, entry.percent, weights[venue_id] / total, entry.as_choice()))
    return found
