"""
The replies with no figures and no model call: off-topic, a clarifying
question when nobody could tell what was asked (misc/AI ARCHITECTURE §5.2),
and small talk - hello, thanks, ok - answered as what it is (2026-10-01: "Hi"
and "thanks!" used to get "I can only help with your own money").
"""

from app.services.assistant_service.facts import Facts
from app.services.assistant_service.router import suggestions


def off_topic(ctx) -> Facts:
    return Facts(
        skill="off_topic", title="Outside the budget", lines=[],
        template="I can only help with your own money in this app - your budget, spending, cash, bills, cards, "
                 "goals, and whether you can afford something. Try one of these:",
        phrase=False, follow_ups=suggestions()[:4],
    )


_CHAT = {
    "greeting": "Hi! Ask me anything about your money - what's left in your budget, where it went, what's due "
                "soon, or whether you can afford something.",
    "thanks": "You're welcome! Anything else you'd like to know?",
    "ack": "Got it. Anything else you'd like to check?",
}


def chat(ctx) -> Facts:
    """Hello, thanks, ok. The follow-ups carry on from the last answer when there is one."""
    kind = ctx.intent.item if ctx.intent.item in _CHAT else "ack"
    follow = list(ctx.follow_ups) if ctx.follow_ups else []
    return Facts(
        skill="chat", title="", lines=[], template=_CHAT[kind], phrase=False,
        follow_ups=follow[:3] or suggestions()[:4],
    )


def clarify(ctx) -> Facts:
    return Facts(
        skill="clarify", title="Not sure what you meant", lines=[],
        template=("I'm not sure what you mean. Could you say it another way? For example:"
                  if ctx.follow_ups else "I'm not sure what you're asking. I can answer questions like these:"),
        phrase=False, follow_ups=suggestions()[:5],
    )
