"""
Card bills and your own spending limit (ACC-19..23, FEATURES.md §21).

What is worth proving: the bill is what the card owed at the close, paying it
in full silences the reminder even while new purchases sit on the next
statement, a part payment does not, a refund after the close reduces what is
left, and the spending limit counts purchases and refunds - never payments -
over the card's own cycle, raising the budget's alerts on the card's dates.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import ValidationException
from app.services import account_service, category_service, transaction_service
from app.services.budget_service import budget_service
from app.services.budget_service.alerts import CardLimit, card_limit_alerts

D = Decimal

# Closes on the 16th, due on the 6th of the next month - the §21 example.
CARD = {"name": "BPI Card", "type": "credit", "statement_closing_day": 16, "payment_due_day": 6}


@pytest.fixture
def setup(session, owner):
    wallet = account_service.create_account(session, owner, {"name": "BDO", "type": "debit",
                                                             "opening_balance": "100000.00"})
    card = account_service.create_account(session, owner, CARD)
    food = category_service.create_category(session, owner, {"name": "Food"})
    refunds = category_service.create_category(session, owner, {"name": "Refunds", "kind": "income"})
    budget_service.create_budget(session, owner, {"period": "monthly", "amount": "90000.00"}, today=date(2026, 8, 1))

    class S:
        pass

    s = S()
    s.wallet, s.card, s.food, s.refunds = wallet.id, card.id, food.id, refunds.id
    return s


def buy(session, owner, s, amount, on, account=None):
    return transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": amount, "account_id": account or s.card,
        "category_id": s.food, "txn_date": on}).transactions[0]


def pay(session, owner, s, amount, on):
    transaction_service.create_transaction(session, owner, {
        "type": "transfer", "amount": amount, "account_id": s.wallet,
        "counter_account_id": s.card, "txn_date": on})


def card_view(session, owner, s, today):
    return account_service.get_account(
        session, owner, s.card, postings=transaction_service.postings(session, owner), today=today
    ).credit


def card_alerts(session, owner, today):
    status = budget_service.status(session, owner, today=today)
    return [(a.kind, a.account_id) for a in status.alerts if a.kind.startswith("card_")]


# ------------------------------------------------------------------ the bill


def test_the_bill_is_what_the_card_owed_at_the_close(session, owner, setup):
    """ACC-19 - earlier unpaid spending included, as the bank's statement has it."""
    buy(session, owner, setup, "2000.00", "2026-08-20")
    buy(session, owner, setup, "10300.00", "2026-09-10")
    buy(session, owner, setup, "999.00", "2026-09-18")  # after the close - the next statement

    credit = card_view(session, owner, setup, date(2026, 9, 20))
    assert (credit.bill.closes, credit.bill.due) == (date(2026, 9, 16), date(2026, 10, 6))
    assert credit.bill.amount == D("12300.00")
    assert credit.bill.left_to_pay == D("12300.00")
    assert credit.amount_due == D("12300.00")
    assert credit.owed == D("13299.00")  # the card, not the bill


def test_a_part_payment_leaves_the_rest_and_keeps_the_reminder(session, owner, setup):
    buy(session, owner, setup, "12300.00", "2026-09-10")
    pay(session, owner, setup, "5000.00", "2026-09-25")

    credit = card_view(session, owner, setup, date(2026, 10, 2))
    assert (credit.bill.paid_since_close, credit.bill.left_to_pay) == (D("5000.00"), D("7300.00"))
    assert credit.due_soon is True
    assert ("card_due", setup.card) in card_alerts(session, owner, date(2026, 10, 2))


def test_paying_the_bill_silences_the_reminder_despite_new_purchases(session, owner, setup):
    """ACC-20 - the reminder is about the bill, not about the card being empty."""
    buy(session, owner, setup, "12300.00", "2026-09-10")
    pay(session, owner, setup, "5000.00", "2026-09-25")
    buy(session, owner, setup, "3200.00", "2026-09-28")  # the next statement's
    pay(session, owner, setup, "7300.00", "2026-10-01")

    credit = card_view(session, owner, setup, date(2026, 10, 2))
    assert credit.bill.left_to_pay == D("0.00")
    assert credit.owed == D("3200.00")
    assert credit.due_soon is True
    assert card_alerts(session, owner, date(2026, 10, 2)) == []


def test_an_unpaid_bill_past_its_due_date_is_overdue(session, owner, setup):
    buy(session, owner, setup, "1000.00", "2026-09-10")
    assert card_view(session, owner, setup, date(2026, 10, 7)).bill.overdue is True
    pay(session, owner, setup, "1000.00", "2026-10-07")
    assert card_view(session, owner, setup, date(2026, 10, 7)).bill.overdue is False


def test_a_refund_after_the_close_reduces_what_is_left_to_pay(session, owner, setup):
    """Decided 2026-09-14 - money returned to the card counts against the bill, like a payment."""
    buy(session, owner, setup, "1000.00", "2026-09-10")
    transaction_service.create_transaction(session, owner, {
        "type": "income", "amount": "400.00", "account_id": setup.card,
        "category_id": setup.refunds, "txn_date": "2026-09-20"})
    bill = card_view(session, owner, setup, date(2026, 9, 21)).bill
    assert (bill.amount, bill.paid_since_close, bill.left_to_pay) == (D("1000.00"), D("400.00"), D("600.00"))


# ---------------------------------------------------------- the spending limit


def limited(session, owner, s, limit="10000.00"):
    account_service.update_account(session, owner, s.card, {**CARD, "spending_limit": limit})


def test_the_limit_counts_purchases_minus_refunds_in_the_open_cycle(session, owner, setup):
    limited(session, owner, setup)
    buy(session, owner, setup, "4000.00", "2026-09-10")  # last cycle
    buy(session, owner, setup, "6500.00", "2026-09-20")
    transaction_service.create_transaction(session, owner, {
        "type": "income", "amount": "500.00", "account_id": setup.card,
        "category_id": setup.refunds, "txn_date": "2026-09-22"})
    pay(session, owner, setup, "4000.00", "2026-09-25")  # a payment is not a refund

    credit = card_view(session, owner, setup, date(2026, 9, 30))
    assert (credit.limit_spent, credit.limit_left) == (D("6000.00"), D("4000.00"))
    assert (credit.period_days, credit.period_days_elapsed) == (30, 14)


def test_the_limit_raises_pace_then_approaching_then_over(session, owner, setup):
    """The §21 walk-through, day by day."""
    limited(session, owner, setup)
    buy(session, owner, setup, "6500.00", "2026-09-20")
    assert card_alerts(session, owner, date(2026, 9, 30)) == [("card_limit_pace", setup.card)]

    buy(session, owner, setup, "1500.00", "2026-10-05")
    assert card_alerts(session, owner, date(2026, 10, 8)) == [("card_limit_approaching", setup.card)]

    buy(session, owner, setup, "2000.00", "2026-10-14")
    assert card_alerts(session, owner, date(2026, 10, 14)) == [("card_limit_over", setup.card)]


def test_a_new_cycle_starts_with_the_whole_limit(session, owner, setup):
    limited(session, owner, setup)
    buy(session, owner, setup, "10000.00", "2026-10-14")
    credit = card_view(session, owner, setup, date(2026, 10, 17))
    assert (credit.limit_spent, credit.limit_left) == (D("0.00"), D("10000.00"))


def test_a_card_without_a_limit_raises_no_limit_alert(session, owner, setup):
    buy(session, owner, setup, "50000.00", "2026-09-20")
    assert card_alerts(session, owner, date(2026, 9, 21)) == []
    assert card_view(session, owner, setup, date(2026, 9, 21)).limit_left is None


def test_the_limit_survives_an_edit_and_refuses_zero(session, owner, setup):
    limited(session, owner, setup, "8000.00")
    account_service.update_account(session, owner, setup.card, {**CARD, "name": "BPI Gold", "spending_limit": "8000.00"})
    assert card_view(session, owner, setup, date(2026, 9, 20)).spending_limit == D("8000.00")
    with pytest.raises(ValidationException):
        limited(session, owner, setup, "0")


def test_only_a_card_keeps_a_spending_limit(session, owner, setup):
    account_service.update_account(session, owner, setup.wallet, {"name": "BDO", "type": "debit",
                                                                  "spending_limit": "5000.00"})
    record = account_service.AccountRepository(session, owner).get(setup.wallet)
    assert "spending_limit" not in record.data


# ------------------------------------------------------------- pure alerts


def limit(spent, elapsed, total=30, amount="10000.00"):
    return CardLimit(account_id=1, limit=D(amount), spent=D(spent), days_elapsed=elapsed, days_total=total)


def test_pace_warns_ahead_of_the_cycle_and_stays_quiet_within_tolerance():
    assert [a.kind for a in card_limit_alerts(limit("6500.00", 14))] == ["card_limit_pace"]  # 65% vs 47%
    assert card_limit_alerts(limit("5500.00", 14)) == []  # 55% vs 47%, inside 10 points


def test_over_replaces_the_other_card_alerts():
    assert [a.kind for a in card_limit_alerts(limit("10000.00", 2))] == ["card_limit_over"]


def test_pace_can_be_switched_off_for_cards_too():
    assert card_limit_alerts(limit("6500.00", 14), pace_enabled=False) == []
