"""Runs CLI commands in-process and collects what they report (Qt-free)."""

from __future__ import annotations

import argparse
import logging
import shlex
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .. import APP_NAME, CLI_NAME, cli, core
from ..models import ALL, PRIMARY, Monitor, MonitorRef
from ..monitor_settings import MonitorSettings, MonitorSettingsFile, is_input_source
from .i18n import tr, tr_template

logger = logging.getLogger(APP_NAME)


def split_command(command: str) -> list[str]:
    # Plain whitespace split instead of shlex: Windows device names such as
    # \\.\DISPLAY2 would lose their backslashes, and no argument ever
    # contains a space.
    return command.split()


class InvalidCommand(ValueError):
    """A command line that can't run; str() is the translated reason."""


def parse_command(
    command: str, settings: MonitorSettingsFile | None = None
) -> argparse.Namespace:
    """The parsed CLI command line; raises InvalidCommand if it isn't valid.
    settings: the monitor names to check against (default: the saved ones)."""
    argv = split_command(command)
    if not argv:
        raise InvalidCommand(tr("Command is empty."))
    try:
        return cli.parse_command(argv, settings)
    except cli.CommandLineError as exc:
        # argparse's own wording has no translations; it goes in as detail.
        raise InvalidCommand(tr("Invalid command: {detail}", detail=exc)) from None
    except SystemExit:  # --help / --version
        raise InvalidCommand(tr("Not a runnable command.")) from None


def validate_command(
    command: str, settings: MonitorSettingsFile | None = None
) -> str | None:
    """Error message (translated) if command is not a valid CLI command line
    (see parse_command)."""
    try:
        parse_command(command, settings)
    except InvalidCommand as exc:
        return str(exc)
    return None


def cli_executable() -> str:
    """How to invoke the CLI, for commands the user binds outside this app."""
    # Built executables: the CLI sits next to the tray app, named like it
    # with "-cli" after the app name (monitoggle-windows-x86_64.exe ->
    # monitoggle-cli-windows-x86_64.exe). Installed from source: the script.
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        rest = exe.name[len(APP_NAME):] if exe.name.lower().startswith(APP_NAME) else exe.suffix
        sibling = exe.with_name(CLI_NAME + rest)
        return str(sibling) if sibling.exists() else sibling.name
    return CLI_NAME


def cli_command_line(command: str) -> str:
    argv = [cli_executable(), *split_command(command)]
    if sys.platform == "win32":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


@dataclass
class CommandResult:
    command: str
    exit_code: int
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.errors


class _Capture(logging.Handler):
    """Collects the log records one thread emits while a command runs,
    translated for display (the log file itself stays English).
    """

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.thread_id = threading.get_ident()
        self.messages: list[str] = []
        self.errors: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread != self.thread_id:
            return
        if isinstance(record.msg, str):
            text = tr_template(record.msg, record.args)
        else:
            text = record.getMessage()
        if record.levelno >= logging.WARNING:
            self.errors.append(text)
        else:
            self.messages.append(text)


def run_command(command: str) -> CommandResult:
    """Runs a CLI command line in-process, exactly as the CLI would."""
    try:
        args = parse_command(command)
    except InvalidCommand as exc:
        return CommandResult(command, 2, errors=[str(exc)])

    logger.info("GUI invocation: %s", command)
    capture = _Capture()
    root = logging.getLogger()
    root.addHandler(capture)
    try:
        code = cli.run_args(args)
    finally:
        root.removeHandler(capture)
    return CommandResult(command, code, capture.messages, capture.errors)


@dataclass
class MonitorState(MonitorRef):
    name: str
    number: int | None
    primary: bool
    width: int
    height: int
    has_ddc: bool
    on: bool | None  # None: unknown (no DDC/CI, or the query failed)
    input: int | None = None  # current input source, None: unknown
    inputs: list[int] = field(default_factory=list)  # supported; empty: unknown
    settings: MonitorSettings = field(default_factory=MonitorSettings)

    @property
    def ref(self) -> str:
        """Token that addresses this monitor in a command."""
        if self.settings.name:
            return self.settings.name
        return str(self.number) if self.number is not None else self.name

    @property
    def device_label(self) -> str:
        """E.g. "2: DP-2 (2560\u00d71440) \u2605" (without the user-given name)."""
        parts = [f"{self.number}:" if self.number is not None else "", self.name]
        if self.width and self.height:
            parts.append(f"({self.width}\u00d7{self.height})")
        if self.primary:
            parts.append("\u2605")
        return " ".join(p for p in parts if p)

    @property
    def label(self) -> str:
        """E.g. "2: Left \u00b7 DP-2 (2560\u00d71440) \u2605"."""
        if not self.settings.name:
            return self.device_label
        prefix = f"{self.number}: " if self.number is not None else ""
        return prefix + self.settings.name + " \u00b7 " + self.device_label.removeprefix(prefix)

    @property
    def active_inputs(self) -> list[int]:
        """Inputs to offer in the menu (none while the monitor is off)."""
        return self.settings.active_inputs(self.inputs) if self.on else []


def _state(m: Monitor) -> MonitorState:
    mode = core.get_power_mode(m)
    on = None if mode is None else core.is_on(mode)
    current, inputs = None, []
    if on:
        current = core.get_input_source(m)
        inputs = _supported_inputs(m)
    return MonitorState(
        name=m.name,
        number=m.number,
        primary=m.primary,
        width=m.width,
        height=m.height,
        has_ddc=m.ddc is not None,
        on=on,
        input=current,
        inputs=inputs,
        settings=m.settings,
    )


# Monitor name -> supported input sources. Reading the capabilities takes up
# to seconds per monitor, and they don't change, so each is read once (only
# while the monitor is on; a failed read is retried on the next snapshot).
_inputs_cache: dict[str, list[int]] = {}


def _supported_inputs(m: Monitor) -> list[int]:
    if m.name not in _inputs_cache:
        inputs = core.get_supported_inputs(m)
        if inputs is None:
            return []
        _inputs_cache[m.name] = inputs
    return _inputs_cache[m.name]


def forget_inputs() -> None:
    """Re-read the supported inputs on the next snapshot (e.g. after a
    monitor was swapped)."""
    _inputs_cache.clear()


def snapshot() -> list[MonitorState]:
    return [_state(m) for m in core.list_monitors()]


# --- Names -------------------------------------------------------------------------


def _name_syntax_error(name: str) -> str | None:
    # Commands are split at whitespace, --sources at commas.
    if any(c.isspace() or c == "," for c in name):
        return tr("'{name}': names can't contain spaces or commas.", name=name)
    return None


def validate_names(
    settings: MonitorSettingsFile, device_names: list[str]
) -> str | None:
    """Error message (translated) if a monitor or input name is unusable in
    commands: not a single word, ambiguous, or already a reference."""
    taken = {d.lower(): d for d in device_names}  # name -> who has it
    for device, m in settings.monitors.items():
        if m.name:
            key = m.name.lower()
            error = _name_syntax_error(m.name)
            if error:
                return error
            if key.isdigit() or key in (PRIMARY, ALL):
                return tr(
                    "'{name}': monitor names can't be numbers, 'primary' or 'all'.",
                    name=m.name,
                )
            if taken.get(key, device) != device:
                return tr(
                    "'{name}' is used for more than one monitor.", name=m.name
                )
            taken[key] = device

        seen: set[str] = set()
        for s in m.inputs.values():
            if not s.name:
                continue
            error = _name_syntax_error(s.name)
            if error:
                return error
            if is_input_source(s.name):
                return tr(
                    "'{name}': input names can't be a standard input name or "
                    "a number.",
                    name=s.name,
                )
            if s.name.lower() in seen:
                return tr(
                    "'{name}' is used for more than one input of {monitor}.",
                    name=s.name,
                    monitor=m.name or device,
                )
            seen.add(s.name.lower())
    return None
