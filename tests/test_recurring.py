"""
The recurring engine (REC-01..30, SUB-00..08) and the projection built on it.

The bugs this guards against are the expensive, quiet ones: a catch-up that
posts a charge twice, a deleted charge that comes back the next morning, an
installment whose parts do not add up to the price, a 37th payment, a skip
that makes debt disappear, and a projection that shows something different
from what later posts.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessRuleException, ConflictException, ValidationException
from app.db.repositories.transaction_repository import TransactionRepository
from app.services import (
    account_service,
    category_service,
    projection_service,
    recurring_service,
    statement_service,
    subscription_service,
    tag_service,
    transaction_service,
)
from app.services.budget_service import budget_service
from app.services.recurring_service import occurrences, schedule_dates, split_schedule

D = Decimal


@pytest.fixture
def books(session, owner):
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash",
                                                             "opening_balance": "5000.00"})
    bdo = account_service.create_account(session, owner, {"name": "BDO", "type": "debit",
                                                          "opening_balance": "50000.00"})
    card = account_service.create_account(session, owner, {"name": "BPI Card", "type": "credit",
                                                           "statement_closing_day": 16, "payment_due_day": 6,
                                                           "credit_limit": "100000.00"})
    rent = category_service.create_category(session, owner, {"name": "Rent"})
    gadgets = category_service.create_category(session, owner, {"name": "Gadgets"})
    financial = category_service.create_category(session, owner, {"name": "Financial"})
    interest = category_service.create_category(session, owner, {"name": "Interest", "parent_id": financial.id})
    streaming = category_service.create_category(session, owner, {"name": "Streaming"})
    salary = category_service.create_category(session, owner, {"name": "Salary", "kind": "income"})

    class B:
        pass

    b = B()
    b.wallet, b.bdo, b.card = wallet.id, bdo.id, card.id
    b.rent, b.gadgets, b.interest, b.streaming, b.salary = rent.id, gadgets.id, interest.id, streaming.id, salary.id
    return b


def rule(session, owner, books, today, **payload):
    base = {"kind": "standard", "type": "expense", "name": "Rent", "account_id": books.wallet,
            "category_id": books.rent, "frequency": "monthly", "amount": "1000.00"}
    return recurring_service.create_rule(session, owner, {**base, **payload}, today=today)


def phone(session, owner, books, today=date(2026, 9, 20), **payload):
    base = {"kind": "installment", "name": "Phone", "account_id": books.card, "category_id": books.gadgets,
            "frequency": "monthly", "start": "2026-09-20", "price": "40000.00", "payments": 6}
    return recurring_service.create_rule(session, owner, {**base, **payload}, today=today)


def posted(session, owner, rule_id):
    views = [v for v in transaction_service.views(session, owner) if v.recurring_id == rule_id]
    return sorted(views, key=lambda v: (v.txn_date, v.id))


# --------------------------------------------------------- the pure schedule


def test_split_schedule_puts_the_rounding_on_the_last_payment():
    assert split_schedule(D("40000.00"), 6) == [D("6666.67")] * 5 + [D("6666.65")]
    parts = split_schedule(D("100000.00"), 36)
    assert (parts[0], parts[-1], sum(parts)) == (D("2777.78"), D("2777.70"), D("100000.00"))


def test_a_monthly_rule_keeps_its_day_where_the_month_has_it():
    data = {"start": "2026-01-31", "frequency": "monthly", "interval": 1}
    assert list(schedule_dates(data, date(2026, 4, 30))) == [
        date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_semi_monthly_clamps_the_30th_in_february():
    data = {"start": "2026-02-01", "frequency": "semi_monthly", "days": [15, 30]}
    assert list(schedule_dates(data, date(2026, 3, 31))) == [
        date(2026, 2, 15), date(2026, 2, 28), date(2026, 3, 15), date(2026, 3, 30)]


def test_every_two_weeks_and_end_conditions():
    data = {"kind": "standard", "type": "expense", "start": "2026-09-01", "frequency": "weekly", "interval": 2,
            "amounts": [{"from": "2026-09-01", "amount": "100.00"}], "end_after": 3}
    found = occurrences(1, data, date(2026, 1, 1), date(2027, 1, 1))
    assert [o.on for o in found] == [date(2026, 9, 1), date(2026, 9, 15), date(2026, 9, 29)]
    assert found[-1].final
    until = {**data, "end_after": None, "end_on": "2026-09-20"}
    assert len(occurrences(1, until, date(2026, 1, 1), date(2027, 1, 1))) == 2


def test_an_amount_change_applies_from_its_date():
    data = {"kind": "standard", "type": "income", "start": "2026-11-15", "frequency": "monthly",
            "amounts": [{"from": "2026-11-15", "amount": "25000.00"}, {"from": "2027-01-01", "amount": "27000.00"}]}
    assert [o.amount for o in occurrences(1, data, date(2026, 11, 1), date(2027, 2, 28))] == [
        D("25000.00"), D("25000.00"), D("27000.00"), D("27000.00")]


# ---------------------------------------------------------------- expansion


def test_catch_up_posts_each_occurrence_exactly_once(session, owner, books):
    created = rule(session, owner, books, date(2026, 9, 1), start="2026-09-01", frequency="weekly")
    assert len(posted(session, owner, created.id)) == 1  # a rule starting today posts today

    first = recurring_service.expand(session, owner, today=date(2026, 9, 29))
    again = recurring_service.expand(session, owner, today=date(2026, 9, 29))
    assert (first.posted, again.posted) == (4, 0)
    assert [v.txn_date.day for v in posted(session, owner, created.id)] == [1, 8, 15, 22, 29]


def test_a_new_rule_does_not_post_the_past_unless_asked(session, owner, books):
    quiet = rule(session, owner, books, date(2026, 9, 14), start="2026-06-01")
    loud = rule(session, owner, books, date(2026, 9, 14), start="2026-06-01", name="Back rent", post_past=True)
    assert (len(posted(session, owner, quiet.id)), len(posted(session, owner, loud.id))) == (0, 4)


def test_a_deleted_charge_does_not_come_back(session, owner, books):
    created = rule(session, owner, books, date(2026, 9, 1), start="2026-09-01")
    transaction_service.delete_transaction(session, owner, posted(session, owner, created.id)[0].id)
    recurring_service.expand(session, owner, today=date(2026, 9, 30))
    assert posted(session, owner, created.id) == []


def test_a_recurring_charge_reduces_the_allowance_on_its_day(session, owner, books):
    budget_service.create_budget(session, owner, {"period": "monthly", "amount": "30000.00"}, today=date(2026, 9, 1))
    rule(session, owner, books, date(2026, 9, 1), start="2026-09-10", amount="5000.00")
    recurring_service.expand(session, owner, today=date(2026, 9, 9))
    assert budget_service.status(session, owner, today=date(2026, 9, 9)).allowance.spent == D("0.00")
    recurring_service.expand(session, owner, today=date(2026, 9, 10))
    assert budget_service.status(session, owner, today=date(2026, 9, 10)).allowance.spent_today == D("5000.00")


def test_a_pause_is_never_caught_up(session, owner, books):
    created = rule(session, owner, books, date(2026, 9, 1), start="2026-09-01")
    recurring_service.set_paused(session, owner, created.id, True, today=date(2026, 9, 15))
    recurring_service.expand(session, owner, today=date(2026, 11, 20))
    resumed = recurring_service.set_paused(session, owner, created.id, False, today=date(2026, 11, 20))
    assert resumed.next_on == date(2026, 12, 1)
    recurring_service.expand(session, owner, today=date(2026, 12, 1))
    assert [v.txn_date for v in posted(session, owner, created.id)] == [date(2026, 9, 1), date(2026, 12, 1)]


def test_an_archived_account_holds_a_rule_back_instead_of_failing(session, owner, books):
    created = rule(session, owner, books, date(2026, 9, 1), start="2026-09-01")
    account_service.set_archived(session, owner, books.wallet, True)
    result = recurring_service.expand(session, owner, today=date(2026, 10, 1))
    assert (result.posted, result.needs_attention) == (0, (created.id,))


def test_a_transfer_rule_posts_both_legs_once(session, owner, books):
    created = rule(session, owner, books, date(2026, 9, 1), type="transfer", name="Savings", account_id=books.bdo,
                   counter_account_id=books.wallet, category_id=None, start="2026-09-01")
    legs = posted(session, owner, created.id)
    assert sorted(v.direction for v in legs) == ["in", "out"]
    assert recurring_service.expand(session, owner, today=date(2026, 9, 1)).posted == 0


def test_an_amount_change_never_rewrites_what_posted(session, owner, books):
    created = rule(session, owner, books, date(2026, 9, 1), start="2026-09-01")
    recurring_service.update_rule(session, owner, created.id, {"amount": "1200.00", "amount_from": "2026-10-01"},
                                  today=date(2026, 9, 2))
    recurring_service.expand(session, owner, today=date(2026, 10, 1))
    assert [v.amount for v in posted(session, owner, created.id)] == [D("1000.00"), D("1200.00")]
    history = recurring_service.get_rule(session, owner, created.id, today=date(2026, 10, 1)).amounts
    assert [(a.on, a.amount) for a in history] == [(date(2026, 9, 1), D("1000.00")), (date(2026, 10, 1), D("1200.00"))]


# -------------------------------------------------------------- installments


def test_the_phone_from_price_and_months_confirmed_by_the_first_bill(session, owner, books):
    """FEATURES §21: ₱40,000 × 6, first bill +₱400 -> 7,066.67 × 5 + 7,066.65."""
    plan = phone(session, owner, books)
    assert (plan.installment.terms, plan.installment.per_payment, plan.amount) == (
        "provisional", D("6666.67"), D("6666.67"))

    check = statement_service.check(session, owner, books.card, date(2026, 10, 16), "7066.67", today=date(2026, 10, 17))
    assert check.statement.difference == D("400.00")
    assert check.suggestions[0] == "installment_interest"
    assert [(p.rule_id, p.name) for p in check.installments] == [(plan.id, "Phone")]

    resolved = statement_service.resolve(session, owner, books.card, date(2026, 10, 16),
                                         {"choice": "installment_interest", "amount": "400.00"}, today=date(2026, 10, 17))
    assert resolved.checked is True
    confirmed = recurring_service.get_rule(session, owner, plan.id, today=date(2026, 10, 17))
    assert (confirmed.installment.terms, confirmed.installment.total, confirmed.installment.remaining) == (
        "confirmed", D("42400.00"), D("35333.33"))

    recurring_service.expand(session, owner, today=date(2027, 3, 31))
    payments = [v for v in posted(session, owner, plan.id) if v.recurring_on is not None]
    assert [v.amount for v in payments] == [D("6666.67")] + [D("7066.67")] * 4 + [D("7066.65")]
    splits = [s for v in posted(session, owner, plan.id) for s in v.splits]
    assert sum(s.amount for s in splits if s.category_id == books.gadgets) == D("40000.00")
    assert sum(s.amount for s in splits if s.category_id == books.interest) == D("2400.00")

    done = recurring_service.get_rule(session, owner, plan.id, today=date(2027, 3, 31))
    assert (done.installment.remaining, done.installment.closed, done.next_on) == (D("0.00"), True, None)


def test_thirty_six_payments_then_nothing(session, owner, books):
    plan = recurring_service.create_rule(session, owner, {
        "kind": "installment", "name": "Motorcycle", "account_id": books.bdo, "category_id": books.gadgets,
        "frequency": "monthly", "start": "2024-01-15", "price": "100000.00", "payments": 36, "interest": "0.00",
    }, today=date(2024, 1, 15))
    recurring_service.expand(session, owner, today=date(2025, 6, 30))  # a long gap
    recurring_service.expand(session, owner, today=date(2027, 6, 30))
    recurring_service.expand(session, owner, today=date(2027, 6, 30))
    payments = posted(session, owner, plan.id)
    assert (len(payments), sum(v.amount for v in payments), payments[-1].amount) == (36, D("100000.00"), D("2777.70"))
    status = recurring_service.get_rule(session, owner, plan.id, today=date(2027, 6, 30)).installment
    assert (status.remaining, status.closed, status.payments_posted) == (D("0.00"), True, 36)


def test_skipping_a_payment_moves_the_payoff_and_owes_the_same(session, owner, books):
    plan = recurring_service.create_rule(session, owner, {
        "kind": "installment", "name": "Laptop", "account_id": books.bdo, "category_id": books.gadgets,
        "frequency": "monthly", "start": "2026-09-10", "price": "3000.00", "payments": 3,
    }, today=date(2026, 9, 10))
    assert plan.installment.payoff_on == date(2026, 11, 10)
    skipped = recurring_service.skip(session, owner, plan.id, date(2026, 10, 10), today=date(2026, 9, 20))
    assert (skipped.installment.payoff_on, skipped.installment.remaining, skipped.next_on) == (
        date(2026, 12, 10), D("2000.00"), date(2026, 11, 10))


def test_an_installment_cannot_be_paused(session, owner, books):
    plan = phone(session, owner, books)
    with pytest.raises(BusinessRuleException):
        recurring_service.set_paused(session, owner, plan.id, True, today=date(2026, 9, 21))


def test_paying_off_closes_the_plan(session, owner, books):
    plan = phone(session, owner, books, interest="2400.00")
    paid = recurring_service.pay_off(session, owner, plan.id, today=date(2026, 9, 25))
    assert (paid.installment.remaining, paid.installment.closed, paid.next_on) == (D("0.00"), True, None)
    payoff = posted(session, owner, plan.id)[-1]
    assert sorted((s.category_id, s.amount) for s in payoff.splits) == sorted(
        [(books.gadgets, D("33333.33")), (books.interest, D("2000.00"))])
    assert recurring_service.expand(session, owner, today=date(2027, 6, 1)).posted == 0


def test_available_credit_subtracts_the_whole_unpaid_remainder(session, owner, books):
    phone(session, owner, books)
    card = account_service.get_account(session, owner, books.card, postings=transaction_service.postings(session, owner),
                                       today=date(2026, 9, 21))
    # Owed 6,666.67 for payment 1; the bank still blocks the 33,333.33 to come.
    assert (card.credit.unpaid_installments, card.credit.available) == (D("33333.33"), D("60000.00"))


def test_terms_are_fixed_once_payments_have_posted(session, owner, books):
    plan = phone(session, owner, books)
    with pytest.raises(BusinessRuleException):
        recurring_service.update_rule(session, owner, plan.id, {"payments": 12}, today=date(2026, 9, 21))
    renamed = recurring_service.update_rule(session, owner, plan.id, {"name": "iPhone"}, today=date(2026, 9, 21))
    assert renamed.name == "iPhone"


def test_a_lower_bill_is_never_installment_interest(session, owner, books):
    phone(session, owner, books)
    statement_service.check(session, owner, books.card, date(2026, 10, 16), "6000.00", today=date(2026, 10, 17))
    with pytest.raises(BusinessRuleException):
        statement_service.resolve(session, owner, books.card, date(2026, 10, 16),
                                  {"choice": "installment_interest", "amount": "400.00"}, today=date(2026, 10, 17))


# ------------------------------------------------------ references stay whole


def test_a_category_a_rule_uses_moves_with_the_rule(session, owner, books):
    created = rule(session, owner, books, date(2026, 9, 14), start="2026-10-01")
    with pytest.raises(ConflictException):
        category_service.delete_category(session, owner, books.rent)
    category_service.delete_category(session, owner, books.rent, reassign_to=books.gadgets)
    assert recurring_service.get_rule(session, owner, created.id, today=date(2026, 9, 14)).category_id == books.gadgets


def test_deleting_a_tag_strips_it_from_rules(session, owner, books):
    tag = tag_service.create_tag(session, owner, {"name": "Home"})
    created = rule(session, owner, books, date(2026, 9, 14), start="2026-10-01", tag_ids=[tag.id])
    tag_service.delete_tag(session, owner, tag.id)
    assert recurring_service.get_rule(session, owner, created.id, today=date(2026, 9, 14)).tag_ids == ()


# ---------------------------------------------------------------- projection


def test_projection_matches_what_later_posts_and_writes_nothing(session, owner, books):
    today = date(2026, 9, 14)
    salary = rule(session, owner, books, today, type="income", name="Salary", account_id=books.bdo,
                  category_id=books.salary, frequency="semi_monthly", days=[15, 30], start="2026-09-15",
                  amount="25000.00")
    netflix = rule(session, owner, books, today, kind="subscription", name="Netflix", category_id=books.streaming,
                   account_id=books.card, start="2026-10-05", amount="549.00")
    count = TransactionRepository(session, owner).count()

    projection = projection_service.project(session, owner, today=today, months=3)
    assert TransactionRepository(session, owner).count() == count
    projected = {(i.rule_id, i.on, i.amount) for m in projection.months for i in m.items}

    recurring_service.expand(session, owner, today=date(2026, 11, 30))
    actual = {(v.recurring_id, v.recurring_on, v.amount) for v in transaction_service.views(session, owner)
              if v.recurring_id in (salary.id, netflix.id)}
    assert projected == actual


def test_months_ahead_without_a_budget(session, owner, books):
    today = date(2026, 9, 30)
    rule(session, owner, books, today, start="2026-10-01", amount="12000.00")
    rule(session, owner, books, today, type="income", name="Salary", category_id=books.salary,
         frequency="semi_monthly", days=[15, 30], start="2026-10-15", amount="25000.00")
    account_service.set_archived(session, owner, books.bdo, True)
    account_service.set_archived(session, owner, books.card, True)

    months = projection_service.project(session, owner, today=today, months=3).months
    october = months[1]
    assert (october.opening, october.income, october.committed, october.closing) == (
        D("5000.00"), D("50000.00"), D("12000.00"), D("43000.00"))
    assert (october.low_point, october.low_on, october.overcommitted) == (D("-7000.00"), date(2026, 10, 1), True)


def test_the_flexible_budget_is_set_aside_on_day_one(session, owner, books):
    today = date(2026, 9, 30)
    budget_service.create_budget(session, owner, {"period": "monthly", "amount": "30000.00"}, today=today)
    rule(session, owner, books, today, start="2026-10-01", amount="12000.00")
    account_service.set_archived(session, owner, books.bdo, True)
    account_service.set_archived(session, owner, books.card, True)
    october = projection_service.project(session, owner, today=today, months=3).months[1]
    # Opening -25,000 (September's whole remaining budget set against 5,000), then
    # 18,000 of flexible budget aside, then rent.
    assert (october.opening, october.spending, october.low_point, october.overcommitted) == (
        D("-25000.00"), D("30000.00"), D("-55000.00"), False)


def test_card_lookahead_stops_at_the_final_payment(session, owner, books):
    today = date(2026, 10, 17)
    rule(session, owner, books, today, kind="subscription", name="Netflix", account_id=books.card,
         category_id=books.streaming, start="2026-11-05", amount="549.00")
    recurring_service.create_rule(session, owner, {
        "kind": "installment", "name": "Phone", "account_id": books.card, "category_id": books.gadgets,
        "frequency": "monthly", "start": "2026-11-10", "price": "6000.00", "payments": 2,
    }, today=today)
    card = projection_service.cards(session, owner, today=today, statements=3)[0]
    assert [(s.closes, s.recurring, s.due) for s in card.statements] == [
        (date(2026, 11, 16), D("3549.00"), date(2026, 12, 6)),
        (date(2026, 12, 16), D("3549.00"), date(2027, 1, 6)),
        (date(2027, 1, 16), D("549.00"), date(2027, 2, 6)),
    ]


# ------------------------------------------------------------- subscriptions


def test_subscriptions_total_upcoming_and_reminders(session, owner, books):
    today = date(2026, 9, 14)
    budget_service.create_budget(session, owner, {"period": "monthly", "amount": "30000.00"}, today=today)
    netflix = rule(session, owner, books, today, kind="subscription", name="Netflix", category_id=books.streaming,
                   start="2026-09-16", amount="549.00", reminder_days=3)
    rule(session, owner, books, today, kind="subscription", name="iCloud", category_id=books.streaming,
         frequency="yearly", start="2027-01-01", amount="1200.00")

    overview = subscription_service.overview(session, owner, today=today)
    assert (overview.monthly_total, overview.budget_share) == (D("649.00"), D("0.0216"))
    assert [(u.name, u.on) for u in overview.upcoming] == [("Netflix", date(2026, 9, 16))]
    alerts = budget_service.status(session, owner, today=today).alerts
    assert [(a.kind, a.rule_id, a.message) for a in alerts] == [("subscription_due", netflix.id, "Netflix charges in 2 days")]


def test_detection_proposes_and_never_charges(session, owner, books):
    for on in ("2026-06-05", "2026-07-05", "2026-08-05"):
        transaction_service.create_transaction(session, owner, {
            "type": "expense", "amount": "549.00", "account_id": books.wallet, "category_id": books.streaming,
            "txn_date": on, "merchant": "Netflix"})
    transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": "549.00", "account_id": books.wallet, "category_id": books.streaming,
        "txn_date": "2026-08-20", "merchant": "Groceries"})
    count = TransactionRepository(session, owner).count()

    found = subscription_service.detected(session, owner, today=date(2026, 9, 1))
    assert [(c.merchant, c.amount, c.months, c.next_on) for c in found] == [
        ("Netflix", D("549.00"), 3, date(2026, 9, 5))]
    assert TransactionRepository(session, owner).count() == count

    rule(session, owner, books, date(2026, 9, 1), kind="subscription", name="Netflix", merchant="Netflix",
         category_id=books.streaming, start="2026-09-05", amount="549.00")
    assert subscription_service.detected(session, owner, today=date(2026, 9, 1)) == []


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize("payload", [
    {"frequency": "semi_monthly", "days": [15]},
    {"end_on": "2026-01-01"},
    {"kind": "installment", "type": "income", "price": "100.00", "payments": 2},
    {"kind": "installment", "price": "0.05", "payments": 12},
    {"amount": None},
])
def test_bad_rules_are_refused(session, owner, books, payload):
    with pytest.raises((ValidationException, BusinessRuleException)):
        rule(session, owner, books, date(2026, 9, 14), start="2026-10-01", **payload)


# ----------------------------------------------------------------------- API


def test_recurring_through_the_api(api):
    assert api.register().status_code == 201
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "20000.00"}).json()["id"]
    rent = api.post("/categories", {"name": "Rent"}).json()["id"]
    body = {"kind": "standard", "type": "expense", "name": "Rent", "account_id": wallet, "category_id": rent,
            "frequency": "monthly", "start": "2026-09-01", "amount": "12000.00"}

    preview = api.post("/recurring/preview?today=2026-09-14", body)
    assert [o["on"] for o in preview.json()][:2] == ["2026-10-01", "2026-11-01"]

    created = api.post("/recurring?today=2026-09-14", body)
    assert created.status_code == 201, created.text
    assert created.json()["next_on"] == "2026-10-01"
    assert api.post("/recurring/expand?today=2026-10-02").json() == {"posted": 1, "rules": 1, "needs_attention": []}
    assert api.post("/recurring/expand?today=2026-10-02").json()["posted"] == 0

    projection = api.get("/projection?today=2026-10-02&months=3").json()
    assert [m["committed"] for m in projection["months"]] == ["0.00", "12000.00", "12000.00"]
    assert api.get("/projection?months=5").status_code == 422
    assert api.get("/projection/cards?today=2026-10-02").json() == []
    assert api.get("/subscriptions?today=2026-10-02").json()["monthly_total"] == "0.00"
    assert api.delete(f"/recurring/{created.json()['id']}").status_code == 204
