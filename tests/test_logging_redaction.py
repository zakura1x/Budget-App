"""
The redaction filter - exit criterion: no plaintext amount appears in logs/
under LOG_LEVEL=DEBUG.
"""

import base64
import json
import logging
import secrets
from decimal import Decimal

import pytest

from app.core.logging_config import RedactionFilter, StripQueryStringFilter, redact, setup_logging

pytestmark = pytest.mark.security


@pytest.mark.parametrize(
    "line, forbidden",
    [
        ("spent PHP 5,000.00 on the motorcycle", "5,000"),
        ("rent ₱18,500 due", "18,500"),
        ("balance is 1,234,567", "1,234,567"),
        ("amount 3500.00 posted", "3500.00"),
        ('{"amount": "700.00", "note": "household"}', "700"),
        ("amount=12 merchant=Jollibee", "Jollibee"),
        ("password=hunter2-Correct", "hunter2"),
        ("pin: 482913", "482913"),
        ("PWD={s3cr3t;pass}", "s3cr3t"),
        ("email noah@example.com logged in", "noah@example.com"),
        ("payload=b'\\x01\\x01\\x8f\\x12\\x99\\x00\\x11\\x22'", "\\x8f"),
        ("splits=[{'category_id': 11, 'amount': Decimal('2800.00')}]", "2800"),
    ],
)
def test_redacts_money_secrets_and_identifiers(line, forbidden):
    assert forbidden not in redact(line)


def test_redacts_keys_in_base64_and_hex():
    key_b64 = base64.b64encode(secrets.token_bytes(32)).decode()
    key_hex = secrets.token_hex(32)
    token = secrets.token_urlsafe(64)
    out = redact(f"loaded {key_b64} and {key_hex} and {token}")
    assert key_b64 not in out and key_hex not in out and token not in out


def test_leaves_ordinary_diagnostics_alone():
    line = "GET /ZBDGT/static/dist/assets/index-a1b2c3d4.js 200 elapsed_ms=412 rows=10000 v1.19.2 127.0.0.1"
    assert redact(line) == line


def test_filter_renders_args_and_exceptions_redacted():
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, "txn %s failed", ({"amount": Decimal("99.50")},), None)
    try:
        raise ValueError("bad amount 4200.00")
    except ValueError:
        import sys

        record.exc_info = sys.exc_info()
    RedactionFilter().filter(record)
    assert "99.50" not in record.getMessage()
    assert "4200.00" not in record.exc_text
    assert record.args is None


def test_access_log_query_strings_are_dropped():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", "/ZBDGT/api/v1/transactions?q=Jollibee", "1.1", 200), None,
    )
    StripQueryStringFilter().filter(record)
    assert "Jollibee" not in record.getMessage()
    assert "/ZBDGT/api/v1/transactions" in record.getMessage()


def test_no_plaintext_amount_reaches_the_log_file_at_debug(tmp_path):
    """End to end: real handlers, DEBUG level, a careless logger.debug(transaction)."""
    setup_logging(log_dir=str(tmp_path), console=False)
    logging.getLogger().setLevel(logging.DEBUG)
    transaction = {
        "txn_date": "2026-09-08", "amount": Decimal("3500.00"), "merchant": "SM Supermarket",
        "splits": [{"category_id": 11, "amount": Decimal("2800.00")}],
    }
    log = logging.getLogger("app.careless")
    log.debug("saving %s", transaction)
    log.debug("amount was %s for %s", Decimal("2800.00"), "noah@example.com")
    log.info("user paid PHP 5,000 for installment 1 of 36")
    try:
        raise RuntimeError(f"failed to post {transaction}")
    except RuntimeError:
        log.exception("write failed")
    for handler in logging.getLogger().handlers:
        handler.flush()

    content = (tmp_path / "app.jsonl").read_text(encoding="utf-8")
    assert content.count("\n") >= 4
    for line in content.splitlines():
        json.loads(line)  # every line is valid JSON
    for forbidden in ("3500", "2800", "5,000", "SM Supermarket", "noah@example.com"):
        assert forbidden not in content, forbidden
    assert "installment" in content  # redaction is surgical, not total
