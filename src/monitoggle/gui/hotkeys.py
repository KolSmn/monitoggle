"""Global hotkey definitions: parsing and per-platform key codes (Qt-free).

Hotkeys are stored in Qt's portable text form ("Ctrl+Alt+F1"), which is what
the settings dialog's key recorder produces. Only layout-independent keys are
supported (letters, digits, F-keys, navigation keys), so a hotkey means the
same physical key on Windows and Linux.
"""

from __future__ import annotations

import string
from dataclasses import dataclass

from .i18n import N_, tr

# Windows RegisterHotKey modifier flags.
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# X11 XGrabKey modifier masks.
X_SHIFT_MASK = 1 << 0
X_LOCK_MASK = 1 << 1  # Caps Lock
X_CONTROL_MASK = 1 << 2
X_MOD1_MASK = 1 << 3  # Alt
X_MOD2_MASK = 1 << 4  # Num Lock (on practically every setup)
X_MOD4_MASK = 1 << 6  # Super

# Modifier -> (display name, Windows flag, X11 mask), in display order.
_MODIFIERS: dict[str, tuple[str, int, int]] = {
    "ctrl": ("Ctrl", MOD_CONTROL, X_CONTROL_MASK),
    "alt": ("Alt", MOD_ALT, X_MOD1_MASK),
    "shift": ("Shift", MOD_SHIFT, X_SHIFT_MASK),
    "meta": ("Meta", MOD_WIN, X_MOD4_MASK),
}
_MODIFIER_ALIASES = {"control": "ctrl", "win": "meta", "super": "meta"}

# The X11 modifiers a hotkey can use; other bits (lock keys, mouse buttons)
# are ignored when matching a key press.
X_RELEVANT_MASK = sum(x11 for _, _, x11 in _MODIFIERS.values())
# Lock keys whose state must not affect whether a hotkey matches.
X_IGNORED_MASKS = (0, X_LOCK_MASK, X_MOD2_MASK, X_LOCK_MASK | X_MOD2_MASK)

# Portable key name -> (Windows virtual-key code, X11 keysym name)
_SPECIAL_KEYS: dict[str, tuple[int, str]] = {
    "Backspace": (0x08, "BackSpace"),
    "Tab": (0x09, "Tab"),
    "Return": (0x0D, "Return"),
    "Enter": (0x0D, "KP_Enter"),
    "Pause": (0x13, "Pause"),
    "Esc": (0x1B, "Escape"),
    "Space": (0x20, "space"),
    "PgUp": (0x21, "Prior"),
    "PgDown": (0x22, "Next"),
    "End": (0x23, "End"),
    "Home": (0x24, "Home"),
    "Left": (0x25, "Left"),
    "Up": (0x26, "Up"),
    "Right": (0x27, "Right"),
    "Down": (0x28, "Down"),
    "Print": (0x2C, "Print"),
    "Ins": (0x2D, "Insert"),
    "Del": (0x2E, "Delete"),
}
KEYS: dict[str, tuple[int, str]] = {
    **{c: (ord(c), c.lower()) for c in string.ascii_uppercase},
    **{d: (ord(d), d) for d in string.digits},
    **{f"F{n}": (0x6F + n, f"F{n}") for n in range(1, 25)},
    **_SPECIAL_KEYS,
}
_KEYS_LOWER = {k.lower(): k for k in KEYS}

# Keys that are fine as a hotkey without a modifier: they don't type text.
_STANDALONE_KEYS = {f"F{n}" for n in range(1, 25)} | {"Pause", "Print"}


class HotkeyError(ValueError):
    # str(exc) is English (for logs); translated() is for display.

    def __init__(self, template: str, **fields: object) -> None:
        super().__init__(template.format(**fields))
        self.template = template
        self.fields = fields

    def translated(self) -> str:
        return tr(self.template, **self.fields)


@dataclass(frozen=True)
class Hotkey:
    modifiers: frozenset[str]
    key: str

    def __str__(self) -> str:
        mods = [name for m, (name, _, _) in _MODIFIERS.items() if m in self.modifiers]
        return "+".join([*mods, self.key])

    @property
    def vk(self) -> int:
        return KEYS[self.key][0]

    @property
    def keysym_name(self) -> str:
        return KEYS[self.key][1]


def parse(text: str) -> Hotkey:
    parts = [p.strip() for p in text.split("+")]
    if not text.strip() or any(not p for p in parts):
        raise HotkeyError(N_("Invalid shortcut '{text}'."), text=text)
    *mods, key = parts

    modifiers: set[str] = set()
    for mod in mods:
        m = _MODIFIER_ALIASES.get(mod.lower(), mod.lower())
        if m not in _MODIFIERS:
            raise HotkeyError(
                N_("Unknown modifier '{modifier}' in '{text}'."), modifier=mod, text=text
            )
        modifiers.add(m)

    canonical = _KEYS_LOWER.get(key.lower())
    if canonical is None:
        raise HotkeyError(
            N_(
                "Key '{key}' is not supported for global shortcuts; use a "
                "letter, digit, F-key or navigation key."
            ),
            key=key,
        )
    if not modifiers and canonical not in _STANDALONE_KEYS:
        raise HotkeyError(
            N_(
                "'{text}' needs a modifier (Ctrl, Alt, Shift or Meta/Win), "
                "otherwise it would block normal typing."
            ),
            text=text,
        )
    return Hotkey(frozenset(modifiers), canonical)


def win_modifiers(hotkey: Hotkey) -> int:
    """RegisterHotKey flags for the hotkey's modifiers."""
    return MOD_NOREPEAT | sum(_MODIFIERS[m][1] for m in hotkey.modifiers)


def x11_modifiers(hotkey: Hotkey) -> int:
    """XGrabKey mask for the hotkey's modifiers."""
    return sum(_MODIFIERS[m][2] for m in hotkey.modifiers)
