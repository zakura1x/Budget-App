"""
Phase 11's three smaller features, each pinned where it could quietly be wrong:

  GOA-05  required-per-month - counts this month and the target's, rounds UP,
          and says nothing once the date has passed
  SUB-07  cancelling a subscription - nothing charges after the day, what it
          would have cost since is replayed through THE schedule, resuming
          never charges the months it was cancelled, and an edit cannot undo it
  STA-10  cash on hand over time - plain balances of the accounts counted
          today, at the end of each bucket, never a day still to come
"""

from datetime import date
from decimal import Decimal as D

import pytest

from app.core.exceptions import BusinessRuleException
from app.services import (
    account_service,
    category_service,
    goal_service,
    recurring_service,
    stats_service,
    subscription_service,
    transaction_service,
)
from app.services.budget_service import budget_service
from app.services.goal_service import monthly_need


# ------------------------------------------------------------------ GOA-05


def test_this_month_and_the_targets_month_both_count():
    # September to June is ten months: 50,000 / 10
    assert monthly_need(D("50000.00"), date(2026, 9, 28), date(2027, 6, 15)) == (D("5000.00"), 10)


def test_a_target_later_this_month_asks_for_all_of_it_now():
    assert monthly_need(D("1234.56"), date(2026, 9, 1), date(2026, 9, 30)) == (D("1234.56"), 1)


def test_it_rounds_up_so_the_last_month_is_never_short():
    amount, months = monthly_need(D("100.00"), date(2026, 9, 1), date(2026, 11, 1))
    assert (amount, months) == (D("33.34"), 3)
    assert amount * months >= D("100.00")


def test_no_date_a_past_date_or_nothing_left_says_nothing():
    assert monthly_need(D("100.00"), date(2026, 9, 1), None) == (None, None)
    assert monthly_need(D("100.00"), date(2026, 9, 1), date(2026, 8, 31)) == (None, None)
    assert monthly_need(D("0.00"), date(2026, 9, 1), date(2027, 1, 1)) == (None, None)


def test_a_goal_carries_its_monthly_need(session, owner):
    bank = account_service.create_account(session, owner, {"name": "BDO", "type": "savings",
                                                           "opening_balance": "20000.00"})
    goal = goal_service.create_goal(session, owner, {"name": "Trip", "target": "12000.00",
                                                     "target_date": "2027-02-28", "account_id": bank.id},
                                    today=date(2026, 9, 28))
    goal_service.add_money(session, owner, goal.id, {"amount": "2000.00"}, today=date(2026, 9, 28))
    view = goal_service.get_goal(session, owner, goal.id, today=date(2026, 9, 28))
    # 10,000 left over September to February - six months
    assert (view.per_month, view.months_left, view.overdue) == (D("1666.67"), 6, False)

    late = goal_service.get_goal(session, owner, goal.id, today=date(2027, 3, 1))
    assert (late.per_month, late.overdue) == (None, True)


# ------------------------------------------------------------------ SUB-07


@pytest.fixture
def netflix(session, owner):
    wallet = account_service.create_account(session, owner, {"name": "GCash", "type": "cash",
                                                             "opening_balance": "5000.00"})
    streaming = category_service.create_category(session, owner, {"name": "Streaming"})
    rule = recurring_service.create_rule(session, owner, {
        "kind": "subscription", "type": "expense", "name": "Netflix", "account_id": wallet.id,
        "category_id": streaming.id, "frequency": "monthly", "amount": "549.00", "start": "2026-06-10",
        "post_past": True}, today=date(2026, 6, 10))
    recurring_service.expand(session, owner, today=date(2026, 7, 20))  # June and July posted
    return rule


def charges(session, owner, rule_id):
    return sorted(v.txn_date for v in transaction_service.views(session, owner) if v.recurring_id == rule_id)


def test_nothing_charges_after_the_day_it_was_cancelled(session, owner, netflix):
    recurring_service.cancel_subscription(session, owner, netflix.id, on=date(2026, 7, 20), today=date(2026, 7, 20))
    recurring_service.expand(session, owner, today=date(2026, 12, 31))
    assert charges(session, owner, netflix.id) == [date(2026, 6, 10), date(2026, 7, 10)]


def test_a_cancelled_one_is_listed_with_what_it_has_saved(session, owner, netflix):
    recurring_service.cancel_subscription(session, owner, netflix.id, on=date(2026, 7, 20), today=date(2026, 7, 20))
    overview = subscription_service.overview(session, owner, today=date(2026, 10, 1))
    [item] = overview.items
    # August, September: 2 x 549 - October's 10th is still to come
    assert (item.cancelled_on, item.saved) == (date(2026, 7, 20), D("1098.00"))
    assert overview.monthly_total == D("0.00")
    assert item.due_in_days is None and not item.remind


def test_a_charge_that_posted_before_a_late_cancellation_is_not_saved(session, owner, netflix):
    """Cancelled as of 20 Jul but only entered on 20 Sep: August's and September's charges were real."""
    recurring_service.expand(session, owner, today=date(2026, 9, 20))  # Aug 10 and Sep 10 post
    recurring_service.cancel_subscription(session, owner, netflix.id, on=date(2026, 7, 20), today=date(2026, 9, 20))
    assert date(2026, 8, 10) in charges(session, owner, netflix.id)  # stays - it was money
    [item] = subscription_service.overview(session, owner, today=date(2026, 10, 15)).items
    assert item.saved == D("549.00")  # only October's


def test_resuming_charges_from_today_never_the_missed_months(session, owner, netflix):
    recurring_service.cancel_subscription(session, owner, netflix.id, on=date(2026, 7, 20), today=date(2026, 7, 20))
    recurring_service.resume_subscription(session, owner, netflix.id, today=date(2026, 10, 5))
    recurring_service.expand(session, owner, today=date(2026, 10, 10))
    assert charges(session, owner, netflix.id)[-1] == date(2026, 10, 10)
    assert date(2026, 8, 10) not in charges(session, owner, netflix.id)
    [item] = subscription_service.overview(session, owner, today=date(2026, 10, 11)).items
    assert item.cancelled_on is None


def test_an_edit_cannot_quietly_restart_a_cancelled_one(session, owner, netflix):
    recurring_service.cancel_subscription(session, owner, netflix.id, on=date(2026, 7, 20), today=date(2026, 7, 20))
    recurring_service.update_rule(session, owner, netflix.id, {"name": "Netflix Premium", "end_on": None},
                                  today=date(2026, 7, 21))
    recurring_service.expand(session, owner, today=date(2026, 9, 30))
    assert charges(session, owner, netflix.id)[-1] == date(2026, 7, 10)


def test_cancel_and_resume_each_happen_once(session, owner, netflix):
    recurring_service.cancel_subscription(session, owner, netflix.id, today=date(2026, 7, 20))
    with pytest.raises(BusinessRuleException):
        recurring_service.cancel_subscription(session, owner, netflix.id, today=date(2026, 7, 21))
    recurring_service.resume_subscription(session, owner, netflix.id, today=date(2026, 7, 21))
    with pytest.raises(BusinessRuleException):
        recurring_service.resume_subscription(session, owner, netflix.id, today=date(2026, 7, 22))


def test_only_a_subscription_is_cancelled(session, owner, netflix):
    rent = recurring_service.create_rule(session, owner, {
        "kind": "standard", "type": "expense", "name": "Rent", "account_id": netflix.account_id,
        "category_id": netflix.category_id, "frequency": "monthly", "amount": "100.00",
        "start": "2026-08-01"}, today=date(2026, 7, 20))
    with pytest.raises(BusinessRuleException):
        recurring_service.cancel_subscription(session, owner, rent.id, today=date(2026, 7, 20))


def test_a_cancel_by_date_is_reminded_like_a_charge(session, owner, netflix):
    recurring_service.set_cancel_by(session, owner, netflix.id, date(2026, 7, 31), today=date(2026, 7, 20))
    far = subscription_service.overview(session, owner, today=date(2026, 7, 20)).items[0]
    assert (far.cancel_by, far.cancel_soon) == (date(2026, 7, 31), False)

    alerts = budget_service.standalone_alerts(session, owner, today=date(2026, 7, 29))
    assert [(a.kind, a.message) for a in alerts if a.kind == "subscription_cancel_by"] == [
        ("subscription_cancel_by", "Cancel Netflix within 2 days")]

    recurring_service.set_cancel_by(session, owner, netflix.id, None, today=date(2026, 7, 29))
    alerts = budget_service.standalone_alerts(session, owner, today=date(2026, 7, 29))
    assert not [a for a in alerts if a.kind == "subscription_cancel_by"]


# ------------------------------------------------------------------ STA-10


@pytest.fixture
def pockets(session, owner):
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash",
                                                             "opening_balance": "1000.00"})
    bank = account_service.create_account(session, owner, {"name": "BDO", "type": "debit",
                                                           "opening_balance": "5000.00"})
    fund = account_service.create_account(session, owner, {"name": "Fund", "type": "investment",
                                                           "opening_balance": "90000.00"})
    food = category_service.create_category(session, owner, {"name": "Food"})

    class P:
        pass

    p = P()
    p.wallet, p.bank, p.fund, p.food = wallet.id, bank.id, fund.id, food.id
    return p


def test_a_point_per_bucket_at_its_end_and_none_in_the_future(session, owner, pockets):
    for on, amount in (("2026-09-02", "100.00"), ("2026-09-09", "250.00"), ("2026-09-20", "50.00")):
        transaction_service.create_transaction(session, owner, {
            "type": "expense", "amount": amount, "account_id": pockets.wallet, "category_id": pockets.food,
            "txn_date": on})
    overview = stats_service.overview(session, owner, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30),
                                      granularity="week", today=date(2026, 9, 16))
    points = [(p.on, p.amount) for p in overview.cash_on_hand]
    # weeks count from the range's first day - ending the 7th, the 14th - then today (the 16th)
    # for the week it is in; nothing after it
    assert points == [(date(2026, 9, 7), D("5900.00")), (date(2026, 9, 14), D("5650.00")),
                      (date(2026, 9, 16), D("5650.00"))]


def test_only_accounts_counted_today_and_a_transfer_between_them_moves_nothing(session, owner, pockets):
    transaction_service.create_transaction(session, owner, {
        "type": "transfer", "amount": "700.00", "account_id": pockets.bank, "counter_account_id": pockets.wallet,
        "txn_date": "2026-09-05"})
    [before, after] = account_service.cash_history(session, owner, [date(2026, 9, 4), date(2026, 9, 5)],
                                                   transaction_service.postings(session, owner))
    assert before == after == D("6000.00")  # the fund is off cash on hand, as it is by default


def test_an_investment_is_read_through_its_valuations(session, owner, pockets):
    record = account_service.get_account(session, owner, pockets.fund)
    data = {"type": "investment", "opening_balance": str(record.opening_balance),
            "valuations": [{"on": "2026-09-10", "value": "95000.00"}]}
    before = account_service.balance_on(data, [], date(2026, 9, 9))
    after = account_service.balance_on(data, [], date(2026, 9, 10))
    assert (before, after) == (D("90000.00"), D("95000.00"))
