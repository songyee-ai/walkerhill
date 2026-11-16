"""상황별 비교와 식당가 보기 (T21, app/compare.py, app/board.py)."""

import json
import shutil
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.board import WALKERHILL_NAMES, pct_change, venue_cards  # noqa: E402
from app.compare import MOVE_LABEL, Place, baseline_dir_of, classify, compare, summary_groups  # noqa: E402
from app.results import load_run  # noqa: E402
from app.validation import VALIDATION_LIMITS, limits_not_in, load_validation, validation_rows  # noqa: E402
from engine.formats import WALKERHILL_VENUE_IDS  # noqa: E402

EXAMPLE = REPO_ROOT / "tests" / "fixtures" / "example"
RUNS = EXAMPLE / "engine" / "samples" / "runs"
SCEN = RUNS / "20261117-103000-competitor-chinese-discount"


def _example_comparison():
    return compare(load_run(baseline_dir_of(SCEN)), load_run(SCEN), summary_groups(EXAMPLE, "sample"))


def test_scenario_run_points_to_its_baseline():
    assert baseline_dir_of(SCEN).name == "20261117-101500-baseline"


def test_classify_covers_every_kind_of_move():
    gr, buffet = Place("walkerhill", "geumryong"), Place("walkerhill", "thebuffet")
    rival, none, failed = Place("competitor", "x"), Place("none"), Place("failed")
    assert classify(gr, gr) == "same"
    assert classify(gr, buffet) == "inside"
    assert classify(gr, rival) == "out" and classify(gr, none) == "out"
    assert classify(rival, gr) == "in" and classify(none, gr) == "in"
    assert classify(rival, none) == "other"
    assert classify(failed, gr) == "failed" and classify(gr, failed) == "failed"
    assert set(MOVE_LABEL) == {"same", "inside", "out", "in", "other", "failed"}


def test_example_family_leaves_for_the_discounted_rival():
    comparison = _example_comparison()
    [move] = comparison.moves
    assert move.before == Place("walkerhill", "geumryong")
    assert move.after == Place("competitor", "examplehotel-chinese")
    assert move.move == "out" and move.reason_after
    assert comparison.count("out") == 1 and comparison.count("in") == 0
    # 금액은 원장에서만 낸다: 기준의 금룡 가중 매출이 상황에서는 0 이 된다.
    assert comparison.total_before > 0 and comparison.total_after == 0
    [geumryong] = comparison.venues
    assert geumryong.name == "금룡" and geumryong.diff == -comparison.total_before


def test_uncovered_groups_come_from_the_summary():
    groups = summary_groups(EXAMPLE, "sample")
    assert "가족·친족" in groups
    comparison = _example_comparison()
    assert "가족·친족" not in comparison.uncovered_groups
    assert set(comparison.uncovered_groups) == set(groups) - {"가족·친족"}


def test_restaurant_cards_show_who_left_and_who_arrived():
    assert set(WALKERHILL_NAMES) == WALKERHILL_VENUE_IDS
    comparison = _example_comparison()
    cards = venue_cards(comparison, comparison.names, always=["geumryong", "thebuffet"])
    by_name = {c.name: c for c in cards}
    geumryong, rival, buffet = by_name["금룡"], by_name["예시호텔 중식당"], by_name["더뷔페"]
    assert [m.persona_id for m in geumryong.left] == ["family-elders"] and not geumryong.arrived
    assert [m.persona_id for m in rival.arrived] == ["family-elders"] and not rival.left
    # 워커힐 업장만 가상 매출이 있다. 금룡은 평소의 매출이 모두 사라졌다.
    assert geumryong.revenue_before == comparison.total_before and geumryong.revenue_after == 0
    assert rival.revenue_before is None
    assert rival.guests_before == 0 and rival.guests_after == 120.0
    # 손님이 없어도 식당가의 워커힐 업장은 카드가 있다. 바뀐 카드가 앞에 온다.
    assert buffet.revenue_before == 0 and not buffet.changed
    assert cards[0] is geumryong


def test_pct_change_handles_zero():
    assert pct_change(100, 0) == "-100%"
    assert pct_change(100, 110) == "+10%"
    assert pct_change(0, 50) == "새로 생김"
    assert pct_change(0, 0) == "변화 없음"


def _write_validation(run_dir: Path) -> None:
    # 형식(docs/FORMATS.md 10.5절)대로 지어낸 검증 결과. 실제 검증 결과는 private/ 에만 있다.
    (run_dir / "validation.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "created_at": "2026-11-19T15:00:00+09:00",
                "min_reviews": 5,
                "venues": {
                    "geumryong": {
                        "n": 12, "enough": True, "venue_match": 8, "venue_match_baseline": 7,
                        "reason_match": 9, "reason_match_baseline": 6,
                    },
                    "thebuffet": {
                        "n": 3, "enough": False, "venue_match": None, "venue_match_baseline": None,
                        "reason_match": None, "reason_match_baseline": None,
                    },
                },
            }
        ),
        encoding="utf-8",
    )  # fmt: skip


def test_validation_shows_counts_and_limits_together(tmp_path: Path):
    run_dir = tmp_path / "run"
    shutil.copytree(RUNS / "20261117-101500-baseline", run_dir)
    assert load_validation(run_dir) is None  # 검증 결과가 없는 실행은 칸을 그리지 않는다
    _write_validation(run_dir)
    validation = load_validation(run_dir)
    rows = {r["업장"]: r for r in validation_rows(validation, WALKERHILL_NAMES)}
    assert rows["금룡"]["검증 건수"] == 12 and rows["금룡"]["고른 업장이 같음"] == "12건 중 8건"
    assert rows["금룡"]["한계"] == VALIDATION_LIMITS["geumryong"]  # 11-16 팀원 요청: 한계를 함께
    assert rows["더뷔페"]["상태"].startswith("검증 건수 부족") and rows["더뷔페"]["고른 업장이 같음"] == ""
    # 명월관은 이 결과에 없지만 한계는 감추지 않는다.
    assert limits_not_in(validation) == ["myongwolgwan"]


def test_detail_tab_renders_validation_with_limits(tmp_path: Path):
    runs = tmp_path / "runs"
    shutil.copytree(RUNS, runs)
    _write_validation(runs / "20261117-101500-baseline")
    app = AppTest.from_file(str(REPO_ROOT / "app" / "main.py"), default_timeout=60).run()
    app.text_input(key="other_folder").set_value(str(runs)).run()
    app.selectbox(key="run_id").set_value("20261117-101500-baseline").run()
    assert not app.exception
    captions = " ".join(c.value for c in app.caption)
    assert "REVIEW_RULES.md 6절" in captions and "명월관 (이 결과에 없음) 한계" in captions
    assert any("검증 건수" in frame.value.columns for frame in app.dataframe)
