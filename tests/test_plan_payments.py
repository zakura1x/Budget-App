"""
REC-32 - paying money on an installment plan, and what an extra payment does.

The scenario is the user's own (2026-09-16): a ₱185,000 motorcycle over 37
payments of ₱5,000 on a loan from a person, first payment 15 September, and
₱15,000 paid on the 16th. ₱5,000 of that is what was due; the ₱10,000 extra
either lowers every later payment or takes the last two away - and the app
asks which, rather than guessing.
"""

from datetime import date
from decimal import Decimal as D

import pytest

from app.core.exceptions import BusinessRuleException, PrepaymentChoiceException
from app.db.repositories.recurring_repository import RecurringRuleRepository
from app.core.utils.money import ZERO
from app.services import (
    account_service,
    category_service,
    projection_service,
    recurring_service,
    transaction_service,
)

TODAY = date(2026, 9, 16)


@pytest.fixture
def loan(session, owner):
    bank = account_service.create_account(session, owner, {"name": "Seabank", "type": "debit",
                                                           "opening_balance": "50000.00"})
    person = account_service.create_account(session, owner, {"name": "Papa bern", "type": "borrowed"})
    vehicle = category_service.create_category(session, owner, {"name": "Vehicle"})
    plan = recurring_service.create_rule(session, owner, {
        "kind": "installment", "name": "Motorcycle", "account_id": person.id, "category_id": vehicle.id,
        "frequency": "monthly", "start": "2026-09-15", "price": "185000.00", "payments": 37, "post_past": True,
    }, today=TODAY)

    class L:
        pass

    loan = L()
    loan.bank, loan.person, loan.plan = bank.id, person.id, plan.id
    return loan


def pay(session, owner, loan, amount, mode=None, on=TODAY):
    return recurring_service.pay_plan(session, owner, loan.plan, amount=amount, from_account_id=loan.bank,
                                      on=on, mode=mode, today=TODAY)


def owed(session, owner, account_id, today=TODAY):
    view = account_service.get_account(session, owner, account_id,
                                       postings=transaction_service.postings(session, owner), today=today)
    return -view.balance + view.plans_unbilled


def charges(session, owner, rule_id):
    return [v for v in transaction_service.views(session, owner) if v.recurring_id == rule_id and v.type == "expense"]


# ------------------------------------------------------------------ the question


def test_an_extra_payment_asks_what_it_should_do(session, owner, loan):
    """₱15,000 when ₱5,000 is due: nothing is written until the user chooses."""
    with pytest.raises(PrepaymentChoiceException) as asked:
        pay(session, owner, loan, "15000.00")
    body = asked.value.extra
    assert (body["due"], body["extra"]) == ("5000.00", "10000.00")
    assert body["lower"] == {"payment": "4722.22", "payments": 36, "payoff_on": "2029-09-15"}
    assert body["shorten"] == {"payment": "5000.00", "payments": 34, "payoff_on": "2029-07-15"}
    # Asked, so nothing moved.
    assert recurring_service.get_rule(session, owner, loan.plan, today=TODAY).installment.money_paid == D("0.00")


def test_paying_what_is_due_asks_nothing(session, owner, loan):
    status = pay(session, owner, loan, "5000.00").installment
    assert (status.money_paid, status.left_to_pay, status.payments_left) == (D("5000.00"), D("180000.00"), 36)


# ------------------------------------------------------------------ the two answers


def test_shorten_keeps_the_monthly_payment_and_drops_the_last_two(session, owner, loan):
    status = pay(session, owner, loan, "15000.00", mode="shorten").installment
    assert status.money_paid == D("15000.00")
    assert status.left_to_pay == D("170000.00")
    assert status.current_payment == D("5000.00")
    assert status.payments_left == 34
    assert status.payoff_on == date(2029, 7, 15)  # two months sooner than 15 Sep 2029


def test_lower_keeps_the_count_and_shrinks_every_later_payment(session, owner, loan):
    status = pay(session, owner, loan, "15000.00", mode="lower").installment
    assert status.left_to_pay == D("170000.00")
    assert status.current_payment == D("4722.22")
    assert status.payments_left == 36
    assert status.payoff_on == date(2029, 9, 15)


@pytest.mark.parametrize("mode", ["shorten", "lower"])
def test_the_plan_still_charges_exactly_its_price(session, owner, loan, mode):
    """
    Every charge the plan ever makes - its schedule and the extra together - is
    the ₱185,000, to the centavo. The schedule runs to 2029, past the dates the
    app records, so it is summed from the one schedule rather than posted.
    """
    pay(session, owner, loan, "15000.00", mode=mode)
    rule = next(r for r in recurring_service.list_rules(session, owner, today=TODAY) if r.id == loan.plan)
    data = RecurringRuleRepository(session, owner).get(loan.plan).data
    scheduled = sum((row[1] + row[2] for row in recurring_service.installment_plan(data)), D("0"))
    extra = sum((v.amount for v in charges(session, owner, loan.plan) if v.recurring_on is None), D("0"))
    assert scheduled + extra == rule.installment.total == D("185000.00")


def test_what_you_owe_is_what_is_left_to_pay(session, owner, loan):
    pay(session, owner, loan, "15000.00", mode="shorten")
    status = recurring_service.get_rule(session, owner, loan.plan, today=TODAY).installment
    assert owed(session, owner, loan.person) == status.left_to_pay == D("170000.00")


def test_the_extra_counts_as_spending_on_the_day_it_is_paid(session, owner, loan):
    pay(session, owner, loan, "15000.00", mode="shorten")
    extra = [v for v in charges(session, owner, loan.plan) if v.recurring_on is None]
    assert [(v.txn_date, v.amount) for v in extra] == [(TODAY, D("10000.00"))]


def test_the_money_really_moves(session, owner, loan):
    pay(session, owner, loan, "15000.00", mode="shorten")
    bank = account_service.get_account(session, owner, loan.bank,
                                       postings=transaction_service.postings(session, owner), today=TODAY)
    assert bank.balance == D("35000.00")


# ------------------------------------------------------------------ early, twice, and all of it


def test_paying_before_the_next_payment_is_due_is_not_extra(session, owner, loan):
    pay(session, owner, loan, "5000.00")  # covers 15 Sep
    status = recurring_service.pay_plan(session, owner, loan.plan, amount="5000.00", from_account_id=loan.bank,
                                        on=date(2026, 9, 20), today=date(2026, 9, 20)).installment
    assert status.money_paid == D("10000.00")  # October's, early - no question


def test_paying_the_early_one_twice_is_extra(session, owner, loan):
    pay(session, owner, loan, "5000.00")
    recurring_service.pay_plan(session, owner, loan.plan, amount="5000.00", from_account_id=loan.bank,
                               on=date(2026, 9, 20), today=date(2026, 9, 20))
    with pytest.raises(PrepaymentChoiceException):
        recurring_service.pay_plan(session, owner, loan.plan, amount="5000.00", from_account_id=loan.bank,
                                   on=date(2026, 9, 21), today=date(2026, 9, 21))


def test_paying_everything_closes_the_plan_without_asking(session, owner, loan):
    status = pay(session, owner, loan, "185000.00").installment
    assert (status.closed, status.left_to_pay) == (True, D("0.00"))
    assert owed(session, owner, loan.person) == D("0.00")


def test_more_than_is_left_is_refused(session, owner, loan):
    with pytest.raises(BusinessRuleException):
        pay(session, owner, loan, "185000.01")


def test_a_payment_from_the_plans_own_account_is_refused(session, owner, loan):
    with pytest.raises(BusinessRuleException):
        recurring_service.pay_plan(session, owner, loan.plan, amount="5000.00", from_account_id=loan.person,
                                   today=TODAY)


def test_terms_are_fixed_once_an_extra_payment_is_made(session, owner, loan):
    pay(session, owner, loan, "15000.00", mode="shorten")
    with pytest.raises(BusinessRuleException):
        recurring_service.update_rule(session, owner, loan.plan, {"payments": 40}, today=TODAY)


def test_two_extra_payments_stack(session, owner, loan):
    pay(session, owner, loan, "15000.00", mode="shorten")  # due 5,000 + 10,000 extra: 34 left
    status = recurring_service.pay_plan(session, owner, loan.plan, amount="5000.00", from_account_id=loan.bank,
                                        on=date(2026, 9, 20), mode="lower", today=date(2026, 9, 20)).installment
    # October's 5,000 early - no extra, so still 34 payments of 5,000.
    assert (status.payments_left, status.current_payment, status.left_to_pay) == (34, D("5000.00"), D("165000.00"))


# ------------------------------------------------------------------ over the wire


def test_the_api_asks_then_pays(api):
    assert api.register().status_code == 201
    bank = api.post("/accounts", {"name": "Seabank", "type": "debit", "opening_balance": "50000.00"}).json()
    person = api.post("/accounts", {"name": "Papa bern", "type": "borrowed"}).json()
    vehicle = api.post("/categories", {"name": "Vehicle", "kind": "expense"}).json()
    plan = api.post("/recurring?today=2026-09-16", {
        "kind": "installment", "type": "expense", "name": "Motorcycle", "account_id": person["id"],
        "category_id": vehicle["id"], "frequency": "monthly", "start": "2026-09-15", "price": "185000.00",
        "payments": 37, "post_past": True,
    }).json()

    body = {"amount": "15000.00", "from_account_id": bank["id"], "on": "2026-09-16"}
    asked = api.post(f"/recurring/{plan['id']}/payments?today=2026-09-16", body)
    assert asked.status_code == 409, asked.text
    assert asked.json()["code"] == "PREPAYMENT_CHOICE"
    assert asked.json()["shorten"]["payments"] == 34

    paid = api.post(f"/recurring/{plan['id']}/payments?today=2026-09-16", {**body, "mode": "shorten"})
    assert paid.status_code == 200, paid.text
    installment = paid.json()["installment"]
    assert (installment["money_paid"], installment["left_to_pay"], installment["payments_left"]) == (
        "15000.00", "170000.00", 34)


# ------------------------------------------------------- undoing a payment


def test_a_payment_can_be_taken_back(session, owner, loan):
    """
    REC-32. A payment made by mistake - or while trying the button - is an
    ordinary transfer: deleting it from EITHER leg puts the plan and both
    balances back exactly as they were (2026-09-21, user: "I can't delete the
    payment I did for this month as I was trying the payment").
    """
    before = owed(session, owner, loan.person)
    pay(session, owner, loan, "5000.00")
    status = recurring_service.get_rule(session, owner, loan.plan, today=TODAY).installment
    assert status.money_paid == D("5000.00")

    # The leg the loan's own page lists is the one INTO the loan, and it is the
    # one the user would tap; deleting it takes its other half with it.
    legs = [v for v in transaction_service.views(session, owner)
            if v.recurring_id == loan.plan and v.type == "transfer"]
    incoming = next(v for v in legs if v.direction == "in")
    transaction_service.delete_transaction(session, owner, incoming.id, today=TODAY)

    status = recurring_service.get_rule(session, owner, loan.plan, today=TODAY).installment
    assert (status.money_paid, status.left_to_pay) == (D("0.00"), D("185000.00"))
    assert owed(session, owner, loan.person) == before
    bank = account_service.get_account(session, owner, loan.bank,
                                       postings=transaction_service.postings(session, owner), today=TODAY)
    assert bank.balance == D("50000.00")


def test_paying_the_plan_does_not_move_net_worth(session, owner, loan):
    """
    ACC-36 / REC-14. The whole loan is a liability from the day it is taken -
    this month's payment included - so paying it swaps cash for debt and the
    grand total stands still (2026-09-21, user: "in my net worth it was not
    counted that I would pay 5,000 for this month"). Cash on hand is what
    moves.
    """
    def figures():
        views = account_service.list_accounts(session, owner, postings=transaction_service.postings(session, owner),
                                              today=TODAY)
        return account_service.cash_on_hand(views).total, account_service.net_worth(views).total

    cash_before, worth_before = figures()
    # 50,000 in the bank, 185,000 owed: one payment billed, the other 36 not yet.
    assert (cash_before, worth_before) == (D("50000.00"), D("-135000.00"))

    pay(session, owner, loan, "5000.00")
    cash_after, worth_after = figures()
    assert cash_after == cash_before - D("5000.00")
    assert worth_after == worth_before


# ------------------------------------------------- a loan bills like a card (ACC-40)


def views(session, owner, today=TODAY):
    return account_service.list_accounts(session, owner, postings=transaction_service.postings(session, owner),
                                         today=today)


def test_a_loan_has_bills_of_its_own(session, owner, loan):
    """
    ACC-40. The plan IS the schedule, so the loan's bills need no typing: 37
    payments, the 15 September one already past on the 16th, the next on 15
    October. `due_now` is the card's rule - everything overdue plus the next.
    """
    person = next(v for v in views(session, owner) if v.id == loan.person)
    assert person.dues is not None
    assert len(person.dues.dues) == 37
    assert person.dues.left_to_pay == D("185000.00")
    assert person.dues.overdue == D("5000.00")
    assert person.dues.next_on == date(2026, 10, 15)
    assert person.dues.due_now == D("10000.00")


def test_cash_on_hand_holds_back_what_is_due_not_the_loan(session, owner, loan):
    """
    ACC-40 / ACC-17 (2026-09-21, user). Switched on, a loan behaves exactly
    like a card with typed bills: the money held back is what is due now, never
    the whole debt - otherwise ₱50,000 in the bank would read as ₱135,000 owed.
    """
    account_service.update_account(session, owner, loan.person,
                                   {"name": "Papa bern", "type": "borrowed", "counts_in_cash_on_hand": True},
                                   postings=transaction_service.postings(session, owner), today=TODAY)
    assert account_service.cash_on_hand(views(session, owner)).total == D("40000.00")  # 50,000 - 10,000 due

    pay(session, owner, loan, "5000.00")
    person = next(v for v in views(session, owner) if v.id == loan.person)
    assert person.dues.overdue == ZERO
    assert person.dues.due_now == D("5000.00")  # only October's now
    # 45,000 in the bank after paying, less October's 5,000.
    assert account_service.cash_on_hand(views(session, owner)).total == D("40000.00")
    # What it OWES and net worth are untouched by any of this (REC-14).
    assert owed(session, owner, loan.person) == D("180000.00")
    assert account_service.net_worth(views(session, owner)).total == D("-135000.00")


def test_a_borrowed_account_with_no_plan_has_no_dues(session, owner):
    """Without a schedule there is nothing to derive, and the account keeps its plain balance."""
    person = account_service.create_account(session, owner, {"name": "Tita Grace", "type": "borrowed",
                                                             "opening_balance": "-2000.00",
                                                             "counts_in_cash_on_hand": True})
    view = next(v for v in views(session, owner) if v.id == person.id)
    assert view.dues is None
    assert view.cash_amount == D("-2000.00")


def test_months_ahead_does_not_take_a_due_twice(session, owner, loan):
    """
    ACC-40 / ACC-35. Once cash on hand holds back what is due, Months ahead
    must not take it again: the payments that cover `due_now` are shown where
    they fall, as money already set aside, with no effect on the month - the
    bargain a card's typed bills have had since 2026-09-16.
    """
    account_service.update_account(session, owner, loan.person,
                                   {"name": "Papa bern", "type": "borrowed", "counts_in_cash_on_hand": True},
                                   postings=transaction_service.postings(session, owner), today=TODAY)
    recurring_service.create_rule(session, owner, {
        "kind": "standard", "type": "transfer", "name": "Papa bern payment", "account_id": loan.bank,
        "counter_account_id": loan.person, "frequency": "monthly", "start": "2026-10-15", "amount": "5000.00",
    }, today=TODAY)

    projection = projection_service.project(session, owner, today=TODAY, months=6)
    # 50,000 less September's overdue payment and October's, which it holds.
    assert projection.cash_on_hand == D("40000.00")

    dues = {i.on: i for month in projection.months for i in month.items
            if i.account_id == loan.person and i.rule_id == 0}
    # What cash on hand already holds is shown where it falls and never taken...
    assert dues[TODAY].kind == "bill_now" and dues[TODAY].effect == ZERO        # September's, overdue
    assert dues[date(2026, 10, 15)].kind == "bill_now"
    assert dues[date(2026, 10, 15)].effect == ZERO
    # ...and every later payment leaves on its own due date.
    assert dues[date(2026, 11, 15)].effect == D("-5000.00")

    # The transfer that pays it moves money between two counted accounts, so it
    # takes nothing by itself - the due above is the money leaving, once.
    paid_by = [i for month in projection.months for i in month.items
               if i.type == "transfer" and i.counter_account_id == loan.person]
    assert paid_by and all(i.effect == ZERO for i in paid_by)
    # And the plan's own charges are not a third copy of the same money.
    assert not [i for month in projection.months for i in month.items
                if i.account_id == loan.person and i.kind == "installment"]
