"""System-wide hotkey registration: RegisterHotKey on Windows, XGrabKey on X11.

Wayland has no API for an app to grab keys globally; there the user binds
the equivalent CLI command in the desktop's own keyboard settings instead.
"""

from __future__ import annotations

import logging
import os
import select
import sys
import threading
from collections.abc import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Signal

from . import hotkeys
from .hotkeys import Hotkey
from .i18n import N_

logger = logging.getLogger(__name__)

# (hotkey, reason) for each hotkey that could not be registered. Reasons are
# English (they are logged); translate them with tr() for display.
Failures = list[tuple[Hotkey, str]]


def unsupported_reason() -> str | None:
    """Why global hotkeys can't work in this session, or None if they can
    (English; translate with tr() for display)."""
    if sys.platform == "win32":
        return None
    if sys.platform.startswith("linux"):
        if (
            os.environ.get("XDG_SESSION_TYPE") == "wayland"
            or os.environ.get("WAYLAND_DISPLAY")
        ):
            return N_(
                "Global shortcuts are not available on Wayland. Bind the CLI "
                "command in your desktop's keyboard settings instead."
            )
        if not os.environ.get("DISPLAY"):
            return N_("No X11 display found.")
        try:
            import Xlib  # noqa: F401
        except ImportError:
            return N_("python-xlib is not installed.")
        return None
    return N_("Global shortcuts are not supported on this platform.")


class HotkeyManager(QObject):
    """Registers a list of hotkeys; emits triggered(index) when one is pressed."""

    triggered = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._backend: _WindowsHotkeys | _X11Hotkeys | None = None

    def set_hotkeys(self, keys: list[Hotkey]) -> Failures:
        self.clear()
        if not keys or unsupported_reason() is not None:
            return []
        if sys.platform == "win32":
            self._backend = _WindowsHotkeys(self.triggered.emit)
        else:
            self._backend = _X11Hotkeys(self.triggered.emit)
        return self._backend.register(keys)

    def clear(self) -> None:
        if self._backend is not None:
            self._backend.unregister()
            self._backend = None


# --- Windows ---------------------------------------------------------------------

WM_HOTKEY = 0x0312
ERROR_HOTKEY_ALREADY_REGISTERED = 1409


class _WindowsHotkeys(QAbstractNativeEventFilter):
    # Registered without a window: WM_HOTKEY then goes to the GUI thread's
    # message queue, where Qt's event dispatcher hands it to this filter.

    def __init__(self, on_trigger: Callable[[int], None]) -> None:
        import ctypes

        super().__init__()
        self._on_trigger = on_trigger
        self._ids: dict[int, int] = {}  # hotkey id -> index
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)

    def register(self, keys: list[Hotkey]) -> Failures:
        import ctypes

        failures: Failures = []
        for index, key in enumerate(keys):
            hotkey_id = index + 1
            if self._user32.RegisterHotKey(
                None, hotkey_id, hotkeys.win_modifiers(key), key.vk
            ):
                self._ids[hotkey_id] = index
                continue
            err = ctypes.get_last_error()
            reason = (
                N_("already in use by another application")
                if err == ERROR_HOTKEY_ALREADY_REGISTERED
                else ctypes.FormatError(err).strip()
            )
            failures.append((key, reason))
        QCoreApplication.instance().installNativeEventFilter(self)
        return failures

    def unregister(self) -> None:
        app = QCoreApplication.instance()
        if app is not None:
            app.removeNativeEventFilter(self)
        for hotkey_id in self._ids:
            self._user32.UnregisterHotKey(None, hotkey_id)
        self._ids.clear()

    def nativeEventFilter(self, eventType, message):  # noqa: N802 (Qt API)
        if bytes(eventType) == b"windows_generic_MSG":
            from ctypes import wintypes

            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.hWnd is None:
                index = self._ids.get(msg.wParam)
                if index is not None:
                    self._on_trigger(index)
                    return True, 0
        return False, 0


# --- X11 -------------------------------------------------------------------------

_X11_RELEVANT_MASK = (
    hotkeys.X_SHIFT_MASK
    | hotkeys.X_CONTROL_MASK
    | hotkeys.X_MOD1_MASK
    | hotkeys.X_MOD4_MASK
)


class _X11Hotkeys:
    # python-xlib connections are not thread-safe, so a dedicated thread owns
    # its own connection: it grabs the keys, then waits for key presses.
    # Closing that connection releases all grabs.

    def __init__(self, on_trigger: Callable[[int], None]) -> None:
        self._on_trigger = on_trigger
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._failures: Failures = []
        self._thread: threading.Thread | None = None

    def register(self, keys: list[Hotkey]) -> Failures:
        self._thread = threading.Thread(
            target=self._run, args=(keys,), name="x11-hotkeys", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout=5):
            return [(k, N_("X11 did not respond")) for k in keys]
        return self._failures

    def unregister(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self, keys: list[Hotkey]) -> None:
        from Xlib import X, XK, display, error

        try:
            disp = display.Display()
        except Exception:
            logger.exception("Cannot open the X display.")
            self._failures = [(k, N_("cannot open the X display")) for k in keys]
            self._ready.set()
            return

        try:
            root = disp.screen().root
            lookup: dict[tuple[int, int], int] = {}
            for index, key in enumerate(keys):
                keycode = disp.keysym_to_keycode(XK.string_to_keysym(key.keysym_name))
                if not keycode:
                    self._failures.append((key, N_("key not on this keyboard")))
                    continue
                mods = hotkeys.x11_modifiers(key)
                catcher = error.CatchError(error.BadAccess)
                for extra in hotkeys.X_IGNORED_MASKS:
                    root.grab_key(
                        keycode,
                        mods | extra,
                        True,
                        X.GrabModeAsync,
                        X.GrabModeAsync,
                        onerror=catcher,
                    )
                disp.sync()
                if catcher.get_error():
                    for extra in hotkeys.X_IGNORED_MASKS:
                        root.ungrab_key(keycode, mods | extra)
                    self._failures.append(
                        (key, N_("already in use by another application"))
                    )
                    continue
                lookup[(keycode, mods)] = index
            self._ready.set()

            while not self._stop.is_set():
                select.select([disp], [], [], 0.5)
                while disp.pending_events():
                    event = disp.next_event()
                    if event.type != X.KeyPress:
                        continue
                    index = lookup.get((event.detail, event.state & _X11_RELEVANT_MASK))
                    if index is not None:
                        self._on_trigger(index)
        except Exception:
            logger.exception("X11 hotkey listener failed.")
        finally:
            self._ready.set()
            disp.close()
