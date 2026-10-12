"""
Accounts - the first encrypted CRUD, and every number derived from it
(ACC-01..ACC-18).

The things worth proving here are the ones SQL cannot check for us: that a
balance is Decimal-exact, that cash on hand counts exactly the accounts it
says it counts, that a card's available credit subtracts the installment
remainder the bank has already blocked, and that a name never reaches the
database in a readable form.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import (
    BusinessRuleException,
    NotFoundException,
    ValidationException,
)
from app.db.models import Account
from app.db.repositories.account_repository import AccountRepository
from app.services import account_service
from app.services.account_service import Posting

CASH = {"name": "Wallet", "type": "cash", "opening_balance": "1500.00"}
CARD = {
    "name": "BPI Gold",
    "type": "credit",
    "opening_balance": "0",
    "credit_limit": "50000.00",
    "statement_closing_day": 20,
    "payment_due_day": 5,
}


def make(session, cipher, **overrides):
    payload = {**CASH, **overrides}
    return account_service.create_account(session, cipher, payload)


# ------------------------------------------------------------------ the rules


def test_create_round_trips_through_the_ciphertext(session, owner):
    created = make(session, owner)
    fetched = account_service.get_account(session, owner, created.id)
    assert fetched.name == "Wallet"
    assert fetched.balance == Decimal("1500.00")
    assert isinstance(fetched.balance, Decimal)


@pytest.mark.security
def test_the_name_is_not_readable_in_the_database(session, owner):
    """The SSMS test, locally: a plain SELECT shows nothing about the account."""
    make(session, owner, name="BPI Savings")
    stored = session.execute(select(Account.payload)).scalars().all()
    assert stored
    for payload in stored:
        assert b"BPI" not in payload
        assert b"Savings" not in payload
        assert b"1500" not in payload


def test_counts_in_cash_on_hand_defaults_by_type(session, owner):
    """ACC-18 - credit on, investment off, and the rest on."""
    kinds = {
        "cash": True, "debit": True, "savings": True, "credit": True, "investment": False,
        "lent": False, "borrowed": False, "member": True,
    }
    for kind, expected in kinds.items():
        extra = {"statement_closing_day": 20, "payment_due_day": 5} if kind == "credit" else {}
        view = make(session, owner, name=f"{kind} account", type=kind, **extra)
        assert view.counts_in_cash_on_hand is expected, kind


def test_borrowed_lent_and_member_accounts_move_money_like_any_other(session, owner):
    """ACC-31/32. A loan is a negative balance that repayments bring back to zero;
    money lent out comes back by transfer; a transport card is spent from."""
    from app.services import transaction_service

    wallet = make(session, owner, name="Wallet", opening_balance="10000.00")
    loan = make(session, owner, name="Car loan", type="borrowed", subtype="loan", opening_balance="-50000.00")
    lent = make(session, owner, name="Juan", type="lent", opening_balance="0")
    beep = make(session, owner, name="Beep", type="member", subtype="transport-card", opening_balance="0")
    on = date(2026, 9, 15)
    for source, target, amount in ((wallet, loan, "5000.00"), (wallet, lent, "2000.00"), (wallet, beep, "500.00")):
        transaction_service.create_transaction(session, owner, {
            "type": "transfer", "amount": amount, "account_id": source.id,
            "counter_account_id": target.id, "txn_date": on.isoformat()}, today=on)

    listed = account_service.list_accounts(session, owner, postings=transaction_service.postings(session, owner), today=on)
    views = {v.name: v for v in listed}
    assert views["Car loan"].balance == Decimal("-45000.00")
    assert views["Juan"].balance == Decimal("2000.00")
    assert views["Beep"].balance == Decimal("500.00")
    assert views["Car loan"].subtype == "loan"
    assert views["Car loan"].credit is None
    # Only the wallet and the member card count; the loan and the money lent out do not.
    cash = account_service.cash_on_hand(listed)
    assert set(cash.account_ids) == {wallet.id, beep.id}
    assert cash.total == Decimal("3000.00")  # 10,000 - 5,000 - 2,000 - 500 left in the wallet + 500 on the card


def test_a_subtype_is_kept_on_an_edit_that_does_not_mention_it(session, owner):
    """ACC-33."""
    created = make(session, owner, name="GCash", type="debit", subtype="e-wallet")
    account_service.update_account(session, owner, created.id, {"name": "GCash", "type": "debit"})
    assert account_service.get_account(session, owner, created.id).subtype == "e-wallet"
    account_service.update_account(session, owner, created.id, {"name": "GCash", "type": "debit", "subtype": None})
    assert account_service.get_account(session, owner, created.id).subtype is None


def test_a_subtype_must_be_a_short_slug(session, owner):
    with pytest.raises(ValidationException):
        make(session, owner, subtype="Not A Slug!")


def test_the_default_can_be_overridden(session, owner):
    view = make(session, owner, type="investment", name="COL Financial", counts_in_cash_on_hand=True)
    assert view.counts_in_cash_on_hand is True


def test_duplicate_names_are_refused(session, owner):
    make(session, owner, name="Wallet")
    with pytest.raises(BusinessRuleException):
        make(session, owner, name="wallet")


def test_type_cannot_change_after_creation(session, owner):
    created = make(session, owner)
    with pytest.raises(BusinessRuleException):
        account_service.update_account(session, owner, created.id, {**CASH, "type": "savings"})


def test_a_float_opening_balance_is_refused(session, owner):
    with pytest.raises(ValidationException):
        make(session, owner, opening_balance=1500.10)


def test_an_unknown_account_is_not_found(session, owner):
    with pytest.raises(NotFoundException):
        account_service.get_account(session, owner, 9999)


# -------------------------------------------------------------- the balances


def test_balance_is_opening_plus_postings_exactly(session, owner):
    created = make(session, owner, opening_balance="1000.00")
    postings = [
        Posting(created.id, date(2026, 9, 1), Decimal("-0.10")),
        Posting(created.id, date(2026, 9, 2), Decimal("-0.20")),
    ]
    view = account_service.get_account(session, owner, created.id, postings=postings)
    # The float answer here is 999.6999999999999; this must be 999.70.
    assert view.balance == Decimal("999.70")
    assert str(view.balance) == "999.70"


def test_postings_for_other_accounts_are_ignored(session, owner):
    mine = make(session, owner, name="Mine")
    theirs = make(session, owner, name="Theirs")
    postings = [Posting(theirs.id, date(2026, 9, 1), Decimal("-500.00"))]
    view = account_service.get_account(session, owner, mine.id, postings=postings)
    assert view.balance == Decimal("1500.00")


# ------------------------------------------------------------ cash on hand


def test_cash_on_hand_counts_only_what_is_switched_on(session, owner):
    make(session, owner, name="Wallet", opening_balance="1500.00")
    make(session, owner, name="BDO", type="debit", opening_balance="20000.00")
    make(session, owner, name="Fund", type="investment", opening_balance="100000.00")
    views = account_service.list_accounts(session, owner)

    total = account_service.cash_on_hand(views)
    assert total.total == Decimal("21500.00")  # the investment is not in my pockets
    assert len(total.account_ids) == 2
    assert len(total.excluded_ids) == 1


def test_a_card_balance_is_subtracted_from_cash_on_hand(session, owner):
    """ACC-18 - money already spent on the card is money you no longer have."""
    wallet = make(session, owner, name="Wallet", opening_balance="1500.00")
    card = make(session, owner, **CARD)
    postings = [Posting(card.id, date(2026, 9, 10), Decimal("-500.00"))]

    views = account_service.list_accounts(session, owner, postings=postings)
    assert account_service.cash_on_hand(views).total == Decimal("1000.00")
    assert {v.id for v in views} == {wallet.id, card.id}


def test_an_archived_account_never_counts(session, owner):
    make(session, owner, name="Wallet", opening_balance="1500.00")
    old = make(session, owner, name="Old bank", type="debit", opening_balance="900.00")
    account_service.set_archived(session, owner, old.id, True)

    views = account_service.list_accounts(session, owner)
    assert account_service.cash_on_hand(views).total == Decimal("1500.00")


def test_archiving_is_reversible_and_does_not_delete(session, owner):
    created = make(session, owner)
    account_service.set_archived(session, owner, created.id, True)
    assert account_service.get_account(session, owner, created.id).archived is True
    account_service.set_archived(session, owner, created.id, False)
    assert account_service.get_account(session, owner, created.id).archived is False


# ------------------------------------------------------------- credit cards


def test_statement_period_and_due_date_are_derived(session, owner):
    card = make(session, owner, **CARD)
    view = account_service.get_account(session, owner, card.id, today=date(2026, 9, 13))
    assert view.credit.period_start == date(2026, 8, 21)
    assert view.credit.period_closes == date(2026, 9, 20)
    assert view.credit.payment_due == date(2026, 10, 5)


def test_period_spend_counts_only_the_open_period(session, owner):
    card = make(session, owner, **CARD)
    postings = [
        Posting(card.id, date(2026, 8, 15), Decimal("-1000.00")),  # last statement
        Posting(card.id, date(2026, 8, 25), Decimal("-300.00")),   # this one
        Posting(card.id, date(2026, 9, 12), Decimal("-200.00")),   # this one
    ]
    view = account_service.get_account(session, owner, card.id, postings=postings, today=date(2026, 9, 13))
    assert view.credit.period_spend == Decimal("500.00")
    assert view.credit.owed == Decimal("1500.00")  # the whole carried balance


def test_available_credit_subtracts_the_installment_remainder(session, owner):
    """ACC-14 - the bank blocks the whole remainder, so we must too."""
    card = make(session, owner, **CARD)
    account_service.update_account(
        session, owner, card.id, {**CARD, "counts_in_cash_on_hand": True}
    )
    # Since Phase 7 the remainder is derived from the installment plans on the
    # card - here one that has not posted a payment yet.
    from app.services import category_service, recurring_service

    gadgets = category_service.create_category(session, owner, {"name": "Gadgets"})
    recurring_service.create_rule(session, owner, {
        "kind": "installment", "name": "Phone", "account_id": card.id, "category_id": gadgets.id,
        "frequency": "monthly", "start": "2026-10-01", "price": "36000.00", "payments": 12,
    }, today=date(2026, 9, 13))

    postings = [Posting(card.id, date(2026, 9, 10), Decimal("-4000.00"))]
    view = account_service.get_account(session, owner, card.id, postings=postings, today=date(2026, 9, 13))
    assert view.credit.owed == Decimal("4000.00")
    assert view.credit.available == Decimal("10000.00")  # 50000 - 4000 - 36000


def test_what_you_owe_is_one_figure_on_a_card_and_a_loan(session, owner):
    """
    REC-14. `owed_with_plans` is worked out once, on the view, for every type in
    OWES - the page, the payoff planner and the assistant all read it. An
    overpaid balance owes nothing, so the plans are the floor (2026-10-12: the
    planner clamped and the page did not).
    """
    from app.services import category_service, recurring_service

    card = make(session, owner, **CARD)
    loan = make(session, owner, name="From Ana", type="borrowed", opening_balance="0")
    cash = make(session, owner)
    gadgets = category_service.create_category(session, owner, {"name": "Gadgets"})
    for account in (card, loan):
        recurring_service.create_rule(session, owner, {
            "kind": "installment", "name": f"Phone {account.id}", "account_id": account.id,
            "category_id": gadgets.id, "frequency": "monthly", "start": "2026-10-01",
            "price": "12000.00", "payments": 12,
        }, today=date(2026, 9, 13))

    postings = [Posting(card.id, date(2026, 9, 10), Decimal("-4000.00")),
                Posting(loan.id, date(2026, 9, 10), Decimal("100.00"))]  # paid ₱100 too much
    views = {v.id: v for v in account_service.list_accounts(session, owner, postings=postings,
                                                             today=date(2026, 9, 13))}
    assert views[card.id].owed_with_plans == views[card.id].credit.owed_with_plans == Decimal("16000.00")
    assert views[loan.id].owed_with_plans == Decimal("12000.00")
    assert views[cash.id].owed_with_plans is None


def test_due_soon_uses_the_configured_window(session, owner):
    card = make(session, owner, **CARD)
    close = account_service.get_account(session, owner, card.id, today=date(2026, 10, 2))
    far = account_service.get_account(session, owner, card.id, today=date(2026, 9, 13))
    assert close.credit.due_soon is True and close.credit.due_in_days == 3
    assert far.credit.due_soon is False


def test_only_a_credit_account_carries_credit_terms(session, owner):
    view = make(session, owner, type="savings", name="BDO Savings",
                statement_closing_day=20, payment_due_day=5, credit_limit="1000.00")
    assert view.credit is None
    record = account_service.AccountRepository(session, owner).get(view.id)
    assert "credit_limit" not in record.data
    assert "statement_closing_day" not in record.data


def test_a_card_needs_its_closing_and_due_days(session, owner):
    with pytest.raises(ValidationException):
        make(session, owner, name="Card", type="credit", statement_closing_day=40, payment_due_day=5)


# --------------------------------------------------------------- investments


def test_a_typed_value_is_appended_with_its_date(session, owner):
    """ACC-13 - the history is kept, not overwritten."""
    fund = make(session, owner, type="investment", name="Fund", opening_balance="100000.00")
    account_service.add_valuation(session, owner, fund.id, "105000.00", on=date(2026, 9, 1))
    view = account_service.add_valuation(session, owner, fund.id, "103500.00", on=date(2026, 10, 1))

    assert [str(v.value) for v in view.valuations] == ["105000.00", "103500.00"]
    assert view.current_value == Decimal("103500.00")
    assert view.balance == Decimal("103500.00")


def test_before_any_valuation_the_opening_balance_stands(session, owner):
    fund = make(session, owner, type="investment", name="Fund", opening_balance="100000.00")
    assert fund.current_value == Decimal("100000.00")


def test_money_moved_in_counts_on_top_of_the_typed_value(session, owner):
    """
    ACC-08/12, fixed 2026-09-16 (user: a transfer into an investment account
    was logged and the balance stood still). What it is WORTH is typed; what
    you MOVE in is a transfer, and it is real money in the fund.
    """
    fund = make(session, owner, type="investment", name="Exness", opening_balance="100000.00")
    account_service.add_valuation(session, owner, fund.id, "105000.00", on=date(2026, 9, 1))
    moved = [Posting(fund.id, date(2026, 9, 10), Decimal("20000.00"), "transfer")]

    view = account_service.get_account(session, owner, fund.id, postings=moved)
    assert view.current_value == Decimal("105000.00")  # still what you typed
    assert view.balance == Decimal("125000.00")  # plus what you put in since


def test_a_contribution_before_the_valuation_is_already_inside_it(session, owner):
    """Typing a value states what the fund is worth THAT day - contributions up to it included."""
    fund = make(session, owner, type="investment", name="Exness", opening_balance="100000.00")
    account_service.add_valuation(session, owner, fund.id, "130000.00", on=date(2026, 9, 20))
    earlier = [Posting(fund.id, date(2026, 9, 10), Decimal("20000.00"), "transfer"),
               Posting(fund.id, date(2026, 9, 20), Decimal("5000.00"), "transfer")]

    assert account_service.get_account(session, owner, fund.id, postings=earlier).balance == Decimal("130000.00")


def test_a_transfer_entered_after_the_value_was_typed_that_day_counts(session, owner):
    """
    Fixed 2026-09-19 (user: moved money from SeaBank to Exness and the Exness
    balance did not move). Same day as the value, but entered after it.
    """
    fund = make(session, owner, type="investment", name="Exness", opening_balance="100000.00")
    view = account_service.add_valuation(session, owner, fund.id, "105000.00", on=date(2026, 9, 19))
    typed = view.valuations[-1].at
    before = Posting(fund.id, date(2026, 9, 19), Decimal("3000.00"), "transfer", None, typed - timedelta(minutes=5))
    after = Posting(fund.id, date(2026, 9, 19), Decimal("20000.00"), "transfer", None, typed + timedelta(minutes=5))

    view = account_service.get_account(session, owner, fund.id, postings=[before, after])
    assert view.current_value == Decimal("105000.00")
    assert view.balance == Decimal("125000.00")  # the earlier one is inside the typed value


def test_a_value_typed_before_it_had_a_time_counts_same_day_postings_entered_later(session, owner):
    """A value saved with only its day covers what was entered that day, not after."""
    fund = make(session, owner, type="investment", name="Exness", opening_balance="100000.00")
    account_service.add_valuation(session, owner, fund.id, "105000.00", on=date(2026, 9, 17))
    record = AccountRepository(session, owner).get(fund.id)
    data = dict(record.data)
    data["valuations"] = [{"on": "2026-09-17", "value": "105000.00"}]  # as stored before 2026-09-19
    AccountRepository(session, owner).update(fund.id, data)
    session.commit()

    same_day = Posting(fund.id, date(2026, 9, 17), Decimal("3000.00"), "transfer", None, datetime(2026, 9, 17, 2, 0))
    next_day = Posting(fund.id, date(2026, 9, 17), Decimal("20000.00"), "transfer", None, datetime(2026, 9, 18, 2, 0))
    view = account_service.get_account(session, owner, fund.id, postings=[same_day, next_day])
    assert view.balance == Decimal("125000.00")


def test_money_taken_out_of_a_fund_comes_off_it(session, owner):
    fund = make(session, owner, type="investment", name="Exness", opening_balance="100000.00")
    out = [Posting(fund.id, date(2026, 9, 10), Decimal("-15000.00"), "transfer")]
    assert account_service.get_account(session, owner, fund.id, postings=out).balance == Decimal("85000.00")


def test_typing_a_new_value_takes_the_contribution_in(session, owner):
    """The new figure is the whole truth again, so nothing is counted twice."""
    fund = make(session, owner, type="investment", name="Exness", opening_balance="100000.00")
    moved = [Posting(fund.id, date(2026, 9, 10), Decimal("20000.00"), "transfer")]
    assert account_service.get_account(session, owner, fund.id, postings=moved).balance == Decimal("120000.00")

    account_service.add_valuation(session, owner, fund.id, "121450.00", on=date(2026, 9, 16))
    view = account_service.get_account(session, owner, fund.id, postings=moved)
    assert view.balance == Decimal("121450.00")


def test_net_worth_counts_what_was_moved_into_a_fund(session, owner):
    fund = make(session, owner, type="investment", name="Exness", opening_balance="100000.00")
    moved = [Posting(fund.id, date(2026, 9, 10), Decimal("20000.00"), "transfer")]
    views = account_service.list_accounts(session, owner, postings=moved)
    assert account_service.net_worth(views).total == Decimal("120000.00")


@pytest.mark.security
def test_a_revaluation_writes_no_transaction(session, owner):
    """ACC-12 - it is a valuation change, and stays out of income and spending."""
    from app.db.models import Transaction

    fund = make(session, owner, type="investment", name="Fund", opening_balance="100000.00")
    account_service.add_valuation(session, owner, fund.id, "105000.00", on=date(2026, 9, 1))
    assert session.execute(select(Transaction.id)).all() == []


def test_only_an_investment_account_can_be_revalued(session, owner):
    wallet = make(session, owner)
    with pytest.raises(BusinessRuleException):
        account_service.add_valuation(session, owner, wallet.id, "10.00")


def test_typing_an_investments_value_asks_and_records_an_unrecorded_gain(session, owner):
    """ACC-12/28, changed 2026-09-18 (user): a new value asks, like every other account."""
    from app.core.exceptions import BalanceDiffersException
    from app.services import transaction_service

    fund = make(session, owner, type="investment", name="Exness", opening_balance="100000.00")
    edit = {"name": "Exness", "type": "investment", "balance": "104250.00"}
    with pytest.raises(BalanceDiffersException):
        account_service.update_account(session, owner, fund.id, edit, today=date(2026, 9, 18))

    account_service.update_account(session, owner, fund.id, {**edit, "balance_action": "adjust"},
                                   postings=transaction_service.postings(session, owner), today=date(2026, 9, 18))
    views = transaction_service.views(session, owner)
    assert [(v.type, v.direction, str(v.amount)) for v in views] == [("adjustment", "in", "4250.00")]
    view = account_service.get_account(session, owner, fund.id, postings=transaction_service.postings(session, owner))
    assert (view.balance, view.opening_balance) == (Decimal("104250.00"), Decimal("100000.00"))


def test_an_unrecorded_loss_on_the_valuations_own_day_still_counts(session, owner):
    from app.services import transaction_service

    fund = make(session, owner, type="investment", name="Exness", opening_balance="100000.00")
    account_service.add_valuation(session, owner, fund.id, "105000.00", on=date(2026, 9, 18))
    account_service.update_account(session, owner, fund.id,
                                   {"name": "Exness", "type": "investment", "balance": "103000.00", "balance_action": "adjust"},
                                   postings=transaction_service.postings(session, owner), today=date(2026, 9, 18))
    view = account_service.get_account(session, owner, fund.id, postings=transaction_service.postings(session, owner))
    assert view.balance == Decimal("103000.00")


def test_correcting_a_valued_investment_moves_its_last_value_and_records_nothing(session, owner):
    from app.services import transaction_service

    fund = make(session, owner, type="investment", name="Exness", opening_balance="100000.00")
    account_service.add_valuation(session, owner, fund.id, "105000.00", on=date(2026, 9, 1))
    account_service.update_account(session, owner, fund.id,
                                   {"name": "Exness", "type": "investment", "balance": "106000.00",
                                    "balance_action": "fix_opening"},
                                   postings=transaction_service.postings(session, owner), today=date(2026, 9, 18))
    view = account_service.get_account(session, owner, fund.id, postings=transaction_service.postings(session, owner))
    assert (view.balance, view.opening_balance) == (Decimal("106000.00"), Decimal("100000.00"))
    assert [str(v.value) for v in view.valuations] == ["106000.00"]
    assert transaction_service.views(session, owner) == []


def test_a_valuation_cannot_be_set_through_the_normal_update(session, owner):
    fund = make(session, owner, type="investment", name="Fund", opening_balance="100000.00")
    account_service.update_account(
        session, owner, fund.id,
        {"name": "Fund", "type": "investment", "opening_balance": "100000.00",
         "valuations": [{"on": "2026-09-01", "value": "999999.00"}]},
    )
    assert account_service.get_account(session, owner, fund.id).valuations == ()


# ---------------------------------------------------------------- the API


def register(api):
    response = api.register()
    assert response.status_code == 201, response.text
    return response


def test_accounts_need_an_unlocked_session(api):
    register(api)
    api.post("/auth/lock")
    response = api.get("/accounts")
    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_LOCKED"


def test_create_and_list_through_the_api(api):
    register(api)
    created = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "1500.00"})
    assert created.status_code == 201, created.text
    assert created.json()["balance"] == "1500.00"

    listed = api.get("/accounts").json()
    assert [a["name"] for a in listed["accounts"]] == ["Wallet"]
    assert listed["cash_on_hand"]["total"] == "1500.00"


def test_the_api_refuses_an_amount_sent_as_a_number(api):
    """Invariant 5, at the edge: JSON 1500.10 has already been through a float."""
    register(api)
    response = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": 1500.10})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_an_integer_amount_is_still_accepted(api):
    register(api)
    response = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": 1500})
    assert response.status_code == 201
    assert response.json()["opening_balance"] == "1500.00"


def test_archive_through_the_api(api):
    register(api)
    account_id = api.post("/accounts", {"name": "Old", "type": "debit"}).json()["id"]
    response = api.post(f"/accounts/{account_id}/archive", {"archived": True})
    assert response.status_code == 200
    assert response.json()["archived"] is True
    assert api.get("/accounts?include_archived=false").json()["accounts"] == []


def test_there_is_no_way_to_delete_an_account(api):
    """ACC-06 - history depends on the row existing."""
    register(api)
    account_id = api.post("/accounts", {"name": "Wallet", "type": "cash"}).json()["id"]
    assert api.delete(f"/accounts/{account_id}").status_code == 405


def test_one_user_cannot_see_another_users_accounts(api):
    register(api)
    api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "1500.00"})
    api.post("/auth/logout")

    second = api.register(email="mara@example.com", name="Mara")
    assert second.status_code == 201, second.text
    assert api.get("/accounts").json()["accounts"] == []

# ------------------------------------------------- untracked cash (ACC-39)


def test_the_wallet_is_made_once_and_handed_back(session, owner):
    """ACC-39 - get-or-create, so two taps cannot leave two wallets behind."""
    first = account_service.untracked_cash(session, owner)
    second = account_service.untracked_cash(session, owner)
    assert first.id == second.id
    assert first.hidden is True
    assert first.type == "cash"
    assert len(AccountRepository(session, owner).list()) == 1


def test_the_wallet_is_in_no_total(session, owner):
    """
    ACC-39. It is cash the user already counts as spent: lending from it moves
    the loan and nothing else. Its own balance only ever falls, and no figure
    anywhere may read it.
    """
    make(session, owner, name="BDO", type="debit", opening_balance="20000.00")
    lent = make(session, owner, name="Juan", type="lent", opening_balance="0")
    wallet = account_service.untracked_cash(session, owner)
    # The two legs of "Lend more, from my wallet".
    postings = [
        Posting(wallet.id, date(2026, 9, 20), Decimal("-500.00"), "transfer"),
        Posting(lent.id, date(2026, 9, 20), Decimal("500.00"), "transfer"),
    ]
    views = account_service.list_accounts(session, owner, postings=postings)

    total = account_service.cash_on_hand(views)
    assert total.total == Decimal("20000.00")  # untouched: that cash was spent long ago
    assert wallet.id not in total.account_ids
    # Net worth gains the loan and never sees the wallet's -500.
    assert account_service.net_worth(views).total == Decimal("20500.00")


def test_the_wallet_keeps_its_name_clear_of_yours(session, owner):
    """The user may already have an account called My wallet; the hidden one is still made."""
    make(session, owner, name=account_service.UNTRACKED_NAME)
    wallet = account_service.untracked_cash(session, owner)
    assert wallet.name != account_service.UNTRACKED_NAME
    assert wallet.hidden is True


def test_an_ordinary_account_is_never_hidden(session, owner):
    """`hidden` is not part of a payload: only untracked_cash() may set it."""
    account = account_service.create_account(session, owner, {**CASH, "hidden": True})
    assert account.hidden is False


def test_editing_the_wallet_leaves_it_hidden(session, owner):
    wallet = account_service.untracked_cash(session, owner)
    account_service.update_account(session, owner, wallet.id, {"name": "Cash I don't track", "type": "cash"})
    assert account_service.get_account(session, owner, wallet.id).hidden is True

def test_lending_from_the_wallet_through_the_api(api):
    """
    ACC-39, end to end: the whole point of the hidden account. Lending ₱500
    from cash the user does not track must move the loan and NOTHING else -
    that money was counted as spent the day it left a real account.
    """
    register(api)
    api.post("/accounts", {"name": "BDO", "type": "debit", "opening_balance": "20000.00"})
    juan = api.post("/accounts", {"name": "Juan", "type": "lent", "opening_balance": "0"})

    wallet = api.post("/accounts/untracked", {})
    assert wallet.status_code == 200, wallet.text
    assert wallet.json()["hidden"] is True
    # Called again by the next loan: the same account, never a second one.
    assert api.post("/accounts/untracked", {}).json()["id"] == wallet.json()["id"]

    lent = api.post("/transactions", {
        "type": "transfer", "amount": "500.00", "txn_date": "2026-09-20",
        "account_id": wallet.json()["id"], "counter_account_id": juan.json()["id"],
    })
    assert lent.status_code == 201, lent.text

    listed = api.get("/accounts").json()
    by_name = {a["name"]: a for a in listed["accounts"]}
    assert by_name["Juan"]["balance"] == "500.00"      # what Juan owes went up
    assert by_name["BDO"]["balance"] == "20000.00"     # and nothing else moved
    assert listed["cash_on_hand"]["total"] == "20000.00"
    assert listed["net_worth"]["total"] == "20500.00"
    assert wallet.json()["id"] in listed["cash_on_hand"]["excluded_ids"]
    # It is still RETURNED - the client needs its name for the row and its id
    # for the next loan - but it is the client that never lists it.
    assert [a["id"] for a in listed["accounts"] if a["hidden"]] == [wallet.json()["id"]]
