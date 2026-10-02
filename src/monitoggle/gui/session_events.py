"""Hooks for the moments right before the session is locked or ends, and
for the display signal going off and on again.

The tray app uses them to turn the monitors back on if all of them are off:
at the lock/login screen its shortcuts don't work, and a monitor switched
off via DDC/CI might then only come back with its power button. A monitor
without a video signal (the system switched the display off after being
idle) may ignore that, so the display coming back on is a second chance.

- Windows: a hidden top-level window receives WM_WTSSESSION_CHANGE (lock),
  WM_QUERYENDSESSION (logoff/shutdown) and WM_POWERBROADCAST (sleep, and
  the display state via GUID_CONSOLE_DISPLAY_STATE).
- Linux: the screensaver's ActiveChanged signal (lock, and as the display
  state: active = blanked), logind's PrepareForSleep/PrepareForShutdown
  (with a delay inhibitor, so there is time to act), and SIGTERM (session
  end).
"""

from __future__ import annotations

import ctypes
import logging
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QObject, QSocketNotifier, Qt, Slot
from PySide6.QtWidgets import QWidget

from .i18n import tr

logger = logging.getLogger(__name__)

LOCK = "Lock"
SESSION_END = "Logoff/shutdown"
SLEEP = "Sleep"

# callback(reason, timeout): timeout is how long the callback may block
# (seconds), or None if it should not block at all.
Callback = Callable[[str, float | None], None]
# display_callback(on): the display signal went on (True) or off (False).
# May repeat a state; must not block.
DisplayCallback = Callable[[bool], None]

SESSION_END_TIMEOUT = 10.0
WINDOWS_SLEEP_TIMEOUT = 4.0  # Windows allows ~2 s for sleep
# logind delays sleep and shutdown for a delay inhibitor up to
# InhibitDelayMaxSec, 5 s by default.
LOGIND_DELAY_TIMEOUT = 4.0
LOCK_DEBOUNCE = 5.0  # several sources may report the same lock


def create(
    callback: Callback, display_callback: DisplayCallback | None = None
) -> QObject | None:
    """The session hooks for this platform, or None where unsupported."""
    display_callback = display_callback or (lambda _on: None)
    try:
        if sys.platform == "win32":
            return _WindowsSessionEvents(callback, display_callback)
        if sys.platform.startswith("linux"):
            return _LinuxSessionEvents(callback, display_callback)
    except Exception:
        logger.exception("Could not set up session event hooks.")
    return None


# --- Windows ---------------------------------------------------------------------

WM_QUERYENDSESSION = 0x0011
WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004
WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
NOTIFY_FOR_THIS_SESSION = 0

PBT_POWERSETTINGCHANGE = 0x8013
DEVICE_NOTIFY_WINDOW_HANDLE = 0
DISPLAY_OFF = 0


class GUID(ctypes.Structure):
    # Fixed-width types: the same layout on every platform.
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_uint8 * 8),
    ]

    @classmethod
    def of(cls, data1: int, data2: int, data3: int, data4: tuple[int, ...]) -> GUID:
        return cls(data1, data2, data3, (ctypes.c_uint8 * 8)(*data4))


# GUID_CONSOLE_DISPLAY_STATE {6FE69556-704A-47A0-8F24-C28D936FDA47}: the
# display of the console session; data 0 = off, 1 = on, 2 = dimmed.
DISPLAY_STATE_GUID = GUID.of(
    0x6FE69556, 0x704A, 0x47A0, (0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47)
)
_DISPLAY_STATE_GUID_BYTES = bytes(DISPLAY_STATE_GUID)


def display_state_from_setting(address: int) -> bool | None:
    """Whether a POWERBROADCAST_SETTING (at address) reports the display as
    on; None if it's about another setting."""
    size = len(_DISPLAY_STATE_GUID_BYTES)
    if ctypes.string_at(address, size) != _DISPLAY_STATE_GUID_BYTES:
        return None
    # Followed by DWORD DataLength and the data: a DWORD for this setting.
    state = ctypes.c_uint32.from_address(address + size + 4).value
    return state != DISPLAY_OFF


class _WindowsSessionEvents(QWidget):
    # A hidden top-level window: broadcasts like WM_QUERYENDSESSION reach
    # top-level windows only, not Qt's message-only helper windows. It is
    # never shown; winId() just creates the native window.

    def __init__(self, callback: Callback, display_callback: DisplayCallback) -> None:
        super().__init__(None, Qt.WindowType.Tool)
        from ctypes import wintypes

        self._callback = callback
        self._display_callback = display_callback
        self._hwnd = int(self.winId())
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.ShutdownBlockReasonCreate.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        self._user32.ShutdownBlockReasonDestroy.argtypes = [wintypes.HWND]
        self._wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
        self._wtsapi32.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
        self._wtsapi32.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
        if not self._wtsapi32.WTSRegisterSessionNotification(
            self._hwnd, NOTIFY_FOR_THIS_SESSION
        ):
            logger.warning(
                "Could not register for session lock notifications (error %d).",
                ctypes.get_last_error(),
            )

        # Display on/off; Windows reports the current state right away.
        self._user32.RegisterPowerSettingNotification.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD
        ]
        self._user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
        self._user32.UnregisterPowerSettingNotification.argtypes = [wintypes.HANDLE]
        self._display_notify = self._user32.RegisterPowerSettingNotification(
            self._hwnd, ctypes.byref(DISPLAY_STATE_GUID), DEVICE_NOTIFY_WINDOW_HANDLE
        )
        if not self._display_notify:
            logger.warning(
                "Could not register for display state notifications (error %d).",
                ctypes.get_last_error(),
            )

    def close_hooks(self) -> None:
        self._wtsapi32.WTSUnRegisterSessionNotification(self._hwnd)
        if self._display_notify:
            self._user32.UnregisterPowerSettingNotification(self._display_notify)

    def nativeEvent(self, eventType, message):  # noqa: N802 (Qt API)
        if bytes(eventType) != b"windows_generic_MSG":
            return False, 0
        from ctypes import wintypes

        msg = wintypes.MSG.from_address(int(message))
        if msg.message == WM_WTSSESSION_CHANGE and msg.wParam == WTS_SESSION_LOCK:
            self._callback(LOCK, None)
        elif msg.message == WM_QUERYENDSESSION:
            # Shows "MoniToggle: Turning monitors back on" in the shutdown
            # screen while we're busy, instead of just being killed.
            self._user32.ShutdownBlockReasonCreate(
                self._hwnd, tr("Turning the monitors back on")
            )
            try:
                self._callback(SESSION_END, SESSION_END_TIMEOUT)
            finally:
                self._user32.ShutdownBlockReasonDestroy(self._hwnd)
        elif msg.message == WM_POWERBROADCAST and msg.wParam == PBT_APMSUSPEND:
            self._callback(SLEEP, WINDOWS_SLEEP_TIMEOUT)
        elif msg.message == WM_POWERBROADCAST and msg.wParam == PBT_POWERSETTINGCHANGE:
            on = display_state_from_setting(msg.lParam)
            if on is not None:
                self._display_callback(on)
        # Never consume the message: Qt and Windows handle it as usual (and
        # the session end / sleep is never vetoed).
        return False, 0


# --- Linux -----------------------------------------------------------------------

LOGIN1 = "org.freedesktop.login1"
LOGIN1_PATH = "/org/freedesktop/login1"
LOGIN1_MANAGER = "org.freedesktop.login1.Manager"

# (service, path, interface) of the screensaver/lock services of the
# common desktops; each emits ActiveChanged(bool).
SCREENSAVERS = [
    ("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver", "org.freedesktop.ScreenSaver"),
    ("org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver"),
    ("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver"),
]


class _LinuxSessionEvents(QObject):
    def __init__(self, callback: Callback, display_callback: DisplayCallback) -> None:
        super().__init__()
        self._callback = callback
        self._display_callback = display_callback
        self._last_lock = 0.0
        self._inhibitor: subprocess.Popen | None = None
        self._setup_sigterm()
        self._setup_dbus()

    # --- SIGTERM (session end; systemd waits for us before SIGKILL)

    def _setup_sigterm(self) -> None:
        # Python signal handlers only run when Python code runs, not while
        # Qt waits in its C++ event loop; the wakeup fd makes Qt notice.
        self._signal_read, self._signal_write = socket.socketpair()
        self._signal_read.setblocking(False)
        self._signal_write.setblocking(False)
        signal.set_wakeup_fd(self._signal_write.fileno())
        signal.signal(signal.SIGTERM, lambda *_: None)
        self._notifier = QSocketNotifier(
            self._signal_read.fileno(), QSocketNotifier.Type.Read, self
        )
        self._notifier.activated.connect(self._on_signal)

    def _on_signal(self) -> None:
        try:
            data = self._signal_read.recv(64)
        except BlockingIOError:
            return
        if signal.SIGTERM in data:
            logger.info("Received SIGTERM.")
            self._callback(SESSION_END, SESSION_END_TIMEOUT)
            QCoreApplication.quit()

    # --- D-Bus: logind (sleep/shutdown) and screensavers (lock)

    def _setup_dbus(self) -> None:
        from PySide6.QtCore import SLOT
        from PySide6.QtDBus import QDBusConnection

        system = QDBusConnection.systemBus()
        if system.isConnected():
            for name, slot in (
                ("PrepareForSleep", "_on_prepare_for_sleep(bool)"),
                ("PrepareForShutdown", "_on_prepare_for_shutdown(bool)"),
            ):
                if not system.connect(LOGIN1, LOGIN1_PATH, LOGIN1_MANAGER, name, self, SLOT(slot)):
                    logger.warning("Could not subscribe to logind %s.", name)
            self._acquire_inhibitor()
        else:
            logger.warning("No D-Bus system bus: sleep/shutdown hooks disabled.")

        session = QDBusConnection.sessionBus()
        if session.isConnected():
            for service, path, interface in SCREENSAVERS:
                session.connect(
                    service, path, interface, "ActiveChanged", self,
                    SLOT("_on_screensaver_active(bool)"),
                )
        else:
            logger.warning("No D-Bus session bus: lock hook disabled.")

    @Slot(bool)
    def _on_screensaver_active(self, active: bool) -> None:
        now = time.monotonic()
        if active and now - self._last_lock > LOCK_DEBOUNCE:
            self._last_lock = now
            self._callback(LOCK, None)
        # The screensaver blanks the display (off) and gives it back when
        # the user returns (on); several sources may report the same.
        self._display_callback(not active)

    @Slot(bool)
    def _on_prepare_for_sleep(self, starting: bool) -> None:
        if starting:
            self._callback(SLEEP, LOGIND_DELAY_TIMEOUT)
            self._release_inhibitor()  # lets the system go to sleep now
        else:
            self._acquire_inhibitor()  # resumed: ready for the next time

    @Slot(bool)
    def _on_prepare_for_shutdown(self, starting: bool) -> None:
        if starting:
            self._callback(SESSION_END, LOGIND_DELAY_TIMEOUT)
            self._release_inhibitor()
        else:
            self._acquire_inhibitor()  # shutdown was cancelled

    # A logind "delay" inhibitor makes sleep/shutdown wait (up to
    # InhibitDelayMaxSec, 5 s by default) until we release it. It is held
    # by a systemd-inhibit child whose command blocks on its stdin: closing
    # that pipe - or this process dying - ends it and releases the lock.

    def _acquire_inhibitor(self) -> None:
        if self._inhibitor is not None or shutil.which("systemd-inhibit") is None:
            return
        try:
            # systemd-inhibit via PATH on purpose (checked with shutil.which).
            self._inhibitor = subprocess.Popen(  # nosec B607
                [
                    "systemd-inhibit",
                    "--what=sleep:shutdown",
                    "--who=MoniToggle",
                    "--why=Turn the monitors back on first",
                    "--mode=delay",
                    "sh", "-c", "read _",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            logger.exception("Could not start systemd-inhibit.")

    def _release_inhibitor(self) -> None:
        proc, self._inhibitor = self._inhibitor, None
        if proc is None:
            return
        try:
            proc.stdin.close()
            proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()

    def close_hooks(self) -> None:
        self._release_inhibitor()
        signal.set_wakeup_fd(-1)
