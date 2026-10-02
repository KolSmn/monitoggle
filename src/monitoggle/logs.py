"""Logging setup shared by the CLI and the tray app: a rotating log file,
optionally mirrored to stdout (up to INFO) and stderr (WARNING and above)."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from . import APP_NAME, storage

LOG_DIR = storage.state_dir()
LOG_FILE = LOG_DIR / f"{APP_NAME}.log"

LOG_LEVEL = logging.INFO
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


class _MaxLevelFilter(logging.Filter):
    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


def configure_logging(console: bool = True) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(LOG_LEVEL)
    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(LOG_LEVEL)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if not console:
        return

    # LOG_LEVEL through INFO (tables, status messages) -> stdout
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(LOG_LEVEL)
    stdout_handler.addFilter(_MaxLevelFilter(logging.INFO))
    stdout_handler.setFormatter(formatter)
    root.addHandler(stdout_handler)

    # WARNING and above (warnings, errors) -> stderr
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)
