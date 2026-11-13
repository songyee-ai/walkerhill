"""영역끼리 주고받는 파일의 모양 (docs/FORMATS.md).

문서가 기준이고, 여기 있는 모델은 그 문서를 코드로 옮긴 것이다.
형식을 바꿀 때는 문서, 이 모델, tests/fixtures/example 의 예시 파일을 함께 고친다.
"""

from engine.formats.choice import (
    Candidate,
    Choice,
    ChoiceRequest,
    ChoiceResponse,
    Option,
    RunCondition,
    problems_in_response,
)
from engine.formats.codes import KO, WALKERHILL_VENUE_IDS
from engine.formats.conditions import AssumedSplit, Condition, ConditionBundle
from engine.formats.evidence import REVIEW_COLUMNS, ReviewLabel, Vocab
from engine.formats.io import read_model
from engine.formats.money import (
    apply_pct,
    change_price,
    net_of_tax,
    round_half_up,
    to_paid_price,
    weighted_amount,
)
from engine.formats.persona import Persona, merge_persona_layers, merged_persona
from engine.formats.run import (
    LEDGER_COLUMNS,
    Calibration,
    LedgerRow,
    RunRecord,
    SavedResponse,
    Validation,
    compute_request_hash,
)
from engine.formats.scenario import Scenario
from engine.formats.summary import SUMMARY_COLUMNS, SummaryRow
from engine.formats.venue import Product, Promotion, Slot, Venue

__all__ = [
    "KO",
    "LEDGER_COLUMNS",
    "REVIEW_COLUMNS",
    "SUMMARY_COLUMNS",
    "WALKERHILL_VENUE_IDS",
    "AssumedSplit",
    "Calibration",
    "Candidate",
    "Choice",
    "ChoiceRequest",
    "ChoiceResponse",
    "Condition",
    "ConditionBundle",
    "LedgerRow",
    "Option",
    "Persona",
    "Product",
    "Promotion",
    "ReviewLabel",
    "RunCondition",
    "RunRecord",
    "SavedResponse",
    "Scenario",
    "SummaryRow",
    "Validation",
    "Slot",
    "Venue",
    "Vocab",
    "apply_pct",
    "change_price",
    "compute_request_hash",
    "merge_persona_layers",
    "merged_persona",
    "net_of_tax",
    "problems_in_response",
    "read_model",
    "round_half_up",
    "to_paid_price",
    "weighted_amount",
]
