"""
DAT-21 - importing the Budget phone app's .xlsx backup.

The workbook is built here, small and synthetic, in the same shape as that
app's export (sheet names, headers, UTC and local date columns, doubles as
text). What is worth proving: every kind of row lands as the right entry,
today's balances are exactly what was typed, a second import adds nothing,
and a file that is not that app's backup - or not plain XML - is refused.
"""

import base64
import io
import zipfile
from decimal import Decimal
from xml.sax.saxutils import escape

import pytest

from app.core.exceptions import ValidationException
from app.services import account_service, budget_app_import_service, category_service, transaction_service

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _letters(index: int) -> str:
    text = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        text = chr(65 + rest) + text
    return text


def xlsx(sheets, format_id="com.budget.portable-xlsx", extra=b""):
    """A minimal workbook with inline strings - enough for the importer, which reads cells, not formatting."""
    sheets = {"_Manifest": [["key", "value"], ["format_id", format_id], ["app_version", "1.16.2"],
                            ["exported_at_utc", "2026-09-15T07:41:39.542Z"]], **sheets}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        entries, rels = [], []
        for number, (name, rows) in enumerate(sheets.items(), start=1):
            entries.append(f'<sheet name="{escape(name)}" sheetId="{number}" r:id="rId{number}"/>')
            rels.append(f'<Relationship Id="rId{number}" Type="worksheet" Target="worksheets/sheet{number}.xml"/>')
            body = "".join(
                f'<row r="{r + 1}">' + "".join(
                    f'<c r="{_letters(c)}{r + 1}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
                    for c, value in enumerate(cells) if value != ""
                ) + "</row>"
                for r, cells in enumerate(rows)
            )
            archive.writestr(f"xl/worksheets/sheet{number}.xml",
                             extra + f'<worksheet xmlns="{MAIN}"><sheetData>{body}</sheetData></worksheet>'.encode())
        archive.writestr("xl/workbook.xml", f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>{"".join(entries)}</sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels",
                         f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{"".join(rels)}</Relationships>')
    return buffer.getvalue()


def table(header, *rows):
    return [header, *[[row.get(h, "") for h in header] for row in rows]]


ACCOUNTS = table(
    ["source_uid", "name", "account_type", "credit_limit", "in_assets", "statement_day", "bill_day", "status", "color_hex"],
    {"source_uid": "a-sea", "name": "Seabank", "account_type": "1", "in_assets": "1", "status": "0", "color_hex": "#FE9F5A"},
    {"source_uid": "a-card", "name": "Spaylater", "account_type": "0", "credit_limit": "85000", "in_assets": "1",
     "statement_day": "15", "bill_day": "5", "status": "0"},
    {"source_uid": "a-mp2", "name": "MP2", "account_type": "1", "in_assets": "0", "status": "0"},
)
CATEGORIES = table(
    ["source_uid", "name", "is_income", "status", "color_hex"],
    {"source_uid": "c-food", "name": "Food & Drink", "is_income": "0", "status": "0", "color_hex": "fecc5a"},
    {"source_uid": "c-salary", "name": "Salary", "is_income": "1", "status": "0"},
    {"source_uid": "c-old", "name": "Trade", "is_income": "0", "status": "1"},
)
SUBCATEGORIES = table(["source_uid", "category_id", "name"], {"source_uid": "s-groc", "category_id": "c-food", "name": "Groceries"})
RECORD_HEADER = ["Date", "Note", "source_uid", "record_type", "category_id", "category_name", "Category", "subcategory_id",
                 "account_id", "occurred_at_utc", "system_amount"]
RECORDS = table(
    RECORD_HEADER,
    {"Date": "2026-09-01", "Note": "weekly shop", "source_uid": "r1", "record_type": "expense", "category_id": "c-food",
     "Category": "Food & Drink", "subcategory_id": "s-groc", "account_id": "a-sea", "system_amount": "100"},
    {"Date": "2026-09-02", "source_uid": "r2", "record_type": "income", "category_id": "c-salary", "Category": "Salary",
     "account_id": "a-sea", "system_amount": "1000"},
    {"Date": "2026-09-03", "source_uid": "r3", "record_type": "expense", "category_id": "c-food", "Category": "Food & Drink",
     "account_id": "", "system_amount": "50"},
    {"Date": "2026-09-04", "source_uid": "r4", "record_type": "refund", "category_id": "c-food", "Category": "Food & Drink",
     "account_id": "a-sea", "system_amount": "20"},
    {"Date": "2026-09-05", "source_uid": "r5", "record_type": "expense", "category_id": "c-old", "Category": "Trade",
     "account_id": "a-card", "system_amount": "299.9999999999998"},
)
MOVES = table(
    ["From", "To", "Date", "Note", "source_uid", "entry_type", "counterpart_entry_id", "account_id", "counterpart_account_id",
     "is_income", "system_amount"],
    {"From": "Seabank", "To": "Spaylater", "Date": "2026-09-06", "source_uid": "t1-out", "entry_type": "transfer",
     "counterpart_entry_id": "t1-in", "account_id": "a-sea", "counterpart_account_id": "a-card", "is_income": "0", "system_amount": "200"},
    {"From": "Seabank", "To": "Spaylater", "Date": "2026-09-06", "source_uid": "t1-in", "entry_type": "transfer",
     "counterpart_entry_id": "t1-out", "account_id": "a-card", "counterpart_account_id": "a-sea", "is_income": "1", "system_amount": "200"},
    {"From": "Out Source", "To": "Seabank", "Date": "2026-09-07", "source_uid": "adj", "entry_type": "balance_adjustment",
     "account_id": "a-sea", "is_income": "1", "system_amount": "999"},
    {"From": "Seabank", "To": "MP2", "Date": "2026-09-08", "source_uid": "fee", "entry_type": "fee", "account_id": "a-sea",
     "is_income": "0", "system_amount": "10"},
)
LOANS = table(
    ["Borrow/Lend", "Counterparty", "Happening Date", "source_uid", "loan_type", "amount", "loan_date_utc", "account_id", "note"],
    {"Borrow/Lend": "Lend", "Counterparty": "Papa", "Happening Date": "Sep 01, 2026 at 09:00", "source_uid": "l-papa",
     "loan_type": "0", "amount": "100", "account_id": "a-sea"},
    {"Borrow/Lend": "Borrow", "Counterparty": "Mama", "Happening Date": "Aug 01, 2026 at 09:00", "source_uid": "l-mama",
     "loan_type": "1", "amount": "0"},
)
LOAN_RECORDS = table(
    ["Counterparty", "Type", "Date", "source_uid", "loan_id", "amount", "account_id", "occurred_at_utc", "note"],
    {"Counterparty": "Papa", "Type": "Receive", "Date": "Sep 10, 2026 at 10:38", "source_uid": "lr1", "loan_id": "l-papa",
     "amount": "50", "account_id": "a-sea"},
    {"Counterparty": "Mama", "Type": "Borrow", "Date": "Aug 02, 2026 at 08:32", "source_uid": "lr2", "loan_id": "l-mama",
     "amount": "500"},
    {"Counterparty": "Mama", "Type": "Pay", "Date": "Sep 11, 2026 at 01:17", "source_uid": "lr3", "loan_id": "l-mama",
     "amount": "200", "account_id": "a-sea"},
)
WORKBOOK = {"Records": RECORDS, "AccountTransactions": MOVES, "Accounts": ACCOUNTS, "Categories": CATEGORIES,
            "Subcategories": SUBCATEGORIES, "Loans": LOANS, "LoanRecords": LOAN_RECORDS}
BALANCES = {"a-sea": "5000.00", "a-card": "1234.50", "a-mp2": "0", "unassigned": "0",
            "loan:l-papa": "50.00", "loan:l-mama": "300.00"}


def balances_by_name(session, owner):
    views = account_service.list_accounts(session, owner, postings=transaction_service.postings(session, owner))
    return {v.name: v for v in views}


def test_the_preview_maps_every_sheet_and_writes_nothing(session, owner):
    found = budget_app_import_service.preview(session, owner, xlsx(WORKBOOK))
    accounts = {a.key: a for a in found.accounts}
    assert (accounts["a-card"].type, accounts["a-card"].owed) == ("credit", True)
    assert accounts["a-mp2"].type == "savings"
    assert accounts["unassigned"].name == "Unassigned (Budget App)"
    assert (accounts["loan:l-papa"].type, accounts["loan:l-papa"].suggested) == ("lent", Decimal("50.00"))
    assert (accounts["loan:l-mama"].type, accounts["loan:l-mama"].suggested) == ("borrowed", Decimal("300.00"))
    # Seabank: -100 +1000 +20 refund -200 transfer -10 fee -100 lent to Papa +50 back -200 paid to Mama
    assert accounts["a-sea"].history == Decimal("460.00")
    # 5 records + 1 transfer + 1 fee + Papa's loan + Papa's repayment + the payment to Mama
    assert (found.transactions, found.ready, found.duplicates) == (10, 10, 0)
    assert (found.adjustments_folded, found.loan_records_folded, found.unassigned) == (1, 1, 1)
    assert found.categories_new == 6  # Food & Drink, Groceries, Salary, Trade, Refunds, Fees
    assert account_service.list_accounts(session, owner) == []


def test_the_run_lands_every_entry_and_todays_balances_exactly(session, owner):
    result = budget_app_import_service.run_import(session, owner, xlsx(WORKBOOK), BALANCES)
    assert (result.accounts_created, result.categories_created, result.transactions) == (6, 6, 10)

    views = balances_by_name(session, owner)
    assert views["Seabank"].balance == Decimal("5000.00")
    assert views["Spaylater"].balance == Decimal("-1234.50")  # typed as owed
    assert views["Spaylater"].credit.limit == Decimal("85000.00")
    assert views["Papa"].balance == Decimal("50.00") and views["Papa"].type == "lent"
    assert views["Mama"].balance == Decimal("-300.00") and views["Mama"].type == "borrowed"
    assert views["MP2"].counts_in_cash_on_hand is False
    assert views["Seabank"].subtype == "bank"

    entries = transaction_service.views(session, owner)
    assert not any(v.type == "adjustment" for v in entries)  # ACC-29: only a balance edit writes one
    card = next(v for v in entries if v.account_id == views["Spaylater"].id and v.type == "expense")
    assert card.amount == Decimal("300.00")  # a double's tail, rounded - never float

    tree = {c.name: c for c in category_service.list_categories(session, owner)}
    assert tree["Trade"].archived is True
    assert [child.name for child in tree["Food & Drink"].children] == ["Groceries"]
    assert "Refunds" in tree and tree["Refunds"].kind == "income"


def test_a_second_import_adds_nothing(session, owner):
    budget_app_import_service.run_import(session, owner, xlsx(WORKBOOK), BALANCES)
    again = budget_app_import_service.preview(session, owner, xlsx(WORKBOOK))
    assert (again.ready, again.duplicates, again.categories_new) == (0, 10, 0)
    assert all(a.exists for a in again.accounts)
    result = budget_app_import_service.run_import(session, owner, xlsx(WORKBOOK), BALANCES)
    assert (result.accounts_created, result.transactions, result.skipped_duplicates) == (0, 0, 10)
    assert balances_by_name(session, owner)["Seabank"].balance == Decimal("5000.00")


def test_new_history_on_an_archived_category_or_settled_loan_still_imports(session, owner):
    """A later export adds a row to a category and a person already archived by the first import."""
    budget_app_import_service.run_import(session, owner, xlsx(WORKBOOK), BALANCES)
    later = dict(WORKBOOK)
    later["Records"] = RECORDS + [[{"Date": "2026-09-20", "source_uid": "r6", "record_type": "expense", "category_id": "c-old",
                                    "Category": "Trade", "account_id": "a-sea", "system_amount": "5"}.get(h, "")
                                   for h in RECORD_HEADER]]
    result = budget_app_import_service.run_import(session, owner, xlsx(later), BALANCES)
    assert (result.transactions, result.skipped_duplicates) == (1, 10)
    tree = {c.name: c for c in category_service.list_categories(session, owner)}
    assert tree["Trade"].archived is True  # closed again after the import
    assert balances_by_name(session, owner)["Seabank"].balance == Decimal("5000.00")


def test_every_account_needs_a_typed_balance(session, owner):
    with pytest.raises(ValidationException):
        budget_app_import_service.run_import(session, owner, xlsx(WORKBOOK), {"a-sea": "1.00"})
    assert account_service.list_accounts(session, owner) == []


@pytest.mark.security
def test_a_file_that_is_not_the_apps_backup_is_refused(session, owner):
    with pytest.raises(ValidationException):
        budget_app_import_service.preview(session, owner, b"not a zip at all")
    with pytest.raises(ValidationException):
        budget_app_import_service.preview(session, owner, xlsx(WORKBOOK, format_id="something.else"))


@pytest.mark.security
def test_xml_with_a_doctype_is_refused(session, owner):
    """Entity expansion needs a DOCTYPE; refusing one closes that door without a parser dependency."""
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'
    with pytest.raises(ValidationException):
        budget_app_import_service.preview(session, owner, xlsx(WORKBOOK, extra=bomb))


def test_the_endpoints_take_the_file_in_the_body(api):
    assert api.register().status_code == 201
    encoded = base64.b64encode(xlsx(WORKBOOK)).decode()
    preview = api.post("/data/import/budget-app/preview", {"file": encoded})
    assert preview.status_code == 200, preview.text
    assert preview.json()["ready"] == 10
    done = api.post("/data/import/budget-app", {"file": encoded, "balances": BALANCES})
    assert done.status_code == 200, done.text
    assert done.json()["transactions"] == 10
    broken = api.post("/data/import/budget-app/preview", {"file": "***"})
    assert broken.status_code == 422
