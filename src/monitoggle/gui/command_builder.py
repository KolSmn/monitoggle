"""Guided command entry: the commands a shortcut can run, as choices with
explanations, and the translation between those choices and the command
text (Qt-free).

The command text stays the one source of truth: build() writes it, parse()
reads an existing one back into choices, describe() says in words what it
does.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import cli
from ..core import OnMixed
from ..models import ALL, PRIMARY
from ..monitor_settings import MonitorSettingsFile
from .commands import MonitorState, split_command
from .i18n import N_, tr


@dataclass(frozen=True)
class Action:
    command: str  # CLI subcommand
    label: str  # N_()-marked
    help: str  # N_()-marked
    monitors: bool = False  # takes monitor references
    source: bool = False  # input: one input source
    sources: bool = False  # cycle-input: optional subset of inputs
    force: bool = False  # --force
    on_mixed: bool = False  # --on-mixed


ACTIONS: tuple[Action, ...] = (
    Action(
        "toggle",
        N_("Toggle on/off"),
        N_("Turns each chosen monitor off if it is on, and on if it is off."),
        monitors=True,
        force=True,
    ),
    Action("on", N_("Turn on"), N_("Turns the chosen monitors on."), monitors=True),
    Action(
        "off",
        N_("Turn off"),
        N_(
            "Turns the chosen monitors off. Refuses if that would leave no "
            "monitor on, unless forced."
        ),
        monitors=True,
        force=True,
    ),
    Action(
        "toggle-all",
        N_("Toggle all monitors"),
        N_(
            "One switch for all monitors: if all are on, turns all off; if "
            "all are off, turns all on."
        ),
        on_mixed=True,
    ),
    Action("all", N_("Turn all monitors on"), N_("Turns every monitor on.")),
    Action(
        "off-all",
        N_("Turn all monitors off"),
        N_("Turns every monitor off, without the safety check."),
    ),
    Action(
        "input",
        N_("Switch input source"),
        N_(
            "Switches the chosen monitors to an input source, e.g. to the "
            "port another computer is connected to."
        ),
        monitors=True,
        source=True,
    ),
    Action(
        "cycle-input",
        N_("Next input source"),
        N_(
            "Switches each chosen monitor to its next active input source. "
            "Limit it to two inputs to toggle between them."
        ),
        monitors=True,
        sources=True,
    ),
)
ACTIONS_BY_COMMAND = {a.command: a for a in ACTIONS}

ON_MIXED_LABELS: dict[OnMixed, str] = {
    "off": N_("Turn all off"),
    "toggle": N_("Toggle each monitor"),
    "on": N_("Turn all on"),
}


@dataclass
class CommandSpec:
    action: str = "toggle"
    monitors: list[str] = field(default_factory=list)  # references, e.g. "Left", "all"
    source: str = ""  # input
    sources: list[str] = field(default_factory=list)  # cycle-input; empty: all active
    force: bool = False
    on_mixed: OnMixed = "off"

    def is_complete(self) -> bool:
        a = ACTIONS_BY_COMMAND.get(self.action)
        if a is None:
            return False
        if a.monitors and not self.monitors:
            return False
        return not (a.source and not self.source)


def build(spec: CommandSpec) -> str:
    """The command text for spec (see CommandSpec.is_complete)."""
    a = ACTIONS_BY_COMMAND[spec.action]
    parts = [a.command]
    if a.source:
        parts.append(spec.source)
    if a.monitors:
        parts += spec.monitors
    if a.force and spec.force:
        parts.append("--force")
    if a.on_mixed and spec.on_mixed != "off":
        parts += ["--on-mixed", spec.on_mixed]
    if a.sources and spec.sources:
        parts += ["--sources", ",".join(spec.sources)]
    return " ".join(parts)


def parse(command: str, settings: MonitorSettingsFile | None = None) -> CommandSpec | None:
    """The choices for an existing command; None if it isn't one of ACTIONS
    or isn't valid (settings: the input names to accept, see cli)."""
    try:
        args = cli.parse_command(split_command(command), settings)
    except (cli.CommandLineError, SystemExit):
        return None
    if args.action not in ACTIONS_BY_COMMAND:
        return None
    return CommandSpec(
        action=args.action,
        monitors=list(getattr(args, "refs", None) or []),
        source=getattr(args, "source", None) or "",
        sources=list(getattr(args, "sources", None) or []),
        force=bool(getattr(args, "force", False)),
        on_mixed=getattr(args, "on_mixed", None) or "off",
    )


# --- Choices -------------------------------------------------------------------------


def monitor_choices(monitors: list[MonitorState]) -> list[tuple[str, str]]:
    """(reference, label) for everything a command can address."""
    return [
        (ALL, tr("All monitors")),
        (PRIMARY, tr("Main monitor")),
        *((m.ref, m.label) for m in monitors),
    ]


def selected_monitors(monitors: list[MonitorState], refs: list[str]) -> list[MonitorState]:
    return [m for m in monitors if any(m.matches(ref) for ref in refs)]


def input_choices(monitors: list[MonitorState], refs: list[str]) -> list[tuple[str, str]]:
    """(source token, label) for the active inputs of the chosen monitors.
    The token is an input's own name where it has one (e.g. "work"), so the
    same name on several monitors is one choice."""
    choices: dict[str, tuple[str, str]] = {}
    for m in selected_monitors(monitors, refs):
        s = m.settings
        # Unlike the tray menu, also for a monitor that is off: the inputs
        # listed in the settings are known then too.
        for code in s.active_inputs(m.inputs):
            token = s.input_token(code)
            choices.setdefault(token.lower(), (token, s.input_label(code)))
    return list(choices.values())


# --- Description ---------------------------------------------------------------------


def _monitor_words(monitors: list[MonitorState], refs: list[str]) -> str:
    words = []
    for ref in refs:
        r = ref.strip().lower()
        if r == ALL:
            words.append(tr("all monitors"))
        elif r == PRIMARY:
            words.append(tr("the main monitor"))
        else:
            m = next((m for m in monitors if m.is_called(ref)), None)
            if m is not None and m.settings.name:
                words.append(m.settings.name)
            elif m is not None and m.number is not None:
                words.append(tr("monitor {number}", number=m.number))
            else:
                words.append(ref)
    return ", ".join(words)


def _source_words(monitors: list[MonitorState], refs: list[str], token: str) -> str:
    labels = dict((t.lower(), label) for t, label in input_choices(monitors, refs))
    return labels.get(token.lower(), token)


def describe(
    command: str,
    monitors: list[MonitorState],
    settings: MonitorSettingsFile | None = None,
) -> str:
    """What a command does, in words (translated); the command text itself
    if it isn't one of the guided actions."""
    spec = parse(command, settings)
    if spec is None or not spec.is_complete():
        return command
    who = _monitor_words(monitors, spec.monitors)
    if spec.action == "toggle":
        text = tr("Toggle {monitors}", monitors=who)
    elif spec.action == "on":
        text = tr("Turn {monitors} on", monitors=who)
    elif spec.action == "off":
        text = tr("Turn {monitors} off", monitors=who)
    elif spec.action == "toggle-all":
        text = tr("Toggle all monitors")
        if spec.on_mixed != "off":
            text += " (" + tr(
                "mixed: {choice}", choice=tr(ON_MIXED_LABELS[spec.on_mixed]).lower()
            ) + ")"
    elif spec.action == "all":
        text = tr("Turn all monitors on")
    elif spec.action == "off-all":
        text = tr("Turn all monitors off")
    elif spec.action == "input":
        text = tr(
            "Switch {monitors} to {source}",
            monitors=who,
            source=_source_words(monitors, spec.monitors, spec.source),
        )
    else:  # cycle-input
        text = tr("Next input on {monitors}", monitors=who)
        if spec.sources:
            names = [_source_words(monitors, spec.monitors, s) for s in spec.sources]
            text += " (" + ", ".join(names) + ")"
    if spec.force:
        text += " " + tr("(forced)")
    return text
