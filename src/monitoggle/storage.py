"""Per-user files: where they live, and reading/writing them as JSON
(Qt-free; shared by the CLI and the tray app)."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from . import APP_NAME

logger = logging.getLogger(__name__)


def xdg_dir(variable: str, fallback: str) -> Path:
    """An XDG base directory, e.g. xdg_dir("XDG_CONFIG_HOME", ".config")."""
    return Path(os.environ.get(variable) or Path.home() / fallback)


def config_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", ".")) / APP_NAME
    return xdg_dir("XDG_CONFIG_HOME", ".config") / APP_NAME


def read_json(path: Path) -> dict:
    """The JSON object stored at path; empty if the file is missing or
    unusable (logged), so the caller falls back to its defaults."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logger.exception("Could not read %s, using defaults.", path)
        return {}
    if not isinstance(data, dict):
        logger.error("Unexpected content in %s, using defaults.", path)
        return {}
    return data


def write_json(path: Path, data: dict) -> None:
    """Writes data to path atomically (never leaves a half-written file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)
