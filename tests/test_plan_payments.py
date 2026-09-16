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
from app.services import account_service, category_service, recurring_service, transaction_service

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
