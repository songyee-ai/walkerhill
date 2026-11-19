"""화면이 실행 폴더를 읽어 보여 줄 모양으로 바꾸는 것을 본다 (T09, app/results.py)."""

import csv
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.results import (  # noqa: E402
    EXAMPLE_LABEL,
    list_runs,
    load_run,
    persona_names,
    run_notices,
    run_sources,
    visit_table,
    visit_view,
    won,
)
from engine.formats.run import SEASON_GAP_REASON  # noqa: E402

EXAMPLE_RUNS = REPO_ROOT / "tests" / "fixtures" / "example" / "engine" / "samples" / "runs"
BASELINE = "20261117-101500-baseline"
COMPETITOR = "20261117-103000-competitor-chinese-discount"
PERSONA = "family-elders"
CONDITION = "meal-dinner-weekend"


@pytest.fixture
def run_copy(tmp_path: Path) -> Path:
    """예시 기준 실행을 임시 폴더에 베낀 것. 원장을 고쳐 실패한 방문 같은 경우를 만든다."""
    target = tmp_path / "runs" / BASELINE
    shutil.copytree(EXAMPLE_RUNS / BASELINE, target)
    return target


def _rewrite_ledger(run_dir: Path, change) -> None:
    path = run_dir / "ledger.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        rows = change(list(reader))
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_example_runs_are_listed_newest_first():
    assert list_runs(EXAMPLE_RUNS) == [COMPETITOR, BASELINE]
    assert list_runs(EXAMPLE_RUNS / "없는 폴더") == []


def test_example_is_always_the_last_source():
    # 키와 기본 데이터가 없는 PC 에도 예시 실행은 있어서 화면이 돈다.
    sources = run_sources(REPO_ROOT)
    assert sources[-1].label == EXAMPLE_LABEL
    assert sources[-1].folder == EXAMPLE_RUNS


def test_walkerhill_choice_shows_venue_products_amounts_and_reasons():
    run = load_run(EXAMPLE_RUNS / BASELINE)
    view = visit_view(run, PERSONA, CONDITION)

    assert view.found and view.failed_reason is None
    assert view.choice_kind == "walkerhill"
    assert view.venue == "금룡"
    assert "워커힐 업장" in view.venue_detail
    # 금액은 원장에서 온다: 코스 A 1인 150,000원 × 4명.
    assert [(line.product, line.quantity, line.list_price, line.paid) for line in view.lines] == [
        ("코스 A", 4, 150000, 600000)
    ]
    assert view.total_paid == 600000
    assert view.revenue_net == 545455
    assert view.reason_labels and view.reason_text
    assert view.condition is not None and view.condition.adults == 4
    # 고르지 않은 업장과 그 이유는 저장된 응답에서 온다.
    assert len(view.not_chosen) == 1
    rejected = view.not_chosen[0]
    assert rejected.kind == "경쟁 업장"
    assert rejected.cheapest is not None and rejected.text


def test_competitor_choice_has_no_walkerhill_revenue():
    run = load_run(EXAMPLE_RUNS / COMPETITOR)
    view = visit_view(run, PERSONA, CONDITION)
    assert view.choice_kind == "competitor"
    assert view.total_paid > 0
    assert view.revenue_net == 0
    assert [item.venue for item in view.not_chosen] == ["금룡"]


def test_persona_names_come_from_saved_responses():
    run = load_run(EXAMPLE_RUNS / BASELINE)
    assert persona_names(run) == {PERSONA: "어르신을 모신 행사 가족"}


def test_failed_visit_shows_reason_and_is_announced(run_copy: Path):
    def fail(rows):
        row = rows[0]
        for key in ("venue_id", "product_id", "unit", "reason_labels", "reason_text", "used_attributes", "llm_call", "request_hash"):
            row[key] = ""
        for key in ("quantity", "list_price", "discount", "paid", "revenue_net", "weighted_revenue"):
            row[key] = "0"
        row.update(choice_kind="none", status="failed", fail_reason="응답이 형식에 맞지 않음")
        return [row]

    _rewrite_ledger(run_copy, fail)
    record = json.loads((run_copy / "run.json").read_text(encoding="utf-8"))
    record["counts"]["failed"] = 1
    (run_copy / "run.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    (run_copy / "llm_rejected").mkdir()
    (run_copy / "llm_rejected" / "0000000000000000.json").write_text("{}", encoding="utf-8")

    run = load_run(run_copy)
    view = visit_view(run, PERSONA, CONDITION)
    assert view.failed_reason == "응답이 형식에 맞지 않음"
    assert view.lines == []
    notices = run_notices(run)
    assert any("실패한 방문이 1건" in n for n in notices)
    assert any("llm_rejected" in n for n in notices)
    assert visit_table(run)[0]["고른 곳"].startswith("실패")


def test_season_gap_row_is_not_taken_as_the_choice(run_copy: Path):
    # 일부 달에만 파는 상품을 고르면 엔진이 나머지 몫을 "이용하지 않음" 줄로 더 적는다 (engine.ledger.visit_rows).
    def split(rows):
        chosen = rows[0]
        # 가중 매출은 그 줄의 represented 로 다시 낸다. 예시 실행의 represented 가 바뀌어도 이 시험은 그대로 맞는다.
        weighted = float(chosen["revenue_net"]) * float(chosen["represented"]) * 0.5
        chosen.update(counted_share="0.5", weighted_revenue=str(round(weighted)))
        gap = dict(chosen)
        for key in ("venue_id", "product_id", "unit", "reason_labels", "used_attributes"):
            gap[key] = ""
        for key in ("quantity", "list_price", "discount", "paid", "revenue_net", "weighted_revenue"):
            gap[key] = "0"
        gap.update(choice_kind="none", reason_text=SEASON_GAP_REASON)
        return [chosen, gap]

    _rewrite_ledger(run_copy, split)
    view = visit_view(load_run(run_copy), PERSONA, CONDITION)
    assert view.choice_kind == "walkerhill"
    assert view.counted_share == 0.5
    assert len(view.lines) == 1
    assert view.reason_text != SEASON_GAP_REASON


def test_missing_visit_is_not_found():
    run = load_run(EXAMPLE_RUNS / BASELINE)
    assert not visit_view(run, PERSONA, "meal-lunch-weekday").found


def test_every_amount_is_marked_virtual():
    assert won(600000) == "600,000원 (가상)"
    table = visit_table(load_run(EXAMPLE_RUNS / BASELINE))
    for column in table[0]:
        if "금액" in column or "매출" in column:
            assert "가상" in column
