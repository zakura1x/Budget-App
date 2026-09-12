"""
Create the FIRST account, so that yours does not have to be the admin one.

    python scripts/create_admin_account.py

FIRST_USER_IS_ADMIN makes account number one the administrator. If you would
rather your own account were an ordinary user, this takes that slot: it
creates a placeholder account with a generated password, and writes its
credentials - and its recovery phrase, which is shown exactly once - to
`admin-account.txt` in the repository root. That file is in .gitignore and
must stay there.

It REFUSES to run once any account exists. Its whole purpose is to be first;
a second run would just consume one of your MAX_USERS slots.

Being admin buys very little here by design (ARCHITECTURE.md 13.2): there is
no admin key, so the administrator cannot read anybody else's rows. What it
does carry is whatever administrative screens later phases add.
"""

import os
import secrets
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

OUTPUT = ROOT / "admin-account.txt"
EMAIL = "admin@zbdgt.local"
DISPLAY_NAME = "Administrator"


def make_password(length: int = 24) -> str:
    """Random, and certain to satisfy the policy rather than hoping it does."""
    symbols = "!@#$%^&*-_=+?"
    pools = [string.ascii_uppercase, string.ascii_lowercase, string.digits, symbols]
    chars = [secrets.choice(pool) for pool in pools]
    everything = "".join(pools)
    chars += [secrets.choice(everything) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def main() -> int:
    from app.core.config import settings
    from app.core.exceptions import AppException
    from app.db.repositories.user_repository import UserRepository
    from app.db.session import session_scope
    from app.services.auth_service.registration_service import create_account

    if OUTPUT.exists():
        print(f"{OUTPUT.name} already exists. Move it aside first.", file=sys.stderr)
        return 1

    password = make_password()

    try:
        with session_scope() as session:
            if UserRepository(session).count() > 0:
                print(
                    "This installation already has an account, so the admin slot is taken.\n"
                    "Nothing was created.",
                    file=sys.stderr,
                )
                return 1
            account = create_account(
                session, email=EMAIL, password=password, display_name=DISPLAY_NAME
            )
    except AppException as exc:
        print(f"Not created: {exc.detail or exc.title}", file=sys.stderr)
        return 1

    OUTPUT.write_text(
        "\n".join([
            "ZBDGT - placeholder administrator account",
            "=" * 60,
            "",
            "Created to occupy the FIRST_USER_IS_ADMIN slot so that your own",
            "account, created next through the sign-up screen, is an ordinary",
            "user. There is nothing in it and nothing needs to be.",
            "",
            f"Created   {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
            f"Database  {settings.DB_NAME}, schema {settings.DB_SCHEMA}",
            f"User id   {account.user_id}",
            f"Admin     {account.is_admin}",
            "",
            "Email     " + EMAIL,
            "Password  " + password,
            "",
            "Recovery phrase (shown once, stored nowhere on the server):",
            "  " + account.recovery_phrase,
            "",
            "=" * 60,
            "This file is gitignored. It is as sensitive as the account is:",
            "either the password or the phrase opens it. If you do not want",
            "the file on this machine, copy what you need elsewhere and",
            "delete it - nothing in the app reads it.",
            "",
        ]),
        encoding="utf-8",
    )

    print(f"Account {account.user_id} created (admin={account.is_admin}).")
    print(f"Credentials and recovery phrase written to {OUTPUT.name} (gitignored).")
    print("Your own account is next - sign up through the app; it will be an ordinary user.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
