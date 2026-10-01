"""Download all files of the latest GitHub release into dist/.

    uv run python download_latest_release.py            # latest release
    uv run python download_latest_release.py v1.4.0     # a specific tag
    uv run python download_latest_release.py --repo OWNER/NAME

Public repositories are accessed without a token first (the API allows 60
requests per hour then). For a private one, or past that limit, the token
in the GITHUB_TOKEN_MONITOGGLE environment variable is used (fine-grained
token, repository permission "Contents: Read-only").

Existing files with the same name in dist/ are replaced. The release notes
are saved next to the files as RELEASE_NOTES.md.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from github import Auth, Github
from github.GithubException import GithubException

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
DEFAULT_REPO = "KolSmn/monitoggle"
# The name of the environment variable holding the token, not a secret.
TOKEN_VARIABLE = "GITHUB_TOKEN_MONITOGGLE"  # nosec B105
CHUNK_SIZE = 1024 * 1024  # PyGithub's default of 1 byte is very slow


def connect(repo_name: str) -> Github:
    """A GitHub connection that can see the repository: without a token
    first (enough for a public one), else with the token."""
    github = Github()
    try:
        github.get_repo(repo_name)
        return github
    except GithubException as exc:
        # 404: GitHub hides private repos from anonymous access;
        # 403: e.g. the anonymous rate limit. Anything else is a real error.
        github.close()
        token = os.environ.get(TOKEN_VARIABLE)
        if exc.status not in (403, 404) or not token:
            raise
    print(f"note: {repo_name} needs authentication, using {TOKEN_VARIABLE}")
    return Github(auth=Auth.Token(token))


def download(repo_name: str, tag: str | None, target: Path) -> list[Path]:
    github = connect(repo_name)
    try:
        return _download(github, repo_name, tag, target)
    finally:
        github.close()


def _download(
    github: Github, repo_name: str, tag: str | None, target: Path
) -> list[Path]:
    repo = github.get_repo(repo_name)
    # get_latest_release(): the newest release that is neither a draft nor
    # marked as pre-release.
    release = repo.get_release(tag) if tag else repo.get_latest_release()
    title = release.name or release.tag_name

    assets = list(release.get_assets())
    print(f"{repo_name} {release.tag_name} ({title}): {len(assets)} file(s)")
    target.mkdir(parents=True, exist_ok=True)

    downloaded: list[Path] = []
    for asset in assets:
        path = target / asset.name
        # Download under a temporary name first, so an interrupted download
        # never leaves a truncated file under the real name.
        partial = path.with_name(path.name + ".part")
        print(f"  {asset.name} ({asset.size / 1024 / 1024:.1f} MB)")
        asset.download_asset(str(partial), chunk_size=CHUNK_SIZE)
        partial.replace(path)
        if sys.platform != "win32" and not path.suffix:
            path.chmod(0o755)  # Linux executables
        downloaded.append(path)

    notes = target / "RELEASE_NOTES.md"
    notes.write_text(
        f"# {title}\n\n{release.body or ''}\n",
        encoding="utf-8",
    )
    downloaded.append(notes)
    return downloaded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tag", nargs="?", help="Release tag (default: latest release)")
    parser.add_argument(
        "--repo", default=DEFAULT_REPO, help=f"OWNER/NAME (default: {DEFAULT_REPO})"
    )
    args = parser.parse_args()

    try:
        files = download(args.repo, args.tag, DIST)
    except GithubException as exc:
        # 404 also means "no access": GitHub hides private repos from
        # tokens without permission for them.
        print(f"error: GitHub answered {exc.status}: {exc.data}", file=sys.stderr)
        return 1
    print(f"Done: {len(files)} file(s) in {DIST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
