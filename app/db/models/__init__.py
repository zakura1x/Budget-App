"""
The sixteen tables of schema ZBDGT (ARCHITECTURE.md section 4.2).

Importing this package registers every model on Base.metadata - alembic/env.py
depends on that, or autogenerate would see an empty schema.

Shape A (operational):  users, refresh_tokens, login_attempts, audit_log,
                        assistant_usage (misc/AI, counts only)
Shape B (encrypted):    the eleven in ENCRYPTED_MODELS
"""

from app.db.models.account import Account
from app.db.models.assistant_usage import AssistantUsage
from app.db.models.attachment import Attachment
from app.db.models.audit_log import AuditLog
from app.db.models.budget import Budget
from app.db.models.budget_allocation import BudgetAllocation
from app.db.models.category import Category
from app.db.models.login_attempt import LoginAttempt
from app.db.models.recurring_rule import RecurringRule
from app.db.models.refresh_token import RefreshToken
from app.db.models.savings_goal import SavingsGoal
from app.db.models.subscription import Subscription
from app.db.models.tag import Tag
from app.db.models.transaction import Transaction
from app.db.models.user import User
from app.db.models.user_preference import UserPreference

OPERATIONAL_MODELS = (User, RefreshToken, LoginAttempt, AuditLog, AssistantUsage)

ENCRYPTED_MODELS = (
    Account,
    Category,
    Budget,
    BudgetAllocation,
    Transaction,
    RecurringRule,
    Subscription,
    SavingsGoal,
    Tag,
    Attachment,
    UserPreference,
)

ENCRYPTED_TABLES = {model.__tablename__: model for model in ENCRYPTED_MODELS}

__all__ = [m.__name__ for m in OPERATIONAL_MODELS + ENCRYPTED_MODELS] + [
    "ENCRYPTED_MODELS",
    "ENCRYPTED_TABLES",
    "OPERATIONAL_MODELS",
]
