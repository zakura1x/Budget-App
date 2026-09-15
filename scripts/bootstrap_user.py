"""
Create an account from the command line - the first one, usually.

    python scripts/bootstrap_user.py

Asks for an email, display name and password, creates the user with its own
DEK wrapped under the master key, and writes the encrypted preferences row.

Runs on the server with direct database access, so it skips the registration
code (whoever can run this can already read .env). MAX_USERS still applies,
and the first account becomes admin when FIRST_USER_IS_ADMIN is set.
"""

import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def main() -> int:
    from app.core.config import settings
    from app.core.exceptions import AppException
    from app.db.session import session_scope
    from app.services.auth_service.registration_service import create_account

    print(f"Create an account - database {settings.DB_NAME}, schema {settings.DB_SCHEMA}\n")
    email = input("Email: ").strip()
    display_name = input("Display name (optional): ").strip() or None
    password = getpass.getpass("Password: ")
    if getpass.getpass("Password again: ") != password:
        print("Passwords do not match. Nothing was created.", file=sys.stderr)
        return 1

    try:
        with session_scope() as session:
            account = create_account(session, email=email, password=password, display_name=display_name)
    except AppException as exc:
        print(f"Not created: {exc.detail or exc.title}", file=sys.stderr)
        return 1

    print(f"\nAccount {account.user_id} created{' (admin)' if account.is_admin else ''}.")
    print("Its key is wrapped under the master key in .env - keep the offline copy of .env current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
