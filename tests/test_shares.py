"""방문의 몫 (T212, docs/FORMATS.md 9절 "점수와 몫", 10.2절, 10.6절 "몫으로 나뉜 방문").

AI 점수(`scores`)를 업장마다의 몫으로 바꾸고, 점수를 검사하고, 몫으로 나뉜 방문을 원장의 줄로 적고,
몫으로 나뉜 방문의 매출 변화를 비례 배분으로 나누는지 본다. 요청과 업장은 예시 묶음(tests/fixtures/example)에서 만들고,
점수·몫·금액·원장 줄은 모두 지어낸 값이다.
"""

import json
from pathlib import Path

import jsonschema
import pytest

from engine.changes import decompose
from engine.constants import load_constants
from engine.formats import LEDGER_COLUMNS, ChoiceRequest, ChoiceResponse, LedgerRow, Venue
from engine.formats.changes import PARTS
from engine.formats.choice import problems_in_response, score_problems
from engine.formats.constants import ConstantsFile
from engine.formats.io import read_csv, write_csv
from engine.formats.money import net_of_tax, round_half_up, weighted_amount
from engine.formats.run import SEASON_GAP_REASON
from engine.ledger import venue_shares, visit_rows
from engine.llm import response_schema
from engine.runner import load_inputs
from engine.shares import SHARPNESS_ID, VENUE_CONSTANT_PREFIX, ShareParams, places, share_params
from tests.conftest import BASELINE_RUN, EXAMPLE_ROOT, load_csv, load_json
from tests.test_engine import DINNER, answer, product_of, requests_in, venue_file

VISIT = f"family-elders__{DINNER}"
# 예시 묶음의 이 방문의 후보 순서: geumryong, thebuffet, examplehotel-buffet, examplehotel-chinese.
GEUMRYONG, BUFFET, RIVAL_BUFFET, RIVAL_CHINESE = "geumryong", "thebuffet", "examplehotel-buffet", "examplehotel-chinese"
K1 = ShareParams(k=1.0, venue_constants={})


# ── 도우미 ──────────────────────────────────────────────────────────────


def request_for(prompt_version: str = "p4") -> ChoiceRequest:
    """예시 묶음의 어르신 가족·주말 저녁 요청. 프롬프트 판만 바꾼다."""
    request = requests_in(EXAMPLE_ROOT, ["family-elders"], [DINNER])[VISIT]
    return request.model_copy(update={"prompt_version": prompt_version})


def scored(request: ChoiceRequest, choice: tuple[str | None, str | None], scores: list[tuple]) -> ChoiceResponse:
    """점수가 있는 답. `scores` 는 (venue_id, percent, option_id[, addons]) 의 목록이다."""
    data = answer(request, *choice).model_dump(mode="json")
    data["scores"] = [
        {
            "venue_id": entry[0],
            "percent": entry[1],
            "option_id": entry[2],
            "addons": [{"product_id": p, "quantity": q} for p, q in (entry[3] if len(entry) > 3 else [])],
        }
        for entry in scores
    ]
    return ChoiceResponse.model_validate(data)


# 약속대로인 점수: 금룡 60, 경쟁 중식 30, 이용하지 않음 10. 점수가 0 인 두 뷔페는 주문을 적지 않았다.
GOOD_SCORES = [
    (GEUMRYONG, 60, "geumryong-o1"),
    (BUFFET, 0, None),
    (RIVAL_BUFFET, 0, None),
    (RIVAL_CHINESE, 30, "examplehotel-chinese-o1"),
    (None, 10, None),
]
GOOD_CHOICE = (GEUMRYONG, "geumryong-o1")


def good_response(request: ChoiceRequest) -> ChoiceResponse:
    return scored(request, GOOD_CHOICE, GOOD_SCORES)


def replaced(venue_id: str | None, new: tuple) -> list[tuple]:
    """GOOD_SCORES 에서 한 곳의 항목만 바꾼 것."""
    return [new if entry[0] == venue_id else entry for entry in GOOD_SCORES]


def with_budget_limit(request: ChoiceRequest, limit: int) -> ChoiceRequest:
    """예산의 max 만 낮춘 요청 (검증을 거치지 않고 바꾼다. 후보의 주문이 예산을 넘는 답을 만들려고 쓴다)."""
    condition = request.condition
    people = condition.adults + condition.children
    top = limit // people if condition.budget.basis == "per_person" else limit
    budget = condition.budget.model_copy(update={"max": top, "typical": min(condition.budget.typical, top)})
    lowered = request.model_copy(update={"condition": condition.model_copy(update={"budget": budget})})
    assert lowered.condition.budget_limit() == limit
    return lowered


def constants_with(k, venue_constants: list[tuple[str, float, bool]] = ()) -> ConstantsFile:
    """엔진의 결정 상수 파일에서 k 를 바꾸고 업장 상수를 더한 것 (venue_id, 값, in_use)."""
    data = load_constants().model_dump(mode="json")
    template = next(c for c in data["constants"] if c["constant_id"] == SHARPNESS_ID)
    template["value"] = k
    data["constants"] = [c for c in data["constants"] if not c["constant_id"].startswith(VENUE_CONSTANT_PREFIX)]
    for venue_id, value, in_use in venue_constants:
        data["constants"].append(
            {**template, "constant_id": f"{VENUE_CONSTANT_PREFIX}{venue_id}", "name": f"{venue_id} 의 업장 상수", "value": value, "in_use": in_use}
        )
    return ConstantsFile.model_validate(data)


# ── engine.shares.places / share_params ─────────────────────────────────


def test_k1_without_venue_constants_uses_the_percent_as_the_share():
    request = request_for()
    found = places(request, good_response(request), K1)
    assert [(p.venue_id, p.score) for p in found] == [(GEUMRYONG, 60), (RIVAL_CHINESE, 30), (None, 10)]
    assert [p.share for p in found] == pytest.approx([0.6, 0.3, 0.1])


def test_k_and_venue_constants_weight_the_share_as_percent_to_the_k_times_the_constant():
    """몫 = (p^k × c) ÷ Σ. k=2, 금룡 상수 0.5 → 금룡 3600×0.5, 중식 900, 이용하지 않음 100."""
    request = request_for()
    found = places(request, good_response(request), ShareParams(k=2.0, venue_constants={GEUMRYONG: 0.5}))
    total = 3600 * 0.5 + 900 + 100
    assert {p.venue_id: p.share for p in found} == pytest.approx({GEUMRYONG: 1800 / total, RIVAL_CHINESE: 900 / total, None: 100 / total})
    assert sum(p.share for p in found) == pytest.approx(1.0)


def test_places_with_percent_zero_are_left_out():
    request = request_for()
    found = places(request, good_response(request), K1)
    assert BUFFET not in [p.venue_id for p in found] and RIVAL_BUFFET not in [p.venue_id for p in found]


def test_places_follow_the_candidate_order_with_not_using_last_whatever_the_answer_order():
    request = request_for()
    shuffled = scored(request, GOOD_CHOICE, [GOOD_SCORES[4], GOOD_SCORES[3], GOOD_SCORES[1], GOOD_SCORES[0], GOOD_SCORES[2]])
    assert [p.venue_id for p in places(request, shuffled, K1)] == [GEUMRYONG, RIVAL_CHINESE, None]


def test_each_place_carries_the_order_it_would_take_there():
    request = request_for()
    found = {p.venue_id: p.choice for p in places(request, good_response(request), K1)}
    assert (found[GEUMRYONG].venue_id, found[GEUMRYONG].option_id) == (GEUMRYONG, "geumryong-o1")
    assert found[RIVAL_CHINESE].option_id == "examplehotel-chinese-o1"
    assert (found[None].venue_id, found[None].option_id) == (None, None)


def test_answer_without_scores_is_one_place_with_share_one_and_no_score():
    request = request_for("p1")
    (only,) = places(request, answer(request, GEUMRYONG, "geumryong-o1"), ShareParams(k=3.0, venue_constants={GEUMRYONG: 0.1}))
    assert (only.venue_id, only.share, only.score, only.choice.option_id) == (GEUMRYONG, 1.0, None, "geumryong-o1")


def test_share_params_reads_k_and_only_the_venue_constants_in_use():
    params = share_params(constants_with(2, [(GEUMRYONG, 0.5, True), (BUFFET, 2.0, False)]))
    assert params.k == 2.0
    assert params.venue_constants == {GEUMRYONG: 0.5}


def test_venue_without_a_constant_and_not_using_count_as_one():
    params = share_params(constants_with(1.5, [(GEUMRYONG, 0.5, True)]))
    assert (params.constant(BUFFET), params.constant(None), params.constant(GEUMRYONG)) == (1.0, 1.0, 0.5)


@pytest.mark.parametrize("k", [0, -1, -0.5])
def test_share_params_refuses_k_that_is_not_above_zero(k):
    with pytest.raises(ValueError, match=SHARPNESS_ID):
        share_params(constants_with(k))


# ── score_problems / problems_in_response ──────────────────────────────


def test_valid_scores_answer_has_no_problems():
    """점수가 0 인 곳은 주문이 null 이어도 된다 (두 뷔페)."""
    request = request_for()
    assert problems_in_response(request, good_response(request)) == []


def test_missing_scores_is_a_problem_for_a_prompt_that_asks_for_scores():
    request = request_for("p4")
    problems = problems_in_response(request, answer(request, *GOOD_CHOICE))
    assert any("scores 가 없다" in p for p in problems)


@pytest.mark.parametrize("prompt_version", ["p1", "p2", "p3"])
def test_missing_scores_is_fine_for_a_single_answer_prompt(prompt_version):
    request = request_for(prompt_version)
    assert problems_in_response(request, answer(request, *GOOD_CHOICE)) == []


WRONG_SCORES = [
    ("합이 100 이 아님", GOOD_CHOICE, replaced(None, (None, 20, None)), "더하면 100 이어야 한다"),
    ("후보가 빠짐", GOOD_CHOICE, [s for s in GOOD_SCORES if s[0] != BUFFET], "scores 에 'thebuffet' 이 없다"),
    ("이용하지 않음이 빠짐", GOOD_CHOICE, replaced(GEUMRYONG, (GEUMRYONG, 70, "geumryong-o1"))[:-1], "scores 에 '이용하지 않음' 이 없다"),
    ("같은 곳이 두 번", GOOD_CHOICE, [*GOOD_SCORES, (BUFFET, 0, None)], "같은 곳이 두 번 있다"),
    ("이용하지 않음이 두 번", GOOD_CHOICE, [*GOOD_SCORES, (None, 0, None)], "같은 곳이 두 번 있다"),
    ("후보에 없는 업장", GOOD_CHOICE, [*GOOD_SCORES, ("nowhere", 0, None)], "scores 의 업장 'nowhere' 가 후보에 없다"),
    ("고른 곳의 점수가 0", (BUFFET, "thebuffet-o1"), GOOD_SCORES, "choice 에 적은 곳의 점수가 0 이다"),
    ("고른 주문이 점수의 주문과 다름", (GEUMRYONG, "geumryong-o2"), GOOD_SCORES, "choice 의 주문이 scores 에 적은 그곳의 주문과 다르다"),
    (
        "점수가 있는 곳의 주문이 그 업장의 것이 아님",
        GOOD_CHOICE,
        replaced(RIVAL_CHINESE, (RIVAL_CHINESE, 30, "geumryong-o2")),
        "scores 의 'examplehotel-chinese' — 고른 주문 'geumryong-o2' 가 업장 'examplehotel-chinese' 의 주문에 없다",
    ),
    (
        "점수가 있는 곳의 주문이 비어 있음",
        GOOD_CHOICE,
        replaced(RIVAL_CHINESE, (RIVAL_CHINESE, 30, None)),
        "scores 의 'examplehotel-chinese' — 업장 'examplehotel-chinese' 는 주문을 하나 골라야 한다",
    ),
    ("이용하지 않음에 주문이 있음", GOOD_CHOICE, replaced(None, (None, 10, "geumryong-o1")), "'이용하지 않음' 에는 주문이 없다"),
]


@pytest.mark.parametrize("name, choice, scores, expected", WRONG_SCORES, ids=[w[0] for w in WRONG_SCORES])
def test_scores_that_break_the_rules_are_problems(name, choice, scores, expected):
    request = request_for()
    problems = score_problems(request, scored(request, choice, scores))
    assert any(expected in p for p in problems), problems


def test_order_over_the_budget_in_a_scores_entry_is_a_problem():
    """점수가 0 보다 큰 곳의 주문도 예산의 max 와 견준다. 뷔페 720,000 원은 낮춘 max 700,000 원을 넘는다 (금룡 600,000, 중식 560,000 은 안 넘는다)."""
    request = with_budget_limit(request_for(), 700000)
    scores = [(GEUMRYONG, 50, "geumryong-o1"), (BUFFET, 20, "thebuffet-o1"), (RIVAL_BUFFET, 0, None), (RIVAL_CHINESE, 20, "examplehotel-chinese-o1"), (None, 10, None)]
    problems = score_problems(request, scored(request, GOOD_CHOICE, scores))
    assert problems == ["scores 의 'thebuffet' — 고른 주문과 추가 상품의 금액을 더한 값이 예산의 max 를 넘는다"]


def test_entry_with_percent_zero_is_not_checked_for_its_order():
    """점수가 0 인 곳은 그곳에 가지 않으므로 주문을 보지 않는다."""
    request = request_for()
    assert score_problems(request, scored(request, GOOD_CHOICE, replaced(BUFFET, (BUFFET, 0, None)))) == []


def test_choosing_not_using_with_scores_is_fine_when_not_using_has_a_score():
    request = request_for()
    scores = [(GEUMRYONG, 20, "geumryong-o1"), (BUFFET, 0, None), (RIVAL_BUFFET, 0, None), (RIVAL_CHINESE, 0, None), (None, 80, None)]
    assert score_problems(request, scored(request, (None, None), scores)) == []


def test_problems_in_response_includes_the_score_problems():
    request = request_for()
    problems = problems_in_response(request, scored(request, GOOD_CHOICE, replaced(None, (None, 20, None))))
    assert any("더하면 100 이어야 한다" in p for p in problems)


# ── engine.llm.response_schema ──────────────────────────────────────────


def test_response_schema_requires_scores_for_a_prompt_that_asks_for_them():
    request = request_for("p4")
    schema = response_schema(request)
    assert "scores" in schema["properties"] and "scores" in schema["required"]
    item = schema["properties"]["scores"]["items"]
    assert set(item["properties"]["venue_id"]["anyOf"][0]["enum"]) == {c.venue_id for c in request.candidates}
    jsonschema.validate(good_response(request).model_dump(mode="json"), schema)


def test_response_schema_has_no_scores_for_a_single_answer_prompt():
    schema = response_schema(request_for("p1"))
    assert "scores" not in schema["properties"] and "scores" not in schema["required"]


def test_response_schema_refuses_a_p4_answer_without_scores():
    request = request_for("p4")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(answer(request, *GOOD_CHOICE).model_dump(mode="json"), response_schema(request))


# ── visit_rows: 몫으로 나뉜 방문을 원장의 줄로 ──────────────────────────


BASE = {
    "run_id": "r",
    "scenario_id": "baseline",
    "visit_id": VISIT,
    "persona_id": "family-elders",
    "customer_group": "가족·친족",
    "condition_id": DINNER,
    "represented": 10.0,
}
HASH = "0123456789abcdef"


def example_venues() -> dict[str, Venue]:
    return load_inputs(EXAMPLE_ROOT, "sample").venues


def rows_for(response: ChoiceResponse, venues: dict[str, Venue] | None = None, params: ShareParams | None = K1) -> list[LedgerRow]:
    return visit_rows(BASE, request_for(), response, venues or example_venues(), "replay", HASH, params)


def place_shares(rows: list[LedgerRow]) -> dict[tuple[str, str | None], float]:
    """곳마다의 고른 몫 (한 곳의 여러 줄은 같은 몫이다. 파는 달이 아닌 몫의 줄은 뺀다)."""
    found: dict[tuple[str, str | None], float] = {}
    for row in rows:
        if row.season_gap_of is None:
            found[(row.choice_kind, row.venue_id)] = row.choice_share
    return found


def test_scores_answer_writes_rows_for_each_place_with_a_share():
    rows = rows_for(good_response(request_for()))
    assert place_shares(rows) == pytest.approx(
        {("walkerhill", GEUMRYONG): 0.6, ("competitor", RIVAL_CHINESE): 0.3, ("none", None): 0.1}
    )
    assert sum(place_shares(rows).values()) == pytest.approx(1.0)


def test_rows_of_one_place_share_the_same_choice_share_and_score():
    rows = rows_for(good_response(request_for()))
    by_venue: dict[str | None, set] = {}
    for row in rows:
        by_venue.setdefault(row.venue_id, set()).add((row.choice_share, row.score))
    assert all(len(values) == 1 for values in by_venue.values()), by_venue
    assert {row.venue_id: row.score for row in rows} == {GEUMRYONG: 60, RIVAL_CHINESE: 30, None: 10}


def test_weighted_revenue_includes_the_choice_share():
    rows = [r for r in rows_for(good_response(request_for())) if r.choice_kind == "walkerhill"]
    assert rows
    for row in rows:
        assert row.weighted_revenue == round_half_up(weighted_amount(row.revenue_net, 10.0, 1.0, row.choice_share))
        assert row.weighted_revenue == round_half_up(row.revenue_net * 10 * 0.6)


def test_reasons_are_written_only_on_the_rows_of_the_chosen_place():
    response = good_response(request_for())
    for row in rows_for(response):
        if row.venue_id == GEUMRYONG:
            assert (row.reason_labels, row.reason_text, row.used_attributes) == (
                response.reason_labels, response.reason_text, response.used_attributes
            )
        else:
            assert (row.reason_labels, row.reason_text, row.used_attributes) == ([], None, [])


def test_rows_of_a_split_visit_all_point_to_the_same_answer():
    for row in rows_for(good_response(request_for())):
        assert (row.llm_call, row.request_hash, row.status) == ("replay", HASH, "ok")


def test_scores_answer_without_params_is_refused():
    with pytest.raises(ValueError, match="params"):
        rows_for(good_response(request_for()), params=None)


def test_single_answer_without_params_is_one_place_with_share_one():
    request = request_for("p1")
    rows = visit_rows(BASE, request, answer(request, *GOOD_CHOICE), example_venues(), "replay", HASH)
    assert {(r.venue_id, r.choice_share, r.score) for r in rows} == {(GEUMRYONG, 1.0, None)}


def seasonal_venues() -> dict[str, Venue]:
    """금룡의 course-a 를 4 ~ 6월에만 파는 것으로 바꾼 업장 정의 (지어낸 값)."""
    data = load_json(venue_file(EXAMPLE_ROOT, GEUMRYONG))
    product_of(data, "course-a")["months"] = [4, 5, 6]
    return {**example_venues(), GEUMRYONG: Venue.model_validate(data)}


def test_seasonal_place_writes_a_season_gap_row_with_the_share_of_that_place():
    rows = rows_for(good_response(request_for()), venues=seasonal_venues())
    bought = [r for r in rows if r.venue_id == GEUMRYONG]
    gaps = [r for r in rows if r.season_gap_of is not None]
    assert bought and all(r.counted_share == pytest.approx(0.25) and r.choice_share == pytest.approx(0.6) for r in bought)
    (gap,) = gaps
    assert (gap.choice_kind, gap.season_gap_of, gap.reason_text, gap.paid) == ("none", GEUMRYONG, SEASON_GAP_REASON, 0)
    assert (gap.choice_share, gap.counted_share, gap.score) == (pytest.approx(0.6), pytest.approx(0.75), 60)
    assert gap.request_hash == HASH


def test_seasonal_split_visit_counts_both_not_using_rows_in_the_visits():
    """이용하지 않음의 방문 = 10 × (이용하지 않음의 몫 0.1 + 금룡의 몫 0.6 × 파는 달이 아닌 몫 0.75)."""
    rows = rows_for(good_response(request_for()), venues=seasonal_venues())
    shares = venue_shares(rows)
    assert shares["none"]["visits"] == pytest.approx(10 * (0.1 + 0.6 * 0.75))
    assert shares["walkerhill"][GEUMRYONG]["visits"] == pytest.approx(10 * 0.6 * 0.25)
    assert shares["competitor"][RIVAL_CHINESE]["visits"] == pytest.approx(10 * 0.3)


def test_amounts_of_every_place_with_a_score_are_rechecked():
    """점수가 0 보다 큰 다른 곳의 주문 금액도 업장 정의로 다시 계산한다 (중식의 단가를 바꾸면 걸린다)."""
    from engine.ledger import amount_problems

    request = request_for()
    venues = example_venues()
    assert amount_problems(request, good_response(request), venues) == []
    data = load_json(venue_file(EXAMPLE_ROOT, RIVAL_CHINESE))
    product_of(data, "course")["price"] += 10000
    changed = {**venues, RIVAL_CHINESE: Venue.model_validate(data)}
    problems = amount_problems(request, good_response(request), changed)
    assert any(p.startswith("scores 의 'examplehotel-chinese' — ") and "단가" in p for p in problems), problems


# ── decompose: 몫으로 나뉜 방문의 비례 배분 ─────────────────────────────


VISIT_ID = "x__c"
K = 1.5
CONSTANTS = {"venue-a": 0.8, "venue-b": 1.3, "rival-c": 1.0, None: 1.0}
KIND = {"venue-a": "walkerhill", "venue-b": "walkerhill", "rival-c": "competitor", None: "none"}


def shares_of(scores: dict[str | None, int]) -> dict[str | None, float]:
    """몫 = (점수^k × 업장 상수) ÷ Σ. 테스트가 엔진과 따로 계산한다."""
    weights = {place: (percent**K) * CONSTANTS[place] for place, percent in scores.items()}
    total = sum(weights.values())
    return {place: w / total for place, w in weights.items()}


def ledger_row(venue: str | None, share: float, list_price: int = 0, discount: int = 0, run: str = "r", represented: float = 100.0) -> LedgerRow:
    """몫이 있는 원장의 한 줄 (지어낸 것). 상품 하나를 1개 산다."""
    kind = KIND[venue]
    quantity = 0 if kind == "none" else 1
    price = list_price if kind != "none" else 0
    paid = quantity * price - (discount if kind != "none" else 0)
    net = net_of_tax(paid) if kind == "walkerhill" else 0
    return LedgerRow.model_validate(
        {
            "run_id": run,
            "scenario_id": "baseline",
            "visit_id": VISIT_ID,
            "persona_id": "x",
            "customer_group": "가족·친족",
            "condition_id": "c",
            "choice_kind": kind,
            "venue_id": venue,
            "product_id": None if kind == "none" else "course",
            "quantity": quantity,
            "unit": None if kind == "none" else "1인",
            "list_price": price,
            "discount": discount if kind != "none" else 0,
            "paid": paid,
            "revenue_net": net,
            "represented": represented,
            "counted_share": 1.0,
            "choice_share": share,
            "score": None,
            "season_gap_of": None,
            "weighted_revenue": round_half_up(weighted_amount(net, represented, 1.0, share)),
            "reason_labels": [],
            "reason_text": None,
            "used_attributes": [],
            "llm_call": "replay",
            "request_hash": HASH,
            "status": "ok",
            "fail_reason": None,
        }
    )


BASE_SCORES = {"venue-a": 50, "venue-b": 30, "rival-c": 15, None: 5}
SCEN_SCORES = {"venue-a": 40, "venue-b": 45, "rival-c": 10, None: 5}
# 업장마다의 낸 금액 (기준, 상황). A 120,000 → 순매출 109,091. B 180,000 → 153,000 (가격 인하) 순매출 163,636 → 139,091.
PAID = {"venue-a": (120000, 120000), "venue-b": (180000, 153000), "rival-c": (140000, 140000), None: (0, 0)}


def split_ledgers(b_discount: bool = False) -> tuple[list[LedgerRow], list[LedgerRow]]:
    """FORMATS 10.6절 "몫으로 나뉜 방문"의 예: k=1.5, 업장 상수 A 0.8, B 1.3, C 1.0, 이용하지 않음 1.0.

    `b_discount` 면 B 의 인하를 표시가 그대로에 할인 27,000 원으로 적는다 (낸 금액은 같다).
    """
    base = [ledger_row(v, s, PAID[v][0]) for v, s in shares_of(BASE_SCORES).items()]
    scen = []
    for venue, share in shares_of(SCEN_SCORES).items():
        if b_discount and venue == "venue-b":
            scen.append(ledger_row(venue, share, 180000, discount=27000, run="s"))
        else:
            scen.append(ledger_row(venue, share, PAID[venue][1], run="s"))
    return base, scen


def test_worked_example_shares_are_what_the_formula_gives():
    """테스트가 계산한 몫이 문서의 예(기준 .5000 / .3776 / .1027 / .0198, 상황 .3174 / .6155 / .0496 / .0175)와 같다."""
    assert shares_of(BASE_SCORES) == pytest.approx({"venue-a": 0.5000, "venue-b": 0.3776, "rival-c": 0.1027, None: 0.0198}, abs=1e-4)
    assert shares_of(SCEN_SCORES) == pytest.approx({"venue-a": 0.3174, "venue-b": 0.6155, "rival-c": 0.0496, None: 0.0175}, abs=1e-4)


def test_split_visit_gainer_takes_its_gain_from_the_losers_in_proportion():
    """B: 남은 몫(.3776)의 금액 차이는 가격 효과, 늘어난 몫은 줄어든 곳들(A, C, 이용하지 않음)에서 줄어든 만큼에 비례해 왔다."""
    base, scen = split_ledgers()
    parts = {v.venue_id: v.parts for v in decompose(base, scen, "b", "s").venues}["venue-b"]
    assert parts.price == -926786
    assert parts.from_walkerhill == 2539137
    assert parts.from_competitor == 738502
    assert parts.new == 30992
    assert (parts.order, parts.to_competitor, parts.to_walkerhill, parts.to_none) == (0, 0, 0, 0)
    assert parts.total == 2381845


def test_split_visit_loser_gives_its_loss_to_the_gainers_in_proportion():
    """A: 몫이 늘어난 곳은 B 하나뿐이라 줄어든 몫의 금액이 모두 워커힐 안에서 옮겨 간 것이다."""
    base, scen = split_ledgers()
    parts = {v.venue_id: v.parts for v in decompose(base, scen, "b", "s").venues}["venue-a"]
    assert parts.to_walkerhill == -1991481
    assert (parts.new, parts.from_competitor, parts.from_walkerhill, parts.to_competitor, parts.to_none, parts.price, parts.order) == (
        0, 0, 0, 0, 0, 0, 0
    )
    assert parts.total == -1991481


def test_split_visit_parts_add_up_exactly_to_each_venue_change():
    base, scen = split_ledgers()
    found = decompose(base, scen, "b", "s")
    for venue in found.venues:
        assert sum(getattr(venue.parts, part) for part in PARTS) == venue.parts.total
        assert venue.after - venue.before == venue.parts.total
    before = sum(r.weighted_revenue for r in base if r.choice_kind == "walkerhill")
    after = sum(r.weighted_revenue for r in scen if r.choice_kind == "walkerhill")
    assert found.walkerhill.total == after - before == 2381845 - 1991481


def test_split_visit_records_the_shares_and_the_place_with_the_largest_share():
    base, scen = split_ledgers()
    (visit,) = decompose(base, scen, "b", "s").visits
    assert (visit.before.venue_id, visit.after.venue_id) == ("venue-a", "venue-b")
    assert {s.venue_id: s.share for s in visit.before_shares} == pytest.approx(shares_of(BASE_SCORES))
    assert {s.venue_id: s.share for s in visit.after_shares} == pytest.approx(shares_of(SCEN_SCORES))
    # 할인(discount)이 없는 가격 인하라 할인을 받은 몫은 없다.
    assert visit.promo == "none"
    assert (visit.promo_shares.would_come, visit.promo_shares.drawn) == (0.0, 0.0)


def test_discounted_split_visit_divides_the_discounted_share_into_would_come_and_drawn():
    """B 의 인하를 할인으로 적으면: 할인을 받은 B 의 몫 .6155 가운데 기준에도 있던 .3776 은 원래 오던 몫, 나머지는 새로 온 몫이다."""
    base, scen = split_ledgers(b_discount=True)
    found = decompose(base, scen, "b", "s")
    (visit,) = found.visits
    b_before, b_after = shares_of(BASE_SCORES)["venue-b"], shares_of(SCEN_SCORES)["venue-b"]
    assert visit.promo_shares.would_come == pytest.approx(b_before)
    assert visit.promo_shares.drawn == pytest.approx(b_after - b_before)
    assert visit.promo == "would_come"
    # 낸 금액이 같아 나누기도 같다: 같은 상품·수량이라 가격 효과다.
    assert {v.venue_id: v.parts for v in found.venues}["venue-b"].price == -926786


def test_single_place_visits_reproduce_the_rules_by_where_the_visit_went():
    """몫이 0 아니면 1 인 방문: A 에 가던 방문이 B 로 옮기면 A 는 전부를 워커힐 안으로 잃고 B 는 전부를 워커힐 안에서 얻는다."""
    base = [ledger_row("venue-a", 1.0, 120000)]
    scen = [ledger_row("venue-b", 1.0, 153000, run="s")]
    parts = {v.venue_id: v.parts for v in decompose(base, scen, "b", "s").venues}
    assert parts["venue-a"].to_walkerhill == -100 * 109091 == parts["venue-a"].total
    assert parts["venue-b"].from_walkerhill == 100 * 139091 == parts["venue-b"].total


def test_season_gap_rows_do_not_overwrite_the_share_of_not_using():
    """파는 달이 아닌 몫의 줄(season_gap_of)은 그 곳의 몫 안에 있다. 이용하지 않음의 몫은 이용하지 않음 줄의 몫(0.1) 그대로다."""
    rows = rows_for(good_response(request_for()), venues=seasonal_venues())
    (visit,) = decompose(rows, [r.model_copy(update={"run_id": "s"}) for r in rows], "b", "s").visits
    assert {(s.kind, s.venue_id): s.share for s in visit.before_shares} == pytest.approx(
        {("walkerhill", GEUMRYONG): 0.6, ("competitor", RIVAL_CHINESE): 0.3, ("none", None): 0.1}
    )


# ── read_csv: 몫 열이 없던 옛 원장 ─────────────────────────────────────


LATER = ("choice_share", "score", "season_gap_of")


def write_old_ledger(path: Path, drop: tuple[str, ...]) -> list[str]:
    """예시 묶음 기준 실행의 원장에서 `drop` 열을 뺀 머리글로 다시 쓴다 (옛 원장의 모양)."""
    rows = load_csv(EXAMPLE_ROOT / "engine" / "samples" / "runs" / BASELINE_RUN / "ledger.csv")
    columns = [c for c in LEDGER_COLUMNS if c not in drop]
    write_csv(path, columns, rows)
    return columns


def test_old_ledger_without_the_share_columns_is_read_with_share_one(tmp_path):
    path = tmp_path / "ledger.csv"
    write_old_ledger(path, LATER)
    rows = read_csv(path, LEDGER_COLUMNS)
    assert rows and all(list(row) == LEDGER_COLUMNS for row in rows)
    assert {(row["choice_share"], row["score"], row["season_gap_of"]) for row in rows} == {("1", "", "")}
    parsed = [LedgerRow.from_row(row) for row in rows]
    assert all(r.choice_share == 1.0 and r.score is None and r.season_gap_of is None for r in parsed)


@pytest.mark.parametrize(
    "drop, expected",
    [
        ((*LATER, "paid"), "빠진 열"),
        (("paid",), "빠진 열"),
        (("score",), "빠진 열 \\['score'\\]"),
    ],
    ids=["몫 열과 다른 열이 함께 빠짐", "다른 열만 빠짐", "몫 열 가운데 하나만 빠짐"],
)
def test_ledger_missing_other_columns_is_still_refused(tmp_path, drop, expected):
    path = tmp_path / "ledger.csv"
    write_old_ledger(path, drop)
    with pytest.raises(ValueError, match=f"머리글이 약속과 다르다: {expected}"):
        read_csv(path, LEDGER_COLUMNS)


def test_old_ledger_row_with_a_wrong_number_of_cells_is_refused(tmp_path):
    path = tmp_path / "ledger.csv"
    write_old_ledger(path, LATER)
    text = path.read_text(encoding="utf-8-sig").rstrip("\n") + "\nr,only,three\n"
    path.write_text(text, encoding="utf-8-sig", newline="\n")
    with pytest.raises(ValueError, match="칸 수가 머리글과 다르다"):
        read_csv(path, LEDGER_COLUMNS)


# ── 독립 검토(11-20)가 찾은 것의 회귀 시험 ─────────────────────────────


def _mixed_visit_rows() -> tuple[list[LedgerRow], list[LedgerRow]]:
    """한 업장(venue-a)이 이용하지 않음·경쟁·다른 워커힐 셋에서 함께 몫을 얻는 방문 (지어낸 값)."""
    base = [
        ledger_row("venue-a", 0.4, 100000, run="b"),
        ledger_row("rival-c", 0.3, 90000, run="b"),
        ledger_row("venue-b", 0.1, 80000, run="b"),
        ledger_row(None, 0.2, run="b"),
    ]
    scen = [ledger_row("venue-a", 0.8, 100000, run="s"), ledger_row("venue-b", 0.05, 80000, run="s"), ledger_row(None, 0.15, run="s")]
    return base, scen


def test_changes_do_not_depend_on_the_python_hash_seed():
    """집합을 도는 순서가 프로세스마다 달라도 갈래의 순서와 1원 배분이 같다. 엔진과 형식 검사가 같은 changes 를 내야 한다."""
    import os
    import subprocess
    import sys

    script = (
        "import json; from engine.changes import decompose; from tests.test_shares import _mixed_visit_rows; "
        "b, s = _mixed_visit_rows(); print(json.dumps(decompose(b, s, 'b', 's').model_dump(mode='json'), sort_keys=True))"
    )
    root = Path(__file__).resolve().parents[1]
    outputs = {
        subprocess.run(
            [sys.executable, "-c", script], cwd=root, capture_output=True, text=True, check=True,
            env={**os.environ, "PYTHONHASHSEED": str(seed)},
        ).stdout
        for seed in range(1, 6)
    }
    assert len(outputs) == 1
    parts = [p["part"] for p in json.loads(outputs.pop())["visits"][0]["parts"] if p["venue_id"] == "venue-a"]
    assert parts == sorted(parts, key=PARTS.index)


def test_promo_shares_never_go_above_one():
    """몫을 여럿 더하면 1.0000000000000002 가 될 수 있다. 할인을 받은 몫은 1 을 넘지 않아 changes 의 형식에 맞는다."""
    from engine.changes import _promo_shares, _Visit

    shares = [p / 100 for p in (34, 21, 5, 14, 1, 16, 9)]
    total = 0.0
    for share in shares:
        total += share
    assert total > 1  # 이 예가 정말 1 을 넘는지 먼저 본다
    after = _Visit(shares={("walkerhill", f"v{i}"): share for i, share in enumerate(shares)})
    for i in range(len(shares)):
        after.discounted[f"v{i}"] = True
    assert _promo_shares(_Visit(shares={("none", None): 1.0}), after)["drawn"] == 1.0
    assert _promo_shares(after, after)["would_come"] == 1.0


def test_choice_and_its_scores_order_compare_what_was_bought():
    """추가 상품을 적은 순서나 수량 0 인 항목만 다른 것은 같은 주문이다 (그것만으로 답을 거절하지 않는다)."""
    from engine.formats.choice import Choice, _bought

    def choice(addons: list[tuple[str, int]]) -> Choice:
        return Choice.model_validate(
            {"venue_id": "v", "option_id": None, "addons": [{"product_id": p, "quantity": q} for p, q in addons]}
        )

    assert _bought(choice([("tin", 1), ("cake", 2)])) == _bought(choice([("cake", 2), ("tin", 1), ("box", 0)]))
    assert _bought(choice([])) == _bought(choice([("box", 0)]))
    assert _bought(choice([("tin", 1)])) != _bought(choice([("tin", 2)]))
