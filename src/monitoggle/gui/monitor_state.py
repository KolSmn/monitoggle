"""The monitors as the tray app shows them: queried status, current and
supported inputs (Qt-free)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import core
from ..models import Monitor, MonitorInfo


@dataclass
class MonitorState(MonitorInfo):
    """A monitor as the tray app shows it: queried once, no DDC/CI handle."""

    has_ddc: bool
    on: bool | None  # None: unknown (no DDC/CI, or the query failed)
    input: int | None = None  # current input source, None: unknown
    inputs: list[int] = field(default_factory=list)  # supported; empty: unknown

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
        **m.info_fields(), has_ddc=m.ddc is not None, on=on, input=current, inputs=inputs
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
