"""GUI settings, stored as JSON in the per-user config directory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .. import storage

CONFIG_FILE = storage.config_dir() / "gui.json"

SHORTCUT_EDITORS = ("guided", "text")


@dataclass
class Shortcut:
    # Key combination in Qt's portable text form, e.g. "Ctrl+Alt+F1".
    keys: str
    # CLI arguments (without the program name), e.g. "toggle 2" or "toggle-all --on-mixed on".
    command: str


@dataclass
class Settings:
    shortcuts: list[Shortcut] = field(default_factory=list)
    # Show a tray notification after successful actions (errors always show).
    notifications: bool = True
    # "auto" (follow the system's UI language) or a code from i18n.LANGUAGES.
    language: str = "auto"
    # Before the session is locked, ends (logoff/shutdown) or the system
    # sleeps: turn the monitors back on if all of them are off.
    wake_before_session_end: bool = True
    # When the tray app starts: turn the monitors on if all of them are off.
    wake_on_startup: bool = True
    # When the system switches the display signal back on (e.g. the mouse
    # is moved after an idle timeout): turn the monitors on if all are off.
    wake_on_display_on: bool = True
    # Seconds between status updates (icon, tooltip, menu), so changes made
    # elsewhere (e.g. a monitor's power button) show up; 0 = off.
    status_refresh_interval: int = 30
    # Seconds between resource usage lines (CPU, memory) in the log; 0 = off.
    resource_log_interval: int = 60
    # How shortcut commands are entered in the settings: one of
    # SHORTCUT_EDITORS, "guided" (chosen from lists) or "text" (typed).
    shortcut_editor: str = "guided"

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        """Settings from the JSON data; missing or unusable values fall back
        to their defaults."""
        values = {
            f.name: _coerce(data[f.name], getattr(cls, f.name))
            for f in fields(cls)
            if f.name != "shortcuts" and f.name in data
        }
        if values.get("shortcut_editor", SHORTCUT_EDITORS[0]) not in SHORTCUT_EDITORS:
            del values["shortcut_editor"]
        shortcuts = [
            Shortcut(keys=str(s["keys"]), command=str(s["command"]))
            for s in data.get("shortcuts", [])
            if isinstance(s, dict) and "keys" in s and "command" in s
        ]
        return cls(shortcuts=shortcuts, **values)


def _coerce(value: object, default: object) -> object:
    """value as the type of the setting's default (ints: non-negative)."""
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        return max(0, int(value))
    return str(value)


def load(path: Path | None = None) -> Settings:
    return Settings.from_dict(storage.read_json(path or CONFIG_FILE))


def save(settings: Settings, path: Path | None = None) -> None:
    storage.write_json(path or CONFIG_FILE, asdict(settings))
