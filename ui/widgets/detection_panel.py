"""Right-hand panel listing what the model currently sees."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.defaults import class_color, is_vehicle
from ui import theme
from ui.widgets.common import EmptyState


class DetectionPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setMinimumWidth(300)
        self.setMaximumWidth(380)
        self._signature: tuple = ()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(9)

        header = QHBoxLayout()
        title = QLabel("Live detections")
        title.setObjectName("sectionTitle")
        self._count = QLabel("0")
        self._count.setStyleSheet(
            f"color: {theme.ACCENT}; background-color: {theme.ACCENT_DIM};"
            "border-radius: 8px; padding: 1px 8px; font-weight: 600; font-size: 8.5pt;"
        )
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._count)
        layout.addLayout(header)

        summary = QHBoxLayout()
        summary.setSpacing(6)
        people_widget, self._people_value = self._summary_tile("People", theme.DANGER)
        vehicles_widget, self._vehicles_value = self._summary_tile("Vehicles", theme.ACCENT)
        tracked_widget, self._tracked_value = self._summary_tile("Tracked", theme.SUCCESS)
        summary.addWidget(people_widget)
        summary.addWidget(vehicles_widget)
        summary.addWidget(tracked_widget)
        layout.addLayout(summary)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Class", "Conf", "ID", "Motion"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(False)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.setWordWrap(False)
        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setHighlightSections(False)
        self._table.verticalHeader().setDefaultSectionSize(28)

        self._empty = EmptyState(
            "No objects detected",
            "Point the camera at a scene containing people or vehicles.",
            "search",
        )

        self._stack = QStackedWidget()
        self._stack.addWidget(self._table)
        self._stack.addWidget(self._empty)
        self._stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._stack, 1)

        self._footer = QLabel(
            "Tracking IDs are temporary, frame-local labels. They are not "
            "identities and are not matched across sessions."
        )
        self._footer.setObjectName("dim")
        self._footer.setWordWrap(True)
        self._footer.setStyleSheet("font-size: 8pt;")
        layout.addWidget(self._footer)

        self._stack.setCurrentWidget(self._empty)

    @staticmethod
    def _summary_tile(label: str, colour: str) -> tuple[QWidget, QLabel]:
        widget = QWidget()
        box = QVBoxLayout(widget)
        box.setContentsMargins(8, 5, 8, 5)
        box.setSpacing(0)
        value = QLabel("0")
        value.setStyleSheet(f"color: {colour}; font-size: 13pt; font-weight: 600;")
        caption = QLabel(label)
        caption.setObjectName("dim")
        caption.setStyleSheet("font-size: 8pt;")
        box.addWidget(value)
        box.addWidget(caption)
        widget.setStyleSheet(
            f"background-color: {theme.SURFACE_ALT}; border-radius: 6px;"
        )
        return widget, value

    # -- API ---------------------------------------------------------------
    def set_detections(self, detections: list) -> None:
        count = len(detections)
        self._count.setText(str(count))
        people = sum(1 for d in detections if d.class_name == "person")
        vehicles = sum(1 for d in detections if is_vehicle(d.class_name))
        tracked = sum(1 for d in detections if d.track_id is not None)
        self._people_value.setText(str(people))
        self._vehicles_value.setText(str(vehicles))
        self._tracked_value.setText(str(tracked))

        if not detections:
            self._signature = ()
            self._table.setRowCount(0)
            self._stack.setCurrentWidget(self._empty)
            return

        self._stack.setCurrentWidget(self._table)
        signature = tuple((d.class_name, d.track_id) for d in detections)
        if signature != self._signature:
            self._signature = signature
            self._rebuild(detections)
        else:
            self._update_values(detections)

    def clear(self) -> None:
        self._signature = ()
        self._table.setRowCount(0)
        self._count.setText("0")
        self._people_value.setText("0")
        self._vehicles_value.setText("0")
        self._tracked_value.setText("0")
        self._stack.setCurrentWidget(self._empty)

    def set_tracking_note(self, mode: str) -> None:
        if mode == "bytetrack":
            text = ("Tracking: ByteTrack. IDs are temporary, frame-local labels - "
                    "not identities, and not matched across sessions.")
        elif mode == "fallback-iou":
            text = ("Tracking: built-in IoU fallback (ByteTrack unavailable). IDs are "
                    "temporary and less stable than ByteTrack's.")
        else:
            text = "Tracking is disabled: no IDs are assigned."
        self._footer.setText(text)

    # -- internals ---------------------------------------------------------
    def _rebuild(self, detections: list) -> None:
        self._table.setRowCount(len(detections))
        for row, det in enumerate(detections):
            colour = class_color(det.class_name)
            name_item = QTableWidgetItem(det.class_name)
            name_item.setForeground(QColor(colour))
            self._table.setItem(row, 0, name_item)

            conf_item = QTableWidgetItem(f"{det.confidence * 100:.0f}%")
            conf_item.setForeground(QColor(theme.TEXT_MUTED))
            self._table.setItem(row, 1, conf_item)

            id_item = QTableWidgetItem("#" + str(det.track_id) if det.track_id is not None else "-")
            id_item.setForeground(QColor(theme.TEXT_DIM))
            self._table.setItem(row, 2, id_item)

            motion = det.direction or ("moving" if det.speed_px_s > 12 else "still")
            motion_item = QTableWidgetItem(motion)
            motion_item.setForeground(QColor(theme.TEXT_DIM))
            self._table.setItem(row, 3, motion_item)

    def _update_values(self, detections: list) -> None:
        for row, det in enumerate(detections):
            item = self._table.item(row, 1)
            if item is not None:
                item.setText(f"{det.confidence * 100:.0f}%")
            motion_item = self._table.item(row, 3)
            if motion_item is not None:
                motion_item.setText(det.direction or ("moving" if det.speed_px_s > 12 else "still"))
