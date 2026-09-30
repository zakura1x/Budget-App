"""
The AI companion's first questions (misc/AI, Phase A2): the figure check, the
router, the five skills (each held to its own screen's figure), the turn with
a fake model, the opt-in, and conversations that go with the key.

The model is always a fake here - FakeModel answers from a function of the
prompt - so these run without the watsonx SDK and without a network.
"""

import json
import logging
from datetime import date
from decimal import Decimal

import pytest

from app.ai import llm_service
from app.ai.llm_service import LLMService
from app.core.config import settings
from app.services.assistant_service import router, verifier
from app.services.assistant_service.facts import day, pct, php
from app.services.assistant_service.memory import set_memory

TODAY = "2026-10-10"
TODAY_DATE = date(2026, 10, 10)


# ------------------------------------------------------------------ fakes


class FakeLoader:
    last_error = None

    def get_watson_credentials_with_retry(self, company_name=None):
        return {"api_key": "k", "project_id": "p", "_test_status": "success"}

    def check_and_auto_reload(self, company=None):
        return False

    def trigger_auto_reload(self, company=None):
        pass


class FakeModel:
    """Answers each prompt with answer(prompt); an Exception is raised instead."""

    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def invoke_with_usage(self, prompt, stop=None):
        self.prompts.append(prompt)
        reply = self.answer(prompt)
        if isinstance(reply, Exception):
            raise reply
        return reply, {"prompt_tokens": 100, "completion_tokens": 20}

    def close(self):
        pass


def install(answer):
    model = FakeModel(answer)
    service = LLMService(credential_loader=FakeLoader())
    service._build_model = lambda name, params, creds: model
    llm_service.set_llm_service(service)
    return model


def first_fact(prompt: str) -> str:
    """A reply that copies the first fact line - figures and all - as the answer."""
    after = prompt.split("\nFacts (", 1)[1]
    return next(line[2:] for line in after.splitlines() if line.startswith("- "))


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    monkeypatch.setattr(settings, "AI_REPLY_LANGUAGE", "en")
    llm_service.set_llm_service(None)
    set_memory(None)
    yield
    llm_service.set_llm_service(None)
    set_memory(None)


def signed_up(api, opt_in=True):
    assert api.register().status_code == 201
    if opt_in:
        assert api.patch("/settings/preferences", {"assistant": True}).status_code == 200


def money_world(api):
    """A wallet, a card, Food and Transport, a September and an October of spending, a budget."""
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "20000.00"}).json()["id"]
    card = api.post("/accounts", {"name": "BPI Card", "type": "credit", "statement_closing_day": 16,
                                  "payment_due_day": 6}).json()["id"]
    food = api.post("/categories", {"name": "Food"}).json()["id"]
    transport = api.post("/categories", {"name": "Transport"}).json()["id"]
    api.post(f"/budgets?today={TODAY}", {"period": "monthly", "amount": "30000.00",
                                         "allocations": [{"category_id": food, "amount": "9000.00"}]})
    for when, amount, account, category in (
        ("2026-09-05", "1200.00", wallet, food), ("2026-09-20", "800.00", wallet, transport),
        ("2026-10-02", "2500.00", wallet, food), ("2026-10-08", "450.50", card, transport),
    ):
        created = api.post(f"/transactions?today={TODAY}", {"type": "expense", "amount": amount, "txn_date": when,
                                                             "account_id": account, "category_id": category})
        assert created.status_code == 201, created.text
    return wallet, card, food


def ask(api, question, conversation_id=None):
    body = {"question": question, "today": TODAY}
    if conversation_id:
        body["conversation_id"] = conversation_id
    return api.post("/assistant/ask", body)


# ---------------------------------------------------------------- verifier


@pytest.mark.parametrize(
    "reply, ok",
    [
        ("You have ₱4,210.00 left.", True),
        ("You have 4210 left.", True),
        ("You have PHP 4,210 left until 31 Oct.", True),
        ("You have ₱4,200.00 left.", False),  # rounded
        ("About four thousand left.", False),  # in words
        ("Mga ₱4,210.00 pa ang natitira, hanggang 31 Oct.", True),
        ("You can spend ₱3,999.00 - you asked about 3,999.", True),  # the question's own figure
        ("You have 5k left.", False),
        ("", False),
    ],
)
def test_the_figure_check(reply, ok):
    facts = ["Left to spend: ₱4,210.00.", "The period runs 1 Oct to 31 Oct."]
    assert verifier.check(reply, facts + ["can I buy it for 3999?"]).ok is ok


def test_k_means_thousands_and_values_compare_by_value():
    assert verifier.figures("5k and 1,234.50 and 1234.5") == {Decimal("5000"), Decimal("1234.5")}


def test_formats():
    assert php(Decimal("-1234.5")) == "-₱1,234.50"
    assert day(date(2027, 1, 3), TODAY_DATE) == "3 Jan 2027"
    assert pct(Decimal("0.8549")) == "85%"


# ------------------------------------------------------------------ router


@pytest.mark.parametrize(
    "question, skill",
    [
        ("How much is left in my budget?", "budget_status"),
        ("Magkano ang natitira sa budget ko?", "budget_status"),
        ("What's my daily allowance?", "budget_status"),
        ("How much did I spend this month?", "spending"),
        ("Saan napunta ang gastos ko?", "spending"),
        ("How much cash do I have?", "cash"),
        ("Magkano pera ko?", "cash"),
        ("What bills are due before payday?", "upcoming"),
        ("Ano ang bayarin ko bago sahod?", "upcoming"),
        ("How much do I owe on my card?", "card"),
        ("When is my card bill due?", "card"),
        ("Tell me a joke", None),
    ],
)
def test_rules_route_the_plain_questions(question, skill):
    assert router.by_rules(question, TODAY_DATE, {}, {}).skill == skill


def test_rules_find_periods_names_and_windows():
    intent = router.by_rules("How much on Food in September?", TODAY_DATE, {5: "Food", 6: "Transport"}, {})
    assert (intent.skill, intent.category_id, intent.period) == ("spending", 5, "2026-09")
    assert router.find_period("gastos noong nakaraang buwan", TODAY_DATE) == "last_month"
    assert router.find_period("what did I buy in December", TODAY_DATE) == "2025-12"
    assert router.find_window("due this week") == "week"
    assert router.find_name("how much is on my bpi card", {1: "BPI Card", 2: "BPI"}) == 1


def test_the_model_route_is_checked_against_the_rules():
    def asks(answer):
        return lambda prompt: (answer, {})

    good = router.by_model("q", TODAY_DATE, {5: "Food"}, {}, asks({"skill": "spending", "category": "food",
                                                                    "period": "2026-09", "window": "never"}))
    assert (good.skill, good.category_id, good.period, good.window) == ("spending", 5, "2026-09", None)
    assert router.by_model("q", TODAY_DATE, {}, {}, asks({"skill": "transfer_money"})) is None
    assert router.by_model("q", TODAY_DATE, {}, {}, lambda p: (_ for _ in ()).throw(TimeoutError())) is None


# ------------------------------------------------------- skills vs screens


def test_budget_answer_is_homes_figure(api):
    signed_up(api)
    money_world(api)
    install(lambda p: RuntimeError("model down"))
    reply = ask(api, "How much is left in my budget?").json()
    home = api.get(f"/budgets/current?today={TODAY}").json()["status"]["allowance"]
    assert reply["skill"] == "budget_status" and reply["ai_phrased"] is False
    assert php(Decimal(home["remaining"])) in reply["text"]
    assert php(Decimal(home["daily"])) in reply["text"]
    assert reply["tone"] in ("ok", "warn")


def test_cash_answer_is_the_accounts_tabs_figure(api):
    signed_up(api)
    money_world(api)
    install(lambda p: RuntimeError("model down"))
    reply = ask(api, "How much cash do I have?").json()
    accounts = api.get(f"/accounts?today={TODAY}").json()
    assert php(Decimal(accounts["cash_on_hand"]["total"])) in reply["text"]
    assert php(Decimal(accounts["net_worth"]["total"])) in reply["text"]


def test_spending_answer_is_the_stats_tabs_figure(api):
    signed_up(api)
    _, _, food = money_world(api)
    install(lambda p: RuntimeError("model down"))
    reply = ask(api, "How much did I spend on Food in September?").json()
    stats = api.get(f"/stats/overview?span=month&on=2026-09-15&today={TODAY}").json()
    food_share = next(c for c in stats["categories"] if c["category_id"] == food)
    assert reply["skill"] == "spending"
    assert php(Decimal(food_share["amount"])) in reply["text"]
    month = ask(api, "How much did I spend this month?").json()
    now = api.get(f"/stats/overview?span=month&on={TODAY}&today={TODAY}").json()
    assert php(Decimal(now["totals"]["spent"])) in month["text"]


def test_card_answer_is_the_cards_figure(api):
    signed_up(api)
    _, card, _ = money_world(api)
    install(lambda p: RuntimeError("model down"))
    reply = ask(api, "How much do I owe on my card?").json()
    credit = api.get(f"/accounts/{card}?today={TODAY}").json()["credit"]
    assert php(Decimal(credit["owed_with_plans"])) in reply["text"]
    assert reply["actions"][0]["route"] == f"/accounts/{card}"


def test_upcoming_lists_a_scheduled_bill(api):
    signed_up(api)
    wallet, _, food = money_world(api)
    rule = api.post(f"/recurring?today={TODAY}", {"kind": "standard", "type": "expense", "name": "Meralco",
                                                    "amount": "2450.00", "account_id": wallet, "category_id": food,
                                                    "frequency": "monthly", "start": "2026-10-15"})
    assert rule.status_code == 201, rule.text
    install(lambda p: RuntimeError("model down"))
    reply = ask(api, "What's due this week?").json()
    assert reply["skill"] == "upcoming"
    assert "Meralco" in " ".join(reply["facts"]) and "₱2,450.00" in " ".join(reply["facts"])


def test_no_budget_says_so(api):
    signed_up(api)
    install(lambda p: RuntimeError("model down"))
    reply = ask(api, "How much is left in my budget?").json()
    assert "haven't set a budget" in reply["text"] and reply["actions"][0]["route"] == "/budget"


# -------------------------------------------------------------- the turn


def test_a_good_reply_is_shown_and_counted(api):
    signed_up(api)
    money_world(api)
    model = install(first_fact)
    reply = ask(api, "How much is left in my budget?").json()
    assert reply["ai_phrased"] is True
    assert reply["text"] == reply["facts"][0]
    assert len(model.prompts) == 1  # the rules routed it; one ANSWER call
    assert "Copy every amount" in model.prompts[0]
    body = api.get("/assistant/status").json()
    assert body["questions_left_today"] == settings.AI_MAX_QUESTIONS_PER_DAY - 1


def test_an_invented_figure_is_never_shown(api):
    signed_up(api)
    money_world(api)
    install(lambda p: "You have ₱99,999.00 left, so go ahead.")
    reply = ask(api, "How much is left in my budget?").json()
    assert reply["ai_phrased"] is False
    assert "99,999" not in reply["text"]


def test_the_model_routes_what_the_rules_cannot(api):
    signed_up(api)
    money_world(api)

    def answer(prompt):
        if prompt.startswith("You sort questions"):
            return json.dumps({"skill": "off_topic"})
        raise AssertionError("an off-topic reply needs no ANSWER call")

    model = install(answer)
    reply = ask(api, "Who won the game last night?").json()
    assert reply["skill"] == "off_topic" and reply["follow_ups"]
    assert len(model.prompts) == 1


def test_nobody_can_tell_gives_a_clarifying_reply(api):
    signed_up(api)
    install(lambda p: "not json")
    reply = ask(api, "hmm").json()
    assert reply["skill"] == "clarify" and reply["follow_ups"]


def test_a_conversation_carries_its_history_in_the_prompt(api):
    signed_up(api)
    money_world(api)
    model = install(first_fact)
    first = ask(api, "How much is left in my budget?").json()
    second = ask(api, "How much cash do I have?", first["conversation_id"]).json()
    assert second["conversation_id"] == first["conversation_id"]
    assert "User: How much is left in my budget?" in model.prompts[1]
    turns = api.get(f"/assistant/conversations/{first['conversation_id']}").json()["turns"]
    assert [t["skill"] for t in turns] == ["budget_status", "cash"]


def test_taglish_replies_only_when_switched_on(api, monkeypatch):
    signed_up(api)
    model = install(first_fact)
    ask(api, "Magkano ang natitira sa budget ko?")
    assert "Reply in English" in model.prompts[-1]
    monkeypatch.setattr(settings, "AI_REPLY_LANGUAGE", "match")
    ask(api, "Magkano ang natitira sa budget ko?")
    assert "Taglish" in model.prompts[-1] and "Reply in English" not in model.prompts[-1]


# ---------------------------------------------------------- the boundary


@pytest.mark.security
def test_refused_unless_opted_in_and_switched_on(api, monkeypatch):
    signed_up(api, opt_in=False)
    install(first_fact)
    refused = ask(api, "How much is left?")
    assert (refused.status_code, refused.json()["code"]) == (403, "ASSISTANT_NOT_OPTED_IN")
    assert api.get("/assistant/status").json()["opted_in"] is False
    api.patch("/settings/preferences", {"assistant": True})
    assert api.get("/assistant/status").json()["opted_in"] is True
    monkeypatch.setattr(settings, "AI_ENABLED", False)
    off = ask(api, "How much is left?")
    assert (off.status_code, off.json()["code"]) == (503, "ASSISTANT_DISABLED")


@pytest.mark.security
def test_opting_in_and_out_is_audited(api, session):
    from sqlalchemy import select

    from app.db.models import AuditLog

    signed_up(api)
    api.patch("/settings/preferences", {"assistant": True})  # no change: no second entry
    api.patch("/settings/preferences", {"assistant": False})
    actions = session.execute(select(AuditLog.action).where(AuditLog.action.like("ASSISTANT_%"))
                              .order_by(AuditLog.id)).scalars().all()
    assert actions == ["ASSISTANT_ENABLED", "ASSISTANT_DISABLED"]


@pytest.mark.security
def test_conversations_go_with_the_key(api):
    signed_up(api)
    install(first_fact)
    first = ask(api, "How much is left in my budget?").json()
    api.post("/auth/lock")
    api.post("/auth/unlock", {"password": "Correct-Horse-9!"})
    gone = api.get(f"/assistant/conversations/{first['conversation_id']}")
    assert gone.status_code == 404


@pytest.mark.security
def test_no_question_or_reply_is_logged(api, caplog):
    signed_up(api)
    money_world(api)
    install(lambda p: "Your Lazada splurge fits.")
    with caplog.at_level(logging.DEBUG):
        ask(api, "Can I afford the Lazada headphones this month?")
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "Assistant turn skill=" in logged
    assert "Lazada" not in logged and "headphones" not in logged


def test_the_callers_errors(api, monkeypatch):
    signed_up(api)
    install(first_fact)
    long = ask(api, "x" * 501)
    assert (long.status_code, long.json()["code"]) == (422, "ASSISTANT_QUESTION_TOO_LONG")
    monkeypatch.setattr(settings, "AI_MAX_QUESTIONS_PER_DAY", 1)
    assert ask(api, "How much is left in my budget?").status_code == 200
    capped = ask(api, "How much is left in my budget?")
    assert (capped.status_code, capped.json()["code"]) == (429, "ASSISTANT_DAILY_LIMIT")


def test_a_second_question_in_flight_is_refused():
    from app.core.exceptions import AssistantBusyException  # noqa: F401 - the code the endpoint answers with

    guard = llm_service.concurrency_guard
    with guard.slot(424242):
        with pytest.raises(llm_service.ConcurrencyLimitReached):
            with guard.slot(424242):
                pass
