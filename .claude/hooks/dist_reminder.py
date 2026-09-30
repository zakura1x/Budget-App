"""Stop hook: don't finish a turn with frontend source newer than the bundle.

Invariant 9 - the server has no npm, so app/web/static/dist/ is committed and
must be rebuilt whenever frontend source changes. If an uncommitted file under
frontend/src/ (tests aside) is newer than dist/.vite/manifest.json, Claude is
sent back once to run `npm run build`.
"""

import json
import os
import subprocess
import sys

MANIFEST = os.path.join("app", "web", "static", "dist", ".vite", "manifest.json")


def main() -> None:
    data = json.load(sys.stdin)
    if data.get("stop_hook_active"):
        return  # already sent back once this turn; don't loop
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", "frontend/src"],
            cwd=root, capture_output=True, text=True, timeout=30,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return
    changed = []
    for line in status.splitlines():
        rel = line[3:].strip().strip('"')
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
        if rel.startswith("frontend/src/tests/"):
            continue
        full = os.path.join(root, rel)
        if os.path.isfile(full):
            changed.append((os.path.getmtime(full), rel))
    if not changed:
        return
    manifest = os.path.join(root, MANIFEST)
    built = os.path.getmtime(manifest) if os.path.isfile(manifest) else 0
    stale = sorted(rel for mtime, rel in changed if mtime > built)
    if stale:
        listed = "\n".join(f"  {rel}" for rel in stale[:10])
        more = f"\n  ...and {len(stale) - 10} more" if len(stale) > 10 else ""
        print(json.dumps({
            "decision": "block",
            "reason": (
                "Frontend source changed after the last build (invariant 9):\n"
                f"{listed}{more}\n"
                "Run `npm run build` in frontend/ so app/web/static/dist/ matches, "
                "or say why the build is not needed."
            ),
        }))


if __name__ == "__main__":
    main()
