"""
card (AI-15): what a card owes, the next payment and its due date, the limit
left, and the open statement - for the card the question names, or every card.

Reads the CreditView that GET /accounts returns, so each figure is the one the
card's tile and page show: `owed_with_plans` as what the card owes (REC-14),
`due_now` for a card with bills typed from its app (ACC-35), else `amount_due`.
"""

from app.core.utils.money import ZERO
from app.services.assistant_service.facts import Action, Facts, Source, day, days, php

LISTED = 4


def _card_lines(view, today):
    c = view.credit
    lines = [f"{view.name}: owes {php(c.owed_with_plans)} in all"
             + (f", of which {php(c.unpaid_installments)} is installments not billed yet"
                if c.unpaid_installments > ZERO else "") + "."]
    if c.due_now is not None:
        lines.append(f"{view.name}: {php(c.due_now)} is due now by its bills; the next due date is "
                     f"{day(c.payment_due, today)} ({days(c.due_in_days)} away).")
        payment = c.due_now
    else:
        closing = c.due_for_statement_closing
        lines.append(f"{view.name}: next payment {php(c.amount_due)} due {day(c.payment_due, today)} "
                     f"({days(c.due_in_days)} away), for the statement that "
                     f"{'closed' if closing < today else 'closes'} {day(closing, today)}.")
        payment = c.amount_due
    lines.append(f"{view.name}: the open statement runs {day(c.period_start, today)} to "
                 f"{day(c.period_closes, today)}, with {php(c.period_spend)} of purchases so far.")
    if c.available is not None and c.limit is not None:
        lines.append(f"{view.name}: {php(c.available)} of the {php(c.limit)} credit limit is available.")
    if c.spending_limit is not None and c.limit_left is not None:
        left = (f"{php(c.limit_left)} left" if c.limit_left >= ZERO else f"over by {php(-c.limit_left)}")
        lines.append(f"{view.name}: your own spending limit of {php(c.spending_limit)} this statement - {left}.")
    return lines, payment


def run(ctx) -> Facts:
    today = ctx.today
    cards = [v for v in ctx.visible_accounts if v.type == "credit" and v.credit is not None]
    wanted = ctx.intent.account_id
    if wanted is not None and any(v.id == wanted for v in cards):
        cards = [v for v in cards if v.id == wanted]
    source = Source("Accounts", "/accounts")
    if not cards:
        return Facts(
            skill="card", title="Credit cards", lines=["No credit card is set up."],
            template="You don't have a credit card set up. Add one on the Accounts tab and I can track its bills.",
            sources=[source], actions=[Action("open_screen", "Open accounts", "/accounts")],
        )

    lines = []
    summaries = []
    tone = "ok"
    for view in cards[:LISTED]:
        card_lines, payment = _card_lines(view, today)
        lines += card_lines
        if payment > ZERO:
            summaries.append(f"{view.name} {php(payment)} due {day(view.credit.payment_due, today)}")
            if view.credit.due_soon:
                tone = "warn"
        if view.credit.available is not None and view.credit.available < ZERO:
            tone = "danger"

    if len(cards) == 1:
        view = cards[0]
        c = view.credit
        payment = c.due_now if c.due_now is not None else c.amount_due
        template = f"{view.name} owes {php(c.owed_with_plans)} in all."
        template += (f" The next payment is {php(payment)}, due {day(c.payment_due, today)}." if payment > ZERO
                     else " Nothing is due right now.")
    else:
        template = ("Next payments: " + "; ".join(summaries) + ".") if summaries else "No card payment is due right now."

    route = f"/accounts/{cards[0].id}" if len(cards) == 1 else "/accounts"
    return Facts(
        skill="card", title="Credit cards" if len(cards) > 1 else cards[0].name, lines=lines, template=template,
        sources=[source], actions=[Action("open_screen", "Open card" if len(cards) == 1 else "Open accounts", route)],
        tone=tone, follow_ups=["What bills are due before payday?", "How much cash do I have?"],
    )
