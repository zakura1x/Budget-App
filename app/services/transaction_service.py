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

Reads never touch SQL beyond the first cold load - they filter, sort, search
and page in Python over TransactionRepository.cached() (TXN-12/13).
"""

from dataclasses import dataclass, field
from datetime import date, datetime
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


# ------------------------------------------------------------------- shapes


@dataclass(frozen=True)
class Split:
    category_id: Optional[int]
    amount: Decimal
    note: Optional[str] = None


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
        result.append(Posting(view.account_id, view.txn_date, view.amount * sign, view.type, view.card_posted_on))
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
        records = [repo.create(data)]

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
        records = [
            repo.update(out_record.id, {**out_data, "pair_id": in_record.id}),
            repo.update(in_record.id, {**in_data, "pair_id": out_record.id}),
        ]
    else:
        data = _clean(db, cipher, payload, kind, existing=record.data)
        records = [repo.update(transaction_id, data)]

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

    for leg in doomed:
        repo.soft_delete(leg.id)
    audit_service.record(
        db, audit_service.DELETE, user_id=cipher.user_id, entity="transactions",
        entity_id=transaction_id, cipher=cipher,
        detail={"type": record.data.get("type"), "legs": len(doomed)},
    )
    db.commit()
    return outcome(db, cipher, [_view(leg) for leg in doomed], today=today)


def repeat_last(
    db: Session, cipher: UserCipher, *, on: Optional[date] = None, today: Optional[date] = None
) -> Outcome:
    """
    TXN-17. Clone the most recently ENTERED transaction - by when it was
    written, not its date - onto `on` (today by default). It goes back through
    the same validation as a new entry, so an account archived since cannot
    quietly receive a copy.
    """
    # A balance adjustment is never something you meant to buy twice (ACC-29).
    records = [r for r in TransactionRepository(db, cipher).cached() if r.data.get("type") != "adjustment"]
    if not records:
        raise NotFoundException("There is nothing to repeat yet")
    latest = max(records, key=lambda r: (r.row_created, r.id))
    if latest.data.get("type") == "transfer" and latest.data.get("direction") == "in":
        latest = _legs(db, cipher, latest)[0]

    data = latest.data
    when = (on or date.today()).isoformat()
    if data.get("type") == "transfer":
        payload = {"type": "transfer", "txn_date": when, "amount": data["amount"],
                   "account_id": data["account_id"], "counter_account_id": data["counter_account_id"],
                   "notes": data.get("notes")}
    else:
        payload = {"type": data["type"], "txn_date": when, "amount": data["amount"],
                   "account_id": data["account_id"], "merchant": data.get("merchant"),
                   "notes": data.get("notes"), "splits": data["splits"],
                   "tag_ids": list(data.get("tag_ids") or [])}
    return create_transaction(db, cipher, payload, today=today)


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
        "attachment_id": (existing or {}).get("attachment_id"),
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
