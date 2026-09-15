"""
Build the folder you copy to the server - exactly the committed files, nothing else.

    python scripts/make_release.py

Writes release/zbdgt-<commit>.zip from the last COMMIT (git archive), so it can
never carry .env, uploads/, backups/, logs/, .venv/, node_modules/ or an
uncommitted edit. It refuses while there are uncommitted changes, because they
would silently not be in the zip - commit (with a fresh `npm run build` in
app/web/static/dist/) first.

On the server (misc/how-to-run.txt, DEPLOY): replace app/, alembic/, scripts/
and the top-level files from the zip; NEVER delete .env, uploads/, backups/ or
logs/ there.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = ROOT / "release"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def main() -> int:
    try:
        dirty = git("status", "--porcelain", "--untracked-files=no")
        commit = git("rev-parse", "--short", "HEAD")
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"git is not available here: {exc}", file=sys.stderr)
        return 1
    if dirty:
        print("There are uncommitted changes; they would not be in the release. Commit first:\n" + dirty,
              file=sys.stderr)
        return 1

    RELEASE_DIR.mkdir(exist_ok=True)
    target = RELEASE_DIR / f"zbdgt-{commit}.zip"
    git("archive", "--format=zip", f"--output={target}", "HEAD")
    size_kb = target.stat().st_size // 1024
    print(f"Wrote {target.relative_to(ROOT)} ({size_kb} KB) from commit {commit}.")
    print("Copy it to the server and follow misc/how-to-run.txt - DEPLOY. Keep the server's .env, "
          "uploads/, backups/ and logs/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
