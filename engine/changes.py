"""매출 변화 나누기 (T210, docs/FORMATS.md 10.6절, docs/PRD.md 8절의 1단계).

기준 실행과 상황 실행의 원장을 방문마다 견줘 워커힐 업장마다의 변화를 새로 들어온 매출, 옮겨 온 매출, 잃은 매출,
가격 효과, 주문 변화로 나눈다. 두 실행은 같은 페르소나·조건·가중치로 돌아 방문마다 대표하는 팀 수가 같다.

방문은 몫으로 나뉘어 여러 곳에 간다 (T212, 원장의 `choice_share`). 그래서 업장마다 이렇게 나눈다 (11-20 wilstein91 결정, 비례 배분):
- 두 실행에서 그 업장에 남은 몫(둘 가운데 작은 몫)의 금액 차이는 가격 효과나 주문 변화다.
- 늘어난 몫은 몫이 줄어든 곳들에서, 줄어든 만큼에 비례해 왔다고 본다 (새로 들어옴, 경쟁에서, 워커힐 안에서).
- 줄어든 몫은 몫이 늘어난 곳들로, 늘어난 만큼에 비례해 갔다고 본다 (잃은 매출).
답 하나로 고른 방문(몫이 0 아니면 1)은 이 규칙이 "어디에 갔나"로 나누던 11-19 의 규칙과 같은 결과를 낸다.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from engine.formats.changes import PARTS, Changes, Part
from engine.formats.run import SEASON_GAP_REASON, LedgerRow

# 방문이 간 곳: (종류, venue_id). "이용하지 않음"은 ("none", None).
PlaceKey = tuple[str, str | None]
NONE_PLACE: PlaceKey = ("none", None)
# 몫의 차이가 이보다 작으면 같은 것으로 본다 (소수로 나눈 끝자리).
SHARE_TOLERANCE = 1e-9


@dataclass
class _Visit:
    represented: float = 0.0
    failed: bool = False
    # 곳마다의 고른 몫 (`choice_share`). 파는 달이 아닌 몫(`season_gap_of`)은 그 곳의 몫 안에 있다.
    shares: dict[PlaceKey, float] = field(default_factory=dict)
    # 워커힐 업장마다의 가중 매출과, 고른 상품·수량 (가격 효과와 주문 변화를 가른다).
    revenue: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    items: dict[str, list[tuple[str, int, float]]] = field(default_factory=lambda: defaultdict(list))
    # 워커힐 업장마다 받은 할인이 있는가 (원장의 `discount`, 가중치를 곱하기 전).
    discounted: dict[str, bool] = field(default_factory=lambda: defaultdict(bool))

    def share(self, place: PlaceKey) -> float:
        return self.shares.get(place, 0.0)

    def top(self) -> PlaceKey:
        """몫이 가장 큰 곳. 같으면 워커힐, 경쟁, 이용하지 않음 순서이고 그다음은 venue_id 순서다."""
        order = {"walkerhill": 0, "competitor": 1, "none": 2}
        if not self.shares:
            return NONE_PLACE
        return min(self.shares, key=lambda p: (-round(self.shares[p], 9), order[p[0]], p[1] or ""))


def _visits(rows: list[LedgerRow]) -> dict[str, _Visit]:
    out: dict[str, _Visit] = {}
    for row in rows:
        visit = out.setdefault(row.visit_id, _Visit())
        visit.represented = max(visit.represented, row.represented)
        if row.status != "ok":
            visit.failed = True
            continue
        if row.choice_kind == "none":
            # 파는 달이 아닌 몫의 줄은 그 곳의 몫에 이미 들어 있다. 옛 원장(11-20 전)은 season_gap_of 가 비어 있어 이유 글로 가른다.
            if row.season_gap_of is None and row.reason_text != SEASON_GAP_REASON:
                visit.shares[NONE_PLACE] = row.choice_share
            continue
        place: PlaceKey = (row.choice_kind, row.venue_id)
        visit.shares[place] = row.choice_share
        if row.choice_kind == "walkerhill" and row.venue_id:
            visit.revenue[row.venue_id] += row.weighted_revenue
            visit.items[row.venue_id].append((row.product_id or "", row.quantity, row.counted_share))
            visit.discounted[row.venue_id] = visit.discounted[row.venue_id] or row.discount > 0
    return out


_PART_IN: dict[str, Part] = {"none": "new", "competitor": "from_competitor", "walkerhill": "from_walkerhill"}
_PART_OUT: dict[str, Part] = {"none": "to_none", "competitor": "to_competitor", "walkerhill": "to_walkerhill"}


def _split(amount: float, weights: dict[str, float]) -> dict[str, float]:
    """금액을 갈래마다 무게에 비례해 나눈다 (반올림 전)."""
    total = sum(weights.values())
    return {key: amount * weight / total for key, weight in weights.items() if weight > 0}


def _whole(target: int, parts: list[tuple[Part, float]]) -> list[tuple[Part, int]]:
    """반올림 전 금액들을 원 단위로 바꾸되 합이 `target` 과 같게 한다 (나머지가 큰 것부터 1원씩 더하거나 뺀다)."""
    floors = [(part, int(amount // 1), amount - amount // 1) for part, amount in parts]
    gap = target - sum(f for _, f, _ in floors)
    order = sorted(range(len(floors)), key=lambda i: -floors[i][2])
    whole = [[part, value] for part, value, _ in floors]
    for i in order[: max(gap, 0)]:
        whole[i][1] += 1
    for i in order[::-1][: max(-gap, 0)]:
        whole[i][1] -= 1
    return [(part, value) for part, value in whole]


def _venue_parts(venue_id: str, b: _Visit, a: _Visit) -> tuple[int, int, list[tuple[Part, int]]]:
    """한 방문에서 워커힐 업장 하나의 변화를 갈래로 나눈다. (기준의 금액, 상황의 금액, 갈래)."""
    place: PlaceKey = ("walkerhill", venue_id)
    rb_raw, ra_raw = b.revenue.get(venue_id, 0.0), a.revenue.get(venue_id, 0.0)
    rb, ra = round(rb_raw), round(ra_raw)
    sb, sa = b.share(place), a.share(place)
    kept = min(sb, sa)
    raw: list[tuple[Part, float]] = []
    if kept > SHARE_TOLERANCE:
        same_order = sorted(b.items[venue_id]) == sorted(a.items[venue_id])
        raw.append(("price" if same_order else "order", ra_raw * kept / sa - rb_raw * kept / sb))
    # 다른 곳들의 몫이 얼마나 줄고 늘었나 (이 업장은 빼고, 종류마다 모은다).
    # 집합을 도는 순서는 파이썬 프로세스마다 달라, 정해진 순서로 돈다 (엔진과 형식 검사가 같은 결과를 내야 한다).
    others = sorted((set(b.shares) | set(a.shares)) - {place}, key=lambda p: (p[0], p[1] or ""))
    lost_by: dict[str, float] = defaultdict(float)
    gained_by: dict[str, float] = defaultdict(float)
    for other in others:
        diff = a.share(other) - b.share(other)
        if diff < 0:
            lost_by[other[0]] += -diff
        else:
            gained_by[other[0]] += diff
    if sa - sb > SHARE_TOLERANCE:
        gain = ra_raw * (sa - sb) / sa
        raw += [(_PART_IN[kind], amount) for kind, amount in _split(gain, lost_by).items()] or [("new", gain)]
    elif sb - sa > SHARE_TOLERANCE:
        loss = -rb_raw * (sb - sa) / sb
        raw += [(_PART_OUT[kind], amount) for kind, amount in _split(loss, gained_by).items()] or [("to_none", loss)]
    if not raw:
        raw = [("price", ra_raw - rb_raw)]
    # 갈래를 정해진 순서로 둔다. 1원을 맞출 때 나머지가 같은 갈래끼리의 순서도 이것으로 정해진다.
    raw.sort(key=lambda item: PARTS.index(item[0]))
    return rb, ra, _whole(ra - rb, raw)


def _promo_shares(b: _Visit, a: _Visit) -> dict[str, float]:
    """상황에서 워커힐 업장의 할인을 받은 몫을, 기준에서도 그 업장에 오던 몫과 새로 온 몫으로 나눈다 (FORMATS 10.6절, T215)."""
    would_come = drawn = 0.0
    for venue_id, discounted in a.discounted.items():
        if not discounted:
            continue
        place: PlaceKey = ("walkerhill", venue_id)
        stayed = min(b.share(place), a.share(place))
        would_come += stayed
        drawn += a.share(place) - stayed
    # 몫을 여럿 더하면 소수의 끝자리에서 1 을 조금 넘을 수 있다 (예: 1.0000000000000002). 몫은 1 을 넘지 않는다.
    return {"would_come": min(would_come, 1.0), "drawn": min(drawn, 1.0)}


def _promo(shares: dict[str, float]) -> str:
    """할인을 받은 몫으로 본 방문의 구분. 할인을 받은 몫이 없으면 `none`, 있으면 둘 가운데 큰 쪽이다 (같으면 `would_come`)."""
    if shares["would_come"] <= SHARE_TOLERANCE and shares["drawn"] <= SHARE_TOLERANCE:
        return "none"
    return "would_come" if shares["would_come"] >= shares["drawn"] else "drawn"


def _place(key: PlaceKey) -> dict[str, str | None]:
    return {"kind": key[0], "venue_id": key[1]}


def _place_shares(visit: _Visit) -> list[dict[str, object]]:
    return [{**_place(key), "share": share} for key, share in sorted(visit.shares.items(), key=lambda kv: (kv[0][0], kv[0][1] or ""))]


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
            rb, ra, found = _venue_parts(venue_id, b, a)
            before_total[venue_id] += rb
            after_total[venue_id] += ra
            for part, amount in found:
                venue_parts[venue_id][part] += amount
                parts.append({"venue_id": venue_id, "part": part, "amount": amount})
        promo_shares = _promo_shares(b, a)
        visits.append(
            {
                "visit_id": visit_id,
                "represented": b.represented,
                "before": _place(b.top()),
                "after": _place(a.top()),
                "before_shares": _place_shares(b),
                "after_shares": _place_shares(a),
                "parts": parts,
                "promo": _promo(promo_shares),
                "promo_shares": promo_shares,
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
