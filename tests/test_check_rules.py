"""검사 도구가 잘못된 파일을 실제로 잡아내는지 본다.

예시 파일 한 벌을 베낀 뒤 한 군데씩 일부러 망가뜨리고, 그 문제가 보고되는지 확인한다.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import BASELINE_RUN, COMPETITOR_RUN, REPO_ROOT, load_csv, load_json, save_csv, save_json

from engine.formats import compute_request_hash
from tools import check_formats
from tools.check_formats import (
    BASE_PROFILE_NOTE,
    IGNORED_DIR_NAMES,
    PRIVATE_LAYER_NOTE,
    Checker,
    Problem,
    check,
    ignored_by_git,
    inspect_content,
)

VENUES = Path("data/venues")
REVIEWS = Path("data/evidence/reviews/geumryong.csv")
RUNS = Path("engine/samples/runs")
LEDGER = RUNS / BASELINE_RUN / "ledger.csv"

# 저장소에 올리면 안 되는 후기 번호의 모양 (지어낸 번호다).
HIDDEN_ID = "P-geumryong-0002"


def edit_json(root: Path, relative: Path, change) -> None:
    data = load_json(root / relative)
    change(data)
    save_json(root / relative, data)


def write(root: Path, relative: str, content: str | bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8", newline="\n")
    return path


def saved_response_path(root: Path, run_id: str = BASELINE_RUN) -> Path:
    """그 실행의 저장된 응답 파일 (예시에는 실행마다 하나씩 있다). root 에서 본 경로를 돌려준다."""
    return next((root / RUNS / run_id / "llm").glob("*.json")).relative_to(root)


def edit_csv(root: Path, relative: Path, change, bom: bool = True) -> None:
    rows = load_csv(root / relative)
    change(rows)
    save_csv(root / relative, rows, bom=bom)


def found(problems: list[Problem], text: str, level: str = "error") -> bool:
    return any(p.level == level and text in str(p) for p in problems)


def messages(problems: list[Problem]) -> str:
    return "\n".join(str(p) for p in problems)


# ── 업장 정의 ────────────────────────────────────────────────────────────────


def test_product_occasion_must_be_in_venue(example_copy):
    slots = [{"meal": None, "day_type": "all"}]
    edit_json(example_copy, VENUES / "geumryong.json", lambda d: d["products"][0].update(occasion="dessert", slots=slots))
    problems = check(example_copy)
    assert found(problems, "occasion 이 업장의 occasions 에 없다"), messages(problems)


def test_unknown_code_value_is_reported_in_korean(example_copy):
    edit_json(example_copy, VENUES / "geumryong.json", lambda d: d["products"][0].update(qty_rule="per_table"))
    problems = check(example_copy)
    assert found(problems, "products[0].qty_rule — 쓸 수 없는 값 'per_table'"), messages(problems)


def test_misspelled_key_is_reported(example_copy):
    def change(data):
        data["prodcts"] = data.pop("products")

    edit_json(example_copy, VENUES / "geumryong.json", change)
    problems = check(example_copy)
    assert found(problems, "prodcts — 약속에 없는 키다"), messages(problems)
    assert found(problems, "products — 키가 빠졌다"), messages(problems)


def test_competitor_must_name_the_venue_it_competes_with(example_copy):
    edit_json(example_copy, VENUES / "examplehotel-chinese.json", lambda d: d.update(competes_with=[]))
    problems = check(example_copy)
    assert found(problems, "경쟁 업장은 competes_with 에"), messages(problems)


def test_non_competitor_must_be_a_walkerhill_venue(example_copy):
    edit_json(
        example_copy, VENUES / "examplehotel-buffet.json", lambda d: d.update(is_competitor=False, competes_with=[])
    )
    problems = check(example_copy)
    assert found(problems, "워커힐 업장의 venue_id 가 아니다"), messages(problems)


def test_source_id_must_exist(example_copy):
    edit_json(example_copy, VENUES / "geumryong.json", lambda d: d["products"][0].update(source_id="S9"))
    problems = check(example_copy)
    assert found(problems, "source_id 가 sources 에 없다"), messages(problems)


def test_file_name_must_match_venue_id(example_copy):
    (example_copy / VENUES / "geumryong.json").rename(example_copy / VENUES / "ondal.json")
    problems = check(example_copy)
    assert found(problems, "파일 이름이 venue_id 'geumryong' 와 다르다"), messages(problems)


def test_venue_without_competitor_is_a_warning_until_strict(example_copy):
    (example_copy / VENUES / "examplehotel-chinese.json").unlink()
    assert found(check(example_copy), "견주는 경쟁 업장이 아직 없다", level="warning")
    assert found(check(example_copy, strict=True), "견주는 경쟁 업장이 아직 없다", level="error")


# ── 후기 라벨 ────────────────────────────────────────────────────────────────


def test_review_label_must_be_in_vocab(example_copy):
    edit_csv(example_copy, REVIEWS, lambda rows: rows[0].update(reasons_chosen="별실;분위기 좋음"))
    problems = check(example_copy)
    assert found(problems, "reasons_chosen 의 '분위기 좋음' 가 값 목록에 없다"), messages(problems)


@pytest.mark.parametrize("column", ["purpose", "party"])
def test_review_purpose_and_party_must_be_in_vocab_when_written(example_copy, column):
    edit_csv(example_copy, REVIEWS, lambda rows: rows[0].update({column: "소풍"}))
    problems = check(example_copy)
    assert found(problems, f"{column} '소풍' 가 값 목록에 없다"), messages(problems)


@pytest.mark.parametrize(
    "blank",
    [
        {"purpose": ""},
        {"party": ""},
        {"summary": ""},
        # 글과 화면에 없는 것은 비운다. 빈 칸만 있는 칸(공백)도 빈 칸이다.
        {"purpose": " ", "party": "", "summary": ""},
    ],
)
def test_review_label_may_leave_what_the_review_does_not_say(example_copy, blank):
    edit_csv(example_copy, REVIEWS, lambda rows: rows[0].update(blank))
    problems = check(example_copy, strict=True)
    assert not problems, messages(problems)


# 근거가 되는 칸과, 그 칸 하나만 남겼을 때 쓸 값 (예시 묶음에 있는 값이다).
EVIDENCE = {
    "purpose": "가족 행사",
    "party": "3대 가족",
    "ordered": "course-a",
    "reasons_chosen": "별실",
    "pain_points": "가격",
    "compared_with": "examplehotel-chinese",
    "would_return": "yes",
}
NO_EVIDENCE = "근거가 되는 칸이 모두 비어 있다"


def test_review_label_without_any_evidence_is_rejected(example_copy):
    # 고객군, 이용 상황, 요약이 있어도 근거가 되는 칸이 없으면 쓸 수 없는 후기다.
    edit_csv(example_copy, REVIEWS, lambda rows: rows[0].update(dict.fromkeys(EVIDENCE, "")))
    problems = check(example_copy)
    assert [p.path for p in problems if NO_EVIDENCE in p.message] == [REVIEWS.as_posix()], messages(problems)
    assert found(problems, "2번째 줄"), messages(problems)


@pytest.mark.parametrize("column", ["ordered", "compared_with"])
@pytest.mark.parametrize("value", ["이름:", "이름: ", "course-a;이름:"])
def test_free_name_needs_a_name(example_copy, column, value):
    # 이름이 없는 '이름:' 은 아무것도 말하지 않는다. 근거가 있는 후기처럼 지나가지 못하게 한다.
    edit_csv(example_copy, REVIEWS, lambda rows: rows[0].update({column: value}))
    problems = check(example_copy)
    assert found(problems, f"{column} 에 '이름:' 만 있고 이름이 없다"), messages(problems)


@pytest.mark.parametrize("column", list(EVIDENCE))
def test_one_evidence_column_is_enough_for_a_review_label(example_copy, column):
    only = {**dict.fromkeys(EVIDENCE, ""), column: EVIDENCE[column]}
    edit_csv(example_copy, REVIEWS, lambda rows: rows[0].update(only))
    problems = check(example_copy, strict=True)
    assert not found(problems, NO_EVIDENCE), messages(problems)


def test_private_review_id_is_rejected(example_copy):
    edit_csv(example_copy, REVIEWS, lambda rows: rows[1].update(review_id="P-geumryong-0011"))
    problems = check(example_copy)
    assert found(problems, "저장소에 올리지 않는다"), messages(problems)
    assert found(problems, "H 나 P 로 시작하는 후기 번호가 있다: P-geumryong-0011"), messages(problems)


def test_review_number_range_depends_on_folder(example_copy):
    edit_csv(example_copy, REVIEWS, lambda rows: rows[1].update(review_id="R-geumryong-5001"))
    problems = check(example_copy)
    assert found(problems, "이 폴더의 번호대는 0001 ~ 4999 다"), messages(problems)


def test_ordered_product_must_exist_or_use_free_name(example_copy):
    edit_csv(example_copy, REVIEWS, lambda rows: rows[0].update(ordered="course-z"))
    assert found(check(example_copy), "ordered 의 'course-z' 가 업장 정의에 없다")
    edit_csv(example_copy, REVIEWS, lambda rows: rows[0].update(ordered="이름:계절 특선"))
    assert not found(check(example_copy), "ordered")


def test_csv_without_bom_is_a_warning(example_copy):
    edit_csv(example_copy, REVIEWS, lambda rows: None, bom=False)
    problems = check(example_copy)
    assert found(problems, "BOM 이 없다", level="warning"), messages(problems)
    assert not [p for p in problems if p.level == "error"], messages(problems)


def test_url_list_must_not_be_in_repository(example_copy):
    (example_copy / "data" / "evidence" / "review_urls.csv").write_text("venue_id,url\n", encoding="utf-8")
    problems = check(example_copy)
    assert found(problems, "후기 주소 목록은 저장소에 올리지 않는다"), messages(problems)


# ── 페르소나 ─────────────────────────────────────────────────────────────────


def test_persona_needs_all_seven_evidence_groups(example_copy):
    edit_json(example_copy, Path("personas/family-elders.json"), lambda d: d["evidence"].pop("budget"))
    problems = check(example_copy)
    assert found(problems, "evidence.budget — 키가 빠졌다"), messages(problems)


def test_share_below_one_is_a_warning_until_strict(example_copy):
    (example_copy / "personas" / "family-kids.json").unlink()
    assert found(check(example_copy), "몫을 더하면 0.5 다", level="warning")
    assert found(check(example_copy, strict=True), "몫을 더하면 0.5 다", level="error")


def test_share_above_one_is_an_error(example_copy):
    edit_json(example_copy, Path("personas/family-kids.json"), lambda d: d["share_in_group"].update(value=0.7))
    problems = check(example_copy)
    assert found(problems, "1 을 넘을 수 없다"), messages(problems)


def test_evidence_must_point_to_existing_review(example_copy):
    edit_json(
        example_copy,
        Path("personas/family-elders.json"),
        lambda d: d["evidence"]["buying"].update(refs=["R-geumryong-0999"]),
    )
    problems = check(example_copy)
    assert found(problems, "후기 'R-geumryong-0999' 가 후기 라벨 파일에 없다"), messages(problems)


def test_public_persona_cannot_cite_private_review(example_copy):
    edit_json(
        example_copy,
        Path("personas/family-elders.json"),
        lambda d: d["evidence"]["buying"]["refs"].append("P-geumryong-0002"),
    )
    problems = check(example_copy)
    assert found(problems, "저장소에 올릴 수 없는 후기다"), messages(problems)


def test_review_grade_needs_a_review(example_copy):
    edit_json(
        example_copy, Path("personas/family-kids.json"), lambda d: d["evidence"]["visit"].update(grade="review")
    )
    problems = check(example_copy)
    assert found(problems, "등급이 review 인데 근거로 든 후기 번호가 없다"), messages(problems)


def test_persona_label_must_be_in_vocab(example_copy):
    edit_json(
        example_copy, Path("personas/family-kids.json"), lambda d: d["visit"]["party"].update(label="대가족")
    )
    problems = check(example_copy)
    assert found(problems, "visit.party.label '대가족' 가 값 목록에 없다"), messages(problems)


# ── 방문 조건과 상황 ─────────────────────────────────────────────────────────


def test_meal_condition_needs_a_meal(example_copy):
    edit_json(example_copy, Path("engine/conditions.json"), lambda d: d["conditions"][0].update(meal=None))
    problems = check(example_copy)
    assert found(problems, "식사 조건에는 meal 이 있어야 한다"), messages(problems)


def test_our_scenario_cannot_change_a_competitor(example_copy):
    edit_json(
        example_copy,
        Path("scenarios/geumryong-course-price-up.json"),
        lambda d: d["changes"][0].update(venue_id="examplehotel-chinese", product_id="course"),
    )
    problems = check(example_copy)
    assert found(problems, "우리 쪽 상황(our_price)은 워커힐 업장만 바꾼다"), messages(problems)


def test_scenario_must_point_to_existing_product(example_copy):
    edit_json(
        example_copy,
        Path("scenarios/geumryong-course-price-up.json"),
        lambda d: d["changes"][0].update(product_id="course-z"),
    )
    problems = check(example_copy)
    assert found(problems, "상품 'course-z' 가 업장 'geumryong' 에 없다"), messages(problems)


def test_unknown_change_op_is_reported(example_copy):
    edit_json(
        example_copy, Path("scenarios/geumryong-course-price-up.json"), lambda d: d["changes"][0].update(op="raise")
    )
    problems = check(example_copy)
    assert found(problems, "op 에 쓸 수 없는 값 'raise'"), messages(problems)


def test_baseline_scenario_is_required(example_copy):
    (example_copy / "scenarios" / "baseline.json").unlink()
    problems = check(example_copy)
    assert found(problems, "기준 상황 scenarios/baseline.json 이 없다"), messages(problems)


# ── 가상 예시 값과 실행 결과 ─────────────────────────────────────────────────


def test_summary_must_point_to_existing_product(example_copy):
    edit_csv(example_copy, Path("data/samples/base_summary.csv"), lambda rows: rows[0].update(product_id="course-z"))
    problems = check(example_copy)
    assert found(problems, "상품 'course-z' 가 업장 'geumryong' 에 없다"), messages(problems)


SUMMARY = Path("data/samples/base_summary.csv")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        # 낸 금액은 세금 포함이고 매출은 세금을 뺀 값이다. 둘을 같은 값으로 적으면 틀린 것이다.
        ({"paid": "40909091"}, "revenue_net 이 paid ÷ 1.1 과 다르다"),
        # 금액이 작아도 틀린 줄은 잡는다: 팔린 것이나 낸 금액이 없는데 매출만 있는 줄.
        ({"quantity": "0", "paid": "0", "revenue_net": "1"}, "quantity 가 0 인데 paid 나 revenue_net 이 있다"),
        ({"paid": "0", "revenue_net": "1"}, "paid 가 0 인데 revenue_net 이 있다"),
        ({"month": "13"}, "month — '13' 는 쓸 수 있는 범위를 벗어난다"),
        ({"month": ""}, "month —"),
        # 코스 B 는 저녁에만 판다.
        ({"product_id": "course-b", "meal": "lunch"}, "끼니 'lunch', 요일 'weekday' 은 그 상품을 파는 때(slots)가 아니다"),
    ],
)
def test_summary_row_rules(example_copy, change, message):
    edit_csv(example_copy, SUMMARY, lambda rows: rows[0].update(change))
    problems = check(example_copy)
    assert found(problems, message), messages(problems)


def test_summary_has_one_row_per_month(example_copy):
    # 같은 고객군·상품·조건이라도 달이 다르면 다른 줄이다. 달까지 같으면 겹친 줄이다.
    def add(rows, month):
        rows.append({**rows[0], "month": month})

    edit_csv(example_copy, SUMMARY, lambda rows: add(rows, "6"))
    assert [str(p) for p in check(example_copy, strict=True)] == []
    edit_csv(example_copy, SUMMARY, lambda rows: add(rows, "5"))
    problems = check(example_copy)
    assert found(problems, "같은 고객군·업장·상품·조건의 줄이 또 있다"), messages(problems)


def test_summary_month_must_be_a_month_the_product_is_sold(example_copy):
    edit_json(example_copy, VENUES / "geumryong.json", lambda d: d["products"][0].update(months=[9, 10]))
    problems = check(example_copy)
    assert found(problems, "5월은 그 상품을 파는 달이 아니다"), messages(problems)


def test_product_sold_at_mixed_times(example_copy):
    """ "주말 점심과 모든 요일 저녁"에 파는 상품: 평일 점심의 집계 줄은 틀린 것이고, 나머지는 맞다."""
    mixed = [{"meal": "lunch", "day_type": "weekend"}, {"meal": "dinner", "day_type": "all"}]
    edit_json(example_copy, VENUES / "geumryong.json", lambda d: d["products"][0].update(slots=mixed))

    def rows_for(*times):
        def change(rows):
            first = rows[0]
            rows[:] = [{**first, "meal": meal, "day_type": day} for meal, day in times]

        return change

    edit_csv(example_copy, SUMMARY, rows_for(("lunch", "weekend"), ("dinner", "weekday"), ("dinner", "weekend"), ("", "weekday")))
    assert [str(p) for p in check(example_copy, strict=True)] == []
    edit_csv(example_copy, SUMMARY, rows_for(("lunch", "weekday")))
    problems = check(example_copy)
    assert found(problems, "끼니 'lunch', 요일 'weekday' 은 그 상품을 파는 때(slots)가 아니다"), messages(problems)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        # 점심·모든 요일과 점심·주말은 주말 점심이 겹친다.
        (
            lambda d: d["products"][0].update(slots=[{"meal": "lunch", "day_type": "all"}, {"meal": "lunch", "day_type": "weekend"}]),
            "slots 에 같은 때가 두 번 들어 있다",
        ),
        (lambda d: d["products"][0].update(slots=[]), "products[0].slots — 항목의 수가 맞지 않는다"),
        (lambda d: d["products"][0].update(slots=[{"meal": None, "day_type": "all"}]), "식사 상품의 slots 에는 meal 을 적는다"),
        (lambda d: d["products"][0].update(price_basis="excluded"), "products[0].price_basis — 쓸 수 없는 값 'excluded'"),
        (lambda d: d["hours"][0].update(source_id="S9"), "hours[0] 의 source_id 가 sources 에 없다"),
        (lambda d: d["reservation"].update(source_id="S9"), "reservation 의 source_id 가 sources 에 없다"),
        (lambda d: d["hours"][0].pop("source_id"), "hours[0].source_id — 키가 빠졌다"),
        # 바뀌기 전의 형식으로 적은 파일은 받지 않는다.
        (lambda d: d["products"][0].update(meals=["lunch"], day_types=["weekday"]), "products[0].meals — 약속에 없는 키다"),
    ],
)
def test_venue_rules_after_format_review(example_copy, change, message):
    edit_json(example_copy, VENUES / "geumryong.json", change)
    problems = check(example_copy)
    assert found(problems, message), messages(problems)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda c: c.update(stay="guest"), "묶음의 조건은 stay 를 null 로 둔다"),
        (lambda c: c.update(condition_id="meal-breakfast-weekday", meal="breakfast"), "묶음에는 조식 조건을 넣지 않는다"),
    ],
)
def test_bundle_has_no_stay_and_no_breakfast(example_copy, change, message):
    edit_json(example_copy, Path("engine/conditions.json"), lambda d: change(d["conditions"][0]))
    problems = check(example_copy)
    assert found(problems, message), messages(problems)


def test_ledger_amounts_must_add_up(example_copy):
    edit_csv(example_copy, RUNS / BASELINE_RUN / "ledger.csv", lambda rows: rows[0].update(paid="590000"))
    problems = check(example_copy)
    assert found(problems, "paid 가 수량 × 표시가 − 할인과 다르다"), messages(problems)


def test_ledger_revenue_follows_tax_rule(example_copy):
    edit_csv(example_copy, RUNS / BASELINE_RUN / "ledger.csv", lambda rows: rows[0].update(revenue_net="545454"))
    problems = check(example_copy)
    assert found(problems, "revenue_net 이 낸 금액 ÷ 1.1 을 반올림한 값과 다르다"), messages(problems)


def test_competitor_choice_has_no_walkerhill_revenue(example_copy):
    edit_csv(
        example_copy,
        RUNS / COMPETITOR_RUN / "ledger.csv",
        lambda rows: rows[0].update(revenue_net="458182", weighted_revenue="54981840"),
    )
    problems = check(example_copy)
    assert found(problems, "경쟁 업장과 이용하지 않음의 revenue_net 은 0 이다"), messages(problems)


def test_only_sample_runs_may_be_in_repository(example_copy):
    edit_json(example_copy, RUNS / BASELINE_RUN / "run.json", lambda d: d.update(data_mode="private"))
    problems = check(example_copy)
    assert found(problems, "가상 예시 값으로 돌린 결과(data_mode 가 sample)만 둔다"), messages(problems)


def test_saved_request_cannot_be_edited_by_hand(example_copy):
    path = next((example_copy / RUNS / BASELINE_RUN / "llm").glob("*.json"))
    edit_json(example_copy, path.relative_to(example_copy), lambda d: d["request"]["condition"].update(adults=6))
    problems = check(example_copy)
    assert found(problems, "request_hash 가 요청으로 다시 낸 값"), messages(problems)


def test_saved_response_must_choose_from_candidates(example_copy):
    path = next((example_copy / RUNS / BASELINE_RUN / "llm").glob("*.json"))
    edit_json(
        example_copy,
        path.relative_to(example_copy),
        lambda d: d["response"]["choice"].update(venue_id="thebuffet", option_id="thebuffet-o1"),
    )
    problems = check(example_copy)
    assert found(problems, "고른 업장 'thebuffet' 가 후보에 없다"), messages(problems)


def test_validation_results_stay_out_of_repository(example_copy):
    save_json(example_copy / RUNS / BASELINE_RUN / "validation.json", {"format_version": 1})
    problems = check(example_copy)
    assert found(problems, "검증 결과는 저장소에 두지 않는다"), messages(problems)


def test_ledger_must_point_to_saved_response(example_copy):
    edit_csv(
        example_copy, RUNS / BASELINE_RUN / "ledger.csv", lambda rows: rows[0].update(request_hash="0" * 16)
    )
    problems = check(example_copy)
    assert found(problems, "저장된 응답 llm/0000000000000000.json 이 없다"), messages(problems)


def test_request_hash_ignores_key_order_but_not_content():
    request = {"b": 1, "a": {"y": [1, 2], "x": "가"}}
    reordered = {"a": {"x": "가", "y": [1, 2]}, "b": 1}
    base = compute_request_hash("anthropic", "claude-opus-5-5", request)
    assert len(base) == 16
    assert compute_request_hash("anthropic", "claude-opus-5-5", reordered) == base
    assert compute_request_hash("anthropic", "claude-sonnet-5-5", request) != base
    assert compute_request_hash("openai", "claude-opus-5-5", request) != base
    assert compute_request_hash("anthropic", "claude-opus-5-5", {**request, "b": 2}) != base


# ── JSON 은 적힌 그대로 엄격하게 읽는다 ──────────────────────────────────────


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["products"][0].update(price="150000"), "products[0].price — '150000' 는 글자다. 숫자는 따옴표 없이 적는다"),
        (lambda d: d.update(is_competitor="false"), "is_competitor — 'false' 는 참·거짓이 아니다"),
        (lambda d: d["products"][0].update(serves=1.0), "products[0].serves — 1.0 는 정수가 아니다"),
    ],
)
def test_json_value_must_have_the_right_type(example_copy, change, message):
    edit_json(example_copy, VENUES / "geumryong.json", change)
    problems = check(example_copy)
    assert found(problems, message), messages(problems)


@pytest.mark.parametrize(
    ("value", "message"),
    [("2026-11-17T10:15:00", "created_at — '2026-11-17T10:15:00' 에 시간대가 없다"), (0, "created_at — 0 는 날짜와 시각이 아니다")],
)
def test_time_needs_a_time_zone(example_copy, value, message):
    edit_json(example_copy, RUNS / BASELINE_RUN / "run.json", lambda d: d.update(created_at=value))
    problems = check(example_copy)
    assert found(problems, message), messages(problems)


def test_broken_json_is_reported(example_copy):
    write(example_copy, "scenarios/baseline.json", "{not json")
    problems = check(example_copy)
    assert found(problems, "scenarios/baseline.json: JSON 으로 읽을 수 없다"), messages(problems)


# ── 덜 만든 것과 틀린 것 ─────────────────────────────────────────────────────


def test_walkerhill_venue_without_hours_is_a_warning_until_strict(example_copy):
    edit_json(example_copy, VENUES / "geumryong.json", lambda d: d.update(hours=None))
    problems = check(example_copy)
    assert found(problems, "워커힐 업장인데 hours 가 null 이다", level="warning"), messages(problems)
    assert not [p for p in problems if p.level == "error"], messages(problems)
    assert found(check(example_copy, strict=True), "워커힐 업장인데 hours 가 null 이다")


def test_bundle_condition_cannot_fix_a_month(example_copy):
    edit_json(example_copy, Path("engine/conditions.json"), lambda d: d["conditions"][0].update(month=5))
    problems = check(example_copy)
    assert found(problems, "묶음의 조건은 month 를 null 로 둔다"), messages(problems)


# ── 데이터 폴더에는 약속한 것만 둔다 ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("relative", "message"),
    [
        ("data/venues/ondal.JSON", "data/venues/ondal.JSON: 약속에 없는 파일이다"),
        ("data/venues/draft/ondal.json", "data/venues/draft: 약속에 없는 폴더다"),
        ("data/evidence/reviews/old/geumryong.csv", "data/evidence/reviews/old: 약속에 없는 폴더다"),
        ("data/evidence/extra/notes.txt", "data/evidence/extra/notes.txt: 약속에 없는 파일이다"),
        ("data/notes.txt", "data/notes.txt: 약속에 없는 파일이다"),
        ("data/samples/other.csv", "data/samples/other.csv: 약속에 없는 파일이다"),
        ("personas/draft.txt", "personas/draft.txt: 약속에 없는 파일이다"),
        ("scenarios/idea.yaml", "scenarios/idea.yaml: 약속에 없는 파일이다"),
        ("engine/samples/note.txt", "engine/samples/note.txt: 약속에 없는 파일이다"),
        (f"engine/samples/runs/{BASELINE_RUN}/extra.csv", "extra.csv: 약속에 없는 파일이다"),
        (f"engine/samples/runs/{BASELINE_RUN}/llm/note.txt", "llm/note.txt: 약속에 없는 파일이다"),
    ],
)
def test_data_folder_holds_only_what_was_agreed(example_copy, relative, message):
    write(example_copy, relative, "x\n")
    problems = check(example_copy)
    assert found(problems, message), messages(problems)


def test_upper_case_suffix_gets_a_hint(example_copy):
    write(example_copy, "data/venues/ondal.JSON", "{}\n")
    assert found(check(example_copy), "확장자는 소문자로 적는다")


def test_guide_files_and_prompts_are_allowed(example_copy):
    write(example_copy, "personas/prompts/p1.md", "당신은 호텔에서 식사할 곳을 고르는 손님입니다.\n")
    write(example_copy, "personas/README.md", "안내\n")
    write(example_copy, "data/venues/README.md", "안내\n")
    write(example_copy, f"engine/samples/runs/{BASELINE_RUN}/README.md", "안내\n")
    assert [str(p) for p in check(example_copy, strict=True)] == []


# ── 올리면 안 되는 것: 파일의 종류, 자리, 크기, 글자 인코딩에 기대지 않고 찾는다 ──


@pytest.mark.parametrize(
    "relative", ["personas/prompts/p1.md", "docs/notes.txt", "app/helper.py", "memo.jsonl", "data/venues/README.md"]
)
def test_private_review_id_is_found_in_any_kind_of_file(example_copy, relative):
    write(example_copy, relative, f"근거: {HIDDEN_ID}\n")
    problems = check(example_copy)
    assert found(problems, f"{relative}: H 나 P 로 시작하는 후기 번호가 있다: {HIDDEN_ID}"), messages(problems)


@pytest.mark.parametrize("encoding", ["cp949", "utf-16", "utf-16-le", "utf-16-be"])
def test_private_review_id_is_found_in_other_encodings(example_copy, encoding):
    write(example_copy, "notes.csv", f"가족,{HIDDEN_ID}\n".encode(encoding))
    problems = check(example_copy)
    assert found(problems, f"notes.csv: H 나 P 로 시작하는 후기 번호가 있다: {HIDDEN_ID}"), messages(problems)
    assert found(problems, "notes.csv: UTF-8 이 아니다"), messages(problems)


def test_big_data_file_is_still_read_and_is_reported(example_copy):
    write(example_copy, "docs/big.json", '"' + " " * 5_100_000 + HIDDEN_ID + '"')
    problems = check(example_copy)
    assert found(problems, "docs/big.json: 데이터 파일이 5MB 를 넘는다"), messages(problems)
    assert found(problems, f"docs/big.json: H 나 P 로 시작하는 후기 번호가 있다: {HIDDEN_ID}"), messages(problems)


@pytest.mark.parametrize("name", ["sales.xlsx", "backup.zip", "frame.parquet"])
def test_file_that_cannot_be_inspected_is_rejected(example_copy, name):
    write(example_copy, f"docs/{name}", b"PK\x03\x04")
    problems = check(example_copy)
    assert found(problems, f"docs/{name}: 안을 검사할 수 없는 형식이다"), messages(problems)


def test_only_the_top_private_folder_is_skipped(example_copy):
    # 맨 위의 private/ 는 깃이 무시한다. 안에 무엇이 있어도 보지 않는다.
    write(example_copy, "private/evidence/holdout/geumryong.csv", f"review_id\n{HIDDEN_ID}\n")
    write(example_copy, "private/runs/x/run.json", '{"data_mode": "private"}\n')
    assert [str(p) for p in check(example_copy, strict=True)] == []
    # 더 깊은 곳의 private/ 는 깃이 무시하지 않는다. 그대로 올라가므로 본다.
    write(example_copy, "data/private/geumryong.csv", f"review_id\n{HIDDEN_ID}\n")
    problems = check(example_copy)
    assert found(problems, "data/private: 깃이 무시하는 것은 저장소 맨 위의 private/ 뿐이다"), messages(problems)
    assert found(problems, f"data/private/geumryong.csv: H 나 P 로 시작하는 후기 번호가 있다: {HIDDEN_ID}")


def test_guide_file_of_private_folder_is_checked(example_copy):
    write(example_copy, "private/README.md", f"예: {HIDDEN_ID}\n")
    problems = check(example_copy)
    assert found(problems, "private/README.md: H 나 P 로 시작하는 후기 번호가 있다"), messages(problems)


def test_private_run_is_found_whatever_it_is_called(example_copy):
    target = example_copy / "app" / "cache" / "last"
    shutil.copytree(example_copy / RUNS / BASELINE_RUN, target)
    edit_json(example_copy, Path("app/cache/last/run.json"), lambda d: d.update(data_mode="private"))
    (target / "run.json").rename(target / "record.json")
    (target / "ledger.csv").rename(target / "rows.csv")
    (target / "calibration.json").rename(target / "compare.json")
    problems = check(example_copy)
    where = "app/cache/last"
    assert found(problems, f"{where}/record.json: 기본 데이터로 돌린 실행 기록이 들어 있다"), messages(problems)
    assert found(problems, f"{where}/record.json: '실행 기록'의 모양인데 둘 수 없는 자리에 있다"), messages(problems)
    assert found(problems, f"{where}/rows.csv: '소비 원장'의 모양인데 둘 수 없는 자리에 있다"), messages(problems)
    assert found(problems, f"{where}/compare.json: '보정의 대조 결과'의 모양인데 둘 수 없는 자리에 있다")
    assert found(problems, "'저장된 LLM 응답'의 모양인데 둘 수 없는 자리에 있다"), messages(problems)


def test_run_file_names_are_reserved(example_copy):
    write(example_copy, "docs/ledger.csv", "a,b\n1,2\n")
    problems = check(example_copy)
    assert found(problems, "docs/ledger.csv: '소비 원장'의 모양인데 둘 수 없는 자리에 있다"), messages(problems)


def test_url_list_is_found_by_its_columns(example_copy):
    write(example_copy, "docs/links.csv", "venue_id,URL,source_kind\ngeumryong,https://blog.example.com/1,blog\n")
    problems = check(example_copy)
    assert found(problems, "docs/links.csv: '후기 주소 목록'의 모양이다"), messages(problems)


def test_review_labels_and_summary_have_one_place(example_copy):
    write(example_copy, "docs/labels.csv", (example_copy / REVIEWS).read_bytes())
    write(example_copy, "docs/numbers.csv", (example_copy / "data/samples/base_summary.csv").read_bytes())
    problems = check(example_copy)
    assert found(problems, "docs/labels.csv: '후기 라벨'의 모양인데 둘 수 없는 자리에 있다"), messages(problems)
    assert found(problems, "docs/numbers.csv: '기본 데이터 집계 파일'의 모양인데 둘 수 없는 자리에 있다")


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp949"])
def test_base_data_is_found_by_its_columns(example_copy, encoding):
    # 열 이름은 공개된 PRD 에 적힌 것이고, 값은 지어낸 것이다.
    content = "업장,총결제액,순매출\n예시 업장,1100,1000\n"
    write(example_copy, "docs/part.csv", content.encode(encoding))
    problems = check(example_copy)
    assert found(problems, "docs/part.csv: '기본 데이터'의 모양이다. 기본 데이터는 저장소에 올리지 않는다"), messages(problems)


def test_base_data_is_found_by_its_name(example_copy):
    write(example_copy, "docs/구매상세_요약.txt", "메모\n")
    problems = check(example_copy)
    assert found(problems, "'기본 데이터'의 모양이다"), messages(problems)


def test_review_label_cannot_hold_an_address(example_copy):
    edit_csv(example_copy, REVIEWS, lambda rows: rows[0].update(summary="자세한 것은 https://blog.example.com/1 에 있다."))
    problems = check(example_copy)
    assert found(problems, "2번째 줄 — 주소가 적혀 있다"), messages(problems)


def test_address_that_looks_like_a_review_id_is_not_one(example_copy):
    edit_json(
        example_copy,
        VENUES / "geumryong.json",
        lambda d: d["sources"][0].update(url="https://example.com/P-menu-2026"),
    )
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_review_id_after_an_address_is_still_found(example_copy):
    # 주소를 지울 때 같은 줄의 다음 칸까지 지우면 안 된다.
    write(example_copy, "docs/notes.txt", f"geumryong,https://blog.example.com/1,blog,{HIDDEN_ID},\n")
    problems = check(example_copy)
    assert found(problems, f"docs/notes.txt: H 나 P 로 시작하는 후기 번호가 있다: {HIDDEN_ID}"), messages(problems)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda persona: persona.update(base_profile={"top_venue": "geumryong"}), "기본 데이터에서 계산한 값(base_profile)이 들어 있다"),
        (lambda persona: persona.update(overridden_by_private=["budget.max"]), "비공개 층이 합쳐진 페르소나가 들어 있다"),
    ],
)
def test_sample_run_cannot_carry_private_values(example_copy, change, message):
    edit_json(example_copy, saved_response_path(example_copy), lambda d: change(d["request"]["persona"]))
    problems = check(example_copy)
    assert found(problems, message), messages(problems)


# ── 내용으로 알아보기: 표의 열 이름과 JSON 의 키 ─────────────────────────────


def copy_saved_response(root: Path) -> dict:
    return load_json(root / saved_response_path(root))


@pytest.mark.parametrize(
    ("relative", "wrap"),
    [
        ("app/demo_responses.json", lambda saved: json.dumps([saved, saved], ensure_ascii=False)),
        ("app/cache.jsonl", lambda saved: json.dumps(saved, ensure_ascii=False) + "\n"),
        ("app/bundle.json", lambda saved: json.dumps({"runs": {"a": {"responses": [saved]}}}, ensure_ascii=False)),
        ("app/lines.json", lambda saved: json.dumps(saved, ensure_ascii=False) + "\n" + json.dumps(saved) + "\n"),
    ],
)
def test_saved_response_is_found_inside_any_json_shape(example_copy, relative, wrap):
    """응답 여럿을 목록 하나에 모으거나 한 줄에 하나씩 적어도 저장된 응답이다."""
    write(example_copy, relative, wrap(copy_saved_response(example_copy)))
    problems = check(example_copy)
    assert found(problems, f"{relative}: '저장된 LLM 응답'의 모양인데 둘 수 없는 자리에 있다"), messages(problems)


def test_private_values_are_found_inside_any_json_shape(example_copy):
    saved = copy_saved_response(example_copy)
    saved["request"]["persona"]["base_profile"] = {"top_venue": "geumryong"}
    write(example_copy, "app/cache.jsonl", json.dumps(saved, ensure_ascii=False) + "\n")
    record = load_json(example_copy / RUNS / BASELINE_RUN / "run.json") | {"data_mode": "private"}
    write(example_copy, "docs/runs.json", json.dumps({"runs": [record]}, ensure_ascii=False))
    problems = check(example_copy)
    assert found(problems, "app/cache.jsonl: 기본 데이터에서 계산한 값(base_profile)이 들어 있다"), messages(problems)
    assert found(problems, "docs/runs.json: 기본 데이터로 돌린 실행 기록이 들어 있다"), messages(problems)


def test_empty_base_profile_is_not_a_private_value():
    """키만 있고 비어 있는 것은 값이 없는 것이다 (형식 문서 9절: 가상 예시로 돌릴 때는 없거나 비어 있다)."""
    for empty in ("null", "{}", "[]"):
        text = '{"persona": {"base_profile": EMPTY, "overridden_by_private": []}}'.replace("EMPTY", empty)
        assert inspect_content("x.json", ".json", text.encode()).notes == []
    filled = b'{"persona": {"base_profile": {"top_venue": "geumryong"}, "overridden_by_private": ["budget.max"]}}'
    assert inspect_content("x.json", ".json", filled).notes == [BASE_PROFILE_NOTE, PRIVATE_LAYER_NOTE]


def test_cut_down_private_run_record_is_found(example_copy):
    # 가중치 같은 큰 키를 덜어 낸 실행 기록도 JSON 이면 알아본다 (글로 찾는 검사는 다른 키가 함께 있어야 한다).
    brief = {"run_id": "20261117-101500-baseline", "data_mode": "private", "status": "ok"}
    write(example_copy, "docs/run_brief.json", json.dumps(brief))
    problems = check(example_copy)
    assert found(problems, "docs/run_brief.json: 기본 데이터로 돌린 실행 기록이 들어 있다"), messages(problems)


def test_tables_turned_into_json_are_still_tables(example_copy):
    ledger = load_csv(example_copy / LEDGER)
    urls = [{"venue_id": "geumryong", "url": "https://blog.example.com/1", "review_id": ""}]
    write(example_copy, "app/ledger_rows.json", json.dumps(ledger, ensure_ascii=False))
    write(example_copy, "app/urls.json", json.dumps(urls, ensure_ascii=False))
    problems = check(example_copy)
    assert found(problems, "app/ledger_rows.json: '소비 원장'의 모양인데 둘 수 없는 자리에 있다"), messages(problems)
    assert found(problems, "app/urls.json: '후기 주소 목록'의 모양이다"), messages(problems)


BASE_DATA_FOUND = "'기본 데이터'의 모양이다. 기본 데이터는 저장소에 올리지 않는다"


@pytest.mark.parametrize(
    ("relative", "content"),
    [
        # 열 이름은 공개된 PRD 에 적힌 것이고 값은 지어낸 것이다.
        ("app/part.csv", "업장,고객군,순매출\n예시 업장,예시 고객군,1000\n"),
        ("app/pivot.csv", "업장,순매출_sum\n예시 업장,1000\n"),
        ("app/paid.tsv", "업장\t총결제액\n예시 업장\t1100\n"),
        ("docs/export.txt", "업장\t순매출\n예시 업장\t1000\n".encode("utf-16")),
        # 맨 앞의 표시(BOM)가 없는 UTF-16 도 읽는다.
        ("docs/export_le.txt", "업장\t순매출\n예시 업장\t1000\n".encode("utf-16-le")),
        ("docs/export_be.txt", "업장\t순매출\n예시 업장\t1000\n".encode("utf-16-be")),
        ("app/base.json", json.dumps([{"업장": "예시 업장", "순매출": 1000}], ensure_ascii=False)),
        ("app/split.json", json.dumps({"columns": ["업장", "총결제액"], "data": [["예시 업장", 1100]]}, ensure_ascii=False)),
        ("app/base.jsonl", json.dumps({"업장": "예시 업장", "순매출 합": 1000}, ensure_ascii=False) + "\n"),
        ("docs/memo.md", "# 메모\n\n| 업장 | 순매출 |\n|---|---|\n| 예시 업장 | 1000 |\n"),
    ],
)
def test_piece_of_base_data_is_found(example_copy, relative, content):
    """집계하거나 일부만 떼어 내면 금액 열이 하나만 남는다. 그것도, 표가 아닌 모양으로 바꾼 것도 기본 데이터다."""
    write(example_copy, relative, content)
    problems = check(example_copy)
    assert found(problems, f"{relative}: {BASE_DATA_FOUND}"), messages(problems)


@pytest.mark.parametrize(
    ("relative", "content"),
    [
        # 기본 데이터의 열을 글로 설명하는 것, 코드에서 그 이름을 쓰는 것은 기본 데이터가 아니다.
        (
            "docs/memo.md",
            "매출은 세금을 뺀 금액(기본 데이터의 `순매출`)으로 센다.\n\n"
            "| 열 | 뜻 |\n|---|---|\n| 순매출 | 세금을 뺀 매출 |\n| 총결제액 | 고객이 낸 금액 |\n",
        ),
        # 글 파일의 첫 줄이 한 칸이면 표가 아니라 글의 첫 문장이다.
        ("docs/memo.txt", "총결제액 기준으로 본 메모\n\n둘째 줄\n"),
        ("app/charts.py", 'LABELS = {"revenue_net": "순매출", "paid": "총결제액"}\n'),
        ("app/labels.json", json.dumps({"labels": ["순매출", "총결제액"]}, ensure_ascii=False)),
        # 문서의 표는 머리글이 그 이름과 똑같을 때만 본다. 지어낸 결과를 보여 주는 표의 머리글까지 막지 않는다.
        ("docs/result.md", "| 업장 | 가상 순매출(원) |\n|---|---|\n| 예시 업장 | 1000 |\n"),
    ],
)
def test_talking_about_base_data_columns_is_allowed(example_copy, relative, content):
    write(example_copy, relative, content)
    assert [str(p) for p in check(example_copy, strict=True)] == []


@pytest.mark.parametrize(
    ("relative", "content"),
    [
        # 주소 열만 있는 표는 후기 주소 목록이 아니다 (공식 메뉴의 출처 목록 같은 것).
        ("tools/venue_sources.csv", "venue_id,title,url\ngeumryong,메뉴 안내,https://example.com/menu\n"),
        # 흔한 낱말의 키 몇 개만으로는 실행 결과로 보지 않는다.
        ("app/filters.json", '{"criteria": [], "groups": []}\n'),
        ("app/settings.json", '{"min_reviews": 5, "venues": ["geumryong"]}\n'),
        # 엔진 코드와 안내 문서는 실행 기록의 값을 설명할 수 있다.
        ("engine/runner.py", 'DEFAULTS = {"data_mode": "private"}\n'),
        ("engine/README.md", '기본 데이터로 돌리면 실행 기록에 `"data_mode": "private"` 가 적힌다.\n'),
        # 빈 폴더를 깃에 남길 때 쓰는 파일.
        ("engine/samples/runs/.gitkeep", ""),
        ("data/venues/.gitkeep", ""),
        # 화면 코드, 그림, 발표 자료.
        ("app/pages/compare.py", "import streamlit as st\n"),
        ("app/assets/logo.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"),
        ("slides/deck.pptx", b"PK\x03\x04"),
        ("slides/deck.pdf", b"%PDF-1.7\n"),
    ],
)
def test_ordinary_files_are_not_stopped(example_copy, relative, content):
    """팀원이 평소에 만드는 파일을 검사가 막지 않는다."""
    write(example_copy, relative, content)
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_url_list_with_other_column_names_is_found(example_copy):
    write(example_copy, "docs/list.csv", "업장,링크,review_id\n금룡,https://blog.example.com/1,\n")
    problems = check(example_copy)
    assert found(problems, "docs/list.csv: '후기 주소 목록'의 모양이다"), messages(problems)


def test_run_record_pasted_into_a_document_is_found(example_copy):
    record = load_json(example_copy / RUNS / BASELINE_RUN / "run.json") | {"data_mode": "private"}
    write(example_copy, "docs/notes.md", "# 결과\n\n```json\n" + json.dumps(record, ensure_ascii=False, indent=2) + "\n```\n")
    problems = check(example_copy)
    assert found(problems, "docs/notes.md: 기본 데이터로 돌린 실행 기록이 들어 있다"), messages(problems)


def test_misplaced_file_is_told_where_test_examples_go(example_copy):
    write(example_copy, "tests/app/ledger_sample.csv", (example_copy / LEDGER).read_bytes())
    problems = check(example_copy)
    assert found(problems, "tests/app/ledger_sample.csv: '소비 원장'의 모양인데 둘 수 없는 자리에 있다"), messages(problems)
    assert found(problems, "테스트에 쓸 예시는 tests/fixtures/<이름>/ 아래에"), messages(problems)


@pytest.mark.parametrize(
    "url",
    ["https://map.example.com/검색/P-course-2024", "https://example.com/wiki/Menu_(P-course-2024)"],
)
def test_address_with_korean_or_brackets_is_still_an_address(example_copy, url):
    edit_json(example_copy, VENUES / "geumryong.json", lambda d: d["sources"][0].update(url=url))
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_word_that_only_looks_like_an_id_is_not_one(example_copy):
    # 업장 식별자는 글자로 시작하고 세 글자 이상이다. 그보다 짧은 것은 후기 번호가 아니다.
    write(example_copy, "docs/notes.md", "- UI-fix-1234 와 H-a-2026, P-1-0001 은 후기 번호가 아니다.\n")
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_venue_id_is_long_enough_to_be_recognised(example_copy):
    path = example_copy / VENUES / "examplehotel-buffet.json"
    data = load_json(path) | {"venue_id": "eb"}
    path.unlink()
    save_json(example_copy / VENUES / "eb.json", data)
    problems = check(example_copy)
    assert found(problems, "data/venues/eb.json: venue_id 'eb' 는 영어 글자로 시작하고 세 글자 이상이어야 한다"), messages(problems)


def test_data_in_a_holdout_folder_is_rejected(example_copy):
    # 번호도 주소도 없이 옮겨 적은 후기는 내용으로 알아볼 수 없다. 폴더 이름으로 본다.
    write(example_copy, "app/holdout/geumryong.csv", "venue_id,text\ngeumryong,좋았다\n")
    write(example_copy, "engine/holdout/split.py", "def split(urls):\n    return urls\n")
    problems = check(example_copy)
    assert found(problems, "app/holdout/geumryong.csv: holdout 이라는 폴더에 데이터 파일이 있다"), messages(problems)
    assert not found(problems, "engine/holdout/split.py"), messages(problems)


def test_only_test_code_may_show_private_ids(example_copy):
    write(example_copy, "tests/test_something.py", f'BAD = "{HIDDEN_ID}"\n')
    assert [str(p) for p in check(example_copy, strict=True)] == []
    # 테스트 폴더라도 코드가 아닌 파일은 본다 (예시 데이터에 진짜 번호가 섞일 수 있다).
    write(example_copy, "tests/notes.txt", f"{HIDDEN_ID}\n")
    write(example_copy, "tests/fixtures/other/data/evidence/reviews/geumryong.csv", f"review_id\n{HIDDEN_ID}\n")
    problems = check(example_copy)
    assert found(problems, f"tests/notes.txt: H 나 P 로 시작하는 후기 번호가 있다: {HIDDEN_ID}"), messages(problems)
    assert found(problems, "tests/fixtures/other/data/evidence/reviews/geumryong.csv: H 나 P 로 시작하는 후기 번호가 있다")


def test_folder_named_for_holdout_or_reference_is_rejected(example_copy):
    write(example_copy, "docs/evidence/holdout/list.txt", "메모\n")
    write(example_copy, "app/evidence/reference/list.txt", "메모\n")
    problems = check(example_copy)
    for relative in ("docs/evidence/holdout/list.txt", "app/evidence/reference/list.txt"):
        assert found(problems, f"{relative}: 떼어 둔 후기와 받은 참고 소스의 후기는 저장소에 올리지 않는다"), messages(problems)


def test_file_too_big_to_read_is_reported(example_copy, monkeypatch):
    monkeypatch.setattr(check_formats, "MAX_SCAN_BYTES", 2_000)
    write(example_copy, "docs/huge.bin", b"x" * 2_001)
    write(example_copy, "docs/small.bin", b"x" * 2_000)
    problems = check(example_copy)
    assert found(problems, "docs/huge.bin: 100MB 를 넘어 검사하지 못했다"), messages(problems)
    assert not found(problems, "docs/small.bin"), messages(problems)


def test_private_folder_must_be_lower_case(example_copy):
    write(example_copy, "Private/base/summary.csv", "a,b\n1,2\n")
    problems = check(example_copy)
    assert found(problems, "Private: 내부 자료의 폴더 이름은 소문자 private 이다"), messages(problems)


# ── 테스트의 예시 묶음도 저장소와 같은 검사를 받는다 ─────────────────────────


def test_other_example_sets_get_the_same_checks(example_copy):
    other = example_copy / "tests" / "fixtures" / "other"
    shutil.copytree(example_copy / RUNS / BASELINE_RUN, other / RUNS / BASELINE_RUN)
    (other / RUNS / BASELINE_RUN / "run.json").unlink()
    problems = check(example_copy)
    where = f"tests/fixtures/other/engine/samples/runs/{BASELINE_RUN}"
    # 자리는 맞지만(예시 묶음 안에서는 그 안의 경로로 본다), 실행 기록이 없어 가상 예시로 돌린 것인지 알 수 없다.
    assert found(problems, f"{where}: 실행 기록 run.json 이 없다"), messages(problems)
    assert not found(problems, "둘 수 없는 자리에 있다"), messages(problems)


def test_whole_example_set_can_be_copied_as_another_set(example_copy):
    other = example_copy / "tests" / "fixtures" / "other"
    for name in ("data", "personas", "scenarios", "engine"):
        shutil.copytree(example_copy / name, other / name)
    assert [str(p) for p in check(example_copy, strict=True)] == []
    edit_json(other, VENUES / "geumryong.json", lambda d: d["products"][0].update(qty_rule="per_table"))
    problems = check(example_copy)
    assert found(problems, "tests/fixtures/other/data/venues/geumryong.json: products[0].qty_rule — 쓸 수 없는 값"), messages(problems)


def test_checker_skips_exactly_what_git_ignores():
    """검사가 건너뛰는 것은 깃이 무시하는 것과 같아야 한다.

    깃이 무시하지 않는 것을 검사가 건너뛰면, 올라가는 파일인데 검사하지 않는 구멍이 된다.
    .gitignore 를 고쳤으면 tools/check_formats.py 의 `ignored_by_git` 과 이 테스트를 함께 고친다.
    """
    lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    patterns = {line.strip() for line in lines if line.strip() and not line.startswith("#")}
    plain_dirs = {p for p in patterns if p.endswith("/") and "*" not in p}
    assert {p.rstrip("/") for p in plain_dirs} | {".git"} == set(IGNORED_DIR_NAMES)
    assert patterns - plain_dirs == {
        ".env",
        ".env.*",
        "!.env.example",
        "private/*",
        "!private/README.md",
        ".DS_Store",
        "Thumbs.db",
        "desktop.ini",
        ".claude/settings.local.json",
        "*.pyc",
        "*.egg-info/",
        "*.log",
    }

    ignored = [
        ((".env",), False),
        (("app", ".env.local"), False),
        (("private", "base", "summary.csv"), False),
        (("private", "runs"), True),
        (("docs", "Thumbs.db"), False),
        ((".claude", "settings.local.json"), False),
        (("engine", "formats", "io.pyc"), False),
        (("walkerhill_dining_sim.egg-info",), True),
        (("run.log",), False),
        (("app", "__pycache__"), True),
    ]
    kept = [
        ((".env.example",), False),
        (("private",), True),
        (("private", "README.md"), False),
        (("data", "private"), True),
        (("data", "private", "summary.csv"), False),
        (("app", ".claude", "settings.local.json"), False),
        (("node_modules",), True),
    ]
    for parts, is_dir in ignored:
        assert ignored_by_git(parts, is_dir), parts
    for parts, is_dir in kept:
        assert not ignored_by_git(parts, is_dir), parts


def test_checker_walks_exactly_the_files_git_can_upload():
    """검사가 훑는 파일이, 깃이 올릴 수 있다고 보는 파일과 같다. 이 저장소에서 깃에 직접 물어 견준다.

    깃이 보는 파일은 이미 올라간 파일과, 아직 안 올렸지만 무시되지 않는 파일이다.
    PC 마다 따로 둔 무시 목록(core.excludesFile)은 빼고 본다. 저장소의 .gitignore 만으로 견주려는 것이다.
    """
    git = shutil.which("git")
    if git is None or not (REPO_ROOT / ".git").exists():
        pytest.skip("깃이 없거나 깃 저장소가 아니다")
    # 윈도우의 깃은 대소문자를 가리지 않고 무시한다. 자동 검사가 도는 리눅스처럼 가리게 해서 견준다.
    settings = ["-c", "core.quotepath=false", "-c", "core.excludesFile=", "-c", "core.ignorecase=false"]
    command = [git, *settings, "ls-files", "-z"]
    result = subprocess.run(
        [*command, "--cached", "--others", "--exclude-standard"], cwd=REPO_ROOT, capture_output=True, check=False
    )
    if result.returncode != 0:
        pytest.skip(f"깃이 파일 목록을 주지 않았다: {result.stderr.decode('utf-8', errors='replace').strip()}")
    listed = [REPO_ROOT / name for name in result.stdout.decode("utf-8").split("\0") if name]
    from_git = {p.relative_to(REPO_ROOT).as_posix() for p in listed if p.is_file() and not p.is_symlink()}
    walked = {p.relative_to(REPO_ROOT).as_posix() for p in Checker(REPO_ROOT)._walk(REPO_ROOT)}
    assert walked - from_git == set(), "깃이 무시하는데 검사가 훑는 파일"
    assert from_git - walked == set(), "깃이 올릴 수 있는데 검사가 건너뛰는 파일"


# ── 원장은 저장된 응답과 실행 기록에서 나온 것이어야 한다 ────────────────────


def test_ledger_must_match_the_saved_response(example_copy):
    # 줄 하나만 보면 계산이 맞는다. 그러나 저장된 응답이 고른 것은 코스 A 다.
    change = {"product_id": "course-b", "list_price": "200000", "paid": "800000"}
    change |= {"revenue_net": "727273", "weighted_revenue": "87272760"}
    edit_csv(example_copy, LEDGER, lambda rows: rows[0].update(change))
    problems = check(example_copy)
    assert found(problems, "원장의 줄이 저장된 응답에서 고른 주문과 다르다"), messages(problems)
    assert not found(problems, "paid 가"), messages(problems)


def test_ledger_reason_must_match_the_saved_response(example_copy):
    edit_csv(example_copy, LEDGER, lambda rows: rows[0].update(reason_labels="맛"))
    problems = check(example_copy)
    assert found(problems, "고른 이유(reason_labels, reason_text, used_attributes)가 저장된 응답과 다르다"), messages(problems)


def test_ledger_row_must_belong_to_the_saved_request(example_copy):
    edit_csv(
        example_copy,
        LEDGER,
        lambda rows: rows[0].update(persona_id="family-kids", visit_id="family-kids__meal-dinner-weekend"),
    )
    problems = check(example_copy)
    assert found(problems, "저장된 응답의 요청은 다른 페르소나의 것이다"), messages(problems)


def test_ledger_cannot_show_a_choice_the_response_did_not_make(example_copy):
    def choose_none(data):
        data["response"]["choice"] = {"venue_id": None, "option_id": None, "addons": []}
        data["response"]["reason_labels"] = ["가격"]
        data["response"]["rejected"] = [
            {"venue_id": venue_id, "pain_labels": ["가격"], "text": "비싸다."}
            for venue_id in ("geumryong", "examplehotel-chinese")
        ]

    edit_json(example_copy, saved_response_path(example_copy), choose_none)
    problems = check(example_copy)
    assert found(problems, "저장된 응답은 '이용하지 않음'인데 원장에는 업장을 고른 줄이 있다"), messages(problems)


def test_ledger_rows_for_added_products_are_matched_too(example_copy):
    """추가 상품(고객이 수량을 정하는 상품)을 고른 방문은 원장에 그 줄이 따로 있어야 한다."""
    tea = {"product_id": "tea", "name": "차", "occasion": "meal"}
    tea |= {"slots": [{"meal": "lunch", "day_type": "all"}, {"meal": "dinner", "day_type": "all"}]}
    tea |= {"months": None, "audience": "all", "unit": "잔", "serves": 1}
    tea |= {"qty_rule": "choice", "qty_max": 4, "price": 8000, "price_basis": "included"}
    tea |= {"grade": "official", "source_id": None}
    edit_json(example_copy, VENUES / "geumryong.json", lambda d: d["products"].append(tea))

    # 요청에 추가 상품을 넣으면 해시가 달라진다. 파일 이름과 원장의 해시를 새 값으로 맞춘다.
    old = example_copy / saved_response_path(example_copy)
    saved = load_json(old)
    saved["request"]["candidates"][0]["addons"] = [
        {"product_id": "tea", "name": "차", "unit": "잔", "unit_price": 8000, "qty_max": 4}
    ]
    saved["response"]["choice"]["addons"] = [{"product_id": "tea", "quantity": 2}]
    saved["request_hash"] = compute_request_hash(saved["provider"], saved["model"], saved["request"])
    old.unlink()
    save_json(old.with_name(f"{saved['request_hash']}.json"), saved)

    rows = load_csv(example_copy / LEDGER)
    rows[0]["request_hash"] = saved["request_hash"]
    added = {**rows[0], "product_id": "tea", "quantity": "2", "unit": "잔", "list_price": "8000"}
    added |= {"discount": "0", "paid": "16000", "revenue_net": "14545", "weighted_revenue": "1745400"}
    save_csv(example_copy / LEDGER, [rows[0], added])
    assert [str(p) for p in check(example_copy, strict=True)] == []

    # 수량이 응답과 다르면 잡는다.
    wrong = {**added, "quantity": "3", "paid": "24000", "revenue_net": "21818", "weighted_revenue": "2618160"}
    save_csv(example_copy / LEDGER, [rows[0], wrong])
    assert found(check(example_copy), "원장의 줄이 저장된 응답에서 고른 주문과 다르다")

    # 추가 상품의 줄이 빠져도 잡는다.
    save_csv(example_copy / LEDGER, [rows[0]])
    assert found(check(example_copy), "원장의 줄이 저장된 응답에서 고른 주문과 다르다")


def test_represented_must_match_the_weights(example_copy):
    edit_csv(example_copy, LEDGER, lambda rows: rows[0].update(represented="999.0", weighted_revenue="544909545"))
    problems = check(example_copy)
    assert found(problems, "represented 가 실행 기록의 페르소나 가중치 × 묶음 비율과 다르다"), messages(problems)


def test_visit_entered_by_hand_needs_no_weights(example_copy):
    """화면에서 조건을 직접 넣어 한 번 돌린 방문(manual-)에는 가중치가 없다. 그런 실행도 통과해야 한다."""
    shutil.rmtree(example_copy / RUNS / COMPETITOR_RUN)  # 기준 실행의 가중치를 따르는 실행은 이 시험과 상관없어 뺀다

    def to_manual(data):
        data["condition_ids"] = ["manual-1"]
        data["weights"].update(group_multiplier={}, persona_weight={}, condition_ratio={})
        data["weights"]["grades"]["condition_ratio"] = {}

    edit_json(example_copy, RUNS / BASELINE_RUN / "run.json", to_manual)

    # 요청의 조건을 바꾸면 해시가 달라진다. 파일 이름과 원장의 해시를 새 값으로 맞춘다.
    old = example_copy / saved_response_path(example_copy)
    saved = load_json(old)
    saved["request"]["condition"]["condition_id"] = "manual-1"
    saved["request_hash"] = compute_request_hash(saved["provider"], saved["model"], saved["request"])
    old.unlink()
    save_json(old.with_name(f"{saved['request_hash']}.json"), saved)

    change = {"condition_id": "manual-1", "visit_id": "family-elders__manual-1", "request_hash": saved["request_hash"]}
    change |= {"represented": "1.0", "weighted_revenue": "545455"}
    edit_csv(example_copy, LEDGER, lambda rows: rows[0].update(change))
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_unreadable_row_is_reported_once(example_copy):
    # 줄 하나를 읽지 못하면 그 줄의 오류만 적는다. 같은 원인에서 나오는 "방문 수가 다르다"를 겹쳐 적지 않는다.
    edit_csv(example_copy, LEDGER, lambda rows: rows[0].update(paid="590000"))
    problems = check(example_copy)
    assert found(problems, "paid 가 수량 × 표시가 − 할인과 다르다"), messages(problems)
    assert not found(problems, "원장의 방문이"), messages(problems)
    assert not found(problems, "빠진 방문"), messages(problems)


def test_represented_cannot_go_unchecked(example_copy):
    # 가중치를 지우면 represented 를 견줄 값이 없다. 조용히 넘어가지 않고 오류로 적는다.
    edit_json(example_copy, RUNS / BASELINE_RUN / "run.json", lambda d: d["weights"].update(persona_weight={}))
    problems = check(example_copy)
    assert found(problems, "weights.persona_weight 에 페르소나 'family-elders' 의 가중치가 없다"), messages(problems)
    assert found(problems, "represented 를 확인할 수 없다"), messages(problems)


def test_weights_come_from_the_baseline_run(example_copy):
    edit_json(
        example_copy,
        RUNS / COMPETITOR_RUN / "run.json",
        lambda d: d["weights"]["persona_weight"].update({"family-elders": 60.0}),
    )
    problems = check(example_copy)
    assert found(problems, "weights 가 weights_from 의 실행과 다르다"), messages(problems)


def test_saved_response_must_reject_every_other_candidate(example_copy):
    edit_json(example_copy, saved_response_path(example_copy), lambda d: d["response"].update(rejected=[]))
    problems = check(example_copy)
    assert found(problems, "응답 — 고르지 않은 후보 'examplehotel-chinese' 가 rejected 에 없다"), messages(problems)


def test_saved_response_is_read_as_written(example_copy):
    edit_json(example_copy, saved_response_path(example_copy), lambda d: d["usage"].update(input_tokens="10"))
    problems = check(example_copy)
    assert found(problems, "usage.input_tokens — '10' 는 글자다. 숫자는 따옴표 없이 적는다"), messages(problems)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(provider="other"), "provider 나 model 이 실행 기록과 다르다"),
        (lambda d: d["request"].update(scenario_id="geumryong-course-price-up"), "요청의 scenario_id 가 실행 기록과 다르다"),
    ],
)
def test_saved_response_belongs_to_its_run(example_copy, change, message):
    edit_json(example_copy, saved_response_path(example_copy), change)
    problems = check(example_copy)
    assert found(problems, message), messages(problems)


def test_ledger_condition_must_be_the_one_in_the_saved_request(example_copy):
    change = {"condition_id": "meal-lunch-weekend", "visit_id": "family-elders__meal-lunch-weekend"}
    edit_csv(example_copy, LEDGER, lambda rows: rows[0].update(change))
    problems = check(example_copy)
    assert found(problems, "저장된 응답의 요청은 다른 조건의 것이다"), messages(problems)


def test_ledger_venue_must_be_the_one_the_response_chose(example_copy):
    # 줄 하나만 보면 경쟁 업장을 고른 줄로 계산이 맞다. 그러나 저장된 응답이 고른 곳은 금룡이다.
    change = {"choice_kind": "competitor", "venue_id": "examplehotel-chinese", "product_id": "course"}
    change |= {"list_price": "140000", "paid": "560000", "revenue_net": "0", "weighted_revenue": "0"}
    edit_csv(example_copy, LEDGER, lambda rows: rows[0].update(change))
    problems = check(example_copy)
    assert found(problems, "원장의 업장이 저장된 응답에서 고른 업장과 다르다"), messages(problems)
    assert not found(problems, "번째 줄 —"), messages(problems)  # 줄 하나의 검사에는 걸리지 않는다


def test_row_that_chose_a_venue_needs_a_saved_response(example_copy):
    # 해시를 비우면 저장된 응답과 견줄 수 없다. 그런 줄은 어디서 나왔는지 확인할 수 없으므로 받지 않는다.
    change = {"request_hash": "", "llm_call": "", "product_id": "course-b", "list_price": "200000"}
    change |= {"paid": "800000", "revenue_net": "727273", "weighted_revenue": "87272760", "reason_labels": "맛"}
    edit_csv(example_copy, LEDGER, lambda rows: rows[0].update(change))
    problems = check(example_copy)
    assert found(problems, "업장을 고른 줄에는 request_hash 가 있어야 한다"), messages(problems)


FAILED_ROW = {"choice_kind": "none", "venue_id": "", "product_id": "", "quantity": "0", "unit": "", "list_price": "0"}
FAILED_ROW |= {"discount": "0", "paid": "0", "revenue_net": "0", "weighted_revenue": "0", "reason_labels": ""}
FAILED_ROW |= {"reason_text": "", "used_attributes": "", "status": "failed", "fail_reason": "응답이 후보 밖의 업장을 골랐다"}


def test_failed_visit_is_one_row_without_amounts(example_copy):
    run_json = RUNS / BASELINE_RUN / "run.json"
    edit_json(example_copy, run_json, lambda d: d.update(counts={"visits": 1, "failed": 1}))
    original = load_csv(example_copy / LEDGER)[0]
    save_csv(example_copy / LEDGER, [original | FAILED_ROW])
    assert [str(p) for p in check(example_copy, strict=True)] == []

    # 실패한 줄의 금액은 합계에 들어가면 안 된다.
    save_csv(example_copy / LEDGER, [original | FAILED_ROW | {"weighted_revenue": "99999999999"}])
    assert found(check(example_copy), "실패한 줄의 수량과 금액은 모두 0 이다")

    # 실패한 줄을 끼워 넣어 다른 줄의 검사를 건너뛰게 할 수 없다.
    edit_json(example_copy, run_json, lambda d: d.update(counts={"visits": 1, "failed": 1}))
    save_csv(example_copy / LEDGER, [original | {"reason_labels": "맛"}, original | FAILED_ROW])
    assert found(check(example_copy), "한 방문에 ok 인 줄과 failed 인 줄이 섞여 있다")

    save_csv(example_copy / LEDGER, [original | FAILED_ROW, original | FAILED_ROW])
    assert found(check(example_copy), "실패한 방문은 줄 하나로만 남긴다")


def test_ledger_visits_must_match_the_run_record(example_copy):
    run_json = RUNS / BASELINE_RUN / "run.json"
    edit_json(example_copy, run_json, lambda d: d.update(counts={"visits": 2, "failed": 0}))
    problems = check(example_copy)
    assert found(problems, "원장의 방문이 1건인데 실행 기록의 counts.visits 는 2 다"), messages(problems)

    edit_json(example_copy, run_json, lambda d: d.update(counts={"visits": 1, "failed": 1}))
    problems = check(example_copy)
    assert found(problems, "원장의 실패한 방문이 0건인데 실행 기록의 counts.failed 는 1 다"), messages(problems)


def test_finished_run_has_every_planned_visit(example_copy):
    def add_condition(data):
        data["condition_ids"].append("meal-lunch-weekend")
        data["weights"]["condition_ratio"]["가족·친족"]["meal-lunch-weekend"] = 0.0
        data["weights"]["grades"]["condition_ratio"]["가족·친족"]["meal-lunch-weekend"] = "assumption"

    edit_json(example_copy, RUNS / BASELINE_RUN / "run.json", add_condition)
    problems = check(example_copy)
    assert found(problems, "페르소나 × 조건마다 방문이 하나씩 있어야 한다: 빠진 방문 1건, 실행 기록에 없는 방문 0건"), messages(problems)


def season_rows(root: Path, share: str, gap: dict | None) -> list[dict]:
    """일부 달에만 파는 곳을 고른 방문의 줄들. 고른 줄의 몫을 `share` 로 하고, `gap` 이 있으면 보탬 줄을 더한다."""
    chosen = load_csv(root / LEDGER)[0]
    chosen |= {"counted_share": share, "weighted_revenue": str(round(545455 * 120 * float(share)))}
    if gap is None:
        return [chosen]
    rest = chosen | {"choice_kind": "none", "venue_id": "", "product_id": "", "quantity": "0", "unit": ""}
    rest |= {"list_price": "0", "discount": "0", "paid": "0", "revenue_net": "0", "weighted_revenue": "0"}
    rest |= {"reason_labels": "", "used_attributes": "", "counted_share": "0.75", "reason_text": "파는 달이 아님"}
    return [chosen, rest | gap]


def test_seasonal_choice_counts_the_rest_as_not_using(example_copy):
    """석 달만 파는 곳을 고르면 몫이 0.25 이고, 나머지 0.75 는 '이용하지 않음' 줄 하나로 남는다 (10.2절)."""
    save_csv(example_copy / LEDGER, season_rows(example_copy, "0.25", {}))
    assert [str(p) for p in check(example_copy, strict=True)] == []

    missing = "일부 달에만 파는 곳을 고른 방문에는 '이용하지 않음' 줄이 하나 더 있어야 한다"
    for rows in (
        season_rows(example_copy, "0.25", None),  # 보탬 줄이 없다
        season_rows(example_copy, "0.25", {"counted_share": "0.9"}),  # 몫을 더해 1 이 아니다
        season_rows(example_copy, "0.25", {"reason_text": "그냥"}),  # 이유가 약속한 문장이 아니다
    ):
        save_csv(example_copy / LEDGER, rows)
        problems = check(example_copy)
        assert found(problems, missing), messages(problems)

    # 일 년 내내 파는 곳을 골랐는데 '이용하지 않음' 줄을 더해 방문을 두 번 세면 안 된다.
    save_csv(example_copy / LEDGER, season_rows(example_copy, "1.0", {"counted_share": "0.9"}))
    problems = check(example_copy)
    assert found(problems, "일 년 내내 파는 곳을 고른 방문인데 '이용하지 않음' 줄이 더 있다"), messages(problems)


def test_rows_of_one_visit_must_agree(example_copy):
    """한 방문의 줄들은 같은 응답에서 나온 것이고, 몫을 더하면 1 이다."""
    chosen = load_csv(example_copy / LEDGER)[0]

    # 같은 방문인데 줄마다 다른 응답을 가리킨다.
    save_csv(example_copy / LEDGER, season_rows(example_copy, "0.25", {"request_hash": "0" * 16}))
    problems = check(example_copy)
    assert found(problems, "같은 방문의 줄인데 request_hash 가 서로 다르다"), messages(problems)

    # 고른 줄들의 몫이 서로 다르다.
    half = chosen | {"counted_share": "0.5", "weighted_revenue": str(round(545455 * 120 * 0.5))}
    save_csv(example_copy / LEDGER, [chosen, half])
    problems = check(example_copy)
    assert found(problems, "한 방문에서 고른 줄들의 counted_share 가 서로 다르다"), messages(problems)

    # "이용하지 않음"뿐인 방문인데 몫이 1 이 아니다.
    save_csv(example_copy / LEDGER, season_rows(example_copy, "0.25", {})[1:])
    problems = check(example_copy)
    assert found(problems, "'이용하지 않음'인 방문은 counted_share 가 1 인 줄 하나다"), messages(problems)


def test_sample_run_cannot_claim_internal_grade(example_copy):
    edit_json(
        example_copy,
        RUNS / BASELINE_RUN / "run.json",
        lambda d: d["weights"]["grades"].update(group_multiplier="internal"),
    )
    problems = check(example_copy)
    assert found(problems, "가중치의 등급에 내부 매출 자료(internal)가 있다"), messages(problems)


def test_number_must_be_finite(example_copy):
    path = example_copy / "scenarios" / "geumryong-course-price-up.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"pct": 10', '"pct": Infinity'), encoding="utf-8")
    problems = check(example_copy)
    assert found(problems, "changes[0].change_price_pct.pct —"), messages(problems)
    assert found(problems, "끝이 있는 수가 아니다"), messages(problems)
