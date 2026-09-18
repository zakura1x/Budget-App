"""
REC-34 - a purchase on a card or a loan paid in installments (2026-09-18).

What must hold: the purchase BECOMES the plan - it is hidden, never counted
next to its payments - so what the card owes does not move, the budget and
Stats see one payment a month, payments already due post at once, a split
purchase keeps its proportions, a typed bill list that held the purchase holds
the plan, and converting back brings the purchase back exactly as it was.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessRuleException
from app.services import (
    account_service,
    category_service,
    installment_conversion,
    recurring_service,
    stats_service,
    transaction_service,
)

TODAY = date(2026, 9, 18)


@pytest.fixture
def card(session, owner):
    """A card closing on the 15th, due on the 15th of the next month, and a purchase on it."""
    account = account_service.create_account(session, owner, {
        "name": "Metrobank", "type": "credit", "statement_closing_day": 15, "payment_due_day": 15,
    })
    gadgets = category_service.create_category(session, owner, {"name": "Gadgets"})
    return account, gadgets


def buy(session, owner, account, category, amount="12000.00", on=TODAY, **extra):
    return transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": amount, "account_id": account.id, "category_id": category.id,
        "txn_date": on.isoformat(), "merchant": "Abenson", **extra}, today=on).transactions[0]


def view_of(session, owner, account, today=TODAY):
    postings = transaction_service.postings(session, owner)
    return account_service.get_account(session, owner, account.id, postings=postings, today=today)


def payments(session, owner, rule_id):
    return sorted((v for v in transaction_service.views(session, owner) if v.recurring_id == rule_id),
                  key=lambda v: v.txn_date)


def test_the_purchase_becomes_the_plan(session, owner, card):
    account, gadgets = card
    purchase = buy(session, owner, account, gadgets)
    owed_before = view_of(session, owner, account).credit.owed_with_plans

    rule = installment_conversion.convert(session, owner, purchase.id, {"payments": 3}, today=TODAY)
    assert (rule.kind, rule.name, rule.category_id, rule.from_transaction) == ("installment", "Abenson", gadgets.id,
                                                                               purchase.id)
    # Bought 18 Sep: the statement closes 15 Oct and is due 15 Nov - the first payment's bill.
    assert rule.start == date(2026, 11, 15)
    assert rule.installment.per_payment == Decimal("4000.00")
    # Hidden, not deleted: nowhere in the ledger, and nothing posted yet.
    assert purchase.id not in {v.id for v in transaction_service.views(session, owner)}
    assert payments(session, owner, rule.id) == []
    # What the card owes does not move: the plan is owed in full from day one (REC-14).
    assert view_of(session, owner, account).credit.owed_with_plans == owed_before == Decimal("12000.00")


def test_payments_already_due_post_at_once(session, owner, card):
    account, gadgets = card
    purchase = buy(session, owner, account, gadgets, on=date(2026, 6, 10))
    rule = installment_conversion.convert(session, owner, purchase.id, {"payments": 6}, today=TODAY)
    # Bought 10 Jun: first bill 15 Jul, then 15 Aug and 15 Sep - three are due by 18 Sep.
    posted = payments(session, owner, rule.id)
    assert [(p.txn_date, p.amount) for p in posted] == [
        (date(2026, 7, 15), Decimal("2000.00")), (date(2026, 8, 15), Decimal("2000.00")),
        (date(2026, 9, 15), Decimal("2000.00"))]
    assert (rule.installment.paid, rule.installment.payments_left) == (Decimal("6000.00"), 3)  # charges posted


def test_the_budget_and_stats_see_one_payment_a_month(session, owner, card):
    account, gadgets = card
    purchase = buy(session, owner, account, gadgets, on=date(2026, 8, 20))
    installment_conversion.convert(session, owner, purchase.id, {"payments": 3, "start": "2026-09-15"}, today=TODAY)
    september = stats_service.overview(session, owner, span="month", on=TODAY, today=TODAY)
    august = stats_service.overview(session, owner, span="month", on=date(2026, 8, 20), today=TODAY)
    assert september.totals.spent == Decimal("4000.00")
    assert august.totals.spent == Decimal("0.00")  # the purchase no longer counts in its own month


def test_a_split_purchase_keeps_its_proportions(session, owner, card):
    account, gadgets = card
    cases = category_service.create_category(session, owner, {"name": "Accessories"})
    purchase = transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": "10000.00", "account_id": account.id, "txn_date": "2026-08-01",
        "splits": [{"category_id": gadgets.id, "amount": "7000.00"}, {"category_id": cases.id, "amount": "3000.00"}],
    }, today=TODAY).transactions[0]
    rule = installment_conversion.convert(session, owner, purchase.id, {"payments": 3, "start": "2026-08-15"},
                                          today=TODAY)
    posted = payments(session, owner, rule.id)
    assert [[(s.category_id, s.amount) for s in p.splits] for p in posted] == [
        [(gadgets.id, Decimal("2333.33")), (cases.id, Decimal("1000.00"))],
        [(gadgets.id, Decimal("2333.33")), (cases.id, Decimal("1000.00"))],
    ]
    assert rule.category_id == gadgets.id  # the larger part names the plan


def test_converting_back_brings_the_purchase_back_as_it_was(session, owner, card):
    account, gadgets = card
    purchase = buy(session, owner, account, gadgets, on=date(2026, 6, 10), notes="Phone")
    rule = installment_conversion.convert(session, owner, purchase.id, {"payments": 6}, today=TODAY)
    assert len(payments(session, owner, rule.id)) == 3

    back = installment_conversion.revert(session, owner, rule.id, today=TODAY)
    assert (back.id, back.amount, back.notes, back.txn_date) == (purchase.id, Decimal("12000.00"), "Phone",
                                                                 date(2026, 6, 10))
    assert payments(session, owner, rule.id) == []
    assert rule.id not in {r.id for r in recurring_service.list_rules(session, owner, today=TODAY)}
    assert view_of(session, owner, account).balance == Decimal("-12000.00")


def test_cashback_already_received_stays_and_comes_back_linked(session, owner, card):
    account, gadgets = card
    rebates = category_service.create_category(session, owner, {"name": "Cashback", "kind": "income"})
    purchase = buy(session, owner, account, gadgets, cashback={"amount": "120.00", "category_id": rebates.id})
    credit_id = transaction_service.get_transaction(session, owner, purchase.id).cashback_id

    rule = installment_conversion.convert(session, owner, purchase.id, {"payments": 3}, today=TODAY)
    credit = transaction_service.get_transaction(session, owner, credit_id)
    assert (credit.type, credit.amount, credit.cashback_of) == ("income", Decimal("120.00"), None)

    installment_conversion.revert(session, owner, rule.id, today=TODAY)
    assert transaction_service.get_transaction(session, owner, credit_id).cashback_of == purchase.id


def test_only_a_card_or_a_loan_spreads_a_purchase(session, owner, card):
    _, gadgets = card
    wallet = account_service.create_account(session, owner, {"name": "GCash", "type": "debit",
                                                              "opening_balance": "5000.00"})
    purchase = buy(session, owner, wallet, gadgets, amount="1000.00")
    with pytest.raises(BusinessRuleException):
        installment_conversion.convert(session, owner, purchase.id, {"payments": 3}, today=TODAY)


def test_a_loan_starts_a_month_after_the_purchase(session, owner, card):
    _, gadgets = card
    loan = account_service.create_account(session, owner, {"name": "Papa", "type": "borrowed"})
    purchase = buy(session, owner, loan, gadgets, amount="9000.00")
    rule = installment_conversion.convert(session, owner, purchase.id, {"payments": 3}, today=TODAY)
    assert rule.start == date(2026, 10, 18)


def test_a_plan_made_from_a_purchase_the_bills_held_is_held_too(session, owner, card):
    """ACC-35: the card's app already had that money; converting it must not add it again."""
    account, gadgets = card
    purchase = buy(session, owner, account, gadgets, amount="3000.00", on=date(2026, 9, 18))
    account_service.set_bills(session, owner, account.id, [{"due": "2026-11-15", "amount": "3000.00"}], today=TODAY)
    installment_conversion.convert(session, owner, purchase.id, {"payments": 3}, today=TODAY)
    bills = {b.due: b for b in view_of(session, owner, account).credit.bills}
    assert (bills[date(2026, 11, 15)].amount, bills[date(2026, 11, 15)].from_plans) == (Decimal("3000.00"),
                                                                                        Decimal("0.00"))


def test_a_new_purchase_with_a_plan_from_the_add_sheet(session, owner, card):
    account, gadgets = card
    rule = installment_conversion.create_with_plan(session, owner, {
        "type": "expense", "amount": "6000.00", "account_id": account.id, "category_id": gadgets.id,
        "txn_date": TODAY.isoformat(), "merchant": "Lazada"}, {"payments": 2}, today=TODAY)
    assert (rule.name, rule.installment.per_payment, rule.from_transaction is not None) == (
        "Lazada", Decimal("3000.00"), True)
    assert [v for v in transaction_service.views(session, owner) if v.recurring_id is None] == []


def test_bad_terms_leave_no_purchase_behind(session, owner, card):
    account, gadgets = card
    with pytest.raises(Exception):
        installment_conversion.create_with_plan(session, owner, {
            "type": "expense", "amount": "6000.00", "account_id": account.id, "category_id": gadgets.id,
            "txn_date": TODAY.isoformat()}, {"payments": 0}, today=TODAY)
    assert transaction_service.views(session, owner) == []


def test_preview_says_what_is_due_and_whether_the_statement_closed(session, owner, card):
    account, _ = card
    found = installment_conversion.preview(session, owner, account_id=account.id, amount="12000.00",
                                           on=date(2026, 6, 10), payments=6, today=TODAY)
    assert (found.start, found.due_now, found.on_closed_statement) == (date(2026, 7, 15), 3, True)
    assert [a for _, a in found.payments] == [Decimal("2000.00")] * 6


def test_through_the_api(api):
    assert api.register().status_code == 201
    q = "?today=2026-09-18"
    card = api.post("/accounts" + q, {"name": "Metrobank", "type": "credit", "statement_closing_day": 15,
                                      "payment_due_day": 15}).json()["id"]
    gadgets = api.post("/categories", {"name": "Gadgets"}).json()["id"]
    bought = api.post("/transactions" + q, {"type": "expense", "amount": "12000.00", "account_id": card,
                                            "category_id": gadgets, "txn_date": "2026-09-18"}).json()
    purchase = bought["transactions"][0]["id"]

    preview = api.post("/recurring/installments/preview" + q, {"account_id": card, "amount": "12000.00",
                                                              "txn_date": "2026-09-18", "payments": 3})
    assert preview.status_code == 200, preview.text
    assert preview.json()["start"] == "2026-11-15"

    made = api.post(f"/recurring/installments/from/{purchase}" + q, {"payments": 3})
    assert made.status_code == 201, made.text
    rule = made.json()
    assert (rule["from_transaction"], rule["installment"]["per_payment"]) == (purchase, "4000.00")

    back = api.post(f"/recurring/{rule['id']}/revert" + q)
    assert back.status_code == 200, back.text
    assert back.json()["id"] == purchase

    added = api.post("/recurring/installments" + q, {
        "purchase": {"type": "expense", "amount": "6000.00", "account_id": card, "category_id": gadgets,
                     "txn_date": "2026-09-18"},
        "terms": {"payments": 2}})
    assert added.status_code == 201, added.text
