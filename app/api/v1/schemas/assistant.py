"""Request and response shapes for /assistant (misc/AI ARCHITECTURE §10, AI-01..05)."""

from datetime import date
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class AssistantStatusOut(BaseModel):
    enabled: bool  # AI_ENABLED and this user is on the pilot list, if there is one
    opted_in: bool  # the `assistant` preference (AI-50)
    questions_left_today: Optional[int]  # None = no daily cap
    reply_language: Literal["en", "match"]  # AI-63
    suggestions: List[str]


class AskIn(BaseModel):
    # The length rule lives in the service, so it answers ASSISTANT_QUESTION_TOO_LONG
    question: str = Field(max_length=2000)
    today: Optional[date] = None
    conversation_id: Optional[str] = Field(default=None, max_length=40)
    # AI-40: where an Explain link was tapped. It NAMES a place; the server reads the figures itself.
    context: Optional["AskContext"] = None


class AskContext(BaseModel):
    screen: Optional[str] = Field(default=None, max_length=20)
    alert: Optional[str] = Field(default=None, max_length=30)
    account_id: Optional[int] = None


AskIn.model_rebuild()  # AskContext is declared after the model that names it


class LinkOut(BaseModel):
    label: str
    route: str


class ActionOut(BaseModel):
    kind: Literal["open_screen", "draft_transaction", "draft_goal", "try_installment"]
    label: str
    route: str = ""
    # A draft's fields, for the ordinary sheet to open pre-filled. Nothing is saved until the user does.
    payload: Optional[Dict[str, Any]] = None


class ReplyOut(BaseModel):
    conversation_id: str
    question: str
    text: str
    ai_phrased: bool  # False: answered from the skill's own sentence (AI-08)
    skill: str
    title: str
    facts: List[str]
    sources: List[LinkOut]
    actions: List[ActionOut]
    tone: Optional[Literal["ok", "warn", "danger"]] = None
    label: Optional[str] = None  # the chip's words when the tone's own do not fit ("Wait", "No")
    verdict: Optional[Literal["yes", "yes_over_budget", "tight", "wait", "no"]] = None  # AI-30
    follow_ups: List[str]


class ConversationOut(BaseModel):
    conversation_id: str
    turns: List[ReplyOut]


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
