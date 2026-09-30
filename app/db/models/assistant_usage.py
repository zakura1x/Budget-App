"""
assistant_usage - Shape A. How much each user asked the AI companion, per day
(misc/AI ARCHITECTURE §7, AI-05).

Counts only: never a question, a reply or a figure, so nothing here needs a
key. It is what the daily question cap reads, and what the Admin screen totals.
`day` is the server's calendar day (date.today(), as the rest of the server
uses). One row per user per day.
"""

from datetime import date

from sqlalchemy import Date, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import BigIntPK


class AssistantUsage(Base):
    __tablename__ = "assistant_usage"
    __table_args__ = (UniqueConstraint("user_id", "day", name="UQ_assistant_usage_user_day"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Answers given from a template because the model failed or was rejected (AI-08)
    fallbacks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
