"""
Logging - with the REDACTION FILTER installed before any handler exists.

ARCHITECTURE.md section 5.5: the redaction filter is the second line of
defence for the day someone adds a well-meaning `logger.debug(transaction)`.
The first line is that nothing outside crypto/ and repositories/ holds a
ciphertext or a key. This file is what catches the mistakes anyway.

What it removes, from the message, its arguments, and any traceback:

  * money          PHP 5,000 / P5,000 / 3500.00 / 1,234,567 / "amount": "12"
  * keys           base64 blobs of 32+ bytes, long hex runs, b'...' reprs
  * named secrets  password=..., pin=..., phrase: ..., token=..., PWD=...
  * a recovery     any run of 12 or more consecutive BIP-39 words
    phrase

It over-redacts on purpose. A log line that says "[AMOUNT]" where a harmless
figure was is a small cost; a log line that says "rent 18,500.00" on a shared
server is the thing the whole design exists to prevent. Durations and counts
should be logged as plain integers ("elapsed_ms=412"), which pass through.

Stdlib logging rather than loguru, as QUOT does: uvicorn and SQLAlchemy log
through stdlib, and a filter attached to every stdlib handler is one place that
sees all of it.
"""

import io
import json
import logging
import re
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from app.core.config import PROJECT_ROOT, settings

# ============================================
# Redaction rules
# ============================================

def _looks_like_key(run: str) -> bool:
    """
    Random base64 has all three character classes and few slashes (about one
    in 64 characters). A URL path such as /ZBDGT/static/dist/assets/index-ab12
    is just as long but slash-dense, and is left alone.
    """
    return (
        any(c.isdigit() for c in run)
        and any(c.isupper() for c in run)
        and any(c.islower() for c in run)
        and run.count("/") <= len(run) // 16
    )


_SENSITIVE_NAMES = (
    r"password|passwd|pwd|pin|pin_hash|phrase|mnemonic|recovery[_ ]?(?:phrase|key)?|"
    r"secret|token|refresh[_ ]?token|access[_ ]?token|authorization|cookie|api[_ ]?key|"
    r"master[_ ]?key|dek|dek_wrapped(?:_recovery)?|pepper|payload|registration[_ ]?code|"
    r"amount|balance|total|limit|credit[_ ]?limit|opening[_ ]?balance|value|splits|"
    r"merchant|notes?|email"
)

_RULES = [
    # key=value / key: value / "key": "value" for sensitive names. The value runs
    # to the next separator; a quoted value runs to its closing quote.
    (
        re.compile(
            rf"""(?ix)
            (["']?\b(?:{_SENSITIVE_NAMES})\b["']?\s*[:=]\s*)
            (
                "(?:[^"\\]|\\.)*"      # a double-quoted value
              | '(?:[^'\\]|\\.)*'      # a single-quoted value
              | \[[^\]]*\]             # a list
              | \{{[^}}]*\}}           # an object
              | [^\s,;&)}}\]]+         # a bare value
            )
            """
        ),
        r"\1[REDACTED]",
    ),
    # bytes reprs: b'...' / b"..." - a ciphertext or a key printed by accident
    (re.compile(r"""\bb(['"])(?:(?!\1).){8,}?\1"""), "[REDACTED-BYTES]"),
    # email addresses - an identifier, and the one the blind index hides
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[EMAIL]"),
    # base64 of 30+ bytes (keys, peppers, wrapped DEKs, tokens) - see _looks_like_key
    (
        re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9+/=_-])"),
        lambda m: "[REDACTED-KEY]" if _looks_like_key(m.group(0)) else m.group(0),
    ),
    # long hex runs (keys in hex, digests)
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "[REDACTED-HEX]"),
    # currency-marked amounts: PHP 5,000.00 / ₱5000 / P 1,200
    (re.compile(r"(?:\bPHP\b|₱|\bPhp\b)\s?-?\d[\d,]*(?:\.\d+)?"), "[AMOUNT]"),
    # grouped thousands: 1,234 / 18,500.00
    (re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w.])"), "[AMOUNT]"),
    # decimals with exactly two places: 3500.00 / 5.50
    (re.compile(r"(?<![\w.])-?\d+\.\d{2}(?![\w.])"), "[AMOUNT]"),
]

_phrase_words: Optional[frozenset] = None


def _bip39_words() -> frozenset:
    global _phrase_words
    if _phrase_words is None:
        try:
            from mnemonic import Mnemonic

            _phrase_words = frozenset(Mnemonic("english").wordlist)
        except Exception:  # noqa: BLE001 - redaction must never stop logging
            _phrase_words = frozenset()
    return _phrase_words


_WORD = re.compile(r"[A-Za-z]+")
_PHRASE_RUN = 12


def _redact_phrases(text: str) -> str:
    """Replace any run of 12+ consecutive BIP-39 words (any separators)."""
    words = _bip39_words()
    if not words:
        return text
    matches = list(_WORD.finditer(text))
    if len(matches) < _PHRASE_RUN:
        return text
    spans = []
    run_start = None
    run_len = 0
    for i, m in enumerate(matches):
        if m.group(0).lower() in words:
            if run_start is None:
                run_start = i
            run_len += 1
        else:
            if run_len >= _PHRASE_RUN:
                spans.append((matches[run_start].start(), matches[i - 1].end()))
            run_start, run_len = None, 0
    if run_len >= _PHRASE_RUN:
        spans.append((matches[run_start].start(), matches[-1].end()))
    for start, end in reversed(spans):
        text = text[:start] + "[REDACTED-PHRASE]" + text[end:]
    return text


def redact(text: str) -> str:
    """Apply every rule. Never raises."""
    if not text:
        return text
    try:
        text = _redact_phrases(text)
        for pattern, replacement in _RULES:
            text = pattern.sub(replacement, text)
        return text
    except Exception:  # noqa: BLE001
        return "[REDACTION FAILED - LINE DROPPED]"


class RedactionFilter(logging.Filter):
    """
    Rewrites a record in place: message rendered with its args, redacted, and
    the args dropped; any exception pre-formatted and redacted. Attached to
    every HANDLER - a filter on a logger does not see records propagated from
    child loggers, a filter on a handler sees everything that handler writes.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "_redacted", False):
            return True
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad format string
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        if record.exc_info:
            formatter = logging.Formatter()
            record.exc_text = redact(formatter.formatException(record.exc_info))
            record.exc_info = None
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        record._redacted = True
        return True


class StripQueryStringFilter(logging.Filter):
    """
    uvicorn's access log prints the full path, query string included - and
    search terms (merchant names, notes) travel in the query. Keep the path,
    drop the query.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = args[:2] + (args[2].split("?", 1)[0],) + args[3:]
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for logs/app.jsonl. Output is redacted too."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_text:
            entry["exc"] = record.exc_text
        elif record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(entry, ensure_ascii=False))


class RedactingFormatter(logging.Formatter):
    """Plain-text formatter whose final output is redacted once more."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def _utf8_stdout():
    """stdout as UTF-8 that never raises - same reasoning as QUOT's."""
    stream = sys.stdout
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
        return stream
    except (AttributeError, ValueError, OSError):
        pass
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        try:
            return io.TextIOWrapper(buffer, encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError, OSError):
            pass
    return stream


_configured = False


def setup_logging(log_dir: Optional[str] = None, console: bool = True) -> None:
    """
    Configure logging. Idempotent.

    Order matters and is the point of this function: the redaction filter is
    created FIRST and attached to each handler BEFORE that handler is added to
    a logger, so there is no instant in which a handler can write an
    unredacted line.
    """
    global _configured
    redaction = RedactionFilter()

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handlers = []
    if console:
        console_handler = logging.StreamHandler(_utf8_stdout())
        console_handler.setFormatter(
            RedactingFormatter("%(asctime)s %(levelname)-7s %(name)s - %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        handlers.append(console_handler)

    directory = Path(log_dir or settings.LOG_DIR)
    if not directory.is_absolute():
        directory = PROJECT_ROOT / directory
    try:
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            directory / "app.jsonl",
            maxBytes=settings.LOG_MAX_SIZE,
            backupCount=settings.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(JsonFormatter())
        handlers.append(file_handler)
    except OSError as exc:
        sys.stderr.write(f"[logging] could not open log file in {directory}: {exc.strerror}\n")

    for handler in handlers:
        handler.addFilter(redaction)  # BEFORE the handler is attached
        handler.setLevel(level)
        root.addHandler(handler)

    # uvicorn configures its own handlers (propagate=False) before it imports
    # this app. Route them through ours instead, so its lines are redacted too.
    access_filter = StripQueryStringFilter()
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        logger.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.addFilter(access_filter)
    # app.core.middleware.logging_middleware writes one line per request, with
    # the user id and without the query string. uvicorn's copy would be a
    # duplicate, so it is kept for warnings only.
    access.setLevel(logging.WARNING)

    # SQL echo would print parameters - which for this app are ciphertexts and
    # blind indexes. Keep the engine quiet regardless of DEBUG.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if not _configured:
        logging.getLogger(__name__).info(
            "Logging configured - level %s, redaction on, dir %s", settings.LOG_LEVEL, directory
        )
    _configured = True
