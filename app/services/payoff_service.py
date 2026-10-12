"""
payoff_service - the debt payoff planner (REC-35). READ-ONLY, like
projection_service: it gathers the debts and hands them to the pure
arithmetic in app/core/utils/payoff.py. Imported by nothing but its endpoint.

A DEBT is every card and borrowed account (OWES) that is not archived or
hidden and owes something: a card's owed with its plans still to bill
(`AccountView.owed_with_plans`, the same for a card and a loan) - what each one's
page says you owe, the figure ACC-34 fixed on 2026-09-21.

ITS MONTHLY PAYMENT, in this order - the first that gives an amount:

    rule    repeating transfers INTO it (a card payment, a loan's monthly
            payment), each at its amount a month (a yearly one / 12)
    plan    else the next payment of each open installment plan on it - what
            the Pay button (REC-32) asks for
    none    nothing is scheduled: the planner says so, and only the extra ever
            reaches it

A payment typed on the planner screen overrides all three for that run and is
never stored.

ITS RATE is the one typed on the account (per month or per year, stored a
year), an estimate: the app never calculates a card's real interest (ACC-19).
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Mapping, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import ValidationException
from app.core.utils.date_utils import add_months
from app.core.utils.money import CENTS, ZERO, money, total
from app.core.utils.payoff import Debt, Plan, compare
from app.services import account_service, recurring_service, transaction_service
from app.services.subscription_service import PER_MONTH

MAX_EXTRA = Decimal("99999999.99")


@dataclass(frozen=True)
class DebtLine:
    account_id: int
    name: str
    type: str
    owed: Decimal
    payment: Decimal
    payment_source: str  # rule | plan | yours | none
    yearly_rate: Optional[Decimal]
    rate: Optional[Decimal]  # as typed
    rate_per: Optional[str]  # month | year


@dataclass(frozen=True)
class Payoff:
    start: date  # month 1 of every plan
    debts: List[DebtLine]
    as_is: Plan
    snowball: Plan
    avalanche: Optional[Plan]  # only when some debt has a rate


def plan(
    db: Session,
    cipher: UserCipher,
    *,
    extra: Decimal = ZERO,
    payments: Optional[Mapping[int, Decimal]] = None,
    today: Optional[date] = None,
) -> Payoff:
    today = today or date.today()
    extra = money(extra)
    if extra < ZERO or extra > MAX_EXTRA:
        raise ValidationException("The extra is zero or more")
    payments = {int(k): money(v) for k, v in (payments or {}).items()}
    if any(v < ZERO for v in payments.values()):
        raise ValidationException("A payment is zero or more")

    views = account_service.list_accounts(db, cipher, postings=transaction_service.postings(db, cipher),
                                          today=today, include_archived=False)
    rules = recurring_service.list_rules(db, cipher, today=today)
    lines: List[DebtLine] = []
    for view in views:
        if view.type not in account_service.OWES or view.hidden:
            continue
        owed = view.owed_with_plans or ZERO
        if owed <= ZERO:
            continue
        payment, source = _payment(view.id, rules)
        if view.id in payments:
            payment, source = payments[view.id], "yours"
        rate = view.debt_rate
        lines.append(DebtLine(
            account_id=view.id, name=view.name, type=view.type, owed=owed, payment=payment, payment_source=source,
            yearly_rate=rate.yearly if rate else None, rate=rate.rate if rate else None,
            rate_per=rate.per if rate else None,
        ))

    start = add_months(date(today.year, today.month, 1), 1)  # payments from next month
    debts = [Debt(line.account_id, line.owed, line.payment, line.yearly_rate) for line in lines]
    plans = compare(debts, extra=extra, start=start)
    return Payoff(start=start, debts=lines, as_is=plans["as_is"], snowball=plans["snowball"],
                  avalanche=plans["avalanche"])


def _payment(account_id: int, rules: List[recurring_service.RuleView]) -> Tuple[Decimal, str]:
    live = [r for r in rules if not r.paused and r.next_on is not None]
    into = [r for r in live if r.type == "transfer" and r.counter_account_id == account_id]
    if into:
        monthly = total(
            (r.amount * PER_MONTH.get(r.frequency, Decimal(1)) / r.interval).quantize(CENTS, rounding=ROUND_HALF_UP)
            for r in into
        )
        return monthly, "rule"
    plans = [r for r in live if r.kind == "installment" and r.account_id == account_id
             and r.installment is not None and not r.installment.closed]
    if plans:
        return total(r.installment.current_payment or r.next_amount or ZERO for r in plans), "plan"
    return ZERO, "none"
