"""
Check the offline copy of .env against the server's, without showing a secret (SEC-31).

    python scripts/env_fingerprint.py                              fingerprints of ./.env
    python scripts/env_fingerprint.py E:\\budget\\.env              fingerprints of a copy
    python scripts/env_fingerprint.py --compare E:\\budget\\.env    ./.env against the copy

Run the first form on the server and the second on the copy and compare the
lines, or put both files on one machine and use --compare, which checks every
setting. Admin -> status shows the same fingerprints for the keys the running
app has loaded.

A fingerprint is a short hash: it shows two copies hold the same key and cannot
be turned back into the key. Passwords and the registration code are never
hashed for display - --compare only says whether they match.

Needs no database and no valid config: it only reads the files. Exit code 2
means the files differ.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", nargs="?", default=str(ROOT / ".env"))
    parser.add_argument("--compare", metavar="OTHER", help="another .env to compare setting by setting")
    args = parser.parse_args(argv)

    from app.core.fingerprints import compare, fingerprints, parse_env

    first = Path(args.file)
    if not first.is_file():
        print(f"No file at {first}", file=sys.stderr)
        return 1
    ours = parse_env(first.read_text(encoding="utf-8"))

    if args.compare:
        second = Path(args.compare)
        if not second.is_file():
            print(f"No file at {second}", file=sys.stderr)
            return 1
        result = compare(ours, parse_env(second.read_text(encoding="utf-8")))
        width = max((len(name) for name in result), default=0)
        print(f"# first:  {first}\n# second: {second}")
        for name, verdict in result.items():
            print(f"{name:<{width}}  {verdict}")
        differ = [name for name, verdict in result.items() if verdict != "same"]
        if differ:
            print(f"\n{len(differ)} setting(s) differ - one of these files is not current.")
            return 2
        print("\nThe two files match.")
        return 0

    print(f"# {first}")
    for name, value in fingerprints(ours).items():
        print(f"{name:<26} {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
