"""
The AI companion's A4 (misc/AI/PHASES.md): Explain links (a context the
server checks), drafts that write nothing, the what-if hand-off, and finding
one merchant's entries.

The rule these hold hardest is ARCHITECTURE §8: the assistant proposes, the
user saves. Every draft test counts rows before and after.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.models import RecurringRule, SavingsGoal, Transaction
from app.services.assistant_service import router
from tests.test_ai_assistant import TODAY, TODAY_DATE, _fresh, ask, first_fact, install, money_world, signed_up  # noqa: F401

D = TODAY_DATE


def rows(session):
    return tuple(session.execute(select(func.count(model.id))).scalar_one()
                 for model in (Transaction, RecurringRule, SavingsGoal))


def ask_with(api, question, context):
    return api.post("/assistant/ask", {"question": question, "today": TODAY, "context": context})


# --------------------------------------------------------------- the router


@pytest.mark.parametrize(
    "question, skill",
    [
        ("I just spent 250 on lunch", "draft"),
        ("I paid 1,500 for groceries yesterday", "draft"),
        ("Gumastos ako ng 300 sa pamasahe", "draft"),
        ("I received 25,000 salary", "draft"),
        ("Help me save ₱50,000 by December", "draft_goal"),
        ("I want to save 20k in 6 months for a Japan trip", "draft_goal"),
        ("How much did I spend this month?", "spending"),  # "spend", not "I spent": a question, not an entry
        ("Can I afford to have spent 500?", "afford"),
    ],
)
def test_drafts_route(question, skill):
    assert router.by_rules(question, D, {}, {}).skill == skill


def test_a_drafted_entry_reads_its_fields_from_the_words():
    intent = router.by_rules("I paid 1,500 for Food at Jollibee yesterday from Wallet", D, {5: "Food"}, {2: "Wallet"},
                             merchants={0: "Jollibee"})
    assert (intent.skill, intent.amount, intent.category_id, intent.account_id, intent.merchant, intent.on, intent.income) == (
        "draft", Decimal("1500.00"), 5, 2, "Jollibee", date(2026, 10, 9), False)
    income = router.by_rules("I received 25,000 today", D, {}, {})
    assert (income.income, income.on) == (True, D)


def test_a_new_merchant_is_read_after_at():
    assert router.by_rules("I spent 180 at Mang Inasal", D, {}, {}).merchant == "Mang Inasal"


@pytest.mark.parametrize(
    "question, amount, on, name",
    [
        ("Help me save ₱50,000 by December", "50000.00", date(2026, 12, 31), None),
        ("I want to save 20k in 6 months for a Japan trip", "20000.00", date(2027, 4, 30), "Japan trip"),
        ("Help me save 100,000 by March 2028 for a car", "100000.00", date(2028, 3, 31), "Car"),
        ("Help me save ₱5,000", "5000.00", None, None),
    ],
)
def test_a_drafted_goal_reads_its_amount_date_and_name(question, amount, on, name):
    intent = router.by_rules(question, D, {}, {})
    assert (intent.skill, intent.amount, intent.on, intent.item) == ("draft_goal", Decimal(amount), on, name)


def test_find_needs_a_name_the_user_has():
    known = router.by_rules("When did I last pay at Jollibee?", D, {}, {}, merchants={0: "Jollibee"})
    assert (known.skill, known.merchant) == ("find", "Jollibee")
    bill = router.by_rules("When did I last pay Meralco?", D, {}, {}, plans={4: "Meralco"})
    assert (bill.skill, bill.rule_id) == ("find", 4)
    assert router.by_rules("When did I last pay my rent?", D, {}, {}).skill != "find"


def test_the_model_cannot_route_to_a_draft_or_find():
    for skill in ("draft", "draft_goal", "find"):
        assert router.by_model("q", D, {}, {}, lambda p, s=skill: ({"skill": s}, {})) is None


# ------------------------------------------------------------------ drafts


@pytest.mark.security
def test_a_drafted_entry_is_a_button_and_writes_nothing(api, session):
    signed_up(api)
    wallet, _, food = money_world(api)
    model = install(first_fact)
    before = rows(session)
    reply = ask(api, "I spent 250 on Food yesterday from Wallet").json()
    assert rows(session) == before
    assert model.prompts == []  # no model call for a draft
    action = reply["actions"][0]
    assert (reply["skill"], action["kind"]) == ("draft", "draft_transaction")
    assert action["payload"] == {"type": "expense", "amount": "250.00", "txn_date": "2026-10-09",
                                 "category_id": food, "account_id": wallet, "merchant": None, "notes": None}
    assert "Nothing is saved until you save it" in reply["text"]


def test_a_merchant_typed_before_brings_its_category(api):
    signed_up(api)
    wallet, _, food = money_world(api)
    api.post(f"/transactions?today={TODAY}", {"type": "expense", "amount": "180.00", "txn_date": "2026-10-05",
                                              "account_id": wallet, "category_id": food, "merchant": "Jollibee"})
    install(first_fact)
    payload = ask(api, "I spent 210 at Jollibee").json()["actions"][0]["payload"]
    assert (payload["merchant"], payload["category_id"], payload["txn_date"]) == ("Jollibee", food, TODAY)


def test_a_draft_without_an_amount_asks_for_one(api):
    signed_up(api)
    install(first_fact)
    reply = ask(api, "I just bought lunch").json()
    assert reply["skill"] == "draft" and reply["actions"] == [] and "How much was it" in reply["text"]


@pytest.mark.security
def test_a_drafted_goal_is_a_button_and_writes_nothing(api, session):
    signed_up(api)
    money_world(api)
    install(first_fact)
    before = rows(session)
    reply = ask(api, "Help me save ₱50,000 by December for a Japan trip").json()
    assert rows(session) == before
    action = reply["actions"][0]
    assert action["kind"] == "draft_goal"
    assert action["payload"] == {"name": "Japan trip", "target": "50000.00", "target_date": "2026-12-31"}
    # GOA-05's own rule: October, November and December - three months
    assert "₱16,666.67 a month for 3 months" in reply["text"]


def test_an_affordability_answer_offers_the_what_if(api):
    signed_up(api)
    money_world(api)
    install(lambda p: RuntimeError("model down"))
    reply = ask(api, "Can I get a ₱60,000 laptop in 12 months?").json()
    action = next(a for a in reply["actions"] if a["kind"] == "try_installment")
    assert action["payload"] == {"name": "laptop", "price": "60000.00", "payments": 12}
    assert action["route"] == "/projection"


# --------------------------------------------------------------------- find


def test_find_reports_a_merchants_entries_and_never_a_note(api):
    signed_up(api)
    wallet, _, food = money_world(api)
    for when, amount in (("2026-09-12", "150.00"), ("2026-10-03", "180.00"), ("2026-10-07", "220.00")):
        api.post(f"/transactions?today={TODAY}", {"type": "expense", "amount": amount, "txn_date": when,
                                                  "account_id": wallet, "category_id": food, "merchant": "Jollibee",
                                                  "notes": "with Ana - surprise gift inside"})
    install(lambda p: RuntimeError("model down"))
    reply = ask(api, "When did I last pay at Jollibee?").json()
    assert reply["skill"] == "find"
    assert "₱220.00 on 7 Oct" in reply["text"] and "2 entries, ₱400.00" in reply["text"]
    everything = reply["text"] + " ".join(reply["facts"])
    assert "Ana" not in everything and "surprise" not in everything
    assert "3 entries, ₱550.00" in " ".join(reply["facts"])


def test_find_sends_only_the_merchant_asked_about(api):
    signed_up(api)
    wallet, _, food = money_world(api)
    for merchant in ("Jollibee", "Mercury Drug"):
        api.post(f"/transactions?today={TODAY}", {"type": "expense", "amount": "100.00", "txn_date": "2026-10-05",
                                                  "account_id": wallet, "category_id": food, "merchant": merchant})
    model = install(first_fact)
    ask(api, "When did I last pay at Jollibee?")
    assert "Jollibee" in model.prompts[-1] and "Mercury Drug" not in model.prompts[-1]


@pytest.mark.parametrize(
    "reply, ok",
    [
        ("You spent ₱3,420.00 from 1 Oct to 31 Oct.", True),
        ("You spent ₱3,420.00 from 1 October to 31 October.", True),  # the same month, spelt out
        ("Nagastos ka ng ₱3,420.00 mula Enero 1 hanggang Disyembre 31.", False),  # every digit real, both months not
        ("You spent ₱3,420.00 by 31 Dec.", False),
        ("You may spend ₱3,420.00.", True),  # "may" the verb is not a month
        ("It is due 1 May.", False),
    ],
)
def test_a_month_in_a_reply_must_be_in_the_facts(reply, ok):
    from app.services.assistant_service import verifier

    assert verifier.check(reply, ["In 1 Oct to 31 Oct: 2 entries, ₱3,420.00 in all."]).ok is ok


# ------------------------------------------------------------ Explain links


def test_a_screen_context_decides_the_skill(api):
    signed_up(api)
    money_world(api)
    install(lambda p: RuntimeError("model down"))
    assert ask_with(api, "Explain this", {"screen": "budget"}).json()["skill"] == "budget_status"
    assert ask_with(api, "Explain this", {"screen": "review"}).json()["skill"] == "review"
    assert ask_with(api, "Explain this", {"screen": "no-such-screen"}).json()["skill"] == "clarify"


def test_an_alert_or_account_context_names_the_card(api):
    signed_up(api)
    wallet, card, _ = money_world(api)
    install(lambda p: RuntimeError("model down"))
    by_alert = ask_with(api, "Explain this alert", {"alert": "card_due", "account_id": card}).json()
    assert by_alert["skill"] == "card" and by_alert["actions"][0]["route"] == f"/accounts/{card}"
    assert ask_with(api, "Tell me about this", {"account_id": card}).json()["skill"] == "card"
    assert ask_with(api, "Tell me about this", {"account_id": wallet}).json()["skill"] == "cash"


@pytest.mark.security
def test_a_context_cannot_name_someone_elses_account(api):
    signed_up(api)
    wallet, _, _ = money_world(api)
    api.client.cookies.clear()
    assert api.register(email="bob@example.com", name="Bob").status_code == 201
    api.patch("/settings/preferences", {"assistant": True})
    install(lambda p: RuntimeError("model down"))
    reply = ask_with(api, "Tell me about this", {"account_id": wallet}).json()
    assert reply["skill"] == "clarify"  # not Bob's account: dropped, and the words alone say nothing
    assert "Wallet" not in reply["text"] + " ".join(reply["facts"])


def test_a_context_never_carries_a_figure(api):
    signed_up(api)
    money_world(api)
    refused = api.post("/assistant/ask", {"question": "Explain this", "today": TODAY,
                                          "context": {"screen": "budget", "remaining": "999999.00"}})
    assert refused.status_code == 200  # the unknown key is ignored, not trusted
    assert "999,999" not in refused.json()["text"]
