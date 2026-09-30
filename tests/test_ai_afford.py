"""
The AI companion's A3 (misc/AI/PHASES.md): "can I afford it?" and the six
skills that look further - review, goals, emergency fund, subscriptions,
payoff, how-to.

The verdict rules are pure, so most of their table is tested without a
database. Every skill is also held to the figure its own screen shows, and
an affordability question is shown to write nothing.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.utils import affordability as rules
from app.db.models import RecurringRule, Transaction
from app.services.assistant_service import router, verifier
from app.services.assistant_service.facts import day, php
from tests.test_ai_assistant import TODAY, TODAY_DATE, _fresh, ask, first_fact, install, money_world, signed_up  # noqa: F401

D = TODAY_DATE


def inputs(price, *, timeline=None, waits=(), set_aside="0.00", week=None, budget=None, method="now", months=1,
           card=None):
    return rules.Inputs(
        price=Decimal(price), today=D, method=method, months=months,
        timeline=timeline if timeline is not None else [(D, Decimal("10000.00"))],
        wait_dates=list(waits), set_aside=Decimal(set_aside),
        essentials_week=Decimal(week) if week else None, budget=budget, card=card,
    )


BUDGET = rules.Budget(left=Decimal("5000.00"), days_left=10, period_end=D + timedelta(days=9))


# ---------------------------------------------------------- the pure rules


def test_fits_the_budget_and_cash():
    r = rules.decide(inputs("3000.00", budget=BUDGET))
    assert (r.verdict, r.covered_by_budget, r.extra, r.lowest) == ("yes", Decimal("3000.00"), Decimal("0.00"),
                                                                   Decimal("10000.00"))
    assert r.daily_after == Decimal("200.00")


def test_over_the_budget_but_cash_is_fine():
    r = rules.decide(inputs("8000.00", budget=BUDGET))
    assert (r.verdict, r.over_budget_by, r.extra, r.lowest) == ("yes_over_budget", Decimal("3000.00"),
                                                                Decimal("3000.00"), Decimal("7000.00"))


def test_wait_for_the_income_that_makes_it_fit():
    timeline = [(D, Decimal("10000.00")), (D + timedelta(days=5), Decimal("30000.00"))]
    r = rules.decide(inputs("12000.00", timeline=timeline, waits=[D + timedelta(days=5)]))
    assert (r.verdict, r.fits_from, r.lowest) == ("wait", D + timedelta(days=5), Decimal("-2000.00"))


def test_tight_when_only_the_money_set_aside_covers_it():
    r = rules.decide(inputs("12000.00", set_aside="5000.00"))
    assert r.verdict == "tight" and "needs_set_aside" in r.reasons


def test_no_when_even_the_money_set_aside_falls_short():
    assert rules.decide(inputs("20000.00", set_aside="5000.00")).verdict == "no"


def test_tight_when_under_a_week_of_essentials():
    r = rules.decide(inputs("8000.00", week="3000.00"))
    assert (r.verdict, r.lowest) == ("tight", Decimal("2000.00"))


def test_a_purchase_inside_the_budget_is_not_blamed_for_a_short_budget():
    short = [(D, Decimal("-4000.00"))]  # the budget is more than the money, before any purchase
    r = rules.decide(inputs("500.00", timeline=short, budget=BUDGET))
    assert (r.verdict, r.reasons, r.extra) == ("tight", ["cash_already_short"], Decimal("0.00"))
    assert rules.decide(inputs("9000.00", timeline=short, budget=BUDGET)).verdict == "no"  # 4,000 of it is extra


def test_exactly_zero_left_still_fits():
    assert rules.decide(inputs("10000.00")).verdict == "yes"
    assert rules.decide(inputs("10000.01")).verdict == "no"


def test_a_card_pays_on_its_bill_and_needs_the_limit():
    timeline = [(D, Decimal("3000.00")), (D + timedelta(days=10), Decimal("23000.00"))]
    card = rules.Card(name="BPI Card", available=Decimal("50000.00"), bill_due=D + timedelta(days=20))
    assert rules.decide(inputs("5000.00", timeline=timeline)).verdict == "no"  # paid today: below zero
    on_card = rules.decide(inputs("5000.00", timeline=timeline, method="card", card=card))
    assert on_card.verdict == "yes" and on_card.charges == ((D + timedelta(days=20), Decimal("5000.00")),)
    short = rules.Card(name="BPI Card", available=Decimal("1000.00"), bill_due=D + timedelta(days=20))
    refused = rules.decide(inputs("5000.00", timeline=timeline, method="card", card=short))
    assert (refused.verdict, refused.limit_short) == ("no", Decimal("4000.00"))


def test_an_installment_splits_the_price_to_the_centavo():
    plan = rules.schedule(Decimal("3000.01"), D, "installment", 3, None)
    assert [a for _, a in plan] == [Decimal("1000.00"), Decimal("1000.00"), Decimal("1000.01")]
    assert [d for d, _ in plan] == [D, date(2026, 11, 10), date(2026, 12, 10)]


def test_an_installment_can_fit_where_paying_now_does_not():
    timeline = [(D, Decimal("4000.00")), (date(2026, 11, 1), Decimal("9000.00")), (date(2026, 12, 1), Decimal("14000.00"))]
    assert rules.decide(inputs("9000.00", timeline=timeline)).verdict != "yes"
    assert rules.decide(inputs("9000.00", timeline=timeline, method="installment", months=3)).verdict == "yes"


def test_a_price_must_be_positive():
    with pytest.raises(ValueError):
        rules.decide(inputs("0.00"))


# --------------------------------------------------------------- the router


@pytest.mark.parametrize(
    "question, amount, method, months",
    [
        ("Can I afford a ₱18,000 phone?", "18000.00", None, None),
        ("can i buy a laptop for 45k", "45000.00", None, None),
        ("Can I get a phone for 15,000 pesos in 6 months?", "15000.00", "installment", 6),
        ("Can I buy shoes for 3500 on my card?", "3500.00", "card", None),
        ("Kaya ko bang bumili ng ₱5,000 na sapatos?", "5000.00", None, None),
        ("Can I afford a PS5 at PHP 28,990.50 x 12", "28990.50", "installment", 12),
        ("Can I afford it?", None, None, None),
    ],
)
def test_prices_and_ways_to_pay_come_from_the_words(question, amount, method, months):
    intent = router.by_rules(question, D, {}, {})
    assert intent.skill == "afford"
    assert intent.amount == (Decimal(amount) if amount else None)
    assert (intent.method, intent.months) == (method, months)


@pytest.mark.parametrize(
    "question, skill",
    [
        ("How do I add an expense?", "how_to"),
        ("What is cash on hand?", "how_to"),
        ("Paano mag-transfer?", "how_to"),
        ("Can I afford a ₱15,000 phone on my card?", "afford"),
        ("Is my emergency fund enough?", "emergency"),
        ("Which debt should I pay off first?", "payoff"),
        ("When will I be debt-free?", "payoff"),
        ("How did I do last month?", "review"),
        ("How are my savings goals?", "goals"),
        ("What subscriptions do I have?", "subscriptions"),
        ("How much do I owe on my card?", "card"),
    ],
)
def test_the_new_skills_route(question, skill):
    assert router.by_rules(question, D, {}, {}).skill == skill


def test_a_goal_named_in_the_question():
    intent = router.by_rules("How's my Japan trip?", D, {}, {}, {7: "Japan trip"})
    assert (intent.skill, intent.goal_id) == ("goals", 7)


def test_the_model_never_sets_a_price():
    rules_intent = router.by_rules("could I get that thing", D, {}, {})
    model = router.Intent(skill="afford", amount=Decimal("99999.00"), by_model=True)
    assert router.merge(rules_intent, model).amount is None


# ---------------------------------------------------------- verdict check


@pytest.mark.parametrize(
    "reply, verdict, ok",
    [
        ("Yes, go ahead - it fits.", "yes", True),
        ("No, you can't afford it.", "yes", False),
        ("Yes, you can buy it!", "no", False),
        ("Not yet - it fits from 15 Oct.", "wait", True),
        ("Sure, you can afford it.", "wait", False),
        ("It's tight: it leaves ₱4,210.00.", "tight", True),
        ("Oo, kaya mo.", "no", False),
    ],
)
def test_a_reply_may_not_contradict_the_verdict(reply, verdict, ok):
    assert verifier.check(reply, ["Lowest: ₱4,210.00 on 15 Oct."], verdict=verdict).ok is ok


def test_tight_is_neither_a_yes_nor_a_no():
    facts = ["Lowest: ₱1,311.00 on 13 Dec."]
    assert verifier.check("No, that is not possible.", facts, verdict="tight").reason == "against_verdict"
    assert verifier.check("Yes, it fits.", facts, verdict="tight").reason == "against_verdict"


@pytest.mark.parametrize(
    "reply, reason",
    [
        ("You should pay off the card first.", "advice"),
        ("Pay off the BPI Card first, it is the smallest.", "advice"),
        ("It leaves ₱1,311.00. I recommend waiting.", "advice"),
        ("Buying it now is not advisable.", "advice"),
        ("Based on the snowball method, pay off the BPI Card first.", "advice"),
        ("You need to pay ₱1,311.00 on 13 Dec.", ""),  # a bill stated, not advice
        ("Not yet - it fits if you buy it on or after 13 Dec.", ""),
        ("Dapat mong bayaran muna ang card.", "advice"),
        ("The facts do not show when you will be debt-free.", "meta"),
        ("By snowball order, BPI Card clears first.", ""),
        ("You pay ₱1,311.00 on 13 Dec.", ""),
    ],
)
def test_a_reply_describes_and_never_advises(reply, reason):
    assert verifier.check(reply, ["₱1,311.00 on 13 Dec."]).reason == reason


# ---------------------------------------------------------------- through the API


def _counts(session):
    return (session.execute(select(func.count(Transaction.id))).scalar_one(),
            session.execute(select(func.count(RecurringRule.id))).scalar_one())


def test_afford_small_and_large(api, session):
    signed_up(api)
    money_world(api)
    install(lambda p: RuntimeError("model down"))
    # The budget here (30,000) is more than the cash, so Months ahead is below zero before any purchase:
    # a lunch that fits the budget is "tight", and the facts say the shortfall is not the lunch's.
    short = ask(api, "Can I afford a ₱500 lunch?").json()
    assert (short["skill"], short["verdict"]) == ("afford", "tight")
    assert "Even without it" in " ".join(short["facts"])
    api.post("/accounts", {"name": "Buffer", "type": "cash", "opening_balance": "100000.00"})
    before = _counts(session)
    small = ask(api, "Can I afford a ₱500 lunch?").json()
    assert (small["skill"], small["verdict"], small["label"], small["tone"]) == ("afford", "yes", "Yes", "ok")
    big = ask(api, "Can I buy a ₱5,000,000 condo?").json()
    assert big["verdict"] == "no" and big["tone"] == "danger"
    plan = ask(api, "Can I get a ₱60,000 laptop in 12 months?").json()
    assert "12 payments" in " ".join(plan["facts"])
    assert _counts(session) == before  # asking wrote nothing


def test_afford_reads_months_ahead_lowest_point(api):
    signed_up(api)
    money_world(api)
    install(lambda p: RuntimeError("model down"))
    reply = ask(api, "Can I afford a ₱500 lunch?").json()
    months = api.get(f"/projection?today={TODAY}&months=3").json()["months"]
    lowest = min(Decimal(m["low_point"]) for m in months)
    assert f"stays {php(lowest)}" in " ".join(reply["facts"])  # a lunch inside the budget moves nothing


def test_afford_without_a_price_asks_for_one(api):
    signed_up(api)
    install(first_fact)
    reply = ask(api, "Can I afford it?").json()
    assert reply["skill"] == "afford" and "How much does it cost" in reply["text"] and reply["verdict"] is None


def test_a_model_reply_against_the_verdict_is_replaced(api):
    signed_up(api)
    money_world(api)
    install(lambda p: "Yes, go ahead and buy it.")
    reply = ask(api, "Can I buy a ₱5,000,000 condo?").json()
    assert reply["verdict"] == "no" and reply["ai_phrased"] is False and reply["text"].startswith("No")


def test_the_prompt_carries_the_decided_answer(api):
    signed_up(api)
    money_world(api)
    model = install(first_fact)
    ask(api, "Can I afford a ₱500 lunch?")
    assert "The answer is already decided" in model.prompts[-1] and "you should" in model.prompts[-1]


def test_goals_answer_is_the_goals_screen(api):
    signed_up(api)
    wallet, _, _ = money_world(api)
    goal = api.post("/goals", {"name": "Japan trip", "target": "60000.00", "account_id": wallet,
                               "target_date": "2027-03-31"}).json()
    api.post(f"/goals/{goal['id']}/add?today={TODAY}", {"amount": "1500.00"})
    install(lambda p: RuntimeError("model down"))
    reply = ask(api, "How is my Japan trip goal?").json()
    screen = next(g for g in api.get(f"/goals?today={TODAY}").json() if g["id"] == goal["id"])
    assert reply["skill"] == "goals"
    assert php(Decimal(screen["saved"])) in reply["text"] and php(Decimal(screen["per_month"])) in reply["text"]


def test_emergency_answer_is_the_emergency_screen(api):
    signed_up(api)
    money_world(api)
    install(lambda p: RuntimeError("model down"))
    reply = ask(api, "Is my emergency fund enough?").json()
    screen = api.get(f"/goals/emergency?today={TODAY}").json()
    assert reply["skill"] == "emergency"
    assert php(Decimal(screen["money"])) in reply["text"] and php(Decimal(screen["target"])) in " ".join(reply["facts"])


def test_subscriptions_answer_is_the_subscriptions_figure(api):
    signed_up(api)
    wallet, _, food = money_world(api)
    api.post(f"/recurring?today={TODAY}", {"kind": "subscription", "type": "expense", "name": "Netflix",
                                            "amount": "549.00", "account_id": wallet, "category_id": food,
                                            "frequency": "monthly", "start": "2026-10-20"})
    install(lambda p: RuntimeError("model down"))
    reply = ask(api, "What subscriptions do I have?").json()
    screen = api.get(f"/subscriptions?today={TODAY}").json()
    assert php(Decimal(screen["monthly_total"])) in reply["text"] and "Netflix" in reply["text"]


def test_payoff_answer_is_the_payoff_screen(api):
    signed_up(api)
    money_world(api)
    install(lambda p: RuntimeError("model down"))
    reply = ask(api, "Which debt should I pay off first?").json()
    screen = api.post(f"/projection/payoff?today={TODAY}", {}).json()
    assert reply["skill"] == "payoff"
    debts = " ".join(reply["facts"])
    for debt in screen["debts"]:
        assert php(Decimal(debt["owed"])) in debts
    if screen["as_is"]["debt_free"]:
        assert day(date.fromisoformat(screen["as_is"]["debt_free"]), TODAY_DATE) in reply["text"]


def test_review_answer_is_the_review_screen(api):
    signed_up(api)
    money_world(api)
    install(lambda p: RuntimeError("model down"))
    reply = ask(api, "How did I do last month?").json()
    screen = api.get(f"/stats/review?today={TODAY}").json()
    assert reply["skill"] == "review" and php(Decimal(screen["spent"])) in reply["text"]


def test_how_to_needs_no_model_and_sends_nothing(api):
    signed_up(api)
    model = install(first_fact)
    reply = ask(api, "How do I add an expense?").json()
    assert reply["skill"] == "how_to" and "+" in reply["text"] and reply["actions"]
    assert model.prompts == []
