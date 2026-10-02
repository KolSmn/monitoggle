"""Runs DDC/CI work off the GUI thread and reports back through Qt signals."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from PySide6.QtCore import QObject, Signal

from .. import APP_NAME
from .commands import CommandResult, run_command
from .monitor_state import snapshot

logger = logging.getLogger(APP_NAME)


class _Bridge(QObject):
    # Emitted from the worker thread; Qt queues them into the GUI thread.
    status_ready = Signal(object)  # list[MonitorState] | None
    command_done = Signal(object)  # CommandResult


class Worker:
    """Runs DDC/CI work off the GUI thread, one job at a time (so commands
    and status queries never talk to a monitor concurrently)."""

    def __init__(self) -> None:
        self.bridge = _Bridge()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ddc")
        self._refresh_pending = False

    def refresh(self) -> None:
        if self._refresh_pending:
            return
        self._refresh_pending = True
        self._pool.submit(self._refresh)

    def _refresh(self) -> None:
        self._refresh_pending = False
        try:
            states = snapshot()
        except Exception:
            logger.exception("Could not query monitors.")
            states = None
        self.bridge.status_ready.emit(states)

    def run(self, command: str) -> None:
        self._pool.submit(self._run, command)

    def _run(self, command: str) -> None:
        try:
            result = run_command(command)
        except Exception as exc:
            logger.exception("Command failed: %s", command)
            result = CommandResult(command, 1, errors=[str(exc) or type(exc).__name__])
        self.bridge.command_done.emit(result)

    def call(self, fn: Callable[[], object], timeout: float | None) -> object:
        """Runs fn in the queue like any job. With a timeout, blocks until it
        is done and returns its result (None on timeout or error); without,
        returns right away and refreshes the status afterwards."""
        try:
            future = self._pool.submit(self._guarded, fn)
        except RuntimeError:  # already shut down
            return None
        if timeout is None:
            future.add_done_callback(lambda _f: self.refresh())
            return None
        try:
            return future.result(timeout=timeout)
        except FutureTimeout:
            logger.warning("%s did not finish within %s s.", fn.__name__, timeout)
            return None

    @staticmethod
    def _guarded(fn: Callable[[], object]) -> object:
        try:
            return fn()
        except Exception:
            logger.exception("%s failed.", fn.__name__)
            return None

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
