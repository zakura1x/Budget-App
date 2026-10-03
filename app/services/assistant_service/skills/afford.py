"""
afford (AI-30..35): "Can I buy a ₱18,000 phone?" - a verdict from rules, then
the numbers behind it and the other ways to do it.

The verdict comes from app/core/utils/affordability.py, which is pure. This
skill feeds it:

- The price, how it is paid (now, a card, or an installment) and over how
  many months, all read from the question's own words (router.find_amount /
  find_method). The model never sets a price.
- What is left of the budget period: budget_service.status, as on Home.
- The cash timeline: Months ahead (projection_service.project), rebuilt
  point by point the way it reads its own lowest point. Each month starts
  with its remaining budget already taken off, then every scheduled item on
  its day. So the verdict and the Months ahead screen can never disagree
  about the lowest point without the purchase.
- Money set aside for goals (GOA-08) and a week of essential spending
  (safety_service.essentials), for "tight".
- For a card, its available limit and the due date of the bill a purchase
  made today lands on (date_utils.due_date, as the card's own page).

Alternatives are computed, never suggested by the model: the first day it
would fit, what 6 and 12 monthly payments would do, and a goal that already
holds enough.
"""

from decimal import Decimal
from typing import List, Optional, Tuple

from app.core.utils import affordability as rules
from app.core.utils.date_utils import due_date
from app.core.utils.money import ZERO, total
from app.services import projection_service, recurring_service, safety_service
from app.services.assistant_service.facts import Action, Facts, Source, day, days, php
from app.services.budget_service import budget_service

INSTALLMENT_OPTIONS = (6, 12)
_WEEKS_PER_MONTH = Decimal(52) / Decimal(12)

# Best first - an alternative is offered only when it ranks better than the verdict asked about
RANK = {"yes": 0, "yes_over_budget": 1, "tight": 2, "wait": 3, "no": 4}

LABELS = {
    "yes": ("Yes", "ok"),
    "yes_over_budget": ("Yes, over budget", "warn"),
    "tight": ("Tight", "warn"),
    "wait": ("Wait", "warn"),
    "no": ("No", "danger"),
}


def timeline(projection, skip=None) -> Tuple[List[Tuple], List]:
    """
    (points, wait_dates) from Months ahead: its running cash line, and the days worth waiting for.
    `skip` is one scheduled item left out - the plan payment being asked about, which the price
    then stands for, so it is not taken off the cash line twice.
    """
    points: List[Tuple] = []
    waits = []
    for month in projection.months:
        live = [i for i in month.items if not i.paused and i is not skip]
        running = month.opening - (month.spending - month.committed)
        points.append((projection.today if month.current else month.start, running))
        # Same day: the money going out first - the cautious reading Months ahead uses too.
        for item in sorted(live, key=lambda i: (i.on, i.effect >= ZERO)):
            running += item.effect
            points.append((item.on, running))
            if item.type == "income" and item.kind != "interest" and item.effect > ZERO:
                waits.append(item.on)
        if not month.current:
            waits.append(month.start)
    return points, sorted(set(waits))


def _scheduled(ctx, projection):
    """
    The next payment of the plan the question names (`intent.rule_id`), as Months ahead holds it:
    the plan's own item, or - for a plan on a loan or a card with bills - the next bill on its account.
    """
    plan = next((r for r in recurring_service.list_rules(ctx.db, ctx.cipher, today=ctx.today)
                 if r.id == ctx.intent.rule_id), None)
    if plan is None:
        return None, None
    items = [i for m in projection.months for i in m.items if not i.paused and i.type == "expense"]
    own = [i for i in items if i.rule_id == plan.id]
    billed = [i for i in items if i.rule_id == 0 and i.account_id == plan.account_id and i.kind == "bill"]
    found = min(own or billed, key=lambda i: i.on, default=None)
    return plan, found


def _card(ctx) -> Optional[rules.Card]:
    cards = [v for v in ctx.visible_accounts if v.type == "credit" and v.credit is not None]
    named = [v for v in cards if v.id == ctx.intent.account_id]
    view = (named or cards or [None])[0]
    if view is None:
        return None
    c = view.credit
    return rules.Card(name=view.name, available=c.available,
                      bill_due=due_date(c.period_closes, c.statement_closing_day, c.payment_due_day))


def _method_text(method: str, months: int, card: Optional[rules.Card]) -> str:
    if method == "card" and card is not None:
        return f"on {card.name}"
    if method == "installment":
        return f"in {months} monthly payments"
    return "paid now"


def run(ctx) -> Facts:
    intent = ctx.intent
    today = ctx.today
    item = f"the {intent.item}" if intent.item else "it"
    if intent.amount is None or intent.amount <= ZERO:
        return Facts(
            skill="afford", title="Can I afford it?", lines=[],
            template="How much does it cost? Ask with the price, like: \"Can I afford a ₱15,000 phone?\" "
                     "or \"Can I buy shoes for ₱3,500 on my card?\"",
            phrase=False,
            follow_ups=["Can I afford a ₱15,000 phone?", "Can I buy a ₱40,000 laptop in 12 months?"],
        )

    price = intent.amount
    method = intent.method or "now"
    card = _card(ctx) if method == "card" else None
    if method == "card" and card is None:
        method = "now"  # no card to put it on
    months = intent.months or (INSTALLMENT_OPTIONS[0] if method == "installment" else 1)

    status = budget_service.status(ctx.db, ctx.cipher, today=today)
    budget = None
    if status is not None:
        a = status.allowance
        budget = rules.Budget(left=a.remaining, days_left=a.days_left, period_end=status.period.end)
    projection = projection_service.project(ctx.db, ctx.cipher, today=today, months=3)
    plan, planned = _scheduled(ctx, projection) if intent.rule_id else (None, None)
    if plan is not None:
        item = f"the {plan.name} payment"
    points, waits = timeline(projection, skip=planned)
    set_aside = total(v.set_aside for v in ctx.visible_accounts)
    essentials = safety_service.essentials(ctx.db, ctx.cipher, today=today)
    week = (essentials.monthly / _WEEKS_PER_MONTH).quantize(Decimal("0.01")) if essentials.monthly > ZERO else None

    def decide(how: str, count: int) -> rules.Result:
        return rules.decide(rules.Inputs(
            price=price, today=today, method=how, months=count, timeline=points, wait_dates=waits,
            set_aside=set_aside, essentials_week=week, budget=budget, card=card if how == "card" else None,
        ))

    result = decide(method, months)
    label, tone = LABELS[result.verdict]
    how = _method_text(method, months, card)
    subject = f"{item} for {php(price)}, {how}"
    lines = [f"Asked: {'paying' if plan is not None else 'buying'} {subject}."]
    if plan is not None and planned is not None:
        # 2026-10-03: "it is for the motorcycle installment plan" - a payment the plans already hold
        lines.append(f"{plan.name} is already scheduled: {php(planned.amount)} on {day(planned.on, today)}. "
                     f"This answer counts the {php(price)} once, in its place.")
    elif plan is not None:
        lines.append(f"{plan.name} has no payment scheduled in the next 3 months.")

    already_short = "cash_already_short" in result.reasons
    if already_short:
        tight_why = ("it fits your budget, but your budget is more than your cash: you were already heading below "
                     "zero without it.")
    elif "needs_set_aside" in result.reasons:
        tight_why = "it only works by using money you set aside for goals."
    else:
        tight_why = "it leaves your cash under a week of essential spending."
    fits = "fits in your budget and your cash stays above zero" if budget is not None else "leaves your cash above zero"
    verdict_text = {
        "yes": f"Yes - you can afford {item}: it {fits}.",
        "yes_over_budget": f"Yes, but it goes over your budget by {php(result.over_budget_by)}; your cash stays "
                           f"above zero.",
        "tight": f"It's tight - {tight_why}",
        "wait": f"Not yet - it fits if you buy it on or after {day(result.fits_from, today)}." if result.fits_from
                else "Not yet.",
        "no": ("No - the card's available limit is short by "
               f"{php(result.limit_short)}." if "card_limit" in result.reasons
               else "No - your cash would go below zero" + (
                   ", even counting the money set aside for goals." if set_aside > ZERO
                   else ", and waiting for your next income does not fix it.")),
    }[result.verdict]
    lines.append(f"Verdict: {verdict_text}")

    if budget is not None:
        booked = price if method != "installment" else result.charges[0][1]
        after = budget.left - booked
        if after >= ZERO:
            lines.append(f"It fits the budget: {php(budget.left)} is left in this period now (to "
                         f"{day(budget.period_end, today)}), and {php(after)} would be left after buying it.")
        else:
            lines.append(f"It does not fit the budget: the price is {php(result.over_budget_by)} more than the "
                         f"{php(max(budget.left, ZERO))} left in this period (to {day(budget.period_end, today)}).")
        if result.daily_after is not None:
            lines.append(f"Daily allowance for the rest of the period if you buy it today: "
                         f"{php(result.daily_after)} for {days(budget.days_left)}.")
    else:
        lines.append("No budget is set, so only cash is checked.")

    if result.lowest == result.lowest_without:
        lines.append(f"Your lowest cash on hand in the next 3 months stays {php(result.lowest)} (on "
                     f"{day(result.lowest_on, today)}), with or without it.")
    else:
        lines.append(f"With it, your lowest cash on hand in the next 3 months is {php(result.lowest)} (on "
                     f"{day(result.lowest_on, today)}). Without it, the lowest is {php(result.lowest_without)}.")
    if result.covered_by_budget > ZERO:
        lines.append(f"{php(result.covered_by_budget)} of the price is money Months ahead already counts as "
                     f"spent from your budget.")
    if method == "card" and card is not None:
        limit = f"{php(card.available)} of limit available" if card.available is not None else "no limit typed"
        lines.append(f"On {card.name}: {limit}; a purchase today is paid on the bill due {day(card.bill_due, today)}.")
    if method == "installment":
        first, last = result.charges[0], result.charges[-1]
        lines.append(f"{months} payments of about {php(first[1])} a month, {day(first[0], today)} to "
                     f"{day(last[0], today)}, before any interest the seller adds.")
    if set_aside > ZERO:
        lines.append(f"Money set aside for goals, not in cash on hand: {php(set_aside)}.")
    if week is not None and result.verdict == "tight" and "under_a_week_of_essentials" in result.reasons:
        lines.append(f"A week of essential spending is about {php(week)}.")

    # Alternatives - worked out here, never by the model (AI-31..33)
    if result.verdict == "wait" and result.fits_from is not None:
        why = next((i.name for m in projection.months for i in m.items
                    if i.on == result.fits_from and i.type == "income"), None)
        lines.append(f"From {day(result.fits_from, today)}" + (f", after {why} comes in," if why else ",")
                     + " your cash stays above zero with it.")
    if result.lowest_without < ZERO:
        lines.append(f"Even without it, Months ahead has your cash going below zero, to {php(result.lowest_without)}"
                     " - the budget and bills ahead are more than the money on hand.")
    if result.verdict in ("tight", "wait", "no") and method == "now" and not already_short:
        for count in INSTALLMENT_OPTIONS:
            option = decide("installment", count)
            if RANK[option.verdict] >= RANK[result.verdict]:
                continue  # only a way that does better is worth offering
            lines.append(f"In {count} monthly payments of about {php(option.charges[0][1])}: "
                         f"{LABELS[option.verdict][0].lower()} (lowest cash {php(option.lowest)}).")
    funded = [g for g in ctx.goals if g.kind != "emergency" and g.saved >= price]
    if funded and result.verdict != "yes":
        g = funded[0]
        lines.append(f"Your {g.name} goal already has {php(g.saved)} set aside, which would cover it.")

    if already_short:
        tight = (f"It's tight. {item[0].upper() + item[1:]} fits in your budget, but your budget is more than your "
                 f"cash: Months ahead already has you at {php(result.lowest_without)} without it.")
    elif "needs_set_aside" in result.reasons:
        tight = (f"It's tight. Buying {item} would bring your lowest cash on hand to {php(result.lowest)}, so it only "
                 f"works by using the {php(set_aside)} you've set aside for goals.")
    else:
        tight = (f"It's tight. Buying {item} would bring your lowest cash on hand to {php(result.lowest)}, under a "
                 f"week of essential spending.")
    template = {
        "yes": f"Yes, you can afford {item}. It {fits.replace('fits in your budget', 'fits in what is left of your budget')}"
               f" - the lowest in the next 3 months would be {php(result.lowest)}.",
        "yes_over_budget": f"Yes, but {item} takes you {php(result.over_budget_by)} over this period's budget. "
                           f"Your cash stays above zero - the lowest would be {php(result.lowest)}.",
        "tight": tight,
        "wait": f"Not yet. Bought today, {item} would take your cash to {php(result.lowest)}. It fits from "
                f"{day(result.fits_from, today)}." if result.fits_from else f"Not yet for {item}.",
        "no": (f"No - {card.name if card else 'the card'} doesn't have enough limit left; it's short by "
               f"{php(result.limit_short)}." if "card_limit" in result.reasons
               else f"No, not right now. {item[0].upper() + item[1:]} would take your cash to {php(result.lowest)}, "
                    f"and waiting a few months doesn't fix it."),
    }[result.verdict]

    actions = [Action("open_screen", "Open months ahead", "/projection")]
    if method == "installment" or result.verdict in ("tight", "wait", "no"):
        # AI-44: the same plan in the app's own what-if (REC-27), where it can be tried and saved
        actions.insert(0, Action("try_installment", "Try it as an installment", "/projection", {
            "name": (intent.item or "Purchase")[:60], "price": str(price),
            "payments": months if method == "installment" else INSTALLMENT_OPTIONS[0],
        }))
    return Facts(
        skill="afford", title=f"{'Paying' if plan is not None else 'Buying'} {item} for {php(price)}", lines=lines, template=template,
        sources=[Source("Budget", "/budget"), Source("Months ahead", "/projection")], actions=actions,
        tone=tone, label=label, verdict=result.verdict, verdict_text=verdict_text,
        follow_ups=["What bills are due before payday?", "How much is left in my budget?"],
    )

