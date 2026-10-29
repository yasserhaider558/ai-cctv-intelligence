"""Live cameras page: source selection, transport controls, detections, timeline."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cameras.devices import enumerate_webcams
from cameras.earthcam import CATALOGUE as EARTHCAM_CATALOGUE
from cameras.onvif import discover as onvif_discover
from cameras.pipeline import (
    STATE_CONNECTING,
    STATE_ERROR,
    STATE_FINISHED,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_RUNNING,
)
from cameras.rtsp import test_stream
from cameras.source import (
    SOURCE_EARTHCAM,
    SOURCE_FILE,
    SOURCE_RTSP,
    SOURCE_WEBCAM,
    VIDEO_FILE_FILTER,
    CameraSource,
)
from events.rules import SEVERITY_ALARM
from ui import theme
from ui.context import AppContext
from ui.icons import make_icon
from ui.widgets.common import format_timestamp
from ui.widgets.detection_panel import DetectionPanel
from ui.widgets.event_timeline import EventTimeline
from ui.widgets.video_view import VideoView


class _WebcamScanner(QThread):
    found = Signal(list)

    def run(self) -> None:
        try:
            self.found.emit(enumerate_webcams(5))
        except Exception:
            self.found.emit([])


class _OnvifScanner(QThread):
    found = Signal(list)

    def run(self) -> None:
        try:
            self.found.emit(onvif_discover(3.0))
        except Exception:
            self.found.emit([])


def _tool_button(text: str, icon_name: str, checkable: bool = False) -> QToolButton:
    button = QToolButton()
    button.setText(" " + text)
    button.setIcon(make_icon(icon_name, theme.TEXT, 16))
    button.setIconSize(QSize(16, 16))
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setCheckable(checkable)
    button.setMinimumHeight(30)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class LivePage(QWidget):
    event_activated = Signal(object)

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._pipeline = ctx.pipeline
        self._seek_block = False
        self._duration = 0.0
        self._scanner: _WebcamScanner | None = None
        self._onvif_scanner: _OnvifScanner | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # -- model warning banner ----------------------------------------
        self._banner = QFrame()
        self._banner.setObjectName("panel")
        self._banner.setStyleSheet(
            f"QFrame#panel {{ background-color: #2A2110; border: 1px solid #4A3A12;"
            " border-radius: 8px; }}"
        )
        banner_layout = QHBoxLayout(self._banner)
        banner_layout.setContentsMargins(14, 10, 10, 10)
        banner_layout.setSpacing(10)
        banner_icon = QLabel()
        banner_icon.setPixmap(make_icon("warning", theme.WARNING, 18).pixmap(18, 18))
        banner_layout.addWidget(banner_icon, 0, Qt.AlignmentFlag.AlignTop)
        self._banner_text = QLabel("")
        self._banner_text.setWordWrap(True)
        self._banner_text.setStyleSheet(f"color: {theme.WARNING}; font-size: 9pt;")
        banner_layout.addWidget(self._banner_text, 1)
        retry = QPushButton("Retry")
        retry.setObjectName("ghost")
        retry.setToolTip("Load the detection model again without reconnecting")
        retry.clicked.connect(self._retry_model)
        banner_layout.addWidget(retry, 0, Qt.AlignmentFlag.AlignTop)
        dismiss = QPushButton("Dismiss")
        dismiss.setObjectName("ghost")
        dismiss.clicked.connect(lambda: self._banner.setVisible(False))
        banner_layout.addWidget(dismiss, 0, Qt.AlignmentFlag.AlignTop)
        self._banner.setVisible(False)
        root.addWidget(self._banner)

        # -- alarm banner --------------------------------------------------
        self._alert_banner = QFrame()
        self._alert_banner.setObjectName("alertBanner")
        self._alert_banner.setStyleSheet(
            "QFrame#alertBanner { background-color: #2A1418;"
            " border: 1px solid #7A2C38; border-radius: 8px; }"
        )
        alert_layout = QHBoxLayout(self._alert_banner)
        alert_layout.setContentsMargins(14, 10, 10, 10)
        alert_layout.setSpacing(10)
        alert_icon = QLabel()
        alert_icon.setPixmap(make_icon("warning", theme.DANGER, 18).pixmap(18, 18))
        alert_layout.addWidget(alert_icon, 0, Qt.AlignmentFlag.AlignTop)
        self._alert_text = QLabel("")
        self._alert_text.setWordWrap(True)
        self._alert_text.setStyleSheet(
            f"color: {theme.DANGER}; font-size: 9.5pt; font-weight: 600;"
        )
        alert_layout.addWidget(self._alert_text, 1)
        alert_dismiss = QPushButton("Dismiss")
        alert_dismiss.setObjectName("ghost")
        alert_dismiss.clicked.connect(lambda: self._alert_banner.setVisible(False))
        alert_layout.addWidget(alert_dismiss, 0, Qt.AlignmentFlag.AlignTop)
        self._alert_banner.setVisible(False)
        root.addWidget(self._alert_banner)

        self._alert_timer = QTimer(self)
        self._alert_timer.setSingleShot(True)
        self._alert_timer.setInterval(20000)
        self._alert_timer.timeout.connect(lambda: self._alert_banner.setVisible(False))

        # -- source bar ---------------------------------------------------
        source_bar = QFrame()
        source_bar.setObjectName("toolbar")
        bar_layout = QVBoxLayout(source_bar)
        bar_layout.setContentsMargins(14, 12, 14, 12)
        bar_layout.setSpacing(9)

        top_row = QHBoxLayout()
        top_row.setSpacing(9)
        top_row.addWidget(QLabel("Source"))
        self._source_combo = QComboBox()
        self._source_combo.addItem("Video file", SOURCE_FILE)
        self._source_combo.addItem("Webcam", SOURCE_WEBCAM)
        self._source_combo.addItem("IP camera (RTSP)", SOURCE_RTSP)
        self._source_combo.addItem("EarthCam (live)", SOURCE_EARTHCAM)
        self._source_combo.setFixedWidth(150)
        self._source_combo.currentIndexChanged.connect(self._on_source_type_changed)
        top_row.addWidget(self._source_combo)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setObjectName("primary")
        self._connect_btn.setMinimumWidth(104)
        self._connect_btn.clicked.connect(self._connect)
        top_row.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setObjectName("ghost")
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(self._disconnect)
        top_row.addWidget(self._disconnect_btn)

        top_row.addStretch(1)
        self._status = QLabel("Idle")
        self._status.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 9pt;")
        top_row.addWidget(self._status)
        bar_layout.addLayout(top_row)

        self._inputs = QStackedWidget()

        # file page
        file_page = QWidget()
        file_layout = QHBoxLayout(file_page)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(9)
        self._file_edit = QLineEdit()
        self._file_edit.setPlaceholderText("Path to an MP4, AVI or MKV file")
        file_layout.addWidget(self._file_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_file)
        file_layout.addWidget(browse)
        self._inputs.addWidget(file_page)

        # webcam page
        webcam_page = QWidget()
        webcam_layout = QHBoxLayout(webcam_page)
        webcam_layout.setContentsMargins(0, 0, 0, 0)
        webcam_layout.setSpacing(9)
        self._device_combo = QComboBox()
        self._device_combo.setMinimumWidth(260)
        self._device_combo.addItem("Not scanned yet", -1)
        webcam_layout.addWidget(self._device_combo)
        rescan = QPushButton("Rescan devices")
        rescan.clicked.connect(self._scan_webcams)
        webcam_layout.addWidget(rescan)
        self._webcam_hint = QLabel("")
        self._webcam_hint.setObjectName("dim")
        webcam_layout.addWidget(self._webcam_hint, 1)
        self._inputs.addWidget(webcam_page)

        # rtsp page
        rtsp_page = QWidget()
        rtsp_layout = QHBoxLayout(rtsp_page)
        rtsp_layout.setContentsMargins(0, 0, 0, 0)
        rtsp_layout.setSpacing(9)
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("rtsp://192.168.1.50:554/stream1")
        rtsp_layout.addWidget(self._url_edit, 1)
        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("Username")
        self._user_edit.setFixedWidth(120)
        rtsp_layout.addWidget(self._user_edit)
        self._pass_edit = QLineEdit()
        self._pass_edit.setPlaceholderText("Password")
        self._pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._pass_edit.setFixedWidth(120)
        rtsp_layout.addWidget(self._pass_edit)
        test_btn = QPushButton("Test")
        test_btn.clicked.connect(self._test_stream)
        rtsp_layout.addWidget(test_btn)
        discover_btn = QPushButton("Discover")
        discover_btn.setToolTip("Search the local network for ONVIF cameras")
        discover_btn.clicked.connect(self._discover_onvif)
        rtsp_layout.addWidget(discover_btn)
        self._inputs.addWidget(rtsp_page)

        # earthcam page
        earthcam_page = QWidget()
        earthcam_layout = QHBoxLayout(earthcam_page)
        earthcam_layout.setContentsMargins(0, 0, 0, 0)
        earthcam_layout.setSpacing(9)
        self._earthcam_combo = QComboBox()
        self._earthcam_combo.setMinimumWidth(320)
        self._populate_earthcam()
        earthcam_layout.addWidget(self._earthcam_combo, 0)
        countries = len({site.country for site in EARTHCAM_CATALOGUE})
        self._earthcam_hint = QLabel(
            f"Live video · {len(EARTHCAM_CATALOGUE)} cameras · {countries} countries"
        )
        self._earthcam_hint.setObjectName("dim")
        earthcam_layout.addWidget(self._earthcam_hint, 1)
        self._inputs.addWidget(earthcam_page)

        bar_layout.addWidget(self._inputs)
        root.addWidget(source_bar)

        # -- video + detections -------------------------------------------
        middle = QHBoxLayout()
        middle.setSpacing(12)
        self._video = VideoView()
        self._video.set_empty(
            "No video source",
            "Choose a video file, a webcam, an RTSP stream or a live EarthCam "
            "street camera above, then press Connect.",
        )
        middle.addWidget(self._video, 1)
        self._panel = DetectionPanel()
        middle.addWidget(self._panel, 0)
        root.addLayout(middle, 1)

        # -- transport ----------------------------------------------------
        transport = QFrame()
        transport.setObjectName("toolbar")
        transport_layout = QHBoxLayout(transport)
        transport_layout.setContentsMargins(12, 8, 12, 8)
        transport_layout.setSpacing(8)

        self._play_btn = _tool_button("Play", "play")
        self._play_btn.clicked.connect(self._resume)
        self._pause_btn = _tool_button("Pause", "pause")
        self._pause_btn.clicked.connect(self._pause)
        self._stop_btn = _tool_button("Stop", "stop")
        self._stop_btn.clicked.connect(self._disconnect)
        for button in (self._play_btn, self._pause_btn, self._stop_btn):
            transport_layout.addWidget(button)

        self._seek = QSlider(Qt.Orientation.Horizontal)
        self._seek.setRange(0, 1000)
        self._seek.setEnabled(False)
        self._seek.sliderPressed.connect(self._on_seek_pressed)
        self._seek.sliderReleased.connect(self._on_seek_released)
        self._seek.valueChanged.connect(self._on_seek_moved)
        transport_layout.addWidget(self._seek, 1)

        self._time_label = QLabel("--:-- / --:--")
        self._time_label.setObjectName("mono")
        self._time_label.setMinimumWidth(112)
        transport_layout.addWidget(self._time_label)

        self._snapshot_btn = _tool_button("Snapshot", "snapshot")
        self._snapshot_btn.clicked.connect(self._take_snapshot)
        transport_layout.addWidget(self._snapshot_btn)

        self._record_btn = _tool_button("Record", "record", checkable=True)
        self._record_btn.toggled.connect(self._toggle_recording)
        transport_layout.addWidget(self._record_btn)

        self._tracking_btn = _tool_button("Tracking", "search", checkable=True)
        self._tracking_btn.toggled.connect(self._toggle_tracking)
        transport_layout.addWidget(self._tracking_btn)

        self._trails_btn = _tool_button("Trails", "analytics", checkable=True)
        self._trails_btn.toggled.connect(self._toggle_trails)
        transport_layout.addWidget(self._trails_btn)

        self._fps_label = QLabel("—")
        self._fps_label.setObjectName("mono")
        self._fps_label.setMinimumWidth(150)
        self._fps_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        transport_layout.addWidget(self._fps_label)

        root.addWidget(transport)

        self._timeline = EventTimeline()
        self._timeline.event_activated.connect(self.event_activated)
        root.addWidget(self._timeline)

        self._wire_pipeline()
        self._restore_last_source()
        self._sync_toggles()
        self._update_controls(STATE_IDLE)

    # -- wiring ------------------------------------------------------------
    def _wire_pipeline(self) -> None:
        pipeline = self._pipeline
        pipeline.state_changed.connect(self._update_controls)
        pipeline.opened.connect(self._on_opened)
        pipeline.failed.connect(self._on_failed)
        pipeline.reconnecting.connect(self._on_reconnecting)
        pipeline.source_finished.connect(self._on_finished)
        pipeline.position_changed.connect(self._on_position)
        pipeline.stats_ready.connect(self.on_stats)
        pipeline.detections_ready.connect(self._panel.set_detections)
        pipeline.event_created.connect(self._on_event)
        pipeline.model_status.connect(self._on_model_status)
        pipeline.snapshot_saved.connect(self._on_snapshot_saved)
        pipeline.recording_state.connect(self._on_recording_state)
        pipeline.status.connect(self._on_status)
        pipeline.error.connect(lambda message: self._ctx.notify(message, "error"))

        if self._pipeline.model_state == "error":
            self._on_model_status("error", self._pipeline.model_error)

    # -- source selection --------------------------------------------------
    def _populate_earthcam(self) -> None:
        """Fill the camera list, one visual group per country."""
        previous_country = None
        for site in EARTHCAM_CATALOGUE:
            if site.country != previous_country:
                if self._earthcam_combo.count():
                    self._earthcam_combo.insertSeparator(self._earthcam_combo.count())
                previous_country = site.country
            self._earthcam_combo.addItem(f"{site.country} · {site.label}", site.page)

    def _on_source_type_changed(self, index: int) -> None:
        self._inputs.setCurrentIndex(max(0, index))
        self._update_controls(self._pipeline.state)

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select a video file", "", VIDEO_FILE_FILTER)
        if path:
            self._file_edit.setText(path)

    def _scan_webcams(self) -> None:
        if self._scanner is not None and self._scanner.isRunning():
            return
        self._webcam_hint.setText("Scanning…")
        self._scanner = _WebcamScanner(self)
        self._scanner.found.connect(self._on_webcams_found)
        self._scanner.start()

    def _on_webcams_found(self, devices: list) -> None:
        self._device_combo.clear()
        if not devices:
            self._device_combo.addItem("No webcam detected", -1)
            self._webcam_hint.setText(
                "No camera could be opened. Check Windows privacy settings or use a video file."
            )
            return
        for device in devices:
            self._device_combo.addItem(device.label, device.index)
        self._webcam_hint.setText(f"{len(devices)} device(s) available.")

    def _test_stream(self) -> None:
        url = self._url_edit.text().strip()
        if not url:
            QMessageBox.information(self, "Test connection", "Enter an RTSP URL first.")
            return
        self._status.setText("Testing stream…")
        self._status.setStyleSheet(f"color: {theme.WARNING}; font-size: 9pt;")
        ok, message, info = test_stream(
            url, self._user_edit.text(), self._pass_edit.text(), timeout_s=10.0
        )
        self._status.setText("Stream OK" if ok else "Stream test failed")
        self._status.setStyleSheet(
            f"color: {theme.SUCCESS if ok else theme.DANGER}; font-size: 9pt;"
        )
        if ok:
            QMessageBox.information(self, "Test connection", message)
        else:
            QMessageBox.warning(self, "Test connection", message)

    def _discover_onvif(self) -> None:
        if self._onvif_scanner is not None and self._onvif_scanner.isRunning():
            return
        self._status.setText("Searching for ONVIF cameras…")
        self._onvif_scanner = _OnvifScanner(self)
        self._onvif_scanner.found.connect(self._on_onvif_found)
        self._onvif_scanner.start()

    def _on_onvif_found(self, devices: list) -> None:
        self._status.setText("Idle")
        self._status.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 9pt;")
        if not devices:
            QMessageBox.information(
                self,
                "ONVIF discovery",
                "No ONVIF camera answered the WS-Discovery probe.\n\n"
                "This is common: many cameras have ONVIF disabled, sit on another "
                "subnet, or block multicast traffic. Enter the RTSP URL manually - "
                "it is usually shown in the camera's web interface.",
            )
            return
        lines = []
        for device in devices[:8]:
            lines.append(f"• {device.name}")
            if device.hardware:
                lines.append(f"    model: {device.hardware}")
            if device.service_url:
                lines.append(f"    service: {device.service_url}")
        QMessageBox.information(
            self,
            "ONVIF discovery",
            "Discovered devices:\n\n" + "\n".join(lines) + "\n\n"
            "Discovery does not return a playable stream URL. Copy the RTSP URL "
            "from the camera's web interface, or install the optional 'onvif-zeep' "
            "package to resolve media profiles automatically.",
        )

    # -- connect / disconnect ---------------------------------------------
    def _build_source(self) -> CameraSource | None:
        kind = self._source_combo.currentData()
        if kind == SOURCE_FILE:
            path = self._file_edit.text().strip()
            if not path:
                QMessageBox.information(self, "No file selected", "Choose a video file first.")
                return None
            source = CameraSource(kind=SOURCE_FILE, identifier=path)
            if not source.exists():
                QMessageBox.warning(
                    self, "File not found", f"This file does not exist:\n{path}"
                )
                return None
            return source

        if kind == SOURCE_EARTHCAM:
            page = self._earthcam_combo.currentData()
            if not page:
                QMessageBox.information(
                    self, "No camera", "Choose an EarthCam camera from the list first."
                )
                return None
            site = next((item for item in EARTHCAM_CATALOGUE if item.page == page), None)
            name = f"{site.country} · {site.label}" if site else "EarthCam"
            return CameraSource(kind=SOURCE_EARTHCAM, identifier=str(page), name=name)

        if kind == SOURCE_WEBCAM:
            index = self._device_combo.currentData()
            if index is None or int(index) < 0:
                QMessageBox.information(
                    self,
                    "No webcam",
                    "No webcam has been detected yet. Press 'Rescan devices'.\n\n"
                    "You can also connect a video file instead - no camera is required "
                    "to use the application.",
                )
                return None
            return CameraSource(
                kind=SOURCE_WEBCAM, identifier=str(int(index)), name=f"Webcam {int(index)}"
            )

        url = self._url_edit.text().strip()
        if not url:
            QMessageBox.information(self, "No URL", "Enter an RTSP URL first.")
            return None
        if "://" not in url:
            QMessageBox.warning(
                self,
                "Invalid URL",
                "The URL must include a scheme, for example:\n"
                "rtsp://192.168.1.50:554/stream1",
            )
            return None
        source = CameraSource(
            kind=SOURCE_RTSP,
            identifier=url,
            username=self._user_edit.text().strip(),
            password=self._pass_edit.text(),
        )
        return source

    def _connect(self) -> None:
        source = self._build_source()
        if source is None:
            return
        try:
            self._ctx.config.set("camera.last_source", source.to_config())
        except Exception:
            pass
        self._banner.setVisible(False)
        self._video.set_loading("Connecting…", "Opening the video source.")
        self._status.setText("Connecting…")
        self._status.setStyleSheet(f"color: {theme.WARNING}; font-size: 9pt;")
        self._pipeline.start(source)

    def _disconnect(self) -> None:
        self._pipeline.stop()
        self._video.clear()
        self._panel.clear()
        self._status.setText("Idle")
        self._status.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 9pt;")
        self._fps_label.setText("—")
        self._time_label.setText("--:-- / --:--")
        self._seek.setValue(0)
        self._record_btn.setChecked(False)

    # -- transport ---------------------------------------------------------
    def _resume(self) -> None:
        if self._pipeline.is_running:
            self._pipeline.resume()

    def _pause(self) -> None:
        if self._pipeline.is_running:
            self._pipeline.pause()

    def _on_seek_pressed(self) -> None:
        self._seek_block = True

    def _on_seek_released(self) -> None:
        self._seek_block = False
        if self._duration > 0:
            self._pipeline.seek(self._seek.value() / 1000.0 * self._duration)

    def _on_seek_moved(self, value: int) -> None:
        if self._seek_block and self._duration > 0:
            seconds = value / 1000.0 * self._duration
            self._time_label.setText(f"{self._clock(seconds)} / {self._clock(self._duration)}")

    @staticmethod
    def _clock(seconds: float) -> str:
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, sec = divmod(remainder, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{sec:02d}"
        return f"{minutes:02d}:{sec:02d}"

    def _take_snapshot(self) -> None:
        if not self._pipeline.is_running:
            self._ctx.notify("Connect a camera before taking a snapshot.", "warning")
            return
        self._pipeline.snapshot()

    def _toggle_recording(self, enabled: bool) -> None:
        if enabled and not self._pipeline.is_running:
            self._record_btn.setChecked(False)
            self._ctx.notify("Connect a camera before recording.", "warning")
            return
        self._pipeline.set_recording(enabled)

    def _toggle_tracking(self, enabled: bool) -> None:
        self._ctx.config.set("detection.tracking_enabled", bool(enabled))
        self._pipeline.apply_settings()

    def _toggle_trails(self, enabled: bool) -> None:
        self._ctx.config.set("detection.show_trails", bool(enabled))
        self._pipeline.apply_settings()

    def _sync_toggles(self) -> None:
        detection = self._ctx.config.section("detection")
        self._tracking_btn.blockSignals(True)
        self._tracking_btn.setChecked(bool(detection.get("tracking_enabled", True)))
        self._tracking_btn.blockSignals(False)
        self._trails_btn.blockSignals(True)
        self._trails_btn.setChecked(bool(detection.get("show_trails", True)))
        self._trails_btn.blockSignals(False)

    # -- pipeline callbacks ------------------------------------------------
    def _update_controls(self, state: str) -> None:
        running = state in (STATE_RUNNING, STATE_PAUSED, STATE_CONNECTING)
        self._connect_btn.setEnabled(not running)
        self._disconnect_btn.setEnabled(running)
        self._play_btn.setEnabled(state == STATE_PAUSED)
        self._pause_btn.setEnabled(state == STATE_RUNNING)
        self._stop_btn.setEnabled(running)
        self._snapshot_btn.setEnabled(state == STATE_RUNNING)
        source = self._pipeline.source
        is_file = bool(source and source.kind == SOURCE_FILE)
        self._seek.setEnabled(is_file and state in (STATE_RUNNING, STATE_PAUSED))
        self._source_combo.setEnabled(not running)
        self._inputs.setEnabled(not running)

        labels = {
            STATE_IDLE: ("Idle", theme.TEXT_MUTED),
            STATE_CONNECTING: ("Connecting…", theme.WARNING),
            STATE_RUNNING: ("Streaming", theme.SUCCESS),
            STATE_PAUSED: ("Paused", theme.WARNING),
            STATE_ERROR: ("Error", theme.DANGER),
            STATE_FINISHED: ("Finished", theme.TEXT_MUTED),
        }
        text, colour = labels.get(state, (state, theme.TEXT_MUTED))
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {colour}; font-size: 9pt;")

        if state == STATE_PAUSED:
            self._video.set_badge("PAUSED", theme.WARNING)
        elif state == STATE_RUNNING:
            self._video.set_badge("LIVE", theme.SUCCESS)
        elif state in (STATE_IDLE, STATE_FINISHED, STATE_ERROR):
            self._video.set_badge("")

    def _on_opened(self, info: dict) -> None:
        self._duration = float(info.get("duration_s") or 0.0)
        self._video.set_badge("LIVE", theme.SUCCESS)
        self._status.setText("Streaming")
        self._status.setStyleSheet(f"color: {theme.SUCCESS}; font-size: 9pt;")
        if self._duration > 0:
            self._time_label.setText(f"00:00 / {self._clock(self._duration)}")
        else:
            self._time_label.setText("live")
        self._panel.set_tracking_note(str(self._ctx.pipeline.last_stats.get("tracking_mode", "")))

    def _on_failed(self, message: str) -> None:
        self._video.set_error("Could not open the source", message)
        self._status.setText("Error")
        self._status.setStyleSheet(f"color: {theme.DANGER}; font-size: 9pt;")
        self._panel.clear()

    def _on_reconnecting(self, message: str) -> None:
        self._video.set_loading("Reconnecting…", message)
        self._status.setText("Reconnecting…")
        self._status.setStyleSheet(f"color: {theme.WARNING}; font-size: 9pt;")

    def _on_finished(self) -> None:
        self._video.set_empty("Playback finished", "The end of the file was reached.")
        self._status.setText("Finished")
        self._status.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 9pt;")

    def _on_position(self, position: float, duration: float) -> None:
        if duration <= 0:
            return
        self._duration = duration
        if not self._seek_block:
            value = int(max(0.0, min(1.0, position / duration)) * 1000)
            self._seek.blockSignals(True)
            self._seek.setValue(value)
            self._seek.blockSignals(False)
            self._time_label.setText(
                f"{self._clock(position)} / {self._clock(duration)}"
            )

    def _on_event(self, record) -> None:
        self._timeline.add_event(record)
        if getattr(record, "severity", "") == SEVERITY_ALARM:
            self._alert_text.setText(
                f"ALARM · {record.title} · {format_timestamp(record.ts)}"
            )
            self._alert_banner.setVisible(True)
            self._alert_timer.start()
            self._ctx.notify(f"Alarm: {record.title}", "error")

    def _on_model_status(self, state: str, message: str) -> None:
        if state == "error":
            self._banner_text.setText(
                "Detection model unavailable - the video feed still works, but no "
                "objects will be detected.\n" + message
            )
            self._banner.setVisible(True)
        elif state == "ready":
            self._banner.setVisible(False)

    def _on_status(self, message: str) -> None:
        self._status.setText(message)
        self._status.setStyleSheet(f"color: {theme.WARNING}; font-size: 9pt;")

    def _retry_model(self) -> None:
        """Reload the weights without touching the camera connection."""
        self._banner.setVisible(False)
        self._status.setText("Reloading the detection model…")
        self._status.setStyleSheet(f"color: {theme.WARNING}; font-size: 9pt;")
        self._pipeline.reload_model()

    def _on_snapshot_saved(self, path: str) -> None:
        self._ctx.notify(f"Snapshot saved to {path}", "success")

    def _on_recording_state(self, recording: bool, path: str) -> None:
        self._record_btn.blockSignals(True)
        self._record_btn.setChecked(recording)
        self._record_btn.blockSignals(False)
        if recording:
            self._video.set_badge("REC", theme.DANGER)
            self._ctx.notify(f"Recording to {path}", "success")
        elif path:
            self._ctx.notify(f"Recording saved to {path}", "success")
            if self._pipeline.state == STATE_RUNNING:
                self._video.set_badge("LIVE", theme.SUCCESS)

    # -- stats -------------------------------------------------------------
    def on_stats(self, stats: dict) -> None:
        processed = float(stats.get("processed_fps", 0.0) or 0.0)
        inference = float(stats.get("inference_ms", 0.0) or 0.0)
        capture = float(stats.get("capture_fps", 0.0) or 0.0)
        self._fps_label.setText(
            f"{processed:.1f} fps · {inference:.0f} ms · in {capture:.0f} fps"
        )
        self._panel.set_tracking_note(str(stats.get("tracking_mode", "")))

    def show_frame(self, image) -> None:
        if image is not None:
            self._video.set_frame(image)

    def current_frame(self):
        """Last painted frame, used as the reference for the region editor."""
        return self._video.current_image()

    # -- misc --------------------------------------------------------------
    def _restore_last_source(self) -> None:
        source = CameraSource.from_config(self._ctx.config.get("camera.last_source"))
        if source is None:
            self._source_combo.setCurrentIndex(0)
            self._inputs.setCurrentIndex(0)
            return
        index = self._source_combo.findData(source.kind)
        if index < 0:
            index = 0
        self._source_combo.setCurrentIndex(index)
        self._inputs.setCurrentIndex(index)
        if source.kind == SOURCE_FILE:
            self._file_edit.setText(source.identifier)
        elif source.kind == SOURCE_RTSP:
            self._url_edit.setText(source.identifier)
            self._user_edit.setText(source.username)
            self._pass_edit.setText(source.password)
        elif source.kind == SOURCE_EARTHCAM:
            position = self._earthcam_combo.findData(source.identifier)
            if position >= 0:
                self._earthcam_combo.setCurrentIndex(position)
        else:
            self._device_combo.clear()
            self._device_combo.addItem(f"Webcam {source.identifier}", int(source.identifier or 0))

    def refresh(self) -> None:
        self._sync_toggles()
        try:
            rows = self._ctx.event_repo.recent(24)
            self._timeline.set_events(rows)
        except Exception:
            pass

    def shutdown(self) -> None:
        for worker in (self._scanner, self._onvif_scanner):
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                worker.wait(2000)
