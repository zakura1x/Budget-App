"""
budget_status (AI-11): how much is left, the daily allowance, whether spending
is on pace, and one category's budget when the question names one.

Reads budget_service.status - the call behind GET /budgets/current and Home -
so every figure is the one Home shows.
"""

from decimal import Decimal

from app.core.utils.money import ZERO
from app.services.assistant_service.facts import Action, Facts, Source, day, days, names, pct, php
from app.services.budget_service import budget_service


def run(ctx) -> Facts:
    status = budget_service.status(ctx.db, ctx.cipher, today=ctx.today)
    source = Source("Budget", "/budget")
    if status is None:
        return Facts(
            skill="budget_status", title="Budget",
            lines=["No budget is set up yet."],
            template="You haven't set a budget yet. Set one on the Budget screen and I can tell you what's left "
                     "and how much you can spend each day.",
            sources=[source], actions=[Action("open_screen", "Set a budget", "/budget")],
            follow_ups=["Where did my money go this month?", "How much cash do I have?"],
        )

    a = status.allowance
    period = status.period
    title = f"Budget, {day(period.start, ctx.today)} to {day(period.end, ctx.today)}"
    lines = [
        f"The budget period runs {day(period.start, ctx.today)} to {day(period.end, ctx.today)}; "
        f"{days(a.days_left)} are left, today included.",
    ]
    if a.carried_in != ZERO:
        lines.append(f"Budget for the period: {php(a.budget)}, plus {php(a.carried_in)} carried over, "
                     f"so {php(a.available)} to spend.")
    else:
        lines.append(f"Budget for the period: {php(a.available)}.")
    lines.append(f"Spent so far this period: {php(a.spent)}.")
    if a.remaining >= ZERO:
        lines.append(f"Left to spend: {php(a.remaining)}.")
    else:
        lines.append(f"Over budget by {php(a.over_by)}.")
    lines.append(f"Daily allowance today: {php(a.daily)}. Spent today: {php(a.spent_today)}.")
    if a.left_today < ZERO:
        lines.append(f"Today's allowance is overspent by {php(-a.left_today)}.")

    elapsed = Decimal(a.days_elapsed) / Decimal(a.days_total) if a.days_total else Decimal(1)
    on_pace = a.used_ratio <= elapsed
    lines.append(f"{pct(a.used_ratio)} of the budget is used with {pct(elapsed)} of the period gone"
                 f" - {'on pace' if on_pace else 'spending faster than the period'}.")

    over = [ctx.category_names[c.category_id] for c in status.categories
            if c.over and c.category_id in ctx.category_names]
    if over:
        lines.append(f"Categories over their budget: {names(over[:5])}.")
    for alert in status.alerts[:3]:
        lines.append(f"Alert: {alert.message}")

    wanted = ctx.intent.category_id
    if wanted is not None:
        progress = next((c for c in status.categories if c.category_id == wanted), None)
        name = ctx.category_names.get(wanted, "That category")
        if progress is None:
            lines.append(f"{name} has no budget of its own in this period.")
        else:
            left = (f"{php(progress.remaining)} left" if progress.remaining >= ZERO
                    else f"over by {php(-progress.remaining)}")
            lines.append(f"{name}: {php(progress.spent)} spent of {php(progress.allocated)} budgeted, {left}.")

    if a.remaining >= ZERO:
        template = (f"You have {php(a.remaining)} left of your {php(a.available)} budget until "
                    f"{day(period.end, ctx.today)}, which is {php(a.daily)} a day for the next {days(a.days_left)}.")
        tone = "ok" if on_pace else "warn"
    else:
        template = (f"You're over this period's {php(a.available)} budget by {php(a.over_by)}, "
                    f"with {days(a.days_left)} to go until {day(period.end, ctx.today)}.")
        tone = "danger"

    return Facts(
        skill="budget_status", title=title, lines=lines, template=template, sources=[source],
        actions=[Action("open_screen", "Open budget", "/budget")], tone=tone,
        follow_ups=["Where did my money go this month?", "What bills are due before payday?"],
    )
