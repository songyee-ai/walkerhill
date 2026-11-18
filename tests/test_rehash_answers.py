"""요청에 상황의 이름이 없는 것과, 그 전에 받은 답의 변환 (T121, docs/FORMATS.md 9절·10.3절)."""

from datetime import timedelta
from pathlib import Path

import pytest

import engine.__main__ as cli
from engine.formats.run import compute_request_hash
from tests.conftest import BASELINE_RUN, COMPETITOR_RUN, load_json, save_json
from tests.test_engine import DINNER, NOW, pick_geumryong, play
from tests.test_scenarios import (
    ELDERS,
    no_format_errors,
    pick_venue,
    play_scenario,
    promo,
    run_scenario,
    write_scenario,
)
from tools.rehash_answers import main, rehash_tree

RUNS = Path("engine/samples/runs")


def make_old(run_dir: Path, scenario_id: str) -> str:
    """실행 폴더의 답 하나를 T121 전의 모양으로 되돌린다: 요청에 scenario_id 를 넣고 해시, 파일 이름, 원장을 옛 값으로. 옛 해시를 돌려준다."""
    (path,) = (run_dir / "llm").glob("*.json")
    data = load_json(path)
    data["request"] = {"prompt_version": data["request"]["prompt_version"], "scenario_id": scenario_id} | data["request"]
    old_hash = compute_request_hash(data["provider"], data["model"], data["request"])
    ledger = run_dir / "ledger.csv"
    ledger.write_bytes(ledger.read_bytes().replace(path.stem.encode(), old_hash.encode()))
    path.unlink()
    save_json(run_dir / "llm" / f"{old_hash}.json", data | {"request_hash": old_hash})
    return old_hash


def test_request_does_not_carry_the_scenario(example_copy):
    base = play(example_copy, pick_geumryong)
    assert "scenario_id" not in base.requests[f"{ELDERS}__{DINNER}"].model_dump()


def test_visit_the_scenario_does_not_touch_replays_the_baseline_answer(example_copy):
    """상황이 그 방문의 후보를 바꾸지 않으면 요청이 기준과 같다. 다른 답을 정해 둬도 기준의 답을 재생한다."""
    base = play(example_copy, pick_geumryong)
    weekday_only = write_scenario(
        example_copy,
        "our_promo",
        {"op": "add_promotion", "venue_id": "geumryong", "promotion": promo("weekday-sale", day_type="weekday")},
        scenario_id="geumryong-weekday-sale",
    )
    played = play_scenario(example_copy, weekday_only, pick_venue("examplehotel-chinese"), base)
    visit_id = f"{ELDERS}__{DINNER}"
    assert played.requests[visit_id] == base.requests[visit_id]  # 주말 저녁의 후보는 평일 할인으로 달라지지 않는다
    (row,), (base_row,) = played.rows, base.rows
    assert (row.venue_id, row.llm_call, row.request_hash) == ("geumryong", "replay", base_row.request_hash)
    assert (row.reason_text, row.paid) == (base_row.reason_text, base_row.paid)
    no_format_errors(example_copy)


def test_answers_are_looked_up_from_the_earliest_run(example_copy):
    folders = cli.earlier_answers(example_copy, "sample")
    assert [f.parent.name for f in folders] == [BASELINE_RUN, COMPETITOR_RUN]


def test_old_answers_are_rehashed_into_the_new_shape(example_copy, capsys):
    runs = example_copy / RUNS
    before = {p: p.read_bytes() for p in runs.rglob("*") if p.is_file()}
    old = [make_old(runs / BASELINE_RUN, "baseline"), make_old(runs / COMPETITOR_RUN, "competitor-chinese-discount")]
    assert all((runs / name / "llm" / f"{h}.json").is_file() for name, h in zip((BASELINE_RUN, COMPETITOR_RUN), old, strict=True))

    assert main(["--check", str(runs)]) == 1  # 바꿀 것이 있다. 아무것도 쓰지 않는다
    assert rehash_tree(runs, write=False) == (2, 2)
    assert main([str(runs)]) == 0
    # 파일 이름, 요청, 원장의 해시가 변환 전의 예시와 글자까지 같아진다. 옛 파일은 남지 않는다.
    assert {p: p.read_bytes() for p in runs.rglob("*") if p.is_file()} == before
    assert main(["--check", str(runs)]) == 0 and rehash_tree(runs) == (0, 0)  # 다시 돌려도 바꿀 것이 없다
    no_format_errors(example_copy)


def test_rehash_stops_when_two_old_answers_become_one_name_with_different_content(example_copy):
    run_dir = example_copy / RUNS / BASELINE_RUN
    (new,) = (run_dir / "llm").glob("*.json")
    kept = new.read_bytes()
    old = load_json(new)
    old["request"]["scenario_id"] = "baseline"
    old["raw_text"] = "다른 답"
    save_json(run_dir / "llm" / "0123456789abcdef.json", old)
    with pytest.raises(ValueError, match="내용이 다른 같은 이름의 파일"):
        rehash_tree(example_copy / RUNS)
    assert new.read_bytes() == kept and (run_dir / "llm" / "0123456789abcdef.json").is_file()  # 아무것도 쓰지 않았다


def test_engine_stops_before_running_on_old_answers(example_copy):
    """옛 모양의 답은 해시가 달라 조용히 재생되지 않는다. LLM 을 새로 부르기 전에 멈추고 변환을 알린다."""
    base = play(example_copy, pick_geumryong)
    make_old(example_copy / RUNS / COMPETITOR_RUN, "competitor-chinese-discount")
    old_folder = example_copy / RUNS / COMPETITOR_RUN / "llm"
    with pytest.raises(ValueError, match="tools.rehash_answers"):
        run_scenario(
            example_copy, "competitor-chinese-discount", weights_from=base.run_dir.name, answers=[old_folder], now=NOW + timedelta(hours=3)
        )
    # 실행 폴더는 만들어지지 않는다
    assert not list((example_copy / RUNS).glob(f"{NOW + timedelta(hours=3):%Y%m%d-%H%M%S}-*"))
