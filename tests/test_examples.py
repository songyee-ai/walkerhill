"""형식 문서, 모델, 예시 파일이 서로 어긋나지 않는지 본다.

형식을 바꿀 때는 docs/FORMATS.md, engine/formats, tests/fixtures/example 을 함께 고친다.
하나만 고치면 여기서 실패한다.
"""

import re
from typing import get_args

from conftest import BASELINE_RUN, COMPETITOR_RUN, EXAMPLE_ROOT, REPO_ROOT, load_csv, load_json

from engine.formats import (
    WALKERHILL_VENUE_IDS,
    Persona,
    Validation,
    codes,
    compute_request_hash,
    merge_persona_layers,
)
from tools.check_formats import check

RUNS = EXAMPLE_ROOT / "engine" / "samples" / "runs"


def test_example_set_passes_strict_check():
    assert [str(p) for p in check(EXAMPLE_ROOT, strict=True)] == []


def test_repository_has_no_errors():
    errors = [str(p) for p in check(REPO_ROOT) if p.level == "error"]
    assert errors == []


# ── 문서의 예시 = 예시 파일 ──────────────────────────────────────────────────


def test_doc_venues_match_files(doc):
    assert len(doc.venues) == 2
    for venue in doc.venues:
        assert load_json(EXAMPLE_ROOT / "data" / "venues" / f"{venue['venue_id']}.json") == venue


def test_doc_vocab_persona_conditions_match_files(doc):
    assert load_json(EXAMPLE_ROOT / "data" / "evidence" / "vocab.json") == doc.vocab
    assert load_json(EXAMPLE_ROOT / "personas" / f"{doc.persona['persona_id']}.json") == doc.persona
    assert load_json(EXAMPLE_ROOT / "engine" / "conditions.json") == doc.conditions


def test_doc_scenarios_match_files(doc):
    assert len(doc.scenarios) == 2
    for scenario in doc.scenarios:
        assert load_json(EXAMPLE_ROOT / "scenarios" / f"{scenario['scenario_id']}.json") == scenario


def test_doc_csv_examples_match_files(doc):
    assert load_csv(EXAMPLE_ROOT / "data" / "evidence" / "reviews" / "geumryong.csv") == doc.reviews
    assert load_csv(EXAMPLE_ROOT / "data" / "samples" / "base_summary.csv") == doc.summary
    # 문서의 원장 예시 두 줄은 서로 다른 실행의 원장에서 한 줄씩 가져온 것이다.
    assert load_csv(RUNS / BASELINE_RUN / "ledger.csv") == [doc.ledger[0]]
    assert load_csv(RUNS / COMPETITOR_RUN / "ledger.csv") == [doc.ledger[1]]


def test_doc_run_and_calibration_match_files(doc):
    assert load_json(RUNS / BASELINE_RUN / "run.json") == doc.run
    assert load_json(RUNS / BASELINE_RUN / "calibration.json") == doc.calibration


def test_doc_request_and_response_match_saved_response(doc):
    request_hash = doc.ledger[0]["request_hash"]
    saved = load_json(RUNS / BASELINE_RUN / "llm" / f"{request_hash}.json")
    # 문서의 요청은 persona 를 줄여 적었다. 실제 요청에는 페르소나의 모든 키가 들어간다.
    assert saved["request"]["persona"] == doc.persona
    assert {**saved["request"], "persona": doc.request["persona"]} == doc.request
    assert saved["response"] == doc.response


def test_doc_ledger_hashes_are_real(doc):
    """문서의 원장 예시에 적힌 해시가 저장된 요청으로 다시 낸 값과 같다.

    요청 예시를 고치면 해시가 달라진다. 그때는 문서의 원장 예시와 예시 파일의 이름을 새 값으로 고친다.
    """
    for run_id, row in ((BASELINE_RUN, doc.ledger[0]), (COMPETITOR_RUN, doc.ledger[1])):
        saved = load_json(RUNS / run_id / "llm" / f"{row['request_hash']}.json")
        expected = compute_request_hash(saved["provider"], saved["model"], saved["request"])
        assert row["request_hash"] == expected


# ── 문서에만 있는 예시도 모델에 맞는다 ───────────────────────────────────────


def test_doc_private_layer_merges_into_valid_persona(doc):
    merged = merge_persona_layers(doc.persona, doc.persona_private)
    persona = Persona.model_validate(merged)
    refs = persona.evidence.preferences.refs
    assert refs == ["R-geumryong-0003", "R-geumryong-0011", "P-geumryong-0002"]
    # 비공개 층에 refs 만 적어도 공개 층의 등급은 남는다.
    assert persona.evidence.preferences.grade == "review"
    # 비공개 층 때문에 달라진 키가 흔적으로 남는다.
    assert persona.overridden_by_private == ["evidence.preferences.refs"]


def test_doc_validation_example_is_valid(doc):
    validation = Validation.model_validate(doc.validation)
    assert validation.venues["geumryong"].enough is True
    assert validation.venues["thebuffet"].enough is False


# ── 문서의 코드 값 표 = 코드 ─────────────────────────────────────────────────


def _doc_codes(text: str, key: str) -> set[str]:
    """2절 코드 값 표에서 그 키의 줄을 찾아 코드 값을 모은다."""
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        # 표의 한 줄은 "| 뜻 | 키 | 코드 값 |" 이다. 둘째 칸이 그 키인 줄만 본다.
        if len(cells) >= 4 and cells[2] == f"`{key}`":
            return set(re.findall(r"`([a-z_]+)`", cells[3])) - {"null"}
    raise AssertionError(f"문서의 코드 값 표에 '{key}' 줄이 없다")


def test_doc_code_table_matches_models(doc):
    expected = {
        "occasion": codes.Occasion,
        "meal": codes.Meal,
        "day_type": codes.DayTypeOrAll,
        "stay": codes.Stay,
        "price_basis": codes.PriceBasis,
        "grade": codes.Grade,
        "kind": codes.ScenarioKind,
        "choice_kind": codes.ChoiceKind,
        "qty_rule": codes.QtyRule,
        "audience": codes.Audience,
        "source_kind": codes.SourceKind,
    }
    for key, literal in expected.items():
        assert _doc_codes(doc.text, key) == set(get_args(literal)), key
    levels = next(line for line in doc.text.splitlines() if "`price_sensitivity`, `wait_tolerance`" in line)
    assert set(re.findall(r"`(low|mid|high)`", levels)) == set(get_args(codes.Level))


def test_doc_venue_ids_match_models(doc):
    table = doc.text.split("**워커힐 업장의 `venue_id`**")[1].split("경쟁 업장의 `venue_id`")[0]
    ids = set(re.findall(r"`([a-z]+)`", table)) - {"venue_id"}
    assert ids == set(WALKERHILL_VENUE_IDS)


def test_ko_labels_cover_every_code():
    """화면에 보여 줄 한국어 뜻이 코드 값마다 있다."""
    pairs = {
        "occasion": codes.Occasion,
        "meal": codes.Meal,
        "day_type": codes.DayTypeOrAll,
        "stay": codes.Stay,
        "price_basis": codes.PriceBasis,
        "grade": codes.Grade,
        "kind": codes.ScenarioKind,
        "choice_kind": codes.ChoiceKind,
        "audience": codes.Audience,
        "source_kind": codes.SourceKind,
        "level": codes.Level,
    }
    for key, literal in pairs.items():
        assert set(codes.KO[key]) == set(get_args(literal)), key
