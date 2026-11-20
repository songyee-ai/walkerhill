"""결정 상수를 읽는다 (docs/FORMATS.md 6.1절, T210).

결정 상수는 엔진 코드와 같은 저장소의 `engine/constants.json` 에 있다. `--root` 로 다른 폴더의 자료를 돌려도 이 파일을 쓴다
(엔진 코드가 그 폴더의 것이 아닌 것과 같다). 엔진은 이 파일의 해시를 실행 기록의 `inputs.constants` 에 남기고,
기준 실행 뒤에 바뀌면 상황을 돌리지 않는다.
해시는 파일 전체가 아니라 결과를 바꾸는 부분(식별자, 값, 단위, 쓰는지)으로만 낸다. 출처·설명·주인만 고치면 해시가 그대로라
기준 상황을 다시 돌리지 않아도 된다 (11-20 wilstein91 결정, T214).
"""

import hashlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from engine.formats.conditions import ConditionBundle
from engine.formats.constants import ConstantsFile, ConstantValue, Range, UsedConstant
from engine.formats.io import read_model
from engine.shares import SHARPNESS_ID, VENUE_CONSTANT_PREFIX

CONSTANTS_PATH = Path(__file__).resolve().parent / "constants.json"


@cache
def load_constants(path: Path = CONSTANTS_PATH) -> ConstantsFile:
    return read_model(path, ConstantsFile)


def values_hash(path: Path = CONSTANTS_PATH) -> str:
    """결정 상수 파일의 해시. 결과를 바꾸는 부분만 본다 (모듈 설명). 고친 파일을 바로 보도록 캐시하지 않고 다시 읽는다."""
    found = read_model(path, ConstantsFile)
    rows = sorted(
        [c.constant_id, c.value.model_dump() if isinstance(c.value, Range) else c.value, c.unit, c.in_use] for c in found.constants
    )
    text = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def constant(constant_id: str) -> ConstantValue:
    """결정 상수 하나의 값. 파일에 없으면 KeyError 다."""
    return load_constants().value(constant_id)


@dataclass(frozen=True)
class RunUse:
    """실행 하나에서 결정 상수가 계산에 실제로 쓰였는지를 가르는 사실 (실행 기록의 `applied`, FORMATS 10.1절, T212·T130 ②).

    "값을 바꿨다면 결과가 달라졌는가"가 아니라 "계산에 들어갔는가"다. 엔진이 실행을 마친 뒤 채운다 (`engine/runner.py`).
    """

    # 집계 파일로 단가를 채운 상품이 하나라도 있다 (`filled_products`).
    filled_prices: bool
    # 기본 데이터의 요약을 보낸 방식 (`none`, `bucketed`, `raw`).
    base_profile_mode: str
    # 가중치를 낼 때 인원이 빈 칸이라 결정 상수로 센 줄의 갈래: `takeout`(포장), `other`(추가 상품).
    # 기준이 아닌 상황은 기준 실행의 가중치를 쓰므로 기준 실행의 것이다.
    blank_people: frozenset[str]
    # 가중치를 낼 때 집계 파일의 줄을 나눈 비율의 `split_id` (위와 같이 기준 실행의 것).
    splits: frozenset[str]
    # 점수가 있는 답으로 몫을 낸 방문이 하나라도 있다 (`share_method` 가 `scores` 나 `mixed`).
    scored: bool
    # 점수가 있는 답에서 몫이 0 보다 큰 업장 (원장의 `score` 가 있는 줄의 `venue_id`).
    scored_venues: frozenset[str]
    # 프롬프트 판이 점수를 묻는다 (`engine.formats.choice.scores_required`).
    scores_asked: bool
    # 요청을 하나라도 만들어 답을 찾았다 (원장에 `request_hash` 가 있는 줄이 있다).
    requests: bool


# 상수마다 "계산에 쓰였는가"를 가르는 규칙. 키가 `-` 로 끝나면 그것으로 시작하는 상수 모두다 (FORMATS 10.1절의 "쓴 결정 상수").
# 규칙이 없는 상수는 실행을 멈추지 않고 쓰인 것(true)으로 적으며 경고를 낸다 (`applied`). 빠뜨리지 않게 지키는 것은
# `engine/constants.json` 의 모든 상수에 규칙이 있는지 보는 테스트다 (tests/test_constants.py).
_RULES: list[tuple[str, Callable[[RunUse, str], bool]]] = [
    ("filled-price-unit", lambda use, _: use.filled_prices),
    # 상품 순위는 요약을 보내면 늘, 비중의 범주 선은 범주로 보낼 때만 쓴다 (`raw` 는 소수로 보낸다).
    ("base-profile-top-products", lambda use, _: use.base_profile_mode != "none"),
    ("base-profile-bucket-", lambda use, _: use.base_profile_mode == "bucketed"),
    ("takeout-teams-per-item", lambda use, _: "takeout" in use.blank_people),
    ("add-on-people-per-item", lambda use, _: "other" in use.blank_people),
    # 보정의 통과 기준은 보정의 대조(`engine.calibration`)가 쓰고 실행의 계산에는 들지 않는다.
    ("calibration-", lambda use, _: False),
    (SHARPNESS_ID, lambda use, _: use.scored),
    (VENUE_CONSTANT_PREFIX, lambda use, constant_id: constant_id.removeprefix(VENUE_CONSTANT_PREFIX) in use.scored_venues),
    # 가격 민감도의 문턱 분포 (`engine.thresholds`): 점수를 묻는 판의 요청에만 들어간다. 그 판으로 요청을 만들었을 때 쓰였다.
    ("price-threshold-", lambda use, _: use.scores_asked and use.requests),
    # 처음 정한 등급별 문턱 셋은 위의 분포로 바뀌어 쓰지 않는다 (`in_use` 가 false 라 기록에 남지 않는다).
    ("price-sensitivity-threshold-", lambda use, _: False),
    # 2단계에서 엔진이 요청에 넣을 값 (지금은 `in_use` 가 false 라 기록에 남지 않는다): 점수를 묻는 판으로 요청을 만들었을 때.
    ("budget-spread-", lambda use, _: use.scores_asked and use.requests),
    ("sensitivity-threshold-spread-", lambda use, _: use.scores_asked and use.requests),
    # 4단계 상수 추정에서 시뮬레이션의 탄력성이 들어야 할 범위다. 실행의 계산에는 들지 않는다.
    ("price-elasticity-", lambda use, _: False),
]


def _rule(constant_id: str) -> Callable[[RunUse, str], bool] | None:
    for key, rule in _RULES:
        if constant_id == key or (key.endswith("-") and constant_id.startswith(key)):
            return rule
    return None


def has_rule(constant_id: str) -> bool:
    """이 상수에 "계산에 쓰였는가"를 가르는 규칙이 있는가."""
    return _rule(constant_id) is not None


def applied(constant_id: str, use: RunUse) -> bool:
    """`engine/constants.json` 이나 추정한 상수 파일의 상수가 이 실행의 계산에 쓰였는가.

    규칙이 없으면 실행을 멈추지 않고 쓰인 것(true)으로 본다. 쓰인 상수를 화면에서 빠뜨리지 않는 쪽이다. 엔진 담당이 알아채게 경고를 낸다.
    """
    rule = _rule(constant_id)
    if rule is None:
        print(
            f"경고: 결정 상수 '{constant_id}' 가 계산에 쓰였는지 가르는 규칙이 없어 쓰인 것(applied true)으로 적는다. "
            "engine/constants.py 의 _RULES 에 규칙을 더한다",
            file=sys.stderr,
        )
        return True
    return rule(use, constant_id)


def _used(found: ConstantsFile, file: str, use: RunUse | None, everything_applied: bool = False) -> list[UsedConstant]:
    return [
        UsedConstant(
            constant_id=c.constant_id,
            name=c.name,
            value=c.value,
            unit=c.unit,
            grade=c.grade,
            sources=c.sources,
            checked_on=c.checked_on,
            file=file,
            applied=None if use is None else everything_applied or applied(c.constant_id, use),
        )
        for c in found.constants
        if c.in_use
    ]


def used_from(found: ConstantsFile, file: str, use: RunUse | None = None) -> list[UsedConstant]:
    """한 상수 파일에서 엔진이 쓰는 것(`in_use`)을 실행 기록에 남길 모양으로 (추정한 상수 파일 등).

    `use` 를 주면 상수마다 이 실행의 계산에 쓰였는지(`applied`)를 적고, 주지 않으면 null 이다.
    """
    return _used(found, file, use)


def used_constants(
    bundle: ConditionBundle,
    summary_constants: ConstantsFile | None = None,
    summary_file: str | None = None,
    use: RunUse | None = None,
) -> list[UsedConstant]:
    """실행 기록에 남길 결정 상수: `engine/constants.json` 가운데 엔진이 지금 쓰는 것(`in_use`), 방문 조건 묶음의 나누는 비율(`assumed_splits`),
    그리고 집계 파일 옆의 상수 파일(`summary_constants`, 한 개당 인원처럼 집계를 만들 때 쓴 값)이 있으면 그 모두.

    `use` 를 주면 상수마다 이 실행의 계산에 쓰였는지(`applied`)를 적는다 (`RunUse`). 나누는 비율은 가중치가 그 비율로 줄을 나눴을 때,
    집계 쪽 상수는 늘 참이다 (실행은 늘 집계 파일을 읽어 쓰고, 그 값은 집계 파일에 이미 들어 있다).
    """
    used = _used(load_constants(), "engine/constants.json", use)
    used += [
        UsedConstant(
            constant_id=split.split_id,
            name=split.applies_when,
            value=dict(split.parts),
            unit=None,
            grade=split.grade,
            sources=[],
            checked_on=split.decided_on,
            file="engine/conditions.json",
            applied=None if use is None else split.split_id in use.splits,
        )
        for split in bundle.assumed_splits
    ]
    if summary_constants is not None and summary_file is not None:
        used += _used(summary_constants, summary_file, use, everything_applied=True)
    return used
