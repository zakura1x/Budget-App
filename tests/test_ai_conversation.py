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


# ------------------------------------------------- the screenshot, 2026-10-03 (misc/AI-Test)


def test_if_i_paid_is_a_question_not_an_entry_to_record():
    asked = router.by_rules("If I paid a 7000 bill for papa bern, Will my budget be sufficient for the month?", D, {}, {})
    assert (asked.skill, asked.amount) == ("afford", Decimal("7000.00"))
    for message in ("Will my budget be enough if I spend 3,000?", "Sapat ba ang budget ko kung bumili ako ng 2,000?"):
        assert router.by_rules(message, D, {}, {}).skill == "afford", message
    assert router.by_rules("I paid 1,500 for groceries yesterday", D, {}, {}).skill == "draft"  # it happened


def test_it_is_for_says_what_the_last_question_was_about():
    plans = {9: "Motorcycle"}
    asked = router.by_rules("If I paid a 7000 bill for papa bern, Will my budget be sufficient?", D, {}, {},
                            plans=plans)
    message = "It is for the motorcycle installment plan"
    more = router.follow_up(message, router.by_rules(message, D, {}, {}, plans=plans), asked)
    # the same 7,000 - now known to be the plan's payment - and NOT turned into a new installment purchase
    assert (more.skill, more.amount, more.rule_id, more.method) == ("afford", Decimal("7000.00"), 9, None)


def test_it_is_for_fills_in_a_draft():
    drafted = router.by_rules("I paid 7000 for the bill today", D, {}, {})
    message = "It is for the motorcycle installment plan"
    more = router.follow_up(message, router.by_rules(message, D, {}, {}), drafted)
    assert (more.skill, more.amount, more.item) == ("draft", Decimal("7000.00"), "motorcycle installment plan")


def _motorcycle(api):
    papa = api.post("/accounts", {"name": "Papa Bern", "type": "borrowed"}).json()["id"]
    vehicle = api.post("/categories", {"name": "Vehicle"}).json()["id"]
    made = api.post("/recurring?today=2026-10-10", {
        "kind": "installment", "type": "expense", "name": "Motorcycle", "account_id": papa,
        "category_id": vehicle, "frequency": "monthly", "start": "2026-10-25", "price": "84000.00", "payments": 12})
    assert made.status_code == 201, made.text


def test_a_payment_the_plans_already_hold_is_counted_once(api):
    signed_up(api)
    money_world(api)
    _motorcycle(api)
    install(first_fact)
    first = ask(api, "If I paid a 7000 bill for papa bern, Will my budget be sufficient for the month?").json()
    assert first["skill"] == "afford"
    more = ask(api, "It is for the motorcycle installment plan", first["conversation_id"]).json()
    assert more["skill"] == "afford" and more["title"].startswith("Paying the Motorcycle payment")
    line = next(f for f in more["facts"] if "already scheduled" in f)
    assert "₱7,000.00 on 25 Oct" in line


def test_a_draft_takes_what_it_was_for_from_the_next_message(api):
    signed_up(api)
    money_world(api)
    install(first_fact)
    drafted = ask(api, "I paid 7000 for the bill today").json()
    more = ask(api, "It is for the motorcycle installment plan", drafted["conversation_id"]).json()
    assert more["skill"] == "draft"
    payload = more["actions"][0]["payload"]
    assert (payload["amount"], payload["notes"]) == ("7000.00", "motorcycle installment plan")


# ------------------------------------------------- misc/AI-Test IMG_4148-4149, 2026-10-03


def _five_thousand_on_the_30th(api):
    papa = api.post("/accounts", {"name": "Papa Bern", "type": "borrowed"}).json()["id"]
    vehicle = api.post("/categories", {"name": "Vehicle"}).json()["id"]
    made = api.post("/recurring?today=2026-10-10", {
        "kind": "installment", "type": "expense", "name": "Motorcycle", "account_id": papa,
        "category_id": vehicle, "frequency": "monthly", "start": "2026-10-30", "price": "60000.00", "payments": 12})
    assert made.status_code == 201, made.text


def _money(line, label):
    import re
    found = re.search(label + r" (-?)₱([\d,]+\.\d\d)", line)
    return Decimal(found.group(1) + found.group(2).replace(",", ""))


def test_paying_more_today_in_place_of_a_held_payment_costs_only_the_difference(api):
    """The 5,000 due on the 30th is already held back from cash on hand; 7,000 instead costs 2,000 more."""
    signed_up(api)
    money_world(api)
    _five_thousand_on_the_30th(api)
    install(first_fact)
    reply = ask(api, "If I paid 7000 bill for my installment plan motorcycle today, Will my budget still be "
                     "sufficient for the month?").json()
    assert reply["skill"] == "afford" and reply["title"].startswith("Paying the Motorcycle payment")
    assert any("already scheduled: ₱5,000.00 on 30 Oct" in f for f in reply["facts"])
    lowest = next(f for f in reply["facts"] if f.startswith("With it, your lowest") or "stays" in f)
    if lowest.startswith("With it"):
        assert _money(lowest, "Without it, the lowest is") - _money(lowest, "is") <= Decimal("2000.00")
    assert not any(a["kind"] == "try_installment" for a in reply["actions"])  # a plan payment is not a purchase


def test_what_i_meant_corrects_the_last_question_instead_of_starting_over(api):
    signed_up(api)
    money_world(api)
    _five_thousand_on_the_30th(api)
    install(first_fact)
    first = ask(api, "If I paid 7000 bill for my installment plan motorcycle today, Will my budget still be "
                     "sufficient for the month?").json()
    meant = ask(api, "What I meant is that I will not pay for the 5000 this 30th instead I will pay 7000 today",
                first["conversation_id"]).json()
    assert meant["skill"] == "afford" and meant["title"] == first["title"]  # the same plan payment, 7,000


def test_a_message_nothing_can_place_continues_the_conversation_when_the_model_is_down(api):
    signed_up(api)
    money_world(api)
    install(lambda prompt: RuntimeError("IBM rejected the key"))
    first = ask(api, "Can I afford a 15,000 phone?").json()
    vague = ask(api, "hmm I will think about the one with the bigger screen", first["conversation_id"]).json()
    assert vague["skill"] == "afford"  # not "I'm not sure what you mean"
    alone = ask(api, "hmm I will think about the one with the bigger screen").json()
    assert alone["skill"] == "clarify"  # with no conversation there is nothing to continue


def test_a_no_says_when_cash_was_short_without_it():
    from app.core.utils import affordability as rules

    today = date(2026, 10, 10)
    result = rules.decide(rules.Inputs(
        price=Decimal("7000.00"), today=today, method="now", months=1,
        timeline=[(today, Decimal("1000.00")), (date(2026, 10, 30), Decimal("-30000.00"))],
        wait_dates=[], set_aside=Decimal("0"), essentials_week=None))
    assert result.verdict == "no" and result.lowest_without == Decimal("-30000.00")
