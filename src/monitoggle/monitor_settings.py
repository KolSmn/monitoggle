"""User-given names for monitors and their input sources, and which inputs
are active (Qt-free; read by the CLI and the tray app alike).

Stored as JSON in the per-user config directory, keyed by device name
(e.g. \\\\.\\DISPLAY2 or DP-2), input sources keyed by their name as
input_source_name() writes it (e.g. HDMI1, 0x1B):

    {"monitors": {"DP-2": {"name": "Left",
                           "inputs": {"HDMI1": {"name": "work", "enabled": true},
                                      "DP1": {"name": "private", "enabled": true},
                                      "HDMI2": {"name": "", "enabled": false}}}}}

A monitor's listed inputs are the ones it offers, in that order (the tray
app lists all of them once anything is customized); without a list, the
monitor's DDC/CI capabilities decide.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from monitorcontrol import InputSource

from . import storage

logger = logging.getLogger(__name__)

CONFIG_FILE = storage.config_dir() / "monitors.json"


# --- Input source codes (VCP 0x60) ----------------------------------------------


def parse_input_source(text: str) -> int:
    """Input source code from a name (e.g. HDMI1, DP1, case-insensitive) or
    a number (decimal or 0x hex, for inputs the standard has no name for,
    e.g. USB-C on many monitors)."""
    t = text.strip()
    try:
        code = int(t, 16) if t.lower().startswith("0x") else int(t)
    except ValueError:
        member = InputSource.__members__.get(t.upper())
        if member is None or member == InputSource.OFF:
            names = ", ".join(s.name for s in InputSource if s != InputSource.OFF)
            raise ValueError(
                f"unknown input source '{text}' (use {names}, a number, "
                "or a name given in the settings)"
            ) from None
        return int(member.value)
    if not 1 <= code <= 0xFF:
        raise ValueError(f"input source {text} is out of range (1-255)")
    return code


def input_source_name(code: int) -> str:
    """Display name that parse_input_source() reads back."""
    try:
        source = InputSource(code)
    except ValueError:
        return f"0x{code:02X}"
    return source.name if source != InputSource.OFF else f"0x{code:02X}"


def is_input_source(text: str) -> bool:
    try:
        parse_input_source(text)
    except ValueError:
        return False
    return True


# --- Settings ----------------------------------------------------------------------


@dataclass
class InputSettings:
    name: str = ""  # e.g. "work"; empty: none
    enabled: bool = True  # disabled: not in the tray menu, skipped by cycle-input


@dataclass
class MonitorSettings:
    name: str = ""  # e.g. "Left"; empty: none
    inputs: dict[int, InputSettings] = field(default_factory=dict)

    def input_code(self, token: str) -> int | None:
        """Input a command refers to: one of this monitor's input names,
        or a standard name/number (see parse_input_source)."""
        t = token.strip().lower()
        for code, s in self.inputs.items():
            if s.name and s.name.lower() == t:
                return code
        try:
            return parse_input_source(token)
        except ValueError:
            return None

    def input_name(self, code: int) -> str:
        """The name given to an input, e.g. "work"; empty: none."""
        s = self.inputs.get(code)
        return s.name if s else ""

    def input_token(self, code: int) -> str:
        """How commands refer to an input: its name if it has one (e.g.
        "work"), else its standard name (e.g. "HDMI1")."""
        return self.input_name(code) or input_source_name(code)

    def input_label(self, code: int) -> str:
        """E.g. "work (HDMI1)", or just "HDMI1" without a name."""
        source = input_source_name(code)
        name = self.input_name(code)
        return f"{name} ({source})" if name else source

    def input_enabled(self, code: int) -> bool:
        s = self.inputs.get(code)
        return s is None or s.enabled

    def active_inputs(self, supported: list[int] | None) -> list[int]:
        """Inputs to offer and cycle through: the listed ones if any (else
        supported, the monitor's own list), without the disabled ones."""
        codes = list(self.inputs) or list(supported or [])
        return [c for c in codes if self.input_enabled(c)]

    def is_customized(self) -> bool:
        return bool(self.name) or any(
            s.name or not s.enabled for s in self.inputs.values()
        )


@dataclass
class MonitorSettingsFile:
    # Device name -> settings
    monitors: dict[str, MonitorSettings] = field(default_factory=dict)

    def get(self, device_name: str) -> MonitorSettings:
        return self.monitors.get(device_name) or MonitorSettings()

    def input_names(self) -> set[str]:
        """All input names given for any monitor (lower case)."""
        return {
            s.name.lower()
            for m in self.monitors.values()
            for s in m.inputs.values()
            if s.name
        }

    @classmethod
    def from_dict(cls, data: dict) -> MonitorSettingsFile:
        monitors: dict[str, MonitorSettings] = {}
        raw_monitors = data.get("monitors")
        for device, raw in (raw_monitors if isinstance(raw_monitors, dict) else {}).items():
            if not isinstance(raw, dict):
                continue
            inputs: dict[int, InputSettings] = {}
            raw_inputs = raw.get("inputs")
            for key, value in (raw_inputs if isinstance(raw_inputs, dict) else {}).items():
                try:
                    code = parse_input_source(str(key))
                except ValueError:
                    logger.warning("Ignoring unknown input source '%s' of %s.", key, device)
                    continue
                value = value if isinstance(value, dict) else {}
                inputs[code] = InputSettings(
                    name=str(value.get("name", "")).strip(),
                    enabled=bool(value.get("enabled", True)),
                )
            monitors[str(device)] = MonitorSettings(
                name=str(raw.get("name", "")).strip(), inputs=inputs
            )
        return cls(monitors)

    def to_dict(self) -> dict:
        return {
            "monitors": {
                device: {
                    "name": m.name,
                    "inputs": {
                        input_source_name(code): {"name": s.name, "enabled": s.enabled}
                        for code, s in m.inputs.items()
                    },
                }
                for device, m in self.monitors.items()
            }
        }


def load(path: Path | None = None) -> MonitorSettingsFile:
    return MonitorSettingsFile.from_dict(storage.read_json(path or CONFIG_FILE))


def save(settings: MonitorSettingsFile, path: Path | None = None) -> None:
    storage.write_json(path or CONFIG_FILE, settings.to_dict())
