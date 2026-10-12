"""
goal_service - savings goals (GOA-01..08; FEATURES.md §13-C).

A GOAL IS MONEY SET ASIDE INSIDE ONE ACCOUNT (GOA-08, 2026-09-16 - the user's
redesign). "Add money" earmarks part of the account's balance for the goal;
nothing moves. The balance stays exactly the sum of the account's transactions,
so it still matches the bank's own app, while what is set aside comes off the
account's AVAILABLE money and off cash on hand (ACC-17) - it cannot be spent by
mistake. Net worth still counts it: set-aside money is still yours.

    Seabank                         36,794.01   balance - matches the bank
      set aside · Emergency fund    -5,000.00
      set aside · Laptop            -8,000.00
      available                     23,794.01   what cash on hand counts

Progress is the goal's own dated list of what was set aside and what was used
(`set_aside` entries), summed on every read - never a stored figure, and never
the account's whole balance (the model before 2026-09-16, whose "Add money"
was a real transfer from another account). Goals made before the change start
at nothing set aside, by the user's choice.

Several goals may share an account, because each claims only its own part. What
may be set aside is limited by what is still available; when spending later
takes the balance below what is set aside, every goal on that account reports
`short_by` rather than pretending the money is there. Deleting a goal releases
what it held. A goal needs a cash, debit or savings account - a card's balance
is a debt and an investment's is a valuation, and neither is money you can set
aside.

THREE KINDS (Phase 13, 2026-09-28). A `saving` goal is the above. A `sinking`
fund is money put by for a cost that comes back - insurance, registration,
school fees: it can REPEAT EVERY YEAR (its date rolls on once passed), or
FOLLOW A YEARLY BILL, whose next occurrence (THE schedule, occurrences())
gives its amount and date (GOA-09). An `emergency` fund is the one goal the
emergency-fund cover and advisor read (GOA-10/11) - at most one. Every kind
shows THIS MONTH'S PART: what the month asks for to stay on time, and how much
of it is set aside already.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Mapping, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import BusinessRuleException, NotFoundException, ValidationException
from app.core.utils.money import ZERO, money
from app.db.models import SavingsGoal
from app.db.repositories.account_repository import AccountRepository
from app.db.repositories.encrypted_repository import EncryptedRepository
from app.services import account_service, audit_service, transaction_service

GOAL_ACCOUNT_TYPES = ("cash", "debit", "savings")
NAME_MAX = 60
NOTE_MAX = 120
MAX_GOALS = 50
MAX_ENTRIES = 1000  # a goal's own history; far beyond years of weekly saving
RATIO = Decimal("0.0001")
ENTRY_KINDS = ("add", "use")
KINDS = ("saving", "sinking", "emergency")  # Phase 13
YEARLY_HORIZON_DAYS = 800  # how far ahead a yearly bill's next occurrence is looked for


class GoalRepository(EncryptedRepository):
    model = SavingsGoal


@dataclass(frozen=True)
class GoalView:
    id: int
    name: str
    target: Decimal
    target_date: Optional[date]
    account_id: int
    colour: str
    icon: str
    saved: Decimal  # what is set aside for this goal: added less used
    remaining: Decimal
    ratio: Decimal  # 0..1, for the bar
    reached: bool
    # GOA-08. The account it lives in, as far as setting aside goes.
    account_balance: Decimal = ZERO
    account_available: Decimal = ZERO  # balance less everything set aside there, by every goal
    short_by: Decimal = ZERO  # how far the balance has fallen below what is set aside there
    # GOA-05. What to set aside each month to reach the target on time, and over how many months.
    per_month: Optional[Decimal] = None
    months_left: Optional[int] = None
    overdue: bool = False  # the target date has passed and it is not reached
    # Phase 13. What kind of goal, and - for a sinking fund - what it follows.
    kind: str = "saving"  # saving | sinking | emergency
    repeats_yearly: bool = False  # GOA-09 - the date rolls on a year once it has passed
    rule_id: Optional[int] = None  # GOA-09 - a yearly bill whose next occurrence sets amount and date
    # THIS MONTH'S PART (GOA-09): what the month asks for to stay on time, and what is set aside in it already.
    month_need: Optional[Decimal] = None
    month_added: Decimal = ZERO
    month_done: bool = False


def monthly_need(remaining: Decimal, today: date, target_date: Optional[date]) -> Tuple[Optional[Decimal], Optional[int]]:
    """
    GOA-05. (amount a month, months) to set aside `remaining` by `target_date`.

    Months are counted INCLUDING this one and the target's own month - money
    set aside in September counts in September - so a target later this month
    asks for all of it now. Rounded UP to the centavo: rounding down would
    leave the last month a centavo short. None with no date, a date already
    past, or nothing left. Pure, and shared by the goals built on it (sinking
    funds, the emergency fund, the payday prompt - ROADMAP.md Phase 13).
    """
    if target_date is None or remaining <= ZERO or target_date < today:
        return None, None
    months = (target_date.year - today.year) * 12 + (target_date.month - today.month) + 1
    return (remaining / months).quantize(Decimal("0.01"), rounding=ROUND_CEILING), months


def list_goals(db: Session, cipher: UserCipher, *, today: Optional[date] = None) -> List[GoalView]:
    records = GoalRepository(db, cipher).list()
    balances = _balances(db, cipher, today)
    held = _held_by_account(records)
    rules = _rules(db, cipher)
    views = [_view(r.id, r.data, balances, held, today or date.today(), rules) for r in records]
    return sorted(views, key=lambda v: (v.reached, v.target_date or date.max, v.name.casefold()))


def get_goal(db: Session, cipher: UserCipher, goal_id: int, *, today: Optional[date] = None) -> GoalView:
    repo = GoalRepository(db, cipher)
    record = repo.get(goal_id)
    if record is None:
        raise NotFoundException("Goal not found")
    return _view(record.id, record.data, _balances(db, cipher, today), _held_by_account(repo.list()),
                 today or date.today(), _rules(db, cipher))


@dataclass(frozen=True)
class YearlyBill:
    """GOA-09. A repeating bill no sinking fund is putting money by for yet."""

    rule_id: int
    name: str
    amount: Decimal
    on: date


def yearly_bills(db: Session, cipher: UserCipher, *, today: Optional[date] = None) -> List[YearlyBill]:
    """
    GOA-09. Bills that come ONCE A YEAR (or less often) with no sinking fund
    following them - offered as "Set aside for it" on the Goals screen. Their
    next occurrence comes from THE schedule. Reads only.
    """
    today = today or date.today()
    followed = {r.data.get("rule_id") for r in GoalRepository(db, cipher).list() if r.data.get("rule_id")}
    found: List[YearlyBill] = []
    for rule_id, rule in _rules(db, cipher).items():
        yearly = rule.get("frequency") == "yearly" or (rule.get("frequency") == "monthly"
                                                        and int(rule.get("interval") or 1) >= 12)
        if not yearly or rule.get("type") != "expense" or rule_id in followed:
            continue
        nxt = _next_bill(rule_id, rule, today)
        if nxt is not None:
            found.append(YearlyBill(rule_id, str(rule.get("name") or "Bill"), nxt[0], nxt[1]))
    return sorted(found, key=lambda b: (b.on, b.name.casefold()))


# ------------------------------------------------------------ the payday prompt


PAYDAY_LOOKBACK_DAYS = 7
PAYDAY_DEFAULT_MIN = 5000  # pesos - the user's choice, 2026-09-28; 0 turns the prompt off


@dataclass(frozen=True)
class PaydaySuggestion:
    goal_id: int
    name: str
    kind: str
    amount: Decimal


@dataclass(frozen=True)
class Payday:
    """GOA-12. "Your ₱25,000 arrived - set some aside?" - and how much for which goal."""

    transaction_id: int
    amount: Decimal
    on: date
    name: str
    suggestions: List[PaydaySuggestion]
    total: Decimal


def payday(db: Session, cipher: UserCipher, *, today: Optional[date] = None) -> Optional[Payday]:
    """
    GOA-12. The latest income of the last week worth a prompt - at least the
    amount set in Settings (`payday_prompt_min`, default ₱5,000; decided by
    the user 2026-09-28), not a cashback credit, not answered yet - with a
    split worked out from each goal's part of THIS month still to set aside:
    the emergency fund first, then sinking funds, then the rest by date.

    Never more than came in, and never more than a goal's account has
    available (GOA-08). None when there is nothing to ask about. Reads only;
    it SUGGESTS, and set_aside_payday is the one write.
    """
    from app.db.repositories.transaction_repository import TransactionRepository
    from app.services import preferences_service

    today = today or date.today()
    threshold = money(preferences_service.get_preferences(db, cipher).get("payday_prompt_min", PAYDAY_DEFAULT_MIN) or 0)
    if threshold <= ZERO:
        return None
    since = today - timedelta(days=PAYDAY_LOOKBACK_DAYS)
    candidates = [
        r for r in TransactionRepository(db, cipher).cached()
        if r.data.get("type") == "income" and not r.data.get("cashback_of") and not r.data.get("set_aside_prompted")
        and since <= date.fromisoformat(str(r.data["txn_date"])) <= today and money(r.data["amount"]) >= threshold
    ]
    if not candidates:
        return None
    income = max(candidates, key=lambda r: (str(r.data["txn_date"]), r.id))
    amount = money(income.data["amount"])

    order = {"emergency": 0, "sinking": 1, "saving": 2}
    goals = sorted((g for g in list_goals(db, cipher, today=today) if not g.reached and g.month_need),
                   key=lambda g: (order.get(g.kind, 3), g.target_date or date.max, g.name.casefold()))
    left = amount
    available: Dict[int, Decimal] = {}
    suggestions: List[PaydaySuggestion] = []
    for goal in goals:
        room = available.setdefault(goal.account_id, max(goal.account_available, ZERO))
        part = min(max((goal.month_need or ZERO) - goal.month_added, ZERO), left, room)
        if part <= ZERO:
            continue
        suggestions.append(PaydaySuggestion(goal.id, goal.name, goal.kind, part))
        left -= part
        available[goal.account_id] = room - part
    if not suggestions:
        return None
    name = income.data.get("merchant") or "Income"
    return Payday(income.id, amount, date.fromisoformat(str(income.data["txn_date"])), str(name), suggestions,
                  amount - left)


def set_aside_payday(db: Session, cipher: UserCipher, transaction_id: int, amounts: Mapping[int, Any], *,
                     today: Optional[date] = None) -> None:
    """
    GOA-12. "Set aside" on the payday card: each amount goes to its goal
    through the same checks as Add money (GOA-08), and the income is marked as
    answered - all in ONE commit, so a refused part leaves nothing half done.
    """
    from app.services import transaction_service as txns

    today = today or date.today()
    for goal_id, amount in amounts.items():
        if money(amount) > ZERO:
            _record_entry(db, cipher, int(goal_id), {"amount": amount, "on": today}, "add", today=today, commit=False)
    txns.mark_set_aside_prompted(db, cipher, transaction_id)
    db.commit()


def dismiss_payday(db: Session, cipher: UserCipher, transaction_id: int) -> None:
    """GOA-12. "Not now" - this income is never asked about again."""
    from app.services import transaction_service as txns

    txns.mark_set_aside_prompted(db, cipher, transaction_id)
    db.commit()


def set_aside_by_account(db: Session, cipher: UserCipher) -> Dict[int, Decimal]:
    """
    GOA-08. What every account has set aside for goals - the one figure
    account_service subtracts from a balance to say what is available. Imported
    lazily there: this module imports account_service.
    """
    return _held_by_account(GoalRepository(db, cipher).list())


def create_goal(db: Session, cipher: UserCipher, payload: Mapping[str, Any], *, today: Optional[date] = None) -> GoalView:
    repo = GoalRepository(db, cipher)
    if repo.count() >= MAX_GOALS:
        raise BusinessRuleException(f"At most {MAX_GOALS} goals")
    data = _clean(db, cipher, payload, None)
    data["created_on"] = (today or date.today()).isoformat()
    data["set_aside"] = []
    record = repo.create(data)
    audit_service.record(db, audit_service.CREATE, user_id=cipher.user_id, entity="savings_goals",
                         entity_id=record.id, cipher=cipher, detail={"name": data["name"]})
    db.commit()
    return get_goal(db, cipher, record.id, today=today)


def update_goal(db: Session, cipher: UserCipher, goal_id: int, payload: Mapping[str, Any], *,
                today: Optional[date] = None) -> GoalView:
    repo = GoalRepository(db, cipher)
    record = repo.get(goal_id)
    if record is None:
        raise NotFoundException("Goal not found")
    data = _clean(db, cipher, payload, record.data, goal_id)
    if data["account_id"] != record.data.get("account_id") and _saved(record.data) > ZERO:
        # What is set aside is part of THAT account's balance; it cannot follow the goal elsewhere.
        raise BusinessRuleException("Use or release what is set aside before moving the goal to another account")
    repo.update(goal_id, data)
    audit_service.record(db, audit_service.UPDATE, user_id=cipher.user_id, entity="savings_goals",
                         entity_id=goal_id, cipher=cipher, detail={"name": payload.get("name")})
    db.commit()
    return get_goal(db, cipher, goal_id, today=today)


def delete_goal(db: Session, cipher: UserCipher, goal_id: int) -> None:
    """Deleting a goal releases what it had set aside; the balance was never touched."""
    repo = GoalRepository(db, cipher)
    if repo.get(goal_id) is None:
        raise NotFoundException("Goal not found")
    repo.soft_delete(goal_id)
    audit_service.record(db, audit_service.DELETE, user_id=cipher.user_id, entity="savings_goals",
                         entity_id=goal_id, cipher=cipher, detail={})
    db.commit()


def add_money(
    db: Session, cipher: UserCipher, goal_id: int, payload: Mapping[str, Any], *, today: Optional[date] = None
) -> GoalView:
    """
    GOA-08. Set part of the account's balance aside for the goal. Nothing moves:
    no transaction, the balance is unchanged, and only what is AVAILABLE in the
    account - and so cash on hand - goes down. At most what is still available.
    """
    return _record_entry(db, cipher, goal_id, payload, "add", today=today)


def use_money(
    db: Session, cipher: UserCipher, goal_id: int, payload: Mapping[str, Any], *, today: Optional[date] = None
) -> GoalView:
    """
    GOA-08. Release money the goal had set aside - you bought the laptop, or
    need it back. Nothing moves here either: the purchase itself is an ordinary
    expense. At most what the goal holds.
    """
    return _record_entry(db, cipher, goal_id, payload, "use", today=today)


# ---------------------------------------------------------------- internals


def _record_entry(
    db: Session, cipher: UserCipher, goal_id: int, payload: Mapping[str, Any], kind: str, *, today: Optional[date],
    commit: bool = True,
) -> GoalView:
    repo = GoalRepository(db, cipher)
    record = repo.get(goal_id)
    if record is None:
        raise NotFoundException("Goal not found")
    try:
        amount = money(payload.get("amount"))
    except (ValueError, TypeError):
        raise ValidationException("Type an amount") from None
    if amount <= ZERO:
        raise ValidationException("An amount is more than zero")
    entries = list(record.data.get("set_aside") or [])
    if len(entries) >= MAX_ENTRIES:
        raise BusinessRuleException("This goal's history is full")

    view = get_goal(db, cipher, goal_id, today=today)
    if kind == "add":
        if amount > view.account_available:
            raise BusinessRuleException(
                f"Only {max(view.account_available, ZERO)} of the account is not already set aside"
            )
    elif amount > view.saved:
        raise BusinessRuleException(f"This goal has {view.saved} set aside")

    when = payload.get("on") or today or date.today()
    note = " ".join(str(payload.get("note") or "").split())[:NOTE_MAX] or None
    entries.append({"on": when.isoformat() if isinstance(when, date) else str(when), "kind": kind,
                    "amount": str(amount), "note": note})
    repo.update(goal_id, {**record.data, "set_aside": entries})
    audit_service.record(
        db, audit_service.GOAL_SET_ASIDE if kind == "add" else audit_service.GOAL_USE,
        user_id=cipher.user_id, entity="savings_goals", entity_id=goal_id, cipher=cipher,
        detail={"amount": str(amount)},
    )
    if commit:
        db.commit()
    return get_goal(db, cipher, goal_id, today=today)


def _saved(data: Mapping[str, Any]) -> Decimal:
    """Added less used, from the goal's own entries - never below zero."""
    held = ZERO
    for entry in data.get("set_aside") or []:
        try:
            amount = money(entry.get("amount"))
        except (ValueError, TypeError):
            continue
        held += amount if entry.get("kind") == "add" else -amount
    return max(held, ZERO)


def _held_by_account(records) -> Dict[int, Decimal]:
    held: Dict[int, Decimal] = {}
    for record in records:
        account_id = int(record.data["account_id"])
        held[account_id] = held.get(account_id, ZERO) + _saved(record.data)
    return held


def _balances(db: Session, cipher: UserCipher, today: Optional[date]) -> Mapping[int, Decimal]:
    views = account_service.list_accounts(db, cipher, today=today)
    return {v.id: v.balance for v in views}


def _view(goal_id: int, data: Mapping[str, Any], balances: Mapping[int, Decimal],
          held: Mapping[int, Decimal], today: date,
          rules: Optional[Mapping[int, Mapping[str, Any]]] = None) -> GoalView:
    target = money(data["target"])
    saved = _saved(data)
    account_id = int(data["account_id"])
    balance = balances.get(account_id, ZERO)
    on_account = held.get(account_id, ZERO)
    target_date = date.fromisoformat(data["target_date"]) if data.get("target_date") else None
    kind = str(data.get("kind") or "saving")
    rule_id = data.get("rule_id")
    followed = _next_bill(int(rule_id), (rules or {}).get(int(rule_id)), today) if rule_id else None
    if followed is not None:
        target, target_date = followed  # GOA-09 - the bill's next occurrence is the goal
    elif data.get("repeats_yearly") and target_date is not None:
        target_date = _next_yearly(target_date, today)
    remaining = max(target - saved, ZERO)
    per_month, months_left = monthly_need(remaining, today, target_date)
    month_need, month_added = _this_month(data, target, saved, target_date, today)
    return GoalView(
        id=goal_id,
        name=str(data.get("name", "")),
        target=target,
        target_date=target_date,
        account_id=account_id,
        colour=str(data.get("colour") or "#3FA37A"),
        icon=str(data.get("icon") or "piggy-bank"),
        saved=saved,
        remaining=remaining,
        ratio=min(saved / target, Decimal(1)).quantize(RATIO, rounding=ROUND_HALF_UP) if target > ZERO else Decimal(0),
        reached=saved >= target,
        account_balance=balance,
        account_available=balance - on_account,
        short_by=max(on_account - max(balance, ZERO), ZERO),
        per_month=per_month,
        months_left=months_left,
        overdue=target_date is not None and target_date < today and remaining > ZERO,
        kind=kind if kind in KINDS else "saving",
        repeats_yearly=bool(data.get("repeats_yearly")),
        rule_id=int(rule_id) if rule_id and followed is not None else None,
        month_need=month_need,
        month_added=month_added,
        month_done=month_need is not None and month_added >= month_need,
    )


def _this_month(data: Mapping[str, Any], target: Decimal, saved: Decimal, target_date: Optional[date],
                today: date) -> Tuple[Optional[Decimal], Decimal]:
    """
    GOA-09. (what this month asks for, what is set aside in it). The ask is
    worked out from where the goal stood when the month BEGAN - so setting this
    month's part aside ticks it off instead of shrinking it - and None when
    the goal has no date, a past one, or was already reached then.
    """
    added = used = ZERO
    for entry in data.get("set_aside") or []:
        on = str(entry.get("on") or "")
        if on[:7] != today.isoformat()[:7]:
            continue
        if entry.get("kind") == "add":
            added += money(entry.get("amount") or ZERO)
        else:
            used += money(entry.get("amount") or ZERO)
    before = saved - added + used
    need, _ = monthly_need(max(target - before, ZERO), today, target_date)
    return need, added


def _next_yearly(on: date, today: date) -> date:
    """GOA-09. A repeating fund's date, rolled on a year at a time until it is today or later."""
    from app.core.utils.date_utils import add_months

    years = 0
    while add_months(on, 12 * years) < today:
        years += 1
    return add_months(on, 12 * years)


def _next_bill(rule_id: int, rule: Optional[Mapping[str, Any]], today: date) -> Optional[Tuple[Decimal, date]]:
    """
    GOA-09. The next occurrence of the bill a sinking fund follows - its amount
    and its day, from THE schedule (occurrences, REC-22). None when the rule is
    gone or has nothing left. Imported here: recurring_service reaches
    account_service, which imports this module lazily.
    """
    if rule is None:
        return None
    from app.services import recurring_service

    ahead = [o for o in recurring_service.occurrences(rule_id, rule, today, today + timedelta(days=YEARLY_HORIZON_DAYS))
             if not o.paused]
    return (ahead[0].amount, ahead[0].on) if ahead else None


def _rules(db: Session, cipher: UserCipher) -> Dict[int, Mapping[str, Any]]:
    from app.db.repositories.recurring_repository import RecurringRuleRepository

    return {r.id: r.data for r in RecurringRuleRepository(db, cipher).list()}


def _clean(db: Session, cipher: UserCipher, payload: Mapping[str, Any], existing: Optional[Mapping[str, Any]],
           goal_id: Optional[int] = None) -> dict:
    data = dict(existing or {})
    name = " ".join(str(payload.get("name") or data.get("name") or "").split())
    if not name:
        raise ValidationException("A goal needs a name")
    data["name"] = name[:NAME_MAX]

    raw_target = payload.get("target", data.get("target"))
    try:
        target = money(raw_target)
    except (ValueError, TypeError):
        raise ValidationException("A goal needs a target amount") from None
    if target <= ZERO or target > transaction_service.MAX_AMOUNT:
        raise ValidationException("A target is more than zero")
    data["target"] = str(target)

    target_date = payload.get("target_date", data.get("target_date"))
    data["target_date"] = (target_date.isoformat() if isinstance(target_date, date) else str(target_date)) if target_date else None

    account_id = payload.get("account_id", data.get("account_id"))
    account = AccountRepository(db, cipher).get(account_id) if isinstance(account_id, int) else None
    if account is None:
        raise ValidationException("A goal needs an account to save in")
    if account.data.get("type") not in GOAL_ACCOUNT_TYPES:
        raise BusinessRuleException("Save toward a goal in a cash, debit or savings account")
    if account.data.get("archived") and account_id != (existing or {}).get("account_id"):
        raise BusinessRuleException("That account is archived")
    # GOA-08: several goals may share an account - each holds only its own part of the balance.
    data["account_id"] = account_id
    data["colour"] = str(payload.get("colour") or data.get("colour") or "#3FA37A")
    data["icon"] = str(payload.get("icon") or data.get("icon") or "piggy-bank")
    data.setdefault("set_aside", [])

    # Phase 13. The kind; a sinking fund may repeat yearly, or follow a yearly bill.
    kind = str(payload.get("kind") or data.get("kind") or "saving")
    if kind not in KINDS:
        raise ValidationException(f"A goal is one of: {', '.join(KINDS)}")
    if kind == "emergency":
        others = [r for r in GoalRepository(db, cipher).list()
                  if r.data.get("kind") == "emergency" and r.id != goal_id]
        if others:
            raise BusinessRuleException("You already have an emergency fund goal - there is one, and the cover reads it")
    data["kind"] = kind
    data["repeats_yearly"] = kind == "sinking" and bool(payload.get("repeats_yearly", data.get("repeats_yearly", False)))
    rule_id = payload.get("rule_id", data.get("rule_id"))
    if kind != "sinking" or not rule_id:
        data["rule_id"] = None
    else:
        from app.db.repositories.recurring_repository import RecurringRuleRepository

        rule = RecurringRuleRepository(db, cipher).get(int(rule_id))
        if rule is None or rule.data.get("type") != "expense":
            raise ValidationException("A sinking fund follows a repeating bill - that one does not exist")
        data["rule_id"] = int(rule_id)
    return data
