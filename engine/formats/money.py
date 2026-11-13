"""금액 규칙 (docs/FORMATS.md 2절).

- 금액은 원 단위 정수다.
- 소수가 나오면 언제나 원 단위로 반올림한다 (0.5 는 올린다).
- 세금을 뺀 매출은 고객이 낸 금액 ÷ 1.1 이다.
- 가격을 퍼센트로 바꿀 때는 바뀐 가격을 반올림한다 (7절). 바뀐 폭을 반올림하지 않는다.
"""

import math
from decimal import ROUND_HALF_UP, Decimal

TAX_RATE = Decimal("1.1")


def round_half_up(value: Decimal | int | float | str) -> int:
    """원 단위로 반올림한다. 0.5 는 올린다 (Python 의 round 는 짝수 쪽으로 가므로 쓰지 않는다).

    금액은 0 이상이다. 음수는 "올린다"가 어느 쪽인지 갈리므로 받지 않는다.
    """
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError(f"금액은 0 이상인, 끝이 있는 수여야 한다: {value}")
    return int(number.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def net_of_tax(paid: int) -> int:
    """고객이 낸 금액(세금 포함)에서 세금을 뺀 매출."""
    return round_half_up(Decimal(paid) / TAX_RATE)


def to_paid_price(price: int, price_basis: str) -> int:
    """출처에 표시된 가격을 고객이 낼 금액으로 바꾼다.

    `excluded` 는 세금과 봉사료가 따로 붙는 표기라 1.1 을 곱한다.
    `included` 와 `unknown` 은 그대로 쓴다 (`unknown` 은 화면에 표시해 알린다).
    """
    if price_basis == "excluded":
        return round_half_up(Decimal(price) * TAX_RATE)
    return price


def apply_pct(amount: int, pct: float | int) -> int:
    """금액의 pct 퍼센트. 할인액을 낼 때 쓴다 (pct 는 0 이상).

    가격을 퍼센트로 올리거나 내릴 때는 이것이 아니라 `change_price` 를 쓴다.
    변동 폭을 반올림해서 더하면, 가격을 내릴 때 바뀐 가격을 반올림한 값과 1원 어긋날 수 있다.
    """
    if isinstance(pct, bool) or not math.isfinite(pct) or pct < 0:
        raise ValueError("pct 는 0 이상인, 끝이 있는 수다. 가격을 내릴 때는 change_price 를 쓴다")
    return round_half_up(Decimal(amount) * Decimal(str(pct)) / Decimal(100))


def change_price(price: int, pct: float | int) -> int:
    """가격을 pct 퍼센트 올리거나 내린 값 (docs/FORMATS.md 7절의 `change_price_pct`). 내리면 pct 가 음수다.

    바뀐 가격 자체를 원 단위로 반올림한다: 가격 × (100 + pct) ÷ 100.
    """
    if isinstance(pct, bool) or not math.isfinite(pct) or pct <= -100:
        raise ValueError("pct 는 -100 보다 큰, 끝이 있는 수여야 한다")
    return round_half_up(Decimal(price) * (Decimal(100) + Decimal(str(pct))) / Decimal(100))
