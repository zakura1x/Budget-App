"""
Shared field types for the v1 schemas.

`Money` is the important one. Pydantic will happily turn the JSON number
12.30 into a Decimal by way of a binary float, which is exactly the conversion
invariant 5 exists to prevent - so a float is REFUSED at the edge and the
client sends an amount as a string ("12.30"). On the way out, pydantic
serialises Decimal as that same string, so a number never round-trips through
a float in either direction.
"""

from decimal import Decimal
from typing import Annotated, Any

from pydantic import BeforeValidator, Field, PlainSerializer

from app.core.utils.money import money as _money


def _as_money(value: Any) -> Decimal:
    if isinstance(value, float):
        raise ValueError("send an amount as a string, not a number - money is never a float")
    return _money(value)


Money = Annotated[
    Decimal,
    BeforeValidator(_as_money),
    PlainSerializer(lambda value: str(value), return_type=str, when_used="json"),
]

Colour = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
IconName = Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[a-z0-9-]+$")]
DayOfMonth = Annotated[int, Field(ge=1, le=31)]
