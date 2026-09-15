"""
Receipts (TXN-15, DAT-17, DAT-19): encrypted on disk, per user, bound to their
own id - and refused when they are not what their name says.
"""

import pytest

from app.core.config import settings
from app.core.crypto.errors import DecryptionError
from app.core.exceptions import NotFoundException, ValidationException
from app.db.repositories.attachment_repository import AttachmentRepository
from app.services import account_service, attachment_service, category_service, transaction_service

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"receipt pixels " * 100
PDF = b"%PDF-1.7\n" + b"statement " * 50


@pytest.fixture(autouse=True)
def uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    return tmp_path / "uploads"


@pytest.fixture
def purchase(session, owner):
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash"})
    food = category_service.create_category(session, owner, {"name": "Food"})
    return transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": "150.00", "account_id": wallet.id, "category_id": food.id}).transactions[0]


@pytest.mark.security
def test_a_receipt_is_encrypted_on_disk_under_the_users_folder(session, owner, purchase, uploads):
    view = attachment_service.attach(session, owner, purchase.id, "lunch.jpg", JPEG)
    path = uploads / str(owner.user_id) / f"{view.id}.enc"
    assert path.is_file()
    assert b"receipt pixels" not in path.read_bytes() and b"JFIF" not in path.read_bytes()
    assert attachment_service.read(session, owner, view.id)[1] == JPEG
    assert transaction_service.get_transaction(session, owner, purchase.id).attachment_id == view.id


@pytest.mark.security
def test_a_file_moved_to_another_receipts_name_does_not_open(session, owner, purchase, uploads):
    first = attachment_service.attach(session, owner, purchase.id, "a.jpg", JPEG)
    second = transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": "10.00", "account_id": purchase.account_id,
        "category_id": purchase.splits[0].category_id}).transactions[0]
    other = attachment_service.attach(session, owner, second.id, "b.pdf", PDF)
    folder = uploads / str(owner.user_id)
    (folder / f"{other.id}.enc").write_bytes((folder / f"{first.id}.enc").read_bytes())
    with pytest.raises(DecryptionError):
        attachment_service.read(session, owner, other.id)


@pytest.mark.parametrize("name, content", [
    ("receipt.jpg", PDF),  # the name says JPEG, the bytes say PDF
    ("receipt.exe", JPEG),
    ("receipt.jpg", b""),
])
def test_a_file_that_is_not_what_it_says_is_refused(session, owner, purchase, name, content):
    with pytest.raises(ValidationException):
        attachment_service.attach(session, owner, purchase.id, name, content)


def test_a_receipt_too_large_is_refused(session, owner, purchase, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE", 100)
    with pytest.raises(ValidationException):
        attachment_service.attach(session, owner, purchase.id, "big.jpg", JPEG)


def test_replacing_and_removing_leave_no_file_behind(session, owner, purchase, uploads):
    first = attachment_service.attach(session, owner, purchase.id, "a.jpg", JPEG)
    second = attachment_service.attach(session, owner, purchase.id, "b.pdf", PDF)
    folder = uploads / str(owner.user_id)
    assert sorted(p.name for p in folder.iterdir()) == [f"{second.id}.enc"]
    with pytest.raises(NotFoundException):
        attachment_service.read(session, owner, first.id)

    attachment_service.remove(session, owner, purchase.id)
    assert list(folder.iterdir()) == []
    assert transaction_service.get_transaction(session, owner, purchase.id).attachment_id is None


def test_receipts_through_the_api(api, uploads):
    assert api.register().status_code == 201
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash"}).json()["id"]
    food = api.post("/categories", {"name": "Food"}).json()["id"]
    txn = api.post("/transactions", {"type": "expense", "amount": "80.00", "account_id": wallet,
                                     "category_id": food}).json()["transactions"][0]["id"]

    made = api.post(f"/transactions/{txn}/attachment", content=JPEG, headers={"X-Filename": "coffee%20shop.jpg"})
    assert made.status_code == 201, made.text
    assert made.json()["filename"] == "coffee shop.jpg"
    got = api.get(f"/attachments/{made.json()['id']}")
    assert (got.status_code, got.content, got.headers["cache-control"]) == (200, JPEG, "no-store")
    assert api.delete(f"/transactions/{txn}/attachment").status_code == 204
    assert AttachmentRepository.raw_file(1, made.json()["id"]) is None
