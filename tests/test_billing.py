"""
app/core/utils/billing - which bill a charge lands on, and what is due now.
Pure, so tested through its own interface: the card page (account_service),
Months ahead (projection_service) and installment conversion all ask it, and
test_card_app_bills.py still proves the whole path end to end.
"""

from datetime import date
from decimal import Decimal as D

from app.core.utils.billing import Owing, bill_due, due_now, on_a_bill

CARD = {"closing_day": 20, "due_day": 5}
TYPED = (date(2026, 10, 15), date(2026, 11, 15))


def test_a_purchase_is_billed_with_its_statement():
    # Closes 20 Oct, due 5 Nov - whatever bills were typed.
    assert bill_due(date(2026, 10, 10), installment=False, bill_dues=TYPED, **CARD) == date(2026, 11, 5)
    assert bill_due(date(2026, 10, 21), installment=False, bill_dues=TYPED, **CARD) == date(2026, 12, 5)


def test_an_installment_joins_the_first_bill_due_on_or_after_its_day():
    """Fixed 2026-09-16: a payment dated 15 Oct was on the 15 Nov bill."""
    assert bill_due(date(2026, 10, 15), installment=True, bill_dues=TYPED, **CARD) == date(2026, 10, 15)
    assert bill_due(date(2026, 10, 16), installment=True, bill_dues=TYPED, **CARD) == date(2026, 11, 15)


def test_past_the_last_bill_an_installment_keeps_its_rhythm():
    assert bill_due(date(2026, 11, 20), installment=True, bill_dues=TYPED, **CARD) == date(2026, 12, 15)
    assert bill_due(date(2026, 12, 31), installment=True, bill_dues=TYPED, **CARD) == date(2027, 1, 15)


def test_on_a_bill_asks_the_same_question():
    for day in (date(2026, 10, 1), date(2026, 11, 15), date(2026, 11, 16), date(2026, 10, 25)):
        for installment in (True, False):
            placed = bill_due(day, installment=installment, bill_dues=TYPED, **CARD)
            assert on_a_bill(day, installment=installment, last_due=TYPED[-1], **CARD) == (placed <= TYPED[-1])


def test_due_now_is_everything_overdue_and_the_next_due_date():
    bills = [Owing(date(2026, 9, 15), D("100.00"), True), Owing(date(2026, 10, 15), D("0.00"), True),
             Owing(date(2026, 11, 15), D("250.00"), False), Owing(date(2026, 12, 15), D("300.00"), False)]
    now = due_now(bills)
    assert (now.amount, now.dues) == (D("350.00"), (date(2026, 9, 15), date(2026, 11, 15)))
    assert (now.next_on, now.next_amount) == (date(2026, 11, 15), D("250.00"))


def test_two_payments_on_the_next_due_date_are_both_due_now():
    """Two loan plans due the same day: both are held, not just the first (fixed 2026-10-12)."""
    now = due_now([Owing(date(2026, 11, 1), D("1000.00"), False), Owing(date(2026, 11, 1), D("500.00"), False),
                   Owing(date(2026, 12, 1), D("1000.00"), False)])
    assert (now.amount, now.next_amount, now.dues) == (D("1500.00"), D("1500.00"), (date(2026, 11, 1),))


def test_nothing_owing_is_nothing_due():
    now = due_now([Owing(date(2026, 11, 1), D("0.00"), False)])
    assert (now.amount, now.dues, now.next_on, now.next_amount) == (D("0.00"), (), None, D("0.00"))
