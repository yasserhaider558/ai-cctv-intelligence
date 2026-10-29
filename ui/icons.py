"""Vector icons drawn with QPainter.

Shipping raster assets would mean guessing at DPI. Drawing in a 24x24 space and
rendering at 2x keeps the icons sharp on any Windows scaling setting, and means
the project has no binary dependencies.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from ui.theme import ACCENT, TEXT

_CACHE: dict[tuple[str, str, int], QIcon] = {}

_SIZE = 24.0


def _pen(color: str, width: float = 1.7) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _stroke(painter: QPainter, color: str, width: float = 1.7) -> None:
    painter.setPen(_pen(color, width))
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _fill(painter: QPainter, color: str) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))


def _draw(name: str, painter: QPainter, color: str) -> None:  # noqa: C901
    if name == "dashboard":
        _stroke(painter, color)
        for x, y in ((3, 3), (14, 3), (3, 14), (14, 14)):
            painter.drawRoundedRect(QRectF(x, y, 7, 7), 1.8, 1.8)

    elif name == "camera":
        _stroke(painter, color)
        painter.drawRoundedRect(QRectF(2, 7, 13.5, 10.5), 2.2, 2.2)
        path = QPainterPath()
        path.moveTo(16.5, 11.2)
        path.lineTo(21.5, 8.2)
        path.lineTo(21.5, 16.6)
        path.lineTo(16.5, 13.6)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawEllipse(QPointF(8.6, 12.2), 2.6, 2.6)

    elif name == "recordings":
        _stroke(painter, color)
        painter.drawEllipse(QPointF(12, 12), 8.2, 8.2)
        _fill(painter, color)
        painter.drawEllipse(QPointF(12, 12), 3.2, 3.2)

    elif name == "events":
        _stroke(painter, color)
        for y in (6.5, 12.0, 17.5):
            painter.drawLine(QPointF(9.5, y), QPointF(20.5, y))
        _fill(painter, color)
        for y in (6.5, 12.0, 17.5):
            painter.drawEllipse(QPointF(4.6, y), 1.5, 1.5)

    elif name == "analytics":
        _fill(painter, color)
        painter.drawRoundedRect(QRectF(4, 13, 3.6, 7), 1.2, 1.2)
        painter.drawRoundedRect(QRectF(10.2, 8, 3.6, 12), 1.2, 1.2)
        painter.drawRoundedRect(QRectF(16.4, 4, 3.6, 16), 1.2, 1.2)

    elif name == "settings":
        _stroke(painter, color)
        for y, knob in ((6.5, 15.0), (12.0, 8.5), (17.5, 13.0)):
            painter.drawLine(QPointF(3, y), QPointF(21, y))
            painter.setBrush(QColor("#0B0F14"))
            painter.drawEllipse(QPointF(knob, y), 2.4, 2.4)

    elif name == "play":
        _fill(painter, color)
        path = QPainterPath()
        path.moveTo(8, 5)
        path.lineTo(19, 12)
        path.lineTo(8, 19)
        path.closeSubpath()
        painter.drawPath(path)

    elif name == "pause":
        _fill(painter, color)
        painter.drawRoundedRect(QRectF(7, 5, 3.6, 14), 1.2, 1.2)
        painter.drawRoundedRect(QRectF(13.4, 5, 3.6, 14), 1.2, 1.2)

    elif name == "stop":
        _fill(painter, color)
        painter.drawRoundedRect(QRectF(6, 6, 12, 12), 2.0, 2.0)

    elif name == "record":
        _stroke(painter, color)
        painter.drawEllipse(QPointF(12, 12), 8.0, 8.0)
        _fill(painter, color)
        painter.drawEllipse(QPointF(12, 12), 4.6, 4.6)

    elif name == "snapshot":
        _stroke(painter, color)
        painter.drawRoundedRect(QRectF(2.5, 6.5, 19, 13), 2.2, 2.2)
        painter.drawEllipse(QPointF(12, 13), 3.4, 3.4)
        painter.drawLine(QPointF(8.5, 6.5), QPointF(9.8, 4.2))
        painter.drawLine(QPointF(9.8, 4.2), QPointF(14.2, 4.2))
        painter.drawLine(QPointF(14.2, 4.2), QPointF(15.5, 6.5))

    elif name == "power":
        _stroke(painter, color)
        painter.drawArc(QRectF(4.5, 4.5, 15, 15), 60 * 16, 240 * 16)
        painter.drawLine(QPointF(12, 2.8), QPointF(12, 11.5))

    elif name == "disconnect":
        _stroke(painter, color)
        painter.drawArc(QRectF(4.5, 4.5, 15, 15), 60 * 16, 240 * 16)
        painter.drawLine(QPointF(12, 2.8), QPointF(12, 11.5))
        painter.drawLine(QPointF(4.5, 4.5), QPointF(19.5, 19.5))

    elif name == "search":
        _stroke(painter, color)
        painter.drawEllipse(QPointF(10.5, 10.5), 6.2, 6.2)
        painter.drawLine(QPointF(15.2, 15.2), QPointF(20.5, 20.5))

    elif name == "refresh":
        _stroke(painter, color)
        painter.drawArc(QRectF(4, 4, 16, 16), 40 * 16, 290 * 16)
        _fill(painter, color)
        path = QPainterPath()
        path.moveTo(19.4, 3.6)
        path.lineTo(20.6, 9.4)
        path.lineTo(15.0, 8.0)
        path.closeSubpath()
        painter.drawPath(path)

    elif name == "trash":
        _stroke(painter, color)
        painter.drawLine(QPointF(3.5, 6.8), QPointF(20.5, 6.8))
        painter.drawLine(QPointF(9.5, 6.8), QPointF(9.5, 3.8))
        painter.drawLine(QPointF(9.5, 3.8), QPointF(14.5, 3.8))
        painter.drawLine(QPointF(14.5, 3.8), QPointF(14.5, 6.8))
        path = QPainterPath()
        path.moveTo(6, 6.8)
        path.lineTo(7.2, 20.2)
        path.lineTo(16.8, 20.2)
        path.lineTo(18, 6.8)
        painter.drawPath(path)
        painter.drawLine(QPointF(10.4, 10.2), QPointF(10.4, 17.0))
        painter.drawLine(QPointF(13.6, 10.2), QPointF(13.6, 17.0))

    elif name == "folder":
        _stroke(painter, color)
        path = QPainterPath()
        path.moveTo(3, 7)
        path.lineTo(9.2, 7)
        path.lineTo(11.2, 9.2)
        path.lineTo(21, 9.2)
        path.lineTo(21, 19)
        path.lineTo(3, 19)
        path.closeSubpath()
        painter.drawPath(path)

    elif name == "chevron_left":
        _stroke(painter, color)
        painter.drawLine(QPointF(14.5, 5.5), QPointF(8.5, 12))
        painter.drawLine(QPointF(8.5, 12), QPointF(14.5, 18.5))

    elif name == "chevron_right":
        _stroke(painter, color)
        painter.drawLine(QPointF(9.5, 5.5), QPointF(15.5, 12))
        painter.drawLine(QPointF(15.5, 12), QPointF(9.5, 18.5))

    elif name == "plus":
        _stroke(painter, color, 2.0)
        painter.drawLine(QPointF(12, 5), QPointF(12, 19))
        painter.drawLine(QPointF(5, 12), QPointF(19, 12))

    elif name == "warning":
        _stroke(painter, color)
        path = QPainterPath()
        path.moveTo(12, 3.6)
        path.lineTo(21.4, 20.2)
        path.lineTo(2.6, 20.2)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(12, 9.2), QPointF(12, 14.4))
        _fill(painter, color)
        painter.drawEllipse(QPointF(12, 17.4), 1.1, 1.1)

    elif name == "check":
        _stroke(painter, color, 2.1)
        painter.drawLine(QPointF(4.5, 12.5), QPointF(9.8, 18))
        painter.drawLine(QPointF(9.8, 18), QPointF(19.5, 6.5))

    elif name == "info":
        _stroke(painter, color)
        painter.drawEllipse(QPointF(12, 12), 8.4, 8.4)
        painter.drawLine(QPointF(12, 11), QPointF(12, 16.6))
        _fill(painter, color)
        painter.drawEllipse(QPointF(12, 7.8), 1.1, 1.1)

    else:  # graceful fallback: a small dot rather than a blank button
        _fill(painter, color)
        painter.drawEllipse(QPointF(12, 12), 3.0, 3.0)


def make_icon(name: str, color: str = TEXT, size: int = 20) -> QIcon:
    key = (name, color, int(size))
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.scale((size * scale) / _SIZE, (size * scale) / _SIZE)
        _draw(name, painter, color)
    finally:
        painter.end()
    pixmap.setDevicePixelRatio(float(scale))

    icon = QIcon(pixmap)
    _CACHE[key] = icon
    return icon


def app_icon() -> QIcon:
    """A simple mark for the window and taskbar."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.scale(size / _SIZE, size / _SIZE)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(ACCENT))
            painter.drawRoundedRect(QRectF(1.5, 1.5, 21, 21), 5.0, 5.0)
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(QPointF(12, 12), 5.4, 5.4)
            painter.setBrush(QColor(ACCENT))
            painter.drawEllipse(QPointF(12, 12), 2.4, 2.4)
        finally:
            painter.end()
        icon.addPixmap(pixmap)
    return icon
