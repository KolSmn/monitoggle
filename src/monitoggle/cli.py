"""Command-line front-end: parses arguments and runs the matching core command.

The tray app also runs its shortcut commands through parse_command() and
run_args(), so a shortcut behaves exactly like the same CLI call.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from typing import NoReturn

from monitorcontrol import PowerMode

from . import APP_NAME, CLI_NAME, core, logs, monitor_settings
from .errors import UserError
from .linux_setup import run_setup
from .models import Monitor
from .monitor_settings import MonitorSettingsFile
from .version import get_version

logger = logging.getLogger(APP_NAME)


def _number(m: Monitor) -> str:
    return str(m.number) if m.number is not None else "-"


def _status(m: Monitor) -> str:
    mode = core.get_power_mode(m)
    if mode is None:
        return "unknown"
    return "on" if mode == PowerMode.on else "off"


def format_list(monitors: list[Monitor]) -> str:
    headers = ["Number", "Status", "Name", "Device name", "Resolution"]
    rows = []
    for m in monitors:
        rows.append(
            [
                _number(m),
                _status(m),
                m.settings.name or "-",
                m.name,
                f"{m.width} x {m.height}",
            ]
        )
    return _format_table(headers, rows)


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(cells: list[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    lines = [fmt(headers), fmt(["-" * w for w in widths])]
    lines.extend(fmt(row) for row in rows)
    return "\n".join(lines)


def show_list() -> None:
    logger.info("\n%s", format_list(core.list_monitors()))


def format_inputs(monitors: list[Monitor]) -> str:
    rows = []
    for m in monitors:
        s = m.settings
        current = core.get_input_source(m)
        codes = s.known_inputs(core.get_supported_inputs(m))
        labels = [
            s.input_label(c) + ("" if s.input_enabled(c) else " [disabled]")
            for c in codes
        ]
        rows.append(
            [
                _number(m),
                s.name or "-",
                m.name,
                s.input_label(current) if current is not None else "unknown",
                ", ".join(labels) or "unknown",
            ]
        )
    return _format_table(["Number", "Name", "Device name", "Input", "Inputs"], rows)


def show_inputs(refs: list[str]) -> None:
    monitors = core.list_monitors()
    if refs:
        monitors = core.resolve_tokens(refs, monitors)
    logger.info("\n%s", format_inputs(monitors))


def _input_source_type(
    settings: MonitorSettingsFile | None,
) -> Callable[[str], str]:
    """argparse type for an input source: a standard name or number, or a
    name given to an input of any monitor (which monitor has it is only
    known when the command runs). Returns the text as given."""

    def check(text: str) -> str:
        try:
            monitor_settings.parse_input_source(text)
        except ValueError as exc:
            names = (settings or monitor_settings.load()).input_names()
            if text.strip().lower() not in names:
                raise argparse.ArgumentTypeError(str(exc)) from None
        return text

    return check


def _input_sources_type(
    settings: MonitorSettingsFile | None,
) -> Callable[[str], list[str]]:
    check = _input_source_type(settings)
    return lambda text: [check(t.strip()) for t in text.split(",") if t.strip()]


# --- Parser ------------------------------------------------------------------------


class CommandLineError(Exception):
    """An invalid command line, raised by parse_command() instead of exiting."""


class _RaisingParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise CommandLineError(f"{self.prog}: {message}")


_EXAMPLES = (
    "list",
    "off 2",
    "on 2",
    "all",
    "toggle 2",
    "off-all",
    "toggle-all",
    "inputs",
    "input HDMI1 2",
    "input work Left",
    "cycle-input Left",
    "cycle-input all",
    "cycle-input 2 --sources HDMI1,DP1",
    "setup      (Linux, once)",
)


def _add_refs(parser: argparse.ArgumentParser, help: str, required: bool = True) -> None:
    parser.add_argument(
        "refs", nargs="+" if required else "*", metavar="monitor", help=help
    )


def _add_force(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip the safety check that refuses to leave no monitor on",
    )


def build_parser(
    parser_class: type[argparse.ArgumentParser] = argparse.ArgumentParser,
    settings: MonitorSettingsFile | None = None,
) -> argparse.ArgumentParser:
    """settings: the monitor and input names to accept; default: the saved
    ones, read when an input source is parsed."""
    parser = parser_class(
        prog=CLI_NAME,
        description="Turn monitors on and off and switch their inputs via DDC/CI.",
        epilog=(
            "Monitor reference: number from the list (e.g. 2), device name "
            "(e.g. \\\\.\\DISPLAY2 on Windows, DP-2 on Linux), the name given "
            "in the tray app's settings (e.g. Left), 'primary' for the "
            "main monitor, or 'all' for every monitor.\n\n"
            "Input source: a name given in the tray app's settings (e.g. "
            "work), a standard name (e.g. HDMI1, DP1), or a number (e.g. 0x1b).\n\n"
            "Examples:\n" + "\n".join(f"  {CLI_NAME} {example}" for example in _EXAMPLES)
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {get_version()}"
    )
    # Each subcommand's func is called with its parsed arguments as keyword
    # arguments (see run_args), so argument names match the parameters.
    sub = parser.add_subparsers(dest="action", required=True)

    p_list = sub.add_parser("list", help="Shows all detected monitors")
    p_list.set_defaults(func=show_list)

    p_on = sub.add_parser("on", help="Turns on the specified monitor(s)")
    _add_refs(p_on, "Monitor(s) to turn on")
    p_on.set_defaults(func=core.turn_on)

    p_off = sub.add_parser("off", help="Turns off the specified monitor(s)")
    _add_refs(p_off, "Monitor(s) to turn off")
    _add_force(p_off)
    p_off.set_defaults(func=core.turn_off)

    p_all = sub.add_parser("all", help="Turns on all monitors (recovery)")
    p_all.set_defaults(func=core.all_on)

    p_off_all = sub.add_parser(
        "off-all", help="Turns off all monitors, always (no safety check)"
    )
    p_off_all.set_defaults(func=core.all_off)

    p_toggle = sub.add_parser(
        "toggle", help="Toggles the specified monitor(s) (on<->off)"
    )
    _add_refs(p_toggle, "Monitor(s) to toggle")
    _add_force(p_toggle)
    p_toggle.set_defaults(func=core.toggle)

    p_toggle_all = sub.add_parser(
        "toggle-all",
        help="Turns all monitors off if any is on, otherwise turns all on",
    )
    p_toggle_all.add_argument(
        "--on-mixed",
        choices=core.ON_MIXED,
        default="off",
        help=(
            "What to do when monitors are in a mixed on/off state: turn "
            "all off (default), toggle each individually, or turn all on"
        ),
    )
    p_toggle_all.set_defaults(func=core.toggle_all)

    p_inputs = sub.add_parser(
        "inputs",
        help="Shows the current and the supported input sources of the monitors",
    )
    _add_refs(p_inputs, "Monitor(s) to show (default: all)", required=False)
    p_inputs.set_defaults(func=show_inputs)

    p_input = sub.add_parser(
        "input", help="Switches the specified monitor(s) to an input source"
    )
    p_input.add_argument(
        "source",
        type=_input_source_type(settings),
        help="Input source: a name given in the settings (e.g. work), a "
        "standard name such as HDMI1, DP1, DVI1 (see 'inputs'), or its number "
        "(e.g. 0x1b for USB-C on many monitors). Disabled inputs work too.",
    )
    _add_refs(p_input, "Monitor(s) to switch")
    p_input.set_defaults(func=core.switch_input)

    p_cycle_input = sub.add_parser(
        "cycle-input",
        help="Switches the specified monitor(s) to their next active input source",
    )
    _add_refs(p_cycle_input, "Monitor(s) to switch")
    p_cycle_input.add_argument(
        "--sources",
        type=_input_sources_type(settings),
        metavar="SOURCE,...",
        help="Comma-separated inputs to cycle through, e.g. work,private or "
        "HDMI1,DP1 to toggle between the two (default: all active inputs of "
        "the monitor; disabled ones are always skipped)",
    )
    p_cycle_input.set_defaults(func=core.cycle_input)

    p_setup = sub.add_parser(
        "setup",
        help="Linux only: one-time setup of DDC/CI access to /dev/i2c-* (asks for the root password)",
    )
    p_setup.add_argument(
        "-y",
        "--yes",
        dest="assume_yes",
        action="store_true",
        help="Don't ask for confirmation",
    )
    p_setup.add_argument(
        "--terminal",
        action="store_true",
        help="Ask for the password in the terminal (sudo) instead of a graphical dialog",
    )
    p_setup.set_defaults(func=run_setup)

    return parser


def parse_command(
    argv: list[str], settings: MonitorSettingsFile | None = None
) -> argparse.Namespace:
    """Parses a command line like main() does, but raises CommandLineError
    instead of printing usage and exiting (for in-process callers).
    settings: see build_parser.
    """
    return build_parser(_RaisingParser, settings).parse_args(argv)


def run_args(args: argparse.Namespace) -> int:
    """Runs a parsed command; returns the process exit code."""
    kwargs = {k: v for k, v in vars(args).items() if k not in ("func", "action")}
    try:
        args.func(**kwargs)
    except UserError as exc:
        logger.error(exc.template, *exc.template_args)
        return 1
    except Exception:
        logger.exception("Unexpected error.")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    logs.configure_logging()
    logger.info("MoniToggle CLI %s, log file: %s", get_version(), logs.LOG_FILE)
    parser = build_parser()
    args = parser.parse_args(argv)
    logger.info("Invocation: %s", " ".join(argv if argv is not None else sys.argv[1:]))
    return run_args(args)
