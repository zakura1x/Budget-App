"""
The full encrypted backup (DAT-06..DAT-17) - the test file that decides whether
the app has a backup or only a file.

The headline is DAT-14: export -> restore into an EMPTY account -> export
again -> the two are semantically identical. Row ids may differ; nothing else
may. Around it: a backup needs no key and leaks no value, a damaged file is
refused whole, a new database with the same .env restores it, a different
master key cannot, the app refuses another account's file, merge adds nothing
twice, and verify writes nothing.
"""

import zipfile
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.crypto.dek import generate_dek, wrap_dek
from app.core.crypto.envelope import PLACEHOLDER
from app.core.crypto.keyring import MasterKeyring, get_master_keyring
from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import BusinessRuleException, ConflictException
from app.db.models import ENCRYPTED_TABLES, User
from app.db.types import utcnow
from app.services import (
    account_service,
    attachment_service,
    category_service,
    preferences_service,
    recurring_service,
    tag_service,
    transaction_service,
)
from app.services.backup_service import bundle, references, restore_service
from app.services.backup_service.bundle import BackupFormatError
from app.services.backup_service.references import ORDER
from app.services.backup_service.restore_service import snapshot
from app.services.backup_service.scheduler import BackupScheduler
from app.services.budget_service import budget_service
from tests.conftest import make_sqlite_engine

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + bytes(range(256)) * 4


@pytest.fixture(autouse=True)
def folders(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setattr(settings, "BACKUP_OFFSITE_DIR", "")
    return tmp_path


def make_user(session, email, keyring=None):
    """A real user with a wrapped DEK - what a backup has to carry to stand alone."""
    keyring = keyring or get_master_keyring()
    dek = generate_dek()
    now = utcnow()
    user = User(email_bidx=email.ljust(64, "x")[:64], password_hash="x", key_version=keyring.current_version,
                dek_wrapped=PLACEHOLDER, created_at=now, updated_at=now)
    session.add(user)
    session.flush()
    user.dek_wrapped = wrap_dek(dek, keyring, user.id)
    session.commit()
    return user, UserCipher(user.id, dek, keyring.current_version)


def fill(session, cipher):
    """Something of every kind, with every kind of reference between them."""
    today = date(2026, 9, 14)
    wallet = account_service.create_account(session, cipher, {"name": "Wallet", "type": "cash", "opening_balance": "9000.00"})
    card = account_service.create_account(session, cipher, {"name": "Card", "type": "credit",
                                                            "statement_closing_day": 16, "payment_due_day": 6})
    food = category_service.create_category(session, cipher, {"name": "Food"})
    groceries = category_service.create_category(session, cipher, {"name": "Groceries", "parent_id": food.id})
    coffee = category_service.create_category(session, cipher, {"name": "Coffee", "parent_id": food.id})
    gadgets = category_service.create_category(session, cipher, {"name": "Gadgets"})
    interest = category_service.create_category(session, cipher, {"name": "Interest"})
    salary = category_service.create_category(session, cipher, {"name": "Salary", "kind": "income"})
    trip = tag_service.create_tag(session, cipher, {"name": "Trip"})
    budget_service.create_budget(session, cipher, {"period": "monthly", "amount": "30000.00",
                                                   "allocations": [{"category_id": food.id, "amount": "8000.00"}]},
                                 today=today)
    preferences_service.update_preferences(session, cipher, {"carry_over": True})
    split = transaction_service.create_transaction(session, cipher, {
        "type": "expense", "amount": "3500.00", "account_id": wallet.id, "txn_date": "2026-09-08",
        "merchant": "SM Supermarket", "tag_ids": [trip.id],
        "splits": [{"category_id": groceries.id, "amount": "2800.00"}, {"category_id": coffee.id, "amount": "700.00"}],
    }).transactions[0]
    transaction_service.create_transaction(session, cipher, {
        "type": "transfer", "amount": "1000.00", "account_id": wallet.id, "counter_account_id": card.id,
        "txn_date": "2026-09-09"})
    transaction_service.create_transaction(session, cipher, {
        "type": "income", "amount": "25000.00", "account_id": wallet.id, "category_id": salary.id, "txn_date": "2026-09-01"})
    doomed = transaction_service.create_transaction(session, cipher, {
        "type": "expense", "amount": "50.00", "account_id": wallet.id, "category_id": coffee.id,
        "txn_date": "2026-09-10"}).transactions[0]
    transaction_service.delete_transaction(session, cipher, doomed.id)
    recurring_service.create_rule(session, cipher, {
        "kind": "standard", "type": "expense", "name": "Rent", "account_id": wallet.id, "category_id": food.id,
        "frequency": "monthly", "start": "2026-09-14", "amount": "1200.00", "tag_ids": [trip.id]}, today=today)
    recurring_service.create_rule(session, cipher, {
        "kind": "subscription", "type": "expense", "name": "Netflix", "account_id": card.id, "category_id": gadgets.id,
        "frequency": "monthly", "start": "2026-10-05", "amount": "549.00", "reminder_days": 2}, today=today)
    recurring_service.create_rule(session, cipher, {
        "kind": "installment", "name": "Phone", "account_id": card.id, "category_id": gadgets.id,
        "interest_category_id": interest.id, "frequency": "monthly", "start": "2026-09-14", "price": "40000.00",
        "payments": 6, "interest": "2400.00"}, today=today)
    account_service.record_statement_check(session, cipher, card.id, date(2026, 8, 16), "0.00", today=today)
    attachment_service.attach(session, cipher, split.id, "receipt.jpg", JPEG)


def decrypted(found, cipher):
    return {t: [(raw.id, raw.is_deleted, cipher.open(t, raw.id, raw.payload, raw.key_version))
                for raw in found.tables[t]] for t in ORDER}


def backup_of(session, user_id, folder):
    info = bundle.write_backup(session, user_id, directory=folder)
    return bundle.read_bundle(folder / info.name), folder / info.name


# ------------------------------------------------------------- the reference map


def test_the_insert_order_covers_every_encrypted_table():
    """A new table missing from ORDER would restore broken - this is the tripwire (§12.3)."""
    assert set(ORDER) == set(ENCRYPTED_TABLES) and len(ORDER) == len(ENCRYPTED_TABLES)
    for table, refs in references.REFERENCES.items():
        assert table in ORDER
        assert all(target in ORDER for _, target in refs)


def test_references_rewrite_lists_and_nested_fields():
    data = {"account_id": 1, "tag_ids": [7, 8], "splits": [{"category_id": 3, "amount": "1.00"}], "pair_id": None}
    maps = {"accounts": {1: 101}, "tags": {7: 107, 8: 108}, "categories": {3: 103}}
    out, missing = references.apply("transactions", data, maps, references.refs("transactions"))
    assert (out["account_id"], out["tag_ids"], out["splits"][0]["category_id"], missing) == (101, [107, 108], 103, [])
    assert data["account_id"] == 1  # the original is untouched
    _, missing = references.apply("transactions", {"account_id": 9}, maps, references.refs("transactions"))
    assert missing == ["transactions.account_id"]


# ------------------------------------------------------------------ the file


@pytest.mark.security
def test_writing_a_backup_needs_no_key_and_leaks_no_value(session, folders):
    user, cipher = make_user(session, "alice")
    fill(session, cipher)
    info = bundle.write_backup(session, user.id, directory=folders / "out")  # no cipher anywhere
    raw = (folders / "out" / info.name).read_bytes()
    with zipfile.ZipFile(folders / "out" / info.name) as archive:
        everything = b"".join(archive.read(name) for name in archive.namelist())
    for secret in (b"SM Supermarket", b"3500.00", b"Wallet", b"Groceries", b"JFIF"):
        assert secret not in everything and secret not in raw
    assert info.rows > 20 and info.attachments == 1


def test_a_damaged_backup_is_refused_whole(session, folders):
    user, cipher = make_user(session, "alice")
    fill(session, cipher)
    _, path = backup_of(session, user.id, folders / "out")
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries["transactions.enc"] = entries["transactions.enc"].replace(b'"is_deleted": false', b'"is_deleted": true', 1)
    tampered = folders / "tampered.budgetbak"
    with zipfile.ZipFile(tampered, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    with pytest.raises(BackupFormatError):
        bundle.read_bundle(tampered)
    with pytest.raises(BackupFormatError):
        bundle.read_bundle(b"not a zip at all")


# --------------------------------------------------------------- DAT-14


def test_round_trip_into_an_empty_account_is_identical(session, folders):
    alice, alice_cipher = make_user(session, "alice")
    fill(session, alice_cipher)
    first, _ = backup_of(session, alice.id, folders / "one")

    bob, bob_cipher = make_user(session, "bob")
    source = restore_service.unlock_source(first, keyring=get_master_keyring())
    report = restore_service.restore(session, first, bob_cipher, source, mode="fresh")
    assert report.ok and report.attachments == 1

    second, _ = backup_of(session, bob.id, folders / "two")
    assert snapshot(decrypted(second, bob_cipher)) == snapshot(decrypted(first, alice_cipher))

    # And the restored references really point at Bob's rows: each rule posts to his own accounts -
    # rent on 14 Oct, Netflix on 5 Oct, the phone's second payment on 14 Oct.
    posted = recurring_service.expand(session, bob_cipher, today=date(2026, 10, 14))
    assert posted.posted == 3 and posted.needs_attention == ()
    accounts = {a.name: a.id for a in account_service.list_accounts(session, bob_cipher)}
    rules = {r.name: r for r in recurring_service.list_rules(session, bob_cipher, today=date(2026, 10, 14))}
    views = transaction_service.views(session, bob_cipher)
    for name, account in (("Rent", "Wallet"), ("Netflix", "Card"), ("Phone", "Card")):
        mine = [v for v in views if v.recurring_id == rules[name].id and v.recurring_on is not None]
        assert mine and all(v.account_id == accounts[account] for v in mine), name
    receipt = next(v for v in transaction_service.views(session, bob_cipher) if v.attachment_id)
    assert attachment_service.read(session, bob_cipher, receipt.attachment_id)[1] == JPEG


@pytest.mark.security
def test_a_new_database_with_the_same_env_restores_the_backup(session, folders):
    """DAT-16: a new server, an empty database, the offline .env copy, and scripts/restore.py (no owner)."""
    alice, alice_cipher = make_user(session, "alice")
    fill(session, alice_cipher)
    first, path = backup_of(session, alice.id, folders / "one")

    engine = make_sqlite_engine()
    try:
        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as fresh_db:
            newcomer, new_cipher = make_user(fresh_db, "alice-again")
            found = bundle.read_bundle(path)
            source = restore_service.unlock_source(found, keyring=get_master_keyring())
            report = restore_service.restore(fresh_db, found, new_cipher, source, mode="fresh")
            assert report.ok
            again, _ = backup_of(fresh_db, newcomer.id, folders / "two")
            assert snapshot(decrypted(again, new_cipher)) == snapshot(decrypted(first, alice_cipher))
    finally:
        engine.dispose()


@pytest.mark.security
def test_a_different_master_key_cannot_open_the_backup(session, folders):
    alice, alice_cipher = make_user(session, "alice")
    fill(session, alice_cipher)
    found, _ = backup_of(session, alice.id, folders / "one")
    stranger = MasterKeyring(current_version=1, current_key=bytes(range(32)))
    with pytest.raises(BusinessRuleException):
        restore_service.unlock_source(found, keyring=stranger)


@pytest.mark.security
def test_the_app_refuses_someone_elses_backup(session, folders):
    alice, alice_cipher = make_user(session, "alice")
    fill(session, alice_cipher)
    found, _ = backup_of(session, alice.id, folders / "one")
    bob, _ = make_user(session, "bob")
    with pytest.raises(BusinessRuleException) as refused:
        restore_service.unlock_source(found, keyring=get_master_keyring(), owner=(bob.id, bob.email_bidx))
    assert refused.value.extra.get("other_account") is True
    assert restore_service.unlock_source(found, keyring=get_master_keyring(), owner=(alice.id, alice.email_bidx))


# ---------------------------------------------------------------- modes


def test_fresh_needs_an_empty_account(session, folders):
    alice, alice_cipher = make_user(session, "alice")
    fill(session, alice_cipher)
    found, _ = backup_of(session, alice.id, folders / "one")
    source = restore_service.unlock_source(found, keyring=get_master_keyring())
    with pytest.raises(ConflictException):
        restore_service.restore(session, found, alice_cipher, source, mode="fresh")


def test_merge_twice_adds_nothing_the_second_time(session, folders):
    alice, alice_cipher = make_user(session, "alice")
    fill(session, alice_cipher)
    found, _ = backup_of(session, alice.id, folders / "one")
    bob, bob_cipher = make_user(session, "bob")
    source = restore_service.unlock_source(found, keyring=get_master_keyring())

    restore_service.restore(session, found, bob_cipher, source, mode="merge")
    counted = {t: len(bundle.BackupRepository(session).raw_rows(t, bob.id)) for t in ORDER}
    again = restore_service.restore(session, found, bob_cipher, source, mode="merge")
    assert all(t.restored == 0 for t in again.tables)
    assert {t: len(bundle.BackupRepository(session).raw_rows(t, bob.id)) for t in ORDER} == counted


def test_verify_writes_nothing_and_reports_what_changed_since(session, folders):
    alice, alice_cipher = make_user(session, "alice")
    fill(session, alice_cipher)
    found, _ = backup_of(session, alice.id, folders / "one")
    source = restore_service.unlock_source(found, keyring=get_master_keyring())

    before = {t: len(bundle.BackupRepository(session).raw_rows(t, alice.id)) for t in ORDER}
    clean = restore_service.restore(session, found, alice_cipher, source, mode="verify")
    assert (clean.ok, clean.differences, clean.unresolved) == (True, [], [])
    assert {t: len(bundle.BackupRepository(session).raw_rows(t, alice.id)) for t in ORDER} == before

    wallet = account_service.list_accounts(session, alice_cipher)[0]
    food = category_service.list_categories(session, alice_cipher)[0]
    transaction_service.create_transaction(session, alice_cipher, {
        "type": "expense", "amount": "99.00", "account_id": wallet.id, "category_id": food.id, "txn_date": "2026-09-14"})
    changed = restore_service.restore(session, found, alice_cipher, source, mode="verify")
    assert [(d.table, d.only_in_backup, d.only_in_live) for d in changed.differences] == [("transactions", 0, 1)]


# ------------------------------------------------------------- keeping them


def test_old_backups_are_pruned_but_the_newest_three_stay(session, folders):
    user, cipher = make_user(session, "alice")
    folder = folders / "prune"
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    for days_ago in (400, 300, 200, 100, 1):
        bundle.write_backup(session, user.id, directory=folder, now=now - timedelta(days=days_ago))
    names = sorted(p.name for p in folder.iterdir())
    assert len(names) == 3  # 1, 100 and 200 days old: the newest three, whatever their age
    assert bundle.latest_backup_at(user.id, folder) == now - timedelta(days=1)


class FakeTimer:
    started = []

    def __init__(self, delay, function, args=()):
        self.delay, self.function, self.args, self.cancelled, self.daemon = delay, function, args, False, False

    def start(self):
        FakeTimer.started.append(self)

    def cancel(self):
        self.cancelled = True


def test_automatic_backup_follows_changes_and_sign_in(session, folders):
    written = []
    FakeTimer.started = []
    latest = {}
    scheduler = BackupScheduler(enabled=True, debounce_seconds=300, interval_hours=24, writer=written.append,
                                latest=lambda uid: latest.get(uid), timer_factory=FakeTimer)
    scheduler.note_change(7)
    scheduler.note_change(7)  # a burst of edits: one backup, pushed back
    assert [t.cancelled for t in FakeTimer.started] == [True, False] and scheduler.pending() == {7}
    FakeTimer.started[-1].function(*FakeTimer.started[-1].args)
    assert written == [7] and scheduler.pending() == set()

    latest[8] = datetime.now(timezone.utc) - timedelta(hours=2)
    scheduler.on_sign_in(8)
    assert scheduler.pending() == set()  # a recent backup: nothing to do
    latest[8] = datetime.now(timezone.utc) - timedelta(hours=30)
    scheduler.on_sign_in(8)
    assert scheduler.pending() == {8} and FakeTimer.started[-1].delay < 60

    off = BackupScheduler(enabled=False, debounce_seconds=300, interval_hours=24, writer=written.append,
                          latest=lambda uid: None, timer_factory=FakeTimer)
    off.note_change(9)
    off.on_sign_in(9)
    assert off.pending() == set()


def test_a_commit_that_changed_data_schedules_a_backup(session, owner, monkeypatch):
    from app.services.backup_service import scheduler as scheduler_module

    noted = []
    fake = BackupScheduler(enabled=True, debounce_seconds=300, interval_hours=24, writer=lambda uid: None,
                           latest=lambda uid: None, timer_factory=FakeTimer)
    monkeypatch.setattr(fake, "note_change", noted.append)
    scheduler_module.set_scheduler(fake)
    try:
        account_service.create_account(session, owner, {"name": "Wallet", "type": "cash"})
        assert noted == [owner.user_id]
    finally:
        scheduler_module.set_scheduler(None)


# ------------------------------------------------------------------ the API


def test_backups_through_the_api(api, folders):
    assert api.register().status_code == 201
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "100.00"}).json()["id"]
    assert wallet

    made = api.post("/backups")
    assert made.status_code == 201, made.text
    name = made.json()["name"]
    listed = api.get("/backups").json()
    assert [b["name"] for b in listed["backups"]] == [name] and listed["automatic"] is False

    download = api.get(f"/backups/{name}/download")
    assert download.status_code == 200 and download.content[:2] == b"PK"

    uploaded = api.post("/backups/upload", content=download.content)
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["same_account"] is True

    report = api.post("/backups/restore", {"upload_id": uploaded.json()["upload_id"], "mode": "verify"})
    assert report.status_code == 200, report.text
    assert (report.json()["ok"], report.json()["differences"]) == (True, [])
    assert api.post("/backups/restore", {"name": name, "mode": "fresh"}).json()["code"] == "CONFLICT"
    assert api.get("/backups/../../etc/download").status_code == 404
