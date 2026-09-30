"""
spending (AI-12): how much went out in a month or the year, where it went, how
it compares with the period before, and one category when the question names
one.

Reads stats_service.overview - the one call behind the Stats tab - with the
same span and day the Stats screen would send, so the totals match it.
"""

from datetime import date, timedelta
from typing import Iterable, Optional

from app.core.utils.money import ZERO
from app.services import stats_service
from app.services.assistant_service.facts import Action, Facts, Source, balance_line, day, names, pct, php

TOP = 5


def _range(ctx):
    """(span, on) for stats_service.overview, from the intent's period."""
    period = ctx.intent.period
    today = ctx.today
    if period == "last_month":
        return "month", stats_service.month_range(today)[0] - timedelta(days=1)
    if period == "this_year":
        return "year", today
    if period and len(period) == 7:
        year, month = (int(p) for p in period.split("-"))
        return "month", date(year, month, 1)
    return "month", today


def _name(ctx, share) -> str:
    if share.unrecorded:
        return "Unrecorded balance changes"
    return ctx.category_names.get(share.category_id, "A deleted category")


def _find(shares: Iterable, category_id: int):
    for share in shares:
        if share.category_id == category_id:
            return share
        found = _find(share.children, category_id)
        if found is not None:
            return found
    return None


def run(ctx) -> Facts:
    span, on = _range(ctx)
    overview = stats_service.overview(ctx.db, ctx.cipher, span=span, on=on, today=ctx.today)
    t = overview.totals
    start, end = overview.start, overview.end
    label = f"{day(start, ctx.today)} to {day(end, ctx.today)}"
    running = start <= ctx.today <= end
    lines = [
        f"Period: {label}" + (f", counted up to today ({day(ctx.today, ctx.today)})." if running else "."),
        balance_line(t.spent, t.earned),
        f"Average spending per day: {php(t.average_daily_spend)}.",
    ]

    top = [s for s in overview.categories if s.amount > ZERO][:TOP]
    if top:
        lines.append("Biggest spending categories: " + "; ".join(
            f"{_name(ctx, s)} {php(s.amount)} ({pct(s.share)})" for s in top) + ".")

    prev = overview.previous
    prev_label = f"{day(prev.start, ctx.today)} to {day(prev.end, ctx.today)}"
    change = t.spent - prev.spent
    if prev.spent > ZERO:
        direction = "more" if change > ZERO else "less"
        lines.append(f"The period before ({prev_label}) had {php(prev.spent)} of spending; this period is "
                     f"{php(abs(change))} {direction} ({pct(abs(change) / prev.spent)}).")
    else:
        lines.append(f"The period before ({prev_label}) had no spending recorded.")

    focus: Optional[str] = None
    wanted = ctx.intent.category_id
    if wanted is not None:
        share = _find(overview.categories, wanted)
        name = ctx.category_names.get(wanted, "That category")
        if share is None or share.amount == ZERO:
            lines.append(f"{name}: nothing spent in this period.")
            focus = f"You haven't spent anything on {name} from {label}."
        else:
            count = share.transaction_count
            lines.append(f"{name}: {php(share.amount)} across {count} "
                         f"{'entry' if count == 1 else 'entries'}, {pct(share.share)} of spending; "
                         f"the period before: {php(share.previous_amount)}.")
            focus = f"You spent {php(share.amount)} on {name} from {label}, against {php(share.previous_amount)} " \
                    f"the period before."

    if focus:
        template = focus
    elif top:
        template = (f"You spent {php(t.spent)} from {label}. Most of it went to "
                    f"{names([f'{_name(ctx, s)} ({php(s.amount)})' for s in top[:3]])}.")
    else:
        template = f"There's no spending recorded from {label}."

    return Facts(
        skill="spending", title=f"Spending, {label}", lines=lines, template=template,
        sources=[Source("Stats", "/stats")], actions=[Action("open_screen", "Open stats", "/stats")],
        follow_ups=["How much is left in my budget?", "Where did my money go last month?"],
    )
