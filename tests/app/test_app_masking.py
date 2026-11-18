"""기본 데이터로 돌린 실행에서 금액·손님 수·채운 단가를 가린다 (PRD 17절, 11-18 팀장 회신. 정하기 전에도 가리는 쪽이 기본).

예시 실행 둘을 임시 폴더에 베껴 `data_mode` 를 `private` 으로, 기준 실행에서 고른 상품 하나를 `filled_products` 로 바꿔 본다.
값은 모두 예시 묶음의 지어낸 값이다. 실제 기본 데이터로 돌린 실행은 쓰지 않는다.
"""

import csv
import json
import shutil
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.board import index_text  # noqa: E402
from app.compare import compare  # noqa: E402
from app.evidence import calibration_rows, load_calibration  # noqa: E402
from app.results import (  # noqa: E402
    FILLED_PRICE,
    FILLED_PRICE_SHORT,
    MASKED_AMOUNT_NOTE,
    MASKED_IN_TEXT,
    load_run,
    mask_amounts,
    shows_numbers,
    visit_table,
    visit_view,
)
from app.street import render_scene, scene_from_comparison  # noqa: E402
from app.validation import validation_rows  # noqa: E402
from engine.formats import LEDGER_COLUMNS, Validation  # noqa: E402
from engine.formats.io import read_csv  # noqa: E402

RUNS = REPO_ROOT / "tests" / "fixtures" / "example" / "engine" / "samples" / "runs"
BASE, SCEN = "20261117-101500-baseline", "20261117-103000-competitor-chinese-discount"
PERSONA, CONDITION = "family-elders", "meal-dinner-weekend"


def _private_copy(tmp_path: Path) -> tuple[Path, str]:
    """예시 실행을 기본 데이터 실행처럼 바꾼 사본과, 채운 단가로 둔 상품(`<venue_id>:<product_id>`)."""
    runs = tmp_path / "runs"
    shutil.copytree(RUNS, runs)
    chosen = next(
        row for row in read_csv(runs / BASE / "ledger.csv", LEDGER_COLUMNS) if row["persona_id"] == PERSONA and row["product_id"]
    )
    filled = f"{chosen['venue_id']}:{chosen['product_id']}"
    for run_id in (BASE, SCEN):
        path = runs / run_id / "run.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["data_mode"] = "private"
        record["filled_products"] = [filled]
        record["skipped_products"] = [p for p in record["skipped_products"] if p != filled]
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return runs, filled


def test_index_is_100_at_the_baseline():
    assert index_text(200, 200) == "지수 100"
    assert index_text(200, 150) == "지수 75"
    assert index_text(0, 5) == "새로 생김" and index_text(0, 0) == "없음"


def test_private_run_hides_filled_prices_but_sample_run_does_not(tmp_path: Path):
    runs, filled = _private_copy(tmp_path)
    base = load_run(runs / BASE)
    assert not shows_numbers(base.record)
    view = visit_view(base, PERSONA, CONDITION)
    assert view.hidden and all(line.hidden for line in view.lines)
    [row] = [r for r in visit_table(base) if r["낸 금액 (가상, 원)"] == FILLED_PRICE]
    assert row["워커힐 매출 (가상, 세금 뺀 원)"] == FILLED_PRICE
    # 상황 실행에서는 그 업장을 고르지 않았다. "가장 싼 주문"에 채운 단가가 들 수 있어 가린다.
    scen_view = visit_view(load_run(runs / SCEN), PERSONA, CONDITION)
    hidden = [item for item in scen_view.not_chosen if item.hidden]
    assert len(hidden) == 1 and filled.startswith("geumryong:") and hidden[0].venue == "금룡"
    assert not scen_view.hidden  # 고른 경쟁 업장의 금액은 공식 가격이라 그대로 보인다
    # 가상 예시 값 실행은 지어낸 값이라 아무것도 가리지 않는다.
    sample = load_run(RUNS / BASE)
    assert shows_numbers(sample.record) and not visit_view(sample, PERSONA, CONDITION).hidden


def test_masked_picture_shows_change_rates_not_amounts(tmp_path: Path):
    runs, _ = _private_copy(tmp_path)
    comparison = compare(load_run(runs / BASE), load_run(runs / SCEN))
    names = {"geumryong": "금룡", "examplehotel-chinese": "예시호텔 중식당"}
    args = (comparison, names, {}, ["geumryong"], ["examplehotel-chinese"], "할인")
    masked, _ = render_scene(scene_from_comparison(*args, masked=True))
    plain, _ = render_scene(scene_from_comparison(*args))
    # 가리면 금액(억·만 원, 원)과 손님 수(명)가 없고, 지수와 변화율만 있다.
    for amount in ("억원", "만원", "원 (가상)", "명 (가상)"):
        assert amount not in masked, amount
    assert "지수 100" in masked and "금액은 가림" in masked and MASKED_AMOUNT_NOTE in masked
    assert "-100%" in masked  # 금룡의 매출이 모두 사라진 변화율은 그대로 보인다
    # 가리지 않으면 지금처럼 금액이 보인다.
    assert "(가상 · 일 년 규모)" in plain and "지수 100" not in plain


def test_detail_tab_shows_masked_cells_without_error(tmp_path: Path):
    runs, _ = _private_copy(tmp_path)
    app = AppTest.from_file(str(REPO_ROOT / "app" / "main.py"), default_timeout=60).run()
    app.text_input(key="other_folder").set_value(str(runs)).run()
    app.selectbox(key="run_id").set_value(BASE).run()
    assert not app.exception
    assert any(m.value == FILLED_PRICE_SHORT for m in app.metric)  # 큰 숫자 칸은 짧게, 까닭은 도움말에
    cells = [str(v) for frame in app.dataframe for v in frame.value.to_numpy().ravel()]
    assert FILLED_PRICE in cells


def test_calibration_shows_pass_and_top_match_but_hides_numbers_for_base_data(tmp_path: Path):
    # 보정 결과(T116)는 근거 보기에서 읽는다. 기본 데이터 실행이면 통과·미달과 가장 큰 업장이 같은지만 보인다 (PRD 17절).
    runs, _ = _private_copy(tmp_path)
    calibration = load_calibration(runs / BASE)
    assert calibration is not None
    private = calibration_rows(calibration, load_run(runs / BASE).record, {})
    sample = calibration_rows(calibration, load_run(RUNS / BASE).record, {})
    assert private and len(private) == len(sample)
    for row in private:
        assert set(row) == {"고객군", "페르소나 수", "가장 큰 업장이 같음", "업장별 비중 차이", "결과"}
        assert row["결과"] in ("통과", "미달") and row["가장 큰 업장이 같음"] in ("예", "아니오")
    # 가상 예시 값은 지어낸 값이라 어느 업장인지와 가장 큰 차이까지 보인다.
    assert all("가장 큰 차이 (%p)" in row for row in sample)


def test_amounts_in_text_are_masked():
    assert mask_amounts("1인 48,300원이라 괜찮다") == "1인 (금액 가림)이라 괜찮다"
    assert mask_amounts("4만 8천원 코스와 15만 원 코스") == "(금액 가림) 코스와 (금액 가림) 코스"
    assert mask_amounts("어른 4명, 2시간") == "어른 4명, 2시간"  # 금액이 아닌 숫자는 그대로
    assert mask_amounts(None) is None


def _put_amount_in_reason(run_dir: Path) -> None:
    """기준 실행의 그 방문 이유 문장에 금액을 넣는다 (지어낸 값). 실제 답에서는 채운 단가로 계산한 금액이 나온다."""
    path = run_dir / "ledger.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        if row["persona_id"] == PERSONA and row["reason_text"]:
            row["reason_text"] += " 1인 48,300원이라 괜찮다."
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_reason_amounts_are_masked_only_when_the_visit_bought_a_filled_price(tmp_path: Path):
    # 11-18 borigunbbang: 금액 칸은 "가격 미확인"인데 바로 아래 AI 의 이유 문장에 채운 단가로 계산한 금액이 그대로 보였다.
    runs, _ = _private_copy(tmp_path)
    _put_amount_in_reason(runs / BASE)
    view = visit_view(load_run(runs / BASE), PERSONA, CONDITION)
    assert view.hidden and "48,300원" not in view.reason_text and MASKED_IN_TEXT in view.reason_text
    # 모든 방문 표와 비교(식당가 그림, 한 사람씩 자세히 보기)도 같은 이유를 쓴다.
    assert all("48,300원" not in row["고른 이유"] for row in visit_table(load_run(runs / BASE)))
    comparison = compare(load_run(runs / BASE), load_run(runs / SCEN))
    assert all("48,300원" not in (m.reason_after or "") for m in comparison.moves)
    # 가상 예시 값 실행은 가리지 않는다.
    sample = tmp_path / "sample"
    shutil.copytree(RUNS, sample)
    _put_amount_in_reason(sample / BASE)
    assert "48,300원" in visit_view(load_run(sample / BASE), PERSONA, CONDITION).reason_text


def test_one_persona_groups_carry_the_calibration_limit(tmp_path: Path):
    # 11-18 borigunbbang: 페르소나가 한 명인 고객군은 업장별 차이를 보지 않고 통과했다. 같은 기준으로 통과한 것처럼 보이지 않게 한계를 붙인다.
    runs, _ = _private_copy(tmp_path)
    calibration = load_calibration(runs / BASE)
    group = next(iter(calibration.groups))
    one = calibration.model_copy(update={"groups": {group: calibration.groups[group].model_copy(update={"personas": 1})}})
    [row] = calibration_rows(one, load_run(runs / BASE).record, {})
    assert row["결과"].endswith("보정 한계: 페르소나 1명") and row["업장별 비중 차이"].startswith("보지 않음")
    [row] = calibration_rows(calibration, load_run(runs / BASE).record, {})
    assert "보정 한계" not in row["결과"]  # 페르소나가 둘이면 붙이지 않는다


def test_validation_shows_higher_or_lower_instead_of_counts_for_base_data():
    # 11-18 borigunbbang 알림 ②: 단순 기준은 기본 데이터의 매출로 고른 업장이라, 기본 데이터 실행에서는 건수 대신 높고 낮음만 보인다.
    validation = Validation.model_validate(
        {
            "format_version": 1,
            "created_at": "2026-11-19T15:00:00+09:00",
            "min_reviews": 5,
            "venues": {
                "geumryong": {
                    "n": 12, "enough": True, "venue_match": 8, "venue_match_baseline": 7,
                    "reason_n": 6, "reason_enough": True, "reason_match": 2, "reason_match_baseline": 3,
                },
            },
            "total": {"n": 12, "venue_match": 8, "venue_match_baseline": 7, "reason_n": 6, "reason_match": 2, "reason_match_baseline": 3},
        }
    )  # fmt: skip
    masked = validation_rows(validation, {"geumryong": "금룡"}, masked=True)
    for row in masked:
        assert "같음 (단순 기준)" not in row and "겹침 (단순 기준)" not in row
        assert not any("건 중" in str(value) for value in row.values())
    assert masked[0]["고른 업장이 같음"] == "단순 기준보다 높음" and masked[0]["이유가 겹침"] == "단순 기준보다 낮음"
    plain = validation_rows(validation, {"geumryong": "금룡"})
    assert plain[0]["고른 업장이 같음"] == "12건 중 8건"  # 가상 예시 값 실행은 지금처럼 건수
