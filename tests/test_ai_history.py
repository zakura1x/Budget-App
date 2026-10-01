"""
The AI companion's saved conversations (misc/AI, Phase A6, AI-60).

Off by default: a conversation goes on lock, as A1-A5 promised. With
`assistant_history_days` above 0 each turn is also sealed into an
`assistant_threads` row under the user's DEK, read back after an unlock,
deleted for good on request, on expiry, or when keeping or the assistant is
turned off - and carried by backup, DEK rotation and account deletion like any
other encrypted row.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.crypto.session_keys import get_session_keyring
from app.core.exceptions import DecryptionError
from app.services.auth_service.tokens import decode_access_token
from app.db.models import AssistantThread
from app.db.repositories.assistant_thread_repository import AssistantThreadRepository
from app.services import preferences_service
from app.services.assistant_service import history
from app.services.assistant_service.memory import Conversation, Turn
from app.services.backup_service import restore_service
from app.core.crypto.keyring import get_master_keyring
from tests.test_ai_assistant import _fresh, ask, first_fact, install, money_world, signed_up  # noqa: F401
from tests.test_backup import backup_of, folders, make_user  # noqa: F401

PASSWORD = "Correct-Horse-9!"


def threads(session) -> int:
    session.expire_all()
    return session.execute(select(func.count(AssistantThread.id))).scalar_one()


def keeping(api, days=90):
    assert api.patch("/settings/preferences", {"assistant_history_days": days}).status_code == 200


def relock(api):
    api.post("/auth/lock")
    assert api.post("/auth/unlock", {"password": PASSWORD}).status_code == 200


# ----------------------------------------------------------------- off by default


@pytest.mark.security
def test_nothing_is_kept_unless_the_user_chooses_to(api, session):
    signed_up(api)
    install(first_fact)
    assert api.get("/assistant/status").json()["history_days"] == 0
    first = ask(api, "How much is left in my budget?").json()
    assert threads(session) == 0
    assert api.get("/assistant/conversations").json() == {"history_days": 0, "conversations": []}
    relock(api)
    assert api.get(f"/assistant/conversations/{first['conversation_id']}").status_code == 404


def test_only_the_offered_lengths_are_accepted(api):
    signed_up(api)
    for bad in (7, -1, True, "90"):
        assert api.patch("/settings/preferences", {"assistant_history_days": bad}).status_code == 422
    keeping(api, 365)
    assert api.get("/assistant/status").json()["history_days"] == 365


# ----------------------------------------------------------------- kept


@pytest.mark.security
def test_a_kept_conversation_is_sealed_and_comes_back_after_an_unlock(api, session):
    signed_up(api)
    money_world(api)
    install(first_fact)
    keeping(api)
    first = ask(api, "How much did I spend this month on my Lazada splurge?").json()
    cid = first["conversation_id"]
    second = ask(api, "And last month?", cid).json()
    assert second["conversation_id"] == cid
    assert threads(session) == 1  # one row per conversation, updated each turn

    raw = session.execute(select(AssistantThread.payload)).scalar_one()
    assert b"Lazada" not in bytes(raw) and b"spend" not in bytes(raw)  # sealed, like every Shape B row

    listed = api.get("/assistant/conversations").json()
    assert listed["history_days"] == 90
    assert [(c["conversation_id"], c["turns"]) for c in listed["conversations"]] == [(cid, 2)]
    assert listed["conversations"][0]["title"].startswith("How much did I spend this month")

    relock(api)  # the copy in memory goes with the key; the sealed row waits
    back = api.get(f"/assistant/conversations/{cid}").json()
    assert [t["question"] for t in back["turns"]] == [first["question"], second["question"]]
    third = ask(api, "How much cash do I have?", cid).json()
    assert third["conversation_id"] == cid and threads(session) == 1
    assert api.get("/assistant/conversations").json()["conversations"][0]["turns"] == 3


def test_a_saved_reply_keeps_no_draft_button(api, session):
    signed_up(api)
    money_world(api)
    install(first_fact)
    keeping(api)
    reply = ask(api, "I spent 250 on Food at Jollibee").json()
    assert [a["kind"] for a in reply["actions"]] == ["draft_transaction"]  # the live reply has it
    relock(api)
    saved = api.get(f"/assistant/conversations/{reply['conversation_id']}").json()["turns"][0]
    assert saved["actions"] == [] and saved["text"] == reply["text"]


def test_deleting_one_removes_it_for_good(api, session):
    signed_up(api)
    install(first_fact)
    keeping(api)
    cid = ask(api, "How much is left in my budget?").json()["conversation_id"]
    other = ask(api, "How much cash do I have?").json()["conversation_id"]
    assert threads(session) == 2
    assert api.delete(f"/assistant/conversations/{cid}").status_code == 204
    assert threads(session) == 1  # not soft-deleted: gone
    assert [c["conversation_id"] for c in api.get("/assistant/conversations").json()["conversations"]] == [other]
    assert api.get(f"/assistant/conversations/{cid}").status_code == 404


@pytest.mark.parametrize("change", [{"assistant_history_days": 0}, {"assistant": False}])
def test_turning_keeping_or_the_assistant_off_deletes_every_saved_one(api, session, change):
    signed_up(api)
    install(first_fact)
    keeping(api)
    ask(api, "How much is left in my budget?")
    ask(api, "How much cash do I have?")
    assert threads(session) == 2
    assert api.patch("/settings/preferences", change).status_code == 200
    assert threads(session) == 0


def test_a_conversation_untouched_too_long_is_deleted(api, session):
    signed_up(api)
    install(first_fact)
    keeping(api, 30)
    cid = ask(api, "How much is left in my budget?").json()["conversation_id"]
    fresh = ask(api, "How much cash do I have?").json()["conversation_id"]

    session_id = decode_access_token(api.cookies.get(settings.SESSION_COOKIE_NAME)).session_id
    cipher = get_session_keyring().cipher_for(session_id)
    repo = AssistantThreadRepository(session, cipher)
    old = next(r for r in repo.list() if r.data["conversation_id"] == cid)
    stale = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(timespec="seconds")
    repo.update(old.id, {**old.data, "updated_at": stale})
    session.commit()

    listed = api.get("/assistant/conversations").json()["conversations"]
    assert [c["conversation_id"] for c in listed] == [fresh]
    assert threads(session) == 1


def test_at_most_fifty_are_kept(session, monkeypatch):
    user, cipher = make_user(session, "alice")
    preferences_service.update_preferences(session, cipher, {"assistant": True, "assistant_history_days": 90})
    monkeypatch.setattr(history, "MAX_THREADS", 3)
    for n in range(5):
        conversation = Conversation(id=f"c{n}", turns=[Turn(question=f"Question {n}", reply={"text": "ok"})])
        history.save(session, cipher, conversation)
        session.commit()
    _, kept = history.summaries(session, cipher)
    assert len(kept) == 3 and "c4" in {k.conversation_id for k in kept}


# ----------------------------------------------------------------- one user's own


@pytest.mark.security
def test_another_user_cannot_read_or_delete_a_kept_conversation(api, session):
    signed_up(api)
    install(first_fact)
    keeping(api)
    cid = ask(api, "How much is left in my budget?").json()["conversation_id"]
    api.client.cookies.clear()
    assert api.register(email="bob@example.com").status_code == 201
    api.patch("/settings/preferences", {"assistant": True, "assistant_history_days": 90})
    assert api.get(f"/assistant/conversations/{cid}").status_code == 404
    assert api.get("/assistant/conversations").json()["conversations"] == []
    assert api.delete(f"/assistant/conversations/{cid}").status_code == 204  # nothing of his to delete
    assert threads(session) == 1


# ----------------------------------------------------------------- the rest of the system


@pytest.mark.security
def test_rotating_the_key_reseals_kept_conversations(api, session):
    signed_up(api)
    install(first_fact)
    keeping(api)
    cid = ask(api, "How much is left in my budget?").json()["conversation_id"]
    session_id = decode_access_token(api.cookies.get(settings.SESSION_COOKIE_NAME)).session_id
    old_cipher = get_session_keyring().cipher_for(session_id)
    assert api.post("/security/rotate-key", {"password": PASSWORD}).status_code == 200
    session.expire_all()
    row = session.execute(select(AssistantThread)).scalar_one()
    with pytest.raises(DecryptionError):
        old_cipher.open("assistant_threads", row.id, row.payload, row.key_version)
    relock(api)
    assert len(api.get(f"/assistant/conversations/{cid}").json()["turns"]) == 1


def test_deleting_the_account_removes_kept_conversations(api, session):
    signed_up(api)
    install(first_fact)
    keeping(api)
    ask(api, "How much is left in my budget?")
    assert threads(session) == 1
    gone = api.post("/security/delete-account", {"password": PASSWORD, "confirm_email": "noah@example.com"})
    assert gone.status_code in (200, 204), gone.text
    assert threads(session) == 0


def test_kept_conversations_go_through_a_backup_and_restore(session, folders):  # noqa: F811
    alice, alice_cipher = make_user(session, "alice")
    preferences_service.update_preferences(session, alice_cipher, {"assistant": True, "assistant_history_days": 90})
    history.save(session, alice_cipher, Conversation(id="trip", turns=[
        Turn(question="Can I afford a 3,000 pair of shoes?", reply={"text": "Yes - it fits.", "actions": []})]))
    session.commit()
    found, _ = backup_of(session, alice.id, folders / "one")

    bob, bob_cipher = make_user(session, "bob")
    source = restore_service.unlock_source(found, keyring=get_master_keyring())
    assert restore_service.restore(session, found, bob_cipher, source, mode="fresh").ok
    loaded = history.load(session, bob_cipher, "trip")
    assert loaded is not None and loaded.turns[0].reply["text"] == "Yes - it fits."
