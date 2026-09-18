"""
installment_conversion - a purchase on a card or a loan, paid in installments
instead (REC-34, added 2026-09-18).

The user's case: ₱12,000 bought on a card, and the bank splits it into three
monthly payments. The PURCHASE BECOMES THE PLAN (decided with the user, option
A): an installment rule takes over the purchase's amount, categories,
merchant, note, tags, account and date, and the purchase itself is hidden -
soft-deleted and linked both ways (`from_transaction` on the rule,
`converted_to` on the purchase) - so nothing is counted twice:

  * the budget sees one payment a month, as every installment does (REC-14);
  * the card owes the whole price from day one (`plans_unbilled`), so what it
    owes does not move when the purchase turns into a plan;
  * each payment lands on the bill of its own month (ACC-35), and a typed
    bill list that already held the purchase counts the plan as held too
    (account_service._plan_charges);
  * payments whose date has come are posted at once - the purchase they
    replace was already there.

A purchase split across categories keeps its proportions on every payment
(`category_shares`); its receipt stays on it and is shown on the plan; any
cashback already received stays its own income entry.

CONVERTING BACK (`revert`) removes the plan and the payments it posted and
brings the purchase back exactly as it was. Money PAID on the plan (a transfer,
REC-32) really moved, so it stays.

Only a card (credit) or a loan (borrowed) can do this: on any other account
the money has already left, and there is nothing to spread.

Import direction: this imports recurring_service and transaction_service;
only its endpoints import it.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import BusinessRuleException, NotFoundException, ValidationException
from app.core.utils.date_utils import add_months, statement_period
from app.core.utils.money import ZERO, money
from app.db.repositories.account_repository import AccountRepository
from app.db.repositories.category_repository import CategoryRepository
from app.db.repositories.recurring_repository import RecurringRuleRepository
from app.db.repositories.transaction_repository import TransactionRepository
from app.services import audit_service, recurring_service, transaction_service

SPREADS_ON: Tuple[str, ...] = ("credit", "borrowed")
ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class Preview:
    start: date
    payments: List[Tuple[date, Decimal]]
    due_now: int  # payments dated on or before today - posted as soon as the plan is saved
    on_closed_statement: bool  # the purchase sits on a card statement that has closed


# ------------------------------------------------------------------ reading


def preview(
    db: Session,
    cipher: UserCipher,
    *,
    account_id: int,
    amount: Any,
    on: date,
    payments: Any,
    start: Optional[date] = None,
    interest: Any = None,
    today: Optional[date] = None,
) -> Preview:
    """What the plan would be: its first payment day and every payment. Writes nothing."""
    today = today or date.today()
    account = _account(db, cipher, account_id)
    first = start or default_start(account, on)
    data = recurring_service._pure(  # noqa: SLF001 - the one schedule, validated the one way
        {"kind": "installment", "type": "expense", "price": str(_price(amount)), "payments": payments,
         "interest": None if interest in (None, "") else str(interest), "start": first.isoformat(),
         "frequency": "monthly"},
        None, today, 0,
    )
    rows = recurring_service.installment_plan(data)
    return Preview(
        start=first,
        payments=[(day, price + extra) for day, price, extra in rows],
        due_now=sum(1 for day, _, _ in rows if day <= today),
        on_closed_statement=_closed(account, on, today),
    )


def default_start(account: Mapping[str, Any], on: date) -> date:
    """
    The first payment: on a card, the bill the purchase itself would have been
    on - its statement's due date; on a loan, a month after the purchase.
    """
    if account.get("type") == "credit":
        closing = int(account.get("statement_closing_day") or 1)
        due = int(account.get("payment_due_day") or 1)
        return statement_period(on, closing, due).due
    return add_months(on, 1)


# ------------------------------------------------------------------ writing


def convert(
    db: Session, cipher: UserCipher, transaction_id: int, terms: Mapping[str, Any], *, today: Optional[date] = None
) -> recurring_service.RuleView:
    """REC-34. Turn one purchase into an installment plan. One commit, then the payments already due post."""
    today = today or date.today()
    transactions = TransactionRepository(db, cipher)
    record = next((r for r in transactions.cached() if r.id == transaction_id), None)
    if record is None:
        raise NotFoundException("Transaction not found")
    data = record.data
    if data.get("type") != "expense":
        raise BusinessRuleException("Only a purchase can be paid in installments")
    if data.get("recurring_id") is not None:
        raise BusinessRuleException("This is already a payment of a plan")
    account = _account(db, cipher, int(data["account_id"]))

    rules = RecurringRuleRepository(db, cipher)
    if rules.count() >= recurring_service.MAX_RULES:
        raise BusinessRuleException(f"At most {recurring_service.MAX_RULES} recurring rules")

    on = date.fromisoformat(str(data.get("card_posted_on") or data["txn_date"]))
    start = _opt_date(terms.get("start")) or default_start(account, on)
    splits = [(int(s["category_id"]), money(s["amount"])) for s in data.get("splits") or [] if s.get("category_id")]
    if not splits:
        raise BusinessRuleException("Give this purchase a category first")
    main = max(splits, key=lambda s: s[1])[0]
    categories = {r.id: r.data for r in CategoryRepository(db, cipher).list()}
    payload: Dict[str, Any] = {
        "kind": "installment", "type": "expense",
        "name": data.get("merchant") or (categories.get(main) or {}).get("name") or "Installment",
        "account_id": int(data["account_id"]), "category_id": main,
        "price": str(money(data["amount"])), "payments": terms.get("payments"),
        "interest": None if terms.get("interest") in (None, "") else str(terms["interest"]),
        "start": start.isoformat(), "frequency": "monthly",
        "merchant": data.get("merchant"), "notes": data.get("notes"), "tag_ids": list(data.get("tag_ids") or []),
    }
    if len(splits) > 1:
        payload["category_shares"] = [{"category_id": c, "amount": str(a)} for c, a in splits]
    rule = recurring_service._clean(db, cipher, payload, None, today, posted_count=0)  # noqa: SLF001
    # Every payment from the first one posts: the purchase they replace was already recorded.
    rule.update({"posted_through": (start - ONE_DAY).isoformat(), "pauses": [], "skips": [], "closed_on": None,
                 "from_transaction": record.id})
    created = rules.create(rule)

    # TXN-22. Cashback already received stays as its own income entry.
    if data.get("cashback_id"):
        credit = next((r for r in transactions.cached() if r.id == data["cashback_id"]), None)
        if credit is not None:
            transactions.update(credit.id, {**credit.data, "cashback_of": None})
    transactions.update(record.id, {**data, "converted_to": created.id})
    transactions.soft_delete(record.id)
    audit_service.record(
        db, audit_service.INSTALLMENT_CONVERT, user_id=cipher.user_id, entity="recurring_rules",
        entity_id=created.id, cipher=cipher,
        detail={"transaction_id": record.id, "price": rule["price"], "payments": rule["payments"],
                "start": rule["start"]},
    )
    db.commit()
    recurring_service._expand(db, cipher, [created], today)  # noqa: SLF001 - the payments already due
    return recurring_service.get_rule(db, cipher, created.id, today=today)


def create_with_plan(
    db: Session, cipher: UserCipher, purchase: Mapping[str, Any], terms: Mapping[str, Any], *, today: Optional[date] = None
) -> recurring_service.RuleView:
    """
    REC-34, from the add sheet: a new purchase paid in installments from the
    start. The terms are checked BEFORE the purchase is written, so a bad
    number of payments cannot leave a lone purchase behind.
    """
    today = today or date.today()
    if purchase.get("type") != "expense":
        raise BusinessRuleException("Only a purchase can be paid in installments")
    account_id = purchase.get("account_id")
    if not isinstance(account_id, int) or isinstance(account_id, bool):
        raise ValidationException("Choose an account")
    on = _opt_date(purchase.get("txn_date")) or today
    preview(db, cipher, account_id=account_id, amount=purchase.get("amount"), on=on,
            payments=terms.get("payments"), start=_opt_date(terms.get("start")), interest=terms.get("interest"),
            today=today)
    outcome = transaction_service.create_transaction(db, cipher, {**purchase, "cashback": None}, today=today)
    return convert(db, cipher, outcome.transactions[0].id, terms, today=today)


def revert(
    db: Session, cipher: UserCipher, rule_id: int, *, today: Optional[date] = None
) -> transaction_service.TransactionView:
    """REC-34. The plan goes, with the payments it posted; the purchase comes back as it was."""
    rules = RecurringRuleRepository(db, cipher)
    rule = rules.get(rule_id)
    if rule is None:
        raise NotFoundException("Plan not found")
    origin = rule.data.get("from_transaction")
    if not origin:
        raise BusinessRuleException("This plan was not made from a purchase")
    transactions = TransactionRepository(db, cipher)
    original = transactions.get(int(origin), include_deleted=True)
    if original is None or not original.is_deleted:
        raise BusinessRuleException("The purchase this plan came from is not there to bring back")

    removed = 0
    for record in list(transactions.cached()):
        # The scheduled charges only: money PAID on the plan (a transfer, REC-32) really moved.
        if record.data.get("recurring_id") == rule_id and record.data.get("type") == "expense":
            transactions.soft_delete(record.id)
            removed += 1
    restored = {k: v for k, v in original.data.items() if k != "converted_to"}
    credit_id = restored.get("cashback_id")
    if credit_id:
        credit = next((r for r in transactions.cached() if r.id == credit_id), None)
        if credit is not None and credit.data.get("cashback_of") is None:
            transactions.update(credit.id, {**credit.data, "cashback_of": original.id})
        elif credit is None:
            restored.update({"cashback": None, "cashback_id": None})  # deleted meanwhile - the link goes with it
    transactions.update(original.id, restored)
    transactions.undelete(original.id)
    rules.soft_delete(rule_id)
    audit_service.record(
        db, audit_service.INSTALLMENT_REVERT, user_id=cipher.user_id, entity="recurring_rules",
        entity_id=rule_id, cipher=cipher, detail={"transaction_id": original.id, "payments_removed": removed},
    )
    db.commit()
    return transaction_service.get_transaction(db, cipher, original.id)


# ---------------------------------------------------------------- internals


def _account(db: Session, cipher: UserCipher, account_id: int) -> Mapping[str, Any]:
    record = AccountRepository(db, cipher).get(account_id)
    if record is None:
        raise NotFoundException("Account not found")
    if record.data.get("type") not in SPREADS_ON:
        raise BusinessRuleException("Only a purchase on a credit card or a loan can be paid in installments")
    return record.data


def _closed(account: Mapping[str, Any], on: date, today: date) -> bool:
    if account.get("type") != "credit":
        return False
    closing = int(account.get("statement_closing_day") or 1)
    due = int(account.get("payment_due_day") or 1)
    return statement_period(on, closing, due).closes < today


def _price(amount: Any) -> Decimal:
    try:
        value = money(amount)
    except (ValueError, TypeError, ArithmeticError):
        raise ValidationException("Type the amount") from None
    if value <= ZERO:
        raise ValidationException("Type the amount")
    return value


def _opt_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValidationException("That is not a date") from None
