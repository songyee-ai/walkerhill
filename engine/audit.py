"""원장의 조건 위반을 센다 (docs/PRD.md 11절의 "조건 위반이 0건").

후보를 추리는 코드(`engine/candidates.py`)와 원장을 만드는 코드(`engine/ledger.py`)를 쓰지 않고,
업장 정의·페르소나 정의·방문 조건 묶음과 원장만으로 따로 본다.
같은 코드로 만들고 같은 코드로 확인하면 틀린 규칙을 틀린 채로 통과시키기 때문이다.
"""

from collections import defaultdict
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from engine.formats.choice import RunCondition
from engine.formats.conditions import MANUAL_CONDITION_PREFIX, ConditionBundle
from engine.formats.money import TAX_RATE
from engine.formats.persona import Persona
from engine.formats.run import LedgerRow, SavedResponse
from engine.formats.venue import Product, Venue

_BASIS_RATE = {
    "included": Decimal(1),
    "unknown": Decimal(1),
    "excluded_vat": TAX_RATE,
    "excluded_vat_service": TAX_RATE * TAX_RATE,
}
_SHARE_TOLERANCE = 1e-6
_EVERY_MONTH = frozenset(range(1, 13))


def _paid_price(price: int, basis: str) -> int:
    return int((Decimal(price) * _BASIS_RATE[basis]).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _months(venue: Venue, product: Product) -> frozenset[int]:
    return frozenset(product.months or venue.months or _EVERY_MONTH)


def _condition_problems(
    row: LedgerRow, condition: RunCondition, request_persona_id: object, personas: dict[str, Persona], bundle: ConditionBundle
) -> list[str]:
    """저장된 요청의 조건이 페르소나 정의와 방문 조건 묶음에서 나온 것인지 본다.

    인원과 예산을 요청에서만 읽으면, 조건을 만드는 코드가 틀렸을 때 그 틀린 값으로 확인하게 된다.
    화면에서 직접 넣은 조건(`manual-`)은 인원과 예산을 사람이 넣은 것이라 견줄 것이 없다.
    """
    problems = []
    if request_persona_id != row.persona_id or condition.condition_id != row.condition_id:
        problems.append("저장된 요청이 다른 페르소나나 다른 조건의 것이다")
    if row.condition_id.startswith(MANUAL_CONDITION_PREFIX):
        return problems
    persona = personas.get(row.persona_id)
    planned = bundle.condition(row.condition_id)
    if persona is None or planned is None:
        return [*problems, "페르소나 정의나 묶음의 조건이 없다"]
    if (condition.adults, condition.children) != (persona.visit.party.adults, persona.visit.party.children):
        problems.append("요청의 인원이 페르소나 정의와 다르다")
    if condition.budget != persona.budget:
        problems.append("요청의 예산이 페르소나 정의와 다르다")
    for key in ("occasion", "meal", "day_type", "stay", "month"):
        if getattr(condition, key) != getattr(planned, key):
            problems.append(f"요청의 {key} 가 묶음의 조건과 다르다")
    return problems


def violations(
    rows: list[LedgerRow],
    venues: dict[str, Venue],
    saved: dict[str, SavedResponse],
    personas: dict[str, Persona],
    bundle: ConditionBundle,
) -> list[str]:
    """업장을 고른 방문마다 조건을 어겼는지 본다. 어긴 것을 `<방문> — <종류>: <설명>` 으로 돌려준다.

    `status` 가 ok 인 줄만 본다. 방문의 조건은 그 줄의 `request_hash` 가 가리키는 저장된 응답의 요청에서 읽되,
    그 조건이 페르소나 정의와 묶음에서 나온 것인지도 따로 견준다. 예산의 한도는 페르소나 정의에서 낸다.

    `personas` 에는 그 실행에 쓴 페르소나를 준다. 기본 데이터로 돌린 실행이면 두 층을 합친 것이다
    (`engine.runner.load_inputs` 가 돌려주는 `personas`). 공개 층만 주면 비공개 층이 바꾼 예산이 "조건 불일치"로 나온다.
    """
    found: list[str] = []
    visits: dict[str, list[LedgerRow]] = defaultdict(list)
    for row in rows:
        if row.status == "ok":
            visits[row.visit_id].append(row)

    for visit_id, visit_rows in visits.items():
        bought = [row for row in visit_rows if row.choice_kind != "none"]
        if not bought:
            continue

        def bad(kind: str, detail: str, visit_id: str = visit_id) -> None:
            found.append(f"{visit_id} — {kind}: {detail}")

        entry = saved.get(bought[0].request_hash or "")
        venue = venues.get(bought[0].venue_id or "")
        if entry is None:
            bad("응답 없음", "저장된 응답이 없는 방문이 업장을 골랐다")
            continue
        if venue is None:
            bad("없는 업장", f"'{bought[0].venue_id}'")
            continue
        condition: RunCondition = entry.request.condition
        for problem in _condition_problems(bought[0], condition, entry.request.persona.get("persona_id"), personas, bundle):
            bad("조건 불일치", problem)
        people = condition.adults + condition.children

        if condition.occasion not in venue.occasions:
            bad("다른 이용 상황의 업장", f"'{venue.venue_id}' 에는 {condition.occasion} 가 없다")
        if venue.hours is not None and not any(
            h.meal == condition.meal and h.day_type in (condition.day_type, "all") for h in venue.hours
        ):
            bad("운영 시간 밖", f"'{venue.venue_id}' 는 그 끼니·요일에 영업하지 않는다")
        if condition.month is not None and venue.months is not None and condition.month not in venue.months:
            bad("파는 달이 아님", f"'{venue.venue_id}' 는 {condition.month}월에 영업하지 않는다")
        if venue.reservation is not None:
            low, high = venue.reservation.party_min, venue.reservation.party_max
            if high is not None and people > high:
                bad("인원 초과", f"{people}명인데 '{venue.venue_id}' 는 {high}명까지 받는다")
            if low is not None and people < low:
                bad("예약 조건 위반", f"{people}명인데 '{venue.venue_id}' 는 {low}명부터 받는다")

        mains: list[Product] = []
        extras: list[Product] = []
        covered = {"adult": False, "child": False}
        for row in bought:
            product = venue.product(row.product_id or "")
            if product is None:
                bad("없는 상품", f"'{row.product_id}' 가 '{venue.venue_id}' 에 없다")
                continue
            if product.occasion != condition.occasion:
                bad("다른 이용 상황의 업장", f"상품 '{product.product_id}' 는 {product.occasion} 상품이다")
            if not any(s.meal == condition.meal and s.day_type in (condition.day_type, "all") for s in product.slots):
                bad("운영 시간 밖", f"상품 '{product.product_id}' 는 그 끼니·요일에 팔지 않는다")
            if condition.month is not None and condition.month not in _months(venue, product):
                bad("파는 달이 아님", f"상품 '{product.product_id}' 는 {condition.month}월에 팔지 않는다")
            if product.price is None or row.list_price != _paid_price(product.price, product.price_basis):
                bad("금액 불일치", f"상품 '{product.product_id}' 의 표시가가 업장 정의와 다르다")
            if row.unit != product.unit:
                bad("금액 불일치", f"상품 '{product.product_id}' 의 단위가 업장 정의와 다르다")

            if product.qty_rule == "choice":
                extras.append(product)
                if row.quantity > (product.qty_max or 0):
                    bad("수량 초과", f"상품 '{product.product_id}' 를 qty_max 보다 많이 샀다")
                continue
            mains.append(product)
            heads = {"adult": condition.adults, "child": condition.children, "all": people}[product.audience]
            wanted = heads if product.qty_rule == "per_person" else int(
                (Decimal(heads) / product.serves).to_integral_value(rounding=ROUND_CEILING)
            )
            if row.quantity != wanted:
                bad("금액 불일치", f"상품 '{product.product_id}' 의 수량이 수량 규칙과 다르다")
            for who in ("adult", "child"):
                covered[who] = covered[who] or product.audience in (who, "all")

        # 예산의 max 는 산 것 전부(주문 + 추가 상품)와 견준다 (docs/FORMATS.md 9절).
        # 한도는 요청이 아니라 페르소나 정의에서 낸다. 요청의 예산이 틀렸으면 그 틀린 한도로는 넘은 것을 알 수 없다.
        # 화면에서 직접 넣은 조건(manual-)과 정의가 없는 페르소나는 견줄 정의가 없어 요청의 값을 쓴다.
        persona = None if bought[0].condition_id.startswith(MANUAL_CONDITION_PREFIX) else personas.get(bought[0].persona_id)
        budget = persona.budget if persona else condition.budget
        heads = persona.visit.party.adults + persona.visit.party.children if persona else people
        spent = sum(row.paid for row in bought)
        limit = budget.max * heads if budget.basis == "per_person" else budget.max
        if spent > limit:
            bad("예산 초과", f"{spent}원을 냈는데 예산의 max 로는 {limit}원까지다")
        if mains and not (covered["adult"] and (covered["child"] or condition.children == 0)):
            bad("인원 초과", "일행 가운데 몫이 없는 사람이 있다")

        # 방문의 몫: 주문(없으면 산 추가 상품)을 모두 함께 파는 달 수 ÷ 12. 조건에 달이 있으면 1 이다 (10.2절).
        months = _EVERY_MONTH
        for product in mains or extras:
            months &= _months(venue, product)
        share = 1.0 if condition.month is not None else len(months) / 12
        gaps = [row for row in visit_rows if row.choice_kind == "none"]
        gap_ok = (
            not gaps if share > 1 - _SHARE_TOLERANCE
            else len(gaps) == 1 and abs(gaps[0].counted_share - (1 - share)) <= _SHARE_TOLERANCE
        )
        if any(abs(row.counted_share - share) > _SHARE_TOLERANCE for row in bought) or not gap_ok:
            bad("몫 불일치", f"그 업장의 것으로 세는 몫은 {share} 여야 하고, 나머지는 '이용하지 않음' 줄 하나여야 한다")
        if condition.month is None and mains:
            for product in extras:
                if not months <= _months(venue, product):
                    bad("몫 불일치", f"추가 상품 '{product.product_id}' 는 주문을 파는 달 가운데 팔지 않는 달이 있다")
    return found
