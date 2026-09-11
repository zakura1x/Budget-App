"""Request and response shapes for /auth. Strings are length-capped so a
request cannot make bcrypt or BIP-39 chew on megabytes."""

from typing import List, Optional

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)
    registration_code: str = Field(min_length=1, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=60)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class PinRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=12)


class PasswordRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class SetPinRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=12)
    current_password: Optional[str] = Field(default=None, max_length=256)


class RecoverRequest(BaseModel):
    phrase: str = Field(min_length=1, max_length=400)
    new_password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: int
    is_admin: bool
    email: Optional[str] = None  # only while unlocked - it lives under the DEK
    display_name: Optional[str] = None


class SessionOut(BaseModel):
    user: UserOut
    locked: bool
    pin_set: bool
    auto_lock_minutes: int


class RegisterOut(SessionOut):
    # Shown ONCE. Nothing on the server keeps a copy.
    recovery_phrase: List[str]


class PasswordPolicy(BaseModel):
    min_length: int
    require_upper: bool
    require_digit: bool
    require_symbol: bool


class AuthConfigOut(BaseModel):
    registration_open: bool
    pin_enabled: bool
    pin_length: int
    recovery_words: int
    password_policy: PasswordPolicy
