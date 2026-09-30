"""
goals (AI-18): how each savings goal is doing - saved of target, what is left,
and what it asks for each month (GOA-05) - or the one goal the question names.

Reads goal_service.list_goals, the call behind the Goals screen, so "per month"
is GOA-05's own figure and a sinking fund's target is its bill's (GOA-09).
"""

from app.services.assistant_service.facts import Action, Facts, Source, day, pct, php

LISTED = 6
KINDS = {"saving": "savings goal", "sinking": "sinking fund", "emergency": "emergency fund"}


def _line(g, today) -> str:
    text = f"{g.name} ({KINDS.get(g.kind, 'goal')}): {php(g.saved)} set aside of {php(g.target)} ({pct(g.ratio)})"
    if g.reached:
        return text + " - reached."
    text += f", {php(g.remaining)} to go"
    if g.target_date is not None:
        text += f", target date {day(g.target_date, today)}"
    if g.per_month is not None and g.months_left is not None:
        text += f"; {php(g.per_month)} a month over {g.months_left} months reaches it on time"
    if g.overdue:
        text += "; the target date has passed"
    return text + "."


def run(ctx) -> Facts:
    today = ctx.today
    goals = ctx.goals
    source = Source("Savings goals", "/goals")
    if not goals:
        return Facts(
            skill="goals", title="Savings goals", lines=["No savings goals are set up."],
            template="You don't have any savings goals yet. Add one on the Goals screen and I can track it for you.",
            sources=[source], actions=[Action("open_screen", "Open goals", "/goals")],
        )

    wanted = next((g for g in goals if g.id == ctx.intent.goal_id), None)
    shown = [wanted] if wanted else goals[:LISTED]
    lines = [_line(g, today) for g in shown]
    if not wanted and len(goals) > LISTED:
        lines.append(f"{len(goals) - LISTED} more goals are on the Goals screen.")

    if wanted:
        g = wanted
        if g.reached:
            template = f"{g.name} is reached - {php(g.saved)} of {php(g.target)}."
        else:
            template = f"{g.name} has {php(g.saved)} of {php(g.target)} set aside, {php(g.remaining)} to go."
            if g.per_month is not None:
                template += f" Setting aside {php(g.per_month)} a month gets you there by {day(g.target_date, today)}."
    else:
        reached = [g for g in goals if g.reached]
        template = f"You have {len(goals)} {'goal' if len(goals) == 1 else 'goals'}" + (
            f", {len(reached)} reached." if reached else ".")
        top = [g for g in goals if not g.reached][:2]
        if top:
            template += " " + " ".join(f"{g.name}: {php(g.saved)} of {php(g.target)}." for g in top)

    tone = None
    if wanted:
        tone = "ok" if wanted.reached or not wanted.overdue else "warn"
    return Facts(
        skill="goals", title=wanted.name if wanted else "Savings goals", lines=lines, template=template,
        sources=[source], actions=[Action("open_screen", "Open goals", "/goals")], tone=tone,
        follow_ups=["Is my emergency fund enough?", "Can I afford a ₱15,000 phone?"],
    )
