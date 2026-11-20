"""매출 변화 나누기 (T210, docs/FORMATS.md 10.6절, docs/PRD.md 8절의 1단계).

기준 실행과 상황 실행의 원장을 방문마다 견줘 워커힐 업장마다의 변화를 새로 들어온 매출, 옮겨 온 매출, 잃은 매출,
가격 효과, 주문 변화로 나눈다. 두 실행은 같은 페르소나·조건·가중치로 돌아 방문마다 대표하는 팀 수가 같다.
그래서 갈래는 "어디에 갔나"만 견줘 정하고, 금액은 원장의 `weighted_revenue` 를 그대로 더한다.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from engine.formats.changes import PARTS, Changes, Part
from engine.formats.run import LedgerRow


@dataclass
class _Visit:
    represented: float = 0.0
    failed: bool = False
    kind: str = "none"
    venue_id: str | None = None
    # 워커힐 업장마다의 가중 매출과, 고른 상품·수량 (가격 효과와 주문 변화를 가른다).
    revenue: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    items: dict[str, list[tuple[str, int, float]]] = field(default_factory=lambda: defaultdict(list))
    # 워커힐 업장에서 받은 할인이 있는가 (원장의 `discount`, 가중치를 곱하기 전).
    discounted: bool = False


def _visits(rows: list[LedgerRow]) -> dict[str, _Visit]:
    out: dict[str, _Visit] = {}
    for row in rows:
        visit = out.setdefault(row.visit_id, _Visit())
        visit.represented = max(visit.represented, row.represented)
        if row.status != "ok":
            visit.failed = True
            continue
        if row.choice_kind == "walkerhill" and row.venue_id:
            visit.kind, visit.venue_id = "walkerhill", row.venue_id
            visit.revenue[row.venue_id] += row.weighted_revenue
            visit.items[row.venue_id].append((row.product_id or "", row.quantity, row.counted_share))
            visit.discounted = visit.discounted or row.discount > 0
        elif row.choice_kind == "competitor" and visit.kind != "walkerhill":
            visit.kind, visit.venue_id = "competitor", row.venue_id
    return out


def _part_in(before_kind: str) -> Part:
    """이 업장으로 온 방문의 갈래: 기준에서 어디에 있었나."""
    if before_kind == "none":
        return "new"
    return "from_competitor" if before_kind == "competitor" else "from_walkerhill"


def _part_out(after_kind: str) -> Part:
    """이 업장을 떠난 방문의 갈래: 상황에서 어디로 갔나."""
    if after_kind == "none":
        return "to_none"
    return "to_competitor" if after_kind == "competitor" else "to_walkerhill"


def _promo(b: _Visit, a: _Visit) -> str:
    """상황에서 워커힐 업장의 할인을 받은 방문이, 기준에서도 그 업장에 오던 방문인가 (FORMATS 10.6절의 `promo`, T215)."""
    if a.kind != "walkerhill" or not a.discounted:
        return "none"
    return "would_come" if b.kind == "walkerhill" and b.venue_id == a.venue_id else "drawn"


def decompose(base_rows: list[LedgerRow], scen_rows: list[LedgerRow], baseline_run_id: str, run_id: str) -> Changes:
    """두 원장으로 `changes.json` 의 내용을 낸다.

    한쪽 실행에서라도 실패했거나 한쪽에만 있는 방문은 두 실행 모두에서 뺀다 (화면의 비교와 같다, `app/compare.py`).
    """
    before, after = _visits(base_rows), _visits(scen_rows)
    excluded = sorted(v for v in set(before) | set(after) if v not in before or v not in after or before[v].failed or after[v].failed)
    venue_parts: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(PARTS, 0))
    before_total: dict[str, int] = defaultdict(int)
    after_total: dict[str, int] = defaultdict(int)
    visits = []
    for visit_id in sorted(set(before) & set(after)):
        if visit_id in excluded:
            continue
        b, a = before[visit_id], after[visit_id]
        parts = []
        for venue_id in sorted(set(b.revenue) | set(a.revenue)):
            rb, ra = round(b.revenue.get(venue_id, 0.0)), round(a.revenue.get(venue_id, 0.0))
            before_total[venue_id] += rb
            after_total[venue_id] += ra
            at_before = b.kind == "walkerhill" and b.venue_id == venue_id
            at_after = a.kind == "walkerhill" and a.venue_id == venue_id
            if at_before and at_after:
                same_order = sorted(b.items[venue_id]) == sorted(a.items[venue_id])
                found: list[tuple[Part, int]] = [("price" if same_order else "order", ra - rb)]
            elif at_after:
                found = [(_part_in(b.kind), ra)]
            else:
                found = [(_part_out(a.kind), -rb)]
            for part, amount in found:
                venue_parts[venue_id][part] += amount
                parts.append({"venue_id": venue_id, "part": part, "amount": amount})
        visits.append(
            {
                "visit_id": visit_id,
                "represented": b.represented,
                "before": {"kind": b.kind, "venue_id": b.venue_id},
                "after": {"kind": a.kind, "venue_id": a.venue_id},
                "parts": parts,
                "promo": _promo(b, a),
            }
        )
    venues = [
        {
            "venue_id": venue_id,
            "before": before_total[venue_id],
            "after": after_total[venue_id],
            "parts": {**venue_parts[venue_id], "total": after_total[venue_id] - before_total[venue_id]},
        }
        for venue_id in sorted(venue_parts)
    ]
    walkerhill = {part: sum(v["parts"][part] for v in venues) for part in (*PARTS, "total")}
    return Changes.model_validate(
        {
            "format_version": 1,
            "run_id": run_id,
            "baseline_run_id": baseline_run_id,
            "excluded_visits": excluded,
            "walkerhill": walkerhill,
            "venues": venues,
            "visits": visits,
        }
    )
