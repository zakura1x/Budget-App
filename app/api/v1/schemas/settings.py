"""Request and response shapes for /security, /goals and /admin (SEC-21..24, GOA-01..07, UX-20)."""

from datetime import date, datetime
from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.budgets import Ratio
from app.api.v1.schemas.common import Colour, IconName, Money


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class ReauthIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class DeleteAccountIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    confirm_email: str = Field(min_length=1, max_length=254)


class SessionsEndedOut(BaseModel):
    sessions_ended: int


class RotatedKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sessions_ended: int
    backups_replaced: bool


class GoalIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=60)
    target: Optional[Money] = None
    target_date: Optional[date] = None
    account_id: Optional[int] = None
    colour: Optional[Colour] = None
    icon: Optional[IconName] = None


class ContributeIn(BaseModel):
    amount: Money
    from_account_id: int
    txn_date: Optional[date] = None


class GoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    target: Money
    target_date: Optional[date] = None
    account_id: int
    colour: str
    icon: str
    saved: Money
    remaining: Money
    ratio: Ratio
    reached: bool


class AdminUserOut(BaseModel):
    """What an admin can see: the row, never the data - not even the email, which lives under the user's key (SEC-18)."""

    id: int
    is_admin: bool
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None
    key_version: int


class ActiveIn(BaseModel):
    active: bool


class AdminDeleteIn(BaseModel):
    confirm_user_id: int
    password: str = Field(min_length=1, max_length=256)


class AdminStatusOut(BaseModel):
    users: int
    active_users: int
    max_users: int
    master_key_version: int
    master_key_versions_loaded: int
    unlocked_sessions: int
    cached_users: int
    rows: Dict[str, int]  # per table, every user - counts only
    # SEC-31: short non-secret hashes of the keys this process loaded, to compare
    # with the offline copy of .env (scripts/env_fingerprint.py).
    key_fingerprints: Dict[str, str]
