"""PreToolUse hook: refuse Write/Edit on files that hold real keys or real money.

.env carries BUDGET_MASTER_KEY (invariant 8; losing it loses every account),
and uploads/, backups/ and budget_app_backup/ hold real finances. DEPLOY.md
lists the first three as the server folders a deploy must never touch.
"""

import json
import os
import sys

PROTECTED_DIRS = ("budget_app_backup/", "uploads/", "backups/")
PROTECTED_FILES = ("admin-account.txt",)
ALLOWED = (".env.example",)


def reason_for(rel: str) -> str | None:
    name = rel.rsplit("/", 1)[-1]
    if name in ALLOWED:
        return None
    if name == ".env" or name.startswith(".env."):
        return f"{rel} holds the master key and secrets - edit it by hand."
    if name.endswith((".key", ".pem")):
        return f"{rel} is key material - edit it by hand."
    if rel in PROTECTED_FILES:
        return f"{rel} holds the admin account's password - edit it by hand."
    for folder in PROTECTED_DIRS:
        if rel.startswith(folder):
            return f"{folder} holds real finances - Claude may not write there."
    return None


def main() -> None:
    data = json.load(sys.stdin)
    path = (data.get("tool_input") or {}).get("file_path") or ""
    if not path:
        return
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    full = os.path.normcase(os.path.abspath(path))
    base = os.path.normcase(os.path.abspath(root))
    if not full.startswith(base + os.sep):
        return
    rel = full[len(base) + 1 :].replace("\\", "/")
    reason = reason_for(rel)
    if reason:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }))


if __name__ == "__main__":
    main()
