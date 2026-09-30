"""
upcoming (AI-14): the bills and charges due in a window - this week, the rest
of the month, or until the next income lands ("before payday").

Reads projection_service.project - Months ahead, which the calendar's
scheduled days also come from (CAL-07) - so a listed charge is the same item
on the same day as those screens show. Never a date rule of its own.
"""

from datetime import timedelta
from typing import List, Optional

from app.core.utils.money import ZERO, total
from app.services import projection_service
from app.services.assistant_service.facts import Action, Facts, Source, day, days, php

LISTED = 10
DEFAULT_DAYS = 14
PAYDAY_HORIZON_DAYS = 45


def _outgoing(item) -> bool:
    return not item.paused and (item.type == "expense" or (item.type == "transfer" and item.effect < ZERO))


def _income(item) -> bool:
    return not item.paused and item.type == "income" and item.kind != "interest" and item.amount > ZERO


def run(ctx) -> Facts:
    today = ctx.today
    projection = projection_service.project(ctx.db, ctx.cipher, today=today, months=3)
    items = sorted((i for m in projection.months for i in m.items), key=lambda i: (i.on, i.rule_id))
    ahead = [i for i in items if i.on >= today]

    payday: Optional[object] = next(
        (i for i in ahead if _income(i) and i.on > today and i.on <= today + timedelta(days=PAYDAY_HORIZON_DAYS)),
        None,
    )
    window = ctx.intent.window or ("payday" if payday is not None else None)
    lines: List[str] = []
    if window == "week":
        end, label = today + timedelta(days=6), "the next 7 days"
    elif window == "month" and projection.months:
        end = projection.months[0].end
        label = f"now to {day(end, today)}"
    elif window == "payday" and payday is not None:
        end = payday.on - timedelta(days=1)
        label = f"before your next income on {day(payday.on, today)}"
        lines.append(f"Next income: {payday.name}, {php(payday.amount)} on {day(payday.on, today)}.")
    else:
        end = today + timedelta(days=DEFAULT_DAYS - 1)
        label = f"the next {days(DEFAULT_DAYS)}"
        if window == "payday":
            lines.append(f"No income is scheduled in the next {days(PAYDAY_HORIZON_DAYS)}.")

    due = [i for i in ahead if i.on <= end and _outgoing(i)]
    coming_in = [i for i in ahead if i.on <= end and _income(i)]
    title = f"Due {label}"
    lines.insert(0, f"Window: {day(today, today)} to {day(end, today)} ({label}).")
    if due:
        listed = "; ".join(f"{day(i.on, today)} {i.name} {php(i.amount)} from {ctx.account_name(i.account_id)}"
                           for i in due[:LISTED])
        lines.append(f"Charges and bills due ({len(due)}): {listed}.")
        if len(due) > LISTED:
            lines.append(f"{len(due) - LISTED} more are due in the window.")
        lines.append(f"Total due in the window: {php(total(i.amount for i in due))}.")
    else:
        lines.append("Nothing scheduled is due in the window.")
    if coming_in and window != "payday":
        lines.append("Income expected: " + "; ".join(
            f"{day(i.on, today)} {i.name} {php(i.amount)}" for i in coming_in[:5]) + ".")

    lines.append(f"Cash on hand today: {php(projection.cash_on_hand)}.")
    tone = "ok"
    if projection.months:
        month = projection.months[0]
        lines.append(f"Lowest cash on hand projected this month: {php(month.low_point)} on "
                     f"{day(month.low_on, today)}.")
        if month.low_point < ZERO:
            tone = "danger"

    if due:
        biggest = sorted(due, key=lambda i: i.amount, reverse=True)[:3]
        template = (f"You have {len(due)} {'charge' if len(due) == 1 else 'charges'} due {label}, "
                    f"{php(total(i.amount for i in due))} in all. The biggest: "
                    + "; ".join(f"{i.name} {php(i.amount)} on {day(i.on, today)}" for i in biggest) + ".")
    else:
        template = f"Nothing scheduled is due {label}."

    return Facts(
        skill="upcoming", title=title, lines=lines, template=template,
        sources=[Source("Months ahead", "/projection"), Source("Calendar", "/calendar")],
        actions=[Action("open_screen", "Open months ahead", "/projection")], tone=tone,
        follow_ups=["How much cash do I have?", "How much do I owe on my card?"],
    )
