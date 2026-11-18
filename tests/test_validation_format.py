"""검증 결과 `validation.json` 의 이유 일치 건수 규칙 (FORMATS.md 10.5절, PRD 6.6절, T117).

값은 문서의 예시(지어낸 값)를 고쳐 가며 본다.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from engine.formats import Validation


@pytest.fixture
def example(doc) -> dict:
    return copy.deepcopy(doc.validation)


def _rejects(data: dict, words: str) -> None:
    with pytest.raises(ValidationError) as caught:
        Validation.model_validate(data)
    assert words in str(caught.value)


def test_doc_example_passes(example):
    Validation.model_validate(example)


def test_old_shape_without_reason_count_is_rejected(example):
    # 이유 일치의 분모가 없던 모양은 이제 받지 않는다 (화면이 n 을 분모로 잘못 보이지 않게)
    for venue in example["venues"].values():
        del venue["reason_n"], venue["reason_enough"]
    del example["total"]
    with pytest.raises(ValidationError):
        Validation.model_validate(example)


def test_reason_count_cannot_exceed_reviews(example):
    example["venues"]["thebuffet"]["reason_n"] = 4
    example["total"]["reason_n"] += 3
    _rejects(example, "reason_n 이 n 보다 크다")


def test_reason_enough_follows_min_reviews(example):
    example["venues"]["pizzahill"]["reason_enough"] = True
    example["venues"]["pizzahill"]["reason_match"] = 1
    example["venues"]["pizzahill"]["reason_match_baseline"] = 1
    _rejects(example, "reason_enough 가 reason_n 과 min_reviews 로 정한 것과 다르다")


def test_reason_counts_are_null_when_not_enough(example):
    example["venues"]["pizzahill"]["reason_match"] = 1
    _rejects(example, "reason_enough 가 false 면 건수는 null 이다")


def test_reason_counts_are_required_when_enough(example):
    example["venues"]["geumryong"]["reason_match_baseline"] = None
    _rejects(example, "reason_enough 가 true 면 건수를 모두 적는다")


def test_reason_match_cannot_exceed_reason_count(example):
    example["venues"]["geumryong"]["reason_match"] = 7
    example["total"]["reason_match"] = 8
    _rejects(example, "Value error, 건수가 reason_n 보다 크다")


def test_venue_counts_still_follow_enough(example):
    # 업장 일치의 규칙은 그대로다: 건수가 모자란 업장은 null
    example["venues"]["thebuffet"]["venue_match"] = 1
    _rejects(example, "Value error, enough 가 false 면 건수는 null 이다")


def test_total_is_required(example):
    del example["total"]
    with pytest.raises(ValidationError):
        Validation.model_validate(example)


@pytest.mark.parametrize("name", ["n", "reason_n"])
def test_total_counts_are_the_sum_of_venues(example, name):
    example["total"][name] += 1
    _rejects(example, f"total 의 {name} 이 업장들의 {name} 을 합친 것과 다르다")


def test_total_match_cannot_be_below_the_written_venues(example):
    # 적힌 업장의 합(금룡 8 + 피자힐 5)보다 작을 수 없다
    example["total"]["venue_match"] = 12
    _rejects(example, "total 의 venue_match 은 업장들에 적힌 건수의 합 13 이상")


def test_total_match_may_include_venues_without_enough_reviews(example):
    # 건수가 모자란 업장(더뷔페)의 후기도 total 에 들어가 적힌 합보다 클 수 있다
    assert example["total"]["venue_match"] > 8 + 5
    Validation.model_validate(example)


def test_total_match_equals_the_sum_when_every_venue_is_written(example):
    del example["venues"]["thebuffet"], example["venues"]["pizzahill"]
    example["total"] = {
        "n": 12,
        "venue_match": 8,
        "venue_match_baseline": 7,
        "reason_n": 6,
        "reason_match": 4,
        "reason_match_baseline": 3,
    }
    Validation.model_validate(example)
    example["total"]["venue_match_baseline"] = 8
    _rejects(example, "total 의 venue_match_baseline 은 업장들에 적힌 건수의 합 7 이상, 건수가 모자란 업장의 n 까지 더한 7 이하다")


@pytest.mark.parametrize(
    ("name", "most"),
    [
        # 금룡 8 + 피자힐 5 가 적혔고, 더뷔페는 null 이라 n 3 까지 더할 수 있다
        ("venue_match", 8 + 5 + 3),
        # 금룡 4 가 적혔고, 피자힐과 더뷔페는 null 이라 reason_n 2 + 1 까지 더할 수 있다
        ("reason_match", 4 + 2 + 1),
    ],
)
def test_total_match_cannot_exceed_what_the_venues_allow(example, name, most):
    # 11-17 독립 검토: 건수가 모자란 업장의 분모보다 더 많이 맞을 수는 없다
    example["total"][name] = most
    Validation.model_validate(example)
    example["total"][name] = most + 1
    _rejects(example, f"total 의 {name} 은")
