"""
Non-secret fingerprints of the secrets in .env (SEC-31; ARCHITECTURE.md 5.2.1).

The offline copy of .env is only insurance if it holds the SAME keys as the
server. A fingerprint lets the two be compared without either being shown:

    fingerprint = first 12 hex of SHA-256("budget:env-fingerprint:v1:" NAME "=" value)

Only settings holding long random values are fingerprinted (FINGERPRINTED): a
short hash of such a key cannot be turned back into it. A password or the
registration code is guessable, and a hash of it would let guesses be checked
offline - so those are only ever compared as same / different.

Imports nothing from the app: scripts/env_fingerprint.py must run against a
copy of .env on a USB stick, with no database and no valid config.
"""

import hashlib
import hmac
from typing import Dict, Mapping

FINGERPRINTED = (
    "BUDGET_MASTER_KEY",
    "BUDGET_RETIRED_KEYS",
    "BUDGET_BLIND_INDEX_PEPPER",
    "PIN_PEPPER",
    "JWT_SECRET_KEY",
    "SESSION_SECRET",
)


def fingerprint(name: str, value: str) -> str:
    digest = hashlib.sha256(f"budget:env-fingerprint:v1:{name}={value.strip()}".encode("utf-8")).hexdigest()
    return f"{digest[0:4]}-{digest[4:8]}-{digest[8:12]}"


def parse_env(text: str) -> Dict[str, str]:
    """NAME=value lines; comments and blank lines skipped. The last occurrence of a name wins, as in dotenv."""
    values: Dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export "):].strip()
        values[name] = value.strip()
    return values


def fingerprints(values: Mapping[str, str]) -> Dict[str, str]:
    """A fingerprint for each random key present; '(empty)' for one set to nothing."""
    return {
        name: fingerprint(name, values[name]) if values[name].strip() else "(empty)"
        for name in FINGERPRINTED
        if name in values
    }


def compare(first: Mapping[str, str], second: Mapping[str, str]) -> Dict[str, str]:
    """Every setting in either file -> 'same' | 'DIFFERENT' | 'only in first' | 'only in second'. Never a value."""
    result: Dict[str, str] = {}
    for name in sorted(set(first) | set(second)):
        if name not in second:
            result[name] = "only in first"
        elif name not in first:
            result[name] = "only in second"
        else:
            same = hmac.compare_digest(first[name].encode("utf-8"), second[name].encode("utf-8"))
            result[name] = "same" if same else "DIFFERENT"
    return result
