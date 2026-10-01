"""
The AI companion as a conversation (2026-10-01, user: "it is not being adaptive
to the message... not communicative during the session").

Before: every message was read on its own. "Hi" and "thanks!" were told the
assistant only talks about money, "what about last month?" became a monthly
review, a price was lost on "how about on installment?", and "why?" jumped to
another skill. Now small talk is answered as small talk, and a follow-up
continues the previous turn's intent with only the slots it names replaced.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.services.assistant_service import router
from tests.test_ai_assistant import _fresh, ask, first_fact, install, money_world, signed_up  # noqa: F401

D = date(2026, 10, 10)
CATS = {1: "Food"}


@pytest.mark.parametrize("message, kind", [
    ("Hi", "greeting"), ("hello there", "greeting"), ("Good morning!", "greeting"), ("Kumusta", "greeting"),
    ("thanks!", "thanks"), ("Thank you so much", "thanks"), ("Salamat po", "thanks"), ("ty", "thanks"),
    ("ok", "ack"), ("Okay.", "ack"), ("got it", "ack"), ("sige po", "ack"), ("ok po 🙏", "ack"),
])
def test_small_talk_is_recognised(message, kind):
    assert router.small_talk(message) == kind


@pytest.mark.parametrize("message", [
    "Hi, how much is left?", "ok so how much cash do I have?", "thanks, and my card?", "How much is left?",
])
def test_a_question_that_starts_politely_is_still_a_question(message):
    assert router.small_talk(message) is None


def _after(previous_question, message):
    previous = router.by_rules(previous_question, D, CATS, {})
    return router.follow_up(message, router.by_rules(message, D, CATS, {}), previous)


def test_a_follow_up_keeps_the_skill_and_replaces_only_what_it_names():
    later = _after("How much did I spend on Food this month?", "What about last month?")
    assert (later.skill, later.period, later.category_id, later.carried) == ("spending", "last_month", 1, True)
    food = _after("How much did I spend last month?", "And on Food?")
    assert (food.skill, food.period, food.category_id) == ("spending", "last_month", 1)


def test_a_follow_up_keeps_the_price_and_the_item():
    cheaper = _after("Can I afford a 15,000 phone?", "What if it's only 8,000?")
    assert (cheaper.skill, cheaper.amount, cheaper.item) == ("afford", Decimal("8000.00"), "phone")
    spread = router.follow_up("How about on installment for 6 months?",
                              router.by_rules("How about on installment for 6 months?", D, CATS, {}), cheaper)
    assert (spread.amount, spread.method, spread.months) == (Decimal("8000.00"), "installment", 6)


def test_eh_sa_keeps_the_budget_question_for_one_category():
    food = _after("Magkano natitira sa budget ko?", "Eh sa Food?")
    assert (food.skill, food.category_id) == ("budget_status", 1)


@pytest.mark.parametrize("message", ["Why is it so high?", "Is that good?", "Can you explain that more?", "Bakit?"])
def test_asking_about_the_last_answer_stays_on_it(message):
    assert _after("How much is left in my budget?", message).skill == "budget_status"
    assert router.asks_for_more(message)


def test_a_follow_up_naming_another_topic_moves_to_it():
    assert _after("How much cash do I have?", "And my card?").skill == "card"


@pytest.mark.parametrize("message", ["What's the weather like?", "Write me a poem", "I spent 250 on lunch",
                                     "How do I add a budget?"])
def test_a_message_that_stands_on_its_own_is_not_carried(message):
    assert _after("How much did I spend this month?", message) is None


def test_nothing_is_carried_from_small_talk_or_a_draft():
    assert router.follow_up("And last month?", router.by_rules("And last month?", D, CATS, {}),
                            router.Intent(skill="chat")) is None
    assert router.follow_up("And last month?", router.by_rules("And last month?", D, CATS, {}),
                            router.Intent(skill="draft")) is None


# ------------------------------------------------------------------ through the API


def test_hello_and_thanks_get_a_reply_not_a_refusal_and_no_model_call(api):
    signed_up(api)
    money_world(api)
    model = install(first_fact)
    hi = ask(api, "Hi").json()
    assert hi["skill"] == "chat" and hi["text"].startswith("Hi!") and hi["follow_ups"]
    assert model.prompts == []
    first = ask(api, "How much is left in my budget?", hi["conversation_id"]).json()
    thanks = ask(api, "thanks!", first["conversation_id"]).json()
    assert thanks["skill"] == "chat" and "welcome" in thanks["text"]
    assert thanks["follow_ups"] == first["follow_ups"][:3]  # carries on from the last answer
    assert len(model.prompts) == 1


def test_what_about_last_month_answers_last_month_and_tells_the_model_so(api):
    signed_up(api)
    money_world(api)
    model = install(first_fact)
    first = ask(api, "How much did I spend this month?").json()
    later = ask(api, "What about last month?", first["conversation_id"]).json()
    assert later["skill"] == "spending" and later["title"].endswith("1 Sep to 30 Sep")
    assert "continues the previous question" in model.prompts[-1]
    assert "What about last month? (meaning: Spending, 1 Sep to 30 Sep)" in model.prompts[-1]
    why = ask(api, "Why is it so high?", first["conversation_id"]).json()
    assert why["skill"] == "spending" and "wants more than the last answer gave" in model.prompts[-1]


def test_a_new_conversation_carries_nothing(api):
    signed_up(api)
    money_world(api)
    install(first_fact)
    ask(api, "How much did I spend this month?")
    fresh = ask(api, "What about last month?").json()  # no conversation id: nothing to continue
    assert fresh["skill"] == "clarify"  # the fake model routes nothing, and there is no earlier turn to lean on
