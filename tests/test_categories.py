"""
Categories, sub-categories, and the delete that has to clean up after itself
(CAT-01..CAT-08).

The test that matters most is the last group: deleting a category must walk
EVERY SPLIT of every transaction. A reference left behind inside `splits[]` is
invisible to SQL, to the type system and to every later report - the first
sign of it would be a budget that quietly stops adding up.
"""

import pytest

from app.core.exceptions import (
    BusinessRuleException,
    ConflictException,
    NotFoundException,
    ValidationException,
)
from app.db.repositories.transaction_repository import TransactionRepository
from app.services import category_service


def make(session, cipher, name, **overrides):
    return category_service.create_category(session, cipher, {"name": name, **overrides})


def add_transaction(session, cipher, *splits, amount="1000.00"):
    """A Phase 4-shaped transaction: every one carries a splits array (TXN-16)."""
    repo = TransactionRepository(session, cipher)
    record = repo.create({
        "txn_date": "2026-09-12",
        "type": "expense",
        "amount": amount,
        "account_id": 1,
        "merchant": "SM",
        "splits": [{"category_id": cid, "amount": value} for cid, value in splits],
    })
    session.commit()
    return record


# -------------------------------------------------------------- the tree


def test_create_and_read_back(session, owner):
    created = make(session, owner, "Groceries", icon="cart", colour="#2C9669")
    fetched = category_service.get_category(session, owner, created.id)
    assert (fetched.name, fetched.icon, fetched.colour, fetched.kind) == ("Groceries", "cart", "#2C9669", "expense")


def test_children_nest_under_their_parent(session, owner):
    food = make(session, owner, "Food")
    make(session, owner, "Coffee", parent_id=food.id)
    make(session, owner, "Groceries", parent_id=food.id)

    tree = category_service.list_categories(session, owner)
    assert [c.name for c in tree] == ["Food"]
    assert [c.name for c in tree[0].children] == ["Coffee", "Groceries"]


def test_sub_categories_go_one_level_deep(session, owner):
    food = make(session, owner, "Food")
    coffee = make(session, owner, "Coffee", parent_id=food.id)
    with pytest.raises(BusinessRuleException):
        make(session, owner, "Beans", parent_id=coffee.id)


def test_a_parent_cannot_become_a_child(session, owner):
    food = make(session, owner, "Food")
    make(session, owner, "Coffee", parent_id=food.id)
    other = make(session, owner, "Shopping")
    with pytest.raises(BusinessRuleException):
        category_service.update_category(session, owner, food.id, {"name": "Food", "parent_id": other.id})


def test_a_category_cannot_be_its_own_parent(session, owner):
    food = make(session, owner, "Food")
    with pytest.raises(BusinessRuleException):
        category_service.update_category(session, owner, food.id, {"name": "Food", "parent_id": food.id})


def test_a_missing_parent_is_refused(session, owner):
    """No foreign key can say this - parent_id is inside the ciphertext."""
    with pytest.raises(ValidationException):
        make(session, owner, "Coffee", parent_id=4242)


def test_a_sub_category_shares_its_parents_kind(session, owner):
    salary = make(session, owner, "Salary", kind="income")
    with pytest.raises(BusinessRuleException):
        make(session, owner, "Groceries", kind="expense", parent_id=salary.id)


def test_duplicate_names_under_the_same_parent_are_refused(session, owner):
    food = make(session, owner, "Food")
    make(session, owner, "Coffee", parent_id=food.id)
    with pytest.raises(BusinessRuleException):
        make(session, owner, "coffee", parent_id=food.id)


def test_the_same_name_is_fine_under_a_different_parent(session, owner):
    food = make(session, owner, "Food")
    travel = make(session, owner, "Travel")
    make(session, owner, "Coffee", parent_id=food.id)
    assert make(session, owner, "Coffee", parent_id=travel.id).name == "Coffee"


def test_expense_and_income_are_separate_lists(session, owner):
    make(session, owner, "Groceries")
    make(session, owner, "Salary", kind="income")
    assert [c.name for c in category_service.list_categories(session, owner, kind="income")] == ["Salary"]
    assert [c.name for c in category_service.list_categories(session, owner, kind="expense")] == ["Groceries"]


def test_reorder_writes_the_dragged_order(session, owner):
    first = make(session, owner, "A")
    second = make(session, owner, "B")
    third = make(session, owner, "C")

    category_service.reorder(session, owner, [third.id, first.id, second.id])
    assert [c.name for c in category_service.list_categories(session, owner)] == ["C", "A", "B"]


def test_reorder_rejects_an_unknown_id(session, owner):
    first = make(session, owner, "A")
    with pytest.raises(NotFoundException):
        category_service.reorder(session, owner, [first.id, 9999])


# ------------------------------------------------------------- safe delete


def test_an_unused_category_just_goes(session, owner):
    coffee = make(session, owner, "Coffee")
    result = category_service.delete_category(session, owner, coffee.id)
    assert result == {"deleted": [coffee.id], "transactions_moved": 0, "reassigned_to": None}
    assert category_service.list_categories(session, owner) == []


def test_deleting_a_used_category_asks_where_to_move_them(session, owner):
    """CAT-08 - it refuses, and says how many are in the way."""
    coffee = make(session, owner, "Coffee")
    add_transaction(session, owner, (coffee.id, "1000.00"))

    with pytest.raises(ConflictException) as raised:
        category_service.delete_category(session, owner, coffee.id)
    assert raised.value.extra["usage"] == 1
    assert category_service.get_category(session, owner, coffee.id).name == "Coffee"


@pytest.mark.security
def test_reassignment_rewrites_every_split(session, owner):
    """
    The one that cannot be caught later. `category_id` lives inside splits[],
    one level deeper in the ciphertext than a top-level field - a miss here is
    invisible to the database.
    """
    coffee = make(session, owner, "Coffee")
    household = make(session, owner, "Household")
    food = make(session, owner, "Food")
    record = add_transaction(session, owner, (coffee.id, "300.00"), (household.id, "700.00"))

    result = category_service.delete_category(session, owner, coffee.id, reassign_to=food.id)
    assert result["transactions_moved"] == 1

    data = TransactionRepository(session, owner).get(record.id).data
    assert [split["category_id"] for split in data["splits"]] == [food.id, household.id]
    assert [split["amount"] for split in data["splits"]] == ["300.00", "700.00"]  # untouched


def test_deleting_a_parent_takes_its_children_and_their_transactions(session, owner):
    food = make(session, owner, "Food")
    coffee = make(session, owner, "Coffee", parent_id=food.id)
    other = make(session, owner, "Other")
    record = add_transaction(session, owner, (coffee.id, "1000.00"))

    result = category_service.delete_category(session, owner, food.id, reassign_to=other.id)
    assert result["deleted"] == sorted([food.id, coffee.id])
    assert result["transactions_moved"] == 1

    data = TransactionRepository(session, owner).get(record.id).data
    assert data["splits"][0]["category_id"] == other.id
    remaining = category_service.list_categories(session, owner)
    assert [c.name for c in remaining] == ["Other"]
    assert remaining[0].children == ()


def test_transactions_cannot_be_moved_onto_a_doomed_category(session, owner):
    food = make(session, owner, "Food")
    coffee = make(session, owner, "Coffee", parent_id=food.id)
    add_transaction(session, owner, (coffee.id, "1000.00"))
    with pytest.raises(BusinessRuleException):
        category_service.delete_category(session, owner, food.id, reassign_to=coffee.id)


def test_transactions_cannot_be_moved_across_kinds(session, owner):
    """An expense on an income category would flip its sign in every report."""
    coffee = make(session, owner, "Coffee")
    salary = make(session, owner, "Salary", kind="income")
    add_transaction(session, owner, (coffee.id, "1000.00"))
    with pytest.raises(BusinessRuleException):
        category_service.delete_category(session, owner, coffee.id, reassign_to=salary.id)


def test_usage_counts_every_split_not_every_transaction(session, owner):
    coffee = make(session, owner, "Coffee")
    household = make(session, owner, "Household")
    add_transaction(session, owner, (coffee.id, "300.00"), (household.id, "700.00"))
    add_transaction(session, owner, (coffee.id, "50.00"), amount="50.00")

    tree = {c.name: c.usage for c in category_service.list_categories(session, owner, with_usage=True)}
    assert tree == {"Coffee": 2, "Household": 1}


# ---------------------------------------------------------------- the API


def test_categories_need_an_unlocked_session(api):
    assert api.register().status_code == 201
    api.post("/auth/lock")
    response = api.get("/categories")
    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_LOCKED"


def test_create_and_nest_through_the_api(api):
    assert api.register().status_code == 201
    parent = api.post("/categories", {"name": "Food", "icon": "restaurant", "colour": "#E8734A"})
    assert parent.status_code == 201, parent.text
    child = api.post("/categories", {"name": "Coffee", "parent_id": parent.json()["id"]})
    assert child.status_code == 201

    tree = api.get("/categories").json()
    assert [c["name"] for c in tree] == ["Food"]
    assert [c["name"] for c in tree[0]["children"]] == ["Coffee"]


def test_delete_through_the_api(api):
    assert api.register().status_code == 201
    category_id = api.post("/categories", {"name": "Coffee"}).json()["id"]
    account_id = api.post("/accounts", {"name": "Wallet", "type": "cash"}).json()["id"]
    assert account_id

    # No transactions endpoint until Phase 4, so an unused delete is the path
    # the API can prove today; the reassignment itself is covered above.
    response = api.delete(f"/categories/{category_id}")
    assert response.status_code == 200
    assert response.json()["deleted"] == [category_id]


def test_reorder_through_the_api(api):
    assert api.register().status_code == 201
    first = api.post("/categories", {"name": "A"}).json()["id"]
    second = api.post("/categories", {"name": "B"}).json()["id"]
    ordered = api.post("/categories/reorder", {"ordered_ids": [second, first]})
    assert ordered.status_code == 200
    assert [c["name"] for c in ordered.json()] == ["B", "A"]


def test_one_user_cannot_see_another_users_categories(api):
    assert api.register().status_code == 201
    api.post("/categories", {"name": "Coffee"})
    api.post("/auth/logout")

    assert api.register(email="mara@example.com", name="Mara").status_code == 201
    assert api.get("/categories").json() == []
