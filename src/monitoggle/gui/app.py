"""Entry point of the tray app: single instance, language, waiting for the tray."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QDir, QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from .. import APP_NAME, DISPLAY_NAME, logs
from ..version import get_version
from . import autostart, config
from .i18n import tr
from .language import apply_language
from .tray import TrayApp

logger = logging.getLogger(APP_NAME)

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
