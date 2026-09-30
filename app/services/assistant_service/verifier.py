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
from typing import Iterable, Set

MAX_REPLY_CHARS = 1500

# 1,234.50 · 1234 · 4.5 · 5k - the sign is ignored: "over by ₱500" and "-₱500" are one figure
_NUMBER = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(\s?[kK](?![A-Za-z]))?")
# A number in words cannot be checked, so it is not allowed (English and Filipino)
_NUMBER_WORDS = re.compile(
    r"\b(hundreds?|thousands?|millions?|billions?|daan|raan|libo|milyon|bilyon)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str  # "" when ok; empty | too_long | number_words | unknown_figure


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


def check(reply: str, allowed_texts: Iterable[str]) -> Verdict:
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
    return Verdict(True, "")
