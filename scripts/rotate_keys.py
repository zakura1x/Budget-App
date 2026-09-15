"""
Rotate the master key (SEC-11; ARCHITECTURE.md 5.2.2). Dry run first, always.

    python scripts/rotate_keys.py --status
    python scripts/rotate_keys.py --new-key --dry-run
    python scripts/rotate_keys.py --new-key
        -> RESTART THE APP (IIS: recycle the ZBDGT app pool) so it loads the new key
    python scripts/rotate_keys.py --rewrap --dry-run
    python scripts/rotate_keys.py --rewrap
        -> refresh the offline copy of .env TODAY, and check it with env_fingerprint.py

--new-key edits .env and nothing else: a fresh BUDGET_MASTER_KEY, the version
one higher, and the old key appended to BUDGET_RETIRED_KEYS. Every DEK still
opens, because the old key stays loaded as a retired version.

--rewrap moves each account's DEK from an older wrap to the current one. The
DEK itself does not change, so no row, receipt or backup is re-encrypted. It
commits one account at a time: interrupted, run it again and it carries on.
Run it only AFTER the restart - an app still running on the old .env cannot
open a DEK wrapped under a version it has not loaded, and its users would be
unable to sign in until it restarts.

NEVER REMOVE A RETIRED KEY while a backup made before the rotation might be
needed: a .budgetbak carries the wrap it was written with, and only that
version's key opens it.

What rotation does not do: lock out anyone who already unwrapped a DEK. After
a leaked .env, rotate the master key first, then have every user rotate their
own key (Settings -> Rotate my encryption key). FEATURES.md §17.
"""

import argparse
import base64
import os
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ENV_FILE = ROOT / ".env"
MAX_VERSION = 255


class RotationError(Exception):
    """.env is not in a state a rotation can safely start from."""


def _get(text: str, name: str):
    match = re.search(rf"^{name}=(.*)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _set(text: str, name: str, value: str) -> str:
    line = f"{name}={value}"
    pattern = re.compile(rf"^{name}=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda _: line, text, count=1)
    return text.rstrip("\n") + "\n" + line + "\n"


def plan_new_env(text: str, new_key: str):
    """(new .env text, old version, new version) for a fresh key. Pure - touches no file."""
    old_key = _get(text, "BUDGET_MASTER_KEY")
    if not old_key:
        raise RotationError("BUDGET_MASTER_KEY is empty - there is nothing to rotate")
    if new_key == old_key:
        raise RotationError("the new key is the old key")
    raw_version = _get(text, "BUDGET_KEY_VERSION") or "1"
    if not raw_version.isdigit():
        raise RotationError("BUDGET_KEY_VERSION is not a number")
    old_version = int(raw_version)
    new_version = old_version + 1
    if new_version > MAX_VERSION:
        raise RotationError(f"key versions stop at {MAX_VERSION}")

    retired = [entry.strip() for entry in (_get(text, "BUDGET_RETIRED_KEYS") or "").split(",") if entry.strip()]
    taken = {entry.partition(":")[0].strip() for entry in retired}
    if str(old_version) in taken or str(new_version) in taken:
        raise RotationError("BUDGET_RETIRED_KEYS already lists the current or next version - fix .env by hand first")
    retired.append(f"{old_version}:{old_key}")

    text = _set(text, "BUDGET_MASTER_KEY", new_key)
    text = _set(text, "BUDGET_KEY_VERSION", str(new_version))
    text = _set(text, "BUDGET_RETIRED_KEYS", ",".join(retired))
    return text, old_version, new_version


def write_atomically(path: Path, text: str) -> None:
    partial = path.with_name(path.name + ".rotating")
    partial.write_text(text, encoding="utf-8")
    os.replace(partial, path)  # never a half-written .env


def rewrap_all(session, keyring, *, dry_run: bool) -> dict:
    """
    Move every DEK not under the current version. A dry run proves each old
    wrap still opens and changes nothing. Each account commits on its own.
    """
    from sqlalchemy import select

    from app.core.crypto.dek import wrapped_key_version, zero
    from app.core.crypto.errors import DecryptionError, KeyNotAvailableError
    from app.db.models import User
    from app.db.repositories.user_repository import UserRepository

    users = UserRepository(session)
    result = {"moved": 0, "pending": 0, "current": 0, "failed": []}
    for user_id in session.execute(select(User.id).order_by(User.id)).scalars().all():
        user = users.get(user_id)
        if wrapped_key_version(bytes(user.dek_wrapped)) == keyring.current_version:
            result["current"] += 1
            continue
        try:
            if dry_run:
                zero(users.unwrap_dek(user, keyring))
                result["pending"] += 1
                continue
            users.rewrap_dek(user, keyring)
            session.commit()
            result["moved"] += 1
        except (DecryptionError, KeyNotAvailableError):
            session.rollback()
            result["failed"].append(user_id)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--status", action="store_true", help="which key version wraps each account")
    action.add_argument("--new-key", action="store_true", help="put a new master key in .env, retiring the old")
    action.add_argument("--rewrap", action="store_true", help="re-wrap every DEK under the current key")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--env", default=str(ENV_FILE), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.new_key:
        path = Path(args.env)
        if not path.is_file():
            print(f"No .env at {path}", file=sys.stderr)
            return 1
        new_key = base64.b64encode(secrets.token_bytes(32)).decode()
        try:
            text, old_version, new_version = plan_new_env(path.read_text(encoding="utf-8"), new_key)
        except RotationError as exc:
            print(f"Not rotated: {exc}", file=sys.stderr)
            return 1
        if args.dry_run:
            print(f"[dry run] would make version {new_version} the master key and retire version "
                  f"{old_version} into BUDGET_RETIRED_KEYS. .env is unchanged.")
            return 0
        write_atomically(path, text)

        from app.core.fingerprints import fingerprint

        print(f"Version {new_version} is now the master key in {path}; version {old_version} is retired, not lost.")
        print(f"New key fingerprint: {fingerprint('BUDGET_MASTER_KEY', new_key)}")
        print("\nNext, in this order:")
        print("  1. Restart the app, so it loads the new key.")
        print("  2. python scripts/rotate_keys.py --rewrap --dry-run, then --rewrap")
        print("  3. Replace the offline copy of .env TODAY and check it: scripts/env_fingerprint.py --compare")
        return 0

    os.chdir(ROOT)
    from app.core.crypto.keyring import get_master_keyring
    from app.db.repositories.user_repository import UserRepository
    from app.db.session import get_session

    keyring = get_master_keyring()
    session = get_session()
    try:
        if args.status:
            versions = UserRepository(session).wrap_versions()
            print(f"Master key version {keyring.current_version} is current; versions loaded: {list(keyring.versions)}")
            print("Accounts by the version wrapping their key: "
                  + (", ".join(f"v{v}: {n}" for v, n in versions.items()) or "none"))
            behind = sum(n for v, n in versions.items() if v != keyring.current_version)
            if behind:
                print(f"{behind} account(s) still wrapped under an older key - run --rewrap.")
            return 0

        result = rewrap_all(session, keyring, dry_run=args.dry_run)
    finally:
        session.close()

    if args.dry_run:
        print(f"[dry run] {result['pending']} to re-wrap, {result['current']} already current. Nothing changed.")
    else:
        print(f"Re-wrapped {result['moved']}; {result['current']} were already current.")
    if result["failed"]:
        print(f"Could not open the key of account(s) {result['failed']} with the loaded master keys. "
              "Is the right key in BUDGET_RETIRED_KEYS, and was the app restarted?", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
