"""The tray icon, drawn from the monitors' power states."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

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
