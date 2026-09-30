"""
The skills: question -> Facts, in plain Python over existing services
(misc/AI ARCHITECTURE §5.2).

A skill never computes a figure a screen does not already show; it calls the
service behind that screen and formats what comes back, so the assistant can
never disagree with the app (a test holds each skill to its endpoint). Each
takes a Context and returns Facts; none writes anything.
"""

from dataclasses import dataclass
from datetime import date
from functools import cached_property
from typing import Callable, Dict, List

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.services import account_service, category_service, goal_service, transaction_service
from app.services.assistant_service.facts import Facts
from app.services.assistant_service.router import Intent


@dataclass
class Context:
    db: Session
    cipher: UserCipher
    today: date
    intent: Intent
    question: str = ""  # the user's words - only how_to reads them; every other skill reads the intent

    @cached_property
    def categories(self) -> Dict[int, category_service.CategoryView]:
        flat: Dict[int, category_service.CategoryView] = {}
        for root in category_service.list_categories(self.db, self.cipher, include_archived=False):
            flat[root.id] = root
            for child in root.children:
                flat[child.id] = child
        return flat

    @cached_property
    def category_names(self) -> Dict[int, str]:
        return {cid: view.name for cid, view in self.categories.items()}

    @cached_property
    def goals(self) -> List[goal_service.GoalView]:
        return goal_service.list_goals(self.db, self.cipher, today=self.today)

    @cached_property
    def goal_names(self) -> Dict[int, str]:
        return {g.id: g.name for g in self.goals}

    @cached_property
    def accounts(self) -> List[account_service.AccountView]:
        """Exactly what GET /accounts builds - the same call, the same figures."""
        return account_service.list_accounts(
            self.db, self.cipher, postings=transaction_service.postings(self.db, self.cipher), today=self.today,
        )

    @cached_property
    def visible_accounts(self) -> List[account_service.AccountView]:
        """What the user can see and name: never the untracked wallet (ACC-39) or an archived account."""
        return [a for a in self.accounts if not a.hidden and not a.archived]

    @cached_property
    def account_names(self) -> Dict[int, str]:
        return {a.id: a.name for a in self.visible_accounts}

    def account_name(self, account_id: int) -> str:
        for view in self.accounts:
            if view.id == account_id:
                return "your wallet" if view.hidden else view.name
        return "an account"


def run(ctx: Context) -> Facts:
    from app.services.assistant_service.skills import (
        afford, budget_status, card, cash, emergency, goals, how_to, other, payoff, review, spending,
        subscriptions, upcoming,
    )

    table: Dict[str, Callable[[Context], Facts]] = {
        "budget_status": budget_status.run,
        "spending": spending.run,
        "cash": cash.run,
        "upcoming": upcoming.run,
        "card": card.run,
        "afford": afford.run,
        "review": review.run,
        "goals": goals.run,
        "emergency": emergency.run,
        "subscriptions": subscriptions.run,
        "payoff": payoff.run,
        "how_to": how_to.run,
        "off_topic": other.off_topic,
    }
    skill = table.get(ctx.intent.skill or "")
    return skill(ctx) if skill else other.clarify(ctx)
