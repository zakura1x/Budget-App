"""
transaction_service - the write path, and every read over the working set
(TXN-01..TXN-21).

THE SHAPE (TXN-16), locked in from day one. Every stored transaction carries a
non-empty `splits` array, and a simple one has exactly one element. Not
"category_id OR splits": one shape means stats, budgets and category deletion
each have exactly one code path. `category_id` is accepted on the way IN as
shorthand for a single split, and never stored at the top level.

THE INVARIANT (TXN-20). `amount == sum(splits[].amount)`, Decimal-exact,
enforced here and nowhere else can enforce it. A one-centavo drift would pass
every database constraint there is and quietly corrupt every report built on
top of it. `validate_splits` is pure so it is tested directly, not only
through the API.

TRANSFERS (TXN-04) are a linked pair: an `out` leg on the source account and an
`in` leg on the destination, each naming the other in `pair_id`. A transfer
moves money between your own accounts; it is never spending and never income,
so its single split has no category and every total skips it. Both legs are
written, edited and deleted together, in one database transaction.

BALANCE ADJUSTMENTS (ACC-29) are the fourth type, and the only one nobody types
in: `record_adjustment` writes one when a user sets an account's balance and
accepts recording the difference (account_service.update_account). One
account, one uncategorised split, `direction` out for an unrecorded loss and
in for a gain. A balance counts it; the budget, the day totals and a card's
spending limit read only the types they mean, so none of them ever does - the
budget stays the same (confirmed 2026-09-14). It can be deleted and never
edited - its audit entry recorded before and after.

TAGS (TXN-10) are ids inside the payload, checked against the user's tags on
every write - no foreign key can do it. An expense or income carries up to
MAX_TAGS; a transfer and an adjustment carry none. A write that does not
mention `tag_ids` keeps the ones already there. Deleting a tag removes its id
from every transaction (tag_service.delete_tag).

A PURCHASE THE BANK POSTED LATE (ACC-26) carries `card_posted_on`. It moves
the purchase to a later card statement and changes nothing else: the budget
reads `txn_date` and only `txn_date`.

CASHBACK (TXN-22) is a linked pair too, and for the same reason transfers are:
the money really does arrive, often days later, and a balance that did not
move would be a lie. The purchase keeps its full amount and carries
`cashback` - what was earned, where it lands and when - plus `cashback_id`,
the income row that credits it; that row carries `cashback_of` back. The pair
is written, edited and deleted together. Spending stats therefore stay GROSS
(confirmed by the user 2026-09-16): a PHP 1,000 purchase with PHP 20 back is
PHP 1,000 of spending and PHP 20 of income, never PHP 980 of spending.

Reads never touch SQL beyond the first cold load - they filter, sort, search
and page in Python over TransactionRepository.cached() (TXN-12/13).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import (
    BusinessRuleException,
    NotFoundException,
    ValidationException,
)
from app.core.utils.money import ZERO, money, total
from app.db.repositories.account_repository import AccountRepository
from app.db.repositories.category_repository import CategoryRepository
from app.db.repositories.encrypted_repository import Record
from app.db.repositories.transaction_repository import TransactionRepository
from app.db.types import utcnow
from app.services import account_service, audit_service, tag_service
from app.services.account_service import Posting

TYPES: Tuple[str, ...] = ("expense", "income", "transfer")  # what can be entered
LISTED_TYPES: Tuple[str, ...] = TYPES + ("adjustment",)  # what the ledger can show and filter on

MAX_AMOUNT = Decimal("999999999.99")  # nine integer digits - what the numpad allows
MAX_SPLITS = 20
MERCHANT_MAX = 80
NOTES_MAX = 500
SPLIT_NOTE_MAX = 120
MAX_TAGS = 10
EARLIEST = date(2000, 1, 1)
PAGE_MAX = 200
MERCHANTS_MAX = 200  # TXN-24 - more suggestions than anyone scrolls
RECENTLY_DELETED_DAYS = 30  # TXN-25 - how far back Recently deleted lists


# ------------------------------------------------------------------- shapes


@dataclass(frozen=True)
class Split:
    category_id: Optional[int]
    amount: Decimal
    note: Optional[str] = None


@dataclass(frozen=True)
class Cashback:
    """
    TXN-22. What a purchase earns back: the amount, the account it lands in and
    the day it does. `rate` is kept only to say where the amount came from -
    "2% of what you spent" reads better than a bare figure - and nothing
    recomputes from it, so a rate that changes later cannot rewrite history.
    """

    amount: Decimal
    account_id: int
    category_id: int
    on: date
    rate: Optional[Decimal] = None


@dataclass(frozen=True)
class TransactionView:
    id: int
    type: str
    txn_date: date
    amount: Decimal
    account_id: int
    splits: Tuple[Split, ...]
    merchant: Optional[str] = None
    notes: Optional[str] = None
    direction: Optional[str] = None  # transfers only: "out" | "in"
    counter_account_id: Optional[int] = None  # transfers only
    pair_id: Optional[int] = None  # transfers only
    tag_ids: Tuple[int, ...] = ()
    recurring_id: Optional[int] = None
    recurring_on: Optional[date] = None  # the occurrence it posted as; None for a payment against a plan
    interest_on: Optional[date] = None  # ACC-37 - the day of savings interest this credited
    cashback: Optional["Cashback"] = None  # TXN-22 - what this purchase earns back
    cashback_id: Optional[int] = None  # the income row that credits it
    cashback_of: Optional[int] = None  # on that row: the purchase it came from
    attachment_id: Optional[int] = None  # TXN-15 - the receipt
    created_at: Optional[datetime] = None
    card_posted_on: Optional[date] = None  # ACC-26 - the statement it landed on, when later


@dataclass(frozen=True)
class DayTotal:
    """What a day cost and earned. Transfers are in neither, by definition."""

    on: date
    spent: Decimal
    earned: Decimal


@dataclass(frozen=True)
class Page:
    items: List[TransactionView]
    next_cursor: Optional[str]
    total_count: int
    days: List[DayTotal] = field(default_factory=list)


@dataclass(frozen=True)
class Outcome:
    """
    What a write changed, in the SAME response (the Phase 4 contract note):
    the rows, the accounts they touched with their new balances, and cash on
    hand. Phase 5 adds the recomputed budget status alongside, so the home
    ring never needs a second round trip.
    """

    transactions: List[TransactionView]
    accounts: List[account_service.AccountView]
    cash_on_hand: account_service.CashOnHand
    budget_status: Optional[Any] = None  # budget_service.BudgetStatus, or None with no budget


@dataclass(frozen=True)
class Merchant:
    """
    TXN-24. A merchant typed before, and what it was filed under LAST time -
    so picking it again can pre-select the category. `category_id` is None
    when the latest entry was split (which line would it be?) or its category
    is gone or archived.
    """

    name: str
    type: str  # expense | income - the same shop is rarely both, and never the same category
    count: int
    category_id: Optional[int]
    last_used: date


@dataclass(frozen=True)
class Deleted:
    """
    TXN-25. One entry in Recently deleted: the row as it was, when it went, and
    whether it can come back. `reason` says why not, in words, so the screen
    can show the Restore button disabled with the reason under it rather than
    let a tap fail.
    """

    transaction: TransactionView
    deleted_at: datetime
    restorable: bool
    reason: Optional[str] = None


# -------------------------------------------------------- the pure invariant


def validate_splits(amount: Decimal, splits: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """
    TXN-16/20. Clean a splits array and prove it adds up - exactly.

    Returns the splits in their stored form: amounts as 2-place Decimal
    strings, notes trimmed. Raises rather than rounds: if the parts do not
    sum to the whole, one of them is wrong, and guessing which is how a
    centavo goes missing.
    """
    if not isinstance(splits, (list, tuple)) or not splits:
        raise ValidationException("A transaction needs at least one split")
    if len(splits) > MAX_SPLITS:
        raise ValidationException(f"At most {MAX_SPLITS} splits")

    cleaned: List[Dict[str, Any]] = []
    for position, split in enumerate(splits, start=1):
        if not isinstance(split, Mapping):
            raise ValidationException(f"Split {position} is not an object")
        part = _amount(split.get("amount"), f"split {position}")
        category_id = split.get("category_id")
        if category_id is not None and (not isinstance(category_id, int) or isinstance(category_id, bool)):
            raise ValidationException(f"Split {position} needs a category id")
        note = split.get("note")
        cleaned.append({
            "category_id": category_id,
            "amount": str(part),
            "note": str(note).strip()[:SPLIT_NOTE_MAX] or None if note else None,
        })

    parts = total(Decimal(s["amount"]) for s in cleaned)
    if parts != amount:
        difference = amount - parts
        raise BusinessRuleException(
            f"The splits add up to {parts}, not {amount} - {abs(difference)} "
            f"{'left to allocate' if difference > 0 else 'over'}",
            extra={"allocated": str(parts), "amount": str(amount), "remaining": str(difference)},
        )
    return cleaned


# ------------------------------------------------------------------ reading


def warm(db: Session, cipher: UserCipher) -> int:
    """Load the working set now - at sign-in, while the user is still looking at the unlock screen."""
    return len(TransactionRepository(db, cipher).cached())


def views(db: Session, cipher: UserCipher) -> List[TransactionView]:
    """Every live transaction, both legs of every transfer, unsorted - what stats and the calendar loop over."""
    return [_view(record) for record in TransactionRepository(db, cipher).cached()]


def postings(db: Session, cipher: UserCipher) -> List[Posting]:
    """
    Every transaction as a signed movement against its account - what
    account_service adds to an opening balance. Expense, a transfer's out
    leg and an unrecorded loss take money away; income, the in leg and an
    unrecorded gain bring it. The type travels with it, so a card can tell a
    purchase from a payment (ACC-21).
    """
    result: List[Posting] = []
    for record in TransactionRepository(db, cipher).cached():
        view = _view(record)
        sign = -1 if view.type == "expense" or view.direction == "out" else 1
        result.append(Posting(view.account_id, view.txn_date, view.amount * sign, view.type, view.card_posted_on,
                              view.created_at, view.id))
    return result


def card_purchases(db: Session, cipher: UserCipher, account_id: int, start: date, end: date) -> List[TransactionView]:
    """ACC-26. The expenses on a card whose STATEMENT day falls in [start, end], newest first."""
    found = [
        view for view in map(_view, TransactionRepository(db, cipher).cached())
        if view.type == "expense" and view.account_id == account_id
        and start <= (view.card_posted_on or view.txn_date) <= end
    ]
    return sorted(found, key=lambda v: (v.txn_date, v.id), reverse=True)


def get_transaction(db: Session, cipher: UserCipher, transaction_id: int) -> TransactionView:
    record = _record(db, cipher, transaction_id)
    return _view(record)


def list_transactions(
    db: Session,
    cipher: UserCipher,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    category_id: Optional[int] = None,
    account_id: Optional[int] = None,
    type: Optional[str] = None,
    tag_id: Optional[int] = None,
    q: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = 50,
) -> Page:
    """
    TXN-11/12/13. Newest first, filtered and searched in Python.

    A transfer appears ONCE in the ledger - as its out leg - unless the list is
    filtered to one account, in which case it is the leg on that account.
    Otherwise every transfer would show up twice.

    Day totals are computed over the whole filtered set, not the page, so a
    day that straddles two pages still shows its true subtotal.
    """
    limit = max(1, min(limit, PAGE_MAX))
    if type is not None and type not in LISTED_TYPES:
        raise ValidationException(f"type must be one of: {', '.join(LISTED_TYPES)}")

    categories = _category_scope(db, cipher, category_id) if category_id is not None else None
    needle = q.strip().casefold() if q and q.strip() else None

    matched: List[TransactionView] = []
    for record in TransactionRepository(db, cipher).cached():
        view = _view(record)
        if view.type == "transfer":
            if account_id is None and view.direction != "out":
                continue
        if account_id is not None and view.account_id != account_id:
            continue
        if type is not None and view.type != type:
            continue
        if tag_id is not None and tag_id not in view.tag_ids:
            continue
        if date_from is not None and view.txn_date < date_from:
            continue
        if date_to is not None and view.txn_date > date_to:
            continue
        if categories is not None and not any(s.category_id in categories for s in view.splits):
            continue
        if needle is not None and not _matches(view, needle):
            continue
        matched.append(view)

    matched.sort(key=lambda v: (v.txn_date, v.id), reverse=True)
    start = _after_cursor(matched, cursor)
    items = matched[start:start + limit]
    more = start + limit < len(matched)
    next_cursor = _cursor(items[-1]) if more and items else None

    shown_days = {v.txn_date for v in items}
    return Page(
        items=items,
        next_cursor=next_cursor,
        total_count=len(matched),
        days=_day_totals(v for v in matched if v.txn_date in shown_days),
    )


def merchants(db: Session, cipher: UserCipher) -> List[Merchant]:
    """
    TXN-24. Every merchant already typed, most used first, each with the
    category its LATEST entry was filed under - what the add sheet suggests as
    you type, and pre-selects when you pick one.

    Merchant is encrypted (TXN-08), so this is a loop over the working set and
    could never be SQL. Names are matched as a person would read them: case,
    and runs of spaces, do not make "Jollibee" and "jollibee " two shops. The
    spelling shown is the latest one used.

    Left out: transfers and balance adjustments (no merchant of their own), and
    a cashback credit - it borrows its purchase's merchant, and suggesting
    "SM Supermarket" as an income would file the next purchase there.
    """
    categories = _categories(db, cipher)
    found: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for view in sorted(views(db, cipher), key=lambda v: (v.txn_date, v.id)):
        if view.type not in ("expense", "income") or view.cashback_of or not view.merchant:
            continue
        key = (view.type, _merchant_key(view.merchant))
        if not key[1]:
            continue
        entry = found.setdefault(key, {"count": 0})
        entry["count"] += 1
        entry["name"] = " ".join(view.merchant.split())
        entry["last_used"] = view.txn_date
        # The latest entry decides - a shop you moved from Food to Household
        # last week is Household now, however often it was Food before.
        only = view.splits[0].category_id if len(view.splits) == 1 else None
        category = categories.get(only) if only is not None else None
        usable = category is not None and not category.get("archived") and category.get("kind") == view.type
        entry["category_id"] = only if usable else None

    ranked = sorted(found.items(), key=lambda item: (-item[1]["count"], -item[1]["last_used"].toordinal(), item[0]))
    return [
        Merchant(name=e["name"], type=kind, count=e["count"], category_id=e["category_id"], last_used=e["last_used"])
        for (kind, _), e in ranked[:MERCHANTS_MAX]
    ]


def _merchant_key(name: str) -> str:
    return " ".join(name.split()).casefold()


# ------------------------------------------------------------------ writing


def create_transaction(
    db: Session, cipher: UserCipher, payload: Mapping[str, Any], *, today: Optional[date] = None
) -> Outcome:
    kind = _type(payload.get("type"))
    repo = TransactionRepository(db, cipher)

    if kind == "transfer":
        out_data, in_data = _clean_transfer(db, cipher, payload, existing=None)
        out_leg = repo.create(out_data)
        in_leg = repo.create({**in_data, "pair_id": out_leg.id})
        out_leg = repo.update(out_leg.id, {**out_data, "pair_id": in_leg.id})
        records = [out_leg, in_leg]
    else:
        data = _clean(db, cipher, payload, kind, existing=None)
        record = repo.create(data)
        records = [record]
        # TXN-22. The credit rides along in the same commit as the purchase.
        block = _cashback_for(db, cipher, payload, data, kind, existing=None)
        if block is not None:
            record, credit = _reconcile_cashback(db, cipher, record, block)
            records = [record] + ([credit] if credit is not None else [])

    audit_service.record(
        db, audit_service.CREATE, user_id=cipher.user_id, entity="transactions",
        entity_id=records[0].id, cipher=cipher,
        detail={"type": kind, "amount": records[0].data["amount"], "legs": len(records)},
    )
    db.commit()
    return outcome(db, cipher, [_view(r) for r in records], today=today)


def update_transaction(
    db: Session,
    cipher: UserCipher,
    transaction_id: int,
    payload: Mapping[str, Any],
    *,
    today: Optional[date] = None,
) -> Outcome:
    repo = TransactionRepository(db, cipher)
    record = _record(db, cipher, transaction_id)
    current = record.data.get("type")
    if current == "adjustment":
        # Its audit entry recorded the balance before and after (ACC-30); an
        # edited amount would contradict it. Delete it and set the balance again.
        raise BusinessRuleException("A balance adjustment cannot be edited - delete it and set the balance again")
    kind = _type(payload.get("type") or current)

    if (current == "transfer") != (kind == "transfer"):
        # A transfer is two rows; anything else is one. Converting between
        # them silently creates or strands a leg - delete and re-add instead.
        raise BusinessRuleException("A transfer cannot become an expense or income, or the other way round")

    if kind == "transfer":
        out_record, in_record = _legs(db, cipher, record)
        out_data, in_data = _clean_transfer(db, cipher, payload, existing=out_record.data)
        # TXN-15. The legs share one receipt; an edit keeps it (older transfers
        # may carry it on the in leg only).
        receipt = out_record.data.get("attachment_id") or in_record.data.get("attachment_id")
        out_data["attachment_id"] = in_data["attachment_id"] = receipt
        records = [
            repo.update(out_record.id, {**out_data, "pair_id": in_record.id}),
            repo.update(in_record.id, {**in_data, "pair_id": out_record.id}),
        ]
    else:
        data = _clean(db, cipher, payload, kind, existing=record.data)
        updated = repo.update(transaction_id, data)
        records = [updated]
        if updated.data.get("cashback_of"):
            # This IS the credit. Editing it keeps the purchase's block honest,
            # rather than leaving it claiming money that moved (TXN-22).
            records.append(_follow_cashback(db, cipher, updated))
        elif kind == "expense" or updated.data.get("cashback_id"):
            block = _cashback_for(db, cipher, payload, data, kind, existing=record.data)
            updated, credit = _reconcile_cashback(db, cipher, updated, block)
            records = [updated] + ([credit] if credit is not None else [])

    audit_service.record(
        db, audit_service.UPDATE, user_id=cipher.user_id, entity="transactions",
        entity_id=transaction_id, cipher=cipher, detail={"type": kind, "amount": records[0].data["amount"]},
    )
    db.commit()
    return outcome(db, cipher, [_view(r) for r in records], today=today)


def delete_transaction(db: Session, cipher: UserCipher, transaction_id: int, *, today: Optional[date] = None) -> Outcome:
    """TXN-14. Soft, so the audit trail and any earlier backup stay honest. A transfer takes both legs."""
    repo = TransactionRepository(db, cipher)
    record = _record(db, cipher, transaction_id)
    doomed = list(_legs(db, cipher, record)) if record.data.get("type") == "transfer" else [record]
    # TXN-22. A purchase takes its cashback with it; deleting the credit on its
    # own leaves the purchase, with nothing left claiming money that is gone.
    credit_id = record.data.get("cashback_id")
    if credit_id:
        doomed.append(_record(db, cipher, credit_id))
    if record.data.get("cashback_of"):
        purchase = _record(db, cipher, record.data["cashback_of"])
        repo.update(purchase.id, {**purchase.data, "cashback": None, "cashback_id": None})

    # TXN-25. `deleted_at` is what puts a row in Recently deleted. Only THIS
    # delete writes it: a purchase hidden by an installment conversion
    # (REC-34), a plan's charges removed by converting back, and a cashback
    # credit taken away by an edit are soft-deleted too - none of them is
    # something you deleted, and none can safely be brought back on its own.
    stamp = utcnow().isoformat(timespec="seconds")
    for leg in doomed:
        repo.update(leg.id, {**leg.data, "deleted_at": stamp})
        repo.soft_delete(leg.id)
    audit_service.record(
        db, audit_service.DELETE, user_id=cipher.user_id, entity="transactions",
        entity_id=transaction_id, cipher=cipher,
        detail={"type": record.data.get("type"), "legs": len(doomed)},
    )
    db.commit()
    return outcome(db, cipher, [_view(leg) for leg in doomed], today=today)


def deleted(db: Session, cipher: UserCipher, *, now: Optional[datetime] = None) -> List[Deleted]:
    """
    TXN-25. What you deleted in the last RECENTLY_DELETED_DAYS, newest first.

    One line per thing deleted, the way the ledger shows it: a transfer as its
    out leg, and a purchase that took its cashback with it as the purchase
    alone - both halves come back together. Only rows carrying `deleted_at`
    are listed, so entries deleted before this existed are not (they cannot be
    told apart from a purchase hidden by an installment conversion).
    """
    now = now or utcnow()
    repo = TransactionRepository(db, cipher)
    cutoff = now - timedelta(days=RECENTLY_DELETED_DAYS)
    rows = {r.id: r for r in repo.deleted_since(cutoff) if r.data.get("deleted_at")}

    listed: List[Deleted] = []
    context = _RestoreContext.load(db, cipher)
    for record in rows.values():
        data = record.data
        if data.get("type") == "transfer" and data.get("direction") == "in" and data.get("pair_id") in rows:
            continue  # shown as its out leg
        if data.get("cashback_of") in rows:
            continue  # went with its purchase, and comes back with it
        when = _parse_stamp(data["deleted_at"])
        if when is None or when < cutoff:
            continue
        problem = _restore_problem(context, _restore_group(db, cipher, record))
        listed.append(Deleted(_view(record), when, problem is None, problem))
    return sorted(listed, key=lambda d: (d.deleted_at, d.transaction.id), reverse=True)


def restore_transaction(
    db: Session, cipher: UserCipher, transaction_id: int, *, today: Optional[date] = None
) -> Outcome:
    """
    TXN-25. Bring back something you deleted - and everything that went with
    it: a transfer's other leg, a purchase's cashback credit. A credit deleted
    ON ITS OWN is joined back to its purchase, which lost the link then.

    Refused, with the reason, when bringing it back would contradict what has
    happened since (`_restore_problem`). Tags deleted meanwhile are dropped
    rather than refused - the entry is still the entry without them.
    """
    repo = TransactionRepository(db, cipher)
    record = repo.get(transaction_id, include_deleted=True)
    if record is None or not record.is_deleted or not record.data.get("deleted_at"):
        raise NotFoundException("That entry is not in Recently deleted")
    group = _restore_group(db, cipher, record)
    problem = _restore_problem(_RestoreContext.load(db, cipher), group)
    if problem is not None:
        raise BusinessRuleException(problem)

    known_tags = tag_service.known_ids(db, cipher)
    restored: List[Record] = []
    for row in group:
        data = {k: v for k, v in row.data.items() if k != "deleted_at"}
        data["tag_ids"] = [t for t in data.get("tag_ids") or [] if t in known_tags]
        repo.update(row.id, data)
        repo.undelete(row.id)
        restored.append(Record(row.id, data, row.row_created, row.row_updated, False))

    # A credit deleted on its own took the cashback off its purchase; put it back.
    lone = [r for r in restored if r.data.get("cashback_of") and all(g.id != r.data["cashback_of"] for g in group)]
    for credit in lone:
        purchase = _record(db, cipher, credit.data["cashback_of"])
        block = {"amount": credit.data["amount"], "account_id": credit.data["account_id"],
                 "category_id": (credit.data.get("splits") or [{}])[0].get("category_id"),
                 "on": credit.data["txn_date"], "rate": None}
        restored.append(repo.update(purchase.id, {**purchase.data, "cashback": block, "cashback_id": credit.id}))

    audit_service.record(
        db, audit_service.RESTORE, user_id=cipher.user_id, entity="transactions",
        entity_id=transaction_id, cipher=cipher,
        detail={"type": record.data.get("type"), "legs": len(group)},
    )
    db.commit()
    return outcome(db, cipher, [_view(r) for r in restored], today=today)


def _restore_group(db: Session, cipher: UserCipher, record: Record) -> List[Record]:
    """The rows one Restore brings back: this one, a transfer's other leg, a purchase's credit."""
    repo = TransactionRepository(db, cipher)
    group = [record]
    linked = []
    if record.data.get("type") == "transfer":
        linked.append(record.data.get("pair_id"))
    linked.append(record.data.get("cashback_id"))
    for row_id in linked:
        if not row_id:
            continue
        other = repo.get(int(row_id), include_deleted=True)
        # Only a row that went in the SAME delete - a credit taken away earlier by an edit stays gone.
        if other is not None and other.is_deleted and other.data.get("deleted_at") == record.data.get("deleted_at"):
            group.append(other)
    return group


@dataclass(frozen=True)
class _RestoreContext:
    """What every restore check reads, loaded once however many entries are listed."""

    accounts: Mapping[int, Mapping[str, Any]]
    categories: Mapping[int, Mapping[str, Any]]
    rules: Set[int]
    live: Sequence[Record]

    @classmethod
    def load(cls, db: Session, cipher: UserCipher) -> "_RestoreContext":
        # Imported here: recurring_service imports this module, and the
        # repository is all a restore needs from that side.
        from app.db.repositories.recurring_repository import RecurringRuleRepository

        return cls(
            accounts={r.id: r.data for r in AccountRepository(db, cipher).list()},
            categories=_categories(db, cipher),
            rules={r.id for r in RecurringRuleRepository(db, cipher).list()},
            live=TransactionRepository(db, cipher).cached(),
        )


def _restore_problem(context: _RestoreContext, group: Sequence[Record]) -> Optional[str]:
    """
    Why this group cannot come back, or None. Each answer is something that
    changed after the delete and that a restore would contradict:

      * its account is gone or archived, or a category it was filed under was
        deleted - there would be nowhere for it to live
      * it was money paid ON a plan (REC-32) - the payment's extra part lives
        in the plan's own `prepayments`, which the delete did not touch, so a
        restored transfer would disagree with the plan; pay it again instead
      * the plan that posted it was deleted, or that occurrence has been
        posted again since (REC-33 pay now, or the catch-up)
      * that day's savings interest was credited again since (ACC-37)
      * a lone cashback credit whose purchase is gone or already earns another
    """
    accounts, categories, live = context.accounts, context.categories, context.live
    ids = {r.id for r in group}

    for row in group:
        data = row.data
        for field_name in ("account_id", "counter_account_id"):
            account_id = data.get(field_name)
            if account_id is None:
                continue
            account = accounts.get(int(account_id))
            if account is None:
                return "Its account was deleted"
            if account.get("archived"):
                return f"{account.get('name') or 'Its account'} is archived - unarchive it first"
        if data.get("type") in ("expense", "income"):
            for split in data.get("splits") or []:
                if split.get("category_id") not in categories:
                    return "A category it was filed under was deleted"
        rule_id = data.get("recurring_id")
        if rule_id:
            if not data.get("recurring_on"):
                return "A payment on a plan - pay it again from the plan instead"
            if int(rule_id) not in context.rules:
                return "The plan that posted it was deleted"
            if any(r.data.get("recurring_id") == rule_id and r.data.get("recurring_on") == data["recurring_on"]
                   for r in live):
                return "That charge has been recorded again since"
        if data.get("interest_on"):
            if any(r.data.get("interest_on") == data["interest_on"] and r.data.get("account_id") == data["account_id"]
                   for r in live):
                return "That day's interest has been credited again since"
        purchase_id = data.get("cashback_of")
        if purchase_id and purchase_id not in ids:
            purchase = next((r for r in live if r.id == purchase_id), None)
            if purchase is None:
                return "The purchase it came from is gone"
            if purchase.data.get("cashback_id"):
                return "Its purchase already has other cashback"
    return None


def _parse_stamp(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def record_adjustment(
    db: Session,
    cipher: UserCipher,
    account_id: int,
    difference: Decimal,
    *,
    on: date,
    note: Optional[str] = None,
) -> Record:
    """
    ACC-29. Write a balance adjustment for `difference` - negative for an
    unrecorded loss - dated `on`.

    Only account_service.update_account calls this, after the user was asked.
    It neither commits nor audits: the caller writes the BALANCE_ADJUST entry
    and commits both in the same database transaction (ACC-30).
    """
    amount = _positive(abs(difference), "difference")
    data = {
        "txn_date": on.isoformat(),
        "type": "adjustment",
        "amount": str(amount),
        "account_id": account_id,
        "direction": "out" if difference < ZERO else "in",
        "counter_account_id": None,
        "pair_id": None,
        "merchant": None,
        "notes": _text(note, NOTES_MAX),
        # One uncategorised split - the same shape rule a transfer keeps, and
        # the same guarantee that no category total can include it.
        "splits": validate_splits(amount, [{"category_id": None, "amount": str(amount)}]),
        "tag_ids": [],
        "recurring_id": None,
        "attachment_id": None,
    }
    return TransactionRepository(db, cipher).create(data)


def post_recurring(
    db: Session,
    cipher: UserCipher,
    payload: Mapping[str, Any],
    *,
    recurring_id: int,
    recurring_on: Optional[date],
) -> List[Record]:
    """
    REC-04/22. Write one occurrence of a recurring rule - or a payment against
    one, an installment's interest or its payoff (`recurring_on` None) -
    validated exactly like a typed entry.

    Only recurring_service calls this. It neither commits nor audits: a
    catch-up posts its whole batch and advances the rule's marker in ONE
    commit, so it happens entirely or not at all.
    """
    kind = _type(payload.get("type"))
    marks = {"recurring_id": recurring_id, "recurring_on": recurring_on.isoformat() if recurring_on else None}
    repo = TransactionRepository(db, cipher)
    if kind == "transfer":
        out_data, in_data = _clean_transfer(db, cipher, payload, existing=None)
        out_leg = repo.create({**out_data, **marks})
        in_leg = repo.create({**in_data, **marks, "pair_id": out_leg.id})
        out_leg = repo.update(out_leg.id, {**out_data, **marks, "pair_id": in_leg.id})
        return [out_leg, in_leg]
    return [repo.create({**_clean(db, cipher, payload, kind, existing=None), **marks})]


def post_interest(
    db: Session,
    cipher: UserCipher,
    payload: Mapping[str, Any],
    *,
    on: date,
) -> Record:
    """
    ACC-37. Write one day's savings interest as ordinary income, validated
    exactly like a typed entry, carrying the day it was earned for.

    Only interest_service calls this. Like post_recurring it neither commits
    nor audits: the whole catch-up and every account's marker move in ONE
    commit. `interest_on` is what makes a second catch-up a no-op, and it
    survives an edit, so a day can never be credited twice.
    """
    data = _clean(db, cipher, payload, _type(payload.get("type")), existing=None)
    return TransactionRepository(db, cipher).create({**data, "interest_on": on.isoformat()})


def reprice_recurring(
    db: Session,
    cipher: UserCipher,
    transaction_id: int,
    *,
    amount: Decimal,
    splits: Sequence[Mapping[str, Any]],
) -> TransactionView:
    """
    REC-29. Correct a posted installment payment to what the bank billed - its
    amount and splits only. Its date, account, plan and statement stay, and it
    is validated like any entry. Only recurring_service calls this; it neither
    commits nor audits, so the plan and its payments change in one commit.
    """
    record = _record(db, cipher, transaction_id)
    if record.data.get("type") != "expense" or record.data.get("recurring_id") is None:
        raise BusinessRuleException("Only a posted installment payment can be corrected this way")
    payload = {**record.data, "amount": str(amount), "splits": [dict(s) for s in splits]}
    payload.pop("category_id", None)
    cleaned = _clean(db, cipher, payload, "expense", existing=record.data)
    updated = TransactionRepository(db, cipher).update(transaction_id, {**record.data, **cleaned})
    return _view(updated)


def validate_entry(db: Session, cipher: UserCipher, payload: Mapping[str, Any]) -> Dict[str, Any]:
    """DAT-04. Clean a would-be entry exactly as create_transaction would, and write nothing."""
    kind = _type(payload.get("type"))
    if kind == "transfer":
        return _clean_transfer(db, cipher, payload, existing=None)[0]
    return _clean(db, cipher, payload, kind, existing=None)


def import_entries(db: Session, cipher: UserCipher, payloads: Sequence[Mapping[str, Any]]) -> int:
    """
    DAT-03. Write many entries from a checked import in ONE commit - all or
    none - without recomputing the budget after each. Only
    import_export_service calls this, after a preview it built.
    """
    repo = TransactionRepository(db, cipher)
    for payload in payloads:
        kind = _type(payload.get("type"))
        if kind == "transfer":
            out_data, in_data = _clean_transfer(db, cipher, payload, existing=None)
            out_leg = repo.create(out_data)
            in_leg = repo.create({**in_data, "pair_id": out_leg.id})
            repo.update(out_leg.id, {**out_data, "pair_id": in_leg.id})
        else:
            repo.create(_clean(db, cipher, payload, kind, existing=None))
    audit_service.record(
        db, audit_service.IMPORT, user_id=cipher.user_id, entity="transactions", cipher=cipher,
        detail={"transactions": len(payloads)},
    )
    db.commit()
    return len(payloads)


def mark_set_aside_prompted(db: Session, cipher: UserCipher, transaction_id: int) -> None:
    """
    GOA-12. The payday prompt has been answered for this income - set aside or
    "not now" - so it is never offered again. Kept on the entry itself (the
    browser may store nothing, invariant 10), so it goes with the entry if it
    is deleted. The caller commits (goal_service).
    """
    record = _record(db, cipher, transaction_id)
    if record.data.get("type") != "income":
        raise BusinessRuleException("Only income is set aside from")
    TransactionRepository(db, cipher).update(transaction_id, {**record.data, "set_aside_prompted": True})


def set_card_posted_on(db: Session, cipher: UserCipher, transaction_id: int, day: date) -> TransactionView:
    """
    ACC-26. Record that the bank posted this purchase on `day`, moving it to a
    later card statement. Its budget period is untouched. The caller audits
    and commits (statement_service).
    """
    record = _record(db, cipher, transaction_id)
    if record.data.get("type") != "expense":
        raise BusinessRuleException("Only a purchase can be posted on a later statement")
    updated = TransactionRepository(db, cipher).update(transaction_id, {**record.data, "card_posted_on": day.isoformat()})
    return _view(updated)


def outcome(
    db: Session, cipher: UserCipher, views: List[TransactionView], *, today: Optional[date] = None
) -> Outcome:
    touched: Set[int] = set()
    for view in views:
        touched.add(view.account_id)
        if view.counter_account_id is not None:
            touched.add(view.counter_account_id)
    accounts = account_service.list_accounts(db, cipher, postings=postings(db, cipher))
    # Imported here, not at the top: budget_service reads postings from this
    # module, so a top-level import would be a cycle.
    from app.services.budget_service import budget_service

    return Outcome(
        transactions=views,
        accounts=[a for a in accounts if a.id in touched],
        cash_on_hand=account_service.cash_on_hand(accounts),
        budget_status=budget_service.status(db, cipher, today=today),
    )


# ---------------------------------------------------------------- cleaning


def _clean(
    db: Session,
    cipher: UserCipher,
    payload: Mapping[str, Any],
    kind: str,
    existing: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    amount = _positive(payload.get("amount"), "amount")
    when = _date(payload.get("txn_date"))
    account_id = _account(db, cipher, payload.get("account_id"), "account_id",
                          allow_archived_if=(existing or {}).get("account_id"))

    raw_splits = payload.get("splits")
    if raw_splits is None:
        if payload.get("category_id") is None:
            raise ValidationException("Choose a category")
        # Input shorthand only - stored, it is a one-element split like any other.
        raw_splits = [{"category_id": payload.get("category_id"), "amount": str(amount)}]
    splits = validate_splits(amount, raw_splits)

    kept = {s.get("category_id") for s in (existing or {}).get("splits") or []}
    categories = _categories(db, cipher)
    for position, split in enumerate(splits, start=1):
        category_id = split["category_id"]
        if category_id is None:
            raise ValidationException(f"Split {position} needs a category")
        category = categories.get(category_id)
        if category is None:
            raise ValidationException(f"Split {position}: that category does not exist")
        if category.get("kind") != kind:
            raise BusinessRuleException(f"Split {position}: an {kind} needs an {kind} category")
        if category.get("archived") and category_id not in kept:
            raise BusinessRuleException(f"Split {position}: that category is archived")

    cleaned = {
        "txn_date": when.isoformat(),
        "type": kind,
        "amount": str(amount),
        "account_id": account_id,
        "merchant": _text(payload.get("merchant"), MERCHANT_MAX),
        "notes": _text(payload.get("notes"), NOTES_MAX),
        "splits": splits,
        "tag_ids": _tags(db, cipher, payload, existing),
        "recurring_id": (existing or {}).get("recurring_id"),
        "recurring_on": (existing or {}).get("recurring_on"),
        # ACC-37. The day this interest was earned for, kept through an edit so
        # the catch-up still knows that day is settled.
        "interest_on": (existing or {}).get("interest_on"),
        # TXN-22. The cashback block and the links between a purchase and its
        # credit are the service's to move (_reconcile_cashback), never a
        # submitted body's - _clean only carries them through untouched.
        "cashback": (existing or {}).get("cashback"),
        "cashback_id": (existing or {}).get("cashback_id"),
        "cashback_of": (existing or {}).get("cashback_of"),
        "attachment_id": (existing or {}).get("attachment_id"),
        # GOA-12. The payday prompt was answered for this income - kept through
        # an edit, so it is never asked twice. Only mark_set_aside_prompted writes it.
        "set_aside_prompted": (existing or {}).get("set_aside_prompted"),
    }
    # ACC-26. A late posting date belongs to one purchase on one card on one
    # day; moving the purchase to another day or card makes it meaningless.
    posted_on = (existing or {}).get("card_posted_on")
    if posted_on and existing.get("txn_date") == cleaned["txn_date"] and existing.get("account_id") == account_id:
        cleaned["card_posted_on"] = posted_on
    return cleaned


def _clean_transfer(
    db: Session,
    cipher: UserCipher,
    payload: Mapping[str, Any],
    existing: Optional[Mapping[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    amount = _positive(payload.get("amount"), "amount")
    when = _date(payload.get("txn_date"))
    source = _account(db, cipher, payload.get("account_id"), "account_id",
                      allow_archived_if=(existing or {}).get("account_id"))
    destination = _account(db, cipher, payload.get("counter_account_id"), "counter_account_id",
                           allow_archived_if=(existing or {}).get("counter_account_id"))
    if source == destination:
        raise BusinessRuleException("A transfer moves money between two different accounts")

    notes = _text(payload.get("notes"), NOTES_MAX)
    # One uncategorised split keeps the shape rule (never empty, sums to the
    # amount) while guaranteeing no category total can ever include it.
    splits = validate_splits(amount, [{"category_id": None, "amount": str(amount)}])
    common = {"txn_date": when.isoformat(), "type": "transfer", "amount": str(amount), "merchant": None,
              "notes": notes, "splits": splits, "tag_ids": [], "attachment_id": None,
              # An edited recurring transfer is still the occurrence it posted as.
              "recurring_id": (existing or {}).get("recurring_id"),
              "recurring_on": (existing or {}).get("recurring_on")}
    return (
        {**common, "direction": "out", "account_id": source, "counter_account_id": destination, "pair_id": None},
        {**common, "direction": "in", "account_id": destination, "counter_account_id": source, "pair_id": None},
    )


# ---------------------------------------------------------------- internals


def _record(db: Session, cipher: UserCipher, transaction_id: int) -> Record:
    for record in TransactionRepository(db, cipher).cached():
        if record.id == transaction_id:
            return record
    raise NotFoundException("Transaction not found")


def _cashback_view(raw: Any) -> Optional[Cashback]:
    """The stored block as the API returns it, or None. Never raises - a read must not fail."""
    if not isinstance(raw, Mapping):
        return None
    try:
        return Cashback(
            amount=money(raw.get("amount", ZERO)),
            account_id=int(raw["account_id"]),
            category_id=int(raw["category_id"]),
            on=date.fromisoformat(str(raw["on"])),
            rate=Decimal(str(raw["rate"])) if raw.get("rate") else None,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _clean_cashback(
    db: Session,
    cipher: UserCipher,
    raw: Any,
    *,
    amount: Decimal,
    purchase_date: date,
    account_id: int,
    existing: Optional[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    TXN-22. Validate the cashback on a purchase into the block that gets
    sealed, or None for no cashback.

    It defaults to the card it was earned on, on the day of the purchase, which
    is what a wallet does; a card that pays at the end of the cycle gets its own
    date, and cashback paid somewhere else gets its own account. A rate is
    remembered, never re-applied.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValidationException("Cashback is an amount and where it lands")

    earned = _positive(raw.get("amount"), "cashback")
    if earned > amount:
        raise BusinessRuleException("Cashback cannot be more than what you spent")

    lands_in = raw.get("account_id") or account_id
    kept = existing or {}
    checked = _account(db, cipher, lands_in, "cashback account", allow_archived_if=kept.get("account_id"))

    category_id = raw.get("category_id")
    if not category_id:
        raise ValidationException("Choose the income category cashback lands in")
    category = _categories(db, cipher).get(int(category_id))
    if category is None:
        raise ValidationException("That cashback category does not exist")
    if category.get("kind") != "income":
        raise BusinessRuleException("Cashback is income, so it needs an income category")
    if category.get("archived") and int(category_id) != kept.get("category_id"):
        raise BusinessRuleException("That cashback category is archived")

    return {
        "amount": str(earned),
        "account_id": checked,
        "category_id": int(category_id),
        "on": _date(raw.get("on") or purchase_date.isoformat()).isoformat(),
        "rate": str(raw["rate"]) if raw.get("rate") else None,
    }


def _cashback_for(
    db: Session,
    cipher: UserCipher,
    payload: Mapping[str, Any],
    data: Mapping[str, Any],
    kind: str,
    *,
    existing: Optional[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    TXN-22. The cashback block a write means: the one submitted, or - when the
    write says nothing about it - the one already there, checked again against
    the amount as it now stands. An edit that drops the purchase below what it
    paid back is refused rather than quietly clamped.
    """
    raw = payload.get("cashback") if "cashback" in payload else (existing or {}).get("cashback")
    if raw is not None and kind != "expense":
        raise BusinessRuleException("Only a purchase earns cashback")
    return _clean_cashback(
        db, cipher, raw, amount=money(data["amount"]),
        purchase_date=date.fromisoformat(str(data["txn_date"])), account_id=int(data["account_id"]),
        existing=(existing or {}).get("cashback"),
    )


def _follow_cashback(db: Session, cipher: UserCipher, credit: Record) -> Record:
    """TXN-22. Copy an edited credit's amount, account and date back onto the purchase's block."""
    repo = TransactionRepository(db, cipher)
    purchase = _record(db, cipher, credit.data["cashback_of"])
    block = dict(purchase.data.get("cashback") or {})
    block.update({"amount": credit.data["amount"], "account_id": credit.data["account_id"],
                  "on": credit.data["txn_date"],
                  "category_id": (credit.data.get("splits") or [{}])[0].get("category_id")})
    return repo.update(purchase.id, {**purchase.data, "cashback": block})


def _reconcile_cashback(
    db: Session,
    cipher: UserCipher,
    record: Record,
    block: Optional[Mapping[str, Any]],
) -> Tuple[Record, Optional[Record]]:
    """
    TXN-22. Bring the purchase's credit row into line with its cashback block:
    write one, correct it, or take it away. Returns (purchase, credit) as
    stored - the rows themselves, because a row written in this transaction is
    not in the working set until COMMIT and could not be read back by id.

    It never commits: the purchase and its credit move in ONE database
    transaction, so a ledger can never hold half a pair.
    """
    repo = TransactionRepository(db, cipher)
    data = record.data
    existing_id = data.get("cashback_id")
    existing = next((r for r in repo.cached() if r.id == existing_id), None) if existing_id else None

    if block is None:
        if existing is not None:
            repo.soft_delete(existing.id)
        if data.get("cashback") is None and existing_id is None:
            return record, None
        return repo.update(record.id, {**data, "cashback": None, "cashback_id": None}), None

    leg = {
        "type": "income",
        "amount": block["amount"],
        "account_id": block["account_id"],
        "txn_date": block["on"],
        "merchant": data.get("merchant") or "Cashback",
        "category_id": block["category_id"],
    }
    if existing is not None:
        cleaned = _clean(db, cipher, leg, "income", existing=existing.data)
        credit = repo.update(existing.id, {**cleaned, "cashback_of": record.id})
    else:
        cleaned = _clean(db, cipher, leg, "income", existing=None)
        credit = repo.create({**cleaned, "cashback_of": record.id})
    return repo.update(record.id, {**data, "cashback": dict(block), "cashback_id": credit.id}), credit


def _legs(db: Session, cipher: UserCipher, record: Record) -> Tuple[Record, Record]:
    """(out leg, in leg) of the transfer this record belongs to."""
    pair_id = record.data.get("pair_id")
    partner = next((r for r in TransactionRepository(db, cipher).cached() if r.id == pair_id), None)
    if partner is None:
        # Integrity drift - no FK could have caught it (verify_integrity.py, Phase 9).
        raise BusinessRuleException("This transfer's other half is missing")
    return (record, partner) if record.data.get("direction") == "out" else (partner, record)


def _view(record: Record) -> TransactionView:
    data = record.data
    return TransactionView(
        id=record.id,
        type=str(data.get("type")),
        txn_date=date.fromisoformat(str(data.get("txn_date"))),
        amount=money(data.get("amount", ZERO)),
        account_id=int(data.get("account_id")),
        splits=tuple(
            Split(s.get("category_id"), money(s.get("amount", ZERO)), s.get("note"))
            for s in data.get("splits") or []
        ),
        merchant=data.get("merchant"),
        notes=data.get("notes"),
        direction=data.get("direction"),
        counter_account_id=data.get("counter_account_id"),
        pair_id=data.get("pair_id"),
        tag_ids=tuple(data.get("tag_ids") or ()),
        recurring_id=data.get("recurring_id"),
        recurring_on=date.fromisoformat(str(data["recurring_on"])) if data.get("recurring_on") else None,
        interest_on=date.fromisoformat(str(data["interest_on"])) if data.get("interest_on") else None,
        cashback=_cashback_view(data.get("cashback")),
        cashback_id=data.get("cashback_id"),
        cashback_of=data.get("cashback_of"),
        attachment_id=data.get("attachment_id"),
        created_at=record.row_created,
        card_posted_on=date.fromisoformat(str(data["card_posted_on"])) if data.get("card_posted_on") else None,
    )


def _day_totals(views: Iterable[TransactionView]) -> List[DayTotal]:
    spent: Dict[date, Decimal] = {}
    earned: Dict[date, Decimal] = {}
    for view in views:
        if view.type == "expense":
            spent[view.txn_date] = spent.get(view.txn_date, ZERO) + view.amount
        elif view.type == "income":
            earned[view.txn_date] = earned.get(view.txn_date, ZERO) + view.amount
    days = sorted(set(spent) | set(earned), reverse=True)
    return [DayTotal(d, spent.get(d, ZERO), earned.get(d, ZERO)) for d in days]


def _matches(view: TransactionView, needle: str) -> bool:
    haystack = [view.merchant or "", view.notes or ""] + [s.note or "" for s in view.splits]
    return any(needle in text.casefold() for text in haystack)


def _category_scope(db: Session, cipher: UserCipher, category_id: int) -> Set[int]:
    """The category and, if it is a parent, its sub-categories - what a person filtering by 'Food' means."""
    scope = {category_id}
    for record in CategoryRepository(db, cipher).list():
        if record.data.get("parent_id") == category_id:
            scope.add(record.id)
    return scope


def _categories(db: Session, cipher: UserCipher) -> Dict[int, Mapping[str, Any]]:
    return {record.id: record.data for record in CategoryRepository(db, cipher).list()}


def _cursor(view: TransactionView) -> str:
    return f"{view.txn_date.isoformat()}_{view.id}"


def _after_cursor(ordered: List[TransactionView], cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        day, _, row = cursor.partition("_")
        key = (date.fromisoformat(day), int(row))
    except ValueError:
        raise ValidationException("That page cursor is not valid") from None
    for index, view in enumerate(ordered):
        if (view.txn_date, view.id) < key:
            return index
    return len(ordered)


def _type(value: Any) -> str:
    kind = str(value or "").strip().lower()
    if kind not in TYPES:
        raise ValidationException(f"type must be one of: {', '.join(TYPES)}")
    return kind


def _amount(value: Any, field: str) -> Decimal:
    try:
        return money(value)
    except ValueError as exc:
        raise ValidationException(f"{field}: {exc}") from None


def _positive(value: Any, field: str) -> Decimal:
    amount = _amount(value, field)
    if amount <= ZERO:
        raise ValidationException("An amount is more than zero")
    if amount > MAX_AMOUNT:
        raise ValidationException("That amount is larger than this app records")
    return amount


def _date(value: Any) -> date:
    if value is None or value == "":
        return date.today()
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date):
        try:
            value = date.fromisoformat(str(value))
        except ValueError:
            raise ValidationException("txn_date is a date like 2026-09-13") from None
    latest = date(date.today().year + 1, 12, 31)
    if not EARLIEST <= value <= latest:
        raise ValidationException("That date is outside what this app records")
    return value


def _account(
    db: Session,
    cipher: UserCipher,
    value: Any,
    field: str,
    allow_archived_if: Optional[int] = None,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationException(f"Choose an account ({field})")
    record = AccountRepository(db, cipher).get(value)
    if record is None:
        raise ValidationException("That account does not exist")
    if record.data.get("archived") and value != allow_archived_if:
        # Editing an old entry on an archived account is fine; adding a new
        # one to it is not - you archived it because it is not in use.
        raise BusinessRuleException("That account is archived")
    return value


def _tags(
    db: Session, cipher: UserCipher, payload: Mapping[str, Any], existing: Optional[Mapping[str, Any]]
) -> List[int]:
    """TXN-10. The payload's tag ids, checked - or the stored ones, when the payload does not mention tags."""
    raw = payload.get("tag_ids")
    if raw is None:
        return list((existing or {}).get("tag_ids") or [])
    if not isinstance(raw, (list, tuple)):
        raise ValidationException("tag_ids is a list")
    chosen: List[int] = []
    for value in raw:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValidationException("A tag id is a number")
        if value not in chosen:
            chosen.append(value)
    if len(chosen) > MAX_TAGS:
        raise ValidationException(f"At most {MAX_TAGS} tags on one transaction")
    if chosen and not set(chosen) <= tag_service.known_ids(db, cipher):
        # No foreign key can say this - the ids are inside the ciphertext.
        raise ValidationException("That tag does not exist")
    return chosen


def _text(value: Any, limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None
