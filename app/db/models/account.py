"""
accounts - Shape B.

Payload: name, type (cash | debit | credit | savings | investment), opening
balance, colour, icon, archived, counts_in_cash_on_hand (ACC-17/18), manual
value for investment accounts (ACC-08), statement closing day, payment due day
and credit limit for credit cards (ACC-09/14). No currency field - PHP only
(ACC-11).
"""

from app.db.base import Base
from app.db.models.encrypted_row import EncryptedRowMixin


class Account(EncryptedRowMixin, Base):
    __tablename__ = "accounts"
