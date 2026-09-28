"""
Phase 13 - money set aside, and a safety net (misc/ROADMAP.md).

  GOA-11  the emergency advisor's rules, one test each, as the user approved
          them on 2026-09-28 - and the clamp, and too little history
  GOA-10  essential monthly spending (essential categories by name or switch,
          plus everything a repeating rule posted) and which money counts
  GOA-09  sinking funds: one that follows a yearly bill, one that repeats,
          this month's part, and the bills with no fund yet
  GOA-12  the payday prompt: when it asks, what it suggests, and that an
          answer - set aside or not now - is kept on the server and final
"""

from datetime import date
from decimal import Decimal as D

import pytest

from app.core.exceptions import BusinessRuleException, ValidationException
from app.core.utils.emergency import swing, target_months
from app.db.repositories.category_repository import CategoryRepository
from app.db.repositories.transaction_repository import TransactionRepository
from app.services import (
    account_service,
    category_service,
    goal_service,
    preferences_service,
    recurring_service,
    safety_service,
    transaction_service,
)

TODAY = date(2026, 9, 28)
STEADY = [D("30000")] * 6


def rules(**extra):
    base = {"work": "employee", "dependents": "0", "earners": "1", "incomes": STEADY, "sources": 2, "debt": D("0")}
    return target_months(**{**base, **extra})


# ------------------------------------------------------------------ GOA-11


def test_the_base_by_kind_of_work():
    assert rules().months == 3
    assert rules(work="contract").months == 6
    assert rules(work="self").months == 6


def test_income_that_swings_adds_one_or_two():
    assert swing([D("100"), D("100")]) == D("0")
    some = [D("30000"), D("20000"), D("30000"), D("20000")]  # 20% swing - nothing
    assert rules(incomes=some).months == 3
    more = [D("30000"), D("15000"), D("30000"), D("15000")]  # 33%
    assert rules(incomes=more).months == 4
    lots = [D("40000"), D("5000"), D("40000"), D("5000")]  # 78%
    assert rules(incomes=lots).months == 5


def test_one_source_a_month_with_nothing_and_heavy_debt_each_add_one():
    assert rules(sources=1).months == 4
    assert rules(debt=D("10000")).months == 4  # a third of 30,000
    gap = [D("30000"), D("30000"), D("0"), D("30000"), D("30000"), D("30000")]
    fired = {f.code for f in rules(incomes=gap).fired}
    assert "no_income" in fired


def test_dependents_add_and_a_second_earner_takes_one_off():
    assert rules(dependents="1-2").months == 4
    assert rules(dependents="3+").months == 5
    assert rules(work="contract", earners="2+").months == 5


def test_it_stays_between_three_and_twelve_and_says_so():
    low = rules(earners="2+")  # 3 - 1 = 2
    assert low.months == 3 and low.fired[-1].code == "clamp"
    high = rules(work="self", dependents="3+", sources=1, debt=D("20000"),
                 incomes=[D("40000"), D("0"), D("40000"), D("0"), D("40000"), D("0")])
    assert high.months == 12


def test_too_little_history_is_the_base_only():
    short = rules(incomes=[D("30000")] * 2, sources=1)
    assert (short.months, short.short_history) == (3, True)
    assert [f.code for f in short.fired] == ["base"]


def test_an_unknown_answer_is_refused():
    with pytest.raises(ValueError):
        rules(work="astronaut")


# ------------------------------------------------------------ fixtures


@pytest.fixture
def books(session, owner):
    bank = account_service.create_account(session, owner, {"name": "BDO", "type": "savings",
                                                           "opening_balance": "100000.00"})
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash",
                                                             "opening_balance": "5000.00"})
    rent = category_service.create_category(session, owner, {"name": "Rent"})
    fun = category_service.create_category(session, owner, {"name": "Fun"})
    streaming = category_service.create_category(session, owner, {"name": "Streaming"})
    insurance = category_service.create_category(session, owner, {"name": "Insurance"})
    salary = category_service.create_category(session, owner, {"name": "Salary", "kind": "income"})
    cashback = category_service.create_category(session, owner, {"name": "Cashback", "kind": "income"})

    class B:
        pass

    b = B()
    b.bank, b.wallet, b.rent, b.fun, b.streaming = bank.id, wallet.id, rent.id, fun.id, streaming.id
    b.insurance, b.salary, b.cashback = insurance.id, salary.id, cashback.id
    return b


def spend(session, owner, books, amount, on, category, account=None):
    transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": amount, "account_id": account or books.bank, "category_id": category,
        "txn_date": on})


def earn(session, owner, books, amount, on, category=None):
    return transaction_service.create_transaction(session, owner, {
        "type": "income", "amount": amount, "account_id": books.bank, "category_id": category or books.salary,
        "txn_date": on, "merchant": "Acme"}).transactions[0]


# ----------------------------------------------------------- essentials


def test_categories_are_essential_by_name_until_switched(session, owner, books):
    records = CategoryRepository(session, owner).list()
    essential = category_service.essential_ids(records)
    assert books.rent in essential and books.insurance in essential
    assert books.fun not in essential and books.salary not in essential  # income never
    category_service.update_category(session, owner, books.rent, {"name": "Rent", "essential": False})
    category_service.update_category(session, owner, books.fun, {"name": "Fun", "essential": True})
    essential = category_service.essential_ids(CategoryRepository(session, owner).list())
    assert books.rent not in essential and books.fun in essential


def test_a_sub_category_follows_its_parent(session, owner, books):
    child = category_service.create_category(session, owner, {"name": "Condo", "parent_id": books.rent})
    assert child.id in category_service.essential_ids(CategoryRepository(session, owner).list())


def test_essential_spending_counts_essentials_and_what_repeats(session, owner, books):
    for month in ("06", "07", "08"):
        spend(session, owner, books, "10000.00", f"2026-{month}-05", books.rent)
        spend(session, owner, books, "4000.00", f"2026-{month}-10", books.fun)  # not essential
    transaction_service.post_recurring(session, owner, {
        "type": "expense", "amount": "600.00", "account_id": books.bank, "category_id": books.streaming,
        "txn_date": "2026-08-12"}, recurring_id=1, recurring_on=date(2026, 8, 12))  # a repeating charge counts
    session.commit()
    need = safety_service.essentials(session, owner, today=TODAY)
    # June, July, August have history: (30,000 + 600) / 3
    assert (need.monthly, need.months, need.guessing) == (D("10200.00"), 3, False)


def test_with_nothing_essential_it_guesses_seventy_percent(session, owner, books):
    for category in (books.rent, books.insurance, books.streaming):
        name = CategoryRepository(session, owner).get(category).data["name"]
        category_service.update_category(session, owner, category, {"name": name, "essential": False})
    spend(session, owner, books, "1000.00", "2026-08-05", books.fun)
    need = safety_service.essentials(session, owner, today=TODAY)
    assert (need.monthly, need.guessing) == (D("700.00"), True)


# --------------------------------------------------------------- GOA-10


def test_the_advice_uses_cash_on_hand_until_there_is_an_emergency_fund(session, owner, books):
    for month in ("06", "07", "08"):
        spend(session, owner, books, "10000.00", f"2026-{month}-05", books.rent)
        earn(session, owner, books, "30000.00", f"2026-{month}-15")
    first = safety_service.advice(session, owner, today=TODAY)
    assert (first.source, first.essentials.monthly) == ("cash", D("10000.00"))
    assert first.money == D("165000.00")  # 105,000 opening + 90,000 - 30,000
    assert first.cover_months == D("16.5")
    # regular employee (not answered yet) 3, one source +1 -> 4 months of 10,000
    assert (first.target_months, first.target, first.answered) == (4, D("40000.00"), False)

    goal = goal_service.create_goal(session, owner, {"name": "Emergency fund", "target": "40000.00",
                                                     "account_id": books.bank, "kind": "emergency"}, today=TODAY)
    goal_service.add_money(session, owner, goal.id, {"amount": "12000.00"}, today=TODAY)
    second = safety_service.advice(session, owner, today=TODAY)
    assert (second.source, second.money, second.cover_months, second.goal_id) == ("goal", D("12000.00"), D("1.2"), goal.id)
    # 28,000 short, reached in 12 months
    assert second.per_month == D("2333.34")


def test_the_three_answers_move_the_target(session, owner, books):
    for month in ("06", "07", "08"):
        spend(session, owner, books, "10000.00", f"2026-{month}-05", books.rent)
        earn(session, owner, books, "30000.00", f"2026-{month}-15")
    preferences_service.update_preferences(session, owner, {"safety_work": "self", "safety_dependents": "3+",
                                                             "safety_earners": "1"})
    advice = safety_service.advice(session, owner, today=TODAY)
    assert (advice.answered, advice.target_months) == (True, 9)  # 6 + one source 1 + dependents 2
    with pytest.raises(ValidationException):
        preferences_service.update_preferences(session, owner, {"safety_work": "pirate"})


def test_there_is_only_one_emergency_fund(session, owner, books):
    goal_service.create_goal(session, owner, {"name": "Emergency", "target": "1000.00", "account_id": books.bank,
                                              "kind": "emergency"}, today=TODAY)
    with pytest.raises(BusinessRuleException):
        goal_service.create_goal(session, owner, {"name": "Another", "target": "1000.00", "account_id": books.bank,
                                                  "kind": "emergency"}, today=TODAY)


# --------------------------------------------------------------- GOA-09


def test_a_sinking_fund_follows_its_yearly_bill(session, owner, books):
    bill = recurring_service.create_rule(session, owner, {
        "kind": "standard", "type": "expense", "name": "Car insurance", "account_id": books.bank,
        "category_id": books.insurance, "frequency": "yearly", "amount": "12000.00", "start": "2027-03-15"},
        today=TODAY)
    assert [b.rule_id for b in goal_service.yearly_bills(session, owner, today=TODAY)] == [bill.id]

    fund = goal_service.create_goal(session, owner, {"name": "Car insurance", "target": "1.00", "account_id": books.bank,
                                                     "kind": "sinking", "rule_id": bill.id}, today=TODAY)
    assert (fund.target, fund.target_date, fund.rule_id) == (D("12000.00"), date(2027, 3, 15), bill.id)
    # September to March: 7 months
    assert (fund.per_month, fund.month_need, fund.month_done) == (D("1714.29"), D("1714.29"), False)
    assert goal_service.yearly_bills(session, owner, today=TODAY) == []  # followed now


def test_this_months_part_is_ticked_off_not_shrunk(session, owner, books):
    fund = goal_service.create_goal(session, owner, {"name": "Tuition", "target": "6000.00", "target_date": "2026-11-30",
                                                     "account_id": books.bank, "kind": "sinking"}, today=TODAY)
    assert fund.month_need == D("2000.00")
    after = goal_service.add_money(session, owner, fund.id, {"amount": "2000.00"}, today=TODAY)
    assert (after.month_need, after.month_added, after.month_done) == (D("2000.00"), D("2000.00"), True)


def test_a_repeating_fund_rolls_on_a_year(session, owner, books):
    fund = goal_service.create_goal(session, owner, {"name": "Christmas", "target": "10000.00",
                                                     "target_date": "2025-12-20", "account_id": books.bank,
                                                     "kind": "sinking", "repeats_yearly": True}, today=TODAY)
    assert fund.target_date == date(2026, 12, 20) and not fund.overdue


def test_only_a_sinking_fund_repeats_or_follows_a_bill(session, owner, books):
    goal = goal_service.create_goal(session, owner, {"name": "Laptop", "target": "50000.00", "account_id": books.bank,
                                                     "repeats_yearly": True, "rule_id": 999}, today=TODAY)
    assert (goal.kind, goal.repeats_yearly, goal.rule_id) == ("saving", False, None)


# --------------------------------------------------------------- GOA-12


@pytest.fixture
def funds(session, owner, books):
    emergency = goal_service.create_goal(session, owner, {
        "name": "Emergency", "target": "30000.00", "target_date": "2027-02-28", "account_id": books.bank,
        "kind": "emergency"}, today=TODAY)
    laptop = goal_service.create_goal(session, owner, {
        "name": "Laptop", "target": "12000.00", "target_date": "2026-11-30", "account_id": books.bank}, today=TODAY)
    return emergency, laptop


def test_income_over_the_amount_offers_a_split(session, owner, books, funds):
    emergency, laptop = funds
    earn(session, owner, books, "25000.00", "2026-09-27")
    offer = goal_service.payday(session, owner, today=TODAY)
    assert (offer.amount, offer.name) == (D("25000.00"), "Acme")
    # the emergency fund first: 30,000 over Sep-Feb = 5,000 this month; then the laptop, 4,000
    assert [(s.goal_id, s.amount) for s in offer.suggestions] == [(emergency.id, D("5000.00")), (laptop.id, D("4000.00"))]
    assert offer.total == D("9000.00")


def test_small_income_cashback_and_old_income_never_ask(session, owner, books, funds):
    earn(session, owner, books, "4999.99", "2026-09-27")
    earn(session, owner, books, "9000.00", "2026-09-10")  # more than a week ago
    transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": "20000.00", "account_id": books.wallet, "category_id": books.fun,
        "txn_date": "2026-09-27", "cashback": {"amount": "6000.00", "category_id": books.cashback}})
    assert goal_service.payday(session, owner, today=TODAY) is None


def test_the_amount_is_the_users_and_zero_turns_it_off(session, owner, books, funds):
    earn(session, owner, books, "3000.00", "2026-09-27")
    preferences_service.update_preferences(session, owner, {"payday_prompt_min": 2000})
    assert goal_service.payday(session, owner, today=TODAY) is not None
    preferences_service.update_preferences(session, owner, {"payday_prompt_min": 0})
    assert goal_service.payday(session, owner, today=TODAY) is None


def test_setting_aside_adds_to_each_goal_and_answers_the_income(session, owner, books, funds):
    emergency, laptop = funds
    income = earn(session, owner, books, "25000.00", "2026-09-27")
    goal_service.set_aside_payday(session, owner, income.id, {emergency.id: D("5000.00"), laptop.id: D("4000.00")},
                                  today=TODAY)
    assert goal_service.get_goal(session, owner, emergency.id, today=TODAY).saved == D("5000.00")
    assert goal_service.get_goal(session, owner, laptop.id, today=TODAY).saved == D("4000.00")
    assert goal_service.payday(session, owner, today=TODAY) is None


def test_a_refused_part_leaves_nothing_half_done(session, owner, books, funds):
    emergency, laptop = funds
    income = earn(session, owner, books, "25000.00", "2026-09-27")
    with pytest.raises(BusinessRuleException):
        goal_service.set_aside_payday(session, owner, income.id,
                                      {emergency.id: D("5000.00"), laptop.id: D("999999.00")}, today=TODAY)
    session.rollback()
    assert goal_service.get_goal(session, owner, emergency.id, today=TODAY).saved == D("0.00")
    assert goal_service.payday(session, owner, today=TODAY) is not None


def test_not_now_is_final_and_survives_an_edit(session, owner, books, funds):
    income = earn(session, owner, books, "25000.00", "2026-09-27")
    goal_service.dismiss_payday(session, owner, income.id)
    assert goal_service.payday(session, owner, today=TODAY) is None
    transaction_service.update_transaction(session, owner, income.id, {
        "type": "income", "amount": "26000.00", "account_id": books.bank, "category_id": books.salary,
        "txn_date": "2026-09-27"})
    assert TransactionRepository(session, owner).get(income.id).data["set_aside_prompted"] is True
    assert goal_service.payday(session, owner, today=TODAY) is None


# ------------------------------------------------------------------ the API


def test_the_new_routes(api):
    assert api.register().status_code == 201
    bank = api.post("/accounts", {"name": "BDO", "type": "savings", "opening_balance": "50000.00"}).json()["id"]
    salary = api.post("/categories", {"name": "Salary", "kind": "income"}).json()["id"]
    rent = api.post("/categories", {"name": "Rent"}).json()
    assert rent["essential"] is True
    goal = api.post("/goals", {"name": "Emergency", "target": "30000.00", "target_date": "2030-01-31",
                               "account_id": bank, "kind": "emergency"}).json()
    assert goal["kind"] == "emergency"

    advice = api.get("/goals/emergency")
    assert advice.status_code == 200 and advice.json()["source"] == "goal"
    assert api.get("/goals/yearly-bills").json() == []
    assert api.get("/goals/payday").json() is None

    income = api.post("/transactions", {"type": "income", "amount": "20000.00", "account_id": bank,
                                        "category_id": salary}).json()["transactions"][0]
    offer = api.get("/goals/payday").json()
    assert offer["transaction_id"] == income["id"]
    done = api.post(f"/goals/payday/{income['id']}", {"amounts": {str(goal["id"]): offer["suggestions"][0]["amount"]}})
    assert done.status_code == 204
    assert api.get("/goals/payday").json() is None
