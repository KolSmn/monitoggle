"""The app version: the latest git tag, as reported by `git describe`.

- Built executables: build.py writes the version into _build_version.py
  (generated, gitignored) right before PyInstaller runs.
- From source (a git checkout): asked from git at runtime, e.g.
  "v1.4.0", or "v1.4.0-3-g72dbbd0-dirty" for 3 commits past the tag with
  uncommitted changes.
- Installed as a package (pip/uv, no git checkout, or git failing): the
  version hatch-vcs recorded in the package metadata, e.g. "v1.4.0".
"""

from __future__ import annotations

import functools
import subprocess
import sys
from importlib import metadata
from pathlib import Path

UNKNOWN = "unknown"
DISTRIBUTION = "monitoggle"  # the project name in pyproject.toml

# src/monitoggle/version.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[2]


def describe(cwd: Path) -> str | None:
    """`git describe` for the repository at cwd, or None without git/tags."""
    # No console window flashing up when called from the windowed GUI.
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        # git via PATH on purpose: it is wherever the developer installed it.
        result = subprocess.run(  # nosec B607
            ["git", "describe", "--tags", "--dirty", "--always"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


@functools.cache
def get_version() -> str:
    try:
        from ._build_version import VERSION  # type: ignore[import-not-found]
    except ImportError:
        pass
    else:
        return VERSION
    if (REPO_ROOT / ".git").exists() and (found := describe(REPO_ROOT)):
        return found
    return installed_version() or UNKNOWN


def installed_version() -> str | None:
    """The version recorded when the package was installed (hatch-vcs, from
    the git tag at build time), e.g. "v1.4.0"; None if not installed."""
    try:
        found = metadata.version(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return None
    # pyproject.toml's fallback-version: built without tags.
    return None if found == "0.0.0" else f"v{found}"
