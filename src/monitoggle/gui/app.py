"""System tray app: switch monitors from the tray menu or via global shortcuts."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path

from PySide6.QtCore import (
    QDir,
    QLibraryInfo,
    QLocale,
    QLockFile,
    QObject,
    QRectF,
    Qt,
    QTimer,
    QTranslator,
    QUrl,
    Signal,
)
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QDesktopServices, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .. import APP_NAME, DISPLAY_NAME, core, logs, monitor_settings
from ..version import get_version
from . import autostart, config, hotkeys, i18n, session_events
from .commands import CommandResult, run_command
from .hotkey_listeners import HotkeyManager, unsupported_reason
from .i18n import tr
from .monitor_state import MonitorState, forget_inputs, snapshot
from .resources import MB, ResourceLogger, ResourceMeter
from .settings_dialog import SettingsDialog

logger = logging.getLogger(APP_NAME)

NOTIFY_MS = 3000
RESOURCE_VIEW_MS = 2000  # CPU/RAM line in the menu, while it is open
# After the display signal is back: when to check the monitors (ms).
DISPLAY_WAKE_DELAYS_MS = (2000, 8000)


def title_with_version() -> str:
    return f"{DISPLAY_NAME} {get_version()}"


# --- Icon -------------------------------------------------------------------------

SCREEN_ON = QColor("#3b82f6")
SCREEN_OFF = QColor("#374151")
SCREEN_UNKNOWN = QColor("#9ca3af")


def make_icon(states: list[bool | None]) -> QIcon:
    """A monitor glyph; the screen shows the share of monitors that are on."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = size / 64
        frame = QRectF(4 * s, 8 * s, 56 * s, 38 * s)
        screen = frame.adjusted(5 * s, 5 * s, -5 * s, -5 * s)

        p.setPen(QPen(QColor("#111827"), max(1.0, 2 * s)))
        p.setBrush(QColor("#e5e7eb"))
        p.drawRoundedRect(frame, 4 * s, 4 * s)
        p.drawRect(QRectF(27 * s, 46 * s, 10 * s, 8 * s))  # stand
        p.drawRoundedRect(QRectF(16 * s, 53 * s, 32 * s, 5 * s), 2 * s, 2 * s)

        p.setPen(Qt.PenStyle.NoPen)
        known = [on for on in states if on is not None]
        if not known:
            p.fillRect(screen, SCREEN_UNKNOWN)
        else:
            p.fillRect(screen, SCREEN_OFF)
            share = sum(known) / len(known)
            p.fillRect(
                QRectF(screen.left(), screen.top(), screen.width() * share, screen.height()),
                SCREEN_ON,
            )
        p.end()
        icon.addPixmap(pixmap)
    return icon


# --- Background worker ---------------------------------------------------------------


class _Bridge(QObject):
    # Emitted from the worker thread; Qt queues them into the GUI thread.
    status_ready = Signal(object)  # list[MonitorState] | None
    command_done = Signal(object)  # CommandResult


class Worker:
    """Runs DDC/CI work off the GUI thread, one job at a time (so commands
    and status queries never talk to a monitor concurrently)."""

    def __init__(self) -> None:
        self.bridge = _Bridge()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ddc")
        self._refresh_pending = False

    def refresh(self) -> None:
        if self._refresh_pending:
            return
        self._refresh_pending = True
        self._pool.submit(self._refresh)

    def _refresh(self) -> None:
        self._refresh_pending = False
        try:
            states = snapshot()
        except Exception:
            logger.exception("Could not query monitors.")
            states = None
        self.bridge.status_ready.emit(states)

    def run(self, command: str) -> None:
        self._pool.submit(self._run, command)

    def _run(self, command: str) -> None:
        try:
            result = run_command(command)
        except Exception as exc:
            logger.exception("Command failed: %s", command)
            result = CommandResult(command, 1, errors=[str(exc) or type(exc).__name__])
        self.bridge.command_done.emit(result)

    def call(self, fn: Callable[[], object], timeout: float | None) -> object:
        """Runs fn in the queue like any job. With a timeout, blocks until it
        is done and returns its result (None on timeout or error); without,
        returns right away and refreshes the status afterwards."""
        try:
            future = self._pool.submit(self._guarded, fn)
        except RuntimeError:  # already shut down
            return None
        if timeout is None:
            future.add_done_callback(lambda _f: self.refresh())
            return None
        try:
            return future.result(timeout=timeout)
        except FutureTimeout:
            logger.warning("%s did not finish within %s s.", fn.__name__, timeout)
            return None

    @staticmethod
    def _guarded(fn: Callable[[], object]) -> object:
        try:
            return fn()
        except Exception:
            logger.exception("%s failed.", fn.__name__)
            return None

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


# --- Tray -----------------------------------------------------------------------------


class TrayApp(QObject):
    def __init__(self, app: QApplication, settings: config.Settings) -> None:
        super().__init__()
        self.app = app
        self.settings = settings
        self.monitors: list[MonitorState] = []
        self._monitor_actions: list[QAction] = []
        self.menu: QMenu | None = None

        self.worker = Worker()
        self.worker.bridge.status_ready.connect(self._on_status)
        self.worker.bridge.command_done.connect(self._on_command_done)

        self.hotkeys = HotkeyManager(self)
        self.hotkeys.triggered.connect(self._on_hotkey)

        self._resource_meter = ResourceMeter()
        self._resource_view_timer = QTimer(self)
        self._resource_view_timer.timeout.connect(self._update_resource_action)

        self.tray = QSystemTrayIcon(make_icon([]), self)
        self.tray.setToolTip(title_with_version())
        self._build_menu()
        self.tray.activated.connect(self._on_activated)
        self.app.setWindowIcon(make_icon([True]))

        self._apply_hotkeys(show_errors=True)
        self.tray.show()
        self.worker.refresh()
        if self.settings.wake_on_startup:
            logger.info("Startup: turning the monitors back on if all are off.")
            self.worker.call(core.wake_if_all_off, None)

        # Display signal switched off by the system (idle, lock screen), and
        # the monitors the lock hook turned on meanwhile (see
        # _on_display_state); the set is only used on the worker thread.
        self._display_off = False
        self._woken_while_display_off: set[str] = set()
        self.session_events = session_events.create(
            self._before_session_end, self._on_display_state
        )

        # Picks up changes made elsewhere, e.g. with a monitor's power button.
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self.worker.refresh)
        self._apply_status_refresh()

        self._resource_logger = ResourceLogger()
        self._resource_timer = QTimer(self)
        self._resource_timer.timeout.connect(self._resource_logger.log)
        self._apply_resource_logging()

    # --- menu

    def _build_menu(self) -> None:
        """(Re)builds the menu in the current language."""
        old = self.menu
        if old is not None:
            self._clear_monitor_actions()

        self.menu = menu = QMenu()
        menu.aboutToShow.connect(self.worker.refresh)
        menu.aboutToShow.connect(self._on_menu_shown)
        menu.aboutToHide.connect(self._resource_view_timer.stop)

        header = menu.addAction(tr("Monitors"))
        header.setEnabled(False)
        self._monitor_anchor = menu.addSeparator()
        if self.monitors:
            self._update_monitor_actions()
        else:
            self._set_monitor_placeholder(tr("Detecting monitors…"))

        menu.addAction(tr("All on"), lambda: self.worker.run("all"))
        menu.addAction(tr("All off"), lambda: self.worker.run("off-all"))
        menu.addAction(tr("Toggle all"), lambda: self.worker.run("toggle-all"))
        self._input_menu = menu.addMenu(tr("Input source"))
        self._input_layout: list[tuple[str, str, tuple[tuple[int, str], ...]]] | None = None
        self._update_input_menu()
        menu.addSeparator()
        # Also re-reads the supported inputs, e.g. after a monitor was swapped.
        menu.addAction(tr("Refresh"), lambda: self.worker.call(forget_inputs, None))
        menu.addAction(tr("Settings…"), self.open_settings)
        menu.addAction(tr("Open log file"), self._open_log)
        self._setup_action = None
        if sys.platform.startswith("linux"):
            self._setup_action = menu.addAction(
                tr("Set up DDC/CI access…"), lambda: self.worker.run("setup --yes")
            )
            self._update_setup_action()
        menu.addSeparator()
        version = menu.addAction(title_with_version())
        version.setEnabled(False)
        self._resource_action = menu.addAction("")
        self._resource_action.setEnabled(False)
        self._update_resource_action()
        menu.addAction(tr("Quit"), self.quit)

        self.tray.setContextMenu(menu)
        if old is not None:
            old.deleteLater()

    def _clear_monitor_actions(self) -> None:
        for action in self._monitor_actions:
            self.menu.removeAction(action)
            action.deleteLater()
        self._monitor_actions = []

    def _set_monitor_placeholder(self, text: str) -> None:
        self._clear_monitor_actions()
        action = QAction(text, self)
        action.setEnabled(False)
        self._insert_monitor_action(action)

    def _insert_monitor_action(self, action: QAction) -> None:
        # Monitor entries go between the "Monitors" header and the separator.
        self.menu.insertAction(self._monitor_anchor, action)
        self._monitor_actions.append(action)

    def _update_monitor_actions(self) -> None:
        if not self.monitors:
            self._set_monitor_placeholder(tr("No monitors found"))
            return

        names = [a.data() for a in self._monitor_actions]
        if names != [m.name for m in self.monitors]:
            self._clear_monitor_actions()
            for m in self.monitors:
                action = QAction(self)
                action.setData(m.name)
                action.setCheckable(True)
                action.triggered.connect(
                    lambda checked, name=m.name: self.worker.run(
                        f"{'on' if checked else 'off'} {name}"
                    )
                )
                self._insert_monitor_action(action)

        # Update in place, so an open menu reflects the new state.
        for action, m in zip(self._monitor_actions, self.monitors, strict=True):
            text = m.label
            if not m.has_ddc:
                text += "  " + tr("(no DDC/CI)")
            elif m.on is None:
                text += "  " + tr("(status unknown)")
            action.setText(text)
            action.setEnabled(m.has_ddc)
            action.setChecked(bool(m.on))

    def _update_input_menu(self) -> None:
        """One submenu per monitor with known active inputs, listing them
        with the current one checked; hidden if there is none."""
        monitors = [m for m in self.monitors if m.active_inputs]
        layout = [
            (m.name, m.label, tuple((c, m.settings.input_label(c)) for c in m.active_inputs))
            for m in monitors
        ]
        if layout != self._input_layout:
            self._input_layout = layout
            for sub_action in self._input_menu.actions():
                sub_action.menu().deleteLater()
            self._input_menu.clear()
            for m in monitors:
                sub = self._input_menu.addMenu(m.label)
                group = QActionGroup(sub)
                for code in m.active_inputs:
                    source = monitor_settings.input_source_name(code)
                    action = group.addAction(m.settings.input_label(code))
                    action.setCheckable(True)
                    action.setData(code)
                    action.triggered.connect(
                        lambda _checked, source=source, name=m.name: self.worker.run(
                            f"input {source} {name}"
                        )
                    )
                    sub.addAction(action)
        self._input_menu.menuAction().setVisible(bool(monitors))

        # Update in place, so an open menu reflects the new state.
        for sub_action, m in zip(self._input_menu.actions(), monitors, strict=True):
            for action in sub_action.menu().actions():
                action.setChecked(action.data() == m.input)

    def _update_setup_action(self) -> None:
        if self._setup_action is None:
            return
        from ..linux_setup import has_i2c_access

        self._setup_action.setVisible(not has_i2c_access())

    def _on_menu_shown(self) -> None:
        # First reading: average since the menu was last open; then live.
        self._update_resource_action()
        self._resource_view_timer.start(RESOURCE_VIEW_MS)

    def _update_resource_action(self) -> None:
        cpu, rss = self._resource_meter.read()
        text = tr("CPU {cpu}%", cpu=f"{cpu:.1f}")
        if rss is not None:
            text += " · " + tr("RAM {ram} MB", ram=f"{rss / MB:.0f}")
        self._resource_action.setText(text)

    def _update_tooltip(self) -> None:
        if not self.monitors:
            self.tray.setToolTip(title_with_version())
            return
        known = [m.on for m in self.monitors if m.on is not None]
        total = len(self.monitors)
        tip = title_with_version() + "\n" + tr("{on} of {total} monitors on", on=sum(known), total=total)
        if len(known) < total:
            tip += " " + tr("({count} unknown)", count=total - len(known))
        self.tray.setToolTip(tip)

    # --- events

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Left click opens the same menu as right click.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.menu.popup(QCursor.pos())

    def _on_status(self, states: list[MonitorState] | None) -> None:
        if states is None:
            self._set_monitor_placeholder(tr("Could not query monitors (see log)"))
            return
        self.monitors = states
        self._update_monitor_actions()
        self._update_input_menu()
        self._update_setup_action()
        self.tray.setIcon(make_icon([m.on for m in states]))
        self._update_tooltip()

    def _on_command_done(self, result: CommandResult) -> None:
        if not result.ok:
            text = "\n".join(result.errors) or tr(
                "'{command}' failed.", command=result.command
            )
            self.tray.showMessage(
                DISPLAY_NAME, text, QSystemTrayIcon.MessageIcon.Warning, NOTIFY_MS * 2
            )
        elif self.settings.notifications and result.messages:
            self.tray.showMessage(
                DISPLAY_NAME,
                "\n".join(result.messages),
                QSystemTrayIcon.MessageIcon.Information,
                NOTIFY_MS,
            )
        self.worker.refresh()

    def _on_hotkey(self, index: int) -> None:
        if 0 <= index < len(self._hotkey_commands):
            self.worker.run(self._hotkey_commands[index])

    # --- actions

    def _apply_hotkeys(self, show_errors: bool) -> None:
        keys: list[hotkeys.Hotkey] = []
        self._hotkey_commands: list[str] = []
        # (shortcut, English reason for the log, translated reason for display)
        failures: list[tuple[object, str, str]] = []
        for s in self.settings.shortcuts:
            try:
                keys.append(hotkeys.parse(s.keys))
            except hotkeys.HotkeyError as exc:
                failures.append((s.keys, str(exc), exc.translated()))
                continue
            self._hotkey_commands.append(s.command)
        failures += [
            (key, reason, tr(reason)) for key, reason in self.hotkeys.set_hotkeys(keys)
        ]
        for key, reason, _ in failures:
            logger.warning("Could not register shortcut %s: %s", key, reason)
        if failures and show_errors:
            lines = "\n".join(f"{key}: {text}" for key, _, text in failures)
            self.tray.showMessage(
                DISPLAY_NAME,
                tr("Some shortcuts could not be registered:") + "\n" + lines,
                QSystemTrayIcon.MessageIcon.Warning,
                NOTIFY_MS * 2,
            )
        elif keys and (unsupported := unsupported_reason()):
            logger.warning("Global shortcuts disabled: %s", unsupported)

    def _before_session_end(self, reason: str, timeout: float | None) -> None:
        """Lock, logoff/shutdown or sleep is imminent: make sure nobody is
        left with every monitor switched off."""
        if not self.settings.wake_before_session_end:
            return
        logger.info("%s: turning the monitors back on if all are off.", reason)
        self.worker.call(self._wake_and_remember, timeout)

    def _wake_and_remember(self) -> None:
        # Worker thread. Without a video signal a monitor may acknowledge
        # "on" and ignore it; remember those for when the display is back.
        woken = core.wake_if_all_off()
        if self._display_off:
            self._woken_while_display_off.update(woken)

    def _on_display_state(self, on: bool) -> None:
        """The system switched the display signal off or back on (idle
        timeout, lock screen, mouse moved). Back on: a second chance to
        turn the monitors on, now that they receive a signal again."""
        if not on:
            self._display_off = True
            return
        if not self._display_off:  # the initial report, or a repeat
            return
        self._display_off = False
        if not self.settings.wake_on_display_on:
            self.worker.call(self._woken_while_display_off.clear, None)
            return
        logger.info("Display on: turning the monitors back on if all are off.")
        # Monitors coming out of standby need a moment before they answer
        # DDC/CI; a second try catches the slow ones.
        for delay in DISPLAY_WAKE_DELAYS_MS:
            QTimer.singleShot(delay, lambda: self.worker.call(self._wake_after_display_on, None))

    def _wake_after_display_on(self) -> None:
        # Worker thread.
        again, self._woken_while_display_off = self._woken_while_display_off, set()
        if again:
            core.turn_on_again(sorted(again))
        core.wake_if_all_off()

    def _apply_status_refresh(self) -> None:
        self._status_timer.stop()
        if self.settings.status_refresh_interval > 0:
            self._status_timer.start(self.settings.status_refresh_interval * 1000)

    def _apply_resource_logging(self) -> None:
        interval = self.settings.resource_log_interval
        self._resource_timer.stop()
        if interval > 0:
            self._resource_logger.log()  # baseline right away
            self._resource_timer.start(interval * 1000)

    def open_settings(self) -> None:
        # Suspend the shortcuts while recording, so pressing an existing one
        # records it instead of triggering it.
        self.hotkeys.clear()
        dialog = SettingsDialog(self.settings, self.monitors, monitor_settings.load())
        try:
            if dialog.exec() == SettingsDialog.DialogCode.Accepted:
                new, old = dialog.result_settings, self.settings
                self.settings = new
                try:
                    config.save(new)
                    monitor_settings.save(dialog.result_monitor_settings)
                except OSError as exc:
                    QMessageBox.warning(
                        None, DISPLAY_NAME, tr("Could not save settings: {error}", error=exc)
                    )
                self.worker.refresh()  # new names in the menu
                if new.language != old.language:
                    apply_language(self.app, new.language)
                    self._build_menu()
                    self._update_tooltip()
                if new.status_refresh_interval != old.status_refresh_interval:
                    self._apply_status_refresh()
                if new.resource_log_interval != old.resource_log_interval:
                    self._apply_resource_logging()
        finally:
            self._apply_hotkeys(show_errors=True)

    def _open_log(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs.LOG_FILE)))

    def quit(self) -> None:
        if self.session_events is not None:
            self.session_events.close_hooks()
        self.hotkeys.clear()
        self.worker.shutdown()
        self.tray.hide()
        self.app.quit()


# --- Language ------------------------------------------------------------------------

_qt_translator: QTranslator | None = None


def apply_language(app: QApplication, setting: str) -> None:
    """Switches our strings and Qt's own (dialog buttons etc.) to a language."""
    global _qt_translator
    code = i18n.resolve(setting, QLocale.system().uiLanguages())
    i18n.set_language(code)
    logger.info("Language: %s (setting: %s)", code, setting)

    if _qt_translator is not None:
        app.removeTranslator(_qt_translator)
        _qt_translator = None
    if code != i18n.SOURCE_LANGUAGE:
        translator = QTranslator(app)
        path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if translator.load(f"qtbase_{code}", path):
            app.installTranslator(translator)
            _qt_translator = translator
        else:
            logger.info("No Qt translations for %s in %s.", code, path)


# --- Entry point ---------------------------------------------------------------------

TRAY_WAIT_ATTEMPTS = 15  # x 2 s: the tray may start after us at login


def use_light_font_engine() -> None:
    """Windows: render text with Qt's GDI font engine instead of DirectWrite.

    DirectWrite loads the whole system font database on first text output
    and keeps a handle to every font file: about +60 MB working set and +600
    handles, just to draw a small menu. GDI costs a fraction of that; the
    only loss (color emoji) doesn't matter here. An explicit QT_QPA_PLATFORM
    wins.
    """
    if sys.platform == "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=gdi")


def main() -> int:
    logs.configure_logging(console=sys.stdout is not None)
    logger.info("GUI %s started. Log file: %s", get_version(), logs.LOG_FILE)

    use_light_font_engine()
    app = QApplication(sys.argv)
    app.setApplicationName(DISPLAY_NAME)
    app.setQuitOnLastWindowClosed(False)

    settings = config.load()
    apply_language(app, settings.language)

    lock = QLockFile(str(Path(QDir.tempPath()) / f"{APP_NAME}-gui.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(
            None, DISPLAY_NAME, tr("MoniToggle is already running in the system tray.")
        )
        return 0

    autostart.refresh()

    tray_app: list[TrayApp] = []
    attempts = 0

    def start() -> None:
        nonlocal attempts
        if QSystemTrayIcon.isSystemTrayAvailable():
            tray_app.append(TrayApp(app, settings))
            return
        attempts += 1
        if attempts < TRAY_WAIT_ATTEMPTS:
            QTimer.singleShot(2000, start)
            return
        QMessageBox.critical(
            None,
            DISPLAY_NAME,
            tr(
                "No system tray found. On GNOME, install the 'AppIndicator and "
                "KStatusNotifierItem Support' extension."
            ),
        )
        app.quit()

    start()
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
