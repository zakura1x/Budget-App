"""
budget_service - budget periods, per-category allocations, and the daily
allowance (BUD-01..BUD-15, ARCHITECTURE.md 3).

    allowance.py      the number the app exists to show (BUD-06/07/08) - pure
    carry_over.py     the symmetric roll-forward between periods (BUD-11) - pure
    alerts.py         over / approaching / pace, computed in-session (BUD-12/14/15) - pure
    budget_service.py the budget itself, its allocations, and the status that
                      stitches the three above together over the working set

Period resolution lives in app/core/utils/date_utils.py, beside the credit-card
statement cycle - shared helpers, never shared dates (ACC-16).
"""
