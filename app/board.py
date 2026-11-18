"""식당가 보기: 식당마다 누가 남고, 새로 오고, 떠났는지와 가상 매출의 변화를 모은다 (T21).

11-16 팀 결정으로 지도 대신, 식당 카드와 페르소나만으로 행동 변화를 보여 준다. 그리는 것은 app/simulator.py 다.
"""

from dataclasses import dataclass, field

from app.compare import Comparison, Move, Place
from engine.formats import KO, WALKERHILL_VENUE_IDS

# 카드의 순서: 워커힐 업장을 먼저, 그다음 경쟁 업장, 마지막에 이용하지 않음.
KIND_ORDER = {"walkerhill": 0, "competitor": 1, "none": 2}

# 업장 정의 파일이 없을 때(예시 자료) 카드에 쓸 이름. docs/PRD.md 3절의 표와 같다.
WALKERHILL_NAMES = {
    "geumryong": "금룡",
    "pizzahill": "피자힐",
    "thebuffet": "더뷔페",
    "ondal": "온달",
    "lepassage": "르파사쥬",
    "myongwolgwan": "명월관",
    "pavilion": "더파빌리온",
    "moegi": "모에기",
}


@dataclass
class VenueCard:
    place: Place
    name: str
    stayed: list[Move] = field(default_factory=list)
    arrived: list[Move] = field(default_factory=list)
    left: list[Move] = field(default_factory=list)
    # 워커힐 업장만 가상 매출이 있다 (경쟁 업장과 이용하지 않음은 매출을 세지 않는다. PRD 7.2절).
    revenue_before: int | None = None
    revenue_after: int | None = None

    @property
    def kind_label(self) -> str:
        return KO["choice_kind"][self.place.kind]

    @property
    def guests_before(self) -> float:
        return sum(m.represented for m in self.stayed + self.left)

    @property
    def guests_after(self) -> float:
        return sum(m.represented for m in self.stayed + self.arrived)

    @property
    def changed(self) -> bool:
        return bool(self.arrived or self.left)


def venue_cards(comparison: Comparison, names: dict[str, str], always: list[str] | None = None) -> list[VenueCard]:
    """식당 카드. `always` 의 워커힐 업장은 손님이 없어도 카드를 둔다 (식당가 전체가 보이게)."""
    names = WALKERHILL_NAMES | names
    cards: dict[Place, VenueCard] = {}

    def card(place: Place) -> VenueCard:
        if place not in cards:
            label = KO["choice_kind"]["none"] if place.kind == "none" else names.get(place.venue_id or "", place.venue_id or "")
            cards[place] = VenueCard(place, label)
        return cards[place]

    for venue_id in always or []:
        if venue_id in WALKERHILL_VENUE_IDS:
            card(Place("walkerhill", venue_id))
    for move in comparison.moves:
        if move.move == "failed":
            continue
        if move.before == move.after:
            card(move.after).stayed.append(move)
        else:
            card(move.before).left.append(move)
            card(move.after).arrived.append(move)
    for change in comparison.venues:
        target = card(Place("walkerhill", change.venue_id))
        target.revenue_before, target.revenue_after = change.before, change.after
    for target in cards.values():
        if target.place.kind == "walkerhill" and target.revenue_before is None:
            target.revenue_before = target.revenue_after = 0
    return sorted(cards.values(), key=lambda c: (KIND_ORDER[c.place.kind], not c.changed, c.name))


def pct_change(before: float, after: float) -> str:
    """변화율. 평소가 0 이면 비율을 낼 수 없어 "새로 생김"으로 적는다."""
    if before == 0:
        return "새로 생김" if after else "변화 없음"
    return f"{(after - before) / before:+.0%}"


def index_text(before: float, value: float) -> str:
    """기본 시나리오를 100 으로 둔 지수. 금액·손님 수를 가리는 실행에서 쓴다 (app/results.py 의 `shows_numbers`).

    기본 시나리오가 0 이면 지수를 낼 수 없어 "없음" 또는 "새로 생김"으로 적는다.
    """
    if before == 0:
        return "새로 생김" if value else "없음"
    return f"지수 {value / before * 100:,.0f}"
