"""Request and response shapes for /auth. Strings are length-capped so a
request cannot make bcrypt chew on megabytes."""

from typing import Optional

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


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetRequestedOut(BaseModel):
    """The same whether or not the address has an account."""

    link_minutes: int


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=128)
    password: str = Field(min_length=1, max_length=256)


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


class PasswordPolicy(BaseModel):
    min_length: int
    require_upper: bool
    require_digit: bool
    require_symbol: bool


class AuthConfigOut(BaseModel):
    registration_open: bool
    pin_enabled: bool
    pin_length: int
    password_reset_enabled: bool
    reset_link_minutes: int
    password_policy: PasswordPolicy
