"""기본 데이터 집계 파일에서 내는 값 (docs/PRD.md 7.2절, docs/FORMATS.md 3절·5절·8절·10.1절).

엔진은 집계 파일 하나에서 아래를 낸다. 기본 데이터로 돌릴 때는 `private/base/summary.csv`,
가상 예시로 돌릴 때는 `data/samples/base_summary.csv` 를 읽는다.

- 고객군마다 묶음의 비율과, 고객군 배수를 맞출 매출 (`group_revenue`, `condition_ratios`)
- 고객군 배수와 페르소나의 가중치 (`fit_weights`. 기준 상황을 다 돌린 뒤에 원장으로 맞춘다)
- 가격이 빈 상품의 단가 (`fill_prices`)
- LLM 에 보낼 기본 데이터의 요약 (`base_profiles`)
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from engine.formats.codes import WALKERHILL_VENUE_IDS
from engine.formats.conditions import MANUAL_CONDITION_PREFIX, AssumedSplit, Condition
from engine.formats.io import read_csv
from engine.formats.money import round_half_up
from engine.formats.persona import Persona
from engine.formats.run import LedgerRow, Weights
from engine.formats.summary import SUMMARY_COLUMNS, SummaryRow
from engine.formats.venue import Venue

# 끼니를 알 수 없는 식사 매출을 나누는 비율 (engine/conditions.json 의 assumed_splits 에서 이 split_id 를 쓴다).
MEAL_SPLIT_ID = "meal-lunch-dinner"

# 가격이 빈 상품의 단가를 반올림하는 단위 (11-15 팀장이 정함). 채운 단가는 후보의 가격으로 LLM 에 가므로,
# 기본 데이터의 평균 단가가 원 단위 그대로 LLM 과 저장된 응답에 남지 않게 한다.
FILLED_PRICE_UNIT = 100

# 기본 데이터의 요약(base_profile)에서 업장마다 적는 상품의 수.
TOP_PRODUCTS = 3

# 비중을 범주로 바꾸는 기준. 고르게 나눴을 때의 몫(1 ÷ 갈래의 수)과 견준다 (11-15 엔진 담당이 정한 설계 가정).
BUCKET_HIGH = 1.5
BUCKET_MID = 0.5

# 비중을 범주로 바꿀 때의 갈래의 수. 업장은 워커힐 8곳, 이용 상황은 셋, 평일·주말은 둘이다.
SHARE_SPLITS = {"venue_share": len(WALKERHILL_VENUE_IDS), "occasion_share": 3, "day_type_share": 2}

# 근거 등급의 세기. 두 값을 곱한 값의 등급은 약한 쪽이다.
GRADE_STRENGTH = {"internal": 3, "official": 3, "review": 2, "assumption": 1, "unknown": 0}


def summary_path(root: Path, data_mode: str) -> Path:
    """그 자료로 돌릴 때 읽는 집계 파일. 가상 예시로 돌릴 때는 `private/` 를 읽지 않는다."""
    if data_mode == "private":
        return root / "private" / "base" / "summary.csv"
    if data_mode == "sample":
        return root / "data" / "samples" / "base_summary.csv"
    raise ValueError(f"모르는 data_mode 다: {data_mode!r}")


def read_summary(path: Path) -> list[SummaryRow]:
    """집계 파일을 읽는다. 줄 하나라도 형식에 맞지 않으면 멈춘다 (틀린 줄을 빼고 돌리면 가중치가 조용히 틀린다)."""
    if not path.is_file():
        raise FileNotFoundError(f"집계 파일이 없다: {path}")
    rows: list[SummaryRow] = []
    for number, row in enumerate(read_csv(path, SUMMARY_COLUMNS), start=2):
        try:
            rows.append(SummaryRow.from_row(row))
        except ValidationError as exc:
            reason = "; ".join(error["msg"] for error in exc.errors())
            raise ValueError(f"집계 파일 {path} 의 {number}번째 줄이 형식에 맞지 않다: {reason}") from exc
    return rows


def weaker(*grades: str) -> str:
    """가장 약한 근거 등급. 세기가 같으면 앞의 것이다 (페르소나의 가중치는 고객군 배수의 등급을 앞에 둔다)."""
    return min(grades, key=lambda grade: GRADE_STRENGTH[grade])


# ── 묶음의 비율과 고객군의 매출 ──────────────────────────────────────────────


@dataclass
class GroupRevenue:
    """한 고객군의 기본 데이터 매출(세금을 뺀 것)을 묶음의 조건마다 나눈 것."""

    by_condition: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    # 팀이 정한 비율(assumed_splits)로 나눈 매출이 든 조건.
    assumed: set[str] = field(default_factory=set)
    # 팀이 정한 비율로 나눈 매출의 일부만 돌리는 조건에 들었는가 (예: 저녁만 돌림).
    # 그러면 합계 자체가 그 비율에 기대므로, 이 고객군의 비율과 배수는 모두 그 비율의 등급을 따른다.
    split_partly_used: bool = False
    # 나누는 비율의 근거 등급 (engine/conditions.json 의 assumed_splits 에 적힌 것).
    split_grade: str = "assumption"

    def total(self) -> float:
        return sum(self.by_condition.values())


def _meal_from_slots(row: SummaryRow, venues: dict[str, Venue], meals: list[str]) -> str | None:
    """끼니가 빈 식사 줄이라도, 그 요일에 그 상품을 `meals` 가운데 한 끼니에만 팔면 그 끼니다. 정할 수 없으면 None.

    예: "주말 점심과 모든 요일 저녁"에 파는 상품의 평일 줄은 저녁이다 (docs/FORMATS.md 8절: 상품으로 알 수 없을 때만 나눈다).
    """
    venue = venues.get(row.venue_id)
    product = venue.product(row.product_id) if venue else None
    if product is None:
        return None
    sold = [meal for meal in meals if product.sold_at(meal, row.day_type)]
    return sold[0] if len(sold) == 1 else None


def _parts(
    row: SummaryRow, conditions: list[Condition], split: AssumedSplit | None, venues: dict[str, Venue]
) -> list[tuple[str | None, float, bool]]:
    """집계 파일의 한 줄이 묶음의 어느 조건에 얼마씩 드는가: (condition_id, 몫, 팀이 정한 비율로 나눴는가).

    - 식사가 아닌 줄은 이용 상황과 평일·주말이 같은 조건에 든다.
    - 끼니가 있는 식사 줄은 끼니까지 같은 조건에 든다. 조식은 묶음에 없어 어디에도 들지 않는다 (docs/FORMATS.md 6절).
    - 끼니가 빈 식사 줄은, 업장 정의의 파는 때로 끼니가 하나로 정해지면 그 끼니에 든다.
      정해지지 않으면 `assumed_splits` 의 비율로 점심과 저녁에 나눠 든다.
    - 돌리지 않는 조건의 몫은 condition_id 가 None 이다 (부르는 쪽이 버린다).
    """
    if row.occasion != "meal":
        meals: list[tuple[str | None, float, bool]] = [(None, 1.0, False)]
    elif row.meal == "breakfast":
        return []
    elif row.meal is None:
        known = _meal_from_slots(row, venues, list(split.parts) if split else ["lunch", "dinner"])
        if known is not None:
            meals = [(known, 1.0, False)]
        elif split is None:
            raise ValueError(
                f"집계 파일에 끼니가 빈 식사 매출이 있는데 방문 조건 묶음에 나누는 비율('{MEAL_SPLIT_ID}')이 없다"
            )
        else:
            meals = [(meal, part, True) for meal, part in split.parts.items()]
    else:
        meals = [(row.meal, 1.0, False)]
    found: list[tuple[str | None, float, bool]] = []
    for meal, part, assumed in meals:
        matched = [c for c in conditions if c.occasion == row.occasion and c.meal == meal and c.day_type == row.day_type]
        if len(matched) > 1:
            raise ValueError(f"방문 조건 묶음에 같은 때의 조건이 둘 이상 있다: {[c.condition_id for c in matched]}")
        if part > 0:
            found.append((matched[0].condition_id if matched else None, part, assumed))
    return found


def group_revenue(
    rows: list[SummaryRow], conditions: list[Condition], splits: list[AssumedSplit], venues: dict[str, Venue]
) -> dict[str, GroupRevenue]:
    """고객군마다, 돌리는 조건마다의 기본 데이터 매출. 읽은 워커힐 업장(`venues` 가운데 경쟁 업장이 아닌 것)의 줄만 쓴다.

    이 매출이 묶음의 비율(`condition_ratios`)과 고객군 배수(`fit_weights`)의 기준이 된다.
    조식과 돌리지 않는 조건의 매출은 들지 않는다. 업장 정의는 끼니가 빈 줄의 끼니를 정하는 데도 쓴다.
    """
    split = next((s for s in splits if s.split_id == MEAL_SPLIT_ID), None)
    ours = {venue_id: venue for venue_id, venue in venues.items() if not venue.is_competitor}
    groups: dict[str, GroupRevenue] = defaultdict(GroupRevenue)
    for row in rows:
        if row.venue_id not in ours or row.revenue_net == 0:
            continue
        parts = _parts(row, conditions, split, ours)
        used = [(condition_id, part, assumed) for condition_id, part, assumed in parts if condition_id is not None]
        if not used:
            continue
        group = groups[row.customer_group]
        if split is not None:
            group.split_grade = split.grade
        for condition_id, part, assumed in used:
            group.by_condition[condition_id] += row.revenue_net * part
            if assumed:
                group.assumed.add(condition_id)
        if any(assumed for _, _, assumed in parts) and len(used) < len(parts):
            group.split_partly_used = True
    return dict(groups)


def group_venue_revenue(
    rows: list[SummaryRow], conditions: list[Condition], splits: list[AssumedSplit], venues: dict[str, Venue]
) -> dict[str, dict[str, float]]:
    """고객군마다, 워커힐 업장마다의 기본 데이터 매출. 보정의 대조에서 기본 데이터 쪽의 업장별 비중을 내는 데 쓴다 (docs/PRD.md 6.5절).

    `group_revenue` 와 같은 줄을 같은 몫으로 센다: 읽은 워커힐 업장의 줄만, 돌리는 조건에 드는 몫만 넣고 조식과 돌리지 않는 조건은 뺀다.
    그래서 한 고객군의 업장별 매출을 더하면 `group_revenue` 의 그 고객군 합계와 같다 (가상 매출을 맞춘 바로 그 매출이다).
    """
    split = next((s for s in splits if s.split_id == MEAL_SPLIT_ID), None)
    ours = {venue_id: venue for venue_id, venue in venues.items() if not venue.is_competitor}
    groups: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        if row.venue_id not in ours or row.revenue_net == 0:
            continue
        used = sum(part for condition_id, part, _ in _parts(row, conditions, split, ours) if condition_id is not None)
        if used:
            groups[row.customer_group][row.venue_id] += row.revenue_net * used
    return {group: dict(by_venue) for group, by_venue in groups.items()}


def _grade(data_mode: str, found: "GroupRevenue", leans_on_split: bool) -> str:
    """기본 데이터면 `internal`, 가상 예시면 `assumption`. 나누는 비율에 기대는 값이면 그 비율의 등급과 견줘 약한 것이다."""
    grade = "internal" if data_mode == "private" else "assumption"
    return weaker(grade, found.split_grade) if leans_on_split else grade


def condition_ratios(
    revenue: dict[str, GroupRevenue], groups: list[str], condition_ids: list[str], data_mode: str
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, str]]]:
    """고객군마다 묶음의 비율과 그 등급. 비율은 돌리는 조건 안에서 더하면 1 이다.

    등급: 기본 데이터로 돌리면 `internal`. 팀이 정한 비율로 나눈 매출이 든 조건은 그 비율의 등급(지금은 `assumption`)과 견줘 약한 것이다.
    나눈 매출의 일부만 돌리는 조건에 든 고객군(예: 저녁만 돌림)은 합계가 그 비율에 기대므로 모든 조건이 그렇다.
    가상 예시로 돌리면 `internal` 대신 `assumption` 이다 (지어낸 값이다). 그 고객군의 매출이 없으면 비율은 0, 등급은 `unknown` 이다.
    """
    ratios: dict[str, dict[str, float]] = {}
    grades: dict[str, dict[str, str]] = {}
    for group in groups:
        found = revenue.get(group)
        total = found.total() if found else 0.0
        ratios[group], grades[group] = {}, {}
        for condition_id in condition_ids:
            if found is None or total <= 0:
                ratios[group][condition_id], grades[group][condition_id] = 0.0, "unknown"
                continue
            ratios[group][condition_id] = found.by_condition.get(condition_id, 0.0) / total
            leans = condition_id in found.assumed or found.split_partly_used
            grades[group][condition_id] = _grade(data_mode, found, leans)
    return ratios, grades


def fit_weights(
    personas: list[Persona],
    ratios: dict[str, dict[str, float]],
    ratio_grades: dict[str, dict[str, str]],
    revenue: dict[str, GroupRevenue],
    rows: list[LedgerRow],
    data_mode: str,
) -> Weights:
    """기준 상황의 원장으로 고객군 배수를 맞추고 페르소나의 가중치를 낸다 (docs/PRD.md 7.2절).

    고객군 배수 = 그 고객군의 기본 데이터 매출 ÷ (그 고객군 방문들의 세금을 뺀 워커힐 매출 × 고객군 안의 몫 × 묶음의 비율 × 몫의 합).
    그러면 기준 상황에서 그 고객군의 가상 매출 합이 기본 데이터의 매출과 같아진다. 페르소나의 가중치 = 고객군 배수 × 고객군 안의 몫.

    맞출 수 없는 고객군(기본 데이터에 매출이 없거나, 기준 상황에서 워커힐 업장을 고른 방문이 없다)은 배수가 0, 등급이 `unknown` 이다.
    배수의 등급은 기본 데이터면 `internal` 이다. 다만 팀이 정한 비율로 나눈 매출의 일부만 돌리는 조건에 들었으면 맞출 매출이 그 비율에 기대므로
    그 비율의 등급과 견줘 약한 것이다.
    실패한 방문과 화면에서 직접 넣은 조건의 방문은 세지 않는다.
    """
    by_id = {p.persona_id: p for p in personas}
    groups = sorted({p.customer_group for p in personas})
    simulated: dict[str, Decimal] = defaultdict(Decimal)
    for row in rows:
        if row.status != "ok" or row.choice_kind != "walkerhill" or row.condition_id.startswith(MANUAL_CONDITION_PREFIX):
            continue
        persona = by_id[row.persona_id]
        ratio = ratios[persona.customer_group][row.condition_id]
        simulated[persona.customer_group] += (
            Decimal(row.revenue_net)
            * Decimal(str(persona.share_in_group.value))
            * Decimal(str(ratio))
            * Decimal(str(row.counted_share))
        )

    multiplier: dict[str, float] = {}
    multiplier_grades: dict[str, str] = {}
    for group in groups:
        target = revenue[group].total() if group in revenue else 0.0
        if target > 0 and simulated[group] > 0:
            multiplier[group] = float(Decimal(str(target)) / simulated[group])
            multiplier_grades[group] = _grade(data_mode, revenue[group], revenue[group].split_partly_used)
        else:
            multiplier[group], multiplier_grades[group] = 0.0, "unknown"

    return Weights.model_validate(
        {
            "group_multiplier": multiplier,
            "persona_weight": {p.persona_id: multiplier[p.customer_group] * p.share_in_group.value for p in personas},
            "condition_ratio": {group: ratios[group] for group in groups},
            "grades": {
                "group_multiplier": multiplier_grades,
                "persona_weight": {
                    p.persona_id: weaker(multiplier_grades[p.customer_group], p.share_in_group.grade) for p in personas
                },
                "condition_ratio": {group: ratio_grades[group] for group in groups},
            },
        }
    )


# ── 가격이 빈 상품 ───────────────────────────────────────────────────────────


def fill_prices(venues: dict[str, Venue], rows: list[SummaryRow], data_mode: str) -> tuple[dict[str, Venue], list[str]]:
    """가격이 빈 상품의 단가를 집계 파일의 낸 금액 ÷ 수량으로 채운다 (docs/FORMATS.md 3절).

    `paid` 는 세금이 든 금액이라 그대로 고객이 낼 단가다. 그래서 가격 표기는 `included` 다.
    단가는 백 원 단위로 반올림한다 (`FILLED_PRICE_UNIT`). 등급은 기본 데이터면 `internal`, 가상 예시면 `assumption` 이다.
    집계 파일에 팔린 것이 없거나 반올림한 단가가 0 원이라 채우지 못한 상품은 그대로 둔다 (후보에서 빠지고 실행 기록의 `skipped_products` 에 남는다).
    채울 상품의 줄에 업장 정의와 다른 단위(`unit`)가 있으면 멈춘다. 단위가 다른 수량을 더하면 단가가 틀린다 (docs/FORMATS.md 8절).
    돌려주는 것: 채운 업장 정의(받은 것은 고치지 않는다), 채운 상품의 목록(`<venue_id>:<product_id>`).
    """
    paid: dict[tuple[str, str], int] = defaultdict(int)
    quantity: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    units: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        paid[(row.venue_id, row.product_id)] += row.paid
        quantity[(row.venue_id, row.product_id)] += Decimal(str(row.quantity))
        units[(row.venue_id, row.product_id)].add(row.unit)

    grade = "internal" if data_mode == "private" else "assumption"
    filled: list[str] = []
    out: dict[str, Venue] = {}
    for venue_id, venue in venues.items():
        products = []
        for product in venue.products:
            key = (venue_id, product.product_id)
            if product.price is None and quantity[key] > 0:
                if units[key] != {product.unit}:
                    raise ValueError(
                        f"집계 파일의 '{venue_id}:{product.product_id}' 줄의 단위 {sorted(units[key])} 가 업장 정의의 단위 "
                        f"'{product.unit}' 와 다르다. 단가를 채울 수 없다 (집계 파일의 unit 은 업장 정의의 단위로 적는다)"
                    )
                price = round_half_up(Decimal(paid[key]) / quantity[key] / FILLED_PRICE_UNIT) * FILLED_PRICE_UNIT
                if price > 0:
                    product = product.model_copy(update={"price": price, "price_basis": "included", "grade": grade})
                    filled.append(f"{venue_id}:{product.product_id}")
            products.append(product)
        out[venue_id] = venue.model_copy(update={"products": products})
    return out, sorted(filled)


# ── LLM 에 보낼 기본 데이터의 요약 ───────────────────────────────────────────


def _bucket(share: float, splits: int) -> str:
    """비중을 범주로 바꾼다. 고르게 나눴을 때의 몫의 1.5배 이상이면 high, 0.5배 이상이면 mid, 그보다 작으면 low."""
    relative = share * splits
    if relative >= BUCKET_HIGH:
        return "high"
    if relative >= BUCKET_MID:
        return "mid"
    return "low"


def _shares(amounts: dict[str, float], key: str, mode: str) -> dict[str, Any]:
    total = sum(amounts.values())
    if total <= 0:
        return {}
    shares = {name: amount / total for name, amount in sorted(amounts.items()) if amount > 0}
    if mode == "raw":
        return {name: round(share, 3) for name, share in shares.items()}
    return {name: _bucket(share, SHARE_SPLITS[key]) for name, share in shares.items()}


def base_profiles(rows: list[SummaryRow], mode: str) -> dict[str, dict[str, Any]]:
    """고객군마다 LLM 에 보낼 기본 데이터의 요약 (docs/FORMATS.md 5절의 `base_profile`).

    - `venue_share`, `occasion_share`, `day_type_share`: 그 고객군의 매출 비중. `bucketed` 면 범주(high·mid·low), `raw` 면 소수 셋째 자리까지.
      매출이 없는 갈래는 적지 않는다.
    - `top_products`: 업장마다 그 고객군의 매출이 큰 상품의 `product_id` 를 큰 순서로 셋까지. 순위만 보내고 수치는 보내지 않는다.

    조식 매출은 넣지 않는다. 묶음에 조식이 없어(docs/FORMATS.md 6절) 조식 매출이 다른 끼니의 선택을 끌어당기지 않게 한다.
    집계 파일의 모든 업장과 조건을 본다. 돌리는 업장이나 조건을 골라도 요약이 바뀌지 않게 한다 (요약이 바뀌면 요청이 달라져 재생되지 않는다).
    """
    if mode not in ("bucketed", "raw"):
        raise ValueError(f"base_profile 을 만들 수 없는 base_profile_mode 다: {mode!r}")
    venue: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    occasion: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    day_type: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    product: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for row in rows:
        if row.meal == "breakfast" or row.revenue_net == 0:
            continue
        group = row.customer_group
        venue[group][row.venue_id] += row.revenue_net
        occasion[group][row.occasion] += row.revenue_net
        day_type[group][row.day_type] += row.revenue_net
        product[group][row.venue_id][row.product_id] += row.revenue_net

    profiles: dict[str, dict[str, Any]] = {}
    for group in sorted(venue):
        venue_share = _shares(venue[group], "venue_share", mode)
        profiles[group] = {
            "venue_share": venue_share,
            "occasion_share": _shares(occasion[group], "occasion_share", mode),
            "day_type_share": _shares(day_type[group], "day_type_share", mode),
            "top_products": {
                venue_id: [pid for pid, _ in sorted(product[group][venue_id].items(), key=lambda item: (-item[1], item[0]))][
                    :TOP_PRODUCTS
                ]
                for venue_id in venue_share
            },
        }
    return profiles


def empty_profile() -> dict[str, Any]:
    """기본 데이터에 매출이 없는 고객군의 요약. 키는 같고 값이 비어 있다."""
    return {"venue_share": {}, "occasion_share": {}, "day_type_share": {}, "top_products": {}}
