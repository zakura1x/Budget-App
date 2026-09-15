"""
recurring_rules and subscriptions - Shape B (REC-01..30, SUB-00..08).

A rule's schedule, template, amount history and installment terms are all
inside its ciphertext. So are the references a posted transaction makes back to
it (`recurring_id`, `recurring_on`), which is why recurring_service - not SQL -
decides whether an occurrence has already posted.

A subscriptions row carries only what a subscription adds to its rule
(`recurring_rule_id`, `reminder_days`). It has no schedule: the rule it points
at is the one thing that can post a Netflix charge.
"""

from app.db.models import RecurringRule, Subscription
from app.db.repositories.encrypted_repository import EncryptedRepository


class RecurringRuleRepository(EncryptedRepository):
    model = RecurringRule


class SubscriptionRepository(EncryptedRepository):
    model = Subscription
