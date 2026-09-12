"""
accounts - Shape B (ACC-01..ACC-18).

Nothing here knows what an account MEANS; it stores and returns payloads. The
balance arithmetic, the statement cycle and the cash-on-hand rule all live in
account_service, because none of them can be expressed in SQL over ciphertext.
"""

from app.db.models import Account
from app.db.repositories.encrypted_repository import EncryptedRepository


class AccountRepository(EncryptedRepository):
    model = Account
