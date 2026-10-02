"""Start the tray app at login: HKCU Run key on Windows, XDG autostart on Linux."""

from __future__ import annotations

import contextlib
import subprocess
import sys
from pathlib import Path

from .. import APP_NAME, DISPLAY_NAME, storage

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def desktop_file() -> Path:
    return storage.xdg_dir("XDG_CONFIG_HOME", ".config") / "autostart" / f"{APP_NAME}.desktop"


def launch_command() -> list[str]:
    """The command line that starts this GUI the way it is running now."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    python = Path(sys.executable)
    if sys.platform == "win32":
        # pythonw.exe: no console window at login.
        pythonw = python.with_name("pythonw.exe")
        if pythonw.exists():
            python = pythonw
    return [str(python), "-m", "monitoggle.gui"]


def _desktop_quote(arg: str) -> str:
    # Quoting rules of the Exec key (Desktop Entry Specification).
    if arg and not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`'):
        return arg
    escaped = "".join("\\" + c if c in '"`$\\' else c for c in arg)
    return f'"{escaped}"'


def desktop_entry(command: list[str]) -> str:
    exec_line = " ".join(_desktop_quote(a) for a in command).replace("%", "%%")
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={DISPLAY_NAME}\n"
        "Comment=Turn monitors on and off via DDC/CI\n"
        f"Exec={exec_line}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def _run_key(access: int | None = None):  # -> winreg.HKEYType
    """The HKCU Run key (Windows only); read access by default."""
    import winreg

    return winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ if access is None else access
    )


def is_supported() -> bool:
    return sys.platform == "win32" or sys.platform.startswith("linux")


def is_enabled() -> bool:
    if sys.platform == "win32":
        import winreg

        try:
            with _run_key() as key:
                winreg.QueryValueEx(key, APP_NAME)
        except OSError:
            return False
        return True
    return desktop_file().is_file()


def _remove_entry() -> None:
    if sys.platform == "win32":
        import winreg

        with _run_key(winreg.KEY_SET_VALUE) as key, contextlib.suppress(FileNotFoundError):
            winreg.DeleteValue(key, APP_NAME)
        return
    desktop_file().unlink(missing_ok=True)


def set_enabled(enabled: bool) -> None:
    if not enabled:
        _remove_entry()
        return
    if sys.platform == "win32":
        import winreg

        with _run_key(winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(
                key,
                APP_NAME,
                0,
                winreg.REG_SZ,
                subprocess.list2cmdline(launch_command()),
            )
        return
    path = desktop_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(desktop_entry(launch_command()), encoding="utf-8")


def refresh() -> None:
    """Re-points an existing autostart entry at the current executable
    (e.g. after the app was moved or updated to a new path). Only done for
    the standalone executable, so a quick run from source doesn't hijack it."""
    if getattr(sys, "frozen", False) and is_supported() and is_enabled():
        set_enabled(True)
