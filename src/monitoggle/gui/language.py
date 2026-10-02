"""Switching the tray app's language: our own strings and Qt's."""

from __future__ import annotations

import logging

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication

from .. import APP_NAME
from . import i18n

logger = logging.getLogger(APP_NAME)

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
