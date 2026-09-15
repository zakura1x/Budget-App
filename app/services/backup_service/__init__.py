"""
The full encrypted backup (DAT-06..DAT-17; FEATURES.md §15; ARCHITECTURE.md §12).

    references.py        every reference inside a ciphertext, and the fixed
                         insert order - the map a restore remaps through
    bundle.py            the .budgetbak file: write (no key), read, list, prune
    restore_service.py   unlock with the master key, then
                         fresh | merge | verify
    scheduler.py         automatic backup, triggered by use (DAT-08)
"""
