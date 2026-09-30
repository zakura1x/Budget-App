"""
review (AI-17): "How did I do last month?" - the last finished period, looked
back on. Reads stats_service.review, the call behind the Review screen
(STA-12), so the figures are that screen's.
"""

from app.core.utils.money import ZERO
from app.services import stats_service
from app.services.assistant_service.facts import Action, Facts, Source, balance_line, day, names, php

TOP = 3


def run(ctx) -> Facts:
    today = ctx.today
    r = stats_service.review(ctx.db, ctx.cipher, today=today)
    label = f"{day(r.period.start, today)} to {day(r.period.end, today)}"
    lines = [
        f"Period looked back on: {label}.",
        balance_line(r.spent, r.earned),
    ]
    change = r.spent - r.previous_spent
    if r.previous_spent > ZERO:
        lines.append(f"The period before had {php(r.previous_spent)} of spending, so this one was "
                     f"{php(abs(change))} {'more' if change > ZERO else 'less'}.")
    if r.budget is not None:
        b = r.budget
        state = (f"{php(b.remaining)} under budget" if b.remaining >= ZERO else f"{php(-b.remaining)} over budget")
        lines.append(f"Budget: {php(b.spent)} spent of {php(b.available)} - {state}.")
    ups = sorted((c for c in r.changes if c.change > ZERO), key=lambda c: c.change, reverse=True)[:TOP]
    downs = sorted((c for c in r.changes if c.change < ZERO), key=lambda c: c.change)[:TOP]
    name = lambda c: ctx.category_names.get(c.category_id, "Unrecorded changes")  # noqa: E731
    if ups:
        lines.append("Went up most: " + "; ".join(
            f"{name(c)} {php(c.amount)} (was {php(c.previous)})" for c in ups) + ".")
    if downs:
        lines.append("Went down most: " + "; ".join(
            f"{name(c)} {php(c.amount)} (was {php(c.previous)})" for c in downs) + ".")
    if r.purchases:
        lines.append("Biggest purchases: " + "; ".join(
            f"{day(p.on, today)} {p.merchant or ctx.category_names.get(p.category_id, 'a purchase')} {php(p.amount)}"
            for p in r.purchases[:TOP]) + ".")
    if r.cashback > ZERO:
        lines.append(f"Cashback credited: {php(r.cashback)}.")
    if r.interest > ZERO:
        lines.append(f"Savings interest credited: {php(r.interest)}.")
    lines.append(f"Cash on hand went from {php(r.cash_start)} to {php(r.cash_end)}.")

    if r.budget is not None:
        verdict = "under" if r.budget.remaining >= ZERO else "over"
        amount = abs(r.budget.remaining)
        template = f"From {label} you spent {php(r.spent)}, {php(amount)} {verdict} your budget."
    else:
        template = f"From {label} you spent {php(r.spent)} and earned {php(r.earned)}."
    if ups:
        template += f" {names([name(c) for c in ups])} went up the most."

    tone = None
    if r.budget is not None:
        tone = "ok" if r.budget.remaining >= ZERO else "danger"
    return Facts(
        skill="review", title=f"Review, {label}", lines=lines, template=template,
        sources=[Source("Monthly review", "/review")], actions=[Action("open_screen", "Open the review", "/review")],
        tone=tone, follow_ups=["Where did my money go this month?", "How much is left in my budget?"],
    )
