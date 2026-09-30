"""
The figure check (misc/AI ARCHITECTURE §5.1, AI-07).

A reply may state a number only if the same number is in the facts the skill
built, or in the user's own question ("can I spend 3,999?"). Every number is
compared by VALUE, so "₱4,210.00", "4210" and "4,210.0" are the same figure,
and "5k" is 5000. One number that is in neither means the reply is thrown away
and the template answers instead. So a figure the model invented, rounded,
added up or misread cannot be shown - not "is unlikely to be" (AI-07).

This errs toward refusing. A date written as 2026-10-08 when the facts say
8 Oct, "about ₱4,200" for ₱4,210.00, or a number spelled out in words, all
fail, and the user gets the template, which is always correct.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional, Set

MAX_REPLY_CHARS = 1500

# AI-30: a reply may not open against the verdict the rules decided, or say the opposite anywhere
_OPENS_YES = re.compile(r"^\W*(?:yes|yep|yeah|sure|absolutely|definitely|go ahead|oo|opo|kaya mo|pwede)\b", re.I)
_OPENS_NO = re.compile(r"^\W*(?:no|nope|not yet|not right now|hindi|huwag)\b", re.I)
_SAYS_CANNOT = re.compile(r"\b(?:can'?t|cannot|can not) afford\b|\bhindi mo kaya\b", re.I)
_SAYS_CAN = re.compile(r"\byou can afford\b|\bkaya mo(?:ng)? bilhin\b", re.I)

# AI-35: the assistant describes the user's numbers; it does not advise. A reply that tells the user
# what to do is replaced by the template, whatever its figures.
_ADVICE = re.compile(
    r"\byou should\b|\byou shouldn'?t\b|\bi (?:would )?(?:recommend|suggest|advise)\b|\bmy advice\b|"
    # not "you need to pay ₱2,450.00 on 13 Oct" - that is a bill stated, not advice given
    r"\byou ought to\b|\bdapat (?:mong?|kang|ka)\b|\bmas mabuting?\b|"
    r"\b(?:not |in)?advisable\b|\b(?:un)?wise\b|\bbest (?:to|option)\b|\bbetter to\b|"
    # an instruction, at the start of the reply, a sentence or a clause: "Pay off the card first.",
    # "Based on the snowball method, pay off the card first."
    r"(?:^|[.!?,;:]\s+|\s-\s)\W*(?:pay|buy|save|cut|stop|avoid|consider|try|start|focus|bayaran|bilhin|iwasan)\b",
    re.I,
)

# The reply speaks to the user, not about its own inputs: "the facts do not show..." is the model
# describing the prompt, which means nothing to the person reading it.
_META = re.compile(r"\bthe facts\b|\bfacts (?:do|don'?t|show|provided|given|above|below)\b|\bprovided (?:data|facts)\b",
                   re.I)

# 1,234.50 · 1234 · 4.5 · 5k - the sign is ignored: "over by ₱500" and "-₱500" are one figure
_NUMBER = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(\s?[kK](?![A-Za-z]))?")
# A number in words cannot be checked, so it is not allowed (English and Filipino)
_NUMBER_WORDS = re.compile(
    r"\b(hundreds?|thousands?|millions?|billions?|daan|raan|libo|milyon|bilyon)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str  # "" when ok; empty | too_long | number_words | unknown_figure | against_verdict | advice | meta


def figures(text: str) -> Set[Decimal]:
    found: Set[Decimal] = set()
    for whole, fraction, thousands in _NUMBER.findall(text):
        try:
            value = Decimal(whole.replace(",", "") + (fraction or ""))
        except InvalidOperation:
            continue
        if thousands:
            value *= 1000
        found.add(value.normalize())
    return found


def against(reply: str, verdict: str) -> bool:
    """True when the reply contradicts a decided verdict (AI-30)."""
    text = reply.strip()
    if verdict in ("yes", "yes_over_budget"):
        return bool(_OPENS_NO.match(text) or _SAYS_CANNOT.search(text))
    if verdict == "tight":
        return bool(_OPENS_YES.match(text) or _OPENS_NO.match(text))  # tight is neither a yes nor a no
    if verdict in ("wait", "no"):
        return bool(_OPENS_YES.match(text) or _SAYS_CAN.search(text))
    return False


def check(reply: str, allowed_texts: Iterable[str], verdict: Optional[str] = None) -> Verdict:
    text = reply.strip()
    if not text:
        return Verdict(False, "empty")
    if len(text) > MAX_REPLY_CHARS:
        return Verdict(False, "too_long")
    if _NUMBER_WORDS.search(text):
        return Verdict(False, "number_words")
    allowed: Set[Decimal] = set()
    for source in allowed_texts:
        allowed |= figures(source)
    if figures(text) - allowed:
        return Verdict(False, "unknown_figure")
    if verdict and against(text, verdict):
        return Verdict(False, "against_verdict")
    if _ADVICE.search(text):
        return Verdict(False, "advice")
    if _META.search(text):
        return Verdict(False, "meta")
    return Verdict(True, "")
