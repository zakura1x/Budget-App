"""
One question, end to end (misc/AI ARCHITECTURE §9).

    cap -> in-flight guard -> rules -> (ROUTE call if unsure) -> skill -> ANSWER
    call -> figure check -> reply, or the template

Never raises for a model problem: IAM down, a timeout, junk JSON or a reply
the verifier rejects all end in the skill's template, marked ai_phrased=false
(AI-08). The only errors are the caller's (too long, over the daily cap,
already asking), and those are raised before anything is counted.

Nothing here writes financial data. The one write is the usage count, which
is committed with the turn. Logs carry the skill, how it was routed, whether
the model phrased the reply, why not, counts and elapsed_ms - never the
question or the reply (AI-52).
"""

import json
import logging
import re
import time
from datetime import date
from typing import Any, Dict, Mapping, Optional, Tuple

from sqlalchemy.orm import Session

from app.ai import llm_service
from app.core.config import settings
from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import (
    AssistantBusyException,
    AssistantDailyLimitException,
    AssistantQuestionTooLongException,
    ValidationException,
)
from app.services.assistant_service import router, skills, usage, verifier
from app.services.assistant_service.facts import Facts
from app.services.assistant_service.memory import Turn, get_memory
from app.services.assistant_service.prompts import PROMPT_VERSION, answer_prompt

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 500
ROUTE_PARAMS = {"max_new_tokens": 200, "decoding_method": "greedy"}


def _answer_params() -> Dict[str, Any]:
    return {"max_new_tokens": 400, "temperature": 0.3, "top_p": settings.WATSONX_TOP_P}


def ask(
    db: Session,
    cipher: UserCipher,
    *,
    question: str,
    today: Optional[date] = None,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    text = " ".join((question or "").split())
    if not text:
        raise ValidationException("Type a question first")
    if len(text) > MAX_QUESTION_CHARS:
        raise AssistantQuestionTooLongException(f"Keep a question under {MAX_QUESTION_CHARS} characters")
    if usage.questions_left(db, cipher.user_id) == 0:
        raise AssistantDailyLimitException(
            f"That's today's {settings.AI_MAX_QUESTIONS_PER_DAY} questions. The assistant is back tomorrow.")
    try:
        with llm_service.concurrency_guard.slot(cipher.user_id):
            return _turn(db, cipher, text, today or date.today(), conversation_id)
    except llm_service.ConcurrencyLimitReached as error:
        raise AssistantBusyException(str(error)) from None


class _Meter:
    """Model calls and tokens for one turn - what assistant_usage adds up."""

    def __init__(self) -> None:
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def add(self, used: Mapping[str, Any]) -> None:
        self.calls += 1
        self.prompt_tokens += int(used.get("prompt_tokens") or 0)
        self.completion_tokens += int(used.get("completion_tokens") or 0)


def _service() -> Optional[llm_service.LLMService]:
    if not llm_service.is_enabled():
        return None
    try:
        return llm_service.get_llm_service()
    except Exception as error:
        logger.warning("Assistant model unavailable: %s", error.__class__.__name__)
        return None


def _parse_json(reply: str) -> Mapping:
    match = re.search(r"\{[\s\S]*\}", reply)
    if not match:
        raise ValueError("no JSON object in the reply")
    return json.loads(match.group(0))


def _turn(db: Session, cipher: UserCipher, text: str, today: date, conversation_id: Optional[str]) -> Dict[str, Any]:
    started = time.perf_counter()
    memory = get_memory()
    conversation = memory.get_or_start(cipher.user_id, conversation_id)
    meter = _Meter()
    service = _service()
    model_name = settings.WATSONX_CHAT_MODEL

    ctx = skills.Context(db=db, cipher=cipher, today=today, intent=router.Intent(skill=None))
    intent = router.by_rules(text, today, ctx.category_names, ctx.account_names)
    if intent.skill is None and service is not None:
        def ask_json(prompt: str) -> Tuple[Mapping, Dict[str, int]]:
            reply, used = service.invoke_with_recovery(model_name, ROUTE_PARAMS, prompt)
            meter.add(used)
            return _parse_json(reply), used

        intent = router.merge(intent, router.by_model(text, today, ctx.category_names, ctx.account_names, ask_json))
    ctx.intent = intent

    facts = skills.run(ctx)
    reply_text, phrased, reason = _phrase(service, model_name, facts, text, conversation.history(), meter)

    reply = {
        "conversation_id": conversation.id,
        "question": text,
        "text": reply_text,
        "ai_phrased": phrased,
        "skill": facts.skill,
        "title": facts.title,
        "facts": list(facts.lines),
        "sources": [{"label": s.label, "route": s.route} for s in facts.sources],
        "actions": [{"kind": a.kind, "label": a.label, "route": a.route} for a in facts.actions],
        "tone": facts.tone,
        "follow_ups": list(facts.follow_ups),
    }
    memory.append(cipher.user_id, conversation, Turn(question=text, reply=reply))
    usage.record(db, cipher.user_id, questions=1, model_calls=meter.calls, prompt_tokens=meter.prompt_tokens,
                 completion_tokens=meter.completion_tokens, fallbacks=int(facts.phrase and not phrased))
    db.commit()
    logger.info(
        "Assistant turn skill=%s routed_by=%s phrased=%s reason=%s model_calls=%d elapsed_ms=%d prompt=%s",
        facts.skill, "model" if intent.by_model else "rules", phrased, reason or "-", meter.calls,
        int((time.perf_counter() - started) * 1000), PROMPT_VERSION,
    )
    return reply


def _phrase(service, model_name: str, facts: Facts, question: str, history, meter: _Meter) -> Tuple[str, bool, str]:
    """(text, ai_phrased, why not). The template whenever the model is off, fails, or is not believed."""
    if not facts.phrase:
        return facts.template, False, ""
    if service is None:
        return facts.template, False, "disabled"
    try:
        reply, used = service.invoke_with_recovery(model_name, _answer_params(), answer_prompt(facts, question, history))
        meter.add(used)
    except Exception as error:
        return facts.template, False, llm_service.describe_model_error(error).split(" ")[0]
    verdict = verifier.check(reply, [*facts.lines, question])
    if not verdict.ok:
        return facts.template, False, verdict.reason
    return reply.strip(), True, ""
