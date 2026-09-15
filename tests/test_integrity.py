"""
The integrity check (Phase 9) - app/services/integrity_service.py and
scripts/verify_integrity.py. Finds a row that does not decrypt, a reference to
a row that is gone, a receipt without its file and a file without its receipt,
an account whose key will not open - and names ids, never values.
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select, update

from app.core.config import settings
from app.core.crypto.keyring import MasterKeyring, get_master_keyring
from app.db.models import Transaction, User
from app.db.repositories.transaction_repository import TransactionRepository
from app.db.repositories.user_repository import UserRepository
from app.services import integrity_service

ROOT = Path(__file__).resolve().parents[1]
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"pixels " * 50


@pytest.fixture(autouse=True)
def folders(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "TEMP_DIR", str(tmp_path / "temp"))
    return tmp_path


def some_data(api):
    api.register()
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "500.00"}).json()["id"]
    food = api.post("/categories", {"name": "Food"}).json()["id"]
    txn = api.post("/transactions", {"type": "expense", "amount": "10.00", "account_id": wallet,
                                     "category_id": food, "merchant": "Bakery"}).json()["transactions"][0]["id"]
    api.post(f"/transactions/{txn}/attachment", content=JPEG, headers={"X-Filename": "r.jpg"})
    attachment = api.get(f"/transactions/{txn}").json()["attachment_id"]
    return txn, attachment


def check(session, keyring=None):
    session.expire_all()
    return integrity_service.check_user(session, session.get(User, 1), keyring or get_master_keyring())


def point_transaction_at_a_missing_account(session, txn):
    cipher = UserRepository(session).cipher_for(session.get(User, 1), get_master_keyring())
    repo = TransactionRepository(session, cipher)
    repo.update(txn, {**repo.get(txn).data, "account_id": 999})
    session.commit()


def test_a_clean_account_is_ok(api, session):
    some_data(api)
    report = check(session)
    assert report.ok, report
    assert report.rows["transactions"] == 1 and report.rows["attachments"] == 1
    assert not report.stray_files and not report.to_deleted


def test_a_tampered_row_does_not_decrypt(api, session):
    txn, _ = some_data(api)
    payload = bytearray(session.execute(select(Transaction.payload).where(Transaction.id == txn)).scalar_one())
    payload[-1] ^= 1
    session.execute(update(Transaction).where(Transaction.id == txn).values(payload=bytes(payload)))
    session.commit()
    report = check(session)
    assert report.unreadable == {"transactions": [txn]} and not report.ok


def test_a_reference_to_a_row_that_is_gone_is_broken(api, session):
    txn, _ = some_data(api)
    point_transaction_at_a_missing_account(session, txn)
    report = check(session)
    assert report.broken == {"transactions.account_id": [txn]} and not report.ok


def test_receipt_files_missing_and_stray(api, session, folders):
    _, attachment = some_data(api)
    folder = folders / "uploads" / "1"
    (folder / f"{attachment}.enc").unlink()
    (folder / "leftover.enc.part").write_bytes(b"half a file")
    report = check(session)
    assert report.missing_files == [attachment] and report.stray_files == ["leftover.enc.part"]
    assert not report.ok


def test_an_account_whose_key_will_not_open(api, session):
    some_data(api)
    report = check(session, MasterKeyring(current_version=2, current_key=bytes(range(32))))
    assert report.key_ok is False and not report.ok


def test_the_script_names_ids_never_values(api, session):
    txn, _ = some_data(api)
    point_transaction_at_a_missing_account(session, txn)
    spec = importlib.util.spec_from_file_location("verify_integrity", ROOT / "scripts" / "verify_integrity.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = module.describe(check(session))
    assert "PROBLEMS" in text and f"transactions.account_id: {txn}" in text
    assert "Bakery" not in text and "Wallet" not in text and "500" not in text
