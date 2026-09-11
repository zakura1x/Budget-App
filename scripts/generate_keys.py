"""
Generate every secret this app needs, in one run.

    python scripts/generate_keys.py            print them
    python scripts/generate_keys.py --fill     write them into .env, but ONLY
                                               into keys that are still empty

NOT FOR AN EXISTING INSTALL. A new BUDGET_MASTER_KEY cannot unwrap a DEK
wrapped under the old one, and a new BUDGET_BLIND_INDEX_PEPPER finds no user.
--fill therefore never overwrites a value that is already set - to replace a
key on a live install, use scripts/rotate_keys.py (Phase 9).

The one exception is disaster recovery: if .env is LOST, generate a fresh set
and recover each account with its 12-word phrase (misc/how-to-run.txt).
"""

import argparse
import base64
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def b64_32() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode()


GENERATORS = {
    "BUDGET_MASTER_KEY": b64_32,
    "BUDGET_BLIND_INDEX_PEPPER": b64_32,
    "JWT_SECRET_KEY": lambda: secrets.token_urlsafe(64),
    "PIN_PEPPER": b64_32,
    "SESSION_SECRET": lambda: secrets.token_urlsafe(48),
    "REGISTRATION_CODE": lambda: secrets.token_urlsafe(18),
}


def fill_env(path: Path) -> list:
    """Fill empty secret keys in .env in place. Returns the names filled."""
    text = path.read_text(encoding="utf-8")
    filled = []
    for name, make in GENERATORS.items():
        pattern = re.compile(rf"^{name}=[ \t]*$", re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub(f"{name}={make()}", text, count=1)
            filled.append(name)
    path.write_text(text, encoding="utf-8")
    return filled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fill", action="store_true", help="write into EMPTY keys of .env only")
    args = parser.parse_args()

    if args.fill:
        if not ENV_FILE.exists():
            print("No .env - copy .env.example to .env first.", file=sys.stderr)
            return 1
        filled = fill_env(ENV_FILE)
        if filled:
            print("Filled: " + ", ".join(filled))
            print("\nBack .env up NOW, off this machine, before the first row is written.")
        else:
            print("Nothing to fill - every secret in .env already has a value. Nothing was changed.")
        return 0

    print("# Paste into .env. NEVER into an install that already has data.\n")
    for name, make in GENERATORS.items():
        print(f"{name}={make()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
