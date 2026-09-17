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

    # Editing the bills starts from the typed part only, so saving again does not count the plan twice.
    retyped = [{"due": b.due.isoformat(), "amount": str(b.typed_left)} for b in credit.bills if b.typed_left > 0]
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


def test_months_ahead_takes_each_later_bill_the_day_after_the_one_before_is_due(session, owner):
    """ACC-35 in the projection: cash on hand holds the October bill; November's enters on 16 Oct, and so on."""
    setup(session, owner)
    months = projection_service.project(session, owner, today=TODAY, months=6).months  # no budget: calendar months
    assert [m.bills for m in months] == [
        Decimal("0.00"), Decimal("4120.80"), Decimal("2384.78"), Decimal("1641.90"), Decimal("0.00"), Decimal("0.00")]
    assert months[0].opening == Decimal("12245.51")
    assert months[-1].closing == Decimal("4098.03")  # 20,000 - every bill: 15,901.97
    november = next(i for i in months[1].items if i.kind == "bill")
    assert (november.on, november.amount) == (date(2026, 10, 16), Decimal("4120.80"))


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
    # Not taken again: October still takes only November's bill (entering 16 Oct),
    # and every figure is what it was before the bill was listed.
    assert october.bills == Decimal("4120.80")
    assert months[0].opening == Decimal("12245.51")  # 20,000 less the bill due now
    assert months[-1].closing == Decimal("4098.03")  # 20,000 less every bill, once
