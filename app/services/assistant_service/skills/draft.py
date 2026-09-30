"""
draft (AI-42, AI-43): something to record or set up, handed back as a DRAFT.

"I just spent 250 on lunch at Jollibee" does not save an entry. It answers
with a button that opens the ordinary add sheet pre-filled; the user checks
it and saves through the normal path, which announces the write like any
other (`afterWrite(...MONEY)`). The assistant writes nothing, here or
anywhere (ARCHITECTURE §8).

Every field comes from the question's own words, read by the router: the
amount, a category or account the user named, a merchant, "yesterday". A
merchant typed before brings the category it was last filed under (TXN-24's
own memory). Nothing is guessed by the model, and no model is called.

"Help me save ₱50,000 for December" works the same way: the monthly amount is
goal_service.monthly_need (GOA-05's own rule), and the button opens the goal
sheet pre-filled.
"""

from app.core.utils.money import ZERO
from app.services import goal_service
from app.services.assistant_service.facts import Action, Facts, day, php


def transaction(ctx) -> Facts:
    intent = ctx.intent
    today = ctx.today
    if intent.amount is None or intent.amount <= ZERO:
        return Facts(
            skill="draft", title="A new entry", lines=[],
            template="How much was it? Tell me like: \"I spent 250 on lunch\" and I'll set the entry up for you "
                     "to check.",
            phrase=False, follow_ups=["I spent 250 on lunch", "I paid 1,500 for groceries yesterday"],
        )

    kind = "income" if intent.income else "expense"
    on = intent.on or today
    category_id = intent.category_id
    if category_id is None and intent.merchant:
        # TXN-24: what this merchant was filed under last time
        known = next((m for m in ctx.merchants if m.name.lower() == intent.merchant.lower() and m.type == kind), None)
        category_id = known.category_id if known else None
    category = ctx.categories.get(category_id) if category_id is not None else None
    if category is not None and category.kind != kind:
        category_id, category = None, None  # an expense category on an income (or the reverse) is never pre-filled
    account = next((a for a in ctx.visible_accounts if a.id == intent.account_id), None)

    parts = [f"{php(intent.amount)} {kind}"]
    if category is not None:
        parts.append(category.name)
    if intent.merchant:
        parts.append(f"at {intent.merchant}")
    if account is not None:
        parts.append(f"from {account.name}" if kind == "expense" else f"into {account.name}")
    parts.append("today" if on == today else day(on, today))
    missing = [] if category is not None else ["a category"]
    template = "Here's the entry, ready for you to check: " + ", ".join(parts) + "."
    if missing:
        template += " Pick a category before you save."
    template += " Nothing is saved until you save it."

    payload = {
        "type": kind, "amount": str(intent.amount), "txn_date": on.isoformat(),
        "category_id": category_id, "account_id": account.id if account else None,
        "merchant": intent.merchant, "notes": intent.item if intent.item and not intent.merchant else None,
    }
    return Facts(
        skill="draft", title="A new entry", lines=[], template=template, phrase=False,
        actions=[Action("draft_transaction", "Open the entry", payload=payload)],
    )


def goal(ctx) -> Facts:
    intent = ctx.intent
    today = ctx.today
    if intent.amount is None or intent.amount <= ZERO:
        return Facts(
            skill="draft_goal", title="A new goal", lines=[],
            template="How much do you want to save, and by when? Tell me like: \"Help me save ₱50,000 by December\".",
            phrase=False, follow_ups=["Help me save ₱50,000 by December", "Help me save ₱20,000 in 6 months"],
        )

    name = intent.item or "Savings"
    target_date = intent.on
    template = f"A goal of {php(intent.amount)}"
    if name != "Savings":
        template += f" for {name}"
    if target_date is not None:
        per_month, months = goal_service.monthly_need(intent.amount, today, target_date)
        template += f" by {day(target_date, today)}"
        if per_month is not None:
            template += f" means setting aside {php(per_month)} a month for {months} months"
    else:
        template += " with no date yet"
    template += ". Open it to choose the account and save it - nothing is set up until you do."

    payload = {"name": name[:60], "target": str(intent.amount),
               "target_date": target_date.isoformat() if target_date else None}
    return Facts(
        skill="draft_goal", title="A new goal", lines=[], template=template, phrase=False,
        actions=[Action("draft_goal", "Open the goal", payload=payload)],
        follow_ups=["How are my savings goals?"],
    )
