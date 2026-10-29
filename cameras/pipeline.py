"""Pipeline orchestration: one capture thread plus one long-lived inference thread.

The inference thread outlives individual camera connections so the YOLO model is
loaded once per application run instead of once per connection. Switching source
resets tracking state but keeps the weights in memory.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from cameras.capture_thread import CaptureThread
from cameras.inference_thread import InferenceThread
from cameras.source import CameraSource
from utils.buffer import LatestBuffer
from utils.logging_setup import get_logger

log = get_logger(__name__)

STATE_IDLE = "idle"
STATE_CONNECTING = "connecting"
STATE_RUNNING = "running"
STATE_PAUSED = "paused"
STATE_ERROR = "error"
STATE_FINISHED = "finished"


class PipelineController(QObject):
    state_changed = Signal(str)
    source_changed = Signal(object)
    opened = Signal(dict)
    failed = Signal(str)
    stats_ready = Signal(dict)
    detections_ready = Signal(list)
    event_created = Signal(object)
    model_status = Signal(str, str)
    position_changed = Signal(float, float)
    source_finished = Signal()
    reconnecting = Signal(str)
    snapshot_saved = Signal(str)
    recording_state = Signal(bool, str)
    error = Signal(str)
    status = Signal(str)

    def __init__(
        self,
        config,
        event_repo,
        session_repo,
        models_dir: Path,
        snapshot_dir: Path,
        recording_dir: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._event_repo = event_repo
        self._session_repo = session_repo
        self._models_dir = Path(models_dir)
        self._snapshot_dir = Path(snapshot_dir)
        self._recording_dir = Path(recording_dir)

        self._capture_buffer: LatestBuffer = LatestBuffer()
        self._display_buffer: LatestBuffer = LatestBuffer()
        self._capture: CaptureThread | None = None
        self._inference: InferenceThread | None = None

        self._state = STATE_IDLE
        self._source: CameraSource | None = None
        self._pending_source: CameraSource | None = None
        self._session_id: int | None = None
        self._session_started = 0.0
        self._last_stats: dict = {}

        # Start loading the model right away. The weights take several seconds
        # to import and initialise, and doing that here means it is ready by the
        # time the user has picked a source. It also prevents a short video file
        # from being played out before inference is able to look at any frame.
        self._create_inference_thread()

    # -- state -------------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    @property
    def source(self) -> CameraSource | None:
        return self._source

    @property
    def is_running(self) -> bool:
        return self._capture is not None and self._capture.isRunning()

    @property
    def is_paused(self) -> bool:
        return bool(self._capture and self._capture.is_paused)

    @property
    def display_buffer(self) -> LatestBuffer:
        return self._display_buffer

    @property
    def last_stats(self) -> dict:
        return dict(self._last_stats)

    @property
    def model_state(self) -> str:
        return self._inference.model_state if self._inference is not None else "idle"

    @property
    def model_error(self) -> str:
        return self._inference.model_error if self._inference is not None else ""

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    # -- lifecycle ---------------------------------------------------------
    def start(self, source: CameraSource) -> None:
        self.stop()
        self._source = source
        self._pending_source = source
        self.source_changed.emit(source)

        if self._inference is None:
            self._create_inference_thread()

        settings = self._config.snapshot()
        self._inference.apply_settings(settings)
        self._inference.set_camera(source.display_name)
        # Retry a failed model load when the user reconnects; that is the moment
        # they are most likely to have fixed the download or the weights path.
        self._inference.request_reset(
            reload_model=self._inference.model_state == "error"
        )

        self._set_state(STATE_CONNECTING)

        if self._inference.model_state == "loading":
            # Opening the source now would consume frames that nothing can
            # analyse yet. Wait for the model, then start capture.
            self.status.emit("Loading the detection model before opening the source…")
            log.info("Deferring capture start until the model finishes loading")
            return

        self._launch_capture()

    def _launch_capture(self) -> None:
        source = self._pending_source
        if source is None:
            return
        self._pending_source = None
        if self._capture is not None:
            return

        self._capture_buffer.clear()
        self._display_buffer.clear()
        self._capture_buffer.reset_counters()

        video = self._config.snapshot().get("video", {})
        capture = CaptureThread(source, self._capture_buffer, options=video)
        capture.opened.connect(self._on_opened)
        capture.failed.connect(self._on_failed)
        capture.source_finished.connect(self._on_source_finished)
        capture.position_changed.connect(self.position_changed)
        capture.capture_stats.connect(self._on_capture_stats)
        capture.reconnecting.connect(self.reconnecting)

        self._capture = capture
        self._open_session(source)
        self.status.emit("Opening the video source…")
        capture.start()
        log.info("Pipeline started for %s", source.safe_identifier())

    def _on_model_status(self, state: str, message: str) -> None:
        self.model_status.emit(state, message)
        if state != "loading" and self._pending_source is not None:
            self._launch_capture()

    def stop(self) -> None:
        self._pending_source = None
        capture = self._capture
        self._capture = None
        if capture is not None:
            try:
                capture.set_paused(False)
                capture.requestInterruption()
                if capture.wait(5000):
                    capture.deleteLater()
                else:
                    # Never delete a QThread that is still running: that is a
                    # hard crash. Let it finish on its own and leak the object.
                    log.warning("Capture thread still running after 5 s; not deleting it")
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("Error stopping capture: %s", exc)
        self._capture_buffer.clear()
        if self._source is not None:
            self._close_session()
        self._set_state(STATE_IDLE)

    def shutdown(self) -> None:
        """Called from the window's close handler."""
        self.stop()
        inference = self._inference
        self._inference = None
        if inference is not None:
            try:
                inference.set_recording(False)
                inference.requestInterruption()
                inference.request_reset()
                if not inference.wait(12000):
                    log.warning("Inference thread did not stop within 12 s")
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("Error stopping inference: %s", exc)
        self._display_buffer.close()
        log.info("Pipeline shut down")

    def _create_inference_thread(self) -> None:
        settings = self._config.snapshot()
        inference = InferenceThread(
            input_buffer=self._capture_buffer,
            output_buffer=self._display_buffer,
            settings=settings,
            models_dir=self._models_dir,
            event_repo=self._event_repo,
            snapshot_dir=self._snapshot_dir,
            recording_dir=self._recording_dir,
        )
        inference.stats_ready.connect(self._on_stats)
        inference.detections_ready.connect(self.detections_ready)
        inference.event_created.connect(self.event_created)
        inference.model_status.connect(self._on_model_status)
        inference.snapshot_saved.connect(self.snapshot_saved)
        inference.recording_state.connect(self.recording_state)
        inference.error.connect(self.error)
        self._inference = inference
        inference.start()

    # -- controls ----------------------------------------------------------
    def pause(self) -> None:
        if self._capture is not None:
            self._capture.set_paused(True)
            self._set_state(STATE_PAUSED)

    def resume(self) -> None:
        if self._capture is not None:
            self._capture.set_paused(False)
            self._set_state(STATE_RUNNING)

    def seek(self, seconds: float) -> None:
        if self._capture is not None:
            self._capture.seek(seconds)

    def snapshot(self) -> None:
        if self._inference is not None:
            self._inference.request_snapshot()

    def set_recording(self, enabled: bool) -> None:
        if self._inference is not None:
            self._inference.set_recording(enabled)

    def apply_settings(self, settings: dict | None = None) -> None:
        if self._inference is not None:
            self._inference.apply_settings(settings or self._config.snapshot())

    def reload_model(self) -> None:
        if self._inference is not None:
            self._inference.request_reset(reload_model=True)

    # -- capture callbacks -------------------------------------------------
    def _on_opened(self, info: dict) -> None:
        self._set_state(STATE_RUNNING)
        self.opened.emit(info)

    def _on_capture_stats(self, stats: dict) -> None:
        if self._inference is not None:
            self._inference.update_capture_fps(float(stats.get("capture_fps", 0.0) or 0.0))

    def _on_failed(self, message: str) -> None:
        log.error("Pipeline failure: %s", message)
        self._set_state(STATE_ERROR)
        self._close_session()
        self.failed.emit(message)

    def _on_source_finished(self) -> None:
        self._set_state(STATE_FINISHED)
        self._close_session()
        self.source_finished.emit()

    def _on_stats(self, stats: dict) -> None:
        self._last_stats = dict(stats)
        self.stats_ready.emit(stats)

    # -- session bookkeeping ----------------------------------------------
    def _open_session(self, source: CameraSource) -> None:
        self._session_started = time.time()
        try:
            self._session_id = self._session_repo.start(
                source.display_name, source.kind, self._session_started
            )
        except Exception as exc:  # pragma: no cover - database dependent
            self._session_id = None
            log.warning("Could not open a session row: %s", exc)

    def _close_session(self) -> None:
        if self._session_id is None:
            return
        stats = self._last_stats
        if self._inference is not None:
            try:
                stats = self._inference.session_stats()
            except Exception:
                stats = self._last_stats
        try:
            self._session_repo.finish(
                self._session_id,
                ended=time.time(),
                frames_processed=int(stats.get("frames_processed", 0) or 0),
                frames_dropped=int(stats.get("frames_dropped", 0) or 0),
                detections=int(stats.get("detections", 0) or 0),
                avg_fps=float(stats.get("avg_fps", 0.0) or 0.0),
            )
        except Exception as exc:  # pragma: no cover - database dependent
            log.warning("Could not close the session row: %s", exc)
        finally:
            self._session_id = None
