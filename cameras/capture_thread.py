"""Capture thread: owns the OpenCV handle and never touches the interface.

Frames are pushed into a one-slot buffer, so a slow inference stage simply
causes older frames to be skipped instead of piling up in memory.
"""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path

import cv2
from PySide6.QtCore import QThread, Signal

from cameras.devices import open_webcam
from cameras.earthcam import open_earthcam_capture
from cameras.rtsp import diagnose_failure, open_stream
from cameras.source import (
    SOURCE_EARTHCAM,
    SOURCE_FILE,
    SOURCE_RTSP,
    SOURCE_WEBCAM,
    CameraSource,
)
from utils.buffer import FramePacket, LatestBuffer
from utils.logging_setup import get_logger

log = get_logger(__name__)


def open_capture(
    source: CameraSource, options: dict | None = None, should_stop=None
) -> tuple[cv2.VideoCapture | None, dict, str]:
    """Open ``source``. Returns ``(capture, info, error_message)``.

    ``should_stop`` is accepted for sources that pace themselves; the EarthCam
    stream is real video, so it does not need it, but the signature stays uniform.
    """
    options = options or {}
    if source.kind == SOURCE_FILE:
        path = Path(source.identifier)
        if not path.is_file():
            return None, {}, f"Video file not found:\n{path}"
        try:
            capture = cv2.VideoCapture(str(path))
        except Exception as exc:
            return None, {}, f"OpenCV could not open the file:\n{path}\n\n{exc}"
        if capture is None or not capture.isOpened():
            if capture is not None:
                capture.release()
            return None, {}, (
                f"OpenCV could not decode this file:\n{path}\n\n"
                "The file may be corrupt or use a codec that is missing from "
                "your OpenCV build. Re-encoding to H.264 MP4 usually fixes it."
            )
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if not (1.0 <= fps <= 240.0):
            fps = 25.0
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        info = {
            "kind": source.kind,
            "name": source.display_name,
            "width": width,
            "height": height,
            "fps": fps,
            "frames": frames,
            "duration_s": (frames / fps) if fps > 0 else 0.0,
            "is_live": False,
        }
        return capture, info, ""

    if source.kind == SOURCE_WEBCAM:
        try:
            index = int(source.identifier)
        except (TypeError, ValueError):
            index = 0
        capture = open_webcam(
            index,
            int(options.get("webcam_width", 0) or 0),
            int(options.get("webcam_height", 0) or 0),
        )
        if capture is None:
            return None, {}, (
                f"No webcam could be opened at index {index}.\n\n"
                "Checks:\n"
                "  1. Is another application (Teams, Zoom, OBS) using the camera?\n"
                "  2. Windows Settings > Privacy > Camera - allow desktop apps.\n"
                "  3. Try a different device index in the camera selector.\n"
                "  4. Use a video file instead if no camera is attached."
            )
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if not (1.0 <= fps <= 240.0):
            fps = 30.0
        info = {
            "kind": source.kind,
            "name": source.display_name,
            "width": width,
            "height": height,
            "fps": fps,
            "frames": 0,
            "duration_s": 0.0,
            "is_live": True,
        }
        return capture, info, ""

    if source.kind == SOURCE_RTSP:
        capture = open_stream(source.identifier, source.username, source.password)
        if capture is None:
            return None, {}, diagnose_failure(source.open_target(), source.username)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if not (1.0 <= fps <= 240.0):
            fps = 25.0
        info = {
            "kind": source.kind,
            "name": source.display_name,
            "width": width,
            "height": height,
            "fps": fps,
            "frames": 0,
            "duration_s": 0.0,
            "is_live": True,
        }
        return capture, info, ""

    if source.kind == SOURCE_EARTHCAM:
        capture, error = open_earthcam_capture(source.identifier, should_stop=should_stop)
        if capture is None:
            return None, {}, error
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if not (1.0 <= fps <= 240.0):
            fps = 25.0
        info = {
            "kind": source.kind,
            "name": source.display_name,
            "width": width,
            "height": height,
            "fps": fps,
            "frames": 0,
            "duration_s": 0.0,
            "is_live": True,
        }
        return capture, info, ""

    return None, {}, f"Unsupported source kind: {source.kind}"


class CaptureThread(QThread):
    opened = Signal(dict)
    failed = Signal(str)
    source_finished = Signal()
    position_changed = Signal(float, float)
    capture_stats = Signal(dict)
    reconnecting = Signal(str)

    def __init__(
        self,
        source: CameraSource,
        buffer: LatestBuffer,
        options: dict | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._buffer = buffer
        self._options = options or {}
        self._paused = False
        self._seek_target: float | None = None
        self._frames_read = 0

    # -- controls (called from the interface thread) -----------------------
    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)

    @property
    def is_paused(self) -> bool:
        return self._paused

    def seek(self, seconds: float) -> None:
        self._seek_target = max(0.0, float(seconds))

    # -- thread body -------------------------------------------------------
    def run(self) -> None:  # noqa: C901 - a capture loop is inherently branchy
        log.info("Capture starting: %s", self._source.safe_identifier())
        capture, info, error = open_capture(
            self._source, self._options, self.isInterruptionRequested
        )
        if capture is None:
            log.error("Capture open failed: %s", error)
            self.failed.emit(error)
            return

        try:
            self.opened.emit(info)
            self._loop(capture, info)
        finally:
            try:
                capture.release()
            except Exception:
                pass
            log.info("Capture thread finished after %d frames", self._frames_read)

    def _loop(self, capture: cv2.VideoCapture, info: dict) -> None:
        is_live = bool(info.get("is_live", True))
        source_fps = float(info.get("fps") or 25.0)
        period = 1.0 / source_fps if not is_live and source_fps > 0 else 0.0
        next_deadline = time.perf_counter()

        failures = 0
        last_position_emit = 0.0
        last_stats_emit = time.monotonic()
        stats_window: deque[float] = deque(maxlen=60)

        while not self.isInterruptionRequested():
            if self._paused:
                time.sleep(0.02)
                next_deadline = time.perf_counter()
                continue

            seek = self._seek_target
            if seek is not None:
                self._seek_target = None
                if not is_live:
                    try:
                        capture.set(cv2.CAP_PROP_POS_MSEC, seek * 1000.0)
                        next_deadline = time.perf_counter()
                    except Exception:
                        pass

            try:
                ok, frame = capture.read()
            except Exception as exc:  # pragma: no cover - backend dependent
                log.warning("Frame read raised: %s", exc)
                ok, frame = False, None

            if not ok or frame is None:
                if not is_live:
                    self.source_finished.emit()
                    return
                failures += 1
                if failures < 5:
                    time.sleep(0.02)
                    continue
                reopened = self._reconnect()
                if reopened is None:
                    return
                try:
                    capture.release()
                except Exception:
                    pass
                capture, info = reopened
                is_live = bool(info.get("is_live", True))
                source_fps = float(info.get("fps") or 25.0)
                period = 0.0 if is_live else (1.0 / source_fps if source_fps > 0 else 0.0)
                next_deadline = time.perf_counter()
                failures = 0
                continue

            failures = 0
            self._frames_read += 1
            now = time.monotonic()
            stats_window.append(now)

            position_s = 0.0
            duration_s = float(info.get("duration_s") or 0.0)
            if not is_live:
                try:
                    position_s = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
                except Exception:
                    position_s = 0.0

            self._buffer.put(
                FramePacket(
                    index=self._frames_read,
                    timestamp=time.time(),
                    frame=frame,
                    position_s=position_s,
                    duration_s=duration_s,
                    source_fps=source_fps,
                )
            )

            if not is_live and now - last_position_emit >= 0.4:
                last_position_emit = now
                self.position_changed.emit(position_s, duration_s)

            if now - last_stats_emit >= 1.0:
                last_stats_emit = now
                fps = 0.0
                if len(stats_window) >= 2:
                    span = stats_window[-1] - stats_window[0]
                    if span > 0:
                        fps = (len(stats_window) - 1) / span
                self.capture_stats.emit(
                    {
                        "capture_fps": round(fps, 1),
                        "frames_read": self._frames_read,
                        "buffer_dropped": self._buffer.dropped,
                    }
                )

            if period > 0.0:
                next_deadline += period
                delay = next_deadline - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                elif delay < -period * 2:
                    # We fell far behind (slow disk or heavy CPU load); resync
                    # instead of sprinting to catch up.
                    next_deadline = time.perf_counter()

    def _reconnect(self) -> tuple[cv2.VideoCapture, dict] | None:
        attempts = max(1, int(self._options.get("reconnect_attempts", 3)))
        delay = max(0.2, float(self._options.get("reconnect_delay_s", 3.0)))
        self.reconnecting.emit(
            f"Stream interrupted - reconnecting (up to {attempts} attempts)..."
        )
        log.warning("Live source lost; attempting %d reconnects", attempts)
        for attempt in range(1, attempts + 1):
            if self.isInterruptionRequested():
                return None
            time.sleep(delay)
            capture, new_info, error = open_capture(
                self._source, self._options, self.isInterruptionRequested
            )
            if capture is not None:
                self.opened.emit(new_info)
                log.info("Reconnected on attempt %d", attempt)
                return capture, new_info
            log.warning("Reconnect attempt %d failed: %s", attempt, error)
        self.failed.emit(
            f"The stream could not be reconnected after {attempts} attempts.\n\n"
            "The camera may be offline, the network may have dropped, or another "
            "client may have taken the single allowed RTSP slot."
        )
        return None
