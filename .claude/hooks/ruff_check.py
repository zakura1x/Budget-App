"""PostToolUse hook: run `ruff check` on a .py file right after it is written.

Lint findings go back to Claude as a block reason so they are fixed in the
same turn, instead of surfacing at the next `ruff check app tests`.
"""

import json
import os
import subprocess
import sys

# The classic ruff defaults the code was written against. ruff 0.16 widened
# its default set (I, UP, RUF, B...), which reports ~1800 findings on code
# that predates it - pinned here so the hook flags new mistakes, not history.
RULES = "E4,E7,E9,F"

def main() -> None:
    data = json.load(sys.stdin)
    path = (data.get("tool_input") or {}).get("file_path") or ""
    if not path.endswith(".py") or not os.path.isfile(path):
        return
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    ruff = os.path.join(root, ".venv", "Scripts", "ruff.exe")
    if not os.path.isfile(ruff):
        ruff = "ruff"
    try:
        result = subprocess.run(
            [ruff, "check", "--quiet", "--select", RULES, path],
            cwd=root, capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip()
        print(json.dumps({
            "decision": "block",
            "reason": f"ruff check found problems in {path}:\n{output}",
        }))


if __name__ == "__main__":
    main()
