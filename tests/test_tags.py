"""
Tags (TXN-10) - the labels that cut across categories.

The test that matters most is the delete: a tag id lives inside every
transaction payload that uses it, where no foreign key can reach. Deleting the
tag must walk every transaction and take the id out, or the ledger filter and
spending-by-tag would quietly count a tag that no longer exists.
"""

import pytest

from app.core.exceptions import BusinessRuleException, NotFoundException, ValidationException
from app.db.repositories.transaction_repository import TransactionRepository
from app.services import account_service, category_service, tag_service, transaction_service


@pytest.fixture
def setup(session, owner):
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash",
                                                             "opening_balance": "5000.00"})
    bank = account_service.create_account(session, owner, {"name": "BDO", "type": "debit"})
    food = category_service.create_category(session, owner, {"name": "Food"})
    trip = tag_service.create_tag(session, owner, {"name": "Boracay trip", "colour": "#4a90d9"})
    work = tag_service.create_tag(session, owner, {"name": "Work"})

    class S:
        pass

    s = S()
    s.wallet, s.bank, s.food, s.trip, s.work = wallet.id, bank.id, food.id, trip.id, work.id
    return s


def spend(session, owner, s, amount="100.00", **extra):
    payload = {"type": "expense", "amount": amount, "account_id": s.wallet,
               "category_id": s.food, "txn_date": "2026-09-12", **extra}
    return transaction_service.create_transaction(session, owner, payload).transactions[0]


# ----------------------------------------------------------------- the tags


def test_create_and_list_alphabetically(session, owner, setup):
    tags = tag_service.list_tags(session, owner)
    assert [(t.name, t.colour) for t in tags] == [("Boracay trip", "#4A90D9"), ("Work", "#6E7B8B")]


def test_names_are_unique_whatever_the_case(session, owner, setup):
    with pytest.raises(BusinessRuleException):
        tag_service.create_tag(session, owner, {"name": "  boracay   TRIP "})


def test_a_bad_colour_is_refused(session, owner, setup):
    with pytest.raises(ValidationException):
        tag_service.update_tag(session, owner, setup.work, {"name": "Work", "colour": "blue"})


def test_rename_keeps_the_colour(session, owner, setup):
    renamed = tag_service.update_tag(session, owner, setup.trip, {"name": "Bora 2026"})
    assert (renamed.name, renamed.colour) == ("Bora 2026", "#4A90D9")


def test_usage_counts_transactions(session, owner, setup):
    spend(session, owner, setup, tag_ids=[setup.trip])
    spend(session, owner, setup, tag_ids=[setup.trip, setup.work])
    usage = {t.id: t.usage for t in tag_service.list_tags(session, owner, with_usage=True)}
    assert usage == {setup.trip: 2, setup.work: 1}


# ------------------------------------------------------ tags on transactions


def test_a_transaction_carries_its_tags(session, owner, setup):
    row = spend(session, owner, setup, tag_ids=[setup.work, setup.trip, setup.work])
    assert row.tag_ids == (setup.work, setup.trip)  # duplicates dropped, order kept


def test_an_unknown_tag_is_refused(session, owner, setup):
    """No foreign key can say this - tag_ids is inside the ciphertext."""
    with pytest.raises(ValidationException):
        spend(session, owner, setup, tag_ids=[4242])


def test_a_deleted_tag_cannot_be_used(session, owner, setup):
    tag_service.delete_tag(session, owner, setup.work)
    with pytest.raises(ValidationException):
        spend(session, owner, setup, tag_ids=[setup.work])


def test_an_edit_that_does_not_mention_tags_keeps_them(session, owner, setup):
    row = spend(session, owner, setup, tag_ids=[setup.trip])
    edited = transaction_service.update_transaction(session, owner, row.id, {
        "type": "expense", "amount": "120.00", "account_id": setup.wallet,
        "category_id": setup.food, "txn_date": "2026-09-12"}).transactions[0]
    assert edited.tag_ids == (setup.trip,)


def test_an_empty_list_clears_them(session, owner, setup):
    row = spend(session, owner, setup, tag_ids=[setup.trip])
    edited = transaction_service.update_transaction(session, owner, row.id, {
        "type": "expense", "amount": "100.00", "account_id": setup.wallet,
        "category_id": setup.food, "txn_date": "2026-09-12", "tag_ids": []}).transactions[0]
    assert edited.tag_ids == ()


def test_repeat_last_copies_the_tags(session, owner, setup):
    spend(session, owner, setup, tag_ids=[setup.trip])
    copy = transaction_service.repeat_last(session, owner).transactions[0]
    assert copy.tag_ids == (setup.trip,)


def test_a_transfer_carries_no_tags(session, owner, setup):
    legs = transaction_service.create_transaction(session, owner, {
        "type": "transfer", "amount": "50.00", "account_id": setup.wallet,
        "counter_account_id": setup.bank, "tag_ids": [setup.trip]}).transactions
    assert all(leg.tag_ids == () for leg in legs)


def test_the_ledger_filters_by_tag(session, owner, setup):
    tagged = spend(session, owner, setup, tag_ids=[setup.trip])
    spend(session, owner, setup)
    page = transaction_service.list_transactions(session, owner, tag_id=setup.trip)
    assert [row.id for row in page.items] == [tagged.id]


# --------------------------------------------------------------- the delete


def test_deleting_a_tag_leaves_no_transaction_pointing_at_it(session, owner, setup):
    both = spend(session, owner, setup, tag_ids=[setup.trip, setup.work])
    only = spend(session, owner, setup, tag_ids=[setup.work])
    untouched = spend(session, owner, setup, tag_ids=[setup.trip])

    result = tag_service.delete_tag(session, owner, setup.work)
    assert result == {"deleted": setup.work, "transactions_untagged": 2}

    # The working set was written through...
    cached = {r.id: r.data["tag_ids"] for r in TransactionRepository(session, owner).cached()}
    assert cached == {both.id: [setup.trip], only.id: [], untouched.id: [setup.trip]}
    # ...and so was the database: a cold read says the same.
    stored = {r.id: r.data["tag_ids"] for r in TransactionRepository(session, owner).list()}
    assert stored == cached
    assert [t.id for t in tag_service.list_tags(session, owner)] == [setup.trip]


def test_deleting_a_missing_tag_is_not_found(session, owner, setup):
    with pytest.raises(NotFoundException):
        tag_service.delete_tag(session, owner, 4242)


# ---------------------------------------------------------------- the API


def test_tags_through_the_api(api):
    assert api.register().status_code == 201
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "1000.00"}).json()["id"]
    food = api.post("/categories", {"name": "Food"}).json()["id"]

    created = api.post("/tags", {"name": "Trip", "colour": "#4A90D9"})
    assert created.status_code == 201, created.text
    tag = created.json()["id"]

    response = api.post("/transactions", {"type": "expense", "amount": "250.00", "account_id": wallet,
                                          "category_id": food, "tag_ids": [tag]})
    assert response.status_code == 201, response.text
    assert response.json()["transactions"][0]["tag_ids"] == [tag]

    assert api.get(f"/transactions?tag={tag}").json()["total_count"] == 1
    assert api.get("/tags?with_usage=true").json()[0]["usage"] == 1

    deleted = api.delete(f"/tags/{tag}")
    assert deleted.json() == {"deleted": tag, "transactions_untagged": 1}
    assert api.get("/transactions").json()["items"][0]["tag_ids"] == []


def test_tags_need_an_unlocked_session(api):
    assert api.register().status_code == 201
    api.post("/auth/lock")
    response = api.get("/tags")
    assert (response.status_code, response.json()["code"]) == (401, "SESSION_LOCKED")
