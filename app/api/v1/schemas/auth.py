"""Request and response shapes for /auth. Strings are length-capped so a
request cannot make bcrypt chew on megabytes."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


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
    passkey_set: bool = False  # SEC-12


class PasskeyAnswer(BaseModel):
    """SEC-12 - what navigator.credentials.get() answered, binary fields base64url."""

    credential_id: str = Field(max_length=1400)
    client_data_json: str = Field(max_length=4096)
    authenticator_data: str = Field(max_length=4096)
    signature: str = Field(max_length=1024)


class PasskeyNew(BaseModel):
    """SEC-12 - what navigator.credentials.create() answered."""

    client_data_json: str = Field(max_length=4096)
    attestation_object: str = Field(max_length=16384)
    label: Optional[str] = Field(default=None, max_length=60)


class PasskeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    label: Optional[str] = None
    created: datetime
    last_used: Optional[datetime] = None


class OpenSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device: Optional[str] = None
    started: datetime
    last_active: datetime
    current: bool


class SignInOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    at: datetime
    kind: str
    success: bool
    same_network: bool


class ActivityOut(BaseModel):
    """SEC-32 - who is signed in, and the last month of sign-ins."""

    sessions: List[OpenSessionOut]
    sign_ins: List[SignInOut]
    passkeys: List[PasskeyOut]
    passkey_enabled: bool


class SessionsEndedCountOut(BaseModel):
    ended: int


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
    passkey_enabled: bool = False  # SEC-12
    password_policy: PasswordPolicy
