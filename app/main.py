"""화면의 뼈대. 공통 틀이 돌아가는지 확인하려고 둔 것이다.

화면 담당이 T09 에서 이 파일을 채운다. 지금은 예시 파일(tests/fixtures/example)을 읽어 보여 주기만 한다.

띄우는 법 (저장소 맨 위에서):

    uv run python -m streamlit run app/main.py
"""

from pathlib import Path

import streamlit as st

from engine.formats import KO, LEDGER_COLUMNS, LedgerRow, RunRecord, Venue, read_model
from engine.formats.io import read_csv

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = REPO_ROOT / "tests" / "fixtures" / "example"

st.set_page_config(page_title="워커힐 다이닝 페르소나 시뮬레이터", layout="wide")
st.title("워커힐 다이닝 페르소나 시뮬레이터")
st.caption("화면의 모든 금액은 가상 값입니다. 실제 매출이나 실제 구매율이 아닙니다.")
st.info(
    "공통 틀이 돌아가는지 확인하는 화면입니다. "
    "아래 내용은 지어낸 예시 파일(tests/fixtures/example)을 읽어 보여 준 것입니다."
)

st.subheader("업장 (예시)")
venues = [read_model(path, Venue) for path in sorted((EXAMPLE_ROOT / "data" / "venues").glob("*.json"))]
st.dataframe(
    [
        {
            "업장": venue.name,
            "호텔": venue.hotel,
            "구분": KO["choice_kind"]["competitor" if venue.is_competitor else "walkerhill"],
            "이용 상황": ", ".join(KO["occasion"][occasion] for occasion in venue.occasions),
            "상품 수": len(venue.products),
        }
        for venue in venues
    ],
    hide_index=True,
)

st.subheader("실행 결과 (예시)")
names = {venue.venue_id: venue.name for venue in venues}
for run_dir in sorted((EXAMPLE_ROOT / "engine" / "samples" / "runs").iterdir()):
    record = read_model(run_dir / "run.json", RunRecord)
    rows = [LedgerRow.from_row(row) for row in read_csv(run_dir / "ledger.csv", LEDGER_COLUMNS)]
    st.markdown(f"**상황 `{record.scenario_id}`** · 모델 `{record.llm.model}` · 방문 {record.counts.visits}건")
    st.dataframe(
        [
            {
                "페르소나": row.persona_id,
                "조건": row.condition_id,
                "고른 곳": names.get(row.venue_id or "", KO["choice_kind"]["none"]),
                "구분": KO["choice_kind"][row.choice_kind],
                "낸 금액 (가상, 원)": row.paid,
                "워커힐 매출 (가상, 원)": row.revenue_net,
                "고른 이유": row.reason_text,
            }
            for row in rows
        ],
        hide_index=True,
    )
