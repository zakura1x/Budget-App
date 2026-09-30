"""
payoff (AI-20): the user's debts, which one clears first, and when they are
debt-free - as the payments already set up go, and in snowball or avalanche
order (REC-35).

Reads payoff_service.plan with no extra, the Payoff screen's opening view.
Interest there is an ESTIMATE from rates the user typed, and the facts say so.
The skill reports the plans side by side; which to follow is the user's
choice (AI-35), so no plan is called the one to pick.
"""

from app.core.utils.money import ZERO
from app.services import payoff_service
from app.services.assistant_service.facts import Action, Facts, Source, day, php
from app.services.assistant_service.facts import names as name_list

LISTED = 6


def _plan_line(label, plan, names, today) -> str:
    if plan.debt_free is None:
        return f"{label}: at least one debt never clears with the payments as they are."
    order = ", ".join(names.get(o.id, "a debt") for o in plan.outcomes)
    text = f"{label}: debt-free by {day(plan.debt_free, today)} ({plan.months} months); order {order}"
    if plan.interest > ZERO:
        text += f"; about {php(plan.interest)} in interest, estimated from the rates you typed"
    return text + "."


def run(ctx) -> Facts:
    today = ctx.today
    p = payoff_service.plan(ctx.db, ctx.cipher, today=today)
    source = Source("Pay off debts", "/payoff")
    if not p.debts:
        return Facts(
            skill="payoff", title="Debts", lines=["No card, loan or other debt has a balance owed."],
            template="You don't owe anything on your cards or loans right now.",
            sources=[source], tone="ok",
        )

    names = {d.account_id: d.name for d in p.debts}
    lines = ["Debts: " + "; ".join(
        f"{d.name} owes {php(d.owed)}, paying {php(d.payment)} a month" for d in p.debts[:LISTED]) + "."]
    lines.append(f"Plans start with next month's payments, from {day(p.start, today)}.")
    lines.append(_plan_line("As the payments are now", p.as_is, names, today))
    lines.append(_plan_line("Snowball (smallest balance first)", p.snowball, names, today))
    if p.avalanche is not None:
        lines.append(_plan_line("Avalanche (highest rate first)", p.avalanche, names, today))
    else:
        lines.append("No rate is typed on any debt, so there is no avalanche plan.")

    unpaid = [d.name for d in p.debts if d.payment <= ZERO]
    if unpaid:
        lines.append(f"No monthly payment is recorded for {name_list(unpaid)}, so no plan can clear "
                     f"{'it' if len(unpaid) == 1 else 'them'} and there is no debt-free date yet.")

    # "Clears first" only means something in a plan that finishes
    firsts = []
    if p.snowball.debt_free is not None and p.snowball.outcomes:
        firsts.append(f"by snowball order, {names.get(p.snowball.outcomes[0].id, 'a debt')} clears first")
    if p.avalanche is not None and p.avalanche.debt_free is not None and p.avalanche.outcomes:
        firsts.append(f"by avalanche order, {names.get(p.avalanche.outcomes[0].id, 'a debt')} clears first")
    if firsts:
        lines.append("Which clears first depends on the order chosen: " + "; ".join(firsts) + ".")
    first = p.as_is.outcomes[0] if p.as_is.outcomes else None
    if p.as_is.debt_free is not None:
        template = f"At your current payments you're debt-free by {day(p.as_is.debt_free, today)}"
        if first is not None:
            template += f", and {names.get(first.id, 'your first debt')} clears first"
        template += "."
    elif unpaid:
        template = (f"There's no debt-free date yet: no monthly payment is recorded for {name_list(unpaid)}. "
                    f"Type one on the Payoff screen to see when it clears.")
    else:
        template = "At your current payments at least one debt never clears - the Payoff screen shows which."
    # "Which should I pay first?" asks for advice, and left to itself the model gives it ("Pay off the
    # card first"). So the reply opens with the plain finding, and the orders are described after it.
    lead = template.split(". ")[0].rstrip(".") + "."
    return Facts(
        skill="payoff", title="Paying off debts", lines=lines, template=template, sources=[source],
        verdict_text=lead,
        actions=[Action("open_screen", "Open payoff planner", "/payoff")],
        tone="ok" if p.as_is.debt_free is not None else "danger",
        follow_ups=["How much do I owe on my card?", "What bills are due before payday?"],
    )
