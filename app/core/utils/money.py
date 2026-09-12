"""
Money - Decimal, two places, never a float (invariant 5, ARCHITECTURE.md 5.3).

`user_cipher.dumps_payload()` already refuses to seal a float, so a float that
reaches a payload is caught before it can be stored. This module is the other
half: it is how a value BECOMES money in the first place, so the refusal is
never the thing the user meets. Parsing happens once, at the edge, and
everything inward is already a quantised Decimal.

PHP only (ACC-11). There is no currency here because there is no currency in
the data - `₱` and its grouping are formatting constants in the frontend.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Any) -> Decimal:
    """
    Coerce to a 2-place Decimal, or raise ValueError.

    A `float` is refused rather than converted: 0.1 + 0.2 has already lost the
    argument by the time it gets here, and silently accepting one would put a
    binary rounding error into a stored balance.
    """
    if isinstance(value, bool):
        raise ValueError("a boolean is not an amount")
    if isinstance(value, float):
        raise ValueError("money is Decimal, never float")
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, str):
        text = value.strip().replace(",", "").replace("₱", "")
        if not text:
            raise ValueError("an amount is required")
        try:
            parsed = Decimal(text)
        except InvalidOperation:
            raise ValueError("not an amount") from None
    else:
        raise ValueError("not an amount")

    if not parsed.is_finite():
        raise ValueError("not an amount")
    return parsed.quantize(CENTS, rounding=ROUND_HALF_UP)


def total(values) -> Decimal:
    """Sum of money, still money - and ZERO rather than int 0 when empty."""
    result = ZERO
    for value in values:
        result += value
    return result.quantize(CENTS, rounding=ROUND_HALF_UP)
