"""Shared small widgets: cards, empty states, stat cards, formatting helpers."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui import theme
from ui.icons import make_icon


def format_timestamp(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return "-"


def format_time_only(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return "--:--:--"


def format_relative(ts: float, now: float | None = None) -> str:
    import time

    now = time.time() if now is None else now
    delta = max(0.0, now - ts)
    if delta < 5:
        return "just now"
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def h_line() -> QFrame:
    line = QFrame()
    line.setObjectName("divider")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    return line


class Card(QFrame):
    """A rounded surface panel."""

    def __init__(self, parent: QWidget | None = None, padding: int = 16) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        self._layout.setSpacing(10)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget, stretch: int = 0) -> None:
        self._layout.addWidget(widget, stretch)


class Panel(QFrame):
    def __init__(self, parent: QWidget | None = None, padding: int = 14) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        self._layout.setSpacing(10)

    def body(self) -> QVBoxLayout:
        return self._layout


class StatCard(QFrame):
    """Small KPI card: label, big value, hint line, coloured accent dot."""

    def __init__(
        self,
        title: str,
        value: str = "0",
        hint: str = "",
        accent: str = theme.ACCENT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(7)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {accent}; font-size: 8pt;")
        dot.setFixedWidth(10)
        self._title = QLabel(title.upper())
        self._title.setObjectName("cardTitle")
        header.addWidget(dot)
        header.addWidget(self._title)
        header.addStretch(1)
        layout.addLayout(header)

        self._value = QLabel(value)
        self._value.setObjectName("cardValue")
        layout.addWidget(self._value)

        self._hint = QLabel(hint)
        self._hint.setObjectName("cardHint")
        layout.addWidget(self._hint)

    def set_value(self, value: str | int) -> None:
        self._value.setText(str(value))

    def set_hint(self, hint: str) -> None:
        self._hint.setText(hint)

    def set_accent(self, color: str) -> None:
        self._value.setStyleSheet(f"color: {color};")


class EmptyState(QWidget):
    """Centred placeholder used wherever a list or chart has no data."""

    def __init__(
        self,
        title: str,
        body: str = "",
        icon_name: str = "info",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = QLabel()
        icon_label.setPixmap(make_icon(icon_name, theme.TEXT_DIM, 34).pixmap(34, 34))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        self._title = QLabel(title)
        self._title.setObjectName("emptyTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title)

        self._body = QLabel(body)
        self._body.setObjectName("dim")
        self._body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._body.setWordWrap(True)
        self._body.setMaximumWidth(460)
        layout.addWidget(self._body, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_text(self, title: str, body: str = "") -> None:
        self._title.setText(title)
        self._body.setText(body)


class InfoRow(QWidget):
    """A label/value line used in status panels."""

    def __init__(self, label: str, value: str = "-", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(12)
        self._label = QLabel(label)
        self._label.setObjectName("muted")
        self._value = QLabel(value)
        self._value.setObjectName("mono")
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._label)
        layout.addStretch(1)
        layout.addWidget(self._value)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def set_value_color(self, color: str) -> None:
        self._value.setStyleSheet(f"color: {color};")

    def set_label(self, text: str) -> None:
        self._label.setText(text)


def chip(text: str, color: str, background: str | None = None) -> QLabel:
    label = QLabel(text)
    bg = background or QColor(color).darker(320).name()
    label.setStyleSheet(
        f"color: {color}; background-color: {bg}; border: 1px solid {color}33;"
        "border-radius: 8px; padding: 1px 8px; font-size: 8.5pt; font-weight: 600;"
    )
    return label


def bold(label: QLabel, size: float | None = None) -> QLabel:
    font = label.font()
    font.setWeight(QFont.Weight.DemiBold)
    if size:
        font.setPointSizeF(size)
    label.setFont(font)
    return label
