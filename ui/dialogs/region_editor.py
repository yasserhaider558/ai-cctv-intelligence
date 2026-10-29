"""Polygon region editor: draw, name, enable and delete regions of interest."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from events.regions import Region, validate_polygon
from ui import theme

_PALETTE = ("#4DA3FF", "#2ED3A0", "#FFC145", "#B388FF", "#FF7BD5", "#FF9F45")


class RegionCanvas(QWidget):
    polygon_finished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(560, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._background: QImage | None = None
        self._regions: list[Region] = []
        self._drawing: list[tuple[float, float]] = []
        self._active = False
        self._name = "Region"
        self._color = _PALETTE[0]

    # -- API ---------------------------------------------------------------
    def set_background(self, image: QImage | None) -> None:
        self._background = image
        self.update()

    def set_regions(self, regions: list[Region]) -> None:
        self._regions = regions
        self.update()

    def start_new(self, name: str, color: str) -> None:
        self._active = True
        self._drawing = []
        self._name = name
        self._color = color
        self.update()

    def cancel_new(self) -> None:
        self._active = False
        self._drawing = []
        self.update()

    def undo_point(self) -> None:
        if self._drawing:
            self._drawing.pop()
            self.update()

    def finish_new(self) -> Region | None:
        if not self._active:
            return None
        if not validate_polygon(self._drawing):
            return None
        region = Region(
            name=self._name or "Region",
            points=list(self._drawing),
            color=self._color,
            enabled=True,
        )
        self._active = False
        self._drawing = []
        self.update()
        return region

    @property
    def is_drawing(self) -> bool:
        return self._active

    @property
    def point_count(self) -> int:
        return len(self._drawing)

    # -- geometry ----------------------------------------------------------
    def _image_rect(self) -> QRectF:
        area = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self._background is None or self._background.isNull():
            return area
        iw, ih = self._background.width(), self._background.height()
        if iw <= 0 or ih <= 0:
            return area
        scale = min(area.width() / iw, area.height() / ih)
        width, height = iw * scale, ih * scale
        return QRectF(
            area.x() + (area.width() - width) / 2,
            area.y() + (area.height() - height) / 2,
            width,
            height,
        )

    def _to_widget(self, x: float, y: float) -> QPointF:
        rect = self._image_rect()
        return QPointF(rect.x() + x * rect.width(), rect.y() + y * rect.height())

    # -- painting ----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        outer = QRectF(self.rect())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#05070A"))
        painter.drawRoundedRect(outer, 8, 8)

        image_rect = self._image_rect()
        if self._background is not None and not self._background.isNull():
            painter.drawImage(image_rect, self._background)
        else:
            painter.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
            painter.setBrush(QColor("#0D1219"))
            painter.drawRect(image_rect)
            painter.setPen(QColor(theme.TEXT_DIM))
            font = QFont(self.font())
            font.setPointSizeF(9.5)
            painter.setFont(font)
            painter.drawText(
                image_rect,
                int(Qt.AlignmentFlag.AlignCenter),
                "No frame captured yet - connect a camera for a live reference,\n"
                "or draw on this empty canvas (coordinates are still relative).",
            )

        for region in self._regions:
            self._paint_region(painter, region)

        if self._drawing:
            self._paint_drawing(painter)

        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(outer.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        painter.end()

    def _paint_region(self, painter: QPainter, region: Region) -> None:
        if len(region.points) < 2:
            return
        colour = QColor(region.color)
        polygon = QPolygonF([self._to_widget(x, y) for x, y in region.points])
        if not region.enabled:
            colour.setAlpha(90)
        fill = QColor(colour)
        fill.setAlpha(38 if region.enabled else 18)
        painter.setPen(QPen(colour, 2))
        painter.setBrush(fill)
        painter.drawPolygon(polygon)

        painter.setBrush(colour)
        painter.setPen(Qt.PenStyle.NoPen)
        for point in polygon:
            painter.drawEllipse(point, 3.0, 3.0)

        anchor = polygon[0]
        font = QFont(self.font())
        font.setPointSizeF(8.5)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(colour)
        suffix = "" if region.enabled else " (disabled)"
        painter.drawText(
            QPointF(anchor.x() + 6, max(14.0, anchor.y() - 6)), region.name + suffix
        )

    def _paint_drawing(self, painter: QPainter) -> None:
        colour = QColor(self._color)
        points = [self._to_widget(x, y) for x, y in self._drawing]

        if len(points) >= 2:
            painter.setPen(QPen(colour, 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolyline(QPolygonF(points))
        if len(points) >= 3:
            preview = QPolygonF(points)
            fill = QColor(colour)
            fill.setAlpha(30)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawPolygon(preview)

        painter.setPen(QPen(QColor("#FFFFFF"), 1.5))
        painter.setBrush(colour)
        for index, point in enumerate(points):
            radius = 5.0 if index == 0 else 3.5
            painter.drawEllipse(point, radius, radius)

        if points:
            painter.setPen(QColor(theme.TEXT))
            font = QFont(self.font())
            font.setPointSizeF(8.5)
            painter.setFont(font)
            painter.drawText(
                QPointF(points[-1].x() + 9, points[-1].y() - 8),
                f"{len(points)} pt",
            )

    # -- interaction -------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not self._active:
            super().mousePressEvent(event)
            return
        rect = self._image_rect()
        if event.button() == Qt.MouseButton.RightButton:
            self.undo_point()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        position = event.position()
        if not rect.contains(position) or rect.width() <= 0 or rect.height() <= 0:
            return
        x = (position.x() - rect.x()) / rect.width()
        y = (position.y() - rect.y()) / rect.height()
        self._drawing.append((max(0.0, min(1.0, x)), max(0.0, min(1.0, y))))
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._active and len(self._drawing) >= 3:
            self.polygon_finished.emit()
        else:
            super().mouseDoubleClickEvent(event)


class RegionEditorDialog(QDialog):
    def __init__(
        self,
        regions: list[Region],
        background: QImage | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Regions of interest")
        self.setMinimumSize(900, 560)
        self._regions = [
            Region(name=r.name, points=list(r.points), color=r.color, enabled=r.enabled)
            for r in regions
        ]
        self._counter = len(self._regions) + 1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        intro = QLabel(
            "Click to place polygon points. Right-click removes the last point. "
            "Double-click or press Finish to close the polygon. Coordinates are stored "
            "relative to the frame, so they survive a resolution change."
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        body = QHBoxLayout()
        body.setSpacing(12)

        # left column
        left = QVBoxLayout()
        left.setSpacing(8)
        list_title = QLabel("Regions")
        list_title.setObjectName("sectionTitle")
        left.addWidget(list_title)

        self._list = QListWidget()
        self._list.setMinimumWidth(220)
        self._list.currentRowChanged.connect(self._on_selection_changed)
        left.addWidget(self._list, 1)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Region name")
        left.addWidget(self._name_edit)

        self._enabled_box = QCheckBox("Region alerts enabled for this region")
        self._enabled_box.setChecked(True)
        self._enabled_box.toggled.connect(self._on_enabled_toggled)
        left.addWidget(self._enabled_box)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._new_btn = QPushButton("New region")
        self._new_btn.setObjectName("primary")
        self._new_btn.clicked.connect(self._start_new)
        row.addWidget(self._new_btn)
        self._finish_btn = QPushButton("Finish")
        self._finish_btn.setEnabled(False)
        self._finish_btn.clicked.connect(self._finish)
        row.addWidget(self._finish_btn)
        left.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self._cancel_btn = QPushButton("Cancel drawing")
        self._cancel_btn.setObjectName("ghost")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel)
        row2.addWidget(self._cancel_btn)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("danger")
        self._delete_btn.clicked.connect(self._delete_selected)
        row2.addWidget(self._delete_btn)
        left.addLayout(row2)

        self._hint = QLabel("")
        self._hint.setObjectName("dim")
        self._hint.setWordWrap(True)
        left.addWidget(self._hint)

        body.addLayout(left, 0)

        self._canvas = RegionCanvas()
        self._canvas.set_background(background)
        self._canvas.set_regions(self._regions)
        self._canvas.polygon_finished.connect(self._finish)
        body.addWidget(self._canvas, 1)

        layout.addLayout(body, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Save regions")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_list()

    # -- list management ---------------------------------------------------
    def _refresh_list(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for region in self._regions:
            item = QListWidgetItem(
                f"{region.name}  ·  {len(region.points)} pts"
                + ("" if region.enabled else "  (disabled)")
            )
            item.setForeground(QColor(region.color))
            self._list.addItem(item)
        self._list.blockSignals(False)
        self._canvas.set_regions(self._regions)

    def _on_selection_changed(self, row: int) -> None:
        if 0 <= row < len(self._regions):
            region = self._regions[row]
            self._name_edit.blockSignals(True)
            self._name_edit.setText(region.name)
            self._name_edit.blockSignals(False)
            self._enabled_box.blockSignals(True)
            self._enabled_box.setChecked(region.enabled)
            self._enabled_box.blockSignals(False)

    def _on_enabled_toggled(self, enabled: bool) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._regions):
            self._regions[row].enabled = bool(enabled)
            self._refresh_list()
            self._list.setCurrentRow(row)

    # -- drawing -----------------------------------------------------------
    def _start_new(self) -> None:
        self._canvas.start_new(
            self._name_edit.text().strip() or f"Region {self._counter}",
            _PALETTE[len(self._regions) % len(_PALETTE)],
        )
        self._counter += 1
        self._finish_btn.setEnabled(True)
        self._cancel_btn.setEnabled(True)
        self._new_btn.setEnabled(False)
        self._hint.setText("Drawing: click to add points, right-click to undo one.")

    def _finish(self) -> None:
        region = self._canvas.finish_new()
        if region is None:
            self._hint.setText("A region needs at least three points.")
            return
        self._regions.append(region)
        self._refresh_list()
        self._list.setCurrentRow(len(self._regions) - 1)
        self._finish_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._new_btn.setEnabled(True)
        self._hint.setText(f"Added '{region.name}'.")

    def _cancel(self) -> None:
        self._canvas.cancel_new()
        self._finish_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._new_btn.setEnabled(True)
        self._hint.setText("Drawing cancelled.")

    def _delete_selected(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._regions):
            removed = self._regions.pop(row)
            self._refresh_list()
            self._hint.setText(f"Removed '{removed.name}'.")

    # -- result ------------------------------------------------------------
    def regions(self) -> list[Region]:
        return self._regions
