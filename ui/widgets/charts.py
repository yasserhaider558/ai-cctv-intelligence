"""Small bar charts drawn from real stored values.

There is no animation and no invented data: with an empty series the widget
paints an explicit "no data" message.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ui import theme


class BarChart(QWidget):
    def __init__(
        self,
        horizontal: bool = True,
        accent: str = theme.ACCENT,
        value_suffix: str = "",
        max_items: int = 10,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._horizontal = horizontal
        self._accent = accent
        self._suffix = value_suffix
        self._max_items = max_items
        self._data: list[tuple[str, float]] = []
        self.setMinimumHeight(140 if not horizontal else 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, data: list[tuple[str, float]]) -> None:
        cleaned = [(str(label), float(value)) for label, value in data if value is not None]
        if self._max_items:
            cleaned = cleaned[: self._max_items]
        self._data = cleaned
        self.update()

    def clear(self) -> None:
        self._data = []
        self.update()

    def has_data(self) -> bool:
        return bool(self._data)

    # -- painting ----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())

        if not self._data:
            painter.setPen(QColor(theme.TEXT_DIM))
            font = QFont(self.font())
            font.setPointSizeF(9.5)
            painter.setFont(font)
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "No data recorded yet")
            painter.end()
            return

        if self._horizontal:
            self._paint_horizontal(painter, rect)
        else:
            self._paint_vertical(painter, rect)
        painter.end()

    def _paint_horizontal(self, painter: QPainter, rect: QRectF) -> None:
        rows = self._data
        label_width = 108.0
        value_width = 46.0
        row_height = max(22.0, min(30.0, (rect.height() - 4) / max(1, len(rows))))
        max_value = max((v for _, v in rows), default=0.0) or 1.0
        bar_area = max(20.0, rect.width() - label_width - value_width)

        label_font = QFont(self.font())
        label_font.setPointSizeF(9.0)
        value_font = QFont(self.font())
        value_font.setPointSizeF(8.5)
        value_font.setBold(True)

        for index, (label, value) in enumerate(rows):
            top = rect.top() + index * row_height
            if top + row_height > rect.bottom():
                break
            painter.setFont(label_font)
            painter.setPen(QColor(theme.TEXT_MUTED))
            painter.drawText(
                QRectF(rect.left(), top, label_width - 10, row_height),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                label,
            )

            track = QRectF(rect.left() + label_width, top + row_height / 2 - 5, bar_area, 10)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.SURFACE_HIGH))
            painter.drawRoundedRect(track, 5, 5)

            width = max(4.0, bar_area * (value / max_value))
            bar = QRectF(track.left(), track.top(), width, track.height())
            painter.setBrush(QColor(self._accent))
            painter.drawRoundedRect(bar, 5, 5)

            painter.setFont(value_font)
            painter.setPen(QColor(theme.TEXT))
            painter.drawText(
                QRectF(rect.right() - value_width, top, value_width, row_height),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"{value:.0f}{self._suffix}",
            )

    def _paint_vertical(self, painter: QPainter, rect: QRectF) -> None:
        rows = self._data
        plot = QRectF(rect.left() + 6, rect.top() + 16, rect.width() - 12, rect.height() - 38)
        if plot.height() <= 10 or plot.width() <= 10:
            return

        max_value = max((v for _, v in rows), default=0.0) or 1.0
        slot = plot.width() / max(1, len(rows))
        bar_width = max(3.0, min(34.0, slot * 0.58))

        label_font = QFont(self.font())
        label_font.setPointSizeF(7.8)
        value_font = QFont(self.font())
        value_font.setPointSizeF(7.6)

        # baseline
        painter.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
        painter.drawLine(plot.bottomLeft(), plot.bottomRight())

        step = max(1, int(len(rows) / 8) + (1 if len(rows) > 8 else 0))
        for index, (label, value) in enumerate(rows):
            centre_x = plot.left() + slot * index + slot / 2
            height = plot.height() * (value / max_value)
            height = max(2.0, height)
            bar = QRectF(centre_x - bar_width / 2, plot.bottom() - height, bar_width, height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self._accent))
            painter.drawRoundedRect(bar, 3, 3)

            painter.setFont(label_font)
            painter.setPen(QColor(theme.TEXT_DIM))
            if index % step == 0:
                painter.drawText(
                    QRectF(centre_x - slot / 2, plot.bottom() + 5, slot, 14),
                    int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                    label,
                )

            if len(rows) <= 12 and value > 0:
                painter.setFont(value_font)
                painter.setPen(QColor(theme.TEXT_MUTED))
                painter.drawText(
                    QRectF(centre_x - slot / 2, plot.bottom() - height - 14, slot, 13),
                    int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom),
                    f"{value:.0f}",
                )


class Sparkline(QWidget):
    """Tiny filled line used for the processing-rate history."""

    def __init__(self, accent: str = theme.SUCCESS, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: list[float] = []
        self._accent = accent
        self.setMinimumHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def push(self, value: float) -> None:
        self._values.append(float(value))
        if len(self._values) > 90:
            self._values.pop(0)
        self.update()

    def clear(self) -> None:
        self._values.clear()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 3, -1, -3)
        if len(self._values) < 2:
            painter.setPen(QColor(theme.TEXT_DIM))
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "collecting...")
            painter.end()
            return

        top = max(self._values)
        top = max(top, 1.0)
        step = rect.width() / (len(self._values) - 1)
        points = []
        for index, value in enumerate(self._values):
            x = rect.left() + step * index
            y = rect.bottom() - (value / top) * rect.height()
            points.append((x, y))

        from PySide6.QtGui import QPainterPath

        path = QPainterPath()
        path.moveTo(points[0][0], rect.bottom())
        for x, y in points:
            path.lineTo(x, y)
        path.lineTo(points[-1][0], rect.bottom())
        path.closeSubpath()

        colour = QColor(self._accent)
        colour.setAlpha(38)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawPath(path)

        line = QPainterPath()
        line.moveTo(points[0][0], points[0][1])
        for x, y in points[1:]:
            line.lineTo(x, y)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(self._accent), 1.6))
        painter.drawPath(line)
        painter.end()
