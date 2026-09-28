"""
Phase 12 - looking ahead (misc/ROADMAP.md).

  REC-35  the debt payoff planner: its pure arithmetic (snowball, avalanche,
          rolling freed payments on, interest as an estimate, a debt that
          never clears), and the service that finds each debt's owed figure,
          payment and rate - typed as the bank shows it (user, 2026-09-28)
  REC-27  the what-if: an unsaved plan runs through the one schedule and
          changes the months ahead, and nothing is written
  CAL-06  the year view is twelve months exactly as the month view gives them
  SUB-07  a cancelled subscription says so on its rule (the sheet hides Pause)
"""

from datetime import date
from decimal import Decimal as D

import pytest

from app.core.exceptions import ValidationException
from app.core.utils.payoff import Debt, compare, order, simulate
from app.db.repositories.recurring_repository import RecurringRuleRepository
from app.services import (
    account_service,
    calendar_service,
    category_service,
    payoff_service,
    projection_service,
    recurring_service,
    transaction_service,
)

START = date(2026, 10, 1)


# ------------------------------------------------------------ the arithmetic


def test_snowball_orders_by_balance_and_avalanche_by_rate():
    debts = [Debt(1, D("50000.00"), D("1000.00"), D("36")), Debt(2, D("5000.00"), D("500.00"), D("12")),
             Debt(3, D("20000.00"), D("800.00"), None)]
    assert [d.id for d in order(debts, "snowball")] == [2, 3, 1]
    # highest rate first; a debt with no rate typed comes after every one that has one
    assert [d.id for d in order(debts, "avalanche")] == [1, 2, 3]


def test_paying_only_the_payment_with_no_interest():
    plan = simulate([Debt(1, D("3000.00"), D("1000.00"))], extra=D("0"), strategy="as_is", start=START,
                    rolling=False)
    [outcome] = plan.outcomes
    assert (outcome.months, outcome.paid_off, plan.debt_free, plan.interest) == (3, date(2026, 12, 1),
                                                                                 date(2026, 12, 1), D("0.00"))


def test_the_extra_goes_to_the_first_debt_and_a_freed_payment_rolls_on():
    debts = [Debt(1, D("1000.00"), D("500.00")), Debt(2, D("3000.00"), D("500.00"))]
    as_is = simulate(debts, extra=D("0"), strategy="as_is", start=START, rolling=False)
    snowball = simulate(debts, extra=D("500.00"), strategy="snowball", start=START)
    assert [o.months for o in as_is.outcomes] == [2, 6]
    # month 1: debt 1 gets 500 + 500 extra = cleared; its 500 then rolls to debt 2 with the extra
    assert [o.months for o in snowball.outcomes] == [1, 3]


def test_interest_is_an_estimate_from_the_typed_rate():
    # 12% a year = 1% a month on 10,000 owed, paid 5,000 a month
    plan = simulate([Debt(1, D("10000.00"), D("5000.00"), D("12"))], extra=D("0"), strategy="as_is",
                    start=START, rolling=False)
    assert plan.outcomes[0].months == 3
    # 100.00, then 1% of 5,100 = 51.00, then 1% of 151 = 1.51
    assert plan.interest == D("152.51")


def test_a_debt_whose_interest_outruns_its_payment_never_clears():
    plan = simulate([Debt(1, D("100000.00"), D("500.00"), D("36"))], extra=D("0"), strategy="as_is",
                    start=START, rolling=False)
    assert (plan.outcomes[0].months, plan.months, plan.debt_free) == (None, None, None)


def test_avalanche_saves_interest_over_snowball():
    debts = [Debt(1, D("20000.00"), D("1000.00"), D("36")), Debt(2, D("5000.00"), D("1000.00"), D("6"))]
    plans = compare(debts, extra=D("3000.00"), start=START)
    assert plans["avalanche"].interest < plans["snowball"].interest


def test_no_rate_anywhere_means_no_avalanche():
    plans = compare([Debt(1, D("1000.00"), D("100.00"))], extra=D("0"), start=START)
    assert plans["avalanche"] is None


def test_a_negative_extra_is_refused():
    with pytest.raises(ValueError):
        simulate([], extra=D("-1"), strategy="snowball", start=START)


# ------------------------------------------------ the rate, and the service


@pytest.fixture
def owing(session, owner):
    bank = account_service.create_account(session, owner, {"name": "BDO", "type": "debit",
                                                           "opening_balance": "80000.00"})
    card = account_service.create_account(session, owner, {
        "name": "BPI Card", "type": "credit", "statement_closing_day": 20, "payment_due_day": 5,
        "opening_balance": "-12000.00", "debt_rate": {"rate": "3", "per": "month"}})
    loan = account_service.create_account(session, owner, {
        "name": "Papa", "type": "borrowed", "opening_balance": "-6000.00"})
    gadgets = category_service.create_category(session, owner, {"name": "Gadgets"})

    class Owing:
        pass

    o = Owing()
    o.bank, o.card, o.loan, o.gadgets = bank.id, card.id, loan.id, gadgets.id
    return o


def test_a_rate_is_kept_as_typed_and_read_a_year(session, owner, owing):
    card = account_service.get_account(session, owner, owing.card)
    assert (card.debt_rate.rate, card.debt_rate.per, card.debt_rate.yearly) == (D("3.0000"), "month", D("36.0000"))


def test_null_removes_the_rate_and_left_out_keeps_it(session, owner, owing):
    base = {"name": "BPI Card", "type": "credit", "statement_closing_day": 20, "payment_due_day": 5}
    account_service.update_account(session, owner, owing.card, base)
    assert account_service.get_account(session, owner, owing.card).debt_rate is not None
    account_service.update_account(session, owner, owing.card, {**base, "debt_rate": None})
    assert account_service.get_account(session, owner, owing.card).debt_rate is None


def test_only_a_card_or_a_loan_carries_a_rate(session, owner, owing):
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash",
                                                             "debt_rate": {"rate": "3", "per": "month"}})
    assert account_service.get_account(session, owner, wallet.id).debt_rate is None


def test_a_monthly_rate_over_the_ceiling_is_refused(session, owner):
    with pytest.raises(ValidationException):
        account_service.create_account(session, owner, {
            "name": "Shark", "type": "borrowed", "debt_rate": {"rate": "10", "per": "month"}})


def test_the_planner_finds_owed_payments_and_rates(session, owner, owing):
    recurring_service.create_rule(session, owner, {
        "kind": "standard", "type": "transfer", "name": "Card payment", "account_id": owing.bank,
        "counter_account_id": owing.card, "frequency": "monthly", "amount": "2000.00", "start": "2026-10-05"},
        today=date(2026, 9, 28))
    result = payoff_service.plan(session, owner, extra=D("1000.00"), today=date(2026, 9, 28))
    debts = {d.account_id: d for d in result.debts}
    assert (debts[owing.card].owed, debts[owing.card].payment, debts[owing.card].payment_source) == (
        D("12000.00"), D("2000.00"), "rule")
    assert debts[owing.card].yearly_rate == D("36.0000")
    assert (debts[owing.loan].owed, debts[owing.loan].payment_source) == (D("6000.00"), "none")
    assert result.start == date(2026, 10, 1)
    assert result.avalanche is not None  # the card has a rate


def test_a_loans_plan_is_its_payment_when_nothing_is_scheduled_into_it(session, owner, owing):
    recurring_service.create_rule(session, owner, {
        "kind": "installment", "name": "Motorcycle", "account_id": owing.loan, "category_id": owing.gadgets,
        "frequency": "monthly", "start": "2026-10-15", "price": "60000.00", "payments": 12},
        today=date(2026, 9, 28))
    result = payoff_service.plan(session, owner, today=date(2026, 9, 28))
    loan = next(d for d in result.debts if d.account_id == owing.loan)
    # the whole plan is owed from day one (REC-14), paid 5,000 a month
    assert (loan.owed, loan.payment, loan.payment_source) == (D("66000.00"), D("5000.00"), "plan")


def test_a_payment_typed_on_the_planner_wins_and_is_not_stored(session, owner, owing):
    result = payoff_service.plan(session, owner, payments={owing.loan: D("1500.00")}, today=date(2026, 9, 28))
    loan = next(d for d in result.debts if d.account_id == owing.loan)
    assert (loan.payment, loan.payment_source) == (D("1500.00"), "yours")
    again = payoff_service.plan(session, owner, today=date(2026, 9, 28))
    assert next(d for d in again.debts if d.account_id == owing.loan).payment_source == "none"


# ------------------------------------------------------------------ REC-27


def test_a_what_if_changes_the_months_ahead_and_writes_nothing(session, owner, owing):
    before = RecurringRuleRepository(session, owner).count()
    phone = {"kind": "installment", "name": "Phone", "account_id": owing.bank, "category_id": owing.gadgets,
             "frequency": "monthly", "start": "2026-10-10", "price": "36000.00", "payments": 12}
    result = projection_service.what_if(session, owner, phone, today=date(2026, 9, 28), months=3)
    assert RecurringRuleRepository(session, owner).count() == before

    tried = [i for m in result.with_plan.months for i in m.items if i.rule_id == recurring_service.TRIAL_RULE_ID]
    assert [(i.on, i.amount) for i in tried] == [(date(2026, 10, 10), D("3000.00")), (date(2026, 11, 10), D("3000.00"))]
    assert not [i for m in result.without.months for i in m.items if i.rule_id < 0]
    october = next(m for m in result.with_plan.months if m.start <= date(2026, 10, 10) <= m.end)
    same = next(m for m in result.without.months if m.start == october.start)
    assert october.committed - same.committed == D("3000.00")


def test_a_what_if_is_checked_like_a_new_rule(session, owner, owing):
    with pytest.raises(ValidationException):
        projection_service.what_if(session, owner, {"kind": "standard", "type": "expense", "name": "X",
                                                    "account_id": 99999, "category_id": owing.gadgets,
                                                    "frequency": "monthly", "amount": "1.00", "start": "2026-10-01"},
                                   today=date(2026, 9, 28), months=3)


# ------------------------------------------------------------------ CAL-06


def test_the_year_is_twelve_months_as_the_month_view_gives_them(session, owner, owing):
    food = category_service.create_category(session, owner, {"name": "Food"})
    for on in ("2026-03-04", "2026-03-20", "2026-11-02"):
        transaction_service.create_transaction(session, owner, {
            "type": "expense", "amount": "250.00", "account_id": owing.bank, "category_id": food.id, "txn_date": on})
    year = calendar_service.year(session, owner, 2026)
    assert [m.month for m in year.months] == list(range(1, 13))
    assert year.spent == D("750.00")
    march = calendar_service.month(session, owner, 2026, 3)
    assert year.months[2] == march


def test_a_year_outside_the_app_is_refused(session, owner):
    with pytest.raises(ValidationException):
        calendar_service.year(session, owner, 1999)


# ------------------------------------------------------------------ SUB-07


def test_a_cancelled_subscription_says_so_on_its_rule(session, owner, owing):
    sub = recurring_service.create_rule(session, owner, {
        "kind": "subscription", "type": "expense", "name": "Netflix", "account_id": owing.bank,
        "category_id": owing.gadgets, "frequency": "monthly", "amount": "549.00", "start": "2026-10-10"},
        today=date(2026, 9, 28))
    assert sub.cancelled_on is None
    rule = recurring_service.cancel_subscription(session, owner, sub.id, on=date(2026, 9, 28), today=date(2026, 9, 28))
    assert rule.cancelled_on == date(2026, 9, 28)


# ------------------------------------------------------------------ the API


def test_the_new_routes(api):
    assert api.register().status_code == 201
    bank = api.post("/accounts", {"name": "BDO", "type": "debit", "opening_balance": "50000.00"}).json()["id"]
    card = api.post("/accounts", {"name": "Card", "type": "credit", "statement_closing_day": 20,
                                  "payment_due_day": 5, "opening_balance": "-9000.00",
                                  "debt_rate": {"rate": "2.5", "per": "month"}}).json()
    assert card["debt_rate"] == {"rate": "2.5000", "per": "month", "yearly": "30.0000"}
    gadgets = api.post("/categories", {"name": "Gadgets"}).json()["id"]

    payoff = api.post("/projection/payoff", {"extra": "1000.00", "payments": {str(card["id"]): "1500.00"}})
    assert payoff.status_code == 200, payoff.text
    body = payoff.json()
    assert body["debts"][0]["payment_source"] == "yours"
    assert body["avalanche"]["strategy"] == "avalanche"

    what_if = api.post("/projection/what-if", {"kind": "installment", "name": "Phone", "account_id": bank,
                                               "category_id": gadgets, "frequency": "monthly",
                                               "start": "2030-01-10", "price": "12000.00", "payments": 6},
                       params={"months": 3})
    assert what_if.status_code == 200, what_if.text
    assert set(what_if.json()) == {"without", "with_plan"}

    year = api.get("/calendar/2026")
    assert year.status_code == 200 and len(year.json()["months"]) == 12
    assert api.get("/calendar/2026/3").status_code == 200  # the month route is still reachable
