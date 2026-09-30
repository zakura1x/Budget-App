"""Request and response shapes for /assistant (misc/AI ARCHITECTURE §10, AI-01..05)."""

from typing import Dict, Optional

from pydantic import BaseModel


class AssistantStatusOut(BaseModel):
    enabled: bool  # AI_ENABLED and this user is on the pilot list, if there is one
    questions_left_today: Optional[int]  # None = no daily cap


class HealthCheckOut(BaseModel):
    ok: bool
    detail: str
    ms: Optional[int] = None


class UsageTodayOut(BaseModel):
    users: int
    questions: int
    model_calls: int
    prompt_tokens: int
    completion_tokens: int
    fallbacks: int


class AssistantHealthOut(BaseModel):
    status: str  # disabled | ok | failing
    enabled: bool
    model: str
    company: str
    timeout_seconds: int
    checks: Dict[str, HealthCheckOut]
    usage_today: UsageTodayOut
