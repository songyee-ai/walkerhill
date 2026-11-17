"""근거 보기 탭 (T22, app/evidence.py)."""

import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.evidence import (  # noqa: E402
    BASIS_UNKNOWN,
    NO_GRADE,
    PRICE_UNKNOWN,
    REASON_LACK,
    baseline_runs,
    persona_evidence_rows,
    persona_overview,
    personas,
    product_notes,
    ref_label,
    venue_overview,
    venue_value_rows,
    venues,
    weight_rows,
)
from app.results import load_run  # noqa: E402

EXAMPLE = REPO_ROOT / "tests" / "fixtures" / "example"
EXAMPLE_RUNS = EXAMPLE / "engine" / "samples" / "runs"


def test_every_venue_value_has_a_grade_a_source_and_a_checked_date():
    # 값마다 근거 등급, 출처, 확인일 (T22 완료 조건 1). 저장소의 업장 정의 모두로 본다.
    found = venues(REPO_ROOT)
    assert found
    for venue in found.values():
        for row in venue_value_rows(venue):
            assert row["근거 등급"] and row["출처"] and row["확인일"], (venue.venue_id, row)
            # 영업시간과 예약은 형식에 등급 칸이 없어 지어내지 않는다
            assert (row["근거 등급"] == NO_GRADE) == (row["갈래"] in ("영업시간", "예약"))


def test_missing_price_is_marked_unconfirmed():
    # 가격이 비었으면 "가격 미확인", 가격은 있는데 표기를 모르면 "가격 표기 미확인" (T22 완료 조건 4).
    venue = venues(EXAMPLE)["geumryong"]
    first = venue.products[0]
    blank = first.model_copy(update={"price": None, "grade": "unknown"})
    unknown_basis = first.model_copy(update={"price": 10000, "price_basis": "unknown"})
    changed = venue.model_copy(update={"products": [blank, unknown_basis]})
    flags = [row["표시"] for row in venue_value_rows(changed)[:2]]
    assert flags == [PRICE_UNKNOWN, BASIS_UNKNOWN]
    [row] = [r for r in venue_overview({"geumryong": changed}) if r["업장"] == venue.name]
    assert row[PRICE_UNKNOWN] == 1


def test_persona_evidence_shows_grade_and_review_numbers():
    # 페르소나의 묶음마다 근거 등급과 후기 번호 (T22 완료 조건 2). 업장 출처 번호는 이름으로 바꿔 보인다.
    found_venues = venues(EXAMPLE)
    persona = personas(EXAMPLE)["family-elders"]
    rows = persona_evidence_rows(persona, found_venues)
    assert len(rows) == 7 and all(r["근거 등급"] for r in rows)
    assert sum(r["후기 수"] for r in rows) == len(persona.review_refs())
    source = found_venues["geumryong"].sources[0]
    assert ref_label(f"geumryong:{source.source_id}", found_venues).startswith(found_venues["geumryong"].name)
    assert ref_label("R-geumryong-0001", found_venues) == "R-geumryong-0001"


def test_persona_without_review_numbers_for_reasons_is_flagged():
    # 방문 모습·기호·구매 성향에 후기 번호가 없으면 "이유 근거 부족" (T22 완료 조건 4).
    persona = personas(EXAMPLE)["family-elders"]
    assert persona_overview({"p": persona})[0]["표시"] == ""
    evidence = persona.evidence.model_copy(
        update={key: getattr(persona.evidence, key).model_copy(update={"refs": []}) for key in ("visit", "preferences", "buying")}
    )
    lacking = persona.model_copy(update={"evidence": evidence})
    assert persona_overview({"p": lacking})[0]["표시"] == REASON_LACK
    marks = {r["묶음"]: r["표시"] for r in persona_evidence_rows(lacking, venues(EXAMPLE))}
    assert marks["방문 모습"] == marks["기호와 제약"] == marks["구매 성향"] == "후기 없음"


def test_weights_show_grades_and_hide_base_data_numbers():
    # 가중치와 묶음 비율의 근거 등급 (T22 완료 조건 3). 기본 데이터 실행의 수치는 PRD 17절의 결정 전까지 가린다.
    [run_id] = baseline_runs(EXAMPLE_RUNS)[:1]
    record = load_run(EXAMPLE_RUNS / run_id).record
    tables = weight_rows(record, {})
    assert set(tables) == {"고객군 배수", "페르소나 가중치", "묶음 비율"}
    assert all(row["근거 등급"] for rows in tables.values() for row in rows)
    assert tables["고객군 배수"][0]["고객군 배수"] != "가림"  # 가상 예시 값은 보인다
    private = record.model_copy(update={"data_mode": "private"})
    hidden = weight_rows(private, {})
    assert {row["고객군 배수"] for row in hidden["고객군 배수"]} == {"가림"}
    assert [r["근거 등급"] for r in hidden["묶음 비율"]] == [r["근거 등급"] for r in tables["묶음 비율"]]


def test_product_notes_name_filled_and_skipped_products():
    [run_id] = baseline_runs(EXAMPLE_RUNS)[:1]
    record = load_run(EXAMPLE_RUNS / run_id).record
    venue = venues(EXAMPLE)["geumryong"]
    product = venue.products[0]
    changed = record.model_copy(update={"filled_products": [f"geumryong:{product.product_id}"], "skipped_products": ["x:y"]})
    notes = product_notes(changed, {"geumryong": venue})
    assert f"{venue.name} {product.name}" in notes[0] and "원" not in notes[0]  # 단가는 보이지 않는다
    assert PRICE_UNKNOWN in notes[1] and "x:y" in notes[1]


@pytest.mark.parametrize("part", ["업장", "페르소나", "가중치와 검증"])
def test_evidence_tab_renders(part: str):
    app = AppTest.from_file(str(REPO_ROOT / "app" / "main.py"), default_timeout=60)
    app.session_state["ev_part"] = part
    app.run()
    assert not app.exception
    assert [t.label for t in app.tabs][-1] == "근거 보기"
