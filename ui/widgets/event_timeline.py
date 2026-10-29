"""Bottom event timeline: a horizontally scrolling strip of event chips."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from events.rules import (
    EVENT_INTRUSION,
    EVENT_LOITERING,
    EVENT_PERSON,
    EVENT_VEHICLE,
    SEVERITY_ALARM,
    SEVERITY_WARNING,
    severity_for,
)
from ui import theme
from ui.widgets.common import format_time_only

MAX_CHIPS = 40

_TYPE_COLORS = {
    EVENT_PERSON: theme.DANGER,
    EVENT_VEHICLE: theme.ACCENT,
    EVENT_INTRUSION: theme.WARNING,
    EVENT_LOITERING: "#B388FF",
}


def _type_color(event_type: str) -> str:
    """Severity wins over the per-type palette for warnings and alarms."""
    severity = severity_for(event_type)
    if severity == SEVERITY_ALARM:
        return theme.DANGER
    if severity == SEVERITY_WARNING:
        return theme.WARNING
    return _TYPE_COLORS.get(event_type, theme.TEXT_MUTED)


class EventChip(QFrame):
    clicked = Signal(object)

    def __init__(self, record, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._record = record
        event_type = getattr(record, "event_type", "")
        colour = _type_color(event_type)
        severity = severity_for(event_type)
        background = "#2A1418" if severity == SEVERITY_ALARM else theme.SURFACE_ALT
        self.setFixedSize(206, 62)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QFrame {{ background-color: {background};"
            f" border: 1px solid {theme.BORDER_SOFT};"
            f" border-left: 3px solid {colour}; border-radius: 7px; }}"
            f"QFrame:hover {{ background-color: {theme.SURFACE_HIGH}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(1)

        header = QHBoxLayout()
        header.setSpacing(6)
        time_label = QLabel(format_time_only(getattr(record, "ts", 0.0)))
        time_label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-family: 'Cascadia Mono', Consolas, monospace;"
            "font-size: 8pt; border: none; background: transparent;"
        )
        tag = QLabel(str(getattr(record, "event_type", "")).upper())
        tag.setStyleSheet(
            f"color: {colour}; font-size: 7.5pt; font-weight: 700;"
            "border: none; background: transparent;"
        )
        header.addWidget(time_label)
        header.addStretch(1)
        header.addWidget(tag)
        layout.addLayout(header)

        title = QLabel(getattr(record, "title", "Event"))
        title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 9pt; font-weight: 600;"
            "border: none; background: transparent;"
        )
        title.setWordWrap(False)
        metrics = QFontMetrics(title.font())
        title.setText(
            metrics.elidedText(getattr(record, "title", "Event"), Qt.TextElideMode.ElideRight, 178)
        )
        layout.addWidget(title)

        bits = []
        class_name = getattr(record, "class_name", "")
        if class_name:
            bits.append(class_name)
        track_id = getattr(record, "track_id", None)
        if track_id is not None:
            bits.append(f"#{track_id}")
        region = getattr(record, "region_name", "")
        if region:
            bits.append(region)
        meta = QLabel(" · ".join(bits) or "—")
        meta.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 8pt;"
            "border: none; background: transparent;"
        )
        layout.addWidget(meta)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._record)
        super().mousePressEvent(event)


class EventTimeline(QFrame):
    event_activated = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setFixedHeight(126)
        self._chips: list[EventChip] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Event timeline")
        title.setObjectName("sectionTitle")
        self._count = QLabel("0 events shown")
        self._count.setObjectName("dim")
        hint = QLabel("newest first")
        hint.setObjectName("dim")
        header.addWidget(title)
        header.addSpacing(10)
        header.addWidget(self._count)
        header.addStretch(1)
        header.addWidget(hint)
        layout.addLayout(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._strip = QWidget()
        self._strip.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        self._strip_layout = QHBoxLayout(self._strip)
        self._strip_layout.setContentsMargins(0, 0, 0, 0)
        self._strip_layout.setSpacing(8)
        self._strip_layout.addStretch(1)

        self._empty = QLabel("No events yet. Detection events appear here as they happen.")
        self._empty.setObjectName("dim")
        self._strip_layout.insertWidget(0, self._empty)

        self._scroll.setWidget(self._strip)
        layout.addWidget(self._scroll, 1)

    # -- API ---------------------------------------------------------------
    def add_event(self, record) -> None:
        chip = EventChip(record)
        chip.clicked.connect(self.event_activated)
        self._strip_layout.insertWidget(0, chip)
        self._chips.insert(0, chip)
        self._empty.setVisible(False)
        self._trim()
        self._scroll.horizontalScrollBar().setValue(0)
        self._update_count()

    def set_events(self, records: list) -> None:
        self.clear()
        for record in reversed(list(records)):
            chip = EventChip(record)
            chip.clicked.connect(self.event_activated)
            self._strip_layout.insertWidget(0, chip)
            self._chips.insert(0, chip)
        self._empty.setVisible(not self._chips)
        self._trim()
        self._update_count()

    def clear(self) -> None:
        for chip in self._chips:
            self._strip_layout.removeWidget(chip)
            chip.setParent(None)
            chip.deleteLater()
        self._chips.clear()
        self._empty.setVisible(True)
        self._update_count()

    # -- internals ---------------------------------------------------------
    def _trim(self) -> None:
        while len(self._chips) > MAX_CHIPS:
            chip = self._chips.pop()
            self._strip_layout.removeWidget(chip)
            chip.setParent(None)
            chip.deleteLater()

    def _update_count(self) -> None:
        total = len(self._chips)
        self._count.setText(f"{total} event{'s' if total != 1 else ''} shown")
