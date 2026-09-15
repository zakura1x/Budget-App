"""
CSV out and in (DAT-01..05, DAT-11).

The guarantee that matters: an export re-imports identically - one row per
split, so a split purchase comes back as the same split. Around it: preview
writes nothing, duplicates are recognised, a CSV from a bank with its own
column names and signed amounts imports through a mapping, and a file with any
problem imports nothing at all.
"""

import csv
import io

import pytest

from app.core.exceptions import BusinessRuleException, ValidationException
from app.db.repositories.transaction_repository import TransactionRepository
from app.services import (
    account_service,
    category_service,
    import_export_service,
    tag_service,
    transaction_service,
)


def books(session, cipher):
    wallet = account_service.create_account(session, cipher, {"name": "Wallet", "type": "cash", "opening_balance": "9000.00"})
    bdo = account_service.create_account(session, cipher, {"name": "BDO", "type": "debit"})
    food = category_service.create_category(session, cipher, {"name": "Food"})
    groceries = category_service.create_category(session, cipher, {"name": "Groceries", "parent_id": food.id})
    household = category_service.create_category(session, cipher, {"name": "Household"})
    salary = category_service.create_category(session, cipher, {"name": "Salary", "kind": "income"})
    trip = tag_service.create_tag(session, cipher, {"name": "Trip"})
    return wallet.id, bdo.id, groceries.id, household.id, salary.id, trip.id


def ledger(session, cipher):
    wallet, bdo, groceries, household, salary, trip = books(session, cipher)
    transaction_service.create_transaction(session, cipher, {
        "type": "expense", "amount": "3500.00", "account_id": wallet, "txn_date": "2026-09-08",
        "merchant": "=SUM(A1)", "notes": "weekly, run", "tag_ids": [trip],
        "splits": [{"category_id": groceries, "amount": "2800.00", "note": "food"},
                   {"category_id": household, "amount": "700.00"}]})
    transaction_service.create_transaction(session, cipher, {
        "type": "income", "amount": "25000.00", "account_id": bdo, "category_id": salary, "txn_date": "2026-09-01"})
    transaction_service.create_transaction(session, cipher, {
        "type": "transfer", "amount": "1000.00", "account_id": bdo, "counter_account_id": wallet, "txn_date": "2026-09-02"})


def parsed(lines):
    return list(csv.DictReader(io.StringIO("".join(lines).lstrip("﻿"))))


def test_export_is_one_row_per_split(session, owner):
    ledger(session, owner)
    lines, count = import_export_service.export_csv(session, owner)
    rows = parsed(lines)
    assert lines[0].startswith("﻿txn_id,split_index,date")
    assert (count, len(rows)) == (3, 4)  # the transfer once, the split twice
    split = [r for r in rows if r["amount"] == "3500.00"]
    assert [(r["split_index"], r["split_amount"], r["category"], r["parent_category"]) for r in split] == [
        ("1", "2800.00", "Groceries", "Food"), ("2", "700.00", "Household", "")]
    assert len({r["txn_id"] for r in split}) == 1
    assert split[0]["merchant"] == "'=SUM(A1)"  # a spreadsheet would have run it
    transfer = next(r for r in rows if r["type"] == "transfer")
    assert (transfer["account"], transfer["counter_account"]) == ("BDO", "Wallet")


def test_an_export_reimports_identically(session, owner, another):
    ledger(session, owner)
    lines, _ = import_export_service.export_csv(session, owner)
    books(session, another)  # the same names, different ids

    preview = import_export_service.preview(session, another, "".join(lines))
    assert (preview.errors, preview.transactions, preview.ready, preview.duplicates) == ([], 3, 3, 0)
    assert import_export_service.run_import(session, another, "".join(lines)).created == 3

    again, _ = import_export_service.export_csv(session, another)
    strip = lambda rows: [{k: v for k, v in r.items() if k != "txn_id"} for r in rows]  # noqa: E731
    assert strip(parsed(again)) == strip(parsed(lines))


def test_preview_writes_nothing_and_finds_duplicates(session, owner):
    ledger(session, owner)
    lines, _ = import_export_service.export_csv(session, owner)
    count = TransactionRepository(session, owner).count()
    preview = import_export_service.preview(session, owner, "".join(lines))
    assert (preview.duplicates, preview.ready) == (3, 0)
    assert TransactionRepository(session, owner).count() == count
    assert import_export_service.run_import(session, owner, "".join(lines)).skipped_duplicates == 3


def test_a_bank_csv_through_a_mapping(session, owner):
    books(session, owner)
    text = "Posted,Description,Amount,Acct,Kind\n14/09/2026,Jollibee,-250.50,Wallet,Groceries\n15/09/2026,Payroll,\"25,000.00\",BDO,Salary\n"
    mapping = {"date": "Posted", "merchant": "Description", "amount": "Amount", "account": "Acct", "category": "Kind"}
    preview = import_export_service.preview(session, owner, text, mapping=mapping, date_format="DD/MM/YYYY")
    assert preview.errors == []
    assert [(e.type, str(e.amount), e.account) for e in preview.entries] == [
        ("expense", "250.50", "Wallet"), ("income", "25000.00", "BDO")]


def test_a_file_with_any_problem_imports_nothing(session, owner):
    books(session, owner)
    text = "date,amount,account,category,type\n2026-09-14,100.00,Wallet,Groceries,expense\n2026-09-14,50.00,Nowhere,Groceries,expense\n2026-13-01,5.00,Wallet,Pets,expense\n"
    preview = import_export_service.preview(session, owner, text)
    assert [(i.line, i.message) for i in preview.errors] == [
        (3, "No account called Nowhere"), (4, "Dates in this file should look like YYYY-MM-DD")]
    with pytest.raises(BusinessRuleException):
        import_export_service.run_import(session, owner, text)
    assert TransactionRepository(session, owner).count() == 0


def test_a_file_without_the_needed_columns_is_refused(session, owner):
    with pytest.raises(ValidationException):
        import_export_service.preview(session, owner, "when,what\n2026-09-14,coffee\n")


def test_csv_through_the_api(api):
    assert api.register().status_code == 201
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash"}).json()["id"]
    food = api.post("/categories", {"name": "Food"}).json()["id"]
    api.post("/transactions", {"type": "expense", "amount": "120.00", "account_id": wallet, "category_id": food,
                               "txn_date": "2026-09-14", "merchant": "Bakery"})
    response = api.get("/data/transactions.csv")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert "Bakery" in response.text and response.headers["x-transaction-count"] == "1"

    preview = api.post("/data/import/preview", {"csv": response.text})
    assert preview.status_code == 200, preview.text
    assert preview.json()["duplicates"] == 1
    result = api.post("/data/import", {"csv": response.text, "skip_duplicates": False})
    assert result.json() == {"created": 1, "skipped_duplicates": 0}


@pytest.fixture
def another(session):
    """A second user with a cipher - where an export is re-imported."""
    from app.core.crypto.dek import generate_dek
    from app.core.crypto.envelope import PLACEHOLDER
    from app.core.crypto.user_cipher import UserCipher
    from app.db.models import User
    from app.db.types import utcnow

    now = utcnow()
    user = User(email_bidx="b" * 64, password_hash="x", key_version=1, dek_wrapped=PLACEHOLDER,
                created_at=now, updated_at=now)
    session.add(user)
    session.flush()
    return UserCipher(user.id, generate_dek(), 1)
