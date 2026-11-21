"""매출 변화 나누기를 화면에 보인다 (T124, app/breakdown.py, PRD 8절의 1단계, FORMATS.md 10.6절).

값은 모두 예시 묶음의 지어낸 값이다. 실제 기본 데이터로 돌린 실행은 쓰지 않는다.
"""

import json
import shutil
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.breakdown import (  # noqa: E402
    GROUPS,
    NO_FILE_NOTE,
    Breakdown,
    Group,
    VenueBreakdown,
    add_up,
    load_breakdown,
    share_text,
)
from app.compare import combine_months, compare  # noqa: E402
from app.results import load_run  # noqa: E402
from app.simulator import breakdown_amount, breakdown_note, breakdown_rows  # noqa: E402
from engine.formats.changes import PARTS  # noqa: E402

RUNS = REPO_ROOT / "tests" / "fixtures" / "example" / "engine" / "samples" / "runs"
BASE, SCEN = "20261117-101500-baseline", "20261117-103000-competitor-chinese-discount"


def _groups(**parts: int) -> list[Group]:
    from app.breakdown import _groups as make

    return make({part: parts.get(part, 0) for part in PARTS})


def _inside_breakdown() -> Breakdown:
    """지어낸 값: 더뷔페를 고르던 방문이 피자힐로 옮겨 가 워커힐 안에서 300 이 줄었다."""
    groups = _groups(from_walkerhill=700, to_walkerhill=-1000)
    venues = [
        VenueBreakdown("thebuffet", 1000, 0, _groups(to_walkerhill=-1000)),
        VenueBreakdown("pizzahill", 500, 1200, _groups(from_walkerhill=700)),
    ]
    return Breakdown(1500, -300, groups, venues)


def test_groups_are_the_five_of_prd_with_unit_effect_split():
    # PRD 8절의 넷 가운데 단가 효과를 가격 효과와 주문 변화로 나눴다 (T210 의 경위). 엔진의 갈래 여덟이 모두 한 번씩 든다.
    assert [label for _, label, _, _ in GROUPS] == ["새로 들어온 매출", "옮겨 온 매출", "잃은 매출", "가격 효과", "주문 변화"]
    keys = [part for _, _, parts, _ in GROUPS for part in parts]
    assert sorted(keys) == sorted(PARTS) and len(keys) == len(PARTS)


def test_example_comparison_carries_the_engine_breakdown():
    comparison = compare(load_run(RUNS / BASE), load_run(RUNS / SCEN))
    found = comparison.breakdown
    assert found is not None
    # 다섯 갈래를 더하면 두 원장으로 낸 워커힐 가상 매출의 변화와 같다 (남는 금액이 없다).
    assert sum(g.amount for g in found.groups) == found.total == comparison.total_after - comparison.total_before
    assert found.before == comparison.total_before
    # 예시: 금룡을 고르던 가족이 할인한 경쟁 중식당으로 갔다. 잃은 매출(경쟁 업장으로)만 있다.
    lost = next(g for g in found.groups if g.key == "lost")
    assert lost.amount == found.total < 0 and lost.parts["to_competitor"] == found.total
    assert [v.venue_id for v in found.venues] == ["geumryong"]


def test_no_breakdown_without_the_file_or_for_another_run(tmp_path: Path):
    runs = tmp_path / "runs"
    shutil.copytree(RUNS, runs)
    # 다른 기준과 견준 파일이면 쓰지 않는다.
    assert load_breakdown(runs / SCEN, SCEN, "20261117-000000-baseline") is None
    assert load_breakdown(runs / SCEN, SCEN, BASE) is not None
    # 11-19 T210 전에 돌린 실행에는 파일이 없다. 화면은 나누기 없이 그리고 안내만 한다.
    (runs / SCEN / "changes.json").unlink()
    assert compare(load_run(runs / BASE), load_run(runs / SCEN)).breakdown is None
    assert "다시 돌리면 생깁니다" in NO_FILE_NOTE


def test_breakdown_is_dropped_when_it_does_not_match_the_ledgers(tmp_path: Path):
    # 파일의 합이 두 원장으로 낸 변화와 다르면(빼는 방문이 다르면) 화면에 잘못된 갈래를 보이지 않는다.
    runs = tmp_path / "runs"
    shutil.copytree(RUNS, runs)
    path = runs / SCEN / "changes.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for parts in [data["walkerhill"], data["venues"][0]["parts"]]:
        parts["to_competitor"] -= 1
        parts["total"] -= 1
    data["venues"][0]["after"] = 0
    data["venues"][0]["before"] += 1
    data["visits"][0]["parts"][0]["amount"] -= 1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    assert load_breakdown(runs / SCEN, SCEN, BASE) is not None
    assert compare(load_run(runs / BASE), load_run(runs / SCEN)).breakdown is None


def test_months_are_added_and_a_missing_month_drops_the_breakdown():
    # 기간의 값은 달마다의 합이다 (FORMATS.md 10.1절 "여러 달을 합치는 법", T216. 11-20 까지는 달 평균).
    comparison = compare(load_run(RUNS / BASE), load_run(RUNS / SCEN))
    found = comparison.breakdown
    assert found is not None
    twice = add_up([found, found])
    assert [g.amount for g in twice.groups] == [2 * g.amount for g in found.groups]
    assert twice.before == 2 * found.before and twice.total == 2 * found.total
    assert [v.after for v in twice.venues] == [2 * v.after for v in found.venues]
    assert combine_months([(11, comparison), (12, comparison)]).breakdown == twice
    # 한 달이라도 나누기가 없으면 더하지 않는다 (빠진 달이 0 으로 섞이면 갈래가 작아 보인다).
    missing = compare(load_run(RUNS / BASE), load_run(RUNS / SCEN))
    missing.breakdown = None
    assert combine_months([(11, comparison), (12, missing)]).breakdown is None


def test_shares_are_points_of_the_baseline_and_add_up_to_the_change_rate():
    assert share_text(-300, 1500) == "-20.0%p"
    assert share_text(0, 1500) == "0%p"
    assert share_text(1, 1_000_000) == "+0.0%p"
    assert share_text(-300, 1500, "%") == "-20.0%"
    assert share_text(5, 0) == "—"  # 기본 시나리오에 워커힐 매출이 없으면 견줄 수 없다


def test_masked_breakdown_shows_shares_not_amounts():
    found = _inside_breakdown()
    assert breakdown_amount(-300, found.before, masked=False) == "−300원"
    assert breakdown_amount(0, found.before, masked=False) == "0원"
    masked_rows = breakdown_rows(found, {}, masked=True)
    plain_rows = breakdown_rows(found, {}, masked=False)
    assert [r["업장"] for r in masked_rows] == ["더뷔페", "피자힐"]
    cells = " ".join(v for row in masked_rows for v in row.values())
    assert "원" not in cells and "%p" in cells
    assert plain_rows[1]["옮겨 온 매출"] == "+700원" and plain_rows[1]["합계"] == "+700원"
    assert masked_rows[0]["잃은 매출"] == "-66.7%p"


def test_note_explains_moves_inside_walkerhill():
    # 워커힐 안에서 옮긴 방문은 옮겨 온 매출과 잃은 매출에 함께 들어 있다. 워커힐 전체로는 그 차이만 남는다고 적는다.
    found = _inside_breakdown()
    plain = breakdown_note(found, masked=False)
    assert "변화(−300원)" in plain and "옮겨 온 매출(+700원)" in plain and "그 차이(−300원)" in plain
    masked = breakdown_note(found, masked=True)
    assert "원" not in masked and "-20.0%p" in masked and "금액은 가립니다" in masked
    assert "변화율(-20.0%)" in masked  # 다섯 갈래의 합은 몫(%p)이 아니라 변화율(%)이다
    assert "워커힐 안에서" not in breakdown_note(Breakdown(1500, 0, _groups(), []), masked=False)


def _show_example_comparison(runs_dir: str) -> None:
    from pathlib import Path as _Path

    from app.compare import compare as _compare
    from app.results import load_run as _load_run
    from app.simulator import show_comparison

    runs = _Path(runs_dir)
    comparison = _compare(_load_run(runs / "20261117-101500-baseline"), _load_run(runs / "20261117-103000-competitor-chinese-discount"))
    show_comparison(comparison, {}, "할인")


def test_screen_draws_the_five_groups():
    app = AppTest.from_function(_show_example_comparison, args=(str(RUNS),), default_timeout=60)
    app.run()
    assert not app.exception
    cells = [m.value for m in app.markdown]
    for _, label, _, _ in GROUPS:
        assert any(c.startswith(f":small[{label}]") for c in cells), label
    lost = next(c for c in cells if c.startswith(":small[잃은 매출]"))
    assert ":red[−" in lost and "원]" in lost
    assert any("다섯 갈래를 더하면" in c.value for c in app.caption)


def test_runs_made_from_the_screen_carry_a_matching_breakdown(tmp_path: Path):
    # 화면의 "기본 시나리오와 비교하기"와 같은 흐름으로 새로 돌린 상황 실행에는 엔진이 쓴 나누기가 있고, 원장으로 낸 변화와 맞는다.
    from app.runs import EXAMPLE_VENUES, simulate

    root = tmp_path / "try-example"
    shutil.copytree(REPO_ROOT / "tests" / "fixtures" / "example", root)
    result = simulate(
        root, REPO_ROOT, "sample", "competitor-chinese-discount",
        ["family-elders"], ["meal-dinner-weekend"], list(EXAMPLE_VENUES), False, is_example=True,
    )  # fmt: skip
    assert result.ok and result.scenario is not None
    assert (result.scenario.run_dir / "changes.json").is_file()
    comparison = compare(load_run(result.baseline.run_dir), load_run(result.scenario.run_dir))
    assert comparison.breakdown is not None
    assert comparison.breakdown.total == comparison.total_after - comparison.total_before
