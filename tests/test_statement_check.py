"""
The statement check (ACC-24..26, FEATURES.md §21) - one number from the bank,
and every explanation of the difference an ordinary transaction.

The guarantees: the difference is derived and every resolution brings it to
exactly 0.00; a lower bank total is never treated as a charge; and a purchase
the bank posted late moves between statements and card cycles while its budget
period stays where it was.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessRuleException, ValidationException
from app.db.models import Account
from app.services import account_service, category_service, statement_service, transaction_service
from app.services.budget_service import budget_service

D = Decimal
CARD = {"name": "BPI Card", "type": "credit", "statement_closing_day": 16, "payment_due_day": 6}
CLOSES = date(2026, 10, 16)
AFTER = date(2026, 10, 17)


@pytest.fixture
def setup(session, owner):
    card = account_service.create_account(session, owner, CARD)
    food = category_service.create_category(session, owner, {"name": "Food"})
    interest = category_service.create_category(session, owner, {"name": "Interest"})

    class S:
        pass

    s = S()
    s.card, s.food, s.interest = card.id, food.id, interest.id
    return s


def buy(session, owner, s, amount, on):
    return transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": amount, "account_id": s.card,
        "category_id": s.food, "txn_date": on}).transactions[0]


def statement_of(session, owner, s, closes=CLOSES, today=AFTER):
    return statement_service.get(session, owner, s.card, closes, today=today)


# ------------------------------------------------------------- the figure


def test_the_bank_total_is_kept_and_the_difference_derived(session, owner, setup):
    buy(session, owner, setup, "18666.67", "2026-10-01")
    before = statement_of(session, owner, setup)
    assert (before.statement.amount, before.statement.difference, before.checked) == (D("18666.67"), None, False)

    after = statement_service.check(session, owner, setup.card, CLOSES, "19066.67", today=AFTER)
    assert (after.statement.bank_total, after.statement.difference) == (D("19066.67"), D("400.00"))
    assert after.suggestions == ["charge", "forgot"]


def test_typing_the_total_again_replaces_it(session, owner, setup):
    buy(session, owner, setup, "100.00", "2026-10-01")
    statement_service.check(session, owner, setup.card, CLOSES, "150.00", today=AFTER)
    again = statement_service.check(session, owner, setup.card, CLOSES, "100.00", today=AFTER)
    assert again.checked is True
    record = account_service.AccountRepository(session, owner).get(setup.card)
    assert len(record.data["statement_checks"]) == 1


@pytest.mark.security
def test_the_bank_total_is_not_readable_in_the_database(session, owner, setup):
    statement_service.check(session, owner, setup.card, CLOSES, "19066.67", today=AFTER)
    for payload in session.execute(select(Account.payload)).scalars().all():
        assert b"19066" not in payload


def test_only_a_closed_statement_of_a_card_can_be_checked(session, owner, setup):
    with pytest.raises(BusinessRuleException):  # has not closed yet
        statement_service.check(session, owner, setup.card, CLOSES, "1.00", today=CLOSES)
    with pytest.raises(ValidationException):  # not this card's closing day
        statement_service.check(session, owner, setup.card, date(2026, 10, 15), "1.00", today=AFTER)
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash"})
    with pytest.raises(BusinessRuleException):
        statement_service.check(session, owner, wallet.id, CLOSES, "1.00", today=AFTER)


def test_an_edit_to_the_card_keeps_its_statement_checks(session, owner, setup):
    statement_service.check(session, owner, setup.card, CLOSES, "10.00", today=AFTER)
    account_service.update_account(session, owner, setup.card, {**CARD, "name": "BPI Gold"})
    assert statement_of(session, owner, setup).statement.bank_total == D("10.00")


# ---------------------------------------------------------- explaining it


def test_a_charge_brings_the_difference_to_zero(session, owner, setup):
    buy(session, owner, setup, "18666.67", "2026-10-01")
    statement_service.check(session, owner, setup.card, CLOSES, "19066.67", today=AFTER)
    result = statement_service.resolve(session, owner, setup.card, CLOSES, {
        "choice": "charge", "amount": "400.00", "category_id": setup.interest, "note": "Finance charge"}, today=AFTER)

    assert (result.statement.difference, result.checked) == (D("0.00"), True)
    charge = [t for t in transaction_service.list_transactions(session, owner).items if t.notes == "Finance charge"]
    assert [(c.txn_date, c.amount, c.splits[0].category_id) for c in charge] == [(CLOSES, D("400.00"), setup.interest)]


def test_a_difference_can_be_split_across_charges(session, owner, setup):
    statement_service.check(session, owner, setup.card, CLOSES, "550.00", today=AFTER)
    part = statement_service.resolve(session, owner, setup.card, CLOSES, {
        "choice": "charge", "amount": "400.00", "category_id": setup.interest}, today=AFTER)
    assert part.statement.difference == D("150.00")
    with pytest.raises(BusinessRuleException):  # more than is left to explain
        statement_service.resolve(session, owner, setup.card, CLOSES, {
            "choice": "charge", "amount": "150.01", "category_id": setup.interest}, today=AFTER)


def test_a_lower_bank_total_is_never_a_charge(session, owner, setup):
    buy(session, owner, setup, "1500.00", "2026-10-01")
    statement_service.check(session, owner, setup.card, CLOSES, "1000.00", today=AFTER)
    with pytest.raises(BusinessRuleException):
        statement_service.resolve(session, owner, setup.card, CLOSES, {
            "choice": "charge", "amount": "500.00", "category_id": setup.interest}, today=AFTER)


def test_nothing_resolves_before_the_bank_total_is_in(session, owner, setup):
    with pytest.raises(BusinessRuleException):
        statement_service.resolve(session, owner, setup.card, CLOSES, {
            "choice": "charge", "amount": "1.00", "category_id": setup.interest}, today=AFTER)


# ------------------------------------------------------- posted on the next


def test_a_late_posting_moves_the_statement_and_not_the_budget(session, owner, setup):
    """ACC-26 - the §21 case: bought on the 15th, posted by the bank after the close."""
    budget_service.create_budget(session, owner, {"period": "monthly", "amount": "30000.00"}, today=date(2026, 10, 1))
    buy(session, owner, setup, "3000.00", "2026-10-02")
    late = buy(session, owner, setup, "1500.00", "2026-10-15")
    statement_service.check(session, owner, setup.card, CLOSES, "3000.00", today=AFTER)

    offered = statement_of(session, owner, setup)
    assert offered.statement.difference == D("-1500.00")
    assert [c.id for c in offered.late_candidates] == [late.id]
    assert offered.suggestions == ["posted_next", "forgot"]

    result = statement_service.resolve(session, owner, setup.card, CLOSES,
                                       {"choice": "posted_next", "transaction_id": late.id}, today=AFTER)
    assert (result.statement.difference, result.checked) == (D("0.00"), True)

    # The October budget still holds it; the card's next statement does too.
    october = budget_service.status(session, owner, today=AFTER)
    assert october.allowance.spent == D("4500.00")
    credit = account_service.get_account(session, owner, setup.card, postings=transaction_service.postings(session, owner),
                                         today=AFTER).credit
    assert credit.limit_spent == D("1500.00")


def test_only_a_purchase_near_the_close_can_move(session, owner, setup):
    early = buy(session, owner, setup, "1500.00", "2026-10-02")
    statement_service.check(session, owner, setup.card, CLOSES, "0.00", today=AFTER)
    with pytest.raises(BusinessRuleException):
        statement_service.resolve(session, owner, setup.card, CLOSES,
                                  {"choice": "posted_next", "transaction_id": early.id}, today=AFTER)


def test_the_posting_window_is_the_cards_own_setting(session, owner, setup):
    """ACC-26, per card since 2026-09-14 - a new card starts at 3 days, and the user can change it."""
    buy(session, owner, setup, "1500.00", "2026-10-12")  # 4 days before the close
    statement_service.check(session, owner, setup.card, CLOSES, "0.00", today=AFTER)
    assert statement_of(session, owner, setup).late_candidates == []  # outside the default 3 days

    account_service.update_account(session, owner, setup.card, {**CARD, "posting_lag_days": 5})
    widened = statement_of(session, owner, setup)
    assert [c.amount for c in widened.late_candidates] == [D("1500.00")]

    account_service.update_account(session, owner, setup.card, {**CARD, "name": "BPI Gold"})
    assert statement_of(session, owner, setup).statement.posting_lag_days == 5  # an edit that doesn't mention it keeps it

    account_service.update_account(session, owner, setup.card, {**CARD, "name": "BPI Gold", "posting_lag_days": 0})
    assert statement_of(session, owner, setup).late_candidates == []


def test_a_posting_window_past_ten_days_is_refused(session, owner, setup):
    with pytest.raises(ValidationException):
        account_service.update_account(session, owner, setup.card, {**CARD, "posting_lag_days": 11})


def test_moving_the_purchase_to_another_day_forgets_the_late_posting(session, owner, setup):
    late = buy(session, owner, setup, "1500.00", "2026-10-15")
    statement_service.check(session, owner, setup.card, CLOSES, "0.00", today=AFTER)
    statement_service.resolve(session, owner, setup.card, CLOSES,
                              {"choice": "posted_next", "transaction_id": late.id}, today=AFTER)
    assert transaction_service.get_transaction(session, owner, late.id).card_posted_on == AFTER

    transaction_service.update_transaction(session, owner, late.id, {
        "type": "expense", "amount": "1500.00", "account_id": setup.card,
        "category_id": setup.food, "txn_date": "2026-10-12"})
    assert transaction_service.get_transaction(session, owner, late.id).card_posted_on is None


# ---------------------------------------------------------------- the API


def test_the_statement_check_through_the_api(api):
    assert api.register().status_code == 201
    card = api.post("/accounts", CARD).json()["id"]
    interest = api.post("/categories", {"name": "Interest"}).json()["id"]
    api.post("/transactions", {"type": "expense", "amount": "18666.67", "account_id": card,
                               "category_id": interest, "txn_date": "2026-10-01"})

    checked = api.post(f"/accounts/{card}/statements/2026-10-16/check?today=2026-10-17", {"bank_total": "19066.67"})
    assert checked.status_code == 200, checked.text
    assert checked.json()["statement"]["difference"] == "400.00"

    resolved = api.post(f"/accounts/{card}/statements/2026-10-16/resolve?today=2026-10-17",
                        {"choice": "charge", "amount": "400.00", "category_id": interest})
    assert resolved.status_code == 200, resolved.text
    assert (resolved.json()["statement"]["difference"], resolved.json()["checked"]) == ("0.00", True)

    bill = api.get("/accounts?today=2026-10-17").json()["accounts"][0]["credit"]["bill"]
    assert (bill["amount"], bill["bank_total"]) == ("19066.67", "19066.67")


def test_a_statement_that_has_not_closed_is_refused_by_the_api(api):
    assert api.register().status_code == 201
    card = api.post("/accounts", CARD).json()["id"]
    response = api.post(f"/accounts/{card}/statements/2026-10-16/check?today=2026-10-16", {"bank_total": "1.00"})
    assert (response.status_code, response.json()["code"]) == (400, "BUSINESS_RULE")
