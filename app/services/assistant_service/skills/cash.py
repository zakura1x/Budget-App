"""
cash (AI-13): cash on hand, what is in each account that counts, net worth, and
one account's balance when the question names it.

Reads the same list_accounts / cash_on_hand / net_worth trio as GET /accounts,
so the headline matches the Accounts tab and Home. Cash on hand already leaves
out money set aside for goals (GOA-08) and counts a card with bills by what is
due now (ACC-35); this skill repeats those figures, it never rebuilds them.
"""

from app.core.utils.money import ZERO, total
from app.services import account_service
from app.services.assistant_service.facts import Action, Facts, Source, php

LISTED = 8


def _money_in(view) -> str:
    if view.type in ("credit", "borrowed"):
        owed = view.credit.owed_with_plans if view.credit else -view.balance + view.plans_unbilled
        return f"{view.name}: you owe {php(owed)}"
    text = f"{view.name}: {php(view.balance)}"
    if view.set_aside > ZERO and view.available is not None:
        text += f" ({php(view.set_aside)} set aside for goals, {php(view.available)} free)"
    return text


def run(ctx) -> Facts:
    views = ctx.accounts
    cash = account_service.cash_on_hand(views)
    worth = account_service.net_worth(views)
    counted = [v for v in ctx.visible_accounts if v.id in cash.account_ids]
    set_aside = total(v.set_aside for v in counted)

    lines = [f"Cash on hand: {php(cash.total)} across {len(counted)} "
             f"{'account' if len(counted) == 1 else 'accounts'} that count toward it."]
    if set_aside > ZERO:
        lines.append(f"Money set aside for goals, already left out of cash on hand: {php(set_aside)}.")
    if counted:
        lines.append("Accounts in cash on hand: " + "; ".join(_money_in(v) for v in counted[:LISTED]) + ".")
    others = [v for v in ctx.visible_accounts if v.id not in cash.account_ids]
    if others:
        lines.append("Other accounts, not in cash on hand: " + "; ".join(_money_in(v) for v in others[:LISTED]) + ".")
    lines.append(f"Net worth: {php(worth.total)}.")
    lines.append(f"Net worth is made of {php(worth.assets)} in everything you own, less {php(worth.liabilities)} "
                 f"in everything you owe.")

    template = f"You have {php(cash.total)} in cash on hand."
    if set_aside > ZERO:
        template += f" That's after the {php(set_aside)} you've set aside for goals."
    template += f" Your net worth is {php(worth.total)}."

    wanted = ctx.intent.account_id
    if wanted is not None:
        view = next((v for v in ctx.visible_accounts if v.id == wanted), None)
        if view is not None:
            lines.append(f"Asked about: {_money_in(view)}.")
            template = _money_in(view).replace(f"{view.name}: ", f"{view.name} - ", 1) + "."

    return Facts(
        skill="cash", title="Cash on hand", lines=lines, template=template,
        sources=[Source("Accounts", "/accounts")], actions=[Action("open_screen", "Open accounts", "/accounts")],
        tone="ok" if cash.total >= ZERO else "danger",
        follow_ups=["What bills are due before payday?", "How much is left in my budget?"],
    )
