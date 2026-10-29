"""Dark surveillance theme: palette constants and the global stylesheet."""

from __future__ import annotations

BG = "#0B0F14"
SURFACE = "#111721"
SURFACE_ALT = "#161E2A"
SURFACE_HIGH = "#1C2634"
BORDER = "#243040"
BORDER_SOFT = "#1A2331"
TEXT = "#E8EEF6"
TEXT_MUTED = "#93A3B8"
TEXT_DIM = "#61738A"
ACCENT = "#3B82F6"
ACCENT_HOVER = "#5C9CFF"
ACCENT_DIM = "#1D3B63"
DANGER = "#EF4444"
WARNING = "#F59E0B"
SUCCESS = "#22C55E"
INFO = "#22D3EE"

FONT_FAMILY = '"Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif'
MONO_FAMILY = '"Cascadia Mono", "Consolas", monospace'

STYLESHEET = f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: 9.5pt;
    outline: none;
}}

QWidget {{
    background-color: {BG};
    color: {TEXT};
}}

QMainWindow, QDialog {{
    background-color: {BG};
}}

QToolTip {{
    background-color: {SURFACE_HIGH};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 5px 7px;
    border-radius: 4px;
}}

/* ---------- structural panels ---------- */
QFrame#sidebar {{
    background-color: {SURFACE};
    border-right: 1px solid {BORDER_SOFT};
}}

QFrame#headerBar {{
    background-color: {SURFACE};
    border-bottom: 1px solid {BORDER_SOFT};
}}

QFrame#card {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_SOFT};
    border-radius: 10px;
}}

QFrame#panel {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_SOFT};
    border-radius: 10px;
}}

QFrame#toolbar {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER_SOFT};
    border-radius: 8px;
}}

QFrame#divider {{
    background-color: {BORDER_SOFT};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

/* ---------- typography ---------- */
QLabel#appTitle {{
    font-size: 13pt;
    font-weight: 600;
    color: {TEXT};
}}
QLabel#pageTitle {{
    font-size: 15pt;
    font-weight: 600;
}}
QLabel#sectionTitle {{
    font-size: 10pt;
    font-weight: 600;
    color: {TEXT};
}}
QLabel#cardTitle {{
    font-size: 8.5pt;
    font-weight: 600;
    color: {TEXT_MUTED};
    letter-spacing: 1px;
}}
QLabel#cardValue {{
    font-size: 22pt;
    font-weight: 600;
    color: {TEXT};
}}
QLabel#cardHint {{
    font-size: 8.5pt;
    color: {TEXT_DIM};
}}
QLabel#muted {{
    color: {TEXT_MUTED};
}}
QLabel#dim {{
    color: {TEXT_DIM};
}}
QLabel#mono {{
    font-family: {MONO_FAMILY};
    color: {TEXT_MUTED};
    font-size: 9pt;
}}
QLabel#emptyTitle {{
    font-size: 11pt;
    font-weight: 600;
    color: {TEXT_MUTED};
}}

/* ---------- navigation ---------- */
QToolButton#navButton {{
    background-color: transparent;
    border: none;
    border-radius: 7px;
    color: {TEXT_MUTED};
    padding: 9px 10px;
    text-align: left;
    font-size: 9.5pt;
    font-weight: 500;
}}
QToolButton#navButton:hover {{
    background-color: {SURFACE_ALT};
    color: {TEXT};
}}
QToolButton#navButton:checked {{
    background-color: {ACCENT_DIM};
    color: #DCEBFF;
    font-weight: 600;
}}

/* ---------- buttons ---------- */
QPushButton {{
    background-color: {SURFACE_HIGH};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    min-height: 18px;
}}
QPushButton:hover {{
    background-color: #22303F;
    border-color: #2E3D4F;
}}
QPushButton:pressed {{
    background-color: #1A2432;
}}
QPushButton:disabled {{
    color: {TEXT_DIM};
    background-color: {SURFACE_ALT};
    border-color: {BORDER_SOFT};
}}
QPushButton#primary {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton#primary:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton#primary:disabled {{
    background-color: {ACCENT_DIM};
    border-color: {ACCENT_DIM};
    color: #8FA9C9;
}}
QPushButton#danger {{
    background-color: transparent;
    border: 1px solid #4A2530;
    color: #FF8A94;
}}
QPushButton#danger:hover {{
    background-color: #33161D;
    border-color: #7A2C38;
}}
QPushButton#ghost {{
    background-color: transparent;
    border: 1px solid {BORDER};
    color: {TEXT_MUTED};
}}
QPushButton#ghost:hover {{
    background-color: {SURFACE_ALT};
    color: {TEXT};
}}
QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 5px;
}}
QToolButton:hover {{
    background-color: {SURFACE_HIGH};
    border-color: {BORDER};
}}
QToolButton:checked {{
    background-color: {ACCENT_DIM};
    border-color: {ACCENT_DIM};
}}
QToolButton:disabled {{
    color: #55657A;
}}

/* ---------- inputs ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 9px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    min-height: 18px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {ACCENT};
}}
QLineEdit:disabled, QComboBox:disabled {{
    color: {TEXT_DIM};
    background-color: #121924;
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE_HIGH};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DIM};
    selection-color: {TEXT};
    padding: 4px;
    outline: none;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background-color: {SURFACE_HIGH};
    border: none;
    width: 16px;
}}

QCheckBox {{
    spacing: 8px;
    color: {TEXT};
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border-radius: 4px;
    border: 1px solid {BORDER};
    background-color: {SURFACE_ALT};
}}
QCheckBox::indicator:hover {{
    border-color: {ACCENT};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    image: none;
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: {SURFACE_HIGH};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {TEXT};
    width: 12px;
    height: 12px;
    margin: -5px 0;
    border-radius: 6px;
}}
QSlider::handle:horizontal:hover {{
    background: {ACCENT_HOVER};
}}

/* ---------- tables ---------- */
QTableWidget, QTableView {{
    background-color: {SURFACE};
    alternate-background-color: {SURFACE_ALT};
    border: 1px solid {BORDER_SOFT};
    border-radius: 8px;
    gridline-color: transparent;
    selection-background-color: {ACCENT_DIM};
    selection-color: {TEXT};
}}
QTableWidget::item {{
    padding: 6px 8px;
    border-bottom: 1px solid {BORDER_SOFT};
}}
QHeaderView::section {{
    background-color: {SURFACE_ALT};
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 7px 8px;
    font-size: 8.5pt;
    font-weight: 600;
}}
QTableCornerButton::section {{
    background-color: {SURFACE_ALT};
    border: none;
}}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #2A3648;
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: #3A4A61;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #2A3648;
    border-radius: 4px;
    min-width: 28px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}

/* ---------- misc ---------- */
QGroupBox {{
    border: 1px solid {BORDER_SOFT};
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
    color: {TEXT_MUTED};
    font-size: 9pt;
}}
QProgressBar {{
    background-color: {SURFACE_ALT};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 3px;
}}
QSplitter::handle {{
    background-color: transparent;
    width: 10px;
    height: 10px;
}}
QMenu {{
    background-color: {SURFACE_HIGH};
    border: 1px solid {BORDER};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 22px 6px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {ACCENT_DIM};
}}
QStatusBar {{
    background-color: {SURFACE};
    border-top: 1px solid {BORDER_SOFT};
    color: {TEXT_MUTED};
}}
QStatusBar::item {{
    border: none;
}}
"""
