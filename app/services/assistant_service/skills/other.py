"""
The two replies with no figures and no model call: off-topic, and a clarifying
question when nobody could tell what was asked (misc/AI ARCHITECTURE §5.2).
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


def clarify(ctx) -> Facts:
    return Facts(
        skill="clarify", title="Not sure what you meant", lines=[],
        template="I'm not sure what you're asking. I can answer questions like these:",
        phrase=False, follow_ups=suggestions()[:5],
    )
