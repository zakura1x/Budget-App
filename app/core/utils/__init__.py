"""
Pure helpers - no database, no session, no clock of their own.

`date_utils` resolves periods (the budget month, and a credit card's own
statement cycle, which are never the same thing - ACC-16) and `money` is the
one place a value becomes a Decimal.
"""
