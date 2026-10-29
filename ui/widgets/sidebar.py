"""Collapsible navigation sidebar."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config.defaults import APP_VERSION
from ui import theme
from ui.icons import app_icon, make_icon

EXPANDED_WIDTH = 214
COLLAPSED_WIDTH = 62


class Sidebar(QFrame):
    navigation = Signal(str)

    def __init__(self, items: list[tuple[str, str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(EXPANDED_WIDTH)
        self._collapsed = False
        self._buttons: dict[str, QToolButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 12)
        layout.setSpacing(6)

        # -- brand ------------------------------------------------------
        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 0, 0)
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(28, 28))
        logo.setFixedSize(28, 28)
        self._brand = QLabel("AI CCTV")
        self._brand.setObjectName("appTitle")
        brand.addWidget(logo)
        brand.addWidget(self._brand)
        brand.addStretch(1)
        layout.addLayout(brand)

        subtitle = QLabel("Intelligence System")
        subtitle.setObjectName("dim")
        subtitle.setContentsMargins(44, 0, 0, 0)
        self._subtitle = subtitle
        layout.addWidget(subtitle)

        layout.addSpacing(14)

        # -- navigation -------------------------------------------------
        group = QButtonGroup(self)
        group.setExclusive(True)
        self._group = group
        for key, label, icon_name in items:
            button = QToolButton()
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setIcon(make_icon(icon_name, theme.TEXT_MUTED, 18))
            button.setIconSize(QSize(18, 18))
            button.setText("  " + label)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setMinimumHeight(36)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(label)
            button.clicked.connect(lambda _checked=False, k=key: self.navigation.emit(k))
            group.addButton(button)
            layout.addWidget(button)
            self._buttons[key] = button

        layout.addStretch(1)

        # -- footer -----------------------------------------------------
        self._version = QLabel(f"v{APP_VERSION}")
        self._version.setObjectName("dim")
        self._version.setContentsMargins(8, 0, 0, 0)
        layout.addWidget(self._version)

        self._collapse_button = QToolButton()
        self._collapse_button.setObjectName("navButton")
        self._collapse_button.setIcon(make_icon("chevron_left", theme.TEXT_MUTED, 16))
        self._collapse_button.setIconSize(QSize(16, 16))
        self._collapse_button.setText("  Collapse")
        self._collapse_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._collapse_button.setMinimumHeight(32)
        self._collapse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_button.clicked.connect(self.toggle_collapsed)
        layout.addWidget(self._collapse_button)

    # -- API ---------------------------------------------------------------
    def set_active(self, key: str) -> None:
        button = self._buttons.get(key)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def current_key(self) -> str:
        for key, button in self._buttons.items():
            if button.isChecked():
                return key
        return ""

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = bool(collapsed)
        self.setFixedWidth(COLLAPSED_WIDTH if collapsed else EXPANDED_WIDTH)
        self._brand.setVisible(not collapsed)
        self._subtitle.setVisible(not collapsed)
        self._version.setVisible(not collapsed)
        for button in self._buttons.values():
            button.setText("" if collapsed else "  " + button.toolTip())
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly if collapsed
                else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
            button.setIconSize(QSize(18, 18))
        self._collapse_button.setText("" if collapsed else "  Collapse")
        self._collapse_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly if collapsed
            else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._collapse_button.setIcon(
            make_icon("chevron_right" if collapsed else "chevron_left", theme.TEXT_MUTED, 16)
        )
