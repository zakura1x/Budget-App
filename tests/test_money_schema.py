"""
The `Money` field type at the API's edge (app/api/v1/schemas/common.py): a
string both ways, never a float - and zero always leaves as "0.00", so no
screen has to recognise "-0.00" (architecture review 2026-10-12, pass 2 B).
"""

from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from app.api.v1.schemas.common import Money


class Row(BaseModel):
    amount: Money


def test_negative_zero_leaves_as_plain_zero():
    assert Row(amount=-Decimal("0.00")).model_dump(mode="json") == {"amount": "0.00"}
    assert Row(amount=Decimal("-0")).model_dump(mode="json") == {"amount": "0.00"}


def test_every_other_amount_leaves_exactly_as_it_is():
    for value in ("12.50", "-12.50", "0.01", "-0.01", "999999999.99"):
        assert Row(amount=value).model_dump(mode="json") == {"amount": value}


def test_a_float_is_refused():
    with pytest.raises(ValidationError):
        Row(amount=12.5)
