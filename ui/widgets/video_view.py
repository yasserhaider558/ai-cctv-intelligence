"""The video surface: aspect-correct image painting plus state overlays."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ui import theme
from ui.icons import make_icon

MODE_EMPTY = "empty"
MODE_LOADING = "loading"
MODE_ERROR = "error"
MODE_FRAME = "frame"


class VideoView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAutoFillBackground(False)

        self._image: QImage | None = None
        self._mode = MODE_EMPTY
        self._title = "No video source"
        self._body = "Pick a camera on the left and press Connect to start."
        self._badge_text = ""
        self._badge_color = theme.SUCCESS
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._tick)

    # -- public API --------------------------------------------------------
    def set_frame(self, image: QImage) -> None:
        if image is None or image.isNull():
            return
        self._image = image
        if self._mode != MODE_FRAME:
            self._mode = MODE_FRAME
            self._timer.stop()
        self.update()

    def set_empty(self, title: str, body: str = "") -> None:
        self._set_message(MODE_EMPTY, title, body)

    def set_loading(self, title: str, body: str = "") -> None:
        self._set_message(MODE_LOADING, title, body)
        if not self._timer.isActive():
            self._timer.start()

    def set_error(self, title: str, body: str = "") -> None:
        self._set_message(MODE_ERROR, title, body)

    def clear(self) -> None:
        self._image = None
        self._badge_text = ""
        self.set_empty(
            "No video source",
            "Pick a camera on the left and press Connect to start.",
        )

    def set_badge(self, text: str, color: str = theme.SUCCESS) -> None:
        self._badge_text = text
        self._badge_color = color
        self.update()

    def has_frame(self) -> bool:
        return self._image is not None and self._mode == MODE_FRAME

    def current_image(self) -> QImage | None:
        return self._image

    # -- internals ---------------------------------------------------------
    def _set_message(self, mode: str, title: str, body: str) -> None:
        self._mode = mode
        self._title = title
        self._body = body
        if mode != MODE_LOADING:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 1) % 60
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        outer = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
        painter.setBrush(QColor("#05070A"))
        painter.drawRoundedRect(outer, 10, 10)

        if self._mode == MODE_FRAME and self._image is not None:
            self._paint_image(painter, outer)
            self._paint_badge(painter, outer)
        else:
            self._paint_message(painter, outer)
        painter.end()

    def _paint_image(self, painter: QPainter, outer: QRectF) -> None:
        image = self._image
        if image is None:
            return
        area = outer.adjusted(1, 1, -1, -1)
        iw, ih = image.width(), image.height()
        if iw <= 0 or ih <= 0:
            return
        scale = min(area.width() / iw, area.height() / ih)
        width = max(1.0, iw * scale)
        height = max(1.0, ih * scale)
        x = area.x() + (area.width() - width) / 2.0
        y = area.y() + (area.height() - height) / 2.0
        painter.drawImage(QRectF(x, y, width, height), image)

    def _paint_badge(self, painter: QPainter, outer: QRectF) -> None:
        if not self._badge_text:
            return
        font = QFont(self.font())
        font.setPointSizeF(8.5)
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        text_width = metrics.horizontalAdvance(self._badge_text)
        width = text_width + 26
        height = metrics.height() + 8
        rect = QRectF(outer.x() + 14, outer.y() + 14, width, height)

        background = QColor(self._badge_color)
        background.setAlpha(38)
        painter.setPen(QPen(QColor(self._badge_color), 1))
        painter.setBrush(background)
        painter.drawRoundedRect(rect, height / 2.0, height / 2.0)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._badge_color))
        painter.drawEllipse(QPointF(rect.x() + 12, rect.center().y()), 3.0, 3.0)

        painter.setPen(QColor(self._badge_color))
        painter.drawText(
            QRectF(rect.x() + 19, rect.y(), text_width + 4, rect.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._badge_text,
        )

    def _paint_message(self, painter: QPainter, outer: QRectF) -> None:
        centre_x = outer.center().x()
        centre_y = outer.center().y()

        title_font = QFont(self.font())
        title_font.setPointSizeF(12.0)
        title_font.setWeight(QFont.Weight.DemiBold)
        body_font = QFont(self.font())
        body_font.setPointSizeF(9.5)

        body_width = min(440.0, outer.width() - 60.0)
        body_metrics = QFontMetrics(body_font)
        body_rect = body_metrics.boundingRect(
            QRectF(0, 0, body_width, 400).toRect(),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap),
            self._body,
        )
        body_height = float(body_rect.height())

        icon_size = 40.0
        block_height = icon_size + 14 + 24 + 8 + body_height
        top = centre_y - block_height / 2.0

        if self._mode == MODE_LOADING:
            self._paint_spinner(painter, QPointF(centre_x, top + icon_size / 2.0), 15.0)
        else:
            colour = theme.DANGER if self._mode == MODE_ERROR else theme.TEXT_DIM
            icon_name = "warning" if self._mode == MODE_ERROR else "camera"
            pixmap = make_icon(icon_name, colour, int(icon_size)).pixmap(int(icon_size), int(icon_size))
            painter.drawPixmap(
                int(centre_x - icon_size / 2.0), int(top), pixmap
            )

        painter.setFont(title_font)
        painter.setPen(QColor(theme.TEXT if self._mode == MODE_ERROR else theme.TEXT_MUTED))
        title_rect = QRectF(outer.x(), top + icon_size + 14, outer.width(), 26)
        painter.drawText(title_rect, int(Qt.AlignmentFlag.AlignHCenter), self._title)

        painter.setFont(body_font)
        painter.setPen(QColor(theme.TEXT_DIM))
        text_rect = QRectF(
            centre_x - body_width / 2.0,
            top + icon_size + 14 + 24 + 8,
            body_width,
            body_height + 4,
        )
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap),
            self._body,
        )

    def _paint_spinner(self, painter: QPainter, centre: QPointF, radius: float) -> None:
        painter.save()
        painter.translate(centre)
        painter.rotate(self._phase * 6.0)
        pen = QPen(QColor(theme.ACCENT), 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(-radius, -radius, radius * 2, radius * 2)
        painter.drawArc(rect, 0, 260 * 16)
        painter.restore()
