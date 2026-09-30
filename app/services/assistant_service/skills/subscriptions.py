"""
subscriptions (AI-20): what the user is subscribed to, what it costs a month,
what charges next, and what cancelling has saved (SUB-07).

Reads subscription_service.overview - the Subscriptions part of Recurring - so
the monthly total is SUB-05's own (active ones only).
"""

from app.core.utils.money import ZERO
from app.services import subscription_service
from app.services.assistant_service.facts import Action, Facts, Source, day, names, pct, php

LISTED = 8


def run(ctx) -> Facts:
    today = ctx.today
    o = subscription_service.overview(ctx.db, ctx.cipher, today=today)
    source = Source("Recurring", "/recurring")
    active = [i for i in o.items if not i.rule.paused and i.cancelled_on is None
              and (i.rule.end_on is None or i.rule.end_on >= today)]
    cancelled = [i for i in o.items if i.cancelled_on is not None]
    if not o.items:
        return Facts(
            skill="subscriptions", title="Subscriptions", lines=["No subscriptions are set up."],
            template="You don't have any subscriptions set up. Add one under Recurring and I'll keep track of it.",
            sources=[source], actions=[Action("open_screen", "Open recurring", "/recurring")],
        )

    lines = [f"Active subscriptions: {len(active)}, about {php(o.monthly_total)} a month in all."]
    if o.budget_share is not None:
        lines.append(f"That is {pct(o.budget_share)} of this month's budget.")
    if active:
        lines.append("Each, as a monthly cost: " + "; ".join(
            f"{i.rule.name} {php(i.monthly)}" for i in active[:LISTED]) + ".")
    if o.upcoming:
        lines.append("Charging in the next 30 days: " + "; ".join(
            f"{day(u.on, today)} {u.name} {php(u.amount)}" for u in o.upcoming[:LISTED]) + ".")
    for i in active:
        if i.cancel_by is not None:
            lines.append(f"You meant to cancel {i.rule.name} by {day(i.cancel_by, today)}.")
    if cancelled:
        saved = [i for i in cancelled if i.saved > ZERO]
        lines.append("Cancelled: " + "; ".join(
            f"{i.rule.name} on {day(i.cancelled_on, today)}" + (f", {php(i.saved)} saved since" if i.saved > ZERO else "")
            for i in cancelled[:LISTED]) + ".")
        if saved:
            lines.append(f"Saved by cancelling so far: {php(sum((i.saved for i in saved), ZERO))}.")

    biggest = sorted(active, key=lambda i: i.monthly, reverse=True)[:3]
    template = f"You have {len(active)} active {'subscription' if len(active) == 1 else 'subscriptions'}, about " \
               f"{php(o.monthly_total)} a month."
    if biggest:
        template += " The biggest: " + names([f"{i.rule.name} ({php(i.monthly)})" for i in biggest]) + "."
    return Facts(
        skill="subscriptions", title="Subscriptions", lines=lines, template=template, sources=[source],
        actions=[Action("open_screen", "Open recurring", "/recurring")],
        follow_ups=["What bills are due before payday?", "How much is left in my budget?"],
    )
