"""
how_to (AI-21): how to use the app, and what its words mean - from a
hand-written index, with no user data and no model call.

Each topic is matched by keywords; the best match answers, with a button to
the screen it is about. Keep the answers in step with the screens: they are the
app describing itself, so a stale one is a wrong answer.
"""

import re
from typing import List, Tuple

from app.services.assistant_service.facts import Action, Facts

# (keywords, answer, button label, route)
TOPICS: List[Tuple[Tuple[str, ...], str, str, str]] = [
    (("add", "record", "expense", "entry", "log", "magdagdag", "ilagay"),
     "Tap the big + in the middle of the tab bar. Type the amount, pick a category and the account it came from, "
     "and save. Swipe an entry on the ledger to edit it.", "Open the ledger", "/transactions"),
    (("transfer", "move money", "ilipat"),
     "Tap + and switch the sheet to Transfer. Pick the account the money leaves and the one it goes into - "
     "paying a card is a transfer into the card.", "Open accounts", "/accounts"),
    (("budget", "allowance", "carry"),
     "Set the amount and period on the Budget screen (More > Budget); you can give categories their own share. "
     "Your daily allowance is what is left divided by the days left. Carry-over is a switch in Settings.",
     "Open budget", "/budget"),
    (("card bill", "bills", "typed bill", "statement", "card"),
     "Open the card from the Accounts tab. Type the bills your card's app shows, or check a statement's total "
     "against the bank's; a payment to the card is a transfer into it.", "Open accounts", "/accounts"),
    (("goal", "set aside", "sinking", "save for", "ipon"),
     "Make a goal on the Goals screen and choose the account its money sits in. Setting money aside keeps it in "
     "that account but leaves it out of cash on hand. A sinking fund follows a yearly bill.", "Open goals", "/goals"),
    (("recurring", "repeat", "subscription", "salary", "rent"),
     "Add repeating bills, pay and subscriptions under More > Recurring. They post themselves on their dates and "
     "show on Months ahead and the calendar.", "Open recurring", "/recurring"),
    (("installment", "hulugan", "0%"),
     "An installment is a Recurring plan of the installment kind, on a card or a loan. You can also turn a purchase "
     "you already recorded into one from its sheet.", "Open recurring", "/recurring"),
    (("cash on hand",),
     "Cash on hand is the money you can spend now: the accounts switched to count toward it, less money set aside "
     "for goals, with a card that has typed bills counting only what is due now.", "Open accounts", "/accounts"),
    (("net worth",),
     "Net worth is everything you own less everything you owe - every account at its full value, with cards, "
     "loans and unbilled installments owed in full.", "Open accounts", "/accounts"),
    (("months ahead", "projection", "forecast"),
     "Months ahead (More) runs your scheduled pay, bills and budget forward and shows your cash on hand at the end "
     "of each month, and its lowest point.", "Open months ahead", "/projection"),
    (("emergency",),
     "The Emergency fund screen says how many months your emergency money lasts and sets a target from a few "
     "rules; answer its three questions for a closer target.", "Open emergency fund", "/emergency"),
    (("backup", "restore", "export", "csv", "import"),
     "Backup & data (More) makes an encrypted backup, restores one, and exports or imports CSV.",
     "Open backup", "/backup"),
    (("pin", "lock", "passkey", "face id", "fingerprint"),
     "The app locks itself after a few idle minutes; unlock with your PIN or a passkey. Change the timing in "
     "Settings and see signed-in devices under Security.", "Open settings", "/settings"),
    (("category", "categories", "kategorya"),
     "Add, rename, reorder or archive categories under More > Categories; mark the ones that are essential for "
     "the emergency fund.", "Open categories", "/categories"),
    (("delete", "undo", "recently deleted", "burahin"),
     "Delete an entry from its sheet; Undo appears for a few seconds, and More > Recently deleted brings one back "
     "for 30 days.", "Open recently deleted", "/deleted"),
    (("assistant", "turn off", "privacy"),
     "The assistant only reads your figures and never changes anything. Turn it off at the bottom of the "
     "Assistant screen; nothing it was told is kept after the app locks.", "Open assistant", "/assistant"),
]


def _score(question: str, keywords: Tuple[str, ...]) -> int:
    text = question.lower()
    return sum(len(k) for k in keywords if re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", text))


def run(ctx) -> Facts:
    question = getattr(ctx, "question", "") or ""
    best = max(TOPICS, key=lambda t: _score(question, t[0]))
    if _score(question, best[0]) == 0:
        return Facts(
            skill="how_to", title="Using the app", lines=[],
            template="I can explain how to add entries, transfers, budgets, card bills, goals, recurring bills, "
                     "installments, backups and more. What would you like to do?",
            phrase=False,
            follow_ups=["How do I add an expense?", "What is cash on hand?", "How do I set aside money for a goal?"],
        )
    _, answer, label, route = best
    return Facts(skill="how_to", title="Using the app", lines=[], template=answer, phrase=False,
                 actions=[Action("open_screen", label, route)])
