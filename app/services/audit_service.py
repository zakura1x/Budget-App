"""
Audit trail - every security-relevant event and, from Phase 3 on, every
mutation (ARCHITECTURE.md section 8).

The verb and the entity are plaintext, so the log is useful to you. Anything
that would reveal a figure or a name goes in `detail`, which is sealed under
the acting user's DEK - the log must not become the side channel that leaks
what the data tables protect. Events with no unlocked user (a wrong password,
a wrong registration code) have no detail at all.
"""

from typing import Any, Mapping, Optional

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.db.repositories.audit_repository import AuditRepository

# The verbs, in one place so they stay consistent.
REGISTER = "REGISTER"
REGISTER_REJECTED = "REGISTER_REJECTED"
LOGIN = "LOGIN"
LOGIN_FAILED = "LOGIN_FAILED"
LOGOUT = "LOGOUT"
UNLOCK = "UNLOCK"
UNLOCK_FAILED = "UNLOCK_FAILED"
PIN_SET = "PIN_SET"
PIN_LOCKOUT = "PIN_LOCKOUT"
REFRESH_REUSE = "REFRESH_REUSE"
SESSION_END = "SESSION_END"  # SEC-32 - other devices signed out from Settings, with the count
PASSKEY_ADD = "PASSKEY_ADD"  # SEC-12
PASSKEY_REMOVE = "PASSKEY_REMOVE"

# Data mutations, from Phase 3 on. The verb and the table stay plaintext so the
# trail is readable; the name, the amount and anything else identifying goes in
# `detail`, sealed under the acting user's DEK.
CREATE = "CREATE"
UPDATE = "UPDATE"
DELETE = "DELETE"
ARCHIVE = "ARCHIVE"
RESTORE = "RESTORE"
REVALUE = "REVALUE"  # ACC-12 - a valuation change, deliberately not income
REASSIGN = "REASSIGN"  # CAT-08 - transactions moved off a deleted category
REORDER = "REORDER"
# ACC-30 - a typed balance recorded as an adjustment. Written ONLY when the
# user accepts; fixing the opening balance instead writes no such entry.
BALANCE_ADJUST = "BALANCE_ADJUST"
STATEMENT_CHECK = "STATEMENT_CHECK"  # ACC-24 - the bank's total for one statement
BALANCE_CHECK = "BALANCE_CHECK"  # ACC-41 - the bank's balance for one day
INTEREST = "INTEREST"  # ACC-37 - days of savings interest credited, with the count
# Phase 7 - the recurring engine.
EXPAND = "EXPAND"  # REC-04/05 - occurrences posted, with the count
PAUSE = "PAUSE"
RESUME = "RESUME"
SKIP = "SKIP"  # REC-15
PAYOFF = "PAYOFF"  # REC-13
PLAN_PAYMENT = "PLAN_PAYMENT"  # REC-32 - money paid on a plan, and what any extra did
GOAL_SET_ASIDE = "GOAL_SET_ASIDE"  # GOA-08 - part of an account earmarked for a goal; nothing moves
GOAL_USE = "GOAL_USE"  # GOA-08 - what a goal held, released
PAY_NOW = "PAY_NOW"  # REC-33 - a repeating charge's next occurrence recorded early
INSTALLMENT_CONVERT = "INSTALLMENT_CONVERT"  # REC-34 - a purchase turned into an installment plan
INSTALLMENT_REVERT = "INSTALLMENT_REVERT"  # REC-34 - that plan turned back into the one purchase
CONFIRM_TERMS = "CONFIRM_TERMS"  # REC-29 - interest from the first statement
# Phase 8a - data in and out.
BACKUP = "BACKUP"  # DAT-06 - "Back up now"; automatic ones are logged, not audited
RESTORE = "RESTORE"  # DAT-07 - mode, how it was unlocked, counts
EXPORT = "EXPORT"  # DAT-02 - plaintext left the boundary on purpose
IMPORT = "IMPORT"  # DAT-03
# Phase 8b - the account's own security, and the admin.
PASSWORD_CHANGE = "PASSWORD_CHANGE"
PASSWORD_RESET_REQUEST = "PASSWORD_RESET_REQUEST"  # SEC-30 - a link was mailed
PASSWORD_RESET = "PASSWORD_RESET"  # SEC-30 - the link was used
DEK_ROTATE = "DEK_ROTATE"  # SEC-23
ACCOUNT_DELETE = "ACCOUNT_DELETE"  # SEC-21 - no detail: its key is gone
USER_DISABLE = "USER_DISABLE"  # UX-20
USER_ENABLE = "USER_ENABLE"


def record(
    db: Session,
    action: str,
    *,
    user_id: Optional[int] = None,
    entity: Optional[str] = None,
    entity_id: Optional[int] = None,
    ip_hash: Optional[str] = None,
    cipher: Optional[UserCipher] = None,
    detail: Optional[Mapping[str, Any]] = None,
) -> None:
    AuditRepository(db).add(
        action=action, user_id=user_id, entity=entity, entity_id=entity_id,
        ip_hash=ip_hash, cipher=cipher, detail=detail,
    )
