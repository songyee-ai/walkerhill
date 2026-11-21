"""검증 결과 `validation.json` 의 이유 일치 건수 규칙 (FORMATS.md 10.5절, PRD 6.6절, T117)과
기대 일치 건수·후기마다의 몫 `venue_share` 의 규칙 (T226).

값은 문서의 예시(지어낸 값)를 고쳐 가며 본다.
"""

from __future__ import annotations

import copy
import json
import sys

import pytest
from conftest import REPO_ROOT
from pydantic import ValidationError

from engine.formats import Validation, ValidationReview, read_model, validation_problems
from engine.formats.io import read_csv, write_csv
from engine.formats.run import VALIDATION_REVIEW_COLUMNS

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.validation import validation_rows  # noqa: E402


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
        "venue_expected": 7.35,
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


# ── 기대 일치 건수와 후기마다의 몫 (FORMATS.md 10.5절, T226) ─────────────────────
# 값은 모두 지어낸 것이다. 문서 예시의 업장 셋(금룡 12건, 피자힐 9건, 더뷔페 3건)에 맞춰 후기 줄을 만든다.


def _review(review_id: str, venue_id: str, match: str, share: float | None) -> dict[str, str]:
    """돌린 후기 한 줄. Y 면 고른 곳이 후기의 업장이고, N 이면 다른 곳(예시호텔 중식당)을 고른 것이다."""
    return {
        "review_id": review_id,
        "venue_id": venue_id,
        "customer_group": "커플·기념일",
        "persona_id": "couple-anniversary",
        "occasion": "dining",
        "meal": "dinner",
        "day_type": "weekend",
        "chosen_venue_id": venue_id if match == "Y" else "example-chinese",
        "venue_match": match,
        "venue_share": "" if share is None else str(share),
        "reason_match": "",
        "baseline_venue_id": "example-chinese",
        "baseline_venue_match": "N",
        "baseline_reason_match": "",
        "skipped": "",
    }


SKIPPED_ROW = {name: "" for name in VALIDATION_REVIEW_COLUMNS} | {
    "review_id": "R-skip",
    "venue_id": "geumryong",
    "skipped": "고객군이 비어 있음",
}


def _doc_reviews() -> list[dict[str, str]]:
    """문서 예시의 기대 일치(금룡 7.35, 피자힐 4.62, 더뷔페 1.23, 합 13.2)와 일치 건수(8, 5, 2)에 맞는 후기 줄."""
    plan = {
        "geumryong": [("Y", 0.8)] * 8 + [("N", 0.25)] * 3 + [("N", 0.2)],
        "pizzahill": [("Y", 0.7)] * 5 + [("N", 0.3)] * 3 + [("N", 0.22)],
        "thebuffet": [("Y", 0.5)] * 2 + [("N", 0.23)],
    }
    rows = [
        _review(f"R-{venue}-{i}", venue, match, share)
        for venue, items in plan.items()
        for i, (match, share) in enumerate(items)
    ]
    return [*rows, SKIPPED_ROW]


def _reviews(rows: list[dict[str, str]]) -> list[ValidationReview]:
    return [ValidationReview.from_row(row) for row in rows]


def _old(example: dict) -> dict:
    """11-21 전(11-18 T19)의 모양: 기대 일치 칸이 없다."""
    for venue in example["venues"].values():
        del venue["venue_expected"]
    del example["total"]["venue_expected"]
    return example


def test_doc_example_has_expected_counts(example):
    validation = Validation.model_validate(example)
    assert validation.venues["geumryong"].venue_expected == 7.35
    assert validation.venues["thebuffet"].venue_expected is None  # 검증 건수 부족이면 null
    assert validation.total.venue_expected == 13.2


def test_old_result_without_expected_counts_is_still_read(example, tmp_path):
    # 화면이 읽는 그대로(엄격하게) 읽힌다
    path = tmp_path / "validation.json"
    path.write_text(json.dumps(_old(example), ensure_ascii=False), encoding="utf-8")
    validation = read_model(path, Validation)
    assert validation.total.venue_expected is None
    assert all(v.venue_expected is None for v in validation.venues.values())


def test_expected_count_may_be_an_integer_in_json(example, tmp_path):
    # 1단계 답이면 합이 정수일 수 있다. JSON 의 8 은 실수 칸에서도 읽힌다
    example["venues"]["geumryong"]["venue_expected"] = 8
    example["total"]["venue_expected"] = 14
    path = tmp_path / "validation.json"
    path.write_text(json.dumps(example), encoding="utf-8")
    assert read_model(path, Validation).venues["geumryong"].venue_expected == 8


@pytest.mark.parametrize(
    ("value", "words"),
    [
        (12.01, "venue_expected 이 n 보다 크다"),
        (-0.01, "greater than or equal to 0"),
        (7.355, "소수점 아래 2자리까지"),
    ],
)
def test_venue_expected_range_and_rounding(example, value, words):
    example["venues"]["geumryong"]["venue_expected"] = value
    _rejects(example, words)


def test_venue_expected_is_null_when_not_enough(example):
    example["venues"]["thebuffet"]["venue_expected"] = 1.23
    _rejects(example, "enough 가 false 면 venue_expected 는 null 이다")


def test_venue_expected_is_written_on_every_enough_venue_with_the_total(example):
    example["venues"]["pizzahill"]["venue_expected"] = None
    _rejects(example, "업장 'pizzahill' 의 venue_expected 가 없다")


def test_venue_expected_is_not_written_on_venues_without_the_total(example):
    example["total"]["venue_expected"] = None
    _rejects(example, "total 에 venue_expected 가 없는데 업장에는 있다")


def test_total_expected_cannot_exceed_n(example):
    example["total"]["venue_expected"] = 24.01
    _rejects(example, "total 의 venue_expected 이 n 보다 크다")


@pytest.mark.parametrize(
    ("total", "passes"),
    [
        # 적힌 업장의 합은 7.35 + 4.62 = 11.97, 더뷔페(null)의 n 3 까지 더하면 14.97.
        # 값마다 반올림해 적어 (적힌 값 둘 + total) × 0.005 = 0.015 까지는 봐준다
        (11.97, True),
        (14.97, True),
        (11.96, True),
        (11.95, False),
        (14.98, True),
        (14.99, False),
    ],
)
def test_total_expected_stays_within_what_the_venues_allow(example, total, passes):
    example["total"]["venue_expected"] = total
    if passes:
        Validation.model_validate(example)
    else:
        _rejects(example, "total 의 venue_expected 는 업장들에 적힌 값의 합 11.97 이상")


def test_review_rows_of_the_doc_example_pass():
    reviews = _reviews(_doc_reviews())
    assert len([r for r in reviews if r.skipped is None]) == 24


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"venue_share": "1.2"}, "less than or equal to 1"),
        ({"venue_share": "-0.1"}, "greater than or equal to 0"),
        # 고른 곳(choice)이 후기의 업장인데 몫이 0 일 수는 없다 (choice 의 곳은 점수가 0 보다 크다)
        ({"venue_share": "0"}, "venue_match 가 Y 면 venue_share 는 0 보다 크다"),
        # 다른 곳을 골랐으면 그 곳도 몫을 받아 후기의 업장이 전부(1)를 받을 수는 없다
        (
            {"venue_match": "N", "chosen_venue_id": "example-chinese", "venue_share": "1"},
            "venue_match 가 N 이면 venue_share 는 1 보다 작다",
        ),
        ({"venue_match": "N", "chosen_venue_id": "", "venue_share": "1"}, "venue_match 가 N 이면 venue_share 는 1 보다 작다"),
        ({"venue_match": "N"}, "venue_match 는 chosen_venue_id 가 후기의 venue_id 와 같을 때만 Y 다"),
        ({"baseline_venue_match": "Y"}, "baseline_venue_match 는 baseline_venue_id 가"),
        ({"venue_match": ""}, "venue_match 와 baseline_venue_match 를 적는다"),
    ],
)
def test_review_row_rules(change, words):
    with pytest.raises(ValidationError) as caught:
        ValidationReview.from_row(_review("R-1", "geumryong", "Y", 0.8) | change)
    assert words in str(caught.value)


def test_review_row_share_boundaries_pass():
    # choice 는 점수가 가장 큰 곳이라는 보장이 없고 몫은 상수로 바뀌어, 다른 곳을 골랐어도 후기의 업장이 더 큰 몫을 받을 수 있다
    ValidationReview.from_row(_review("R-1", "geumryong", "N", 0.9))
    ValidationReview.from_row(_review("R-1", "geumryong", "N", 0.9999))
    ValidationReview.from_row(_review("R-1", "geumryong", "N", 0))
    ValidationReview.from_row(_review("R-1", "geumryong", "Y", 1))
    # 몫은 반올림하지 않는다. 상수가 아주 작은 곳을 고른 답도 몫이 0 보다 크게 남는다
    assert ValidationReview.from_row(_review("R-1", "geumryong", "Y", 1e-05)).venue_share == 1e-05


def test_skipped_review_has_no_share():
    ValidationReview.from_row(SKIPPED_ROW)
    with pytest.raises(ValidationError) as caught:
        ValidationReview.from_row(SKIPPED_ROW | {"venue_share": "0"})
    assert "돌린 결과의 칸이 빈 칸이다" in str(caught.value)


def _write_csv(path, columns: list[str], rows: list[dict[str, str]]) -> None:
    write_csv(path, columns, [{c: row[c] for c in columns} for row in rows])


def test_new_csv_reads_with_the_share_column(tmp_path):
    path = tmp_path / "validation_reviews.csv"
    _write_csv(path, VALIDATION_REVIEW_COLUMNS, _doc_reviews())
    assert VALIDATION_REVIEW_COLUMNS.index("venue_share") == VALIDATION_REVIEW_COLUMNS.index("venue_match") + 1
    reviews = _reviews(read_csv(path, VALIDATION_REVIEW_COLUMNS))
    assert reviews[0].venue_share == 0.8


def test_old_csv_without_the_share_column_is_still_read(tmp_path):
    # 11-18 T19 의 파일에는 venue_share 열이 없다. 빈 칸으로 읽는다 (engine.formats.io.ADDED_LATER)
    old_columns = [c for c in VALIDATION_REVIEW_COLUMNS if c != "venue_share"]
    path = tmp_path / "validation_reviews.csv"
    _write_csv(path, old_columns, _doc_reviews())
    reviews = _reviews(read_csv(path, VALIDATION_REVIEW_COLUMNS))
    assert len(reviews) == 25
    assert all(r.venue_share is None for r in reviews)


def test_both_files_agree_on_the_doc_example(example):
    validation = Validation.model_validate(example)
    assert validation_problems(validation, _reviews(_doc_reviews()), "scores") == []


def test_old_pair_has_no_problems(example):
    rows = [row | {"venue_share": ""} for row in _doc_reviews()]
    assert validation_problems(Validation.model_validate(_old(example)), _reviews(rows)) == []


def test_old_result_with_new_rows_is_a_problem(example):
    problems = validation_problems(Validation.model_validate(_old(example)), _reviews(_doc_reviews()))
    assert problems and "venue_expected 가 없는데" in problems[0]


def test_new_result_needs_a_share_on_every_reviewed_row(example):
    rows = _doc_reviews()
    rows[0] = rows[0] | {"venue_share": ""}
    problems = validation_problems(Validation.model_validate(example), _reviews(rows))
    assert problems == ["돌린 후기의 venue_share 가 비어 있다: ['R-geumryong-0']"]


def test_expected_counts_must_be_the_sum_of_the_rows(example):
    example["venues"]["geumryong"]["venue_expected"] = 7.4
    example["total"]["venue_expected"] = 13.25
    problems = validation_problems(Validation.model_validate(example), _reviews(_doc_reviews()))
    assert len(problems) == 2
    assert "업장 'geumryong' 의 venue_expected 7.4 가 후기들의 venue_share 합 7.3500 와 다르다" in problems[0]
    assert "total 의 venue_expected 13.25" in problems[1]


def test_rounding_of_the_sum_is_allowed(example):
    # 기대 일치는 몫의 합을 소수 둘째 자리로 반올림해 적는다. 그 폭(0.005)까지는 같은 것으로 본다
    rows = _doc_reviews()
    rows[0] = rows[0] | {"venue_share": "0.8049"}
    example["total"]["venue_expected"] = 13.2
    assert validation_problems(Validation.model_validate(example), _reviews(rows)) == []
    rows[0] = rows[0] | {"venue_share": "0.8051"}
    assert len(validation_problems(Validation.model_validate(example), _reviews(rows))) == 2


def test_single_answers_give_shares_of_zero_or_one(example):
    # 점수가 없는 답(1단계 방식)이면 몫이 0 아니면 1 이라 기대 일치가 일치 건수와 같다 (11-18 결과와 같다)
    rows = [
        row if row["skipped"] else row | {"venue_share": "1" if row["venue_match"] == "Y" else "0"}
        for row in _doc_reviews()
    ]
    single = copy.deepcopy(example)
    single["venues"]["geumryong"]["venue_expected"] = 8
    single["venues"]["pizzahill"]["venue_expected"] = 5
    single["total"]["venue_expected"] = 15
    assert validation_problems(Validation.model_validate(single), _reviews(rows), "single") == []
    # 몫으로 나뉜 답이 single 실행의 결과에 들어 있으면 잡는다
    problems = validation_problems(Validation.model_validate(example), _reviews(_doc_reviews()), "single")
    assert problems and "share_method single" in problems[-1]


def test_screen_reads_new_and_old_results(example):
    # 화면(app/validation.py)은 새 칸을 아직 쓰지 않는다. 새 결과와 옛 결과에서 같은 표가 나온다
    # (화면에 기대 일치를 보이는 것은 "알릴 것"의 11-21 T226 화면 줄)
    names = {"geumryong": "금룡", "pizzahill": "피자힐", "thebuffet": "더뷔페"}
    new = validation_rows(Validation.model_validate(example), names)
    old = validation_rows(Validation.model_validate(_old(copy.deepcopy(example))), names)
    assert new == old
    assert new[0]["고른 업장이 같음"] == "12건 중 8건"


def test_scored_run_needs_the_new_columns(example):
    # 11-18 결과는 모두 1단계 답이다. 옛 모양(새 칸 없음)은 single 실행에서만 받는다
    rows = [row | {"venue_share": ""} for row in _doc_reviews()]
    old = Validation.model_validate(_old(example))
    assert validation_problems(old, _reviews(rows), "single") == []
    for method in ("scores", "mixed"):
        problems = validation_problems(old, _reviews(rows), method)
        assert problems == [f"점수를 받은 실행(share_method {method})의 검증 결과인데 venue_expected 가 없다"]


def test_single_answers_pair_shares_with_the_match():
    # 1단계 답은 고른 곳의 몫이 1 이라 Y 는 1, N 은 0 이다. Y 인데 1 이 아닌 몫(0.8)은 잡는다
    validation = Validation.model_validate(
        {
            "format_version": 1,
            "created_at": "2026-11-21T10:00:00+09:00",
            "min_reviews": 1,
            "venues": {
                "geumryong": {
                    "n": 2, "enough": True, "venue_match": 1, "venue_match_baseline": 0, "venue_expected": 0.8,
                    "reason_n": 0, "reason_enough": False, "reason_match": None, "reason_match_baseline": None,
                },
            },
            "total": {
                "n": 2, "venue_match": 1, "venue_match_baseline": 0, "venue_expected": 0.8,
                "reason_n": 0, "reason_match": 0, "reason_match_baseline": 0,
            },
        }
    )
    reviews = _reviews([_review("R-1", "geumryong", "Y", 0.8), _review("R-2", "geumryong", "N", 0)])
    assert validation_problems(validation, reviews, "scores") == []
    problems = validation_problems(validation, reviews, "single")
    assert problems == ["점수가 없는 답(share_method single)인데 venue_share 가 Y 면 1, N 이면 0 이 아니다: ['R-1']"]


def test_review_counts_must_match_n(example):
    validation = Validation.model_validate(example)
    rows = _doc_reviews()
    # 금룡 후기 하나를 돌리지 못한 것으로 바꾸면 금룡의 n(12)과 total 의 n(24)이 후기 수와 어긋난다
    skipped = SKIPPED_ROW | {"review_id": rows[0]["review_id"]}
    problems = validation_problems(validation, _reviews([skipped, *rows[1:]]))
    assert "업장 'geumryong' 의 n 12 이 돌린 후기 수 11 와 다르다" in problems
    assert "total 의 n 24 이 돌린 후기 수 23 와 다르다" in problems


def test_reviews_of_unknown_venues_are_a_problem(example):
    rows = [*_doc_reviews(), _review("R-x", "moegi", "N", 0)]
    problems = validation_problems(Validation.model_validate(example), _reviews(rows))
    assert problems[0] == "validation.json 의 venues 에 없는 업장의 돌린 후기가 있다: ['moegi']"
    # 돌리지 못한 후기는 venues 에 없는 업장이어도 된다
    rows = [*_doc_reviews(), SKIPPED_ROW | {"review_id": "R-y", "venue_id": "moegi"}]
    assert validation_problems(Validation.model_validate(example), _reviews(rows)) == []
