"""업장 특성 (docs/FORMATS.md 3절의 `traits`, T221).

특성은 3·5단계에서 쓴다. 지금은 LLM 요청에 싣지 않으므로, 특성을 넣어도 요청과 그 해시가 그대로여서 저장된 답이 재생돼야 한다.
"""

from pathlib import Path

import pytest
from conftest import BASELINE_RUN, EXAMPLE_ROOT, load_json, save_json

from engine.answers import request_as_json
from engine.candidates import build_request, run_condition
from engine.formats import RunRecord, compute_request_hash, read_model
from engine.runner import load_inputs
from tools.check_formats import check

VENUES = Path("data") / "venues"
BASELINE_DIR = EXAMPLE_ROOT / "engine" / "samples" / "runs" / BASELINE_RUN


def requests(venues, inputs, prompt_version, month=None) -> dict[str, dict]:
    """방문마다 엔진이 만들 요청 (JSON 으로 바꾼 것). 후보가 없는 방문은 빠진다."""
    found = {}
    for persona in inputs.personas.values():
        for condition in inputs.conditions.conditions:
            request, _ = build_request(
                prompt_version=prompt_version,
                persona=inputs.persona_json[persona.persona_id],
                condition=run_condition(condition, persona, month),
                venues=venues,
                vocab=inputs.vocab,
            )
            if request is not None:
                found[f"{persona.persona_id}__{condition.condition_id}"] = request_as_json(request)
    return found


def test_example_venues_have_traits():
    """아래 테스트가 특성이 든 업장 정의로 도는지 먼저 본다 (예시 묶음에서 특성이 빠지면 아래 테스트는 아무것도 보지 못한다)."""
    venues = load_inputs(EXAMPLE_ROOT, "sample").venues
    assert venues["geumryong"].traits is not None and venues["geumryong"].traits.seats is not None
    assert venues["examplehotel-chinese"].traits is not None
    assert venues["examplehotel-chinese"].traits.distance_km is not None


def test_traits_keep_the_saved_request():
    """특성이 든 예시 묶음으로 만든 요청이, 특성이 생기기 전에 저장한 답의 요청과 바이트까지 같다 (해시가 같다)."""
    record = read_model(BASELINE_DIR / "run.json", RunRecord)
    inputs = load_inputs(EXAMPLE_ROOT, "sample")
    saved = {path.stem: load_json(path) for path in (BASELINE_DIR / "llm").glob("*.json")}
    assert saved
    for request_hash, answer in saved.items():
        # 예시 실행은 업장 몇 곳만 골라 돌렸다. 그 업장들의 정의(특성이 든 것)로 다시 만든다.
        venues = [inputs.venues[candidate["venue_id"]] for candidate in answer["request"]["candidates"]]
        assert any(venue.traits is not None for venue in venues)
        built = requests(venues, inputs, record.llm.prompt_version)
        same = [request for request in built.values() if request == answer["request"]]
        assert len(same) == 1
        assert compute_request_hash(record.llm.provider, record.llm.model, same[0]) == request_hash


def test_requests_are_the_same_with_and_without_traits():
    """모든 방문(페르소나 × 조건, 일 년 전체와 달마다)에서 특성을 지운 업장 정의로 만든 요청과 같다."""
    inputs = load_inputs(EXAMPLE_ROOT, "sample")
    with_traits = list(inputs.venues.values())
    without = [venue.model_copy(update={"traits": None}) for venue in with_traits]
    assert any(venue.traits is not None for venue in with_traits)
    for month in (None, 1, 12):
        first = requests(with_traits, inputs, "p1", month)
        second = requests(without, inputs, "p1", month)
        assert first and first.keys() == second.keys()
        for visit_id, request in first.items():
            assert compute_request_hash("p", "m", request) == compute_request_hash("p", "m", second[visit_id])


def edit_venue(root, venue_id, change) -> None:
    path = root / VENUES / f"{venue_id}.json"
    data = load_json(path)
    change(data)
    save_json(path, data)


def test_venue_without_traits_is_still_valid(example_copy):
    edit_venue(example_copy, "geumryong", lambda d: d.pop("traits"))
    assert [str(p) for p in check(example_copy, strict=True)] == []


def test_no_private_rooms_is_zero(example_copy):
    """별실이 없다고 확인한 것(0)은 모르는 것(null)과 따로 적을 수 있다."""
    edit_venue(example_copy, "geumryong", lambda d: d["traits"]["private_rooms"].update(count=0, max_people=None))
    assert [str(p) for p in check(example_copy, strict=True)] == []


def measured_source(data) -> None:
    data["sources"].append(
        {"source_id": "S2", "title": "지도로 잰 거리 (예시)", "url": "https://example.com/route", "checked_on": "2026-11-19", "kind": "measurement"}
    )


@pytest.mark.parametrize(
    ("venue_id", "change", "message"),
    [
        # 거리는 경쟁 업장만 적는다.
        (
            "geumryong",
            lambda d: (measured_source(d), d["traits"].update(distance_km={"value": 3.0, "source_id": "S2"})),
            "traits.distance_km 은 경쟁 업장만 적는다",
        ),
        # 거리의 출처는 지도로 잰 자료다 (null 이면 메뉴판인 default_source_id 를 쓴다).
        (
            "examplehotel-chinese",
            lambda d: d["traits"]["distance_km"].update(source_id=None),
            "traits.distance_km 의 출처는 kind 가 measurement 인 자료다",
        ),
        # 지도로 잰 출처는 거리에만 쓴다.
        (
            "examplehotel-chinese",
            lambda d: d["traits"]["location"].update(source_id="S2"),
            "traits.location 의 출처가 measurement 자료다",
        ),
        ("geumryong", lambda d: d["traits"]["seats"].update(source_id="S9"), "traits.seats 의 source_id 가 sources 에 없다"),
        ("geumryong", lambda d: d["traits"]["seats"].update(value=0), "traits.seats.value"),
        ("geumryong", lambda d: d["traits"]["private_rooms"].update(count=-1), "traits.private_rooms.count"),
        # 별실 없음(0)에는 인원이 없다.
        (
            "geumryong",
            lambda d: d["traits"]["private_rooms"].update(count=0),
            "count 가 0 (별실 없음)이면 max_people 은 null 이다",
        ),
        (
            "geumryong",
            lambda d: d["traits"]["private_rooms"].update(count=None, max_people=None),
            "count 와 max_people 을 둘 다 모르면 private_rooms 를 null 로 둔다",
        ),
        (
            "geumryong",
            lambda d: d["traits"]["booking"].update(opens_months_before=None),
            "opens_months_before 와 deposit 을 둘 다 모르면 booking 을 null 로 둔다",
        ),
        ("examplehotel-chinese", lambda d: d["traits"]["distance_km"].update(value=0), "traits.distance_km.value"),
        # 모르는 칸도 null 로 적는다 (키를 빠뜨리지 않는다).
        ("geumryong", lambda d: d["traits"].pop("view"), "traits.view — 키가 빠졌다"),
        ("geumryong", lambda d: d["sources"][0].update(kind="blog"), "sources[0].kind — 쓸 수 없는 값 'blog'"),
    ],
)
def test_trait_rules(example_copy, venue_id, change, message):
    edit_venue(example_copy, venue_id, change)
    problems = [str(p) for p in check(example_copy) if p.level == "error"]
    assert any(message in p for p in problems), "\n".join(problems)


def measured_promotion(data) -> None:
    """지도로 잰 출처(S2)를 가리키는 프로모션을 더한다."""
    measured_source(data)
    data["promotions"].append(
        {
            "promo_id": "weekend-10",
            "name": "주말 10% 할인",
            "benefit": {"type": "discount_pct", "value": 10},
            "applies_to": None,
            "conditions": {"day_type": "weekend", "meal": None, "stay": None, "party_min": None},
            "period": None,
            "grade": "assumption",
            "source_id": "S2",
        }
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: (measured_source(d), d.update(default_source_id="S2")), "default_source_id 가 measurement 자료다"),
        (
            lambda d: (measured_source(d), d["products"][0].update(source_id="S2")),
            "상품 'course-a' 의 출처가 measurement 자료다",
        ),
        (lambda d: (measured_source(d), d["hours"][0].update(source_id="S2")), "hours[0] 의 출처가 measurement 자료다"),
        (
            lambda d: (measured_source(d), d["reservation"].update(source_id="S2")),
            "reservation 의 출처가 measurement 자료다",
        ),
        (measured_promotion, "프로모션 'weekend-10' 의 출처가 measurement 자료다"),
    ],
)
def test_measurement_source_is_only_for_distance(example_copy, change, message):
    """지도로 잰 출처는 거리에만 쓴다. 메뉴판·영업 시간·예약·프로모션의 출처로 쓰면 오류다."""
    edit_venue(example_copy, "geumryong", change)
    problems = [str(p) for p in check(example_copy) if p.level == "error"]
    assert any(message in p for p in problems), "\n".join(problems)


def add_measured_product(data) -> None:
    product = load_json(EXAMPLE_ROOT / VENUES / "examplehotel-chinese.json")["products"][0]
    data["changes"].append(
        {"op": "add_product", "venue_id": "examplehotel-chinese", "product": {**product, "product_id": "course-new", "source_id": "S2"}}
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["changes"][0]["promotion"].update(source_id="S2"), "프로모션의 출처가 measurement 자료다"),
        (add_measured_product, "상품의 출처가 measurement 자료다"),
    ],
)
def test_scenario_cannot_cite_measurement_source(example_copy, change, message):
    """상황이 더하는 상품·프로모션도 지도로 잰 출처를 쓰지 못한다."""
    path = example_copy / "scenarios" / "competitor-chinese-discount.json"
    data = load_json(path)
    change(data)
    save_json(path, data)
    problems = [str(p) for p in check(example_copy) if p.level == "error"]
    assert any(message in p for p in problems), "\n".join(problems)


def test_empty_trait_source_id_is_an_error(example_copy):
    """특성의 source_id 가 빈 글자면 기본 출처로 넘기지 않고 오류다 (상품과 같다)."""
    edit_venue(example_copy, "geumryong", lambda d: d["traits"]["location"].update(source_id=""))
    problems = [str(p) for p in check(example_copy) if p.level == "error"]
    assert any("traits.location 의 source_id 가 sources 에 없다" in p for p in problems), "\n".join(problems)
