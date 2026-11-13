"""형식 약속에 딸린 규칙을 본다: 금액, 두 층을 합치는 법, 응답을 다시 검사하는 법."""

import copy
import json

import pytest
from conftest import BASELINE_RUN, EXAMPLE_ROOT, load_csv, load_json
from pydantic import ValidationError

from engine.formats import (
    ChoiceRequest,
    ChoiceResponse,
    ConditionBundle,
    LedgerRow,
    Persona,
    Slot,
    SummaryRow,
    Venue,
    apply_pct,
    change_price,
    merge_persona_layers,
    merged_persona,
    net_of_tax,
    problems_in_response,
    read_model,
    round_half_up,
    to_paid_price,
)

# ── 금액 (docs/FORMATS.md 2절) ──────────────────────────────────────────────


@pytest.mark.parametrize(("value", "expected"), [(0.5, 1), (1.5, 2), (2.5, 3), (2.4, 2), (545454.5, 545455)])
def test_half_is_rounded_up(value, expected):
    assert round_half_up(value) == expected


def test_net_of_tax_divides_by_one_point_one():
    assert net_of_tax(600000) == 545455
    assert net_of_tax(110000) == 100000
    assert net_of_tax(0) == 0


def test_price_shown_without_tax_is_multiplied():
    # 부가세만 따로면 1.1, 봉사료와 부가세가 모두 따로면 1.1 × 1.1 = 1.21 을 곱한다.
    assert to_paid_price(100000, "excluded_vat") == 110000
    assert to_paid_price(100000, "excluded_vat_service") == 121000
    assert to_paid_price(100000, "included") == 100000
    assert to_paid_price(100000, "unknown") == 100000
    # 곱한 뒤 한 번만 반올림한다: 12,345 × 1.21 = 14,937.45
    assert to_paid_price(12345, "excluded_vat_service") == 14937
    assert to_paid_price(5, "excluded_vat") == 6
    # 바뀌기 전의 코드 값이나 모르는 값은 조용히 넘기지 않는다.
    with pytest.raises(ValueError, match="모르는 가격 표기"):
        to_paid_price(100000, "excluded")


def test_slot_says_when_a_product_is_sold():
    product = Venue.model_validate(load_json(EXAMPLE_ROOT / "data" / "venues" / "geumryong.json")).products[0]
    mixed = product.model_copy(update={"slots": [Slot(meal="lunch", day_type="weekend"), Slot(meal="dinner", day_type="all")]})
    assert mixed.sold_at("lunch", "weekend") and mixed.sold_at("dinner", "weekday") and mixed.sold_at("dinner", "weekend")
    assert not mixed.sold_at("lunch", "weekday")
    assert not mixed.sold_at(None, "weekend")
    assert mixed.sold_on("weekday") and mixed.sold_on("weekend")
    lunch_only = product.model_copy(update={"slots": [Slot(meal="lunch", day_type="weekday")]})
    assert lunch_only.sold_on("weekday") and not lunch_only.sold_on("weekend")


def test_summary_unit_price_is_what_the_customer_paid():
    row = SummaryRow.from_row(load_csv(EXAMPLE_ROOT / "data" / "samples" / "base_summary.csv")[0])
    # 낸 금액 ÷ 수량이 단가다 (세금 포함). 세금을 뺀 매출로 나누면 10% 낮아진다.
    assert row.unit_price() == 150000
    assert row.revenue_net / row.quantity < 140000


def test_percent_discount_matches_doc_example():
    # 경쟁 업장의 주말 10% 할인: 4명 × 140,000 의 10%
    assert apply_pct(4 * 140000, 10) == 56000


@pytest.mark.parametrize(
    ("price", "pct", "expected"),
    [(150000, 10, 165000), (15, 10, 17), (15, -10, 14), (99999, -12.5, 87499), (100, -99.5, 1), (150000, 0, 150000)],
)
def test_changed_price_is_rounded_itself(price, pct, expected):
    assert change_price(price, pct) == expected


def test_price_change_is_not_the_rounded_difference():
    # 15원을 10% 내리면 13.5원이고, 반올림하면 14원이다 (7절: 바뀐 가격을 반올림한다).
    # 내린 폭 1.5원을 먼저 반올림해 빼면 13원이 되어 1원 어긋난다.
    assert change_price(15, -10) == 14
    assert 15 - apply_pct(15, 10) == 13


def test_amount_helpers_reject_what_they_cannot_round():
    with pytest.raises(ValueError, match="0 이상"):
        round_half_up(-0.5)
    with pytest.raises(ValueError, match="change_price"):
        apply_pct(1000, -10)
    with pytest.raises(ValueError, match="-100"):
        change_price(1000, -100)
    # 끝이 없는 수는 조용히 넘어가지 않고 같은 종류의 오류로 알린다.
    for bad in (float("inf"), float("nan"), True):
        if bad is not True:
            with pytest.raises(ValueError, match="끝이 있는 수"):
                round_half_up(bad)
        with pytest.raises(ValueError, match="끝이 있는 수"):
            apply_pct(1000, bad)
        with pytest.raises(ValueError, match="끝이 있는 수"):
            change_price(1000, bad)


def test_price_can_drop_to_almost_nothing_but_not_below():
    assert change_price(0, 50) == 0
    assert change_price(150000, -99.99) == 15
    assert change_price(100, -99.99) == 0
    assert apply_pct(600000, 100) == 600000
    assert apply_pct(600000, 0) == 0


# ── 파일은 적힌 그대로 엄격하게 읽는다 (docs/FORMATS.md 2절) ────────────────


def test_read_model_reads_the_file_as_written(tmp_path):
    source = EXAMPLE_ROOT / "data" / "venues" / "geumryong.json"
    assert read_model(source, Venue).venue_id == "geumryong"

    data = load_json(source)
    data["products"][0]["price"] = "150000"
    path = tmp_path / "geumryong.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValidationError):
        read_model(path, Venue)
    # 느슨하게 읽으면 같은 파일이 통과한다. 그래서 파일은 read_model 로 읽는다.
    assert Venue.model_validate(data).products[0].price == 150000


def test_bundle_conditions_are_for_the_whole_year():
    bundle = load_json(EXAMPLE_ROOT / "engine" / "conditions.json")
    assert len(ConditionBundle.model_validate(bundle).conditions) == 8

    fixed = copy.deepcopy(bundle)
    fixed["conditions"][0]["month"] = 5
    with pytest.raises(ValidationError, match="month 를 null 로 둔다"):
        ConditionBundle.model_validate(fixed)

    manual = copy.deepcopy(bundle)
    manual["conditions"][0]["condition_id"] = "manual-1"
    with pytest.raises(ValidationError, match="화면에서 직접 넣은 조건에만 쓴다"):
        ConditionBundle.model_validate(manual)


# ── 두 층을 합치는 규칙 (docs/FORMATS.md 5절) ───────────────────────────────


@pytest.fixture
def public() -> dict:
    return load_json(EXAMPLE_ROOT / "personas" / "family-elders.json")


def private_layer(**content) -> dict:
    return {"format_version": 1, "persona_id": "family-elders", **content}


def test_merge_without_private_layer_adds_an_empty_list(public):
    # 비공개 층이 있든 없든 결과의 모양이 같다.
    assert merge_persona_layers(public, None) == {**public, "overridden_by_private": []}


def test_merged_result_shares_nothing_with_the_layers(public):
    private = private_layer(preferences={"needs": ["주차 대행"], "atmosphere": {"넓은 자리": 2}})
    before = copy.deepcopy((public, private))
    for layer in (None, private):
        merged = merge_persona_layers(public, layer)
        merged["preferences"]["needs"].append("고친 값")
        merged["preferences"]["atmosphere"]["조용함"] = 1
        merged["evidence"]["visit"]["refs"].clear()
        merged["visit"]["party"]["adults"] = 99
    assert (public, private) == before


def test_values_added_by_the_private_layer_are_copied(public):
    """비공개 층이 묶음이나 목록을 통째로 더할 때도 베껴 넣는다. 합친 결과를 고쳐도 비공개 층은 그대로다."""
    del public["visit"]  # 공개 층에 없는 키를 비공개 층이 통째로 더하는 경우
    public["compares_with"] = []
    visit = {"purposes": ["가족 행사"], "party": {"label": "3대 가족", "adults": 4, "children": 0}}
    private = private_layer(visit=visit, compares_with=[["목록 안의 목록"]])
    before = copy.deepcopy(private)
    merged = merge_persona_layers(public, private)
    merged["visit"]["party"]["adults"] = 99
    merged["visit"]["purposes"].append("고친 값")
    merged["compares_with"][0].append("고친 값")
    assert private == before
    assert merged["overridden_by_private"] == ["visit", "compares_with"]


def test_private_layer_fills_an_empty_public_value(public):
    # 공개 층의 값이 비어 있으면(null) 비공개 층의 값을 그대로 쓴다. 종류를 견줄 것이 없다.
    public["budget"] = None
    merged = merge_persona_layers(public, private_layer(budget={"basis": "party", "typical": 1, "max": 2}))
    assert merged["budget"] == {"basis": "party", "typical": 1, "max": 2}
    assert merged["overridden_by_private"] == ["budget"]


def test_private_layer_cannot_erase_or_retype_a_value(public):
    with pytest.raises(ValueError, match="지울 수는 없다"):
        merge_persona_layers(public, private_layer(budget={"max": None}))
    # 공개 층에 없는 키를 null 로 더하는 것도 받지 않는다 (견줄 공개 층의 값이 없어도 걸러야 한다).
    with pytest.raises(ValueError, match="지울 수는 없다"):
        merge_persona_layers(public, private_layer(preferences={"atmosphere": {"새 항목": None}}))
    # 참·거짓은 숫자가 아니다 (Python 에서는 True 가 1 과 같아서 따로 가려야 한다).
    with pytest.raises(ValueError, match="값의 종류는 바꿀 수 없다"):
        merge_persona_layers(public, private_layer(budget={"max": True}))
    with pytest.raises(ValueError, match="값의 종류는 바꿀 수 없다"):
        merge_persona_layers(public, private_layer(visit={"purposes": "가족 행사"}))
    with pytest.raises(ValueError, match="값의 종류는 바꿀 수 없다"):
        merge_persona_layers(public, private_layer(budget=250000))
    with pytest.raises(ValueError, match="값의 종류는 바꿀 수 없다"):
        merge_persona_layers(public, private_layer(budget={"max": "250000"}))


@pytest.mark.parametrize("version", [None, 2, "1", True])
def test_private_layer_needs_the_format_version(public, version):
    layer = {"persona_id": "family-elders", "budget": {"max": 250000}}
    if version is not None:
        layer["format_version"] = version
    with pytest.raises(ValueError, match="format_version"):
        merge_persona_layers(public, layer)


def test_duplicates_inside_the_private_list_are_dropped(public):
    refs = ["P-geumryong-0002", "P-geumryong-0002", "R-geumryong-0003"]
    merged = merge_persona_layers(public, private_layer(evidence={"visit": {"refs": refs}}))
    assert merged["evidence"]["visit"]["refs"] == ["R-geumryong-0003", "R-geumryong-0011", "P-geumryong-0002"]


def test_new_key_from_the_private_layer_is_recorded(public):
    merged = merge_persona_layers(public, private_layer(preferences={"atmosphere": {"전망": 3, "넓은 자리": 2}}))
    assert merged["preferences"]["atmosphere"] == {"조용함": 3, "격식": 3, "전망": 3, "넓은 자리": 2}
    # 값이 바뀐 키(전망 1 → 3)와 새로 생긴 키(넓은 자리)를 모두 적는다.
    assert merged["overridden_by_private"] == ["preferences.atmosphere.전망", "preferences.atmosphere.넓은 자리"]


def test_merged_persona_is_checked_against_the_format(public):
    persona = merged_persona(public, private_layer(budget={"max": 250000}))
    assert persona.budget.max == 250000
    assert persona.overridden_by_private == ["budget.max"]
    assert merged_persona(public, None).overridden_by_private == []
    # 합친 결과가 형식에 어긋나면 받지 않는다: 평소 쓰는 금액(150,000)보다 작은 max, 정수가 아닌 중요도.
    with pytest.raises(ValidationError):
        merged_persona(public, private_layer(budget={"max": 100}))
    with pytest.raises(ValidationError):
        merged_persona(public, private_layer(preferences={"atmosphere": {"전망": 2.5}}))


def test_single_value_is_replaced_and_recorded(public):
    private = {"format_version": 1, "persona_id": "family-elders", "budget": {"max": 250000}}
    merged = merge_persona_layers(public, private)
    assert merged["budget"] == {"basis": "per_person", "typical": 150000, "max": 250000}
    assert merged["overridden_by_private"] == ["budget.max"]
    assert Persona.model_validate(merged).budget.max == 250000


def test_lists_are_joined_without_duplicates(public):
    private = {
        "format_version": 1,
        "persona_id": "family-elders",
        "preferences": {"needs": ["별실", "주차 대행"]},
    }
    merged = merge_persona_layers(public, private)
    assert merged["preferences"]["needs"] == ["별실", "어르신이 움직이기 편함", "주차 대행"]
    # 목록에 값이 더해진 것도 비공개 층 때문에 달라진 것이다. 흔적이 남아야 합친 결과인지 알 수 있다.
    assert merged["overridden_by_private"] == ["preferences.needs"]


def test_list_with_nothing_new_leaves_no_trace(public):
    private = {"format_version": 1, "persona_id": "family-elders", "preferences": {"needs": ["별실"]}}
    merged = merge_persona_layers(public, private)
    assert merged == {**public, "overridden_by_private": []}


def test_same_value_is_not_recorded_as_overridden(public):
    private = {"format_version": 1, "persona_id": "family-elders", "budget": {"max": 220000}}
    assert merge_persona_layers(public, private)["overridden_by_private"] == []


def test_merge_does_not_change_the_public_layer(public):
    before = copy.deepcopy(public)
    private = {"format_version": 1, "persona_id": "family-elders", "evidence": {"visit": {"refs": ["P-x-0001"]}}}
    merge_persona_layers(public, private)
    assert public == before


def test_private_layer_must_be_for_the_same_persona(public):
    with pytest.raises(ValueError, match="persona_id"):
        merge_persona_layers(public, {"format_version": 1, "persona_id": "someone-else"})
    # 식별자가 빠진 층은 누구의 것인지 알 수 없다. 공개 층에도 식별자가 없다고 해서 맞는 것으로 보지 않는다.
    with pytest.raises(ValueError, match="persona_id"):
        merge_persona_layers(public, {"format_version": 1, "budget": {"max": 250000}})
    del public["persona_id"]
    with pytest.raises(ValueError, match="persona_id"):
        merge_persona_layers(public, {"format_version": 1})


def test_private_layer_cannot_add_unknown_keys(public):
    private = {"format_version": 1, "persona_id": "family-elders", "base_profile": {}}
    with pytest.raises(ValueError, match="약속에 없는 키"):
        merge_persona_layers(public, private)


def test_persona_without_review_refs_lacks_reason_evidence():
    elders = Persona.model_validate(load_json(EXAMPLE_ROOT / "personas" / "family-elders.json"))
    kids = Persona.model_validate(load_json(EXAMPLE_ROOT / "personas" / "family-kids.json"))
    assert elders.lacks_reason_evidence() is False
    assert kids.lacks_reason_evidence() is True


# ── 응답을 다시 검사하는 규칙 (docs/FORMATS.md 9절) ─────────────────────────


@pytest.fixture
def saved() -> dict:
    folder = EXAMPLE_ROOT / "engine" / "samples" / "runs" / BASELINE_RUN / "llm"
    return load_json(next(folder.glob("*.json")))


def problems(saved: dict, **changes) -> list[str]:
    response = copy.deepcopy(saved["response"])
    for key, value in changes.items():
        response[key] = value
    return problems_in_response(
        ChoiceRequest.model_validate(saved["request"]), ChoiceResponse.model_validate(response)
    )


def test_example_response_has_no_problems(saved):
    assert problems(saved) == []


def test_choice_must_be_a_candidate(saved):
    found = problems(saved, choice={"venue_id": "ondal", "option_id": "ondal-o1", "addons": []})
    assert any("고른 업장 'ondal' 가 후보에 없다" in p for p in found)


def test_option_must_belong_to_the_venue(saved):
    found = problems(
        saved, choice={"venue_id": "geumryong", "option_id": "examplehotel-chinese-o1", "addons": []}
    )
    assert any("업장 'geumryong' 의 주문에 없다" in p for p in found)


def test_reason_labels_must_be_in_vocab(saved):
    found = problems(saved, reason_labels=["별실", "왠지 좋아서"])
    assert any("이유 라벨 '왠지 좋아서'" in p for p in found)


NONE = {"venue_id": None, "option_id": None, "addons": []}


def rejected_all(*venue_ids: str) -> list[dict]:
    return [{"venue_id": venue_id, "pain_labels": ["가격"], "text": "비싸다."} for venue_id in venue_ids]


def test_choosing_none_uses_pain_points(saved):
    rejected = rejected_all("geumryong", "examplehotel-chinese")
    assert problems(saved, choice=NONE, reason_labels=["가격"], rejected=rejected) == []
    found = problems(saved, choice=NONE, reason_labels=["별실"], rejected=rejected)
    assert found == ["이유 라벨 '별실' 이 vocab.pain_points 에 없다"]


def test_every_other_candidate_is_rejected_exactly_once(saved):
    assert problems(saved, rejected=[]) == ["고르지 않은 후보 'examplehotel-chinese' 가 rejected 에 없다"]
    twice = rejected_all("examplehotel-chinese", "examplehotel-chinese")
    assert problems(saved, rejected=twice) == ["rejected 에 업장 'examplehotel-chinese' 가 두 번 있다"]
    # "이용하지 않음"을 고르면 후보 모두가 고르지 않은 후보다.
    assert problems(saved, choice=NONE, reason_labels=["가격"], rejected=[]) == [
        "고르지 않은 후보 'geumryong' 가 rejected 에 없다",
        "고르지 않은 후보 'examplehotel-chinese' 가 rejected 에 없다",
    ]


def test_added_products_follow_the_request(saved):
    request = copy.deepcopy(saved["request"])
    request["candidates"][0]["addons"] = [
        {"product_id": "tea", "name": "차", "unit": "잔", "unit_price": 8000, "qty_max": 4}
    ]

    def found(*addons: tuple[str, int]) -> list[str]:
        response = copy.deepcopy(saved["response"])
        response["choice"]["addons"] = [{"product_id": product_id, "quantity": qty} for product_id, qty in addons]
        return problems_in_response(
            ChoiceRequest.model_validate(request), ChoiceResponse.model_validate(response)
        )

    assert found(("tea", 0)) == []
    assert found(("tea", 4)) == []
    assert found(("tea", 5)) == ["추가 상품 'tea' 의 수량이 qty_max 를 넘는다"]
    assert found(("coffee", 1)) == ["추가 상품 'coffee' 가 업장 'geumryong' 의 addons 에 없다"]
    assert found(("tea", 1), ("tea", 2)) == ["choice.addons 에 같은 추가 상품이 두 번 있다"]


def test_request_cannot_offer_an_order_over_budget(saved):
    # 1인 기준: 코스 B 는 4명에 800,000 이라 1인 200,000 이다.
    request = copy.deepcopy(saved["request"])
    request["condition"]["budget"]["max"] = 199999
    with pytest.raises(ValidationError, match="'geumryong-o2' 가 예산의 max 를 넘는다"):
        ChoiceRequest.model_validate(request)
    request["condition"]["budget"]["max"] = 200000
    ChoiceRequest.model_validate(request)

    # 일행 기준: total 을 그대로 견준다.
    request["condition"]["budget"] = {"basis": "party", "typical": 500000, "max": 799999}
    with pytest.raises(ValidationError, match="'geumryong-o2' 가 예산의 max 를 넘는다"):
        ChoiceRequest.model_validate(request)
    request["condition"]["budget"]["max"] = 800000
    ChoiceRequest.model_validate(request)


def test_budget_per_person_counts_adults_and_children(saved):
    """1인 기준 예산은 total 을 성인과 어린이를 더한 사람 수로 나눠 견준다."""
    request = copy.deepcopy(saved["request"])
    request["condition"]["budget"] = {"basis": "per_person", "typical": 100000, "max": 150000}
    # 두 명이면 코스 A(600,000)가 1인 300,000 이라 넘는다.
    request["condition"].update(adults=2, children=0)
    with pytest.raises(ValidationError, match="'geumryong-o1' 가 예산의 max 를 넘는다"):
        ChoiceRequest.model_validate(request)
    # 성인 4명에 어린이 2명이면 코스 B(800,000)도 1인 133,333 이라 들어온다.
    request["condition"].update(adults=4, children=2)
    ChoiceRequest.model_validate(request)
    # 어린이를 빼고 4명으로 세면 코스 B 는 1인 200,000 이라 넘는다.
    request["condition"].update(adults=4, children=0)
    with pytest.raises(ValidationError, match="'geumryong-o2' 가 예산의 max 를 넘는다"):
        ChoiceRequest.model_validate(request)


# ── 원장의 한 줄 (docs/FORMATS.md 10.2절) ───────────────────────────────────


@pytest.fixture
def ledger_row() -> dict:
    return load_csv(EXAMPLE_ROOT / "engine" / "samples" / "runs" / BASELINE_RUN / "ledger.csv")[0]


def test_example_ledger_row_is_valid(ledger_row):
    row = LedgerRow.from_row(ledger_row)
    assert (row.paid, row.revenue_net, row.request_hash) == (600000, 545455, "3048cd02fff58366")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"request_hash": "", "llm_call": ""}, "업장을 고른 줄에는 request_hash 가 있어야 한다"),
        ({"request_hash": ""}, "llm_call 과 request_hash 는 둘 다 있거나 둘 다 비어 있다"),
        ({"llm_call": ""}, "llm_call 과 request_hash 는 둘 다 있거나 둘 다 비어 있다"),
        ({"request_hash": "not-a-hash"}, "request_hash 는 16진수 16글자다"),
        ({"fail_reason": "이유"}, "fail_reason 은 실패한 줄에만 적는다"),
        ({"status": "failed", "fail_reason": "이유"}, "실패한 줄은 choice_kind 가 none 이고 업장·상품이 비어 있다"),
        ({"represented": "inf", "weighted_revenue": "inf"}, "finite"),
    ],
)
def test_ledger_row_rules(ledger_row, change, message):
    with pytest.raises(ValidationError, match=message):
        LedgerRow.from_row(ledger_row | change)


def test_failed_ledger_row_carries_no_amounts(ledger_row):
    failed = ledger_row | {"choice_kind": "none", "venue_id": "", "product_id": "", "quantity": "0", "unit": ""}
    failed |= {"list_price": "0", "discount": "0", "paid": "0", "revenue_net": "0", "weighted_revenue": "0"}
    failed |= {"status": "failed", "fail_reason": "응답이 후보 밖의 업장을 골랐다"}
    assert LedgerRow.from_row(failed).status == "failed"
    for column in ("quantity", "list_price", "paid", "revenue_net", "weighted_revenue"):
        with pytest.raises(ValidationError, match="실패한 줄의 수량과 금액은 모두 0 이다"):
            LedgerRow.from_row(failed | {column: "1000"})
    with pytest.raises(ValidationError, match="fail_reason 을 적는다"):
        LedgerRow.from_row(failed | {"fail_reason": ""})


def test_not_using_row_needs_no_saved_response(ledger_row):
    """후보가 하나도 없어 엔진이 정한 '이용하지 않음'은 응답 없이도 남길 수 있다. 금액이 없기 때문이다."""
    none = ledger_row | {"choice_kind": "none", "venue_id": "", "product_id": "", "quantity": "0", "unit": ""}
    none |= {"list_price": "0", "discount": "0", "paid": "0", "revenue_net": "0", "weighted_revenue": "0"}
    none |= {"llm_call": "", "request_hash": "", "reason_labels": "", "reason_text": "", "used_attributes": ""}
    assert LedgerRow.from_row(none).request_hash is None
    with pytest.raises(ValidationError, match="이용하지 않음인 줄은 업장·상품이 비어 있고 수량과 금액이 0 이다"):
        LedgerRow.from_row(none | {"quantity": "4"})


def test_used_attributes_must_exist_in_persona(saved):
    found = problems(saved, used_attributes=["budget.typical", "preferences.hobby"])
    assert found == ["used_attributes 의 'preferences.hobby' 가 페르소나에 없는 속성이다"]


def test_chosen_venue_cannot_also_be_rejected(saved):
    rejected = [{"venue_id": "geumryong", "pain_labels": ["가격"], "text": "비싸다."}]
    found = problems(saved, rejected=rejected)
    assert any("rejected 에도 있다" in p for p in found)
