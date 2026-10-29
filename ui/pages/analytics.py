"""Analytics page: real aggregates from stored events and sessions."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analytics.analytics import RANGES, format_duration, range_start
from ui import theme
from ui.context import AppContext
from ui.widgets.charts import BarChart
from ui.widgets.common import Card, StatCard, format_timestamp


class AnalyticsPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        # -- toolbar -------------------------------------------------------
        bar = QFrame()
        bar.setObjectName("toolbar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 10, 14, 10)
        bar_layout.setSpacing(9)
        bar_layout.addWidget(QLabel("Range"))
        self._range = QComboBox()
        for key, (label, _span) in RANGES.items():
            self._range.addItem(label, key)
        self._range.setCurrentIndex(0)
        self._range.setMinimumWidth(160)
        self._range.currentIndexChanged.connect(lambda _i: self.refresh())
        bar_layout.addWidget(self._range)
        bar_layout.addStretch(1)
        note = QLabel("All values are computed from the local database.")
        note.setObjectName("dim")
        bar_layout.addWidget(note)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        bar_layout.addWidget(refresh_btn)
        root.addWidget(bar)

        # -- cards ---------------------------------------------------------
        cards = QHBoxLayout()
        cards.setSpacing(14)
        self._card_total = StatCard("Events in range", "0", "stored events", theme.ACCENT)
        self._card_region = StatCard("Region alerts", "0", "entry + loitering", theme.WARNING)
        self._card_fps = StatCard("Average processed FPS", "0.0", "across sessions", theme.SUCCESS)
        self._card_uptime = StatCard("Measured uptime", "0s", "sum of sessions", theme.INFO)
        for card in (self._card_total, self._card_region, self._card_fps, self._card_uptime):
            cards.addWidget(card)
        root.addLayout(cards)

        # -- charts --------------------------------------------------------
        charts_row = QHBoxLayout()
        charts_row.setSpacing(14)

        class_card = Card()
        class_header = QHBoxLayout()
        class_title = QLabel("Events by object class")
        class_title.setObjectName("sectionTitle")
        class_header.addWidget(class_title)
        class_header.addStretch(1)
        class_card.body().addLayout(class_header)
        self._class_chart = BarChart(horizontal=True, accent=theme.ACCENT, max_items=8)
        class_card.add(self._class_chart, 1)
        charts_row.addWidget(class_card, 1)

        freq_card = Card()
        freq_header = QHBoxLayout()
        freq_title = QLabel("Event frequency")
        freq_title.setObjectName("sectionTitle")
        freq_header.addWidget(freq_title)
        freq_header.addStretch(1)
        self._freq_hint = QLabel("")
        self._freq_hint.setObjectName("dim")
        freq_header.addWidget(self._freq_hint)
        freq_card.body().addLayout(freq_header)
        self._freq_chart = BarChart(horizontal=False, accent=theme.WARNING)
        freq_card.add(self._freq_chart, 1)
        charts_row.addWidget(freq_card, 1)

        root.addLayout(charts_row, 1)

        # -- tables --------------------------------------------------------
        tables_row = QHBoxLayout()
        tables_row.setSpacing(14)

        uptime_card = Card()
        uptime_title = QLabel("Camera uptime")
        uptime_title.setObjectName("sectionTitle")
        uptime_card.add(uptime_title)
        self._uptime_table = QTableWidget(0, 3)
        self._uptime_table.setHorizontalHeaderLabels(["Camera", "Uptime", "Sessions"])
        self._configure_table(self._uptime_table)
        self._uptime_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        uptime_card.add(self._uptime_table, 1)
        tables_row.addWidget(uptime_card, 1)

        recent_card = Card()
        recent_title = QLabel("Recent events")
        recent_title.setObjectName("sectionTitle")
        recent_card.add(recent_title)
        self._recent_table = QTableWidget(0, 3)
        self._recent_table.setHorizontalHeaderLabels(["Time", "Event", "Class"])
        self._configure_table(self._recent_table)
        self._recent_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        recent_card.add(self._recent_table, 1)
        tables_row.addWidget(recent_card, 1)

        root.addLayout(tables_row, 1)

        self.refresh()

    @staticmethod
    def _configure_table(table: QTableWidget) -> None:
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

    # -- refresh -----------------------------------------------------------
    def refresh(self) -> None:
        key = str(self._range.currentData() or "24h")
        since = range_start(key)
        summary = self._ctx.analytics.summary(since)

        self._card_total.set_value(str(summary.events_in_range))
        self._card_total.set_hint(f"{summary.total_events} events stored in total")
        self._card_region.set_value(str(summary.region_events))
        self._card_fps.set_value(f"{summary.average_fps:.1f}")
        self._card_fps.set_hint(f"{summary.frames_processed} frames processed")
        self._card_uptime.set_value(format_duration(summary.total_uptime_s))
        self._card_uptime.set_hint(f"{summary.sessions} session(s) recorded")

        distribution = self._ctx.analytics.class_distribution(since)
        self._class_chart.set_data(distribution[:8])

        bucket = 3600 if key == "24h" else 86400
        self._freq_hint.setText("per hour" if bucket == 3600 else "per day")
        self._freq_chart.set_data(self._series(since, bucket))

        uptime = self._ctx.analytics.uptime(since)
        self._uptime_table.setRowCount(len(uptime))
        for index, (camera, seconds, sessions) in enumerate(uptime):
            for column, value in enumerate((camera, format_duration(seconds), str(sessions))):
                item = QTableWidgetItem(value)
                item.setForeground(QColor(theme.TEXT_MUTED if column else theme.TEXT))
                self._uptime_table.setItem(index, column, item)

        recent = self._ctx.analytics.recent(8)
        self._recent_table.setRowCount(len(recent))
        for index, row in enumerate(recent):
            for column, value in enumerate(
                (format_timestamp(row.ts), row.title, row.class_name or "-")
            ):
                item = QTableWidgetItem(value)
                item.setForeground(QColor(theme.TEXT_MUTED if column else theme.TEXT_DIM))
                self._recent_table.setItem(index, column, item)

    def _series(self, since: float | None, bucket: int) -> list[tuple[str, float]]:
        now = datetime.now().timestamp()
        start = since if since is not None else now - 30 * 86400
        try:
            counts = dict(self._ctx.event_repo.bucket_counts(start, bucket))
        except Exception:
            counts = {}
        labels: list[tuple[str, float]] = []
        cursor = int(start // bucket) * bucket
        guard = 0
        while cursor <= now and guard < 400:
            label = (
                datetime.fromtimestamp(cursor).strftime("%H:%M")
                if bucket < 86400
                else datetime.fromtimestamp(cursor).strftime("%d %b")
            )
            labels.append((label, float(counts.get(cursor, 0))))
            cursor += bucket
            guard += 1
        return labels
