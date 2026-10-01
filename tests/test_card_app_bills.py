"""
ACC-35 / ACC-36 - a card's bills typed from its own app, and net worth.

What must hold: cash on hand subtracts only what a card with bills has due
now; a payment settles bills oldest first by itself; an overdue bill adds to
the one coming up; the reminder follows the bills; an ordinary edit keeps
them; and net worth counts every debt in full.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessRuleException, ValidationException
from app.services import account_service, category_service, projection_service, recurring_service, transaction_service

TODAY = date(2026, 9, 15)
BILLS = [
    {"due": "2026-10-15", "amount": "7754.49"},
    {"due": "2026-11-15", "amount": "4120.80"},
    {"due": "2026-12-15", "amount": "2384.78"},
    {"due": "2027-01-15", "amount": "1641.90"},
]


def setup(session, owner):
    wallet = account_service.create_account(session, owner, {"name": "Seabank", "type": "debit", "opening_balance": "20000.00"})
    card = account_service.create_account(session, owner, {
        "name": "Spaylater", "type": "credit", "opening_balance": "-16149.23",
        "statement_closing_day": 15, "payment_due_day": 5,
    })
    account_service.set_bills(session, owner, card.id, BILLS, today=TODAY)
    return wallet, card


def views(session, owner, today):
    listed = account_service.list_accounts(session, owner, postings=transaction_service.postings(session, owner), today=today)
    return listed, {v.name: v for v in listed}


def pay(session, owner, wallet, card, amount, on):
    transaction_service.create_transaction(session, owner, {
        "type": "transfer", "amount": amount, "account_id": wallet.id, "counter_account_id": card.id,
        "txn_date": on.isoformat()}, today=on)


def test_cash_on_hand_counts_the_bill_due_now_not_the_whole_debt(session, owner):
    setup(session, owner)
    listed, by_name = views(session, owner, TODAY)
    credit = by_name["Spaylater"].credit
    assert credit.due_now == Decimal("7754.49")
    assert credit.bills_left == Decimal("15901.97")
    assert credit.payment_due == date(2026, 10, 15) and credit.amount_due == Decimal("7754.49")
    assert by_name["Spaylater"].balance == Decimal("-16149.23")  # the balance itself is untouched
    assert account_service.cash_on_hand(listed).total == Decimal("12245.51")  # 20,000 - 7,754.49


def test_net_worth_counts_every_debt_in_full(session, owner):
    setup(session, owner)
    listed, _ = views(session, owner, TODAY)
    worth = account_service.net_worth(listed)
    assert (worth.assets, worth.liabilities, worth.total) == (Decimal("20000.00"), Decimal("16149.23"), Decimal("3850.77"))


def test_an_account_switched_out_of_net_worth_is_left_out_of_it_only(session, owner):
    """ACC-36 - its own switch, on by default; cash on hand does not read it."""
    setup(session, owner)
    fund = account_service.create_account(session, owner, {"name": "MP2", "type": "savings", "opening_balance": "5000.00"})
    listed, by_name = views(session, owner, TODAY)
    assert by_name["MP2"].counts_in_net_worth is True
    assert account_service.net_worth(listed).total == Decimal("8850.77")

    account_service.update_account(session, owner, fund.id, {"name": "MP2", "type": "savings", "counts_in_net_worth": False})
    listed, by_name = views(session, owner, TODAY)
    assert account_service.net_worth(listed).total == Decimal("3850.77")
    assert account_service.cash_on_hand(listed).total == Decimal("17245.51")  # MP2 still counts in cash on hand

    account_service.update_account(session, owner, fund.id, {"name": "MP2 fund", "type": "savings"})
    assert views(session, owner, TODAY)[1]["MP2 fund"].counts_in_net_worth is False  # an edit that does not mention it keeps it


def test_an_installment_on_the_card_is_added_to_the_bills_it_lands_on(session, owner):
    """The bills are not decoration: a plan added on the card moves them, on its own statements' due dates."""
    _, card = setup(session, owner)
    gadgets = category_service.create_category(session, owner, {"name": "Gadgets"})
    recurring_service.create_rule(session, owner, {
        "kind": "installment", "type": "expense", "name": "Phone", "account_id": card.id, "category_id": gadgets.id,
        "frequency": "monthly", "start": "2026-10-05", "price": "12000.00", "payments": 6}, today=TODAY)

    _, by_name = views(session, owner, TODAY)
    credit = by_name["Spaylater"].credit
    assert credit.bills_left == Decimal("27901.97")  # 15,901.97 typed + 12,000.00 of the plan
    assert sum((b.from_plans for b in credit.bills), Decimal("0")) == Decimal("12000.00")
    # A payment dated 5 October is billed in October (fixed 2026-09-16, user): it
    # joins the first bill falling due on or after it, not the statement it would
    # have been "bought" in, which falls due a month later.
    october = next(b for b in credit.bills if b.due == date(2026, 10, 15))
    assert (october.from_plans, october.typed) == (Decimal("2000.00"), Decimal("7754.49"))
    assert credit.due_now == Decimal("9754.49")  # October's bill, the plan payment included
    # Past the last typed bill the plan keeps that bill's day of the month.
    assert [b.due for b in credit.bills][-2:] == [date(2027, 2, 15), date(2027, 3, 15)]

    # Editing starts from everything unpaid (2026-09-17): the saved list then holds the plan's
    # payments, which are not added a second time, so the totals stay the same.
    retyped = [{"due": b.due.isoformat(), "amount": str(b.left)} for b in credit.bills if b.left > 0]
    account_service.set_bills(session, owner, card.id, retyped, today=TODAY)
    assert views(session, owner, TODAY)[1]["Spaylater"].credit.bills_left == Decimal("27901.97")


def test_the_first_payment_lands_on_the_bill_of_its_own_month(session, owner):
    """
    The reported case (2026-09-16): a plan whose first payment is 15 October,
    on a card whose bills fall due on the 15th, was showing up on the 15
    NOVEMBER bill - the statement route treated the payment as a purchase.
    """
    card = account_service.create_account(session, owner, {
        "name": "SPayLater", "type": "credit", "statement_closing_day": 15, "payment_due_day": 15,
    })
    gadgets = category_service.create_category(session, owner, {"name": "Gadgets"})
    account_service.set_bills(session, owner, card.id, [{"due": "2026-10-15", "amount": "3000.00"},
                                                        {"due": "2026-11-15", "amount": "3000.00"}], today=TODAY)
    recurring_service.create_rule(session, owner, {
        "kind": "installment", "type": "expense", "name": "iPhone", "account_id": card.id, "category_id": gadgets.id,
        "frequency": "monthly", "start": "2026-10-15", "price": "12000.00", "payments": 6}, today=TODAY)

    credit = views(session, owner, TODAY)[1]["SPayLater"].credit
    by_due = {b.due: b for b in credit.bills}
    assert by_due[date(2026, 10, 15)].from_plans == Decimal("2000.00")
    assert by_due[date(2026, 10, 15)].amount == Decimal("5000.00")  # 3,000 typed + the first payment
    assert by_due[date(2026, 11, 15)].amount == Decimal("5000.00")
    assert credit.due_now == Decimal("5000.00")


def test_an_ordinary_charge_still_takes_the_statement_route(session, owner):
    """A purchase is billed with the cycle it falls in, which falls due the month after - unchanged."""
    card = account_service.create_account(session, owner, {
        "name": "SPayLater", "type": "credit", "statement_closing_day": 15, "payment_due_day": 15,
    })
    fun = category_service.create_category(session, owner, {"name": "Fun"})
    account_service.set_bills(session, owner, card.id, [{"due": "2026-10-15", "amount": "3000.00"},
                                                        {"due": "2026-11-15", "amount": "3000.00"}], today=TODAY)
    recurring_service.create_rule(session, owner, {
        "kind": "subscription", "type": "expense", "name": "Netflix", "account_id": card.id, "category_id": fun.id,
        "frequency": "monthly", "start": "2026-10-15", "amount": "549.00", "reminder_days": 3}, today=TODAY)

    credit = views(session, owner, TODAY)[1]["SPayLater"].credit
    by_due = {b.due: b for b in credit.bills}
    assert by_due[date(2026, 10, 15)].from_plans == Decimal("0.00")  # charged 15 Oct, billed next cycle
    assert by_due[date(2026, 11, 15)].from_plans == Decimal("549.00")


def test_a_subscription_on_the_card_counts_only_as_far_as_the_typed_bills(session, owner):
    _, card = setup(session, owner)
    fun = category_service.create_category(session, owner, {"name": "Fun"})
    recurring_service.create_rule(session, owner, {
        "kind": "subscription", "type": "expense", "name": "Netflix", "account_id": card.id, "category_id": fun.id,
        "frequency": "monthly", "start": "2026-09-20", "amount": "549.00", "reminder_days": 3}, today=TODAY)
    credit = views(session, owner, TODAY)[1]["Spaylater"].credit
    assert max(b.due for b in credit.bills) == date(2027, 1, 15)  # no year of Netflix beyond the last typed bill
    assert all(b.from_plans in (Decimal("0.00"), Decimal("549.00")) for b in credit.bills)


def test_months_ahead_takes_each_later_bill_in_the_month_it_is_due(session, owner):
    """
    ACC-35 in the projection: cash on hand holds the October bill; each later one
    is taken on its own due date (changed 2026-09-19, user: November's bill showed
    in October, when it was taken the day after the bill before it).
    """
    setup(session, owner)
    months = projection_service.project(session, owner, today=TODAY, months=6).months  # no budget: calendar months
    assert [m.bills for m in months] == [
        Decimal("0.00"), Decimal("0.00"), Decimal("4120.80"), Decimal("2384.78"), Decimal("1641.90"), Decimal("0.00")]
    assert months[0].opening == Decimal("12245.51")
    assert months[-1].closing == Decimal("4098.03")  # 20,000 - every bill: 15,901.97
    november = next(i for i in months[2].items if i.kind == "bill")
    assert (november.on, november.amount) == (date(2026, 11, 15), Decimal("4120.80"))
    # What Home will hold back at each month's end for a bill not taken yet: the
    # October bill is in today's cash on hand already, so September holds nothing more.
    assert [m.bills_held for m in months] == [
        Decimal("0.00"), Decimal("4120.80"), Decimal("2384.78"), Decimal("1641.90"), Decimal("0.00"), Decimal("0.00")]


def test_months_ahead_counts_a_plan_on_a_billed_card_once(session, owner):
    _, card = setup(session, owner)
    gadgets = category_service.create_category(session, owner, {"name": "Gadgets"})
    recurring_service.create_rule(session, owner, {
        "kind": "installment", "type": "expense", "name": "Phone", "account_id": card.id, "category_id": gadgets.id,
        "frequency": "monthly", "start": "2026-10-05", "price": "12000.00", "payments": 6}, today=TODAY)
    months = projection_service.project(session, owner, today=TODAY, months=12).months
    assert months[-1].closing == Decimal("-7901.97")  # 20,000 - 15,901.97 typed - 12,000.00 of the plan, once
    assert not any(i.kind == "installment" for m in months for i in m.items)  # only as part of the bills
    # 10,000, not 12,000: October's payment is inside the bill cash on hand already holds.
    assert sum((m.committed for m in months), Decimal("0")) == Decimal("10000.00")
    assert sum((m.bills for m in months), Decimal("0")) == Decimal("8147.48")  # the typed bills after October's


def test_a_payment_settles_bills_oldest_first(session, owner):
    wallet, card = setup(session, owner)
    pay(session, owner, wallet, card, "8000.00", date(2026, 9, 20))
    listed, by_name = views(session, owner, date(2026, 9, 21))
    bills = by_name["Spaylater"].credit.bills
    assert (bills[0].left, bills[1].paid, bills[1].left) == (Decimal("0.00"), Decimal("245.51"), Decimal("3875.29"))
    assert by_name["Spaylater"].credit.due_now == Decimal("3875.29")
    assert by_name["Spaylater"].credit.payment_due == date(2026, 11, 15)
    assert account_service.cash_on_hand(listed).total == Decimal("8124.71")  # 12,000 - 3,875.29


def test_an_overdue_bill_adds_to_the_one_coming_up(session, owner):
    setup(session, owner)
    _, by_name = views(session, owner, date(2026, 10, 16))
    credit = by_name["Spaylater"].credit
    assert credit.bills[0].overdue is True
    assert credit.due_now == Decimal("11875.29")  # 7,754.49 overdue + 4,120.80 due 15 Nov
    assert credit.payment_due == date(2026, 10, 15)


def test_only_payments_after_the_list_was_saved_count(session, owner):
    wallet, card = setup(session, owner)
    pay(session, owner, wallet, card, "500.00", date(2026, 9, 1))  # before the list: already off the app's Unpaid tab
    _, by_name = views(session, owner, TODAY)
    assert by_name["Spaylater"].credit.due_now == Decimal("7754.49")


def test_an_ordinary_edit_keeps_the_bills_and_an_empty_list_removes_them(session, owner):
    _, card = setup(session, owner)
    account_service.update_account(session, owner, card.id, {
        "name": "SPayLater", "type": "credit", "statement_closing_day": 15, "payment_due_day": 5})
    _, by_name = views(session, owner, TODAY)
    assert by_name["SPayLater"].credit.due_now == Decimal("7754.49")
    account_service.set_bills(session, owner, card.id, [], today=TODAY)
    listed, by_name = views(session, owner, TODAY)
    assert by_name["SPayLater"].credit.due_now is None
    assert account_service.cash_on_hand(listed).total == Decimal("3850.77")  # the whole balance again


def test_bills_are_checked(session, owner):
    wallet, card = setup(session, owner)
    with pytest.raises(BusinessRuleException):
        account_service.set_bills(session, owner, wallet.id, BILLS, today=TODAY)
    with pytest.raises(ValidationException):
        account_service.set_bills(session, owner, card.id, [{"due": "2026-10-15", "amount": "0"}], today=TODAY)
    with pytest.raises(ValidationException):
        account_service.set_bills(session, owner, card.id, [BILLS[0], BILLS[0]], today=TODAY)


def test_bills_and_net_worth_through_the_api(api):
    assert api.register().status_code == 201
    q = "?today=2026-09-15"
    api.post("/accounts" + q, {"name": "Seabank", "type": "debit", "opening_balance": "20000.00"})
    card = api.post("/accounts" + q, {"name": "Spaylater", "type": "credit", "opening_balance": "-16149.23",
                                      "statement_closing_day": 15, "payment_due_day": 5}).json()["id"]
    saved = api.post(f"/accounts/{card}/bills{q}", {"bills": BILLS})
    assert saved.status_code == 200, saved.text
    assert saved.json()["credit"]["due_now"] == "7754.49"
    listed = api.get("/accounts" + q).json()
    assert listed["cash_on_hand"]["total"] == "12245.51"
    assert listed["net_worth"] == {"total": "3850.77", "assets": "20000.00", "liabilities": "16149.23"}


def test_months_ahead_lists_the_bill_cash_on_hand_already_holds(session, owner):
    """
    Reported 2026-09-16: the bill due next appeared nowhere on Months ahead -
    it is inside today's cash on hand, so it was never listed. It is now shown
    in the month it falls due, with no effect, and the figures do not move.
    """
    setup(session, owner)
    months = projection_service.project(session, owner, today=TODAY, months=6).months

    october = months[1]
    shown = [i for i in october.items if i.kind == "bill_now"]
    assert [(i.on, i.amount, i.effect) for i in shown] == [(date(2026, 10, 15), Decimal("7754.49"), Decimal("0.00"))]
    assert october.bills_set_aside == Decimal("7754.49")
    # Not taken again, and November's bill waits for November (2026-09-19); every
    # figure is what it was before the bill was listed.
    assert october.bills == Decimal("0.00")
    assert months[0].opening == Decimal("12245.51")  # 20,000 less the bill due now
    assert months[-1].closing == Decimal("4098.03")  # 20,000 less every bill, once


# ------------------------------------------------------------------ purchases recorded after the list (2026-09-17)


def billed_card(session, owner, *, bills=True):
    """A card closing on the 15th and due on the 15th, with two typed bills saved on TODAY."""
    card = account_service.create_account(session, owner, {
        "name": "Maribank", "type": "credit", "statement_closing_day": 15, "payment_due_day": 15,
    })
    food = category_service.create_category(session, owner, {"name": "Food"})
    if bills:
        account_service.set_bills(session, owner, card.id, [{"due": "2026-10-15", "amount": "3000.00"},
                                                            {"due": "2026-11-15", "amount": "1000.00"}], today=TODAY)
    return card, food


def buy(session, owner, card, food, amount, on, **extra):
    return transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": amount, "account_id": card.id, "category_id": food.id,
        "txn_date": on.isoformat(), **extra}, today=on)


def bills_of(session, owner, today=TODAY):
    return {b.due: b for b in views(session, owner, today)[1]["Maribank"].credit.bills}


def test_a_purchase_recorded_after_the_list_joins_the_bill_of_its_statement(session, owner):
    """Reported 2026-09-17: a purchase added after the bills were typed was on no bill."""
    card, food = billed_card(session, owner)
    buy(session, owner, card, food, "282.00", TODAY)  # closes 15 Sep -> due 15 Oct
    buy(session, owner, card, food, "164.00", date(2026, 9, 17))  # closes 15 Oct -> due 15 Nov
    bills = bills_of(session, owner, date(2026, 9, 17))
    october, november = bills[date(2026, 10, 15)], bills[date(2026, 11, 15)]
    assert (october.typed, october.from_purchases, october.amount) == (
        Decimal("3000.00"), Decimal("282.00"), Decimal("3282.00"))
    assert (november.from_purchases, november.amount, november.from_plans) == (
        Decimal("164.00"), Decimal("1164.00"), Decimal("0.00"))


def test_a_statement_past_the_typed_bills_gets_its_own_bill(session, owner):
    card, food = billed_card(session, owner)
    buy(session, owner, card, food, "500.00", date(2026, 11, 20))  # closes 15 Dec -> due 15 Jan
    bill = bills_of(session, owner, date(2026, 11, 20))[date(2027, 1, 15)]
    assert (bill.typed, bill.from_purchases, bill.left) == (Decimal("0.00"), Decimal("500.00"), Decimal("500.00"))


def test_a_purchase_the_cards_app_already_had_is_not_added_again(session, owner):
    card, food = billed_card(session, owner, bills=False)
    buy(session, owner, card, food, "807.50", TODAY)  # recorded BEFORE the list is typed
    account_service.set_bills(session, owner, card.id, [{"due": "2026-10-15", "amount": "3000.00"}], today=TODAY)
    buy(session, owner, card, food, "99.00", date(2026, 9, 10))  # recorded later, but dated before the list
    bill = bills_of(session, owner)[date(2026, 10, 15)]
    assert (bill.from_purchases, bill.amount) == (Decimal("0.00"), Decimal("3000.00"))


def test_a_purchase_the_bank_posted_late_joins_the_next_bill(session, owner):
    """ACC-26: the posted-on day decides the statement, as the user's Maribank purchase on its closing day."""
    card, food = billed_card(session, owner)
    late = buy(session, owner, card, food, "807.50", TODAY)
    transaction_service.set_card_posted_on(session, owner, late.transactions[0].id, date(2026, 9, 16))
    session.commit()
    bills = bills_of(session, owner, date(2026, 9, 17))
    assert bills[date(2026, 10, 15)].from_purchases == Decimal("0.00")
    assert bills[date(2026, 11, 15)].from_purchases == Decimal("807.50")


def test_a_list_saved_before_the_moment_was_kept_counts_purchases_from_its_day(session, owner):
    from app.db.repositories.account_repository import AccountRepository

    card, food = billed_card(session, owner)
    repo = AccountRepository(session, owner)
    record = repo.get(card.id)
    repo.update(card.id, {k: v for k, v in record.data.items() if k not in ("bills_saved_at", "bills_cover_transactions", "bills_cover_rules")})
    session.commit()
    buy(session, owner, card, food, "180.00", TODAY)
    assert bills_of(session, owner)[date(2026, 10, 15)].from_purchases == Decimal("180.00")


def test_payments_settle_the_typed_part_then_the_purchases(session, owner):
    card, food = billed_card(session, owner)
    wallet = account_service.create_account(session, owner, {"name": "GCash", "type": "debit", "opening_balance": "9000.00"})
    buy(session, owner, card, food, "500.00", TODAY)
    pay(session, owner, wallet, card, "3200.00", date(2026, 9, 16))
    october = bills_of(session, owner, date(2026, 9, 16))[date(2026, 10, 15)]
    assert (october.typed_left, october.purchases_left, october.left) == (
        Decimal("0.00"), Decimal("300.00"), Decimal("300.00"))


def test_months_ahead_takes_new_purchases_with_the_bill_as_money_already_spent(session, owner):
    card, food = billed_card(session, owner)
    buy(session, owner, card, food, "164.00", date(2026, 9, 17))  # on the 15 Nov bill
    months = projection_service.project(session, owner, today=date(2026, 9, 17), months=3).months
    november = [i for m in months for i in m.items if i.name.startswith("Maribank bill due 15 Nov")]
    assert [(i.kind, i.amount) for i in november] == [("bill", Decimal("1164.00"))]


def test_a_plan_the_cards_app_already_counted_is_not_added_again(session, owner):
    """Reported 2026-09-17: SPayLater's typed 8,280.76 showed as 8,296.09 - an older installment's 15.33 twice."""
    card, food = billed_card(session, owner, bills=False)
    recurring_service.create_rule(session, owner, {
        "kind": "installment", "type": "expense", "name": "Aerox", "account_id": card.id, "category_id": food.id,
        "frequency": "monthly", "start": "2026-10-15", "price": "46.00", "payments": 3}, today=TODAY)
    account_service.set_bills(session, owner, card.id, [{"due": "2026-10-15", "amount": "8280.76"}], today=TODAY)
    october = bills_of(session, owner)[date(2026, 10, 15)]
    assert (october.from_plans, october.amount) == (Decimal("0.00"), Decimal("8280.76"))
    assert max(bills_of(session, owner)) == date(2026, 10, 15)  # its later payments add no bill lines either

    # A plan created AFTER the list is still added, as before.
    recurring_service.create_rule(session, owner, {
        "kind": "installment", "type": "expense", "name": "Phone", "account_id": card.id, "category_id": food.id,
        "frequency": "monthly", "start": "2026-10-15", "price": "300.00", "payments": 3}, today=TODAY)
    assert bills_of(session, owner)[date(2026, 10, 15)].from_plans == Decimal("100.00")


# ------------------------------------------------------------------ what the bills hold, and what they do not (2026-09-19)


def test_what_the_card_owes_beyond_its_bills_is_shown(session, owner):
    """
    Reported 2026-09-19: the Bills section did not add up to what the card owes.
    The balance is 16,149.23 and the typed bills 15,901.97 - 247.26 is on no bill.
    """
    _, card = setup(session, owner)
    credit = views(session, owner, TODAY)[1]["Spaylater"].credit
    assert credit.not_on_bill == Decimal("247.26")
    assert credit.bills_left + credit.not_on_bill - credit.bills_not_charged == credit.owed_with_plans

    # A plan and a subscription on the card move the bills, not what is missing from them.
    gadgets = category_service.create_category(session, owner, {"name": "Gadgets"})
    recurring_service.create_rule(session, owner, {
        "kind": "installment", "type": "expense", "name": "Phone", "account_id": card.id, "category_id": gadgets.id,
        "frequency": "monthly", "start": "2026-10-05", "price": "12000.00", "payments": 6}, today=TODAY)
    recurring_service.create_rule(session, owner, {
        "kind": "subscription", "type": "expense", "name": "Netflix", "account_id": card.id, "category_id": gadgets.id,
        "frequency": "monthly", "start": "2026-09-20", "amount": "549.00", "reminder_days": 3}, today=TODAY)
    credit = views(session, owner, TODAY)[1]["Spaylater"].credit
    assert credit.bills_not_charged > Decimal("0.00")  # Netflix: on the bills, not charged yet
    assert credit.not_on_bill == Decimal("247.26")


def test_a_card_without_bills_has_no_figure_for_it(session, owner):
    billed_card(session, owner, bills=False)
    assert views(session, owner, TODAY)[1]["Maribank"].credit.not_on_bill is None


def test_a_payment_made_before_the_list_was_typed_that_day_is_not_applied_again(session, owner):
    """Found 2026-09-19: a payment on the day of the list already took its bill off the card app's Unpaid tab."""
    card, _ = billed_card(session, owner, bills=False)
    wallet = account_service.create_account(session, owner, {"name": "GCash", "type": "debit", "opening_balance": "9000.00"})
    pay(session, owner, wallet, card, "500.00", TODAY)
    account_service.set_bills(session, owner, card.id, [{"due": "2026-10-15", "amount": "3000.00"}], today=TODAY)
    assert bills_of(session, owner)[date(2026, 10, 15)].left == Decimal("3000.00")
    pay(session, owner, wallet, card, "200.00", TODAY)  # made after the list was typed: it does count
    assert bills_of(session, owner)[date(2026, 10, 15)].left == Decimal("2800.00")


def test_a_bill_lists_what_it_is_made_of(session, owner):
    """Asked 2026-09-19: tap a bill to see the installments and purchases it holds, and what paid it."""
    card, food = billed_card(session, owner, bills=False)
    recurring_service.create_rule(session, owner, {
        "kind": "installment", "type": "expense", "name": "Aerox", "account_id": card.id, "category_id": food.id,
        "frequency": "monthly", "start": "2026-10-15", "price": "46.00", "payments": 3}, today=TODAY)
    account_service.set_bills(session, owner, card.id, [{"due": "2026-10-15", "amount": "3000.00"},
                                                        {"due": "2026-11-15", "amount": "1000.00"}], today=TODAY)
    recurring_service.create_rule(session, owner, {
        "kind": "installment", "type": "expense", "name": "Hoodie", "account_id": card.id, "category_id": food.id,
        "frequency": "monthly", "start": "2026-10-15", "price": "969.00", "payments": 3}, today=TODAY)
    buy(session, owner, card, food, "282.00", TODAY, merchant="Shopee")
    wallet = account_service.create_account(session, owner, {"name": "GCash", "type": "debit", "opening_balance": "9000.00"})
    pay(session, owner, wallet, card, "3500.00", date(2026, 9, 16))

    october = bills_of(session, owner, date(2026, 9, 16))[date(2026, 10, 15)]
    lines = [(line.kind, line.name, line.amount) for line in october.lines]
    assert lines == [
        ("typed", None, Decimal("3000.00")),
        ("purchase", "Shopee", Decimal("282.00")),
        ("plan", "Hoodie", Decimal("323.00")),
        ("inside_typed", "Aerox", Decimal("15.33")),  # already in the 3,000 - shown, not added
        ("payment", "Payment", Decimal("3500.00")),
    ]
    adds = sum((line.amount for line in october.lines if line.kind in ("typed", "purchase", "plan")), Decimal("0"))
    assert adds == october.amount
    assert sum((line.amount for line in october.lines if line.kind == "payment"), Decimal("0")) == october.paid
    assert next(line for line in october.lines if line.kind == "purchase").transaction_id is not None
    assert next(line for line in october.lines if line.kind == "plan").rule_id is not None


def test_a_payment_split_across_two_bills_shows_on_both(session, owner):
    wallet, card = setup(session, owner)
    pay(session, owner, wallet, card, "8000.00", date(2026, 9, 20))
    bills = views(session, owner, date(2026, 9, 21))[1]["Spaylater"].credit.bills
    paid = [[line.amount for line in b.lines if line.kind == "payment"] for b in bills[:2]]
    assert paid == [[Decimal("7754.49")], [Decimal("245.51")]]


def test_the_card_look_ahead_shows_the_typed_bills(session, owner):
    """D8 (2026-09-19): a card with bills shows those bills on Months ahead, not a statement-cycle guess."""
    setup(session, owner)
    card = next(c for c in projection_service.cards(session, owner, today=TODAY) if c.name == "Spaylater")
    assert card.statements == []
    assert [(b.due, b.left) for b in card.bills] == [
        (date(2026, 10, 15), Decimal("7754.49")), (date(2026, 11, 15), Decimal("4120.80")),
        (date(2026, 12, 15), Decimal("2384.78")), (date(2027, 1, 15), Decimal("1641.90"))]


def send(session, owner, card, to, amount, on):
    return transaction_service.create_transaction(session, owner, {
        "type": "transfer", "amount": amount, "account_id": card.id, "counter_account_id": to.id,
        "txn_date": on.isoformat()}, today=on)


def test_money_sent_from_the_card_joins_the_bill_of_its_statement(session, owner):
    """Reported 2026-10-01: ₱510 sent to Mama Lala from the Maribank card was on no bill."""
    card, _ = billed_card(session, owner)
    mama = account_service.create_account(session, owner, {"name": "Mama Lala", "type": "lent"})
    beyond = views(session, owner, date(2026, 9, 17))[1]["Maribank"].credit.not_on_bill
    send(session, owner, card, mama, "510.00", TODAY)  # closes 15 Sep -> due 15 Oct
    send(session, owner, card, mama, "90.00", date(2026, 9, 17))  # closes 15 Oct -> due 15 Nov
    bills = bills_of(session, owner, date(2026, 9, 17))
    october, november = bills[date(2026, 10, 15)], bills[date(2026, 11, 15)]
    assert (october.from_purchases, october.amount) == (Decimal("510.00"), Decimal("3510.00"))
    assert (november.from_purchases, november.amount) == (Decimal("90.00"), Decimal("1090.00"))
    line = next(x for x in october.lines if x.kind == "purchase")
    assert line.amount == Decimal("510.00")
    credit = views(session, owner, date(2026, 9, 17))[1]["Maribank"].credit
    assert credit.not_on_bill == beyond  # the card owes 600 more and its bills say so: none of it is off a bill


def test_money_sent_into_the_card_is_still_a_payment_not_a_charge(session, owner):
    card, _ = billed_card(session, owner)
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash", "opening_balance": "9000.00"})
    send(session, owner, wallet, card, "1000.00", TODAY)
    october = bills_of(session, owner)[date(2026, 10, 15)]
    assert (october.from_purchases, october.paid, october.left) == (
        Decimal("0.00"), Decimal("1000.00"), Decimal("2000.00"))


def test_money_sent_before_the_list_was_typed_is_not_added_again(session, owner):
    card, _ = billed_card(session, owner, bills=False)
    mama = account_service.create_account(session, owner, {"name": "Mama Lala", "type": "lent"})
    send(session, owner, card, mama, "510.00", TODAY)  # the card's app already shows it
    account_service.set_bills(session, owner, card.id, [{"due": "2026-10-15", "amount": "3000.00"}], today=TODAY)
    bill = bills_of(session, owner)[date(2026, 10, 15)]
    assert (bill.from_purchases, bill.amount) == (Decimal("0.00"), Decimal("3000.00"))
