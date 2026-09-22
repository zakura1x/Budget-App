"""
recurring_service - THE ONE ENGINE (REC-01..30, SUB-00; ARCHITECTURE.md §4.4, §4.5).

Standard rules (rent, salary), subscriptions (Netflix) and installments (a
phone at ₱40,000 × 6) are all `recurring_rules`, told apart by `kind`. Nothing
else in the app ever creates a transaction from a schedule, so nothing can post
the same charge twice.

ONE SCHEDULE, TWO READERS (REC-22). `occurrences(rule_id, data, start, end)` is
a pure function of a rule's payload. Expansion posts what it returns up to
today; projection_service reads what it returns after today. Neither has its
own calendar to disagree with the other.

THE PAYLOAD:

    {"kind": "standard", "type": "income", "name": "Salary",
     "account_id": 3, "category_id": 12, "merchant": null, "notes": null, "tag_ids": [],
     "frequency": "semi_monthly", "interval": 1, "start": "2026-09-15", "days": [15, 30],
     "end_after": null, "end_on": null,
     "amounts": [{"from": "2026-09-15", "amount": "25000.00"},
                 {"from": "2027-01-01", "amount": "27000.00"}],       REC-20
     "pauses": [{"from": "2026-10-01", "to": "2026-10-31"}],           REC-07
     "skips": ["2026-12-15"],                                          REC-15
     "posted_through": "2026-09-14", "closed_on": null}

  An installment has no `amounts`; it has `price`, `payments`, `interest`
  (null until known), `terms` (provisional | confirmed),
  `interest_category_id` and `interest_changes` instead (REC-09, REC-28):

     "interest_changes": [{"from": "2026-11-20", "per_payment": "500.00"}]

  An installment made FROM A PURCHASE (REC-34, installment_conversion) also
  carries `from_transaction` - the purchase it replaced, hidden until the
  plan is converted back - and, when that purchase was split across
  categories, `category_shares` ([{"category_id", "amount"}], the purchase's
  own split amounts): each payment's price part is split in the same
  proportions, the last share absorbing the rounding.

  the installment's own dated history (REC-20, REC-29): from that payment on,
  each carries that much interest.

IDEMPOTENT CATCH-UP (REC-05). Expansion posts the occurrences dated after
`posted_through` and on or before today that are not already in the working
set as (recurring_id, recurring_on) - and advances `posted_through` in the
same commit. Either check alone would do today; both together survive a
crash between them and a user deleting a posted charge, which must not come
back the next morning.

INSTALLMENTS. Each payment posts two splits - price ÷ payments in the
purchase's category, interest ÷ payments in Financial › Interest - and each
split's LAST payment absorbs its own rounding (REC-16, REC-30), so the price
and the interest both come out exact. The remaining balance is the total less
every expense posted with this rule's id - derived, never a counter (REC-10).
A skip moves the payoff one period later and owes the same (REC-15). An
installment cannot be paused: pausing would pretend the bank stopped billing.

THE BILL CORRECTS THE PLAN (REC-29). When a statement shows the interest, or
later a different payment, the payments already posted are corrected to what
the bank billed - through transaction_service.reprice_recurring, their price
split untouched - and the plan's schedule carries the new interest forward.
The total is the sum of the schedule, so it, the remaining balance and the
payoff always agree with what posts.

A new rule posts nothing dated before the day it is created unless asked
(`post_past`) - those charges were most likely entered by hand already.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import (
    BusinessRuleException,
    NotFoundException,
    PrepaymentChoiceException,
    ValidationException,
)
from app.core.utils.date_utils import add_months, clamp_day
from app.core.utils.money import CENTS, ZERO, money, total
from app.db.repositories.account_repository import AccountRepository
from app.db.repositories.category_repository import CategoryRepository
from app.db.repositories.recurring_repository import RecurringRuleRepository, SubscriptionRepository
from app.db.repositories.transaction_repository import TransactionRepository
from app.services import audit_service, tag_service, transaction_service
from app.services.transaction_service import TransactionView

KINDS: Tuple[str, ...] = ("standard", "subscription", "installment")
TYPES: Tuple[str, ...] = ("expense", "income", "transfer")
FREQUENCIES: Tuple[str, ...] = ("daily", "weekly", "monthly", "yearly", "semi_monthly")

NAME_MAX = 60
MERCHANT_MAX = 80
NOTES_MAX = 500
MAX_RULES = 200
MAX_PULL_BACK_DAYS = 366  # how far back moving a start may reopen the catch-up (REC-05)
MAX_PAYMENTS = 360
MAX_INTERVAL = 52
MAX_TAGS = 10
REMINDER_DAYS_DEFAULT = 3
NEXT_WINDOW_DAYS = 800  # a yearly rule's next date is always inside it
_ITERATION_CAP = 20000  # a daily rule over 50 years; past this a schedule is a bug
ONE_DAY = timedelta(days=1)


# ------------------------------------------------------------------- shapes


@dataclass(frozen=True)
class Occurrence:
    rule_id: int
    on: date
    number: int  # 1-based among the occurrences that count; 0 for a paused one
    amount: Decimal
    splits: Tuple[Tuple[Optional[int], Decimal], ...]  # (category_id, amount)
    paused: bool = False
    final: bool = False  # the last one an end condition allows (REC-06, REC-16)


@dataclass(frozen=True)
class AmountChange:
    on: date
    amount: Decimal


@dataclass(frozen=True)
class InstallmentStatus:
    price: Decimal
    interest: Decimal  # 0.00 while provisional
    total: Decimal  # what the bank bills: price + interest
    payments: int
    per_payment: Decimal  # the first payment; the last absorbs rounding
    terms: str  # provisional | confirmed
    paid: Decimal
    remaining: Decimal  # total - paid, derived from posted transactions (REC-10)
    payments_posted: int
    payoff_on: Optional[date]  # the final scheduled payment, after any skips
    closed: bool
    # REC-32. The plan in MONEY terms - what you have actually paid on it and
    # what is left to pay, which is what "you owe" means on a loan. `paid` and
    # `remaining` above stay the CHARGES: what has been billed, and what is
    # still to bill (the figure a card's available credit holds back).
    money_paid: Decimal = ZERO
    left_to_pay: Decimal = ZERO
    current_payment: Decimal = ZERO  # the next payment still to post - lower after an extra payment
    payments_left: int = 0  # scheduled payments not posted yet, after any shortening
    prepaid: Decimal = ZERO  # every extra payment so far


@dataclass(frozen=True)
class Due:
    """
    ACC-40. One scheduled payment of a plan that money has not covered yet -
    when it falls due, and how much of it is left.

    A loan's bill, and unlike a card's (ACC-35) nobody types it: the plan
    already carries the schedule, so the dates and the amounts are its own.
    """

    on: date
    amount: Decimal
    rule_id: int
    name: str


@dataclass(frozen=True)
class PlansOwed:
    """
    What every open installment still owes, per account, from ONE pass over the
    rules and their postings: the unbilled remainder a card's limit holds back
    (REC-14) and the schedule a loan is paid on (ACC-40). account_service asks
    for both on every read of the account list, and loading the context twice
    would walk the whole working set twice.
    """

    unpaid: Dict[int, Decimal]
    dues: Dict[int, Tuple[Due, ...]]


@dataclass(frozen=True)
class RuleView:
    id: int
    kind: str
    type: str
    name: str
    account_id: int
    counter_account_id: Optional[int]
    category_id: Optional[int]
    interest_category_id: Optional[int]
    merchant: Optional[str]
    notes: Optional[str]
    tag_ids: Tuple[int, ...]
    frequency: str
    interval: int
    start: date
    days: Tuple[int, ...]
    end_after: Optional[int]
    end_on: Optional[date]
    amount: Decimal  # in force today (an installment: its first payment)
    amounts: Tuple[AmountChange, ...]  # REC-20 / SUB-08
    paused: bool
    skips: Tuple[date, ...]
    closed_on: Optional[date]
    posted_through: date
    next_on: Optional[date]
    next_amount: Optional[Decimal]
    problem: Optional[str] = None  # why expansion is holding it back
    reminder_days: Optional[int] = None  # subscriptions only (SUB-06)
    installment: Optional[InstallmentStatus] = None
    from_transaction: Optional[int] = None  # REC-34 - the purchase this plan replaced
    receipt_id: Optional[int] = None  # that purchase's receipt, shown on the plan


@dataclass(frozen=True)
class Upcoming:
    """One occurrence with the rule facts a reader needs - for projection, cards and subscriptions."""

    occurrence: Occurrence
    rule_id: int
    name: str
    kind: str
    type: str
    account_id: int
    counter_account_id: Optional[int]

    @property
    def on(self) -> date:
        return self.occurrence.on

    @property
    def amount(self) -> Decimal:
        return self.occurrence.amount


@dataclass(frozen=True)
class Expansion:
    posted: int  # transactions written (a transfer counts once)
    rules: int
    needs_attention: Tuple[int, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StatementPlan:
    """An installment with a payment on a given statement (REC-29)."""

    rule_id: int
    name: str
    per_payment: Decimal
    terms: str = "provisional"
    payments_posted: int = 0  # every scheduled payment posted so far
    payments_on_statement: int = 0
    on_statement: Decimal = ZERO  # what the app has for this plan's payments on the statement


# --------------------------------------------------------- the pure schedule


def split_schedule(amount: Decimal, payments: int) -> List[Decimal]:
    """REC-16. `amount` in `payments` parts, each rounded half-up, the last making the sum exact."""
    per = (amount / payments).quantize(CENTS, rounding=ROUND_HALF_UP)
    return [per] * (payments - 1) + [amount - per * (payments - 1)]


def schedule_dates(data: Mapping[str, Any], until: date) -> Iterator[date]:
    """
    Every date the schedule names from the rule's start to `until`, before
    skips, pauses and end conditions. A monthly rule keeps its start day where
    the month has it (31 Jan -> 28 Feb -> 31 Mar); semi-monthly days clamp to
    the month's last day, so "30th" is 28 February (REC-19).
    """
    start = _as_date(data["start"])
    frequency = data.get("frequency") or "monthly"
    interval = int(data.get("interval") or 1)

    if frequency == "semi_monthly":
        days = sorted({int(d) for d in data.get("days") or []})
        year, month = start.year, start.month
        for _ in range(_ITERATION_CAP):
            seen: Set[date] = set()
            for number in days:
                day = clamp_day(year, month, number)
                if day in seen or day < start:
                    continue
                seen.add(day)
                if day > until:
                    return
                yield day
            months = year * 12 + month - 1 + interval
            year, month = months // 12, months % 12 + 1
        return

    for k in range(_ITERATION_CAP):
        if frequency == "daily":
            day = start + timedelta(days=k * interval)
        elif frequency == "weekly":
            day = start + timedelta(weeks=k * interval)
        elif frequency == "monthly":
            day = add_months(start, k * interval)
        else:
            day = add_months(start, 12 * k * interval)
        if day > until:
            return
        yield day


def amount_on(data: Mapping[str, Any], day: date) -> Decimal:
    """REC-20. The latest amount set to take effect on or before `day`."""
    entries = sorted(data.get("amounts") or [], key=lambda a: str(a["from"]))
    if not entries:
        raise ValidationException("A rule needs an amount")
    chosen = entries[0]
    for entry in entries:
        if _as_date(entry["from"]) <= day:
            chosen = entry
    return money(chosen["amount"])


PREPAYMENT_MODES: Tuple[str, ...] = ("lower", "shorten")

PlanRow = Tuple[date, Decimal, Decimal]  # (day, price part, interest part)


def installment_plan(data: Mapping[str, Any]) -> List[PlanRow]:
    """
    REC-32. Every payment an installment makes, in order, with extra payments
    already taken into account - the rows occurrences() hands out.

    Built from the plan's own terms (price and interest split per payment,
    REC-16), then its later interest (REC-29), then each extra payment in the
    order it was made. An extra payment only ever touches the payments AFTER
    the one it was made alongside (`after`):

      * "shorten" keeps the monthly amount and takes the extra off the END -
        the last payments disappear, and the new last one is reduced by what
        is left over.
      * "lower" keeps the number of payments and spreads what is left over
        them, so every later payment is smaller.

    Either way the price and the interest each stay exact to the centavo: the
    extra comes off the price first, then the interest.
    """
    payments = int(data["payments"])
    skips = {_as_date(d) for d in data.get("skips") or []}
    start = _as_date(data["start"])
    horizon = start + timedelta(days=min(366 * (payments * int(data.get("interval") or 1) + 1), 366 * 2000))
    days: List[date] = []
    for day in schedule_dates(data, horizon):
        if day in skips:
            continue
        days.append(day)
        if len(days) == payments:
            break

    prices = split_schedule(money(data["price"]), payments)
    interest = money(data.get("interest") or ZERO)
    interests = split_schedule(interest, payments) if interest > ZERO else [ZERO] * payments
    changes = sorted((_as_date(c["from"]), money(c["per_payment"])) for c in data.get("interest_changes") or [])
    rows: List[PlanRow] = []
    for index, day in enumerate(days):
        interest_part = interests[index]
        for since, per_payment in changes:
            if since <= day:
                interest_part = per_payment
        rows.append((day, prices[index], interest_part))

    for extra in sorted(data.get("prepayments") or [], key=lambda p: (str(p["on"]), str(p.get("after")))):
        rows = _apply_prepayment(rows, _as_date(extra.get("after") or extra["on"]), money(extra["amount"]),
                                 str(extra.get("mode") or "shorten"))
    return [row for row in rows if row[1] + row[2] > ZERO]


def _apply_prepayment(rows: Sequence[PlanRow], after: date, amount: Decimal, mode: str) -> List[PlanRow]:
    """One extra payment, applied to the payments dated after `after` (see installment_plan)."""
    kept = [row for row in rows if row[0] <= after]
    later = [row for row in rows if row[0] > after]
    if mode == "lower":
        price_total = total(row[1] for row in later)
        interest_total = total(row[2] for row in later)
        from_price = min(amount, price_total)
        from_interest = min(amount - from_price, interest_total)
        count = len(later)
        if count:
            new_prices = split_schedule(price_total - from_price, count)
            left_interest = interest_total - from_interest
            new_interests = split_schedule(left_interest, count) if left_interest > ZERO else [ZERO] * count
            later = [(row[0], new_prices[i], new_interests[i]) for i, row in enumerate(later)]
        return kept + later

    left = amount
    while later and left > ZERO:
        day, price, interest = later[-1]
        if price + interest <= left:
            later.pop()
            left -= price + interest
            continue
        cut = min(price, left)
        price, left = price - cut, left - cut
        cut = min(interest, left)
        interest, left = interest - cut, left - cut
        later[-1] = (day, price, interest)
    return kept + later


def occurrences(rule_id: int, data: Mapping[str, Any], start: date, end: date) -> List[Occurrence]:
    """
    THE schedule (REC-22): the occurrences in [start, end], numbered from the
    rule's own start so an installment knows which payment each one is.

    Skipped dates are gone and move nothing but the count. Paused dates are
    returned flagged `paused` - projection lists them dimmed - and do not
    count toward an end condition. Nothing on or after `closed_on` exists.
    """
    if end < start:
        return []
    skips = {_as_date(d) for d in data.get("skips") or []}
    pauses = [(_as_date(p["from"]), _as_date(p["to"]) if p.get("to") else None) for p in data.get("pauses") or []]
    end_on = _opt_date(data.get("end_on"))
    closed_on = _opt_date(data.get("closed_on"))
    end_after = data.get("end_after")

    installment = data.get("kind") == "installment"
    plan: List[PlanRow] = []
    if installment:
        # REC-32. The plan's payments with extra payments applied - a shortened
        # plan simply has fewer of them.
        plan = installment_plan(data)
        end_after = len(plan)

    limit = end if end_on is None else min(end, end_on)
    if closed_on is not None:
        limit = min(limit, closed_on - ONE_DAY)

    transfer = data.get("type") == "transfer"
    result: List[Occurrence] = []
    number = 0
    for day in schedule_dates(data, limit):
        if day in skips:
            continue
        if end_after is not None and number >= int(end_after):
            break
        if any(first <= day and (last is None or day <= last) for first, last in pauses):
            if day >= start and not installment:
                amount = amount_on(data, day)
                result.append(Occurrence(rule_id, day, 0, amount, ((_category(data, transfer), amount),), paused=True))
            continue
        number += 1
        if day < start:
            continue
        if installment:
            _, price_part, interest_part = plan[number - 1]
            splits: Tuple[Tuple[Optional[int], Decimal], ...] = _price_splits(data, price_part)
            if interest_part > ZERO:
                splits += ((data.get("interest_category_id"), interest_part),)
            result.append(Occurrence(rule_id, day, number, price_part + interest_part, splits,
                                     final=number == int(end_after)))
        else:
            amount = amount_on(data, day)
            result.append(Occurrence(rule_id, day, number, amount, ((_category(data, transfer), amount),),
                                     final=end_after is not None and number == int(end_after)))
    return result


def _price_splits(data: Mapping[str, Any], price_part: Decimal) -> Tuple[Tuple[Optional[int], Decimal], ...]:
    """
    REC-34. A payment's price part in the plan's category - or, for a plan made
    from a purchase split across categories, in the purchase's own proportions,
    the last share taking whatever rounding is left so the part stays exact.
    """
    shares = [(int(s["category_id"]), money(s["amount"])) for s in data.get("category_shares") or []]
    whole = total(amount for _, amount in shares)
    if len(shares) < 2 or whole <= ZERO:
        return ((data.get("category_id"), price_part),)
    result: List[Tuple[Optional[int], Decimal]] = []
    left = price_part
    for index, (category_id, amount) in enumerate(shares):
        part = left if index == len(shares) - 1 else (price_part * amount / whole).quantize(CENTS, rounding=ROUND_HALF_UP)
        part = min(part, left)
        left -= part
        result.append((category_id, part))
    return tuple(result)


def preview(payload: Mapping[str, Any], *, today: date, count: int = 5) -> List[Occurrence]:
    """The next `count` occurrences of an unsaved rule - "next 5" in the sheet before saving."""
    data = _pure(payload, None, today, posted_count=0)
    first = max(today, _as_date(data["start"]))
    found = occurrences(0, data, first, first + timedelta(days=366 * 10))
    return found[:count]


# ------------------------------------------------------------------ reading


def list_rules(
    db: Session, cipher: UserCipher, *, today: Optional[date] = None, kind: Optional[str] = None
) -> List[RuleView]:
    today = today or date.today()
    context = _Context.load(db, cipher)
    views = [
        _view(record.id, record.data, context, today)
        for record in context.rules
        if kind is None or record.data.get("kind") == kind
    ]
    return sorted(views, key=lambda v: (v.next_on is None, v.next_on or date.max, v.name.casefold(), v.id))


def get_rule(db: Session, cipher: UserCipher, rule_id: int, *, today: Optional[date] = None) -> RuleView:
    context = _Context.load(db, cipher)
    record = next((r for r in context.rules if r.id == rule_id), None)
    if record is None:
        raise NotFoundException("Recurring rule not found")
    return _view(record.id, record.data, context, today or date.today())


def upcoming(db: Session, cipher: UserCipher, start: date, end: date) -> List[Upcoming]:
    """
    Every occurrence in [start, end] that has not posted, paused ones
    included and flagged - what the months ahead and the card look-ahead are
    made of. Reads only; see project() and cards() in projection_service.
    """
    context = _Context.load(db, cipher)
    found: List[Upcoming] = []
    for record in context.rules:
        data = record.data
        posted = context.posted_days.get(record.id, set())
        for occurrence in occurrences(record.id, data, start, end):
            if occurrence.on in posted:
                continue
            found.append(Upcoming(occurrence, record.id, str(data.get("name", "")), str(data.get("kind")),
                                  str(data.get("type")), int(data["account_id"]), data.get("counter_account_id")))
    return sorted(found, key=lambda u: (u.on, u.rule_id))


def unpaid_by_account(db: Session, cipher: UserCipher) -> Dict[int, Decimal]:
    """ACC-14 / REC-14. The unpaid remainder of every open installment, per account - what the bank blocks."""
    return plans_owed(db, cipher).unpaid


def plans_owed(db: Session, cipher: UserCipher) -> PlansOwed:
    """
    REC-14 / ACC-40. Both figures an open plan owes, per account, in one pass.

    `unpaid` is what has still to be BILLED - the charges to come, which a
    card's available credit holds back from day one. `dues` is the SCHEDULE
    money has not covered yet: every payment of the plan, oldest first, with
    what is left of it. The two answer different questions and neither is the
    other: a payment can be billed and unpaid, or paid before it is billed.
    """
    context = _Context.load(db, cipher)
    unpaid: Dict[int, Decimal] = {}
    dues: Dict[int, List[Due]] = {}
    for record in context.rules:
        data = record.data
        if data.get("kind") != "installment":
            continue
        status = _installment_status(record.id, data, context.posted.get(record.id, []))
        if status.closed:
            continue
        account = int(data["account_id"])
        unpaid[account] = unpaid.get(account, ZERO) + status.remaining
        # What money has covered of the schedule, oldest payment first - the
        # same reading as _due_part, which decides what a payment pays for.
        # An extra payment already came off the schedule, so it is not coverage.
        left = max(status.money_paid - status.prepaid, ZERO)
        for day, price, interest in installment_plan(data):
            amount = price + interest
            taken = min(left, amount)
            left -= taken
            if amount - taken > ZERO:
                dues.setdefault(account, []).append(
                    Due(day, (amount - taken).quantize(ZERO), record.id, str(data.get("name", "")))
                )
    return PlansOwed(unpaid, {account: tuple(sorted(rows, key=lambda d: (d.on, d.rule_id)))
                              for account, rows in dues.items()})


def plans_on_statement(
    db: Session, cipher: UserCipher, account_id: int, start: date, closes: date
) -> List[StatementPlan]:
    """REC-29. The installments on this card with a payment on the statement [start, closes], either terms."""
    context = _Context.load(db, cipher)
    plans: List[StatementPlan] = []
    for record in context.rules:
        data = record.data
        if data.get("kind") != "installment" or data.get("account_id") != account_id:
            continue
        views = context.posted.get(record.id, [])
        payments = _scheduled_payments(views)
        here = [v for v in payments if start <= _statement_day(v) <= closes]
        if not here:
            continue
        status = _installment_status(record.id, data, views)
        plans.append(StatementPlan(
            record.id, str(data.get("name", "")), status.per_payment, terms=status.terms,
            payments_posted=len(payments), payments_on_statement=len(here), on_statement=total(v.amount for v in here),
        ))
    return plans


# ------------------------------------------------------------------ writing


def create_rule(db: Session, cipher: UserCipher, payload: Mapping[str, Any], *, today: Optional[date] = None) -> RuleView:
    today = today or date.today()
    repo = RecurringRuleRepository(db, cipher)
    if repo.count() >= MAX_RULES:
        raise BusinessRuleException(f"At most {MAX_RULES} recurring rules")

    data = _clean(db, cipher, payload, None, today, posted_count=0)
    start = _as_date(data["start"])
    # Nothing before today unless asked: those were most likely entered by hand.
    data["posted_through"] = ((start if payload.get("post_past") else max(start, today)) - ONE_DAY).isoformat()
    data.update({"pauses": [], "skips": [], "closed_on": None})

    record = repo.create(data)
    if data["kind"] == "subscription":
        SubscriptionRepository(db, cipher).create({
            "recurring_rule_id": record.id,
            "reminder_days": _reminder_days(payload.get("reminder_days"), REMINDER_DAYS_DEFAULT),
        })
    audit_service.record(
        db, audit_service.CREATE, user_id=cipher.user_id, entity="recurring_rules", entity_id=record.id,
        cipher=cipher, detail={"name": data["name"], "kind": data["kind"]},
    )
    db.commit()
    # A rule starting today posts today, not at the next sign-in.
    _expand(db, cipher, [record], today)
    return get_rule(db, cipher, record.id, today=today)


def update_rule(
    db: Session, cipher: UserCipher, rule_id: int, payload: Mapping[str, Any], *, today: Optional[date] = None
) -> RuleView:
    today = today or date.today()
    repo = RecurringRuleRepository(db, cipher)
    record = _record(repo, rule_id)
    context = _Context.load(db, cipher)
    posted = [v for v in context.posted.get(rule_id, []) if v.recurring_on is not None]
    data = _clean(db, cipher, payload, record.data, today, posted_count=len(posted))
    # REC-05, fixed 2026-09-16 (a real plan lost its first payment this way).
    # A start moved EARLIER has to bring the catch-up marker back with it, or
    # every occurrence between the new start and the old marker is treated as
    # already handled and can never post. Nothing can double up: expansion
    # skips the occurrence dates already in the working set. The pull-back is
    # capped at a year so that dragging a start into the distant past cannot
    # post years of charges in one go.
    floor = max(_as_date(data["start"]), today - timedelta(days=MAX_PULL_BACK_DAYS)) - ONE_DAY
    if floor < _as_date(data["posted_through"]):
        data["posted_through"] = floor.isoformat()
    repo.update(rule_id, data)

    if data["kind"] == "subscription" and payload.get("reminder_days") is not None:
        subs = SubscriptionRepository(db, cipher)
        for sub in subs.list():
            if sub.data.get("recurring_rule_id") == rule_id:
                subs.update(sub.id, {**sub.data, "reminder_days": _reminder_days(payload["reminder_days"], None)})
    audit_service.record(
        db, audit_service.UPDATE, user_id=cipher.user_id, entity="recurring_rules", entity_id=rule_id,
        cipher=cipher, detail={"name": data["name"], "kind": data["kind"]},
    )
    db.commit()
    return get_rule(db, cipher, rule_id, today=today)


def delete_rule(db: Session, cipher: UserCipher, rule_id: int) -> None:
    """Soft. What already posted stays posted, still carrying the rule's id - history is history."""
    repo = RecurringRuleRepository(db, cipher)
    record = _record(repo, rule_id)
    repo.soft_delete(rule_id)
    subs = SubscriptionRepository(db, cipher)
    for sub in subs.list():
        if sub.data.get("recurring_rule_id") == rule_id:
            subs.soft_delete(sub.id)
    audit_service.record(
        db, audit_service.DELETE, user_id=cipher.user_id, entity="recurring_rules", entity_id=rule_id,
        cipher=cipher, detail={"name": record.data.get("name"), "kind": record.data.get("kind")},
    )
    db.commit()


def set_paused(db: Session, cipher: UserCipher, rule_id: int, paused: bool, *, today: Optional[date] = None) -> RuleView:
    """
    REC-07. Paused from today: nothing dated inside a pause ever posts, even on
    catch-up after resuming. Resuming today ends the pause yesterday.
    """
    today = today or date.today()
    repo = RecurringRuleRepository(db, cipher)
    record = _record(repo, rule_id)
    data = dict(record.data)
    if data.get("kind") == "installment":
        raise BusinessRuleException("An installment keeps billing - skip a payment instead of pausing it")

    pauses = [dict(p) for p in data.get("pauses") or []]
    open_pause = pauses[-1] if pauses and not pauses[-1].get("to") else None
    if paused and open_pause is None:
        pauses.append({"from": today.isoformat(), "to": None})
    elif not paused and open_pause is not None:
        if _as_date(open_pause["from"]) >= today:
            pauses.pop()  # paused and resumed before anything fell inside it
        else:
            open_pause["to"] = (today - ONE_DAY).isoformat()
    data["pauses"] = pauses
    repo.update(rule_id, data)
    audit_service.record(
        db, audit_service.PAUSE if paused else audit_service.RESUME, user_id=cipher.user_id,
        entity="recurring_rules", entity_id=rule_id, cipher=cipher, detail={"name": data.get("name")},
    )
    db.commit()
    if not paused:
        _expand(db, cipher, [repo.get(rule_id)], today)
    return get_rule(db, cipher, rule_id, today=today)


def skip(db: Session, cipher: UserCipher, rule_id: int, on: date, *, today: Optional[date] = None) -> RuleView:
    """REC-15. Skip one occurrence that has not posted. An installment still owes it: the payoff moves one period."""
    today = today or date.today()
    repo = RecurringRuleRepository(db, cipher)
    record = _record(repo, rule_id)
    data = dict(record.data)
    if _as_date(data["posted_through"]) >= on:
        raise BusinessRuleException("That one has already posted - delete the transaction instead")
    if not any(not o.paused for o in occurrences(rule_id, data, on, on)):
        raise ValidationException("Nothing is scheduled on that day")
    data["skips"] = sorted({*(data.get("skips") or []), on.isoformat()})
    repo.update(rule_id, data)
    audit_service.record(
        db, audit_service.SKIP, user_id=cipher.user_id, entity="recurring_rules", entity_id=rule_id,
        cipher=cipher, detail={"name": data.get("name"), "on": on.isoformat()},
    )
    db.commit()
    return get_rule(db, cipher, rule_id, today=today)


def pay_off(db: Session, cipher: UserCipher, rule_id: int, *, today: Optional[date] = None) -> RuleView:
    """
    REC-13. Pay what is left in one go, today: one expense carrying the plan's
    id, split into the price and interest still owed, and the plan closes -
    nothing is scheduled on or after today.
    """
    today = today or date.today()
    repo = RecurringRuleRepository(db, cipher)
    record = _record(repo, rule_id)
    data = dict(record.data)
    if data.get("kind") != "installment":
        raise BusinessRuleException("Only an installment can be paid off")
    context = _Context.load(db, cipher)
    posted = context.posted.get(rule_id, [])
    status = _installment_status(rule_id, data, posted)
    if status.closed:
        raise BusinessRuleException("This plan is already paid")

    left = _close_plan(db, cipher, rule_id, data, posted, status, today)
    audit_service.record(
        db, audit_service.PAYOFF, user_id=cipher.user_id, entity="recurring_rules", entity_id=rule_id,
        cipher=cipher, detail={"name": data.get("name"), "amount": str(left)},
    )
    db.commit()
    return get_rule(db, cipher, rule_id, today=today)


def pay_now(
    db: Session,
    cipher: UserCipher,
    rule_id: int,
    *,
    on: Optional[date] = None,
    today: Optional[date] = None,
) -> RuleView:
    """
    REC-33. Record a repeating charge's NEXT occurrence now - Spotify paid
    from GCash before its date (2026-09-16, user: a normal account had no way
    to pay a monthly charge the way a card's plan has Pay).

    It posts exactly the occurrence the rule says is next, carrying that
    occurrence's date as `recurring_on`, so when its day arrives the catch-up
    finds it already posted and leaves it alone - no second charge, and the
    rule's next date moves on by itself. The entry is dated the day it was
    paid, or its own day when that has already come (an occurrence the
    catch-up simply has not reached yet). One occurrence per call.

    Installments have their own payment (REC-32) and income is not paid, so
    both are refused; a paused rule has nothing due until it is resumed.
    """
    today = today or date.today()
    on = on or today
    if on > today:
        raise BusinessRuleException("A payment is made today or on a day already past")
    repo = RecurringRuleRepository(db, cipher)
    record = _record(repo, rule_id)
    data = dict(record.data)
    if data.get("kind") == "installment":
        raise BusinessRuleException("An installment is paid with Pay on the plan")
    if data.get("type") == "income":
        raise BusinessRuleException("Income arrives by itself - there is nothing to pay")
    if data.get("closed_on"):
        raise BusinessRuleException("This rule has ended")

    context = _Context.load(db, cipher)
    view = _view(rule_id, data, context, today)
    if view.paused:
        raise BusinessRuleException("This rule is paused - resume it first")
    through = _as_date(data["posted_through"])
    posted_days = context.posted_days.get(rule_id, set())
    upcoming = next(
        (o for o in occurrences(rule_id, data, through + ONE_DAY, max(through, today) + timedelta(days=NEXT_WINDOW_DAYS))
         if not o.paused and o.on not in posted_days),
        None,
    )
    if upcoming is None:
        raise BusinessRuleException("Nothing is left to pay on this rule")
    if _problem(data, {r.id: r.data for r in AccountRepository(db, cipher).list()},
                {r.id: r.data for r in CategoryRepository(db, cipher).list()}, tag_service.known_ids(db, cipher)):
        raise BusinessRuleException("This rule needs attention first - its account or category has changed")

    payload = _payload(data, upcoming)
    payload["txn_date"] = min(upcoming.on, on).isoformat()
    transaction_service.post_recurring(db, cipher, payload, recurring_id=rule_id, recurring_on=upcoming.on)
    audit_service.record(
        db, audit_service.PAY_NOW, user_id=cipher.user_id, entity="recurring_rules", entity_id=rule_id,
        cipher=cipher, detail={"name": data.get("name"), "occurrence": upcoming.on.isoformat(),
                               "amount": str(upcoming.amount)},
    )
    db.commit()
    return get_rule(db, cipher, rule_id, today=today)


def _close_plan(
    db: Session,
    cipher: UserCipher,
    rule_id: int,
    data: Dict[str, Any],
    posted: Sequence[TransactionView],
    status: InstallmentStatus,
    on: date,
) -> Decimal:
    """
    REC-13. Charge everything the plan has still to bill as one expense dated
    `on`, split into price and interest, and close the plan. Returns the
    amount. Never commits or audits - its callers do, in their own words.
    """
    interest_category = data.get("interest_category_id")
    interest_paid = total(
        split.amount for v in posted if v.type == "expense" for split in v.splits
        if interest_category is not None and split.category_id == interest_category
    )
    price_left = max(status.price - (status.paid - interest_paid), ZERO)
    interest_left = max(status.interest - interest_paid, ZERO)
    splits = [{"category_id": data["category_id"], "amount": str(price_left)}] if price_left > ZERO else []
    if interest_left > ZERO:
        splits.append({"category_id": interest_category, "amount": str(interest_left)})

    if price_left + interest_left > ZERO:
        transaction_service.post_recurring(db, cipher, {
            "type": "expense", "amount": str(price_left + interest_left), "account_id": data["account_id"],
            "txn_date": on.isoformat(), "merchant": data.get("merchant"),
            "notes": f"Paid off - {data.get('name')}", "splits": splits, "tag_ids": data.get("tag_ids") or [],
        }, recurring_id=rule_id, recurring_on=None)
    data["closed_on"] = on.isoformat()
    data["posted_through"] = max(_as_date(data["posted_through"]), on).isoformat()
    RecurringRuleRepository(db, cipher).update(rule_id, data)
    return price_left + interest_left


def pay_plan(
    db: Session,
    cipher: UserCipher,
    rule_id: int,
    *,
    amount: Any,
    from_account_id: Any,
    on: Optional[date] = None,
    mode: Optional[str] = None,
    today: Optional[date] = None,
) -> RuleView:
    """
    REC-32. Money paid on an installment plan - the way a loan from a person or
    a store is actually paid (2026-09-16, user).

    The money is a transfer from the account you pay out of into the plan's
    account, carrying the plan's id, so the plan can say how much you have
    paid and how much is left. It covers what is DUE first: every payment dated
    on or before the payment day not yet covered - or, when nothing is due yet,
    the next payment, paid early. Anything above that is EXTRA, and the user
    chooses what it does, because the two are genuinely different:

      * "lower"   - same number of payments, each one smaller;
      * "shorten" - same monthly payment, the last ones disappear.

    Asked, not assumed: without a `mode` an extra payment answers
    PREPAYMENT_CHOICE with both outcomes worked out, and nothing is written.
    The extra is charged at once - to the plan's category, split price then
    interest, exactly what came off the schedule - so the schedule, the budget
    and what you owe all move together. Paying everything that is left closes
    the plan (REC-13) and asks nothing.
    """
    today = today or date.today()
    on = on or today
    if on > today:
        raise BusinessRuleException("A payment is made today or on a day already past")
    repo = RecurringRuleRepository(db, cipher)
    record = _record(repo, rule_id)
    data = dict(record.data)
    if data.get("kind") != "installment":
        raise BusinessRuleException("Only an installment plan takes payments")
    if not isinstance(from_account_id, int) or isinstance(from_account_id, bool):
        raise ValidationException("Choose the account you pay from")
    if from_account_id == int(data["account_id"]):
        raise BusinessRuleException("Pay from a different account than the plan's own")
    amount = _positive(amount, "amount")

    context = _Context.load(db, cipher)
    posted = context.posted.get(rule_id, [])
    status = _installment_status(rule_id, data, posted)
    if status.closed:
        raise BusinessRuleException("This plan is already paid")
    if amount > status.left_to_pay:
        raise BusinessRuleException(f"That is more than the {status.left_to_pay} left to pay on this plan")

    rows = installment_plan(data)
    due, boundary = _due_part(rows, status.money_paid - status.prepaid, on)
    regular = min(amount, due)
    extra = amount - regular
    settles = amount == status.left_to_pay

    if extra > ZERO and not settles:
        if mode is None:
            raise PrepaymentChoiceException(
                "Choose what the extra payment does",
                extra={"due": str(regular), "extra": str(extra),
                       **{choice: _outcome(data, boundary, extra, choice) for choice in PREPAYMENT_MODES}},
            )
        if mode not in PREPAYMENT_MODES:
            raise ValidationException(f"mode must be one of: {', '.join(PREPAYMENT_MODES)}")

    # The money, both legs, carrying the plan's id - never a schedule date, so
    # the catch-up can never mistake it for a payment it posted itself.
    transaction_service.post_recurring(db, cipher, {
        "type": "transfer", "amount": str(amount), "account_id": from_account_id,
        "counter_account_id": data["account_id"], "txn_date": on.isoformat(),
        "notes": f"Payment - {data.get('name')}",
    }, recurring_id=rule_id, recurring_on=None)

    if settles:
        _close_plan(db, cipher, rule_id, data, posted, status, on)
    elif extra > ZERO:
        extra_row = {"on": on.isoformat(), "after": boundary.isoformat(), "amount": str(extra), "mode": mode}
        after = installment_plan({**data, "prepayments": list(data.get("prepayments") or []) + [extra_row]})
        price_cut = total(r[1] for r in rows) - total(r[1] for r in after)
        interest_cut = total(r[2] for r in rows) - total(r[2] for r in after)
        splits = [{"category_id": data["category_id"], "amount": str(price_cut)}] if price_cut > ZERO else []
        if interest_cut > ZERO:
            splits.append({"category_id": data.get("interest_category_id"), "amount": str(interest_cut)})
        transaction_service.post_recurring(db, cipher, {
            "type": "expense", "amount": str(extra), "account_id": data["account_id"],
            "txn_date": on.isoformat(), "merchant": data.get("merchant") or data.get("name"),
            "notes": f"Extra payment - {data.get('name')}", "splits": splits, "tag_ids": data.get("tag_ids") or [],
        }, recurring_id=rule_id, recurring_on=None)
        data["prepayments"] = list(data.get("prepayments") or []) + [extra_row]
        repo.update(rule_id, data)

    audit_service.record(
        db, audit_service.PLAN_PAYMENT, user_id=cipher.user_id, entity="recurring_rules", entity_id=rule_id,
        cipher=cipher, detail={"name": data.get("name"), "amount": str(amount), "extra": str(extra),
                               "mode": "settled" if settles else mode},
    )
    db.commit()
    return get_rule(db, cipher, rule_id, today=today)


def _due_part(rows: Sequence[PlanRow], covered: Decimal, on: date) -> Tuple[Decimal, date]:
    """
    REC-32. (what a payment made on `on` covers before anything counts as
    extra, the day after which an extra payment changes the schedule).

    Earlier payments cover the plan oldest first. What is due is every payment
    dated on or before `on` that they have not covered; when nothing is due,
    the next payment counts instead - paying it early is not paying extra.
    """
    left = covered
    due = ZERO
    upcoming: Optional[Tuple[Decimal, date]] = None
    for day, price, interest in rows:
        amount = price + interest
        taken = min(left, amount)
        left -= taken
        uncovered = amount - taken
        if day <= on:
            due += uncovered
        elif upcoming is None:
            upcoming = (uncovered, day)
    if due > ZERO or upcoming is None:
        return due, on
    return upcoming[0], (upcoming[1] if upcoming[0] > ZERO else on)


def _outcome(data: Mapping[str, Any], after: date, extra: Decimal, mode: str) -> Dict[str, Any]:
    """The plan as it would be with this extra payment applied this way - the numbers the question shows."""
    row = {"on": after.isoformat(), "after": after.isoformat(), "amount": str(extra), "mode": mode}
    later = [r for r in installment_plan({**data, "prepayments": list(data.get("prepayments") or []) + [row]})
             if r[0] > after]
    return {
        "payment": str(later[0][1] + later[0][2]) if later else "0.00",
        "payments": len(later),
        "payoff_on": later[-1][0].isoformat() if later else None,
    }


def confirm_interest(
    db: Session,
    cipher: UserCipher,
    rule_id: int,
    per_payment: Decimal,
    *,
    category_id: Optional[int] = None,
    today: Optional[date] = None,
) -> RuleView:
    """
    REC-29. A statement shows what the bank adds per payment. The plan becomes
    price + per_payment × payments, and EVERY payment already posted at the
    provisional amount is corrected to carry its interest, on its own day - so
    each stays on the statement the bank billed it on, and a plan confirmed
    after two or three bills ends at exactly zero like one confirmed after the
    first. Later payments post both splits (REC-30).
    """
    today = today or date.today()
    repo = RecurringRuleRepository(db, cipher)
    record = _record(repo, rule_id)
    data = dict(record.data)
    if data.get("kind") != "installment":
        raise BusinessRuleException("Only an installment has terms to confirm")
    if data.get("terms") == "confirmed":
        raise BusinessRuleException("This plan's interest is already confirmed")
    if per_payment <= ZERO:
        raise ValidationException("Interest is more than zero")

    categories = {r.id: r.data for r in CategoryRepository(db, cipher).list()}
    chosen = category_id or data.get("interest_category_id") or _interest_category(categories)
    _check_interest_category(chosen, data.get("category_id"), categories)

    before = data.get("interest_category_id")
    data.update({
        "interest": str(per_payment * int(data["payments"])),
        "terms": "confirmed",
        "interest_category_id": chosen,
    })
    repo.update(rule_id, data)
    posted = _scheduled_payments(_Context.load(db, cipher).posted.get(rule_id, []))
    for view in posted:
        _reprice(db, cipher, view, per_payment, chosen, before)
    audit_service.record(
        db, audit_service.CONFIRM_TERMS, user_id=cipher.user_id, entity="recurring_rules", entity_id=rule_id,
        cipher=cipher, detail={"name": data.get("name"), "interest_per_payment": str(per_payment),
                               "payments_corrected": len(posted)},
    )
    db.commit()
    return get_rule(db, cipher, rule_id, today=today)


def change_installment_payment(
    db: Session,
    cipher: UserCipher,
    rule_id: int,
    payment: Decimal,
    *,
    start: date,
    closes: date,
    category_id: Optional[int] = None,
    today: Optional[date] = None,
) -> RuleView:
    """
    REC-29, its last sentence. A later bill shows a different payment: the
    bank changed what it adds. From this plan's first payment on the statement
    [start, closes], each payment carries `payment` less its share of the price
    as interest - the payments already posted from there are corrected to it,
    and the rest post that way, through the plan's dated `interest_changes`
    (REC-20). Payments before it keep what they were billed, and a newer change
    replaces any later one. The price never changes: it is what was bought.
    """
    today = today or date.today()
    repo = RecurringRuleRepository(db, cipher)
    record = _record(repo, rule_id)
    data = dict(record.data)
    if data.get("kind") != "installment":
        raise BusinessRuleException("Only an installment has a payment to change")
    if data.get("terms") != "confirmed":
        raise BusinessRuleException("Confirm this plan's interest first")
    if payment <= ZERO:
        raise ValidationException("A payment is more than zero")

    posted = _scheduled_payments(_Context.load(db, cipher).posted.get(rule_id, []))
    here = [v for v in posted if start <= _statement_day(v) <= closes]
    if not here:
        raise BusinessRuleException("This plan has no payment on this statement")
    first = here[0].recurring_on
    scheduled = [o for o in occurrences(rule_id, {**data, "closed_on": None}, first, first) if not o.paused]
    if not scheduled:
        raise BusinessRuleException("That payment is no longer on the plan's schedule")
    price_part = scheduled[0].splits[0][1]
    interest = payment - price_part
    if interest < ZERO:
        raise BusinessRuleException(f"A payment cannot be less than its share of the price, {price_part}")

    categories = {r.id: r.data for r in CategoryRepository(db, cipher).list()}
    before = data.get("interest_category_id")
    chosen = category_id or before or _interest_category(categories)
    if interest > ZERO:
        _check_interest_category(chosen, data.get("category_id"), categories)

    changes = [c for c in data.get("interest_changes") or [] if _as_date(c["from"]) < first]
    changes.append({"from": first.isoformat(), "per_payment": str(interest)})
    data.update({"interest_changes": changes, "interest_category_id": chosen})
    repo.update(rule_id, data)
    corrected = [v for v in posted if v.recurring_on >= first]
    for view in corrected:
        _reprice(db, cipher, view, interest, chosen, before)
    audit_service.record(
        db, audit_service.UPDATE, user_id=cipher.user_id, entity="recurring_rules", entity_id=rule_id,
        cipher=cipher, detail={"name": data.get("name"), "payment": str(payment), "from": first.isoformat(),
                               "payments_corrected": len(corrected)},
    )
    db.commit()
    return get_rule(db, cipher, rule_id, today=today)


def expand(db: Session, cipher: UserCipher, *, today: Optional[date] = None) -> Expansion:
    """REC-04/05. Post everything due up to today that has not posted - safe to call as often as you like."""
    return _expand(db, cipher, RecurringRuleRepository(db, cipher).list(), today or date.today())


# ---------------------------------------------------------------- internals


@dataclass
class _Context:
    rules: List[Any]
    posted: Dict[int, List[TransactionView]]  # every transaction carrying a rule's id
    posted_days: Dict[int, Set[date]]  # the occurrence dates already posted
    reminders: Dict[int, int]
    receipts: Dict[int, int] = field(default_factory=dict)  # REC-34 - a converted purchase's receipt

    @classmethod
    def load(cls, db: Session, cipher: UserCipher) -> "_Context":
        posted: Dict[int, List[TransactionView]] = {}
        days: Dict[int, Set[date]] = {}
        for view in transaction_service.views(db, cipher):
            if view.recurring_id is None:
                continue
            posted.setdefault(view.recurring_id, []).append(view)
            if view.recurring_on is not None:
                days.setdefault(view.recurring_id, set()).add(view.recurring_on)
        reminders = {
            int(sub.data["recurring_rule_id"]): int(sub.data.get("reminder_days", REMINDER_DAYS_DEFAULT))
            for sub in SubscriptionRepository(db, cipher).list()
        }
        rules = RecurringRuleRepository(db, cipher).list()
        receipts: Dict[int, int] = {}
        hidden = TransactionRepository(db, cipher)
        for rule in rules:
            if rule.data.get("from_transaction"):
                # The purchase is hidden while the plan stands; its receipt is the plan's.
                original = hidden.get(int(rule.data["from_transaction"]), include_deleted=True)
                if original is not None and original.data.get("attachment_id"):
                    receipts[rule.id] = int(original.data["attachment_id"])
        return cls(rules, posted, days, reminders, receipts)


def _expand(db: Session, cipher: UserCipher, records: Sequence[Any], today: date) -> Expansion:
    context = _Context.load(db, cipher)
    accounts = {r.id: r.data for r in AccountRepository(db, cipher).list()}
    categories = {r.id: r.data for r in CategoryRepository(db, cipher).list()}
    tags = tag_service.known_ids(db, cipher)
    repo = RecurringRuleRepository(db, cipher)

    posted = 0
    touched = 0
    attention: List[int] = []
    for record in records:
        data = record.data
        through = _as_date(data["posted_through"])
        if through >= today:
            continue
        already = context.posted_days.get(record.id, set())
        due = [o for o in occurrences(record.id, data, through + ONE_DAY, today) if not o.paused and o.on not in already]
        if not due:
            continue
        if _problem(data, accounts, categories, tags):
            attention.append(record.id)
            continue
        for occurrence in due:
            transaction_service.post_recurring(db, cipher, _payload(data, occurrence),
                                               recurring_id=record.id, recurring_on=occurrence.on)
            posted += 1
        # The same commit as the postings: the marker and the rows never disagree.
        repo.update(record.id, {**data, "posted_through": today.isoformat()})
        touched += 1

    if posted:
        audit_service.record(
            db, audit_service.EXPAND, user_id=cipher.user_id, entity="recurring_rules", cipher=cipher,
            detail={"posted": posted, "rules": touched, "through": today.isoformat()},
        )
        db.commit()
    return Expansion(posted=posted, rules=touched, needs_attention=tuple(attention))


def _payload(data: Mapping[str, Any], occurrence: Occurrence) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "type": data["type"], "amount": str(occurrence.amount), "account_id": data["account_id"],
        "txn_date": occurrence.on.isoformat(), "notes": data.get("notes"),
    }
    if data["type"] == "transfer":
        payload["counter_account_id"] = data["counter_account_id"]
    else:
        # The rule's name stands in for a merchant, so the ledger says "Phone", not just its category.
        payload["merchant"] = data.get("merchant") or data.get("name")
        payload["tag_ids"] = list(data.get("tag_ids") or [])
        payload["splits"] = [{"category_id": c, "amount": str(a)} for c, a in occurrence.splits if a > ZERO]
    return payload


def _problem(
    data: Mapping[str, Any], accounts: Mapping[int, Mapping], categories: Mapping[int, Mapping], tags: Set[int]
) -> Optional[str]:
    """Why expansion cannot post this rule as it stands - an archived account, a category gone - or None."""
    for key in ("account_id", "counter_account_id"):
        account_id = data.get(key)
        if account_id is None:
            continue
        if account_id not in accounts:
            return "Its account no longer exists"
        if accounts[account_id].get("archived"):
            return "Its account is archived"
    if data.get("type") != "transfer":
        category = categories.get(data.get("category_id"))
        if category is None or category.get("kind") != data.get("type"):
            return "Its category no longer exists"
        for share in data.get("category_shares") or []:
            if categories.get(share.get("category_id")) is None:
                return "One of its categories no longer exists"
        if data.get("kind") == "installment" and money(data.get("interest") or ZERO) > ZERO:
            if categories.get(data.get("interest_category_id")) is None:
                return "Its interest category no longer exists"
    if not set(data.get("tag_ids") or []) <= tags:
        return "One of its tags no longer exists"
    return None


def _view(rule_id: int, data: Mapping[str, Any], context: _Context, today: date) -> RuleView:
    posted = context.posted.get(rule_id, [])
    posted_days = context.posted_days.get(rule_id, set())
    through = _as_date(data["posted_through"])
    first = through + ONE_DAY
    nxt = next(
        (o for o in occurrences(rule_id, data, first, max(first, today) + timedelta(days=NEXT_WINDOW_DAYS))
         if not o.paused and o.on not in posted_days),
        None,
    )
    installment = _installment_status(rule_id, data, posted) if data.get("kind") == "installment" else None
    pauses = data.get("pauses") or []
    return RuleView(
        id=rule_id,
        kind=str(data.get("kind")),
        type=str(data.get("type")),
        name=str(data.get("name", "")),
        account_id=int(data["account_id"]),
        counter_account_id=data.get("counter_account_id"),
        category_id=data.get("category_id"),
        interest_category_id=data.get("interest_category_id"),
        merchant=data.get("merchant"),
        notes=data.get("notes"),
        tag_ids=tuple(data.get("tag_ids") or ()),
        frequency=str(data.get("frequency")),
        interval=int(data.get("interval") or 1),
        start=_as_date(data["start"]),
        days=tuple(int(d) for d in data.get("days") or ()),
        end_after=data.get("end_after"),
        end_on=_opt_date(data.get("end_on")),
        amount=installment.per_payment if installment else amount_on(data, today),
        amounts=tuple(AmountChange(_as_date(a["from"]), money(a["amount"]))
                      for a in sorted(data.get("amounts") or [], key=lambda a: str(a["from"]))),
        paused=bool(pauses) and not pauses[-1].get("to"),
        skips=tuple(_as_date(d) for d in data.get("skips") or ()),
        closed_on=_opt_date(data.get("closed_on")),
        posted_through=through,
        next_on=nxt.on if nxt and not (installment and installment.closed) else None,
        next_amount=nxt.amount if nxt and not (installment and installment.closed) else None,
        reminder_days=context.reminders.get(rule_id) if data.get("kind") == "subscription" else None,
        installment=installment,
        from_transaction=data.get("from_transaction"),
        receipt_id=context.receipts.get(rule_id),
    )


def _installment_status(rule_id: int, data: Mapping[str, Any], posted: Sequence[TransactionView]) -> InstallmentStatus:
    price = money(data["price"])
    payments = int(data["payments"])
    start = _as_date(data["start"])
    # Far enough for the last payment of any schedule; the loop stops at the payment count anyway.
    horizon = start + timedelta(days=min(366 * (payments * int(data.get("interval") or 1) + 1), 366 * 2000))
    schedule = occurrences(rule_id, {**data, "closed_on": None}, start, horizon)
    prepaid = total(money(p["amount"]) for p in data.get("prepayments") or [])
    if len(schedule) == len(installment_plan(data)):
        # The schedule IS the plan: with a later change of interest (REC-29) the
        # total is what each payment carries, not one figure times the count -
        # and an extra payment (REC-32) is part of it, taken off the schedule.
        whole = total(o.amount for o in schedule) + prepaid
    else:
        whole = price + money(data.get("interest") or ZERO)
    interest = whole - price
    paid = total(v.amount for v in posted if v.type == "expense")
    remaining = max(whole - paid, ZERO)
    per_payment = schedule[0].amount if schedule else split_schedule(price, payments)[0]
    money_paid = total(v.amount for v in posted if v.type == "transfer" and v.direction == "in")
    posted_days = {v.recurring_on for v in posted if v.type == "expense" and v.recurring_on is not None}
    to_come = [o for o in schedule if o.on not in posted_days]
    return InstallmentStatus(
        price=price,
        interest=interest,
        total=whole,
        payments=payments,
        per_payment=per_payment,
        terms=str(data.get("terms") or "provisional"),
        paid=paid,
        remaining=remaining,
        payments_posted=sum(1 for v in posted if v.type == "expense" and v.recurring_on is not None),
        payoff_on=_opt_date(data.get("closed_on")) or (schedule[-1].on if schedule else None),
        closed=data.get("closed_on") is not None or remaining == ZERO,
        money_paid=money_paid,
        left_to_pay=max(whole - money_paid, ZERO),
        current_payment=to_come[0].amount if to_come else ZERO,
        payments_left=0 if data.get("closed_on") else len(to_come),
        prepaid=prepaid,
    )


def _scheduled_payments(views: Sequence[TransactionView]) -> List[TransactionView]:
    """An installment's posted payments - not its payoff or other one-offs - in schedule order."""
    return sorted((v for v in views if v.type == "expense" and v.recurring_on is not None),
                  key=lambda v: (v.recurring_on, v.id))


def _statement_day(view: TransactionView) -> date:
    """The day that puts a posting on a card statement (ACC-26)."""
    return view.card_posted_on or view.txn_date


def _reprice(
    db: Session,
    cipher: UserCipher,
    view: TransactionView,
    interest: Decimal,
    interest_category: Optional[int],
    old_interest_category: Optional[int],
) -> None:
    """REC-29. One posted payment corrected to carry `interest`; its price split is left exactly as posted."""
    interest_categories = {interest_category, old_interest_category} - {None}
    price = [s for s in view.splits if s.category_id not in interest_categories]
    splits = [{"category_id": s.category_id, "amount": str(s.amount)} for s in price]
    if interest > ZERO:
        splits.append({"category_id": interest_category, "amount": str(interest)})
    transaction_service.reprice_recurring(
        db, cipher, view.id, amount=total(s.amount for s in price) + interest, splits=splits,
    )


def _clean(
    db: Session,
    cipher: UserCipher,
    payload: Mapping[str, Any],
    existing: Optional[Mapping[str, Any]],
    today: date,
    *,
    posted_count: int,
) -> Dict[str, Any]:
    data = _pure(payload, existing, today, posted_count)
    accounts = {r.id: r.data for r in AccountRepository(db, cipher).list()}
    categories = {r.id: r.data for r in CategoryRepository(db, cipher).list()}

    def account(key: str) -> int:
        value = payload.get(key, data.get(key))
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValidationException(f"Choose an account ({key})")
        if value not in accounts:
            raise ValidationException("That account does not exist")
        if accounts[value].get("archived") and value != (existing or {}).get(key):
            raise BusinessRuleException("That account is archived")
        return value

    data["account_id"] = account("account_id")
    if data["type"] == "transfer":
        data["counter_account_id"] = account("counter_account_id")
        if data["counter_account_id"] == data["account_id"]:
            raise BusinessRuleException("A transfer moves money between two different accounts")
        data.update({"category_id": None, "interest_category_id": None, "merchant": None, "tag_ids": []})
    else:
        data["counter_account_id"] = None
        category_id = payload.get("category_id", data.get("category_id"))
        category = categories.get(category_id)
        if category is None:
            raise ValidationException("Choose a category")
        if category.get("kind") != data["type"]:
            raise BusinessRuleException(f"An {data['type']} needs an {data['type']} category")
        data["category_id"] = category_id

        interest_category = None
        if data["kind"] == "installment":
            interest_category = payload.get("interest_category_id", data.get("interest_category_id"))
            if interest_category is None and money(data.get("interest") or ZERO) > ZERO:
                interest_category = _interest_category(categories)
            if interest_category is not None:
                _check_interest_category(interest_category, category_id, categories)
        data["interest_category_id"] = interest_category

        shares = payload.get("category_shares", data.get("category_shares"))
        if existing and payload.get("category_id") not in (None, existing.get("category_id")):
            shares = None  # a plan moved to one category is in that category only
        if shares:
            if data["kind"] != "installment" or not isinstance(shares, list) or len(shares) < 2:
                raise ValidationException("Only an installment splits its payments across categories")
            cleaned_shares = []
            for share in shares:
                share_category = categories.get(share.get("category_id")) if isinstance(share, Mapping) else None
                if share_category is None or share_category.get("kind") != "expense":
                    raise ValidationException("Each part of the plan needs an expense category")
                cleaned_shares.append({"category_id": share["category_id"],
                                       "amount": str(_positive(share.get("amount"), "amount"))})
            data["category_shares"] = cleaned_shares
        else:
            data.pop("category_shares", None)

        merchant = payload.get("merchant", data.get("merchant"))
        data["merchant"] = _text(merchant, MERCHANT_MAX)
        data["tag_ids"] = _tag_ids(db, cipher, payload.get("tag_ids", data.get("tag_ids")))

    data["notes"] = _text(payload.get("notes", data.get("notes")), NOTES_MAX)
    name = " ".join(str(payload.get("name") or data.get("name") or "").split())
    if not name:
        category = categories.get(data.get("category_id")) or {}
        name = data.get("merchant") or category.get("name") or "Transfer"
    if len(name) > NAME_MAX:
        raise ValidationException(f"A name is at most {NAME_MAX} characters")
    data["name"] = name
    return data


def _pure(
    payload: Mapping[str, Any], existing: Optional[Mapping[str, Any]], today: date, posted_count: int
) -> Dict[str, Any]:
    """Kind, type, schedule and amounts - everything but references, so preview needs no database."""
    data: Dict[str, Any] = dict(existing or {})
    kind = _choice(payload.get("kind") or data.get("kind") or "standard", KINDS, "kind")
    kind_type = _choice(payload.get("type") or data.get("type") or "expense", TYPES, "type")
    if existing and (kind != existing.get("kind") or kind_type != existing.get("type")):
        raise BusinessRuleException("A rule's kind and type cannot change - end it and add a new one")
    if kind != "standard" and kind_type != "expense":
        raise BusinessRuleException(f"A {kind} is an expense")
    data["kind"], data["type"] = kind, kind_type
    data.update(_schedule(payload, data))

    if kind == "installment":
        price = _positive(payload.get("price", data.get("price")), "price")
        payments = _int_range(payload.get("payments", data.get("payments")), "payments", 1, MAX_PAYMENTS)
        raw_interest = payload.get("interest", data.get("interest"))
        interest = _amount(raw_interest, "interest") if raw_interest is not None else None
        if interest is not None and interest < ZERO:
            raise ValidationException("Interest is zero or more")
        terms = "confirmed" if interest is not None else "provisional"
        for part, label in ((price, "price"), (interest or ZERO, "interest")):
            # Every payment must carry something - a ₱0.00 payment could never post.
            if part > ZERO and min(split_schedule(part, payments)) <= ZERO:
                raise ValidationException(f"The {label} is too small to split into {payments} payments")
        data.update({"price": str(price), "payments": payments, "end_after": payments, "end_on": None,
                     "interest": str(interest) if interest is not None else None, "terms": terms})
        data.pop("amounts", None)
        if existing and (posted_count or existing.get("prepayments")):
            fixed = ("price", "payments", "interest", "start", "frequency", "interval", "days")
            if any(_same(data.get(k)) != _same(existing.get(k)) for k in fixed):
                raise BusinessRuleException(
                    "Payments have posted on this plan, so its terms are fixed - skip a payment or pay it off instead"
                )
        return data

    amounts = [dict(a) for a in data.get("amounts") or []]
    if payload.get("amount") is not None:
        amount = _positive(payload["amount"], "amount")
        if not amounts:
            amounts = [{"from": data["start"], "amount": str(amount)}]
        else:
            effective = _as_date(payload.get("amount_from") or max(today, _as_date(data["start"])))
            if amount_on({"amounts": amounts}, effective) != amount:
                # SUB-08 / REC-20: the old amount stays in the history; nothing posted changes.
                amounts = [a for a in amounts if a["from"] != effective.isoformat()]
                amounts.append({"from": effective.isoformat(), "amount": str(amount)})
                amounts.sort(key=lambda a: a["from"])
    if not amounts:
        raise ValidationException("A rule needs an amount")
    data["amounts"] = amounts
    return data


def _schedule(payload: Mapping[str, Any], data: Mapping[str, Any]) -> Dict[str, Any]:
    frequency = _choice(payload.get("frequency") or data.get("frequency") or "monthly", FREQUENCIES, "frequency")
    interval = 1 if frequency == "semi_monthly" else _int_range(
        payload.get("interval", data.get("interval", 1)), "interval", 1, MAX_INTERVAL)
    raw_start = payload.get("start") or data.get("start")
    if raw_start is None:
        raise ValidationException("A rule needs a first date")
    start = _as_date(raw_start)

    days: List[int] = []
    if frequency == "semi_monthly":
        raw = payload.get("days") or data.get("days") or []
        if not isinstance(raw, (list, tuple)):
            raise ValidationException("days is a list of days of the month")
        days = sorted({_int_range(d, "days", 1, 31) for d in raw})
        if not 2 <= len(days) <= 4:
            raise ValidationException("A twice-a-month rule needs two different days, like the 15th and 30th")

    clear = bool(payload.get("clear_end"))
    end_after = None if clear else payload.get("end_after", data.get("end_after"))
    end_on = None if clear else payload.get("end_on", data.get("end_on"))
    if end_after is not None:
        end_after = _int_range(end_after, "end_after", 1, 999)
    if end_on is not None:
        end_on = _as_date(end_on)
        if end_on < start:
            raise ValidationException("A rule cannot end before it starts")
    return {
        "frequency": frequency, "interval": interval, "start": start.isoformat(), "days": days,
        "end_after": end_after, "end_on": end_on.isoformat() if end_on else None,
    }


def _interest_category(categories: Mapping[int, Mapping[str, Any]]) -> Optional[int]:
    """Financial › Interest from the default set (CAT-07), when the user has not picked one."""
    matches = [cid for cid, c in categories.items()
               if c.get("kind") == "expense" and not c.get("archived") and str(c.get("name", "")).casefold() == "interest"]
    return min(matches) if matches else None


def _check_interest_category(chosen: Any, category_id: Any, categories: Mapping[int, Mapping[str, Any]]) -> None:
    if chosen is None:
        raise ValidationException("Choose a category for the interest")
    category = categories.get(chosen)
    if category is None or category.get("kind") != "expense":
        raise ValidationException("The interest category must be a spending category")
    if chosen == category_id:
        # One category for both would make the price and the interest impossible to tell apart.
        raise BusinessRuleException("Put the interest in a different category from the purchase")


def _tag_ids(db: Session, cipher: UserCipher, raw: Any) -> List[int]:
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise ValidationException("tag_ids is a list")
    chosen: List[int] = []
    for value in raw:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValidationException("A tag id is a number")
        if value not in chosen:
            chosen.append(value)
    if len(chosen) > MAX_TAGS:
        raise ValidationException(f"At most {MAX_TAGS} tags")
    if chosen and not set(chosen) <= tag_service.known_ids(db, cipher):
        raise ValidationException("That tag does not exist")
    return chosen


def _record(repo: RecurringRuleRepository, rule_id: int):
    record = repo.get(rule_id)
    if record is None:
        raise NotFoundException("Recurring rule not found")
    return record


def _category(data: Mapping[str, Any], transfer: bool) -> Optional[int]:
    return None if transfer else data.get("category_id")


def _reminder_days(value: Any, default: Optional[int]) -> int:
    if value is None:
        if default is None:
            raise ValidationException("reminder_days is 0-30")
        return default
    return _int_range(value, "reminder_days", 0, 30)


def _same(value: Any) -> str:
    return "" if value is None else str(value)


def _choice(value: Any, allowed: Tuple[str, ...], name: str) -> str:
    text = str(value).strip().lower()
    if text not in allowed:
        raise ValidationException(f"{name} must be one of: {', '.join(allowed)}")
    return text


def _int_range(value: Any, name: str, low: int, high: int) -> int:
    if isinstance(value, bool):
        raise ValidationException(f"{name} must be {low}-{high}")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationException(f"{name} must be {low}-{high}") from None
    if not low <= number <= high:
        raise ValidationException(f"{name} must be {low}-{high}")
    return number


def _amount(value: Any, name: str) -> Decimal:
    try:
        return money(value)
    except ValueError as exc:
        raise ValidationException(f"{name}: {exc}") from None


def _positive(value: Any, name: str) -> Decimal:
    if value is None:
        raise ValidationException(f"A rule needs {'a price' if name == 'price' else 'an amount'}")
    amount = _amount(value, name)
    if amount <= ZERO:
        raise ValidationException("An amount is more than zero")
    if amount > transaction_service.MAX_AMOUNT:
        raise ValidationException("That amount is larger than this app records")
    return amount


def _text(value: Any, limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValidationException("Dates look like 2026-09-15") from None


def _opt_date(value: Any) -> Optional[date]:
    return _as_date(value) if value else None
