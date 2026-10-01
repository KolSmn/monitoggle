"""Delete obsolete dev releases and their tags on GitHub.

    python cleanup_dev_releases.py --dry-run    # only show what would go
    python cleanup_dev_releases.py

A dev tag vX.Y.Z.devN is obsolete if the final vX.Y.Z is released, or if
a newer vX.Y.Z.devM (M > N) is released. So per version only the newest
dev release survives, and only until the final release is out.

Only published releases count, not bare tags or drafts: a tag whose build
failed (or is still running) has no release yet, so it never makes an
older, working release obsolete. Such tags are kept too, until a newer
release of the same version exists.

Uses the GitHub CLI (`gh`), for the repository in GITHUB_REPOSITORY or,
without it, the one of the current directory. The token needs
"Contents: Read and write".
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Iterable

DEV_TAG = re.compile(r"^v(\d+(?:\.\d+)*)\.dev(\d+)$")
FINAL_TAG = re.compile(r"^v(\d+(?:\.\d+)*)$")


def _version(text: str) -> tuple[int, ...]:
    parts = [int(p) for p in text.split(".")]
    while len(parts) > 1 and parts[-1] == 0:  # 1.2 == 1.2.0
        parts.pop()
    return tuple(parts)


def obsolete_dev_tags(tags: Iterable[str], released: Iterable[str]) -> list[str]:
    """The dev tags to delete, sorted by version.

    tags: all tags; released: the tags that have a published release.
    """
    released = set(released)
    finals: set[tuple[int, ...]] = set()
    devs: dict[tuple[int, ...], list[tuple[int, str]]] = {}
    for tag in set(tags) | released:
        if m := FINAL_TAG.match(tag):
            if tag in released:
                finals.add(_version(m[1]))
        elif m := DEV_TAG.match(tag):
            devs.setdefault(_version(m[1]), []).append((int(m[2]), tag))

    obsolete: list[str] = []
    for version in sorted(devs):
        numbered = sorted(devs[version])
        if version in finals:
            obsolete += [tag for _, tag in numbered]
            continue
        newest = max((n for n, tag in numbered if tag in released), default=None)
        if newest is not None:
            obsolete += [tag for n, tag in numbered if n < newest]
    return obsolete


def _gh(*args: str) -> str:
    # The GitHub CLI from PATH, as on the Actions runners.
    result = subprocess.run(  # nosec B607
        ["gh", *args], check=True, capture_output=True, text=True
    )
    return result.stdout


def _repo() -> str:
    return os.environ.get("GITHUB_REPOSITORY") or _gh(
        "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="only list what would be deleted"
    )
    args = parser.parse_args()

    repo = _repo()
    tags = _gh("api", "--paginate", f"repos/{repo}/tags", "--jq", ".[].name").split()
    releases = set(
        _gh(
            "release", "list", "--repo", repo, "--limit", "1000",
            "--json", "tagName", "--jq", ".[].tagName",
        ).split()
    )
    # Drafts are no working release yet (but are deleted with their tag).
    published = set(
        _gh(
            "release", "list", "--repo", repo, "--limit", "1000", "--exclude-drafts",
            "--json", "tagName", "--jq", ".[].tagName",
        ).split()
    )

    obsolete = obsolete_dev_tags(tags, published)
    if not obsolete:
        print("No obsolete dev releases.")
        return 0

    for tag in obsolete:
        kind = "release and tag" if tag in releases else "tag"
        if args.dry_run:
            print(f"Would delete {kind} {tag}")
            continue
        print(f"Deleting {kind} {tag}")
        if tag in releases:
            _gh("release", "delete", tag, "--repo", repo, "--cleanup-tag", "--yes")
        else:
            _gh("api", "--method", "DELETE", f"repos/{repo}/git/refs/tags/{tag}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(f"error: {' '.join(exc.cmd)} failed:\n{exc.stderr}", file=sys.stderr)
        sys.exit(1)
