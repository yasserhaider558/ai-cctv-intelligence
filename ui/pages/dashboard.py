"""Dashboard: KPI cards, live system status and recent events."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cameras.pipeline import STATE_RUNNING
from ui import theme
from ui.context import AppContext
from ui.widgets.common import Card, EmptyState, InfoRow, StatCard, format_timestamp
from ui.widgets.video_view import VideoView


class DashboardPage(QWidget):
    navigate = Signal(str)

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._stats: dict = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # -- KPI cards ---------------------------------------------------
        cards = QHBoxLayout()
        cards.setSpacing(14)
        self._card_cameras = StatCard("Active cameras", "0 / 1", "configured source", theme.ACCENT)
        self._card_people = StatCard("People visible", "0", "currently in frame", theme.DANGER)
        self._card_vehicles = StatCard("Vehicles visible", "0", "currently in frame", theme.INFO)
        self._card_events = StatCard("Events today", "0", "stored locally", theme.WARNING)
        for card in (self._card_cameras, self._card_people, self._card_vehicles, self._card_events):
            cards.addWidget(card)
        layout.addLayout(cards)

        # -- status row --------------------------------------------------
        status_row = QHBoxLayout()
        status_row.setSpacing(14)

        self._status_card = Card()
        status_header = QHBoxLayout()
        title = QLabel("System status")
        title.setObjectName("sectionTitle")
        status_header.addWidget(title)
        status_header.addStretch(1)
        self._open_live = QPushButton("Open live view")
        self._open_live.setObjectName("ghost")
        self._open_live.clicked.connect(lambda: self.navigate.emit("live"))
        status_header.addWidget(self._open_live)
        self._status_card.body().addLayout(status_header)
        self._status_rows = {
            "source": InfoRow("Source", "not connected"),
            "state": InfoRow("State", "idle"),
            "resolution": InfoRow("Resolution", "-"),
            "capture": InfoRow("Capture rate", "-"),
            "processed": InfoRow("Processed rate", "-"),
            "inference": InfoRow("Inference time", "-"),
            "frames": InfoRow("Frames processed", "0"),
            "dropped": InfoRow("Frames skipped", "0"),
        }
        for row in self._status_rows.values():
            self._status_card.add(row)
        status_row.addWidget(self._status_card, 3)

        self._model_card = Card()
        model_header = QHBoxLayout()
        model_title = QLabel("Detection model")
        model_title.setObjectName("sectionTitle")
        model_header.addWidget(model_title)
        model_header.addStretch(1)
        self._model_chip = QLabel("idle")
        self._model_chip.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; background-color: {theme.SURFACE_HIGH};"
            "border-radius: 8px; padding: 2px 9px; font-size: 8pt; font-weight: 600;"
        )
        model_header.addWidget(self._model_chip)
        self._model_card.body().addLayout(model_header)

        self._model_rows = {
            "model": InfoRow("Checkpoint", "-"),
            "device": InfoRow("Device", "cpu"),
            "tracking": InfoRow("Tracking", "off"),
            "safety": InfoRow("Safety model", "off"),
            "classes": InfoRow("Enabled classes", "0"),
            "uptime": InfoRow("Session uptime", "-"),
        }
        for row in self._model_rows.values():
            self._model_card.add(row)

        self._model_message = QLabel("")
        self._model_message.setWordWrap(True)
        self._model_message.setVisible(False)
        self._model_message.setStyleSheet(
            f"color: {theme.WARNING}; background-color: #2A2110; border: 1px solid #4A3A12;"
            "border-radius: 6px; padding: 8px; font-size: 8.5pt;"
        )
        self._model_card.add(self._model_message)
        status_row.addWidget(self._model_card, 2)

        layout.addLayout(status_row)

        # -- preview + recent events -------------------------------------
        bottom = QHBoxLayout()
        bottom.setSpacing(14)

        preview_card = Card(padding=10)
        preview_header = QHBoxLayout()
        preview_title = QLabel("Live preview")
        preview_title.setObjectName("sectionTitle")
        preview_header.addWidget(preview_title)
        preview_header.addStretch(1)
        preview_card.body().addLayout(preview_header)
        self._preview = VideoView()
        self._preview.setMinimumHeight(210)
        self._preview.set_empty(
            "No signal",
            "Connect a camera on the Live Cameras page to see the processed feed here.",
        )
        preview_card.add(self._preview, 1)
        bottom.addWidget(preview_card, 3)

        events_card = Card()
        events_header = QHBoxLayout()
        events_title = QLabel("Recent events")
        events_title.setObjectName("sectionTitle")
        events_header.addWidget(events_title)
        events_header.addStretch(1)
        view_all = QPushButton("View all")
        view_all.setObjectName("ghost")
        view_all.clicked.connect(lambda: self.navigate.emit("events"))
        events_header.addWidget(view_all)
        events_card.body().addLayout(events_header)

        self._events_table = QTableWidget(0, 5)
        self._events_table.setHorizontalHeaderLabels(["Time", "Event", "Class", "Track", "Camera"])
        self._events_table.verticalHeader().setVisible(False)
        self._events_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._events_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._events_table.setShowGrid(False)
        self._events_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self._events_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setHighlightSections(False)

        self._events_empty = EmptyState(
            "No events recorded",
            "Events are written to the local database when detection rules fire.",
            "events",
        )
        self._events_stack = QStackedWidget()
        self._events_stack.addWidget(self._events_table)
        self._events_stack.addWidget(self._events_empty)
        events_card.add(self._events_stack, 1)
        bottom.addWidget(events_card, 2)

        layout.addLayout(bottom, 1)

        self.refresh()

    # -- live updates ------------------------------------------------------
    def on_stats(self, stats: dict) -> None:
        self._stats = stats or {}
        running = self._ctx.pipeline.is_running
        state = self._ctx.pipeline.state

        self._card_cameras.set_value("1 / 1" if running and state == STATE_RUNNING else "0 / 1")
        self._card_people.set_value(str(self._stats.get("people", 0)))
        self._card_vehicles.set_value(str(self._stats.get("vehicles", 0)))

        source = self._ctx.pipeline.source
        self._status_rows["source"].set_value(source.display_name if source else "not connected")
        self._status_rows["state"].set_value(state)
        self._status_rows["capture"].set_value(f"{self._stats.get('capture_fps', 0):.1f} fps")
        self._status_rows["processed"].set_value(f"{self._stats.get('processed_fps', 0):.1f} fps")
        self._status_rows["inference"].set_value(f"{self._stats.get('inference_ms', 0):.0f} ms")
        self._status_rows["frames"].set_value(str(self._stats.get("frames_processed", 0)))
        self._status_rows["dropped"].set_value(str(self._stats.get("frames_dropped", 0)))

        model_state = str(self._stats.get("model_state", "idle"))
        self._set_model_chip(model_state)
        self._model_rows["tracking"].set_value(str(self._stats.get("tracking_mode", "off")))
        self._model_rows["safety"].set_value(str(self._stats.get("safety_state", "off")))
        if self._stats.get("device"):
            self._model_rows["device"].set_value(str(self._stats["device"]))

        message = str(self._stats.get("model_error", "") or "")
        if message:
            headline = message.splitlines()[0]
            self._model_message.setText(
                f"{headline}\nOpen Live Cameras for the full diagnostic and a Retry button."
            )
        else:
            self._model_message.setText("")
        self._model_message.setVisible(bool(message))

    def set_preview(self, image) -> None:
        if image is None:
            self._preview.set_empty(
                "No signal",
                "Connect a camera on the Live Cameras page to see the processed feed here.",
            )
            return
        self._preview.set_frame(image)

    def _set_model_chip(self, state: str) -> None:
        colours = {
            "ready": (theme.SUCCESS, "#12281A"),
            "loading": (theme.WARNING, "#2A2110"),
            "error": (theme.DANGER, "#2A1418"),
        }
        colour, background = colours.get(state, (theme.TEXT_MUTED, theme.SURFACE_HIGH))
        self._model_chip.setText(state)
        self._model_chip.setStyleSheet(
            f"color: {colour}; background-color: {background};"
            "border-radius: 8px; padding: 2px 9px; font-size: 8pt; font-weight: 600;"
        )

    # -- static refresh ----------------------------------------------------
    def refresh(self) -> None:
        detection = self._ctx.config.section("detection")
        self._model_rows["model"].set_value(str(detection.get("model", "-")))
        self._model_rows["device"].set_value(str(detection.get("device", "cpu")))
        enabled = detection.get("enabled_classes", []) or []
        self._model_rows["classes"].set_value(str(len(enabled)))

        try:
            midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            today = self._ctx.event_repo.count(since=midnight)
        except Exception:
            today = 0
        self._card_events.set_value(str(today))

        self._reload_events()

    def _reload_events(self) -> None:
        rows = self._ctx.analytics.recent(8)
        self._events_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = [
                format_timestamp(row.ts),
                row.title,
                row.class_name or "-",
                f"#{row.track_id}" if row.track_id is not None else "-",
                row.camera or "-",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setForeground(QColor(theme.TEXT_DIM))
                self._events_table.setItem(index, column, item)
        if rows:
            self._events_stack.setCurrentWidget(self._events_table)
        else:
            self._events_stack.setCurrentWidget(self._events_empty)
