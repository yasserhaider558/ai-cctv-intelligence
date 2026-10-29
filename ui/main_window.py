"""Main window: sidebar navigation, header, page stack and the frame pump."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cameras.pipeline import (
    STATE_CONNECTING,
    STATE_ERROR,
    STATE_FINISHED,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_RUNNING,
)
from config.defaults import APP_NAME, APP_VERSION
from ui import theme
from ui.context import AppContext
from ui.icons import app_icon
from ui.pages.analytics import AnalyticsPage
from ui.pages.dashboard import DashboardPage
from ui.pages.events import EventsPage
from ui.pages.live import LivePage
from ui.pages.recordings import RecordingsPage
from ui.pages.settings import SettingsPage
from ui.widgets.sidebar import Sidebar

NAV_ITEMS = [
    ("dashboard", "Dashboard", "dashboard"),
    ("live", "Live Cameras", "camera"),
    ("recordings", "Recordings", "recordings"),
    ("events", "Events", "events"),
    ("analytics", "Analytics", "analytics"),
    ("settings", "Settings", "settings"),
]

PAGE_META = {
    "dashboard": ("Dashboard", "System overview and recent activity"),
    "live": ("Live Cameras", "Real-time detection and tracking"),
    "recordings": ("Recordings", "Clips and snapshots written by this application"),
    "events": ("Events", "Searchable history of stored alerts"),
    "analytics": ("Analytics", "Aggregates computed from the local database"),
    "settings": ("Settings", "Detection, events, storage and privacy"),
}

_STATE_STYLE = {
    STATE_RUNNING: (theme.SUCCESS, "#12281A", "streaming"),
    STATE_CONNECTING: (theme.WARNING, "#2A2110", "connecting"),
    STATE_PAUSED: (theme.WARNING, "#2A2110", "paused"),
    STATE_ERROR: (theme.DANGER, "#2A1418", "error"),
    STATE_FINISHED: (theme.TEXT_MUTED, theme.SURFACE_HIGH, "finished"),
    STATE_IDLE: (theme.TEXT_MUTED, theme.SURFACE_HIGH, "idle"),
}

_LEVEL_STYLE = {
    "info": theme.TEXT_MUTED,
    "success": theme.SUCCESS,
    "warning": theme.WARNING,
    "error": theme.DANGER,
}


class MainWindow(QMainWindow):
    def __init__(
        self,
        config,
        db,
        event_repo,
        session_repo,
        analytics,
        pipeline,
        models_dir: Path,
        snapshot_dir: Path,
        recording_dir: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(1280, 800)
        self.resize(1520, 940)

        self._pages: dict[str, QWidget] = {}

        self._ctx = AppContext(
            config=config,
            db=db,
            event_repo=event_repo,
            session_repo=session_repo,
            analytics=analytics,
            pipeline=pipeline,
            models_dir=models_dir,
            snapshot_dir=snapshot_dir,
            recording_dir=recording_dir,
            notify=self._notify,
        )

        # -- layout --------------------------------------------------------
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sidebar = Sidebar(NAV_ITEMS)
        self._sidebar.navigation.connect(self.navigate)
        root.addWidget(self._sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("headerBar")
        header.setFixedHeight(66)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 10, 24, 10)
        header_layout.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        self._title = QLabel("Dashboard")
        self._title.setObjectName("pageTitle")
        self._subtitle = QLabel("System overview and recent activity")
        self._subtitle.setObjectName("muted")
        titles.addWidget(self._title)
        titles.addWidget(self._subtitle)
        header_layout.addLayout(titles)
        header_layout.addStretch(1)

        self._state_chip = QLabel("idle")
        self._state_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_chip.setMinimumWidth(92)
        header_layout.addWidget(self._state_chip)

        self._model_chip = QLabel("model: idle")
        self._model_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._model_chip.setMinimumWidth(132)
        header_layout.addWidget(self._model_chip)

        right_layout.addWidget(header)

        page_host = QWidget()
        page_layout = QVBoxLayout(page_host)
        page_layout.setContentsMargins(22, 16, 22, 16)
        page_layout.setSpacing(0)

        self._stack = QStackedWidget()
        page_layout.addWidget(self._stack)
        right_layout.addWidget(page_host, 1)

        root.addWidget(right, 1)
        self.setCentralWidget(central)

        # -- pages ---------------------------------------------------------
        self._dashboard = DashboardPage(self._ctx)
        self._live = LivePage(self._ctx)
        self._recordings = RecordingsPage(self._ctx)
        self._events = EventsPage(self._ctx)
        self._analytics = AnalyticsPage(self._ctx)
        self._settings = SettingsPage(self._ctx)

        for key, page in (
            ("dashboard", self._dashboard),
            ("live", self._live),
            ("recordings", self._recordings),
            ("events", self._events),
            ("analytics", self._analytics),
            ("settings", self._settings),
        ):
            self._pages[key] = page
            self._stack.addWidget(page)

        self._dashboard.navigate.connect(self.navigate)
        self._live.event_activated.connect(self._on_event_activated)
        self._settings.set_frame_provider(self._live.current_frame)
        self._settings.settings_changed.connect(self._on_settings_changed)

        # -- status bar ----------------------------------------------------
        self._toast = QLabel("")
        self._toast.setStyleSheet(f"color: {theme.TEXT_MUTED}; padding-left: 6px;")
        self.statusBar().addPermanentWidget(self._toast, 1)
        self.statusBar().setSizeGripEnabled(False)
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(lambda: self._toast.setText(""))

        # -- pipeline wiring ----------------------------------------------
        pipeline.state_changed.connect(self._on_state_changed)
        pipeline.stats_ready.connect(self._on_stats)
        pipeline.model_status.connect(self._on_model_status)

        self._pump = QTimer(self)
        self._pump.setInterval(33)
        self._pump.timeout.connect(self._pump_frames)
        self._pump.start()

        self._sidebar.set_active("dashboard")
        self._on_state_changed(pipeline.state)
        self._on_model_status(pipeline.model_state, "")

    # -- navigation --------------------------------------------------------
    def navigate(self, key: str) -> None:
        page = self._pages.get(key)
        if page is None:
            return
        self._stack.setCurrentWidget(page)
        title, subtitle = PAGE_META.get(key, (key, ""))
        self._title.setText(title)
        self._subtitle.setText(subtitle)
        self._sidebar.set_active(key)
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            try:
                refresh()
            except Exception as exc:  # pragma: no cover - defensive
                self._notify(f"Could not refresh this page: {exc}", "error")

    def _on_event_activated(self, record) -> None:
        self.navigate("events")
        event_id = getattr(record, "id", None)
        if isinstance(event_id, int):
            self._events.select_event(event_id)

    def _on_settings_changed(self, _snapshot: dict) -> None:
        self._dashboard.refresh()
        self._live._sync_toggles()  # noqa: SLF001 - same package, single window

    # -- pipeline callbacks ------------------------------------------------
    def _on_state_changed(self, state: str) -> None:
        colour, background, label = _STATE_STYLE.get(
            state, (theme.TEXT_MUTED, theme.SURFACE_HIGH, state)
        )
        self._state_chip.setText(label)
        self._state_chip.setStyleSheet(
            f"color: {colour}; background-color: {background}; border-radius: 10px;"
            " padding: 3px 10px; font-size: 8.5pt; font-weight: 600;"
        )

    def _on_model_status(self, state: str, message: str) -> None:
        colour = {
            "ready": theme.SUCCESS,
            "loading": theme.WARNING,
            "error": theme.DANGER,
        }.get(state, theme.TEXT_MUTED)
        self._model_chip.setText(f"model: {state}")
        self._model_chip.setStyleSheet(
            f"color: {colour}; background-color: {theme.SURFACE_HIGH};"
            "border-radius: 10px; padding: 3px 10px; font-size: 8.5pt; font-weight: 600;"
        )
        if state == "error" and message:
            self._notify(message.splitlines()[0], "error")

    def _on_stats(self, stats: dict) -> None:
        self._dashboard.on_stats(stats)

    def _pump_frames(self) -> None:
        frame = self._ctx.pipeline.display_buffer.get_nowait()
        if frame is None:
            return
        self._live.show_frame(frame.image)
        self._dashboard.set_preview(frame.image)

    # -- notifications -----------------------------------------------------
    def _notify(self, message: str, level: str = "info") -> None:
        colour = _LEVEL_STYLE.get(level, theme.TEXT_MUTED)
        self._toast.setText(str(message))
        self._toast.setStyleSheet(f"color: {colour}; padding-left: 6px;")
        self._toast.setToolTip(str(message))
        self._toast_timer.start(8000)

    # -- shutdown ----------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._pump.stop()
        self._notify("Shutting down…", "info")
        try:
            self._live.shutdown()
        except Exception:
            pass
        try:
            self._ctx.pipeline.shutdown()
        except Exception:
            pass
        try:
            self._ctx.db.close_all()
        except Exception:
            pass
        super().closeEvent(event)
