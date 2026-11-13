"""규칙 엔진과 소비 원장 (T04).

예시 묶음(tests/fixtures/example)의 사본에서 엔진을 돌린다. LLM 은 부르지 않고, 테스트가 "정해 둔 답"을
저장된 응답의 모양으로 써 두면 엔진이 그것을 재생한다. 실행 결과는 임시 폴더에만 생긴다.
"""

import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engine.answers import AnswerBook, save_answer
from engine.audit import violations
from engine.candidates import build_request, candidate_for, candidates_for, quantity_for, run_condition
from engine.formats import (
    LEDGER_COLUMNS,
    ChoiceRequest,
    ChoiceResponse,
    ConditionBundle,
    LedgerRow,
    Persona,
    RunRecord,
    SavedResponse,
    Venue,
    Vocab,
    net_of_tax,
    read_model,
    round_half_up,
    weighted_amount,
)
from engine.formats.io import read_csv
from engine.formats.run import SEASON_GAP_REASON, Weights
from engine.ledger import NO_CANDIDATE_REASON, amount_problems, totals
from engine.runner import NO_SAVED_ANSWER, NotSupportedYet, _engine_commit, load_inputs, run, run_visit
from tests.conftest import BASELINE_RUN, EXAMPLE_ROOT, REPO_ROOT, load_json, save_csv, save_json
from tools.check_formats import check

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 18, 9, 0, 0, tzinfo=KST)
PROVIDER, MODEL = "fixed", "fixed-answers"
DINNER = "meal-dinner-weekend"
LUNCH = "meal-lunch-weekend"


# ── 도우미 ──────────────────────────────────────────────────────────────


def edit(path: Path, change) -> None:
    data = load_json(path)
    change(data)
    save_json(path, data)


def venue_file(root: Path, venue_id: str) -> Path:
    return root / "data" / "venues" / f"{venue_id}.json"


def persona_file(root: Path, persona_id: str) -> Path:
    return root / "personas" / f"{persona_id}.json"


def product_of(data: dict, product_id: str) -> dict:
    return next(p for p in data["products"] if p["product_id"] == product_id)


def answer(request: ChoiceRequest, venue_id: str | None, option_id: str | None = None, addons=()) -> ChoiceResponse:
    """요청에 맞는 답 하나. 고르지 않은 후보는 모두 rejected 에 넣는다."""
    pain = request.vocab.pain_points[0]
    return ChoiceResponse.model_validate(
        {
            "choice": {
                "venue_id": venue_id,
                "option_id": option_id,
                "addons": [{"product_id": p, "quantity": q} for p, q in addons],
            },
            "reason_labels": [pain if venue_id is None else request.vocab.reasons_chosen[0]],
            "reason_text": "정해 둔 답이다.",
            "used_attributes": ["budget"],
            "rejected": [
                {"venue_id": c.venue_id, "pain_labels": [pain], "text": "정해 둔 답이다."}
                for c in request.candidates
                if c.venue_id != venue_id
            ],
        }
    )


def first_option(request: ChoiceRequest, venue_id: str) -> ChoiceResponse:
    return answer(request, venue_id, request.candidate(venue_id).options[0].option_id)


class Played:
    """엔진을 한 번 돌린 결과."""

    def __init__(self, root: Path, run_dir: Path, requests: dict[str, ChoiceRequest]) -> None:
        self.root = root
        self.run_dir = run_dir
        self.requests = requests
        self.record = read_model(run_dir / "run.json", RunRecord)
        self.rows = [LedgerRow.from_row(row) for row in read_csv(run_dir / "ledger.csv", LEDGER_COLUMNS)]
        self.saved = {p.stem: read_model(p, SavedResponse) for p in (run_dir / "llm").glob("*.json")}
        self.venues = {p.stem: read_model(p, Venue) for p in (root / "data" / "venues").glob("*.json")}
        self.personas = {p.stem: read_model(p, Persona) for p in (root / "personas").glob("*.json")}
        self.bundle = read_model(root / "engine" / "conditions.json", ConditionBundle)

    def visit(self, persona_id: str, condition_id: str) -> list[LedgerRow]:
        return [row for row in self.rows if row.visit_id == f"{persona_id}__{condition_id}"]

    def violations(self) -> list[str]:
        return violations(self.rows, self.venues, self.saved, self.personas, self.bundle)


def requests_in(root: Path, persona_ids, condition_ids, venue_ids=None) -> dict[str, ChoiceRequest]:
    """엔진이 방문마다 만들 요청. 후보가 없는 방문은 들어 있지 않다."""
    inputs = load_inputs(root, "sample", venue_ids=venue_ids, persona_ids=persona_ids)
    found = {}
    for persona in inputs.personas.values():
        for condition_id in condition_ids:
            request, _ = build_request(
                prompt_version="p1",
                scenario_id="baseline",
                persona=inputs.persona_json[persona.persona_id],
                condition=run_condition(inputs.conditions.condition(condition_id), persona),
                venues=list(inputs.venues.values()),
                vocab=inputs.vocab,
            )
            if request is not None:
                found[f"{persona.persona_id}__{condition_id}"] = request
    return found


def play(root: Path, pick, persona_ids=("family-elders",), condition_ids=(DINNER,), venue_ids=None, now=NOW) -> Played:
    """`pick(visit_id, request)` 이 돌려준 답을 정해 둔 답으로 써 두고 엔진을 돌린다. None 을 돌려주면 답을 두지 않는다."""
    persona_ids, condition_ids = list(persona_ids), list(condition_ids)
    answers = root.parent / f"answers-{now:%H%M%S}"
    requests = requests_in(root, persona_ids, condition_ids, venue_ids)
    for visit_id, request in requests.items():
        response = pick(visit_id, request)
        if response is not None:
            save_answer(answers, PROVIDER, MODEL, request, response, now)
    run_dir = run(
        root,
        data_mode="sample",
        now=now,
        provider=PROVIDER,
        model=MODEL,
        prompt_version="p1",
        answers=[answers],
        venue_ids=venue_ids,
        persona_ids=persona_ids,
        condition_ids=condition_ids,
        engine_commit="0000000",
    )
    return Played(root, run_dir, requests)


def pick_geumryong(visit_id: str, request: ChoiceRequest) -> ChoiceResponse:
    return first_option(request, "geumryong")


def candidate_ids(played_or_requests, visit_id: str = f"family-elders__{DINNER}") -> list[str]:
    requests = getattr(played_or_requests, "requests", played_or_requests)
    request = requests.get(visit_id)
    return [c.venue_id for c in request.candidates] if request else []


# ── 문서의 예시가 그대로 나오는가 ───────────────────────────────────────


def test_replaying_the_doc_example_writes_the_same_ledger(example_copy):
    """문서의 예시 응답을 재생하면 문서의 예시 원장이 글자까지 똑같이 나온다 (docs/PRD.md 7.3절).

    엔진이 만든 요청의 해시가 문서의 예시와 같아야 재생된다. 다른 칸은 새로 불렀는지 재생했는지(llm_call)뿐이다.
    """
    old_run = example_copy / "engine" / "samples" / "runs" / BASELINE_RUN
    kept = example_copy.parent / "kept"
    shutil.move(old_run, kept)

    run_dir = run(
        example_copy,
        data_mode="sample",
        now=datetime(2026, 11, 17, 10, 15, 0, tzinfo=KST),
        provider="anthropic",
        model="claude-opus-5-5",
        prompt_version="p1",
        answers=[kept / "llm"],
        venue_ids=["geumryong", "examplehotel-chinese"],
        persona_ids=["family-elders"],
        condition_ids=[DINNER],
        weights=Weights.model_validate(load_json(kept / "run.json")["weights"]),
        engine_commit="0000000",
    )

    assert run_dir.name == BASELINE_RUN
    expected = (kept / "ledger.csv").read_bytes().replace(b",new,", b",replay,")
    assert (run_dir / "ledger.csv").read_bytes() == expected
    assert sorted(p.name for p in (run_dir / "llm").iterdir()) == sorted(p.name for p in (kept / "llm").iterdir())
    record = load_json(run_dir / "run.json")
    assert record["llm"]["calls_replayed"] == 1 and record["llm"]["calls_new"] == 0
    assert record["counts"] == {"visits": 1, "failed": 0}


# ── 수량과 금액 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "rule, audience, serves, adults, children, expected",
    [
        ("per_person", "all", 1, 4, 0, 4),
        ("per_person", "all", 1, 2, 2, 4),
        ("per_person", "adult", 1, 2, 2, 2),
        ("per_person", "child", 1, 2, 3, 3),
        ("per_serves", "all", 2, 4, 0, 2),
        ("per_serves", "all", 2, 4, 1, 3),
        ("per_serves", "all", 3, 2, 0, 1),
        ("per_serves", "all", 4, 4, 0, 1),
    ],
)
def test_quantity_follows_the_rule(rule, audience, serves, adults, children, expected):
    data = load_json(venue_file(EXAMPLE_ROOT, "geumryong"))
    data["products"][0].update(qty_rule=rule, audience=audience, serves=serves)
    product = Venue.model_validate(data).products[0]
    assert quantity_for(product, adults, children) == expected


def test_adult_and_child_prices_go_into_one_order(example_copy):
    played = play(
        example_copy,
        lambda visit, request: first_option(request, "thebuffet"),
        persona_ids=["family-kids"],
    )
    rows = played.visit("family-kids", DINNER)
    assert [(r.product_id, r.quantity, r.list_price, r.paid) for r in rows] == [
        ("dinner-adult", 2, 180000, 360000),
        ("dinner-child", 2, 90000, 180000),
    ]
    assert [r.revenue_net for r in rows] == [net_of_tax(360000), net_of_tax(180000)]
    assert played.violations() == []


def test_children_need_a_price_of_their_own(example_copy):
    """어린이가 있는데 어린이 가격이 없으면 그 주문은 만들지 않는다."""
    edit(
        venue_file(example_copy, "thebuffet"),
        lambda d: d.update(products=[p for p in d["products"] if p["audience"] != "child"]),
    )
    assert "thebuffet" not in candidate_ids(requests_in(example_copy, ["family-kids"], [DINNER]), f"family-kids__{DINNER}")
    assert "thebuffet" in candidate_ids(requests_in(example_copy, ["family-elders"], [DINNER]))


@pytest.mark.parametrize(
    "basis, unit_price",
    [("included", 150000), ("unknown", 150000), ("excluded_vat", 165000), ("excluded_vat_service", 181500)],
)
def test_price_is_what_the_customer_pays(example_copy, basis, unit_price):
    edit(venue_file(example_copy, "geumryong"), lambda d: product_of(d, "course-a").update(price_basis=basis))
    played = play(example_copy, pick_geumryong)
    (row,) = played.visit("family-elders", DINNER)
    assert (row.list_price, row.paid, row.revenue_net) == (unit_price, 4 * unit_price, net_of_tax(4 * unit_price))
    assert played.violations() == []


def test_product_without_a_price_is_left_out_and_recorded(example_copy):
    edit(
        venue_file(example_copy, "geumryong"),
        lambda d: product_of(d, "course-b").update(price=None, grade="unknown"),
    )
    played = play(example_copy, pick_geumryong)
    request = played.requests[f"family-elders__{DINNER}"]
    assert [o.lines[0].product_id for o in request.candidate("geumryong").options] == ["course-a"]
    assert played.record.skipped_products == ["geumryong:course-b"]


# ── 검증 사례: 조건을 어긴 곳은 후보에 없고, 그곳을 고른 답은 실패로 남는다 ─────


def remove_dinner_hours(d):
    d["hours"] = [h for h in d["hours"] if h["meal"] != "dinner"]


def dinner_on_weekdays_only(d):
    next(h for h in d["hours"] if h["meal"] == "dinner")["day_type"] = "weekday"


def lunch_only_venue(d):
    d["hours"] = [h for h in d["hours"] if h["meal"] == "lunch"]
    for product in d["products"]:
        product["slots"] = [{"meal": "lunch", "day_type": "all"}]


def budget(**values):
    return lambda d: d["budget"].update(**values)


def party(adults, children=0):
    return lambda d: d["visit"]["party"].update(adults=adults, children=children)


def reservation(**values):
    return lambda d: d["reservation"].update(**values)


# (종류, 고칠 파일, 고치는 것). 고친 뒤에는 금룡이 주말 저녁의 후보가 될 수 없다.
EXCLUDED = [
    ("운영 시간 밖", "venue", remove_dinner_hours),
    ("운영 시간 밖", "venue", dinner_on_weekdays_only),
    ("운영 시간 밖", "venue", lunch_only_venue),
    ("예산 초과", "persona", budget(typical=100000, max=149999)),
    ("예산 초과", "persona", budget(basis="party", typical=300000, max=599999)),
    ("예산 초과", "persona", budget(typical=50000, max=50000)),
    ("인원 초과", "venue", reservation(party_max=3)),
    ("인원 초과", "persona", party(13)),
    ("인원 초과", "persona", party(10, 3)),
    ("예약 조건 위반", "venue", reservation(party_min=5)),
    ("다른 이용 상황의 업장", "venue", lambda d: d.update(occasions=["dessert"], products=[], hours=None)),
]


@pytest.mark.parametrize("kind, where, change", EXCLUDED, ids=[f"{k}-{i}" for i, (k, _, _) in enumerate(EXCLUDED)])
def test_venue_that_breaks_a_condition_is_never_a_candidate(example_copy, kind, where, change):
    path = venue_file(example_copy, "geumryong") if where == "venue" else persona_file(example_copy, "family-elders")
    edit(path, change)

    # 그래도 금룡을 골랐다고 적은 답을 넣는다. 엔진은 그 답을 받아들이지 않아야 한다.
    forced = lambda visit, request: answer(request, "geumryong", "geumryong-o1")  # noqa: E731
    played = play(example_copy, forced)

    assert "geumryong" not in candidate_ids(played)
    assert not any(row.venue_id == "geumryong" for row in played.rows)
    for row in played.rows:
        assert row.status == "failed" or row.reason_text == NO_CANDIDATE_REASON
        assert row.paid == 0 and row.revenue_net == 0
    assert played.violations() == []


def test_boundary_values_are_still_allowed(example_copy):
    """예산의 max 와 꼭 같은 금액, 받을 수 있는 인원과 꼭 같은 인원은 후보에 남는다."""
    edit(persona_file(example_copy, "family-elders"), budget(typical=150000, max=150000))
    edit(venue_file(example_copy, "geumryong"), reservation(party_min=4, party_max=4))
    played = play(example_copy, pick_geumryong)
    request = played.requests[f"family-elders__{DINNER}"]
    assert [o.option_id for o in request.candidate("geumryong").options] == ["geumryong-o1"]  # 코스 B 는 예산을 넘는다
    assert played.visit("family-elders", DINNER)[0].paid == 600000
    assert played.violations() == []


def test_product_not_sold_at_that_meal_is_not_offered(example_copy):
    """운영 시간 밖 (상품): 저녁에만 파는 코스 B 는 점심의 주문에 없다. 그것을 고른 답은 실패다."""
    played = play(
        example_copy,
        lambda visit, request: answer(request, "geumryong", "geumryong-o2"),
        condition_ids=[LUNCH],
    )
    request = played.requests[f"family-elders__{LUNCH}"]
    assert [line.product_id for o in request.candidate("geumryong").options for line in o.lines] == ["course-a"]
    (row,) = played.rows
    assert row.status == "failed" and "geumryong-o2" in row.fail_reason
    assert played.violations() == []


def test_other_occasion_has_no_candidate_and_no_llm_call(example_copy):
    """다른 이용 상황: 식사만 하는 업장뿐이면 디저트 조건에는 후보가 없다. 엔진이 응답 없이 '이용하지 않음'으로 정한다."""
    played = play(example_copy, pick_geumryong, condition_ids=["dessert-weekend", "takeout-weekday"])
    assert played.requests == {}
    for row in played.rows:
        assert (row.choice_kind, row.status, row.reason_text) == ("none", "ok", NO_CANDIDATE_REASON)
        assert row.llm_call is None and row.request_hash is None and row.counted_share == 1
    assert played.record.llm.calls_replayed == 0
    assert played.violations() == []


def test_product_of_another_occasion_is_not_offered(example_copy):
    """다른 이용 상황 (상품): 식사와 포장을 함께 하는 업장이어도 식사 조건에 포장 상품은 나오지 않는다."""

    def add_takeout(d):
        d["occasions"].append("takeout")
        d["hours"].append({"meal": None, "day_type": "all", "open": "12:00", "last_order": None, "close": "22:00", "source_id": None})
        box = dict(product_of(d, "course-a"), product_id="gift-box", name="선물 상자", occasion="takeout", unit="개")
        box.update(slots=[{"meal": None, "day_type": "all"}], qty_rule="choice", qty_max=2, price=50000)
        d["products"].append(box)

    edit(venue_file(example_copy, "geumryong"), add_takeout)
    played = play(example_copy, lambda visit, request: answer(request, "geumryong", "geumryong-o1", [("gift-box", 1)]))
    candidate = played.requests[f"family-elders__{DINNER}"].candidate("geumryong")
    assert candidate.addons == []
    (row,) = played.rows
    assert row.status == "failed" and "gift-box" in row.fail_reason
    assert played.violations() == []


WRONG_ANSWERS = [
    ("없는 주문", lambda r: answer(r, "geumryong", "geumryong-o9")),
    ("다른 업장의 주문", lambda r: answer(r, "geumryong", "examplehotel-chinese-o1")),
    ("없는 추가 상품", lambda r: answer(r, "geumryong", "geumryong-o1", [("no-such-product", 1)])),
    ("후보에 없는 업장", lambda r: answer(r, "thebuffet", "thebuffet-o1")),
    ("주문 없이 업장만", lambda r: answer(r, "geumryong", None)),
]


@pytest.mark.parametrize("name, wrong", WRONG_ANSWERS, ids=[name for name, _ in WRONG_ANSWERS])
def test_answer_that_orders_something_missing_fails(example_copy, name, wrong):
    """없는 상품: 후보에 없는 것을 고른 답은 금액이 0 인 실패 줄 하나로 남는다."""
    played = play(
        example_copy, lambda visit, request: wrong(request), venue_ids=["geumryong", "examplehotel-chinese"]
    )
    (row,) = played.rows
    assert row.status == "failed" and row.fail_reason
    assert (row.choice_kind, row.venue_id, row.product_id, row.paid, row.revenue_net) == ("none", None, None, 0, 0)
    assert played.record.counts.model_dump() == {"visits": 1, "failed": 1}
    # 어긋난 답도 읽어 쓴 것이라 재생한 수에 센다. 실행 폴더에는 베껴 두지 않는다 (어디에 남길지는 T05 에서 정한다).
    assert (row.llm_call, played.record.llm.calls_replayed) == ("replay", 1)
    assert played.saved == {}
    assert played.violations() == []


def test_answer_saved_before_the_menu_changed_is_not_replayed(example_copy):
    """없는 상품: 답을 저장한 뒤 상품이 없어지면 요청이 달라져, 그 답은 재생되지 않는다."""
    first = play(example_copy, lambda visit, request: answer(request, "geumryong", "geumryong-o2"))
    assert first.visit("family-elders", DINNER)[0].product_id == "course-b"

    edit(
        venue_file(example_copy, "geumryong"),
        lambda d: d.update(products=[p for p in d["products"] if p["product_id"] != "course-b"]),
    )
    again = run(
        example_copy,
        data_mode="sample",
        now=NOW + timedelta(hours=1),
        provider=PROVIDER,
        model=MODEL,
        prompt_version="p1",
        answers=[first.run_dir / "llm"],
        persona_ids=["family-elders"],
        condition_ids=[DINNER],
        engine_commit="0000000",
    )
    (row,) = read_csv(again / "ledger.csv", LEDGER_COLUMNS)
    assert (row["status"], row["fail_reason"], row["product_id"]) == ("failed", NO_SAVED_ANSWER, "")


def test_amounts_are_recomputed_from_the_venue_definition(example_copy):
    """금액 불일치: 요청의 후보가 업장 정의와 다르면 다시 계산했을 때 걸린다."""
    request = requests_in(example_copy, ["family-elders"], [DINNER])[f"family-elders__{DINNER}"]
    response = first_option(request, "geumryong")
    venues = {v.venue_id: v for v in load_inputs(example_copy, "sample").venues.values()}
    assert amount_problems(request, response, venues) == []

    def tampered(change) -> ChoiceRequest:
        data = request.model_dump(mode="json")
        line = data["candidates"][0]["options"][0]["lines"][0]
        change(line)
        line["line_total"] = line["quantity"] * line["unit_price"] - line["discount"]
        data["candidates"][0]["options"][0]["total"] = line["line_total"]
        return ChoiceRequest.model_validate(data)

    assert "단가" in amount_problems(tampered(lambda line: line.update(unit_price=100000)), response, venues)[0]
    assert "수량" in amount_problems(tampered(lambda line: line.update(quantity=3)), response, venues)[0]
    assert "할인" in amount_problems(tampered(lambda line: line.update(discount=1000)), response, venues)[0]
    assert "파는 상품이 아니다" in amount_problems(tampered(lambda line: line.update(product_id="ghost")), response, venues)[0]


# ── 위반을 세는 쪽이 위반을 정말 알아보는가 ────────────────────────────
#
# `violations` 가 늘 빈 목록을 돌려주면 위의 "위반 0건"은 뜻이 없다. 어긴 것을 주면 종류마다, 한 건씩 잡는지 본다.


def audit(played: Played, *, venue=None, venue_id="geumryong", saved=None, personas=None, bundle=None, rows=None) -> list[str]:
    """고친 업장 정의·응답·페르소나·묶음·원장으로 위반을 세어, 종류만 차례로 돌려준다."""
    venues = dict(played.venues)
    if venue is not None:
        data = load_json(venue_file(played.root, venue_id))
        venue(data)
        venues[venue_id] = Venue.model_validate(data)
    found = violations(
        played.rows if rows is None else rows,
        venues,
        played.saved if saved is None else saved,
        played.personas if personas is None else personas,
        played.bundle if bundle is None else bundle,
    )
    return sorted(text.split(" — ")[1].split(":")[0] for text in found)


def with_condition(played: Played, **values) -> dict[str, SavedResponse]:
    """저장된 요청의 조건만 바꾼 것. 후보는 비운다 (예산을 줄이면 요청의 후보가 형식에 어긋나게 된다)."""
    changed = {}
    for key, entry in played.saved.items():
        data = entry.model_dump(mode="json")
        data["request"]["candidates"] = []
        data["request"]["condition"].update(values)
        data["response"]["choice"] = {"venue_id": None, "option_id": None, "addons": []}
        changed[key] = SavedResponse.model_validate(data)
    return changed


def with_persona(played: Played, change, persona_id="family-elders") -> dict[str, Persona]:
    data = load_json(persona_file(played.root, persona_id))
    change(data)
    return dict(played.personas, **{persona_id: Persona.model_validate(data)})


def with_budget(played: Played, **values) -> dict:
    """페르소나의 예산과 요청의 예산을 함께 바꾼다 (조건은 서로 맞고, 금액만 예산을 넘게 한다)."""
    personas = with_persona(played, budget(**values))
    return {"personas": personas, "saved": with_condition(played, budget=personas["family-elders"].budget.model_dump())}


def as_manual(played: Played, month: int) -> dict:
    """같은 방문을 화면에서 달을 직접 넣어 돌린 것으로 바꾼다 (묶음의 조건에는 달이 없다)."""
    rows = [
        row.model_copy(update={"condition_id": "manual-1", "visit_id": f"{row.persona_id}__manual-1"})
        for row in played.rows
    ]
    return {"rows": rows, "saved": with_condition(played, condition_id="manual-1", month=month)}


def without_products(*product_ids):
    return lambda d: d.update(products=[p for p in d["products"] if p["product_id"] not in product_ids])


def test_audit_reports_each_kind_of_violation(example_copy):
    played = play(example_copy, pick_geumryong)
    assert audit(played) == []

    assert audit(played, venue=remove_dinner_hours) == ["운영 시간 밖"]
    assert audit(played, venue=lambda d: product_of(d, "course-a").update(slots=[{"meal": "lunch", "day_type": "all"}])) == ["운영 시간 밖"]
    assert audit(played, venue=reservation(party_max=3)) == ["인원 초과"]
    assert audit(played, venue=reservation(party_min=5)) == ["예약 조건 위반"]
    assert audit(played, venue=without_products("course-a")) == ["없는 상품"]
    assert audit(played, venue=lambda d: product_of(d, "course-a").update(price=160000)) == ["금액 불일치"]
    assert audit(played, venue=lambda d: product_of(d, "course-a").update(unit="세트")) == ["금액 불일치"]
    assert audit(played, venue=lambda d: product_of(d, "course-a").update(serves=3, qty_rule="per_serves")) == ["금액 불일치"]
    assert audit(played, saved={}) == ["응답 없음"]
    assert audit(played, rows=[r.model_copy(update={"venue_id": "ondal"}) for r in played.rows]) == ["없는 업장"]

    # 다른 이용 상황: 업장에 그 이용 상황이 없는 것과, 상품이 다른 이용 상황의 것인 것을 따로 센다.
    dessert = audit(played, saved=with_condition(played, occasion="dessert", meal=None))
    assert dessert.count("다른 이용 상황의 업장") == 2 and dessert.count("운영 시간 밖") == 2

    def also_dessert(d):
        d["occasions"].append("dessert")
        d["hours"].append({"meal": None, "day_type": "all", "open": "12:00", "last_order": None, "close": "22:00", "source_id": None})

    dessert = audit(played, venue=also_dessert, saved=with_condition(played, occasion="dessert", meal=None))
    assert dessert.count("다른 이용 상황의 업장") == 1 and dessert.count("운영 시간 밖") == 1


def test_audit_checks_the_budget_against_everything_bought(example_copy):
    played = play(example_copy, pick_geumryong)  # 코스 A 4인, 600000원
    assert audit(played, **with_budget(played, typical=100000, max=149999)) == ["예산 초과"]
    assert audit(played, **with_budget(played, basis="party", typical=100000, max=599999)) == ["예산 초과"]
    assert audit(played, **with_budget(played, basis="party", typical=100000, max=600000)) == []


def test_audit_does_not_take_the_condition_from_the_request_alone(example_copy):
    """요청의 인원과 예산이 페르소나 정의와 다르면, 조건을 만드는 코드가 틀린 것이다. 그것도 위반으로 센다."""
    played = play(example_copy, pick_geumryong)
    # 예산의 한도도 페르소나 정의에서 낸다. 요청의 예산이 부풀어 있으면 조건도 다르고 예산도 넘은 것이다.
    assert audit(played, personas=with_persona(played, budget(typical=100000, max=140000))) == ["예산 초과", "조건 불일치"]
    assert audit(played, saved=with_condition(played, stay="guest")) == ["조건 불일치"]
    assert audit(played, saved=with_condition(played, month=5)) == ["조건 불일치"]  # 묶음의 조건에는 달이 없다
    assert audit(played, personas=with_persona(played, party(3))) == ["조건 불일치"]
    # 1인 기준 예산의 사람 수도 페르소나 정의에서 센다: 2명이면 440000원까지인데 600000원을 냈다.
    assert audit(played, personas=with_persona(played, party(2))) == ["예산 초과", "조건 불일치"]
    assert audit(played, personas={}) == ["조건 불일치"]
    assert audit(played, saved=with_condition(played, day_type="weekday")) == ["조건 불일치"]
    other = {key: entry.model_copy(update={"request": entry.request.model_copy(update={"persona": {"persona_id": "x"}})}) for key, entry in played.saved.items()}
    assert audit(played, saved=other) == ["조건 불일치"]


def test_audit_checks_the_month_when_the_condition_has_one(example_copy):
    played = play(example_copy, pick_geumryong)
    only_winter = lambda d: product_of(d, "course-a").update(months=[1, 2])  # noqa: E731
    assert audit(played, venue=only_winter, **as_manual(played, 1)) == []
    assert audit(played, venue=only_winter, **as_manual(played, 7)) == ["파는 달이 아님"]
    # 업장이 그 달에 영업하지 않으면 업장과 상품에서 한 건씩 나온다.
    assert audit(played, venue=lambda d: d.update(months=[1, 2]), **as_manual(played, 7)) == ["파는 달이 아님"] * 2


def test_audit_checks_the_share_of_a_seasonal_order(example_copy):
    edit(venue_file(example_copy, "geumryong"), lambda d: product_of(d, "course-a").update(months=[4, 5, 6]))
    played = play(example_copy, pick_geumryong)
    assert audit(played) == []
    assert audit(played, venue=lambda d: product_of(d, "course-a").update(months=[4, 5])) == ["몫 불일치"]
    assert audit(played, venue=lambda d: product_of(d, "course-a").update(months=None)) == ["몫 불일치"]
    assert audit(played, rows=[row for row in played.rows if row.choice_kind != "none"]) == ["몫 불일치"]
    # 고른 줄의 몫만 틀리고 "이용하지 않음" 줄은 맞는 원장
    wrong = [row.model_copy(update={"counted_share": 0.3}) if row.venue_id else row for row in played.rows]
    assert audit(played, rows=wrong) == ["몫 불일치"]


def test_audit_checks_that_everyone_has_a_share_of_the_order(example_copy):
    played = play(example_copy, lambda visit, request: first_option(request, "thebuffet"), persona_ids=["family-kids"])
    assert audit(played) == []
    assert audit(played, rows=[row for row in played.rows if row.product_id != "dinner-child"]) == ["인원 초과"]


def add_tea(d: dict) -> None:
    """금룡에 추가 상품(차, 10000원, 4잔까지)을 더한다."""
    tea = dict(product_of(d, "course-a"), product_id="tea", name="차", unit="잔")
    tea.update(qty_rule="choice", qty_max=4, price=10000)
    d["products"].append(tea)


def with_tea(quantity: int):
    return lambda visit, request: answer(request, "geumryong", "geumryong-o1", [("tea", quantity)])


def test_audit_checks_added_products(example_copy):
    edit(venue_file(example_copy, "geumryong"), add_tea)
    played = play(example_copy, with_tea(3))  # 코스 A 600000원 + 차 30000원
    assert audit(played) == []
    assert audit(played, venue=lambda d: product_of(d, "tea").update(qty_max=2)) == ["수량 초과"]
    assert audit(played, venue=lambda d: product_of(d, "tea").update(months=[12])) == ["몫 불일치"]
    assert audit(played, **with_budget(played, basis="party", typical=500000, max=629999)) == ["예산 초과"]
    assert audit(played, **with_budget(played, basis="party", typical=500000, max=630000)) == []


# ── 원장 ────────────────────────────────────────────────────────────────


def mixed(visit_id: str, request: ChoiceRequest) -> ChoiceResponse | None:
    """방문마다 다른 것을 고른다: 워커힐, 경쟁 업장, 이용하지 않음, 그리고 답이 없는 방문 하나."""
    persona_id, condition_id = visit_id.split("__")
    if persona_id == "family-kids":
        if condition_id == LUNCH:
            return None  # 답을 두지 않는다. 실패한 방문이 된다
        return first_option(request, "thebuffet")
    if condition_id == DINNER:
        return first_option(request, "examplehotel-chinese")
    if condition_id == LUNCH:
        return answer(request, None)
    return first_option(request, "geumryong")


MIXED = dict(
    persona_ids=["family-elders", "family-kids"],
    condition_ids=["meal-lunch-weekday", LUNCH, "meal-dinner-weekday", DINNER],
)


def test_ledger_has_the_promised_columns_and_every_visit(example_copy):
    played = play(example_copy, mixed, **MIXED)
    header = (played.run_dir / "ledger.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert header.split(",") == LEDGER_COLUMNS
    assert {row.visit_id for row in played.rows} == {f"{p}__{c}" for p in MIXED["persona_ids"] for c in MIXED["condition_ids"]}
    assert played.record.counts.model_dump() == {"visits": 8, "failed": 1}
    assert played.record.llm.calls_replayed == 7 and played.record.status == "ok"
    assert played.violations() == []


def test_competitor_and_not_using_are_rows_without_walkerhill_revenue(example_copy):
    played = play(example_copy, mixed, **MIXED)

    (away,) = played.visit("family-elders", DINNER)
    assert (away.choice_kind, away.venue_id, away.paid, away.revenue_net, away.weighted_revenue) == (
        "competitor",
        "examplehotel-chinese",
        560000,
        0,
        0,
    )
    assert away.request_hash in played.saved and away.reason_text

    (none,) = played.visit("family-elders", LUNCH)
    assert (none.choice_kind, none.venue_id, none.product_id, none.paid, none.revenue_net) == ("none", None, None, 0, 0)
    assert none.reason_labels and none.request_hash in played.saved

    (failed,) = played.visit("family-kids", LUNCH)
    assert (failed.status, failed.fail_reason, failed.choice_kind, failed.paid) == ("failed", NO_SAVED_ANSWER, "none", 0)


def test_totals_agree_whichever_way_they_are_added(example_copy):
    played = play(example_copy, mixed, **MIXED)
    sums = totals(played.rows)

    for key in ("paid", "revenue_net", "weighted_revenue"):
        by_persona = sum(values[key] for values in sums["by_persona"].values())
        by_venue = sum(values[key] for values in sums["by_venue"].values())
        assert by_persona == by_venue == sums["total"][key] > 0

    ok = [row for row in played.rows if row.status == "ok"]
    assert sums["total"]["paid"] == sum(row.paid for row in ok)
    # 워커힐 매출은 워커힐 업장의 줄에서만 나온다. 세금을 뺀 값은 줄마다 낸 금액 ÷ 1.1 이다.
    assert sums["by_venue"]["examplehotel-chinese"]["revenue_net"] == 0
    assert sums["by_venue"][None] == {"paid": 0, "revenue_net": 0, "weighted_revenue": 0}
    walkerhill = [row for row in ok if row.choice_kind == "walkerhill"]
    assert sums["total"]["revenue_net"] == sum(net_of_tax(row.paid) for row in walkerhill)
    for row in walkerhill:
        assert row.weighted_revenue == round_half_up(weighted_amount(row.revenue_net, row.represented, row.counted_share))


def test_failed_visit_is_left_out_of_totals(example_copy):
    played = play(example_copy, lambda visit, request: None)
    (row,) = played.rows
    assert row.status == "failed"
    assert totals(played.rows) == {
        "total": {"paid": 0, "revenue_net": 0, "weighted_revenue": 0},
        "by_persona": {},
        "by_venue": {},
    }


def test_engine_output_passes_the_format_check(example_copy):
    """LLM 없이 정해 둔 답으로 끝까지 돌린 결과가 형식 검사(원장과 저장된 응답의 대조까지)를 통과한다."""
    played = play(example_copy, mixed, **MIXED)
    assert (played.run_dir / "run.json").is_file() and len(played.saved) == 7
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_same_answers_give_the_same_ledger(example_copy):
    first = play(example_copy, mixed, **MIXED)
    again = run(
        example_copy,
        data_mode="sample",
        now=NOW + timedelta(hours=1),
        provider=PROVIDER,
        model=MODEL,
        prompt_version="p1",
        answers=[first.run_dir / "llm"],
        engine_commit="0000000",
        **MIXED,
    )
    old = (first.run_dir / "ledger.csv").read_text(encoding="utf-8-sig").replace(first.run_dir.name, "RUN")
    new = (again / "ledger.csv").read_text(encoding="utf-8-sig").replace(again.name, "RUN")
    assert old == new


# ── 일부 달에만 파는 상품 ───────────────────────────────────────────────


def test_seasonal_product_is_counted_by_its_share(example_copy):
    edit(venue_file(example_copy, "geumryong"), lambda d: product_of(d, "course-a").update(months=[4, 5, 6]))
    played = play(example_copy, pick_geumryong)
    bought, gap = played.visit("family-elders", DINNER)
    assert (bought.product_id, bought.counted_share) == ("course-a", 0.25)
    assert bought.weighted_revenue == round_half_up(weighted_amount(bought.revenue_net, bought.represented, 0.25)) > 0
    assert (gap.choice_kind, gap.counted_share, gap.reason_text, gap.paid) == ("none", 0.75, SEASON_GAP_REASON, 0)
    assert gap.request_hash == bought.request_hash
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_condition_with_a_month_drops_what_is_not_sold_then():
    inputs = load_inputs(EXAMPLE_ROOT, "sample")
    data = load_json(venue_file(EXAMPLE_ROOT, "geumryong"))
    product_of(data, "course-a")["months"] = [12, 1, 2]
    venue = Venue.model_validate(data)
    persona = inputs.personas["family-elders"]
    july = run_condition(inputs.conditions.condition(DINNER), persona).model_copy(update={"month": 7})
    january = july.model_copy(update={"month": 1})

    def products(condition):
        candidate, _ = candidate_for(venue, condition)
        return [line.product_id for option in candidate.options for line in option.lines]

    assert products(july) == ["course-b"]
    assert products(january) == ["course-a", "course-b"]
    closed = Venue.model_validate(dict(load_json(venue_file(EXAMPLE_ROOT, "geumryong")), months=[1, 2]))
    assert candidate_for(closed, july) == (None, [])


# ── 포장·구매: 주문 없이 추가 상품만 고른다 ─────────────────────────────


def make_takeout(root: Path) -> None:
    """금룡에 포장 상품 둘을 더한다 (지어낸 값)."""

    def change(d):
        d["occasions"].append("takeout")
        d["hours"].append({"meal": None, "day_type": "all", "open": "12:00", "last_order": None, "close": "22:00", "source_id": None})
        for product_id, name, price in (("gift-box", "선물 상자", 50000), ("tea-tin", "차 한 통", 30000)):
            box = dict(product_of(d, "course-a"), product_id=product_id, name=name, occasion="takeout", unit="개")
            box.update(slots=[{"meal": None, "day_type": "all"}], qty_rule="choice", qty_max=3, price=price)
            d["products"].append(box)

    edit(venue_file(root, "geumryong"), change)
    edit(persona_file(root, "family-elders"), budget(basis="party", typical=100000, max=150000))


TAKEOUT = "takeout-weekend"


def test_takeout_venue_is_a_candidate_with_addons_only(example_copy):
    make_takeout(example_copy)
    played = play(
        example_copy,
        lambda visit, request: answer(request, "geumryong", None, [("gift-box", 2), ("tea-tin", 1), ]),
        condition_ids=[TAKEOUT],
    )
    candidate = played.requests[f"family-elders__{TAKEOUT}"].candidate("geumryong")
    assert candidate.options == [] and [a.product_id for a in candidate.addons] == ["gift-box", "tea-tin"]

    rows = played.visit("family-elders", TAKEOUT)
    assert [(r.product_id, r.quantity, r.list_price, r.discount, r.paid) for r in rows] == [
        ("gift-box", 2, 50000, 0, 100000),
        ("tea-tin", 1, 30000, 0, 30000),
    ]
    assert all(r.choice_kind == "walkerhill" and r.revenue_net == net_of_tax(r.paid) for r in rows)
    assert played.violations() == []
    assert [str(p) for p in check(example_copy, strict=True)] == []


@pytest.mark.parametrize(
    "addons, option_id, reason",
    [
        ([("gift-box", 3), ("tea-tin", 1)], None, "예산의 max 를 넘는다"),
        ([("gift-box", 3), ("tea-tin", 0)], None, None),  # 꼭 max 만큼은 된다
        ([], None, "산 추가 상품이 없다"),
        ([("gift-box", 0)], None, "산 추가 상품이 없다"),
        ([("gift-box", 1)], "geumryong-o1", "주문이 없는데 option_id 가 있다"),
        ([("gift-box", 4)], None, "qty_max"),
    ],
)
def test_takeout_answers_that_break_the_rules_fail(example_copy, addons, option_id, reason):
    make_takeout(example_copy)
    played = play(
        example_copy, lambda visit, request: answer(request, "geumryong", option_id, addons), condition_ids=[TAKEOUT]
    )
    (row,) = played.rows
    if reason is None:
        assert (row.status, row.paid) == ("ok", 150000)
    else:
        assert row.status == "failed" and reason in row.fail_reason
    assert played.violations() == []


def test_takeout_product_over_the_budget_is_not_offered(example_copy):
    make_takeout(example_copy)
    edit(persona_file(example_copy, "family-elders"), budget(basis="party", typical=30000, max=40000))
    request = requests_in(example_copy, ["family-elders"], [TAKEOUT])[f"family-elders__{TAKEOUT}"]
    assert [a.product_id for a in request.candidate("geumryong").addons] == ["tea-tin"]
    edit(persona_file(example_copy, "family-elders"), budget(basis="party", typical=20000, max=20000))
    assert requests_in(example_copy, ["family-elders"], [TAKEOUT]) == {}


def test_drinks_alone_do_not_make_a_meal_candidate(example_copy):
    """식사 업장은 주문이 남지 않으면 후보에서 빠진다. 추가 상품만 사는 곳이 되지 않는다."""

    def add_drink(d):
        drink = dict(product_of(d, "course-a"), product_id="tea", name="차", unit="잔")
        drink.update(qty_rule="choice", qty_max=4, price=10000)
        d["products"].append(drink)

    edit(venue_file(example_copy, "geumryong"), add_drink)
    request = requests_in(example_copy, ["family-elders"], [DINNER])[f"family-elders__{DINNER}"]
    assert [a.product_id for a in request.candidate("geumryong").addons] == ["tea"]

    edit(persona_file(example_copy, "family-elders"), budget(typical=100000, max=145000))
    assert "geumryong" not in candidate_ids(requests_in(example_copy, ["family-elders"], [DINNER]))


def test_addon_is_added_to_the_order_on_its_own_row(example_copy):
    def add_drink(d):
        drink = dict(product_of(d, "course-a"), product_id="tea", name="차", unit="잔")
        drink.update(qty_rule="choice", qty_max=4, price=10000)
        d["products"].append(drink)

    edit(venue_file(example_copy, "geumryong"), add_drink)
    played = play(example_copy, lambda visit, request: answer(request, "geumryong", "geumryong-o1", [("tea", 3)]))
    rows = played.visit("family-elders", DINNER)
    assert [(r.product_id, r.quantity, r.paid, r.discount) for r in rows] == [("course-a", 4, 600000, 0), ("tea", 3, 30000, 0)]
    assert played.violations() == []
    assert [str(p) for p in check(example_copy, strict=True)] == []


# ── 후보에 넣는 경쟁 업장 ───────────────────────────────────────────────


def test_candidates_are_our_venues_and_their_competitors():
    inputs = load_inputs(EXAMPLE_ROOT, "sample")
    condition = run_condition(inputs.conditions.condition(DINNER), inputs.personas["family-elders"])
    venues = list(inputs.venues.values())
    found, _ = candidates_for(venues, condition)
    assert [c.venue_id for c in found] == ["geumryong", "thebuffet", "examplehotel-buffet", "examplehotel-chinese"]
    # 견주는 워커힐 업장이 이번 실행에 없으면 그 경쟁 업장은 보지 않는다.
    found, _ = candidates_for([v for v in venues if v.venue_id != "thebuffet"], condition)
    assert [c.venue_id for c in found] == ["geumryong", "examplehotel-chinese"]


# ── 아직 넣지 않은 것은 조용히 지나가지 않는다 ─────────────────────────


def test_scenario_with_changes_is_refused_for_now(example_copy):
    with pytest.raises(NotSupportedYet, match="T10"):
        run(
            example_copy,
            data_mode="sample",
            now=NOW,
            provider=PROVIDER,
            model=MODEL,
            prompt_version="p1",
            answers=[],
            scenario_id="competitor-chinese-discount",
        )


def test_venue_with_a_promotion_is_refused_for_now(example_copy):
    promotion = load_json(example_copy / "scenarios" / "competitor-chinese-discount.json")["changes"][0]["promotion"]
    edit(venue_file(example_copy, "examplehotel-chinese"), lambda d: d["promotions"].append(promotion))
    with pytest.raises(NotSupportedYet, match="examplehotel-chinese"):
        run(example_copy, data_mode="sample", now=NOW, provider=PROVIDER, model=MODEL, prompt_version="p1", answers=[])


# ── 읽는 곳과 쓰는 곳 ───────────────────────────────────────────────────


def test_sample_run_does_not_read_the_private_folder(example_copy):
    private = example_copy / "private" / "personas"
    private.mkdir(parents=True)
    (private / "family-elders.json").write_text("읽으면 오류가 나는 파일", encoding="utf-8")
    played = play(example_copy, pick_geumryong)
    assert played.run_dir.parent == example_copy / "engine" / "samples" / "runs"
    assert "overridden_by_private" not in played.requests[f"family-elders__{DINNER}"].persona
    assert not (example_copy / "private" / "runs").exists()


def test_private_run_merges_the_private_layer_and_writes_under_private(example_copy, doc):
    save_json(example_copy / "private" / "personas" / "family-elders.json", doc.persona_private)
    inputs = load_inputs(example_copy, "private", persona_ids=["family-elders"])
    assert inputs.persona_json["family-elders"]["overridden_by_private"] == ["evidence.preferences.refs"]

    run_dir = run(
        example_copy,
        data_mode="private",
        now=NOW,
        provider=PROVIDER,
        model=MODEL,
        prompt_version="p1",
        answers=[],
        persona_ids=["family-elders"],
        condition_ids=[DINNER],
        engine_commit="0000000",
    )
    assert run_dir.parent == example_copy / "private" / "runs"
    assert load_json(run_dir / "run.json")["data_mode"] == "private"


# ── 저장소의 실제 업장 정의 ─────────────────────────────────────────────


def test_every_real_venue_file_gives_valid_requests():
    """저장소의 업장 정의 16개로 조건마다 요청을 만들어 본다. 형식에 맞고, 예산을 넘는 주문이 없어야 한다."""
    venues = [read_model(p, Venue) for p in sorted((REPO_ROOT / "data" / "venues").glob("*.json"))]
    vocab = read_model(REPO_ROOT / "data" / "evidence" / "vocab.json", Vocab)
    bundle = read_model(REPO_ROOT / "engine" / "conditions.json", ConditionBundle)
    assert len(bundle.conditions) == 8 and bundle.assumed_splits[0].parts == {"lunch": 0.5, "dinner": 0.5}

    seen: set[str] = set()
    addons_only: set[str] = set()
    for persona_id in ("family-elders", "family-kids"):
        raw = load_json(persona_file(EXAMPLE_ROOT, persona_id))
        persona = Persona.model_validate(raw)
        for condition in bundle.conditions:
            visit = run_condition(condition, persona)
            request, _ = build_request(
                prompt_version="p1", scenario_id="baseline", persona=raw, condition=visit, venues=venues, vocab=vocab
            )
            if request is None:
                continue
            ChoiceRequest.model_validate_json(request.model_dump_json(), strict=True)
            by_id = {v.venue_id: v for v in venues}
            for candidate in request.candidates:
                seen.add(candidate.venue_id)
                assert condition.occasion in by_id[candidate.venue_id].occasions
                assert all(option.total <= visit.budget_limit() for option in candidate.options)
                if not candidate.options:
                    addons_only.add(candidate.venue_id)
    assert {"pizzahill", "parnas-mercato521", "josun-deli"} <= seen
    # 포장·구매 조건에서는 주문 없이 추가 상품만 고르는 후보가 나온다.
    assert {"pizzahill", "josun-deli"} <= addons_only


# ── 형식: 주문이 없는 후보 (docs/FORMATS.md 9절) ────────────────────────


def takeout_request(root: Path) -> dict:
    make_takeout(root)
    request = requests_in(root, ["family-elders"], [TAKEOUT])[f"family-elders__{TAKEOUT}"]
    return request.model_dump(mode="json")


def test_candidate_needs_an_order_or_an_addon(example_copy):
    data = takeout_request(example_copy)
    data["candidates"][0]["addons"] = []
    with pytest.raises(ValueError, match="고를 주문도 추가 상품도 없다"):
        ChoiceRequest.model_validate(data)


def test_request_cannot_offer_a_takeout_product_over_budget(example_copy):
    data = takeout_request(example_copy)
    data["candidates"][0]["addons"][0]["unit_price"] = 150001
    with pytest.raises(ValueError, match="하나만 사도 예산의 max 를 넘는다"):
        ChoiceRequest.model_validate(data)
    data["candidates"][0]["addons"][0]["unit_price"] = 150000
    ChoiceRequest.model_validate(data)


def test_option_without_a_venue_is_not_a_choice():
    with pytest.raises(ValueError, match="venue_id 가 null 인데 option_id 가 있다"):
        ChoiceResponse.model_validate(
            {
                "choice": {"venue_id": None, "option_id": "geumryong-o1", "addons": []},
                "reason_labels": ["가격"],
                "reason_text": "x",
                "used_attributes": [],
                "rejected": [],
            }
        )


@pytest.mark.parametrize(
    "column, value",
    [("quantity", "1"), ("list_price", "40000"), ("product_id", "tea-tin"), ("unit", "판")],
)
def test_format_check_compares_takeout_rows_with_the_saved_answer(example_copy, column, value):
    """주문 없이 추가 상품만 고른 방문도 원장을 손으로 고치면 형식 검사가 잡는다."""
    make_takeout(example_copy)
    played = play(
        example_copy, lambda visit, request: answer(request, "geumryong", None, [("gift-box", 2)]), condition_ids=[TAKEOUT]
    )
    assert check(example_copy, strict=True) == []

    path = played.run_dir / "ledger.csv"
    (row,) = read_csv(path, LEDGER_COLUMNS)
    row[column] = value
    row["paid"] = str(int(row["quantity"]) * int(row["list_price"]))
    row["revenue_net"] = str(net_of_tax(int(row["paid"])))
    row["weighted_revenue"] = str(round(int(row["revenue_net"]) * float(row["represented"])))
    save_csv(path, [row])
    assert any("저장된 응답에서 고른 주문과 다르다" in str(p) for p in check(example_copy, strict=True))


# ── 예산은 산 것 전부와 견준다 ──────────────────────────────────────────


def test_added_products_count_toward_the_budget(example_copy):
    """주문에 추가 상품을 더한 금액이 예산의 max 를 넘는 답은 실패다. 꼭 max 만큼은 된다."""
    edit(venue_file(example_copy, "geumryong"), add_tea)
    edit(persona_file(example_copy, "family-elders"), budget(basis="party", typical=500000, max=620000))

    over = play(example_copy, with_tea(3))
    (row,) = over.rows
    assert row.status == "failed" and "예산의 max 를 넘는다" in row.fail_reason
    assert over.violations() == []

    exact = play(example_copy, with_tea(2), now=NOW + timedelta(hours=1))
    assert [(r.product_id, r.paid) for r in exact.rows] == [("course-a", 600000), ("tea", 20000)]
    assert exact.violations() == []


def test_added_product_nobody_could_afford_is_not_offered(example_copy):
    edit(venue_file(example_copy, "geumryong"), add_tea)
    edit(persona_file(example_copy, "family-elders"), budget(basis="party", typical=500000, max=609999))
    candidate = requests_in(example_copy, ["family-elders"], [DINNER])[f"family-elders__{DINNER}"].candidate("geumryong")
    assert [o.option_id for o in candidate.options] == ["geumryong-o1"] and candidate.addons == []

    edit(persona_file(example_copy, "family-elders"), budget(basis="party", typical=500000, max=610000))
    candidate = requests_in(example_copy, ["family-elders"], [DINNER])[f"family-elders__{DINNER}"].candidate("geumryong")
    assert [a.product_id for a in candidate.addons] == ["tea"]


def test_added_product_bought_zero_times_leaves_no_row(example_copy):
    edit(venue_file(example_copy, "geumryong"), add_tea)
    played = play(example_copy, with_tea(0))
    assert [(r.product_id, r.status) for r in played.rows] == [("course-a", "ok")]


# ── 일부 달에만 파는 것과 추가 상품, 성인·어린이 짝 ─────────────────────


def test_seasonal_added_product_is_not_offered_with_a_year_round_order(example_copy):
    """일 년 내내 파는 주문에 12월에만 파는 음료를 더하면 음료가 일 년 내내 팔린 것으로 세어진다. 그래서 넣지 않는다."""
    edit(venue_file(example_copy, "geumryong"), add_tea)
    request = requests_in(example_copy, ["family-elders"], [DINNER])[f"family-elders__{DINNER}"]
    response = with_tea(1)("", request)
    year_round = load_inputs(example_copy, "sample").venues
    assert amount_problems(request, response, year_round) == []

    edit(venue_file(example_copy, "geumryong"), lambda d: product_of(d, "tea").update(months=[12]))
    seasonal = load_inputs(example_copy, "sample").venues
    assert requests_in(example_copy, ["family-elders"], [DINNER])[f"family-elders__{DINNER}"].candidate("geumryong").addons == []
    # 추가 상품은 후보에 하나의 목록이다. 12월에만 파는 주문이 있어도 일 년 내내 파는 주문이 함께 있으면 넣지 않는다.
    edit(venue_file(example_copy, "geumryong"), lambda d: product_of(d, "course-a").update(months=[12]))
    assert requests_in(example_copy, ["family-elders"], [DINNER])[f"family-elders__{DINNER}"].candidate("geumryong").addons == []
    # 요청을 만든 뒤 업장 정의가 바뀌었더라도, 다시 계산할 때 걸린다.
    assert any("팔지 않는 달" in problem for problem in amount_problems(request, response, seasonal))

    # 주문도 같은 달에만 팔면 함께 낼 수 있다. 조건에 12월을 넣어도 그렇다.
    edit(venue_file(example_copy, "geumryong"), lambda d: [p.update(months=[12]) for p in d["products"]])
    assert [a.product_id for a in requests_in(example_copy, ["family-elders"], [DINNER])[f"family-elders__{DINNER}"].candidate("geumryong").addons] == ["tea"]
    inputs = load_inputs(example_copy, "sample")
    december = run_condition(inputs.conditions.condition(DINNER), inputs.personas["family-elders"]).model_copy(update={"month": 12})
    candidate, _ = candidate_for(seasonal["geumryong"], december)
    assert [a.product_id for a in candidate.addons] == ["tea"]
    # 조건에 달이 있으면 그 달의 방문이라, 다시 계산할 때도 파는 달이 다른 것을 문제 삼지 않는다.
    request, _ = build_request(
        prompt_version="p1",
        scenario_id="baseline",
        persona=inputs.persona_json["family-elders"],
        condition=december,
        venues=list(seasonal.values()),
        vocab=inputs.vocab,
    )
    assert amount_problems(request, with_tea(1)("", request), seasonal) == []


def kids_condition(root: Path, month: int | None):
    inputs = load_inputs(root, "sample")
    condition = run_condition(inputs.conditions.condition(DINNER), inputs.personas["family-kids"])
    return inputs.venues["thebuffet"], condition.model_copy(update={"month": month})


def test_adult_and_child_prices_pair_only_when_sold_in_the_same_months(example_copy):
    edit(venue_file(example_copy, "thebuffet"), lambda d: product_of(d, "dinner-child").update(months=[1, 2, 3, 4, 5, 6]))
    # 조건에 달이 없으면 방문의 몫이 하나여야 해서, 파는 달이 다른 성인·어린이 가격은 한 주문이 되지 못한다.
    assert candidate_for(*kids_condition(example_copy, None))[0] is None
    # 조건에 달이 있으면 그 달에 파는 것끼리 짝짓는다.
    candidate, _ = candidate_for(*kids_condition(example_copy, 3))
    assert [[line.product_id for line in o.lines] for o in candidate.options] == [["dinner-adult", "dinner-child"]]
    assert candidate_for(*kids_condition(example_copy, 9))[0] is None  # 9월에는 어린이 가격이 없다


def test_venue_whose_orders_have_no_price_does_not_turn_into_an_addons_only_venue(example_copy):
    """주문이 될 상품의 가격이 모두 비어 있다고 해서 음료만 파는 후보가 되지는 않는다."""

    def change(d):
        add_tea(d)
        for product in d["products"]:
            if product["product_id"] != "tea":
                product.update(price=None, grade="unknown")

    edit(venue_file(example_copy, "geumryong"), change)
    inputs = load_inputs(example_copy, "sample")
    condition = run_condition(inputs.conditions.condition(DINNER), inputs.personas["family-elders"])
    assert candidate_for(inputs.venues["geumryong"], condition) == (None, ["geumryong:course-a", "geumryong:course-b"])


def test_takeout_products_sold_in_different_months_cannot_be_bought_together(example_copy):
    make_takeout(example_copy)
    edit(
        venue_file(example_copy, "geumryong"),
        lambda d: (product_of(d, "gift-box").update(months=[1]), product_of(d, "tea-tin").update(months=[2])),
    )
    both = play(example_copy, lambda v, r: answer(r, "geumryong", None, [("gift-box", 1), ("tea-tin", 1)]), condition_ids=[TAKEOUT])
    (row,) = both.rows
    assert row.status == "failed" and "함께 파는 달이 없다" in row.fail_reason

    one = play(
        example_copy, lambda v, r: answer(r, "geumryong", None, [("gift-box", 1)]), condition_ids=[TAKEOUT], now=NOW + timedelta(hours=1)
    )
    bought, gap = one.rows
    assert bought.counted_share == pytest.approx(1 / 12) and gap.counted_share == pytest.approx(11 / 12)
    assert one.violations() == []


def test_visit_with_a_month_is_counted_whole(example_copy):
    """조건에 달을 넣어 돌린 방문(화면에서 직접 넣은 조건)은 몫이 1 이고 '파는 달이 아님' 줄이 없다."""
    edit(venue_file(example_copy, "geumryong"), lambda d: product_of(d, "course-a").update(months=[4, 5, 6]))
    inputs = load_inputs(example_copy, "sample", persona_ids=["family-elders"])
    persona = inputs.personas["family-elders"]
    answers = example_copy.parent / "manual-answers"
    book = AnswerBook([answers], PROVIDER, MODEL)

    def visit(month: int):
        condition = run_condition(inputs.conditions.condition(DINNER), persona).model_copy(
            update={"condition_id": f"manual-{month}", "month": month}
        )
        request, _ = build_request(
            prompt_version="p1",
            scenario_id="baseline",
            persona=inputs.persona_json[persona.persona_id],
            condition=condition,
            venues=list(inputs.venues.values()),
            vocab=inputs.vocab,
        )
        option = request.candidate("geumryong").options[0]
        save_answer(answers, PROVIDER, MODEL, request, answer(request, "geumryong", option.option_id), NOW)
        return run_visit(
            run_id="20261118-090000-baseline",
            inputs=inputs,
            persona=persona,
            condition=condition,
            represented=0.0,
            prompt_version="p1",
            book=book,
        ).rows

    (may,) = visit(5)
    assert (may.product_id, may.counted_share, may.status) == ("course-a", 1.0, "ok")
    (july,) = visit(7)
    assert (july.product_id, july.counted_share) == ("course-b", 1.0)  # 7월에는 코스 A 를 팔지 않는다


# ── 다시 계산하는 검사가 요청을 믿지 않는가 ────────────────────────────


def test_recomputing_does_not_trust_the_request(example_copy):
    edit(venue_file(example_copy, "geumryong"), add_tea)
    request = requests_in(example_copy, ["family-elders"], [DINNER])[f"family-elders__{DINNER}"]
    venues = load_inputs(example_copy, "sample").venues
    data = request.model_dump(mode="json")
    geumryong = data["candidates"][0]

    # 수량을 고객이 정하는 상품을 주문의 줄에 넣은 요청
    line = geumryong["options"][0]["lines"][0]
    line.update(product_id="tea", unit_price=10000, line_total=40000)
    geumryong["options"][0]["total"] = 40000
    found = amount_problems(ChoiceRequest.model_validate(data), first_option(request, "geumryong"), venues)
    assert any("주문의 줄에 넣을 수 없다" in problem for problem in found)

    # 추가 상품을 업장 정의보다 많이 살 수 있다고 적은 요청
    data = request.model_dump(mode="json")
    data["candidates"][0]["addons"][0]["qty_max"] = 9
    loose = ChoiceRequest.model_validate(data)
    found = amount_problems(loose, with_tea(5)("", loose), venues)
    assert any("업장 정의의 qty_max 를 넘는다" in problem for problem in found)


# ── 저장된 응답을 읽는 곳 ───────────────────────────────────────────────


def replay_after(example_copy, damage) -> tuple[dict, dict]:
    """정해 둔 답을 써 둔 뒤 그 파일을 `damage` 로 고치고 돌린다. (원장의 줄, 실행 기록)을 돌려준다."""
    answers = example_copy.parent / "damaged"
    request = requests_in(example_copy, ["family-elders"], [DINNER])[f"family-elders__{DINNER}"]
    request_hash = save_answer(answers, PROVIDER, MODEL, request, first_option(request, "geumryong"), NOW)
    damage(answers / f"{request_hash}.json")
    run_dir = run(
        example_copy,
        data_mode="sample",
        now=NOW,
        provider=PROVIDER,
        model=MODEL,
        prompt_version="p1",
        answers=[answers],
        persona_ids=["family-elders"],
        condition_ids=[DINNER],
        engine_commit="0000000",
    )
    (row,) = read_csv(run_dir / "ledger.csv", LEDGER_COLUMNS)
    return row, load_json(run_dir / "run.json")


def test_saved_answer_with_an_edited_request_is_not_used(example_copy):
    """요청을 손으로 고친 저장 응답은 파일 이름의 해시와 맞지 않는다. 그 답으로는 원장을 만들지 않는다."""
    row, record = replay_after(example_copy, lambda path: edit(path, lambda d: d["request"].update(prompt_version="p9")))
    assert (row["status"], row["paid"], row["venue_id"]) == ("failed", "0", "")
    assert "해시와 맞지 않는다" in row["fail_reason"]
    assert record["counts"] == {"visits": 1, "failed": 1} and record["llm"]["calls_replayed"] == 1


def test_saved_answer_whose_own_hash_was_edited_is_not_used(example_copy):
    row, _ = replay_after(example_copy, lambda path: edit(path, lambda d: d.update(request_hash="0" * 16)))
    assert row["status"] == "failed" and "해시와 맞지 않는다" in row["fail_reason"]


def test_saved_answer_that_cannot_be_read_fails_the_visit(example_copy):
    row, _ = replay_after(example_copy, lambda path: path.write_text("{", encoding="utf-8"))
    assert row["status"] == "failed" and "읽을 수 없다" in row["fail_reason"]


def test_sample_run_refuses_answers_kept_under_private(example_copy):
    with pytest.raises(ValueError, match="private/ 아래의 저장된 응답을 쓰지 않는다"):
        run(
            example_copy,
            data_mode="sample",
            now=NOW,
            provider=PROVIDER,
            model=MODEL,
            prompt_version="p1",
            answers=[example_copy / "private" / "runs" / "x" / "llm"],
        )


def test_run_record_hashes_every_input_the_request_depends_on(example_copy):
    first = play(example_copy, pick_geumryong)
    assert set(first.record.inputs) == {"venues", "personas", "conditions", "scenario", "vocab"}
    edit(example_copy / "data" / "evidence" / "vocab.json", lambda d: d["pain_points"].append("새 라벨"))
    again = play(example_copy, pick_geumryong, now=NOW + timedelta(hours=1))
    assert again.record.inputs["vocab"] != first.record.inputs["vocab"]
    assert again.record.inputs["venues"] == first.record.inputs["venues"]


def test_audit_checks_the_budget_of_a_visit_that_bought_added_products_only(example_copy):
    make_takeout(example_copy)  # 일행 기준 예산의 max 는 150000원
    played = play(
        example_copy, lambda v, r: answer(r, "geumryong", None, [("gift-box", 2), ("tea-tin", 1)]), condition_ids=[TAKEOUT]
    )
    assert audit(played) == []
    assert audit(played, **with_budget(played, basis="party", typical=100000, max=129999)) == ["예산 초과"]
    assert audit(played, **with_budget(played, basis="party", typical=100000, max=130000)) == []


# ── 가중 매출의 반올림 ──────────────────────────────────────────────────


def test_weighted_revenue_that_ends_in_a_half_is_rounded_up_and_accepted(example_copy):
    """대표하는 크기 0.0875 × 매출 11000원 = 962.5원. 소수로 곱하면 962.4999… 가 되어 반올림이 갈리는 값이다.

    원장을 만드는 쪽과 원장을 검사하는 쪽이 다르게 계산하면 이 값에서 실행이 멈춘다 (재검토에서 나온 것).
    """
    edit(persona_file(example_copy, "family-elders"), lambda d: d["share_in_group"].update(value=0.7))
    edit(persona_file(example_copy, "family-kids"), lambda d: d["share_in_group"].update(value=0.3))
    edit(venue_file(example_copy, "geumryong"), lambda d: product_of(d, "course-a").update(price=3025))
    eight = [c.condition_id for c in read_model(example_copy / "engine" / "conditions.json", ConditionBundle).conditions]
    played = play(example_copy, pick_geumryong, condition_ids=eight)
    (row,) = played.visit("family-elders", DINNER)
    assert (row.paid, row.revenue_net, row.represented, row.weighted_revenue) == (12100, 11000, 0.0875, 963)
    assert [str(p) for p in check(example_copy, strict=True)] == []


@pytest.mark.parametrize("revenue_net, represented, share", [(11000, 0.0875, 1.0), (2972300, 0.7, 0.25), (15000, 0.0875, 1.0)])
def test_ledger_row_accepts_the_rounded_weighted_revenue(revenue_net, represented, share):
    exact = weighted_amount(revenue_net, represented, share)
    assert exact % 1 == 0.5  # 꼭 반이 남는 값이다
    row = {
        "run_id": "20261118-090000-baseline",
        "scenario_id": "baseline",
        "visit_id": "family-elders__meal-dinner-weekend",
        "persona_id": "family-elders",
        "customer_group": "가족·친족",
        "condition_id": "meal-dinner-weekend",
        "choice_kind": "walkerhill",
        "venue_id": "geumryong",
        "product_id": "course-a",
        "quantity": 1,
        "unit": "1인",
        "list_price": revenue_net * 11 // 10,
        "discount": 0,
        "paid": revenue_net * 11 // 10,
        "revenue_net": revenue_net,
        "represented": represented,
        "counted_share": share,
        "weighted_revenue": round_half_up(exact),
        "reason_labels": ["맛"],
        "reason_text": "x",
        "used_attributes": [],
        "llm_call": "replay",
        "request_hash": "0" * 16,
        "status": "ok",
        "fail_reason": None,
    }
    assert LedgerRow.model_validate(row).weighted_revenue == round_half_up(exact)
    with pytest.raises(ValueError, match="weighted_revenue"):
        LedgerRow.model_validate(dict(row, weighted_revenue=round_half_up(exact) + 1))


# ── 실행 기록의 엔진 커밋 ───────────────────────────────────────────────


def test_engine_commit_is_marked_only_when_engine_code_has_uncommitted_changes(tmp_path):
    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", *args], cwd=tmp_path, check=True, capture_output=True
        )

    (tmp_path / "engine").mkdir()
    (tmp_path / "engine" / "code.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "engine" / "conditions.json").write_text("{}\n", encoding="utf-8")
    git("init", "-q")
    git("add", ".")
    git("commit", "-q", "-m", "first")
    commit = _engine_commit(tmp_path)
    assert commit and "+" not in commit and commit != "unknown"

    # 실행 결과와 방문 조건 묶음, 엔진 밖의 파일은 엔진 코드가 아니다.
    (tmp_path / "engine" / "samples" / "runs" / "x").mkdir(parents=True)
    (tmp_path / "engine" / "samples" / "runs" / "x" / "run.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "engine" / "conditions.json").write_text('{"a": 1}\n', encoding="utf-8")
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    assert _engine_commit(tmp_path) == commit

    (tmp_path / "engine" / "code.py").write_text("x = 2\n", encoding="utf-8")
    assert _engine_commit(tmp_path) == commit + "+dirty"
    assert _engine_commit(tmp_path / "engine" / "no-such-folder") == "unknown"
