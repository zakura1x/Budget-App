"""
emergency (AI-19): "Is my emergency fund enough?" - how long the emergency
money lasts, the target the advisor's rules set, and what reaches it.

Reads safety_service.advice, the call behind the Emergency fund screen
(GOA-10/11). The target comes from app/core/utils/emergency.py's rules and is
repeated here with the rules that fired - never re-judged.
"""

from decimal import Decimal

from app.core.utils.money import ZERO
from app.services import safety_service
from app.services.assistant_service.facts import Action, Facts, Source, php


def _months(value: Decimal) -> str:
    text = f"{value.normalize():f}" if value == value.to_integral() else f"{value:.1f}"
    return f"{text} month" if value == 1 else f"{text} months"


def run(ctx) -> Facts:
    a = safety_service.advice(ctx.db, ctx.cipher, today=ctx.today)
    source = Source("Emergency fund", "/emergency")
    where = "your emergency fund goal" if a.source == "goal" else "your cash on hand (no emergency fund goal is set)"
    lines = [f"Emergency money: {php(a.money)}, counted from {where}."]
    if a.measurable:
        guess = " (a guess: 70% of all spending, since no category is marked essential)" if a.essentials.guessing else ""
        lines.append(f"Essential spending: about {php(a.essentials.monthly)} a month, averaged over "
                     f"{a.essentials.months} months{guess}.")
        lines.append(f"At that rate the {php(a.money)} of emergency money lasts {_months(a.cover_months)}.")
    else:
        lines.append("There is no essential spending recorded yet to measure it against.")
    lines.append(f"The target is {php(a.target)}, which is {_months(Decimal(a.target_months))} of essential spending.")
    gap = a.money - a.target
    lines.append(f"The emergency money is {php(abs(gap))} {'above' if gap >= ZERO else 'below'} the target.")
    if a.fired:
        lines.append("Why that target: " + "; ".join(f.text for f in a.fired) + ".")
    if not a.answered:
        lines.append("The three questions on the Emergency fund screen (work, dependents, earners) are not answered "
                     "yet, so the target uses the defaults.")
    if a.per_month > ZERO:
        lines.append(f"{php(a.per_month)} a month reaches the target in {safety_service.CATCH_UP_MONTHS} months.")
    if a.short_history:
        lines.append("There are fewer than three months of income recorded, so only the base target applies.")

    reached = a.money >= a.target
    if not a.measurable:
        template = (f"You have {php(a.money)} as emergency money. Record a few months of spending and I can tell you "
                    f"how long it lasts.")
    elif reached:
        template = (f"Yes. Your {php(a.money)} lasts about {_months(a.cover_months)}, which meets your "
                    f"{_months(Decimal(a.target_months))} target of {php(a.target)}.")
    else:
        template = (f"Not yet. Your {php(a.money)} lasts about {_months(a.cover_months)}; the target is "
                    f"{_months(Decimal(a.target_months))}, {php(a.target)}. Setting aside {php(a.per_month)} a month "
                    f"gets you there in {safety_service.CATCH_UP_MONTHS} months.")
    return Facts(
        skill="emergency", title="Emergency fund", lines=lines, template=template, sources=[source],
        actions=[Action("open_screen", "Open emergency fund", "/emergency")],
        tone="ok" if reached else "warn",
        follow_ups=["How are my savings goals?", "Can I afford a ₱15,000 phone?"],
    )
