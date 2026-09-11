"""
Create an account from the command line - the first one, usually.

    python scripts/bootstrap_user.py

Asks for an email, display name and password, creates the user with its own
DEK, wraps that DEK under the master key AND under a freshly generated 12-word
recovery phrase, writes the encrypted preferences row, and shows the phrase
ONCE.

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

    words = account.recovery_phrase.split()
    print(f"\nAccount {account.user_id} created{' (admin)' if account.is_admin else ''}.\n")
    print("=" * 64)
    print("  YOUR RECOVERY PHRASE - shown once, never stored anywhere")
    print("=" * 64)
    for i in range(0, len(words), 3):
        print("   " + "".join(f"{n:>2}. {w:<12}" for n, w in enumerate(words[i:i + 3], start=i + 1)))
    print("=" * 64)
    print(
        "  Write these on PAPER. Keep them away from this machine and away\n"
        "  from your .env backup. Either one opens all of your data - keeping\n"
        "  them together defeats the point of having two. Lose both and the\n"
        "  data is gone, permanently, for everyone.\n"
    )
    input("Press Enter once the words are written down. The screen will be cleared. ")
    os.system("cls" if os.name == "nt" else "clear")
    print(f"Account {account.user_id} is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
