"""
Column types.

Two jobs:

1. PORTABLE TYPES. Production is SQL Server; the test suite runs the same
   models on SQLite so the two-step insert, AAD binding and tamper detection
   are exercised against a real database without touching the company one.
   Each type is the SQL Server type, with a SQLite stand-in.

2. EncryptedPayload - the guard on every ciphertext column.

   It cannot do the encryption itself: a TypeDecorator sees one value, and the
   AAD needs the row's id and user (ARCHITECTURE.md 5.3). Repositories do that
   through UserCipher. What this type does is REFUSE TO WRITE ANYTHING THAT IS
   NOT A SEALED ENVELOPE. Assign a dict, a str, or JSON bytes to a payload
   column and the flush raises, instead of plaintext landing in the database.

   It guards against mistakes, not adversaries - shape is not proof - but the
   mistake it catches is the one that would quietly defeat the whole design.
"""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, LargeBinary, SmallInteger
from sqlalchemy.dialects import mssql
from sqlalchemy.types import TypeDecorator

from app.core.crypto.envelope import PLACEHOLDER, is_envelope

# BIGINT IDENTITY on SQL Server; SQLite only autoincrements INTEGER PRIMARY KEY.
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")

TinyInt = SmallInteger().with_variant(mssql.TINYINT(), "mssql")

# DATETIME2, always UTC, stored naive (SQL Server has no zone on DATETIME2).
UtcDateTime = DateTime().with_variant(mssql.DATETIME2(), "mssql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EncryptedPayload(TypeDecorator):
    """VARBINARY(MAX) that only accepts a sealed envelope (or the placeholder)."""

    impl = LargeBinary
    cache_ok = True

    def __init__(self, length=None):
        # length=None -> VARBINARY(MAX); a number for fixed-size blobs such as
        # a wrapped DEK (62 bytes, stored in VARBINARY(128)).
        super().__init__()
        self.length = length

    def load_dialect_impl(self, dialect):
        if dialect.name == "mssql":
            return dialect.type_descriptor(mssql.VARBINARY(self.length or "max"))
        return dialect.type_descriptor(LargeBinary(self.length))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, (bytearray, memoryview)):
            value = bytes(value)
        if not isinstance(value, bytes):
            raise TypeError(
                f"Refusing to write a {type(value).__name__} to an encrypted column. "
                "Payloads are sealed by the repository through UserCipher - "
                "never assigned directly."
            )
        if value == PLACEHOLDER or is_envelope(value):
            return value
        raise ValueError(
            "Refusing to write bytes that are not a sealed envelope to an encrypted column"
        )

    def process_result_value(self, value, dialect):
        return None if value is None else bytes(value)
