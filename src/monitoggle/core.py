"""Monitor power control: discovery, status and the commands.

Front-end independent: the CLI and the tray app both call into this module.
Failures meant for the user are raised as UserError; what a command did is
logged (logger APP_NAME), which is how front-ends show it.
"""

from __future__ import annotations

import logging
import operator
from collections.abc import Callable, Sequence
from operator import methodcaller
from typing import Literal, TypeVar, get_args

from monitorcontrol import Monitor as DdcMonitor
from monitorcontrol import PowerMode, VCPError

from . import APP_NAME, monitor_settings
from .backends import get_backend
from .errors import UserError
from .models import Monitor

logger = logging.getLogger(APP_NAME)

T = TypeVar("T")

# What toggle_all() does when some monitors are on and some off.
OnMixed = Literal["off", "toggle", "on"]
ON_MIXED: tuple[OnMixed, ...] = get_args(OnMixed)

# Desired state of a monitor (given whether it is on now), per on_mixed choice.
_DESIRED: dict[OnMixed, Callable[[bool], bool]] = {
    "off": lambda _on: False,
    "toggle": operator.not_,
    "on": lambda _on: True,
}


def list_monitors() -> list[Monitor]:
    """Detected monitors, with their user-given names and inputs."""
    monitors = get_backend().list_monitors()
    settings = monitor_settings.load()
    for m in monitors:
        m.settings = settings.get(m.name)
    return monitors


# --- DDC/CI access -------------------------------------------------------------


def _read(
    m: Monitor,
    query: Callable[[DdcMonitor], T],
    what: str,
    errors: tuple[type[Exception], ...] = (VCPError,),
) -> T | None:
    """query's answer from the monitor; None without DDC/CI access or if the
    query fails (only logged at debug level: the value is then unknown)."""
    if m.ddc is None:
        return None
    try:
        with m.ddc:
            return query(m.ddc)
    except errors:
        logger.debug("Could not read %s of %s.", what, m.name, exc_info=True)
        return None


def _write(m: Monitor, command: Callable[[DdcMonitor], object]) -> None:
    """Sends command to the monitor; raises VCPError if that fails."""
    if m.ddc is None:
        raise VCPError("no DDC/CI access")
    with m.ddc:
        command(m.ddc)


def _has_ddc(m: Monitor) -> bool:
    """Whether the monitor can be switched; logs that it's skipped if not."""
    if m.ddc is None:
        logger.warning("No DDC/CI access to %s, skipped.", m.display_name)
        return False
    return True


# --- DDC/CI power status -----------------------------------------------------


def get_power_mode(m: Monitor) -> PowerMode | None:
    # ValueError: a value outside the standard's PowerMode (some monitors).
    return _read(m, methodcaller("get_power_mode"), "power status", (VCPError, ValueError))


def set_power_mode(m: Monitor, mode: PowerMode) -> None:
    _write(m, lambda ddc: ddc.set_power_mode(mode))


def is_on(mode: PowerMode | None) -> bool:
    # Unknown status (no DDC/CI, or the query failed) counts as "on", so the
    # safety check when turning monitors off stays strict.
    return mode is None or mode == PowerMode.on


def apply_power_mode(targets: list[Monitor], mode: PowerMode) -> list[Monitor]:
    """Switches each target to mode; returns the ones that actually switched."""
    switched: list[Monitor] = []
    for m in filter(_has_ddc, targets):
        try:
            set_power_mode(m, mode)
        except VCPError:
            logger.exception("Failed to switch %s.", m.display_name)
            continue
        switched.append(m)
    return switched


def resolve_tokens(tokens: Sequence[str], monitors: list[Monitor]) -> list[Monitor]:
    """Monitors matching any of the references (number, name, 'primary')."""
    resolved: dict[str, Monitor] = {}
    for token in tokens:
        matches = [m for m in monitors if m.matches(token)]
        if not matches:
            logger.warning("'%s' does not match any monitor.", token)
            continue
        for m in matches:
            resolved[m.name] = m
    return list(resolved.values())


def apply_desired_states(
    monitors: list[Monitor],
    targets: list[Monitor],
    desired: Callable[[bool], bool],
    force: bool = False,
) -> None:
    """Brings each target monitor into the state requested by desired().

    Aborts beforehand if that would leave no monitor on, unless force is set.
    """
    states = {m.name: is_on(get_power_mode(m)) for m in monitors}
    target_names = {m.name for m in targets}

    resulting_active = sum(
        desired(states[m.name]) if m.name in target_names else states[m.name]
        for m in monitors
    )
    if resulting_active <= 0 and not force:
        raise UserError(
            "Aborted: this would leave no monitor on. Nothing was changed. "
            "Use --force to do it anyway."
        )

    turned_on: list[str] = []
    turned_off: list[str] = []
    for m in targets:
        want_on = desired(states[m.name])
        if want_on == states[m.name]:
            continue
        if apply_power_mode([m], PowerMode.on if want_on else PowerMode.off_soft):
            (turned_on if want_on else turned_off).append(m.display_name)

    if turned_on:
        logger.info("Turned on: %s", ", ".join(turned_on))
    if turned_off:
        logger.info("Turned off: %s", ", ".join(turned_off))


# --- Commands ------------------------------------------------------------------


def _all_monitors() -> list[Monitor]:
    monitors = list_monitors()
    if not monitors:
        raise UserError("No monitors found.")
    return monitors


def _resolve_targets(refs: Sequence[str], monitors: list[Monitor]) -> list[Monitor]:
    targets = resolve_tokens(refs, monitors)
    if not targets:
        raise UserError("No matching monitors found, nothing changed.")
    return targets


# refs: monitor references as the user gives them (number, device name or
# "primary"), see Monitor.matches().


def _switch(refs: Sequence[str], choice: OnMixed, force: bool = False) -> None:
    monitors = list_monitors()
    targets = _resolve_targets(refs, monitors)
    apply_desired_states(monitors, targets, desired=_DESIRED[choice], force=force)


def turn_on(refs: Sequence[str]) -> None:
    _switch(refs, "on")


def turn_off(refs: Sequence[str], force: bool = False) -> None:
    _switch(refs, "off", force)


def toggle(refs: Sequence[str], force: bool = False) -> None:
    _switch(refs, "toggle", force)


def all_on() -> None:
    monitors = _all_monitors()
    apply_desired_states(monitors, monitors, desired=_DESIRED["on"])


def all_off() -> None:
    """Turns off every monitor, without the safety check."""
    monitors = _all_monitors()
    apply_desired_states(monitors, monitors, desired=_DESIRED["off"], force=True)


def toggle_all(on_mixed: OnMixed = "off") -> None:
    """Group switch: all on -> all off, all off -> all on; a mixed state is
    resolved by on_mixed (all off, flip each, or all on)."""
    monitors = _all_monitors()
    states = [is_on(get_power_mode(m)) for m in monitors]
    if not any(states):
        choice: OnMixed = "on"
    elif all(states):
        choice = "off"
    else:
        choice = on_mixed
    apply_desired_states(monitors, monitors, desired=_DESIRED[choice], force=True)


# --- DDC/CI input source (VCP 0x60) --------------------------------------------


def get_input_source(m: Monitor) -> int | None:
    return _read(m, methodcaller("get_input_source"), "input source")


def get_supported_inputs(m: Monitor) -> list[int] | None:
    """Input sources the monitor announces in its capabilities string; None
    if it could not be queried. The query takes a moment (up to seconds)."""
    # Exception: VCPError, or a capabilities string the parser chokes on.
    caps = _read(m, methodcaller("get_vcp_capabilities"), "capabilities", (Exception,))
    return None if caps is None else [int(s) for s in caps.get("inputs", [])]


def set_input_source(m: Monitor, code: int) -> None:
    _write(m, lambda ddc: ddc.set_input_source(code))


def active_inputs(m: Monitor) -> list[int]:
    """The monitor's active inputs (see MonitorSettings.active_inputs); only
    queries the monitor if the settings don't list its inputs."""
    supported = None if m.settings.inputs else get_supported_inputs(m)
    return m.settings.active_inputs(supported)


def _input_code(m: Monitor, source: str) -> int | None:
    code = m.settings.input_code(source)
    if code is None:
        logger.warning("'%s' is not an input of %s, skipped.", source, m.display_name)
    return code


def _switch_input(m: Monitor, code: int) -> None:
    if not _has_ddc(m):
        return
    try:
        set_input_source(m, code)
    except VCPError:
        logger.exception("Failed to switch the input of %s.", m.display_name)
        return
    logger.info(
        "%s: switched to input %s.", m.display_name, m.settings.input_label(code)
    )


# source: an input as the user gives it: a name from the settings (e.g.
# "work", per monitor), a standard name (e.g. HDMI1) or a number.


def switch_input(source: str, refs: Sequence[str]) -> None:
    """Switches the target monitors to an input source (also a disabled one:
    it was asked for explicitly)."""
    targets = _resolve_targets(refs, list_monitors())
    for m in targets:
        code = _input_code(m, source)
        if code is not None:
            _switch_input(m, code)


def cycle_input(refs: Sequence[str], sources: Sequence[str] | None = None) -> None:
    """Switches each target monitor to the next of sources (default: its
    active inputs), after the current one. With two sources this toggles
    between them. Inputs disabled in the settings are always skipped."""
    targets = _resolve_targets(refs, list_monitors())
    for m in filter(_has_ddc, targets):
        if sources:
            codes = [_input_code(m, s) for s in sources]
            candidates = [
                c
                for c in dict.fromkeys(c for c in codes if c is not None)
                if m.settings.input_enabled(c)
            ]
        else:
            candidates = active_inputs(m)
        if not candidates and m.settings.inputs:
            logger.warning("%s has no active inputs, skipped.", m.display_name)
            continue
        if not candidates:
            logger.warning(
                "Could not determine the inputs of %s, skipped. Name them "
                "with --sources.",
                m.display_name,
            )
            continue
        current = get_input_source(m)
        if current in candidates:
            target = candidates[(candidates.index(current) + 1) % len(candidates)]
        else:
            target = candidates[0]
        if target == current:
            logger.info(
                "%s: already on input %s.", m.display_name, m.settings.input_label(target)
            )
            continue
        _switch_input(m, target)


def wake_if_all_off() -> list[str]:
    """Turns all monitors on if every one of them is off.

    Meant for right before the session is locked or ends (the tray app
    calls it then): at the lock/login screen no shortcut works, and a
    monitor switched off via DDC/CI might then only come back with its
    power button. Returns the names of the monitors that were turned on.
    """
    monitors = list_monitors()
    # Unknown status counts as on (is_on), so this only acts when every
    # monitor reliably reports being off.
    if not monitors or any(is_on(get_power_mode(m)) for m in monitors):
        logger.info("Not all monitors are off, nothing to do.")
        return []
    switched = apply_power_mode(monitors, PowerMode.on)
    logger.info(
        "All monitors were off; turned on: %s",
        ", ".join(m.display_name for m in switched) or "none",
    )
    return [m.name for m in switched]


def turn_on_again(names: Sequence[str]) -> list[str]:
    """Sends "on" again to the monitors with these device names, whatever
    they report.

    For monitors wake_if_all_off() turned on while the system had switched
    the display signal off: without a signal, a monitor may acknowledge the
    command but ignore it, and still report "on" afterwards. Returns the
    names of the monitors that were switched.
    """
    monitors = [m for m in list_monitors() if m.name in set(names)]
    switched = apply_power_mode(monitors, PowerMode.on)
    if switched:
        logger.info("Turned on again: %s", ", ".join(m.display_name for m in switched))
    return [m.name for m in switched]
