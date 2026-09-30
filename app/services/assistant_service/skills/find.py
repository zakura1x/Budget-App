"""
find (AI-41): one merchant's or one bill's own entries - "When did I last pay
Meralco?", "How much at Jollibee this month?".

Reads transaction_service.views, the working set every list is drawn from.
An entry matches by the merchant typed on it, or by the recurring rule it was
posted from (a bill's own charges carry its rule id, not a merchant).

What reaches the model (README Q2, allowed 2026-09-30): the merchant or bill
name the user asked about, and dates, amounts and account names of its
entries. NEVER a note, and never a merchant the question did not name.
"""

from datetime import date, timedelta
from typing import List, Tuple

from app.core.utils.money import total
from app.services import stats_service, transaction_service
from app.services.assistant_service.facts import Action, Facts, Source, day, php

RECENT = 5


def _range(ctx) -> Tuple[date, date, str]:
    period, today = ctx.intent.period, ctx.today
    if period == "last_month":
        start, end = stats_service.month_range(stats_service.month_range(today)[0] - timedelta(days=1))
    elif period == "this_year":
        start, end = date(today.year, 1, 1), date(today.year, 12, 31)
    elif period and len(period) == 7:
        year, month = (int(p) for p in period.split("-"))
        start, end = stats_service.month_range(date(year, month, 1))
    else:
        start, end = stats_service.month_range(today)
    return start, end, f"{day(start, today)} to {day(end, today)}"


def run(ctx) -> Facts:
    intent, today = ctx.intent, ctx.today
    merchant = (intent.merchant or "").strip().lower()
    rule_id = intent.rule_id
    name = ctx.plan_names.get(rule_id) if rule_id is not None else intent.merchant
    if not name:
        return Facts(
            skill="find", title="Find an entry", lines=[],
            template="Which merchant or bill do you mean? Ask with its name as you typed it on an entry, like: "
                     "\"When did I last pay Meralco?\"",
            phrase=False,
        )

    rows: List = [
        v for v in transaction_service.views(ctx.db, ctx.cipher)
        if v.direction != "in" and v.txn_date <= today
        and ((rule_id is not None and v.recurring_id == rule_id) or (merchant and (v.merchant or "").lower() == merchant))
    ]
    rows.sort(key=lambda v: (v.txn_date, v.id), reverse=True)
    source = Source("Ledger", "/transactions")
    if not rows:
        return Facts(
            skill="find", title=name, lines=[f"No entry for {name} is recorded up to today."],
            template=f"I don't see any entry for {name} yet.", sources=[source],
        )

    start, end, label = _range(ctx)
    in_period = [v for v in rows if start <= v.txn_date <= end]
    last = rows[0]
    lines = [
        f"Asked about: {name}.",
        f"Most recent entry: {php(last.amount)} on {day(last.txn_date, today)}, from "
        f"{ctx.account_name(last.account_id)}.",
        f"In {label}: {len(in_period)} {'entry' if len(in_period) == 1 else 'entries'}, "
        f"{php(total(v.amount for v in in_period))} in all.",
        f"Ever recorded: {len(rows)} {'entry' if len(rows) == 1 else 'entries'}, "
        f"{php(total(v.amount for v in rows))} in all, the first on {day(rows[-1].txn_date, today)}.",
    ]
    if len(rows) > 1:
        lines.append("The latest ones: " + "; ".join(
            f"{day(v.txn_date, today)} {php(v.amount)}" for v in rows[:RECENT]) + ".")

    template = (f"Your last {name} entry was {php(last.amount)} on {day(last.txn_date, today)}. "
                f"From {label} that's {len(in_period)} {'entry' if len(in_period) == 1 else 'entries'}, "
                f"{php(total(v.amount for v in in_period))} in all.")
    return Facts(
        skill="find", title=name, lines=lines, template=template, sources=[source],
        actions=[Action("open_screen", "Open the ledger", "/transactions")],
        follow_ups=["Where did my money go this month?"],
    )
