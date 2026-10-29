"""Events page: searchable, filterable event history with deletion controls."""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from events.rules import (
    ALARM_EVENT_TYPES,
    EVENT_LABELS,
    SEVERITY_ALARM,
    SEVERITY_WARNING,
    WARNING_EVENT_TYPES,
    severity_for,
)
from ui import theme
from ui.context import AppContext
from ui.icons import make_icon
from ui.widgets.common import EmptyState, format_timestamp

_RANGES = (
    ("All time", None),
    ("Today", "today"),
    ("Last 7 days", "7d"),
    ("Last 30 days", "30d"),
)


class EventsPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._rows = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # -- filters ------------------------------------------------------
        bar = QFrame()
        bar.setObjectName("toolbar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 10, 14, 10)
        bar_layout.setSpacing(9)

        search_icon = QLabel()
        search_icon.setPixmap(make_icon("search", theme.TEXT_DIM, 16).pixmap(16, 16))
        bar_layout.addWidget(search_icon)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search title, class, region, camera or track ID")
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumWidth(280)
        bar_layout.addWidget(self._search, 1)

        self._type_combo = QComboBox()
        self._type_combo.addItem("All event types", "all")
        self._type_combo.addItem("Warnings and alarms", list(WARNING_EVENT_TYPES))
        self._type_combo.addItem("Alarms only", list(ALARM_EVENT_TYPES))
        self._type_combo.insertSeparator(self._type_combo.count())
        for key, label in EVENT_LABELS.items():
            self._type_combo.addItem(label, key)
        self._type_combo.setMinimumWidth(190)
        bar_layout.addWidget(self._type_combo)

        self._range_combo = QComboBox()
        for label, key in _RANGES:
            self._range_combo.addItem(label, key)
        self._range_combo.setMinimumWidth(130)
        bar_layout.addWidget(self._range_combo)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        bar_layout.addWidget(refresh_btn)

        bar_layout.addSpacing(8)
        self._open_btn = QPushButton("Open snapshot")
        self._open_btn.setObjectName("ghost")
        self._open_btn.clicked.connect(self._open_snapshot)
        bar_layout.addWidget(self._open_btn)

        self._delete_btn = QPushButton("Delete selected")
        self._delete_btn.setObjectName("danger")
        self._delete_btn.clicked.connect(self._delete_selected)
        bar_layout.addWidget(self._delete_btn)

        self._clear_btn = QPushButton("Clear history")
        self._clear_btn.setObjectName("danger")
        self._clear_btn.clicked.connect(self._clear_all)
        bar_layout.addWidget(self._clear_btn)

        root.addWidget(bar)

        # -- table --------------------------------------------------------
        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels(
            ["Time", "Type", "Event", "Class", "Track", "Region", "Camera", "Conf"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(False)
        header = self._table.horizontalHeader()
        # Fixed widths, not ResizeToContents: with that mode Qt re-measures every
        # row on every insert, so filling a 1000-row table is quadratic and the
        # window stops responding for half a minute. The event column stretches
        # instead, which needs no measuring at all.
        for column, width in (
            (0, 140),   # Time
            (1, 120),   # Type
            (3, 100),   # Class
            (4, 70),    # Track
            (5, 110),   # Region
            (6, 200),   # Camera
            (7, 60),    # Conf
        ):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self._table.setColumnWidth(column, width)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setHighlightSections(False)
        self._table.doubleClicked.connect(lambda _index: self._open_snapshot())

        self._empty = EmptyState(
            "No matching events",
            "Events appear here when detection rules fire. Adjust the filters or "
            "connect a camera to start collecting history.",
            "events",
        )
        self._stack = QStackedWidget()
        self._stack.addWidget(self._table)
        self._stack.addWidget(self._empty)
        root.addWidget(self._stack, 1)

        footer = QHBoxLayout()
        self._count = QLabel("0 events")
        self._count.setObjectName("dim")
        footer.addWidget(self._count)
        footer.addStretch(1)
        hint = QLabel(
            "Snapshots are stored only when 'Save evidence snapshots' is enabled in Settings."
        )
        hint.setObjectName("dim")
        footer.addWidget(hint)
        root.addLayout(footer)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(320)
        self._debounce.timeout.connect(self.refresh)

        self._search.textChanged.connect(lambda _t: self._debounce.start())
        self._search.returnPressed.connect(self.refresh)
        self._type_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        self._range_combo.currentIndexChanged.connect(lambda _i: self.refresh())

        self.refresh()

    # -- queries -----------------------------------------------------------
    def _since(self) -> float | None:
        key = self._range_combo.currentData()
        now = datetime.now()
        if key == "today":
            return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        if key == "7d":
            return (now - timedelta(days=7)).timestamp()
        if key == "30d":
            return (now - timedelta(days=30)).timestamp()
        return None

    def refresh(self) -> None:
        selected = self._type_combo.currentData()
        if isinstance(selected, (list, tuple)):
            event_types: list[str] | None = list(selected)
            event_type = "all"
        else:
            event_types = None
            event_type = str(selected or "all")
        try:
            rows = self._ctx.event_repo.list(
                search=self._search.text().strip(),
                event_type=event_type,
                event_types=event_types,
                since=self._since(),
                limit=1000,
            )
        except Exception as exc:
            self._ctx.notify(f"Could not read events: {exc}", "error")
            rows = []

        self._rows = rows
        # Batch the insert: without this Qt repaints and re-lays-out on every one
        # of the thousands of setItem calls.
        self._table.setUpdatesEnabled(False)
        self._table.blockSignals(True)
        self._table.setRowCount(len(rows))
        dim = QColor(theme.TEXT_DIM)
        muted = QColor(theme.TEXT_MUTED)
        bright = QColor(theme.TEXT)
        danger = QColor(theme.DANGER)
        warning = QColor(theme.WARNING)
        try:
            for index, row in enumerate(rows):
                values = [
                    format_timestamp(row.ts),
                    EVENT_LABELS.get(row.event_type, row.event_type),
                    row.title,
                    row.class_name or "-",
                    f"#{row.track_id}" if row.track_id is not None else "-",
                    row.region_name or "-",
                    row.camera or "-",
                    f"{row.confidence * 100:.0f}%" if row.confidence else "-",
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 0:
                        item.setData(Qt.ItemDataRole.UserRole, row.id)
                        item.setForeground(dim)
                    elif column == 1:
                        severity = severity_for(row.event_type)
                        if severity == SEVERITY_ALARM:
                            item.setForeground(danger)
                        elif severity == SEVERITY_WARNING:
                            item.setForeground(warning)
                        else:
                            item.setForeground(muted)
                    elif column == 2:
                        item.setForeground(bright)
                    else:
                        item.setForeground(muted)
                    if row.snapshot and column == 2:
                        item.setToolTip("A snapshot is stored for this event")
                    self._table.setItem(index, column, item)
        finally:
            self._table.blockSignals(False)
            self._table.setUpdatesEnabled(True)

        self._stack.setCurrentWidget(self._table if rows else self._empty)
        try:
            total = self._ctx.event_repo.count()
        except Exception:
            total = len(rows)
        if len(rows) == total:
            self._count.setText(f"{len(rows)} event{'s' if len(rows) != 1 else ''}")
        else:
            self._count.setText(f"showing {len(rows)} of {total} stored events")

    def select_event(self, event_id: int) -> None:
        for row_index in range(self._table.rowCount()):
            item = self._table.item(row_index, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == event_id:
                self._table.selectRow(row_index)
                self._table.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
                return

    # -- actions -----------------------------------------------------------
    def _selected_ids(self) -> list[int]:
        ids: list[int] = []
        model = self._table.selectionModel()
        if model is None:
            return ids
        for index in model.selectedRows():
            item = self._table.item(index.row(), 0)
            if item is not None:
                value = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(value, int):
                    ids.append(value)
        return ids

    def _open_snapshot(self) -> None:
        model = self._table.selectionModel()
        rows = model.selectedRows() if model is not None else []
        if not rows:
            self._ctx.notify("Select an event first.", "warning")
            return
        row_index = rows[0].row()
        if row_index >= len(self._rows):
            return
        snapshot = self._rows[row_index].snapshot
        if not snapshot:
            self._ctx.notify(
                "This event has no snapshot. Enable 'Save evidence snapshots' in Settings "
                "before the event occurs.", "warning",
            )
            return
        url = QUrl.fromLocalFile(snapshot)
        if not QDesktopServices.openUrl(url):
            self._ctx.notify(f"Could not open {snapshot}", "error")

    def _delete_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            self._ctx.notify("Select one or more events to delete.", "warning")
            return
        answer = QMessageBox.question(
            self,
            "Delete events",
            f"Delete {len(ids)} selected event(s)? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = self._ctx.event_repo.delete(ids)
        self.refresh()
        self._ctx.notify(f"Deleted {removed} event(s).", "success")

    def _clear_all(self) -> None:
        total = self._ctx.event_repo.count()
        if total == 0:
            self._ctx.notify("The event history is already empty.", "info")
            return
        answer = QMessageBox.question(
            self,
            "Clear event history",
            f"Delete all {total} stored events?\n\n"
            "Snapshots and recordings on disk are not removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = self._ctx.event_repo.clear()
        self.refresh()
        self._ctx.notify(f"Cleared {removed} event(s).", "success")
