"""GUI settings, stored as JSON in the per-user config directory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
        default = cls()
        shortcuts = [
            Shortcut(keys=str(s["keys"]), command=str(s["command"]))
            for s in data.get("shortcuts", [])
            if isinstance(s, dict) and "keys" in s and "command" in s
        ]
        return cls(
            shortcuts=shortcuts,
            notifications=bool(data.get("notifications", default.notifications)),
            language=str(data.get("language", default.language)),
            wake_before_session_end=bool(
                data.get("wake_before_session_end", default.wake_before_session_end)
            ),
            wake_on_startup=bool(data.get("wake_on_startup", default.wake_on_startup)),
            wake_on_display_on=bool(
                data.get("wake_on_display_on", default.wake_on_display_on)
            ),
            status_refresh_interval=_non_negative_int(
                data.get("status_refresh_interval"), default.status_refresh_interval
            ),
            resource_log_interval=_non_negative_int(
                data.get("resource_log_interval"), default.resource_log_interval
            ),
            shortcut_editor=(
                data["shortcut_editor"]
                if data.get("shortcut_editor") in SHORTCUT_EDITORS
                else default.shortcut_editor
            ),
        )


def _non_negative_int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0, int(value))


def load(path: Path | None = None) -> Settings:
    return Settings.from_dict(storage.read_json(path or CONFIG_FILE))


def save(settings: Settings, path: Path | None = None) -> None:
    storage.write_json(path or CONFIG_FILE, asdict(settings))
