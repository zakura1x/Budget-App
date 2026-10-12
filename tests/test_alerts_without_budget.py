"""
Account alerts need no budget (Phase 10) - and a statement that does not
match the bank raises one (ACC-24).

Before, card and subscription banners came only inside the budget status, so
someone who tracked a card without a budget never heard its bill was due.
"""

from datetime import date
from decimal import Decimal

from app.services import account_service, category_service, statement_service, transaction_service
from app.services.budget_service import budget_service
from app.services.budget_service.alerts import CardDue, StatementDiffers, account_alerts

D = Decimal
CARD = {"name": "BPI Card", "type": "credit", "statement_closing_day": 16, "payment_due_day": 6}


def a_card(session, owner):
    card = account_service.create_account(session, owner, CARD)
    food = category_service.create_category(session, owner, {"name": "Food"})
    return card.id, food.id


def buy(session, owner, card, food, amount, on):
    transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": amount, "account_id": card, "category_id": food, "txn_date": on})


def kinds(alerts):
    return [(a.kind, a.account_id) for a in alerts]


def test_account_alerts_stand_on_their_own():
    alerts = account_alerts(cards_due=[CardDue(account_id=9, due_in_days=0)], statements_differ=[StatementDiffers(9)])
    assert kinds(alerts) == [("card_due", 9), ("statement_differs", 9)]
    assert alerts[0].message == "A card payment is due today"
    # The screen words it from `when`, never by taking the sentence apart (2026-10-12).
    assert alerts[0].when == "today"
    assert account_alerts(cards_due=[CardDue(account_id=9, due_in_days=3)])[0].when == "in 3 days"


def test_a_card_bill_reminds_without_a_budget(session, owner):
    card, food = a_card(session, owner)
    buy(session, owner, card, food, "12300.00", "2026-09-10")
    today = date(2026, 10, 2)  # the 16 Sep statement is due 6 Oct
    assert budget_service.status(session, owner, today=today) is None
    assert ("card_due", card) in kinds(budget_service.standalone_alerts(session, owner, today=today))


def test_a_statement_that_does_not_match_the_bank_raises_an_alert(session, owner):
    card, food = a_card(session, owner)
    buy(session, owner, card, food, "18666.67", "2026-10-01")
    closes, after = date(2026, 10, 16), date(2026, 10, 17)

    assert ("statement_differs", card) not in kinds(budget_service.standalone_alerts(session, owner, today=after))
    statement_service.check(session, owner, card, closes, "19066.67", today=after)
    assert ("statement_differs", card) in kinds(budget_service.standalone_alerts(session, owner, today=after))

    statement_service.check(session, owner, card, closes, "18666.67", today=after)  # the bank figure was mistyped
    assert ("statement_differs", card) not in kinds(budget_service.standalone_alerts(session, owner, today=after))


def test_with_a_budget_the_same_alerts_come_in_the_status(session, owner):
    card, food = a_card(session, owner)
    budget_service.create_budget(session, owner, {"period": "monthly", "amount": "90000.00"}, today=date(2026, 8, 1))
    buy(session, owner, card, food, "12300.00", "2026-09-10")
    status = budget_service.status(session, owner, today=date(2026, 10, 2))
    assert ("card_due", card) in kinds(status.alerts)


def test_the_api_sends_alerts_when_there_is_no_budget(api):
    assert api.register().status_code == 201
    card = api.post("/accounts", CARD).json()["id"]
    food = api.post("/categories", {"name": "Food"}).json()["id"]
    api.post("/transactions", {"type": "expense", "amount": "12300.00", "account_id": card,
                               "category_id": food, "txn_date": "2026-09-10"})
    body = api.get("/budgets/current?today=2026-10-02").json()
    assert body["status"] is None
    assert [(a["kind"], a["account_id"]) for a in body["alerts"]] == [("card_due", card)]
    assert body["alerts"][0]["when"] is not None
