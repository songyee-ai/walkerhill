"""매출 변화 나누기: 엔진이 쓴 `changes.json` 을 화면의 다섯 갈래로 묶는다 (T124, docs/PRD.md 8절의 1단계, FORMATS.md 10.6절).

계산은 엔진이 한다 (`engine/changes.py`, T210). 화면은 갈래를 묶어 보이기만 한다.
PRD 8절의 넷(새로 들어온 매출, 옮겨 온 매출, 잃은 매출, 단가 효과) 가운데 단가 효과를 가격 효과와 주문 변화로 나눠 다섯이다
(T210 의 경위: 넷으로는 주문만 바뀐 방문이 가격 효과처럼 보였다).
"""

from dataclasses import dataclass
from pathlib import Path

from engine.formats import read_model
from engine.formats.changes import ChangeParts, Changes

# (키, 이름, 묶는 엔진의 갈래, 뜻). 순서는 화면에 보이는 순서다.
GROUPS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("new", "새로 들어온 매출", ("new",), "기본 시나리오에서 외식하지 않던 방문이 워커힐 업장을 고른 매출입니다."),
    (
        "moved_in",
        "옮겨 온 매출",
        ("from_competitor", "from_walkerhill"),
        "기본 시나리오에서 경쟁 업장이나 다른 워커힐 업장을 고르던 방문이 이 업장으로 옮겨 온 매출입니다.",
    ),
    (
        "lost",
        "잃은 매출",
        ("to_competitor", "to_walkerhill", "to_none"),
        "기본 시나리오에서 이 업장을 고르던 방문이 경쟁 업장, 다른 워커힐 업장, 외식 안 함으로 옮겨 간 매출입니다.",
    ),
    ("price", "가격 효과", ("price",), "같은 업장에서 같은 상품을 같은 수량으로 골랐는데 가격이나 할인만 달라 생긴 차이입니다."),
    ("order", "주문 변화", ("order",), "같은 업장을 골랐지만 상품이나 수량이 달라 생긴 차이입니다."),
)
PART_LABEL = {
    "new": "외식 안 함에서",
    "from_competitor": "경쟁 업장에서",
    "from_walkerhill": "워커힐 안에서",
    "to_competitor": "경쟁 업장으로",
    "to_walkerhill": "워커힐 안으로",
    "to_none": "외식 안 함으로",
    "price": "가격·할인",
    "order": "상품·수량",
}
NO_FILE_NOTE = "이 실행에는 매출 변화 나누기(changes.json)가 없습니다. 11-19 전에 돌린 실행이면 다시 돌리면 생깁니다."


@dataclass(frozen=True)
class Group:
    key: str
    label: str
    amount: int
    # 묶은 엔진의 갈래마다의 금액 (도움말에 보인다)
    parts: dict[str, int]
    note: str


@dataclass(frozen=True)
class VenueBreakdown:
    venue_id: str
    before: int
    after: int
    groups: list[Group]

    @property
    def parts_total(self) -> int:
        """갈래의 합. 표의 합계는 이 값을 쓴다 (기간을 더해도 `after` − `before` 와 같다. 11-20 까지의 달 평균은 반올림만큼 달랐다)."""
        return sum(g.amount for g in self.groups)


@dataclass(frozen=True)
class Breakdown:
    # 워커힐 전체의 기본 시나리오 가상 매출. 가릴 때 갈래를 이 값에 견준 비율로 보인다.
    before: int
    total: int
    groups: list[Group]
    venues: list[VenueBreakdown]

    @property
    def inside(self) -> tuple[int, int]:
        """(워커힐 안에서 옮겨 온 금액, 워커힐 안으로 잃은 금액). 워커힐 전체로는 둘을 더한 차액만 남는다."""
        return self.groups[1].parts.get("from_walkerhill", 0), self.groups[2].parts.get("to_walkerhill", 0)


def _groups(parts: ChangeParts | dict[str, int]) -> list[Group]:
    value = parts if isinstance(parts, dict) else parts.model_dump()
    return [
        Group(key, label, sum(value[p] for p in keys), {p: value[p] for p in keys}, note) for key, label, keys, note in GROUPS
    ]


def from_changes(changes: Changes) -> Breakdown:
    venues = [VenueBreakdown(v.venue_id, v.before, v.after, _groups(v.parts)) for v in changes.venues]
    return Breakdown(sum(v.before for v in changes.venues), changes.walkerhill.total, _groups(changes.walkerhill), venues)


def load_breakdown(scen_dir: Path | None, run_id: str, baseline_run_id: str | None) -> Breakdown | None:
    """상황 실행 폴더의 `changes.json`. 없거나, 다른 실행의 것이면 None 이다 (화면은 나누기 없이 그린다)."""
    if scen_dir is None or baseline_run_id is None:
        return None
    path = scen_dir / "changes.json"
    if not path.is_file():
        return None
    try:
        changes = read_model(path, Changes)
    except ValueError:
        # 형식이 바뀌기 전의 파일 (예: 11-20 전에는 방문마다의 할인 칸 `promo` 가 없었다). 나누기 없이 그린다 (T130)
        return None
    if changes.run_id != run_id or changes.baseline_run_id != baseline_run_id:
        return None
    return from_changes(changes)


def _add_groups(lists: list[list[Group]]) -> list[Group]:
    parts = {part: 0 for _, _, keys, _ in GROUPS for part in keys}
    for groups in lists:
        for group in groups:
            for part, amount in group.parts.items():
                parts[part] += amount
    return _groups(parts)


def add_up(breakdowns: list[Breakdown]) -> Breakdown:
    """기간의 달마다 나눈 것을 더한다 (app/compare.py 의 `combine_months` 와 같은 뜻, FORMATS.md 10.1절 "여러 달을 합치는 법", T216).

    갈래·업장·합계를 모두 달마다의 값을 더해 낸다. 11-17 ~ 11-20 에는 달 평균을 냈다.
    """
    if len(breakdowns) == 1:
        return breakdowns[0]
    groups = _add_groups([b.groups for b in breakdowns])
    by_venue: dict[str, list[VenueBreakdown]] = {}
    for b in breakdowns:
        for v in b.venues:
            by_venue.setdefault(v.venue_id, []).append(v)
    venues = [
        VenueBreakdown(venue_id, sum(v.before for v in items), sum(v.after for v in items), _add_groups([v.groups for v in items]))
        for venue_id, items in sorted(by_venue.items())
    ]
    return Breakdown(sum(b.before for b in breakdowns), sum(g.amount for g in groups), groups, venues)


def share_text(amount: float, before: float, unit: str = "%p") -> str:
    """기본 시나리오 워커힐 매출에 견준 몫 (%p). 갈래의 몫을 모두 더하면 워커힐 매출의 변화율(%)이다. 금액을 가릴 때 쓴다.

    합계(변화율)를 적을 때는 `unit="%"` 로 부른다.
    """
    if before == 0:
        return "—"
    value = amount / before * 100
    if round(value, 1) == 0:
        return f"0{unit}" if amount == 0 else (f"+0.0{unit}" if amount > 0 else f"-0.0{unit}")
    return f"{value:+.1f}{unit}"
