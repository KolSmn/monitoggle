"""Translations for the tray app (Qt-free).

English is the source language: every user-facing string is written in
English in the code and wrapped in tr() (translate now) or N_() (only mark
it, translate later with tr() - for text that is also logged, since log
files stay English). Each other language is a module in this package whose
MESSAGES dict maps those English strings to the translation; a missing
entry falls back to English.

Adding a language: copy de.py to <code>.py (ISO 639-1 code), translate the
values, and register the module in _MODULES below. tests/test_gui.py checks
that every language covers all strings, with matching placeholders.

Placeholders:
- GUI strings use str.format fields: tr("{on} of {total} monitors on", on=1, total=2)
- Messages from the core (log records, UserError) keep their %-style
  templates and are translated with tr_template() when displayed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import ModuleType

from . import de

SOURCE_LANGUAGE = "en"
AUTO = "auto"

_MODULES: dict[str, ModuleType] = {"de": de}

# Language code -> native name, for the language picker.
LANGUAGES: dict[str, str] = {
    SOURCE_LANGUAGE: "English",
    **{code: module.NAME for code, module in _MODULES.items()},
}
CATALOGS: dict[str, Mapping[str, str]] = {
    code: module.MESSAGES for code, module in _MODULES.items()
}

_current = SOURCE_LANGUAGE


def N_(text: str, /) -> str:  # noqa: N802 (gettext convention)
    """Marks text for translation without translating it."""
    return text


def resolve(setting: str, system_languages: Iterable[str]) -> str:
    """Language to use for a setting ("auto" or a code), given the system's
    preferred UI languages (e.g. ["de-DE", "en-US"])."""
    if setting in LANGUAGES:
        return setting
    for tag in system_languages:
        code = tag.replace("_", "-").split("-")[0].lower()
        if code in LANGUAGES:
            return code
    return SOURCE_LANGUAGE


def set_language(code: str) -> None:
    global _current
    _current = code if code in LANGUAGES else SOURCE_LANGUAGE


def current_language() -> str:
    return _current


def _lookup(text: str) -> str:
    return CATALOGS.get(_current, {}).get(text, text)


def tr(text: str, /, **fields: object) -> str:
    translated = _lookup(text)
    if not fields:
        return translated
    try:
        return translated.format(**fields)
    except (KeyError, IndexError, ValueError):
        return text.format(**fields)


def tr_template(template: str, args: object = ()) -> str:
    """Translates a %-style message template (log record / UserError) and
    fills in its arguments."""
    translated = _lookup(template)
    if not args:
        return translated
    try:
        return translated % args
    except (TypeError, ValueError, KeyError):
        return template % args
