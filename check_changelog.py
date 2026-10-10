"""Check that CHANGELOG.md has an entry for a release tag.

    python check_changelog.py v1.4.0               # CHANGELOG.md of HEAD
    python check_changelog.py v1.4.0 --rev <sha>   # ... of another commit

Only final tags (vX.Y.Z) need an entry, a "## [vX.Y.Z] - YYYY-MM-DD"
section; dev tags (vX.Y.Z.devN) and other tags pass without one. The file
is read from the commit through git, not from the working tree, so an
uncommitted entry doesn't count.

Used by CI on tag pushes, and by the reference-transaction hook in
.githooks/ before git creates a tag.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

# As in cleanup_dev_releases.py.
FINAL_TAG = re.compile(r"^v(\d+(?:\.\d+)*)$")


def needs_entry(tag: str) -> bool:
    return FINAL_TAG.match(tag) is not None


def has_entry(tag: str, changelog: str) -> bool:
    heading = rf"^## \[{re.escape(tag)}\] - \d{{4}}-\d{{2}}-\d{{2}}[ \t\r]*$"
    return re.search(heading, changelog, re.MULTILINE) is not None


def _changelog_at(rev: str) -> str:
    # git from PATH; ^{} peels an annotated tag to its commit.
    result = subprocess.run(  # nosec B607
        ["git", "show", f"{rev}^{{}}:CHANGELOG.md"],
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    return result.stdout.decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tag", help="tag name, e.g. v1.4.0")
    parser.add_argument(
        "--rev", default="HEAD", help="commit or tag object to read CHANGELOG.md from"
    )
    args = parser.parse_args()

    if not needs_entry(args.tag):
        print(f"{args.tag}: not a final release tag, no changelog entry needed.")
        return 0
    try:
        changelog = _changelog_at(args.rev)
    except subprocess.CalledProcessError as exc:
        print(
            f"error: can't read CHANGELOG.md at {args.rev}:\n"
            f"{exc.stderr.decode(errors='replace')}",
            file=sys.stderr,
        )
        return 1
    if not has_entry(args.tag, changelog):
        print(
            f"error: CHANGELOG.md has no '## [{args.tag}] - YYYY-MM-DD' section "
            f"(in {args.rev}). Add it and commit before tagging.",
            file=sys.stderr,
        )
        return 1
    print(f"{args.tag}: CHANGELOG.md has an entry.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
