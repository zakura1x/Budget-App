"""
Phase 14 - checking, reviewing and securing (misc/ROADMAP.md).

  ACC-41  a debit or savings account checked against the bank for a day: the
          difference is derived, and a forgotten transaction or a balance
          adjustment through the ONE existing path answers it
  STA-12  the monthly review of a finished period, and Home's offer of it
  SEC-32  open sessions with a device label, ending one or all the others,
          and recent sign-ins that say "same network" without an IP
  SEC-12  a passkey unlocks the lock screen through the PIN's own path: a
          fake authenticator signs real WebAuthn answers, and every way a
          wrong one could slip through is tried
"""

import base64
import hashlib
import json
import os
import struct
from datetime import date, timedelta
from decimal import Decimal as D

from urllib.parse import urlparse

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from app.core.config import settings
from app.core.exceptions import BusinessRuleException, ValidationException
from app.core.utils.user_agent import device_label
from app.db.models import RefreshToken, User
from app.services import (
    account_service,
    category_service,
    preferences_service,
    recurring_service,
    stats_service,
    transaction_service,
)
from app.services.auth_service.passkey_service import _cbor
from app.services.budget_service import budget_service

TODAY = date(2026, 9, 28)
RP_ID = urlparse(settings.APP_PUBLIC_URL).hostname
PASSWORD = "Correct-Horse-9!"
ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36"


# ------------------------------------------------------------------ ACC-41


@pytest.fixture
def books(session, owner):
    bank = account_service.create_account(session, owner, {"name": "BDO", "type": "debit",
                                                           "opening_balance": "10000.00"})
    card = account_service.create_account(session, owner, {"name": "BPI", "type": "credit",
                                                           "statement_closing_day": 20, "payment_due_day": 5})
    food = category_service.create_category(session, owner, {"name": "Food"})
    fun = category_service.create_category(session, owner, {"name": "Fun"})
    salary = category_service.create_category(session, owner, {"name": "Salary", "kind": "income"})

    class B:
        pass

    b = B()
    b.bank, b.card, b.food, b.fun, b.salary = bank.id, card.id, food.id, fun.id, salary.id
    return b


def spend(session, owner, books, amount, on, category=None, merchant=None):
    return transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": amount, "account_id": books.bank, "category_id": category or books.food,
        "txn_date": on, "merchant": merchant}).transactions[0]


def account(session, owner, books, today=TODAY):
    return account_service.get_account(session, owner, books.bank,
                                       postings=transaction_service.postings(session, owner), today=today)


def test_a_matching_balance_is_checked(session, owner, books):
    spend(session, owner, books, "1000.00", "2026-09-20")
    spend(session, owner, books, "500.00", "2026-09-27")  # after the day checked - not in it
    account_service.check_balance(session, owner, books.bank, date(2026, 9, 25), "9000.00", today=TODAY)
    check = account(session, owner, books).balance_check
    assert (check.bank, check.app, check.difference, check.checked, check.stale) == (
        D("9000.00"), D("9000.00"), D("0.00"), True, False)


def test_a_forgotten_transaction_answers_the_difference(session, owner, books):
    account_service.check_balance(session, owner, books.bank, date(2026, 9, 25), "9650.00", today=TODAY)
    check = account(session, owner, books).balance_check
    assert (check.difference, check.checked) == (D("-350.00"), False)
    spend(session, owner, books, "350.00", "2026-09-24")
    assert account(session, owner, books).balance_check.checked


def test_a_balance_adjustment_through_the_one_path_answers_it(session, owner, books):
    account_service.check_balance(session, owner, books.bank, date(2026, 9, 20), "9800.00", today=TODAY)
    view = account(session, owner, books)
    # The Adjust button sends today's balance plus the difference - ACC-28's own question.
    with pytest.raises(Exception) as asked:
        account_service.update_account(session, owner, books.bank, {"name": "BDO", "type": "debit",
                                                                    "balance": str(view.balance - D("200.00"))},
                                       postings=transaction_service.postings(session, owner), today=TODAY)
    assert asked.value.code == "BALANCE_DIFFERS"
    account_service.update_account(session, owner, books.bank, {
        "name": "BDO", "type": "debit", "balance": str(view.balance - D("200.00")), "balance_action": "adjust"},
        postings=transaction_service.postings(session, owner), today=TODAY)
    check = account(session, owner, books).balance_check
    assert (check.adjusted, check.difference, check.checked) == (D("-200.00"), D("0.00"), True)


def test_one_check_a_day_and_it_survives_an_edit(session, owner, books):
    account_service.check_balance(session, owner, books.bank, date(2026, 9, 25), "1.00", today=TODAY)
    account_service.check_balance(session, owner, books.bank, date(2026, 9, 25), "10000.00", today=TODAY)
    account_service.update_account(session, owner, books.bank, {"name": "BDO Savings", "type": "debit"}, today=TODAY)
    view = account(session, owner, books)
    assert view.balance_check.checked and view.name == "BDO Savings"
    stored = account_service.AccountRepository(session, owner).get(books.bank).data["balance_checks"]
    assert len(stored) == 1 and set(stored[0]) == {"on", "bank", "at"}  # the bank's figure only, never the difference


def test_an_old_check_goes_stale(session, owner, books):
    account_service.check_balance(session, owner, books.bank, date(2026, 8, 1), "10000.00", today=TODAY)
    assert account(session, owner, books).balance_check.stale


def test_what_cannot_be_checked(session, owner, books):
    with pytest.raises(BusinessRuleException):
        account_service.check_balance(session, owner, books.card, TODAY, "0.00", today=TODAY)  # a card has ACC-24
    with pytest.raises(ValidationException):
        account_service.check_balance(session, owner, books.bank, TODAY + timedelta(days=1), "0.00", today=TODAY)
    assert account_service.get_account(session, owner, books.card, today=TODAY).balance_check is None


# ------------------------------------------------------------------ STA-12


def test_a_month_reviewed_without_a_budget(session, owner, books):
    spend(session, owner, books, "3000.00", "2026-07-10", books.fun)  # July: fun
    spend(session, owner, books, "1000.00", "2026-07-11")
    spend(session, owner, books, "2500.00", "2026-08-03", merchant="SM")  # August: food only
    spend(session, owner, books, "400.00", "2026-08-09")
    spend(session, owner, books, "100.00", "2026-08-30")
    spend(session, owner, books, "50.00", "2026-08-31")
    transaction_service.create_transaction(session, owner, {
        "type": "income", "amount": "30000.00", "account_id": books.bank, "category_id": books.salary,
        "txn_date": "2026-08-15"})
    spend(session, owner, books, "999.00", "2026-09-02")  # September is not in it

    review = stats_service.review(session, owner, today=TODAY)
    assert (review.period.start, review.period.end, review.period.span) == (date(2026, 8, 1), date(2026, 8, 31), "month")
    assert (review.spent, review.earned, review.net, review.previous_spent) == (
        D("3050.00"), D("30000.00"), D("26950.00"), D("4000.00"))
    assert review.budget is None
    changes = {c.category_id: c.change for c in review.changes}
    assert changes == {books.fun: D("-3000.00"), books.food: D("2050.00")}  # a category that stopped counts too
    assert [p.amount for p in review.purchases] == [D("2500.00"), D("400.00"), D("100.00")]
    assert review.purchases[0].merchant == "SM"
    # Cash on hand the day before August and at its end: 10,000 - 4,000, then + 30,000 - 3,050
    assert (review.cash_start, review.cash_end) == (D("6000.00"), D("32950.00"))


def test_plans_that_started_and_prices_that_changed(session, owner, books):
    rule = recurring_service.create_rule(session, owner, {
        "kind": "subscription", "type": "expense", "name": "Netflix", "account_id": books.bank,
        "category_id": books.fun, "frequency": "monthly", "amount": "549.00", "start": "2026-08-10"},
        today=date(2026, 8, 1))
    recurring_service.update_rule(session, owner, rule.id, {
        "kind": "subscription", "type": "expense", "name": "Netflix", "account_id": books.bank,
        "category_id": books.fun, "frequency": "monthly", "amount": "649.00", "start": "2026-08-10",
        "amount_from": "2026-08-20"}, today=date(2026, 8, 20))
    events = {(e.name, e.event, e.on): e for e in stats_service.review(session, owner, today=TODAY).plans}
    assert set(events) == {("Netflix", "started", date(2026, 8, 10)), ("Netflix", "price", date(2026, 8, 20))}
    price = events[("Netflix", "price", date(2026, 8, 20))]
    assert (price.previous_amount, price.amount) == (D("549.00"), D("649.00"))


def test_the_current_period_has_nothing_to_review(session, owner, books):
    with pytest.raises(ValidationException):
        stats_service.review(session, owner, today=TODAY, on=TODAY)


def test_a_budget_period_is_reviewed_with_its_result(session, owner, books):
    budget_service.create_budget(session, owner, {"period": "monthly", "month_start_day": 26, "amount": "5000.00"},
                                 today=date(2026, 7, 26))
    spend(session, owner, books, "6000.00", "2026-09-01")
    review = stats_service.review(session, owner, today=TODAY)
    assert (review.period.start, review.period.end, review.period.span) == (date(2026, 8, 26), date(2026, 9, 25), "budget")
    assert (review.budget.spent, review.budget.remaining) == (D("6000.00"), D("-1000.00"))


def test_a_period_from_before_the_budget_has_no_result(session, owner, books):
    budget_service.create_budget(session, owner, {"period": "monthly", "month_start_day": 26, "amount": "5000.00"},
                                 today=TODAY)  # starts with the period 26 Sep - 25 Oct
    review = stats_service.review(session, owner, today=TODAY)
    assert (review.period.start, review.period.span, review.budget) == (date(2026, 8, 26), "budget", None)


def test_home_offers_it_in_the_first_days_until_not_now(session, owner, books):
    prefs = preferences_service.get_preferences(session, owner)
    assert stats_service.review_offer(session, owner, today=date(2026, 9, 3), prefs=prefs).start == date(2026, 8, 1)
    assert stats_service.review_offer(session, owner, today=date(2026, 9, 6), prefs=prefs) is None  # too late
    preferences_service.update_preferences(session, owner, {"review_dismissed_for": "2026-08-01"})
    prefs = preferences_service.get_preferences(session, owner)
    assert stats_service.review_offer(session, owner, today=date(2026, 9, 3), prefs=prefs) is None
    assert stats_service.review_offer(session, owner, today=date(2026, 10, 1), prefs=prefs).start == date(2026, 9, 1)


# ------------------------------------------------------------------ SEC-32


@pytest.mark.parametrize("ua, label", [
    (ANDROID, "Chrome on Android"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
     "Mobile/15E148 Safari/604.1", "Safari on iPhone"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36 "
     "Edg/129.0", "Edge on Windows"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:130.0) Gecko/20100101 Firefox/130.0", "Firefox on Mac"),
    ("curl/8.4.0", "Browser on a device"),
    ("", None),
])
def test_a_device_is_a_coarse_label(ua, label):
    assert device_label(ua) == label


def signed_up(api):
    response = api.register()
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.security
def test_sessions_are_listed_with_their_device_and_can_be_ended(api, engine):
    signed_up(api)  # the first session - the test client's own UA
    assert api.post("/auth/login", {"email": "noah@example.com", "password": PASSWORD},
                    headers={"User-Agent": ANDROID}).status_code == 200
    body = api.get("/auth/activity").json()
    assert [s["current"] for s in body["sessions"]] == [True, False]
    this, other = body["sessions"]
    assert this["device"] == "Chrome on Android"
    # a handle, never the session id the keyring is keyed by
    assert isinstance(other["id"], int)

    refused = api.post(f"/auth/sessions/{this['id']}/end")
    assert refused.status_code == 400  # this device signs out instead
    assert api.post(f"/auth/sessions/{other['id']}/end").status_code == 204
    assert len(api.get("/auth/activity").json()["sessions"]) == 1
    from sqlalchemy.orm import Session as S

    with S(engine) as db:
        reasons = {r.revoke_reason for r in db.execute(select(RefreshToken)).scalars() if r.revoked_at}
    assert reasons == {"user"}


@pytest.mark.security
def test_sign_out_everywhere_else_keeps_this_one(api):
    signed_up(api)
    api.post("/auth/login", {"email": "noah@example.com", "password": PASSWORD})
    api.post("/auth/login", {"email": "noah@example.com", "password": PASSWORD})
    assert api.post("/auth/sessions/end-others").json()["ended"] == 2
    assert api.get("/settings/preferences").status_code == 200  # still signed in here
    assert len(api.get("/auth/activity").json()["sessions"]) == 1


@pytest.mark.security
def test_recent_sign_ins_say_same_network_never_an_ip(api):
    signed_up(api)
    api.post("/auth/login", {"email": "noah@example.com", "password": "Wrong-Password-1!"})
    api.post("/auth/login", {"email": "noah@example.com", "password": PASSWORD})
    sign_ins = api.get("/auth/activity").json()["sign_ins"]
    assert [(s["kind"], s["success"], s["same_network"]) for s in sign_ins[:2]] == [
        ("login", True, True), ("login", False, True)]
    assert all(set(s) == {"at", "kind", "success", "same_network"} for s in sign_ins)


# ------------------------------------------------------------------ SEC-12


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _cbor_encode(value):
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | info]) + n.to_bytes(size, "big")
    if isinstance(value, bool):
        return bytes([0xF5 if value else 0xF4])
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        return head(3, len(value.encode())) + value.encode()
    if isinstance(value, list):
        return head(4, len(value)) + b"".join(_cbor_encode(v) for v in value)
    if isinstance(value, dict):
        return head(5, len(value)) + b"".join(_cbor_encode(k) + _cbor_encode(v) for k, v in value.items())
    raise TypeError(value)


class Authenticator:
    """A platform authenticator in miniature: one P-256 key, signing like a phone would."""

    def __init__(self, origin=None):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential = os.urandom(32)
        self.count = 0
        self.origin = origin or settings.APP_PUBLIC_URL
        self.rp_hash = hashlib.sha256(RP_ID.encode()).digest()

    def create(self, options):
        client = json.dumps({"type": "webauthn.create", "challenge": options["challenge"], "origin": self.origin}).encode()
        nums = self.key.public_key().public_numbers()
        cose = {1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")}
        auth = (self.rp_hash + bytes([0x45]) + struct.pack(">I", self.count) + bytes(16)
                + struct.pack(">H", len(self.credential)) + self.credential + _cbor_encode(cose))
        attestation = _cbor_encode({"fmt": "none", "attStmt": {}, "authData": auth})
        return {"client_data_json": _b64(client), "attestation_object": _b64(attestation)}

    def get(self, options, *, flags=0x05, kind="webauthn.get", origin=None, count=None, key=None):
        self.count = self.count + 1 if count is None else count
        client = json.dumps({"type": kind, "challenge": options["challenge"], "origin": origin or self.origin}).encode()
        auth = self.rp_hash + bytes([flags]) + struct.pack(">I", self.count)
        signature = (key or self.key).sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return {"credential_id": _b64(self.credential), "client_data_json": _b64(client),
                "authenticator_data": _b64(auth), "signature": _b64(signature)}


@pytest.fixture
def passkeys_on(monkeypatch):
    monkeypatch.setattr(settings, "BIOMETRIC_WEBAUTHN_ENABLED", True)


def with_passkey(api):
    signed_up(api)
    device = Authenticator()
    options = api.post("/auth/passkeys/options", {"password": PASSWORD}).json()
    assert options["rp"]["id"] == RP_ID and options["authenticatorSelection"]["userVerification"] == "required"
    added = api.post("/auth/passkeys", device.create(options), headers={"User-Agent": ANDROID})
    assert added.status_code == 201, added.text
    assert added.json()["label"] == "Chrome on Android"
    return device


def locked_options(api):
    assert api.post("/auth/lock").status_code == 204
    return api.post("/auth/passkey/unlock-options").json()


@pytest.mark.security
def test_passkeys_are_off_unless_the_server_turns_them_on(api):
    signed_up(api)
    assert api.get("/auth/config").json()["passkey_enabled"] is False
    assert api.post("/auth/passkeys/options", {"password": PASSWORD}).status_code == 400


@pytest.mark.security
def test_adding_one_takes_the_password(api, passkeys_on):
    signed_up(api)
    assert api.post("/auth/passkeys/options", {"password": "Not-The-Password-1"}).status_code == 401


@pytest.mark.security
def test_a_passkey_unlocks_the_lock_screen(api, passkeys_on, engine):
    device = with_passkey(api)
    from sqlalchemy.orm import Session as S

    with S(engine) as db:
        wrapped_before = bytes(db.execute(select(User)).scalar_one().dek_wrapped)
    options = locked_options(api)
    assert api.get("/settings/preferences").json()["code"] == "SESSION_LOCKED"
    assert api.get("/auth/me").json()["passkey_set"] is True
    body = api.post("/auth/passkey/unlock", device.get(options))
    assert body.status_code == 200, body.text
    assert body.json()["locked"] is False
    assert api.get("/settings/preferences").status_code == 200
    with S(engine) as db:
        user = db.execute(select(User)).scalar_one()
        # The passkey decided; the master key unwrapped. Nothing about the key changed.
        assert bytes(user.dek_wrapped) == wrapped_before
        assert "PRIVATE" not in user.passkeys and "dek" not in user.passkeys.lower()


@pytest.mark.security
@pytest.mark.parametrize("wrong", ["origin", "type", "unverified", "other_key", "backwards"])
def test_a_wrong_answer_does_not_unlock(api, passkeys_on, wrong):
    device = with_passkey(api)
    options = locked_options(api)
    if wrong == "backwards":
        device.count = 10
        assert api.post("/auth/passkey/unlock", device.get(options)).status_code == 200
        options = locked_options(api)
    answer = {
        "origin": lambda: device.get(options, origin="https://evil.example"),
        "type": lambda: device.get(options, kind="webauthn.create"),
        "unverified": lambda: device.get(options, flags=0x01),  # a tap, no fingerprint
        "other_key": lambda: device.get(options, key=ec.generate_private_key(ec.SECP256R1())),
        "backwards": lambda: device.get(options, count=3),  # a cloned authenticator
    }[wrong]()
    assert api.post("/auth/passkey/unlock", answer).status_code == 401
    assert api.get("/settings/preferences").json()["code"] == "SESSION_LOCKED"


@pytest.mark.security
def test_a_challenge_is_used_once(api, passkeys_on):
    device = with_passkey(api)
    options = locked_options(api)
    answer = device.get(options)
    assert api.post("/auth/passkey/unlock", answer).status_code == 200
    api.post("/auth/lock")
    assert api.post("/auth/passkey/unlock", answer).status_code == 401  # replayed


@pytest.mark.security
def test_a_removed_passkey_unlocks_nothing(api, passkeys_on):
    with_passkey(api)
    passkey = api.get("/auth/activity").json()["passkeys"][0]
    assert api.delete(f"/auth/passkeys/{passkey['id']}").status_code == 204
    api.post("/auth/lock")
    assert api.post("/auth/passkey/unlock-options").status_code == 400
    assert api.get("/auth/me").json()["passkey_set"] is False


def test_the_small_cbor_reader_refuses_what_webauthn_never_sends():
    assert _cbor(_cbor_encode({1: [b"x", "y", -7, True]})) == {1: [b"x", "y", -7, True]}
    with pytest.raises(ValidationException):
        _cbor(_cbor_encode(1) + b"\x00")  # trailing bytes
    with pytest.raises(ValidationException):
        _cbor(b"\x9f\x01\xff")  # an indefinite-length array
    with pytest.raises(ValidationException):
        _cbor(b"\x5a\xff\xff\xff\xff")  # a byte string longer than the data
