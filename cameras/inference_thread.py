"""Inference thread: detection, tracking, events, annotation, recording.

This thread is the only place that touches the YOLO model. It reads the newest
captured frame, produces an annotated frame, and publishes compact statistics.
The interface never calls into it synchronously, so a slow model cannot freeze
the window.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
from PySide6.QtCore import QThread, Signal

from config.defaults import is_vehicle, resolve_enabled_classes
from detection.detector import Detector, DetectorError
from detection.model_manager import resolve_model_path
from detection.types import DetectionResult
from events.engine import EventEngine
from tracking.trails import TrailStore
from utils.buffer import LatestBuffer, ProcessedFrame
from utils.imaging import annotate_frame, save_snapshot, to_qimage
from utils.logging_setup import get_logger

log = get_logger(__name__)

_INVALID_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(value: str, fallback: str = "camera") -> str:
    cleaned = _INVALID_FILENAME.sub("_", (value or "").strip()).strip("_")
    return cleaned[:60] or fallback


class InferenceThread(QThread):
    stats_ready = Signal(dict)
    detections_ready = Signal(list)
    event_created = Signal(object)
    model_status = Signal(str, str)
    snapshot_saved = Signal(str)
    recording_state = Signal(bool, str)
    error = Signal(str)

    def __init__(
        self,
        input_buffer: LatestBuffer,
        output_buffer: LatestBuffer,
        settings: dict,
        models_dir: Path,
        event_repo,
        snapshot_dir: Path,
        recording_dir: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._input = input_buffer
        self._output = output_buffer
        self._settings = settings or {}
        self._models_dir = Path(models_dir)
        self._event_repo = event_repo
        self._snapshot_dir = Path(snapshot_dir)
        self._recording_dir = Path(recording_dir)

        self._lock = threading.Lock()
        self._pending_settings: dict | None = None
        self._reset_requested = True
        self._reload_model = False
        self._snapshot_requested = False
        self._recording_requested = False
        self._camera_name = ""

        self._detector: Detector | None = None
        self._model_error = ""
        # The thread's first action is loading the model, so this is the honest
        # initial state. Starting at "idle" would let a fast start() skip the
        # "wait for the model" branch and consume a short clip before inference
        # was ready.
        self._model_state = "loading"
        self._engine = EventEngine(
            self._settings.get("events", {}),
            self._settings.get("safety_model", {}),
        )
        self._trails = TrailStore(
            max_points=int(self._settings.get("detection", {}).get("trail_length", 32))
        )

        # Second, independent detector for the violence model. It is optional:
        # if the weights are absent or fail to load, the main pipeline carries on.
        self._safety: Detector | None = None
        self._safety_state = "off"
        self._safety_error = ""
        self._safety_hits: list = []
        self._safety_counter = 0

        self._frames_processed = 0
        self._detections_total = 0
        self._session_frames = 0
        self._session_detections = 0
        self._session_started_at = time.time()
        self._frames_since_prune = 0
        self._processed_times: deque[float] = deque(maxlen=40)
        self._inference_times: deque[float] = deque(maxlen=30)
        self._last_stats_emit = 0.0
        self._last_result = DetectionResult()
        self._writer: cv2.VideoWriter | None = None
        self._recording_path: Path | None = None
        self._capture_fps = 0.0

    # -- thread-safe controls ---------------------------------------------
    def apply_settings(self, settings: dict) -> None:
        with self._lock:
            self._pending_settings = settings

    def set_camera(self, name: str) -> None:
        self._camera_name = name or ""

    def update_capture_fps(self, fps: float) -> None:
        self._capture_fps = float(fps or 0.0)

    def request_reset(self, reload_model: bool = False) -> None:
        self._reset_requested = True
        if reload_model:
            with self._lock:
                self._reload_model = True

    def request_snapshot(self) -> None:
        self._snapshot_requested = True

    def set_recording(self, enabled: bool) -> None:
        self._recording_requested = bool(enabled)

    @property
    def model_error(self) -> str:
        return self._model_error

    @property
    def model_state(self) -> str:
        return self._model_state

    def session_stats(self) -> dict:
        """Counters for the current source, read at the moment a session closes.

        The pipeline used to rely on the last emitted stats packet, which could
        be up to a quarter second stale - or still belong to the previous source
        if the new one had not produced a frame yet.
        """
        if self._reset_requested:
            return {"frames_processed": 0, "frames_dropped": 0, "detections": 0, "avg_fps": 0.0}
        elapsed = max(1e-6, time.time() - self._session_started_at)
        frames = self._session_frames
        return {
            "frames_processed": frames,
            "frames_dropped": self._input.dropped,
            "detections": self._session_detections,
            "avg_fps": (frames / elapsed) if frames else 0.0,
        }

    # -- thread body -------------------------------------------------------
    def run(self) -> None:
        self._ensure_model()

        while not self.isInterruptionRequested():
            self._consume_pending()
            packet = self._input.wait_get(0.15)
            if packet is None:
                self._flush_stats(force=False)
                continue

            if self._reset_requested:
                self._reset_requested = False
                self._reset_state()

            result = self._infer(packet.frame)
            self._run_safety_model(packet.frame, result)
            self._frames_processed += 1
            self._session_frames += 1
            self._processed_times.append(time.monotonic())

            trails = self._trails.update(result.detections, time.time())

            annotated = self._annotate(packet.frame, result.detections, trails)

            self._evaluate_events(result, annotated)
            self._handle_snapshot(annotated)
            self._tick_recording(annotated)

            self._last_result = result
            self._publish(packet, annotated, result, trails)
            self._flush_stats(force=False)

        self._close_writer()
        self._output.clear()
        if self._detector is not None:
            self._detector.close()
            self._detector = None
        if self._safety is not None:
            self._safety.close()
            self._safety = None
        log.info("Inference thread stopped after %d frames", self._frames_processed)

    def _ensure_model(self) -> None:
        detection = self._settings.get("detection", {}) or {}
        self._model_state = "loading"
        self.model_status.emit("loading", "Loading detection model...")
        classes = self._effective_classes(self._settings)
        detector = Detector(
            model_name=str(detection.get("model", "yolov8n.pt")),
            models_dir=self._models_dir,
            device=str(detection.get("device", "cpu")),
            imgsz=int(detection.get("imgsz", 640)),
            conf=float(detection.get("confidence", 0.35)),
            iou=float(detection.get("iou", 0.45)),
            max_det=int(detection.get("max_detections", 100)),
            enabled_classes=classes,
            tracking=bool(detection.get("tracking_enabled", True)),
            torch_threads=int(detection.get("torch_threads", 0) or 0),
        )
        try:
            detector.load()
            self._detector = detector
            self._model_error = ""
            self._model_state = "ready"
            message = f"{detector.model_name} ready on {detector.device}"
            if detector.device_note:
                message += f" - {detector.device_note}"
            self.model_status.emit("ready", message)
            log.info("Detector ready (%s); class filter: %s",
                     detector.tracking_mode, ", ".join(classes) or "none")
        except DetectorError as exc:
            self._detector = None
            self._model_error = str(exc)
            self._model_state = "error"
            self.model_status.emit("error", str(exc))
            log.error("Model load failed: %s", exc)
        except Exception as exc:  # pragma: no cover - defensive
            self._detector = None
            self._model_error = f"Unexpected error while loading the model: {exc}"
            self._model_state = "error"
            self.model_status.emit("error", self._model_error)
            log.exception("Unexpected model load failure")

        self._ensure_safety_model()

    def _ensure_safety_model(self) -> None:
        """Load the optional violence model. Failure never blocks the main one."""
        safety = self._settings.get("safety_model", {}) or {}
        if not safety.get("enabled", True):
            self._safety_state = "off"
            self._safety = None
            self._safety_hits = []
            return

        model_name = str(safety.get("model", "yolo_small_weights.pt"))
        model_path = resolve_model_path(model_name, self._models_dir)
        if not Path(model_path).is_file():
            self._safety_state = "off"
            self._safety = None
            self._safety_hits = []
            log.info(
                "Violence model not found (%s); safety alerts stay limited to heuristics",
                model_path,
            )
            return

        self._safety_state = "loading"
        detection = self._settings.get("detection", {}) or {}
        try:
            detector = Detector(
                model_name=model_name,
                models_dir=self._models_dir,
                device=str(detection.get("device", "cpu")),
                imgsz=int(safety.get("imgsz", 640)),
                conf=float(safety.get("confidence", 0.45)),
                iou=float(safety.get("iou", 0.45)),
                max_det=20,
                enabled_classes=list(safety.get("classes", ["violence"]) or []),
                tracking=False,
                torch_threads=int(detection.get("torch_threads", 0) or 0),
            )
            detector.load()
            self._safety = detector
            self._safety_state = "ready"
            self._safety_error = ""
            log.info(
                "Violence model ready: %s (classes: %s)",
                model_name,
                ", ".join(detector.available_classes()) or "none",
            )
        except Exception as exc:
            self._safety = None
            self._safety_state = "error"
            self._safety_error = str(exc)
            log.warning("Violence model failed to load: %s", exc)
            self.error.emit(f"Violence model unavailable: {exc}")

    def _run_safety_model(self, frame, result: DetectionResult) -> None:
        """Run the violence model every N frames and merge its boxes."""
        if self._safety is None:
            return
        safety = self._settings.get("safety_model", {}) or {}
        stride = max(1, int(safety.get("run_every_n_frames", 2) or 1))
        self._safety_counter += 1
        if self._safety_counter >= stride:
            self._safety_counter = 0
            try:
                self._safety_hits = list(self._safety.infer(frame).detections)
            except Exception as exc:
                log.warning("Violence model inference failed: %s", exc)
                self._safety_hits = []
        if self._safety_hits:
            # Reused between runs so boxes do not flicker on skipped frames.
            result.detections.extend(self._safety_hits)

    @staticmethod
    def _effective_classes(settings: dict) -> list[str]:
        return resolve_enabled_classes(
            settings.get("detection"), settings.get("events")
        )

    def _consume_pending(self) -> None:
        with self._lock:
            pending = self._pending_settings
            self._pending_settings = None
            reload_model = self._reload_model
            self._reload_model = False

        safety_changed = False
        if pending is not None:
            previous = self._settings
            self._settings = pending
            detection = pending.get("detection", {}) or {}
            if previous.get("detection", {}).get("model") != detection.get("model"):
                reload_model = True
            if self._detector is not None:
                try:
                    self._detector.set_runtime_options(
                        conf=float(detection.get("confidence", 0.35)),
                        iou=float(detection.get("iou", 0.45)),
                        imgsz=int(detection.get("imgsz", 640)),
                        max_det=int(detection.get("max_detections", 100)),
                        enabled_classes=self._effective_classes(pending),
                        tracking=bool(detection.get("tracking_enabled", True)),
                        device=str(detection.get("device", "cpu")),
                    )
                except Exception as exc:
                    log.warning("Could not apply detection settings: %s", exc)
            safety = pending.get("safety_model", {}) or {}
            self._engine.configure(pending.get("events", {}), safety)
            previous_safety = previous.get("safety_model", {}) or {}
            safety_changed = (
                previous_safety.get("model") != safety.get("model")
                or bool(previous_safety.get("enabled", True))
                != bool(safety.get("enabled", True))
            )
            if self._safety is not None and not safety_changed:
                try:
                    self._safety.set_runtime_options(
                        conf=float(safety.get("confidence", 0.45)),
                        iou=float(safety.get("iou", 0.45)),
                        imgsz=int(safety.get("imgsz", 640)),
                        enabled_classes=list(safety.get("classes", []) or []),
                    )
                except Exception as exc:
                    log.warning("Could not apply violence-model settings: %s", exc)
            trail_length = max(2, int(detection.get("trail_length", 32) or 32))
            if trail_length != self._trails.max_points:
                self._trails = TrailStore(max_points=trail_length)
            if not detection.get("tracking_enabled", True):
                self._trails.reset()

        if reload_model:
            if self._detector is not None:
                self._detector.close()
                self._detector = None
            self._ensure_model()
            self._reset_requested = True

        if safety_changed and not reload_model:
            if self._safety is not None:
                self._safety.close()
                self._safety = None
            self._safety_hits = []
            self._ensure_safety_model()

    def _reset_state(self) -> None:
        if self._detector is not None:
            self._detector.reset_tracking()
        self._trails.reset()
        self._engine.reset()
        self._inference_times.clear()
        self._safety_hits = []
        self._safety_counter = 0
        # Per-session counters start again with every source, so a stored
        # session never inherits frames from the previous one.
        self._session_frames = 0
        self._session_detections = 0
        self._session_started_at = time.time()
        log.debug("Tracking and event state reset for the new source")

    # -- pipeline stages ---------------------------------------------------
    def _infer(self, frame) -> DetectionResult:
        detection = self._settings.get("detection", {}) or {}
        if not detection.get("enabled", True):
            height, width = frame.shape[:2]
            return DetectionResult(frame_size=(width, height))
        if self._detector is None:
            height, width = frame.shape[:2]
            return DetectionResult(frame_size=(width, height))
        try:
            result = self._detector.infer(frame)
            self._inference_times.append(result.inference_ms)
            self._detections_total += result.count
            self._session_detections += result.count
            return result
        except DetectorError as exc:
            self._model_error = str(exc)
            self._model_state = "error"
            self.model_status.emit("error", str(exc))
            self._detector = None
            height, width = frame.shape[:2]
            return DetectionResult(frame_size=(width, height))
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Inference error")
            self.error.emit(f"Inference error: {exc}")
            height, width = frame.shape[:2]
            return DetectionResult(frame_size=(width, height))

    def _annotate(self, frame, detections, trails):
        detection = self._settings.get("detection", {}) or {}
        regions = []
        if detection.get("enabled", True):
            height, width = frame.shape[:2]
            for region in self._engine.regions:
                if not region.enabled:
                    continue
                regions.append(
                    (region.name, region.to_pixels(width, height), region.color)
                )
        if not detections and not regions:
            return frame
        return annotate_frame(
            frame,
            detections,
            regions=regions,
            trails=trails if detection.get("show_trails", True) else None,
            show_trails=bool(detection.get("show_trails", True)),
            show_confidence=bool(detection.get("label_confidence", True)),
            show_track_id=bool(detection.get("label_track_id", True)),
        )

    def _evaluate_events(self, result: DetectionResult, annotated) -> list:
        if not result.detections:
            return []
        if result.frame_size[0] and result.frame_size[1]:
            width, height = result.frame_size
        else:
            height, width = annotated.shape[:2]
        try:
            events = self._engine.evaluate(
                result.detections, int(width), int(height),
                time.time(), self._camera_name,
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Event evaluation failed")
            self.error.emit(f"Event evaluation failed: {exc}")
            return []

        if not events:
            return []

        events_settings = self._settings.get("events", {}) or {}
        want_snapshot = bool(events_settings.get("save_snapshots", False))
        for record in events:
            if want_snapshot:
                path = self._snapshot_path(record)
                if save_snapshot(annotated, path):
                    record.snapshot = str(path)
            try:
                record.id = self._event_repo.add(
                    ts=record.ts,
                    event_type=record.event_type,
                    title=record.title,
                    class_name=record.class_name,
                    track_id=record.track_id,
                    confidence=record.confidence,
                    region_name=record.region_name,
                    camera=record.camera,
                    snapshot=record.snapshot,
                    details=record.details,
                )
            except Exception as exc:
                log.warning("Could not store event: %s", exc)
            self.event_created.emit(record)

        self._frames_since_prune += len(events)
        if self._frames_since_prune >= 50:
            self._frames_since_prune = 0
            try:
                keep = int(events_settings.get("max_stored_events", 20000) or 20000)
                self._event_repo.prune(keep)
            except Exception:
                pass
        return events

    def _snapshot_path(self, record) -> Path:
        stamp = datetime.fromtimestamp(record.ts)
        folder = self._snapshot_dir / stamp.strftime("%Y-%m-%d")
        parts = [stamp.strftime("%H%M%S"), record.event_type, safe_name(record.class_name, "object")]
        if record.track_id is not None:
            parts.append(f"id{record.track_id}")
        return folder / ("_".join(parts) + ".jpg")

    def _handle_snapshot(self, annotated) -> None:
        if not self._snapshot_requested:
            return
        self._snapshot_requested = False
        stamp = datetime.now()
        folder = self._snapshot_dir / stamp.strftime("%Y-%m-%d")
        path = folder / f"{stamp.strftime('%H%M%S')}_manual_{safe_name(self._camera_name)}.jpg"
        if save_snapshot(annotated, path):
            self.snapshot_saved.emit(str(path))
        else:
            self.error.emit(f"Could not write the snapshot to {path}")

    def _tick_recording(self, annotated) -> None:
        if self._recording_requested:
            if self._writer is None:
                self._open_writer(annotated)
            if self._writer is not None:
                try:
                    self._writer.write(annotated)
                except Exception as exc:
                    self.error.emit(f"Recording failed: {exc}")
                    self._close_writer()
                    self._recording_requested = False
        elif self._writer is not None:
            self._close_writer()

    def _open_writer(self, annotated) -> None:
        height, width = annotated.shape[:2]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fps = float(self._settings.get("recording", {}).get("fps", 15) or 15)
        codec = str(self._settings.get("recording", {}).get("codec", "mp4v") or "mp4v")
        path = self._recording_dir / f"{safe_name(self._camera_name)}_{stamp}.mp4"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            writer = cv2.VideoWriter(
                str(path), cv2.VideoWriter_fourcc(*codec[:4].ljust(4)), fps, (width, height)
            )
            if not writer.isOpened():
                self.error.emit(
                    f"Could not start recording to {path}. "
                    "The codec may be unavailable in this OpenCV build."
                )
                self._recording_requested = False
                self.recording_state.emit(False, "")
                return
            self._writer = writer
            self._recording_path = path
            self.recording_state.emit(True, str(path))
            log.info("Recording started: %s", path)
        except Exception as exc:
            self.error.emit(f"Could not start recording: {exc}")
            self._recording_requested = False
            self.recording_state.emit(False, "")

    def _close_writer(self) -> None:
        if self._writer is None:
            return
        path = self._recording_path
        try:
            self._writer.release()
        except Exception:
            pass
        self._writer = None
        self._recording_path = None
        self.recording_state.emit(False, str(path) if path else "")
        log.info("Recording stopped: %s", path)

    # -- output ------------------------------------------------------------
    def _publish(self, packet, annotated, result: DetectionResult, trails) -> None:
        try:
            image = to_qimage(annotated)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Frame conversion failed: %s", exc)
            return
        self._output.put(
            ProcessedFrame(
                index=packet.index,
                timestamp=packet.timestamp,
                image=image,
                detections=result.detections,
                stats={"inference_ms": result.inference_ms},
            )
        )

    def _flush_stats(self, force: bool = True) -> None:
        now = time.monotonic()
        if not force and now - self._last_stats_emit < 0.25:
            return
        self._last_stats_emit = now

        fps = 0.0
        if len(self._processed_times) >= 2:
            span = self._processed_times[-1] - self._processed_times[0]
            if span > 0:
                fps = (len(self._processed_times) - 1) / span
        avg_inference = (
            sum(self._inference_times) / len(self._inference_times)
            if self._inference_times else 0.0
        )
        detections = self._last_result.detections
        people = sum(1 for d in detections if d.class_name == "person")
        vehicles = sum(1 for d in detections if is_vehicle(d.class_name))
        session_elapsed = max(1e-6, time.time() - self._session_started_at)
        session_fps = self._session_frames / session_elapsed if self._session_frames else 0.0

        stats = {
            "processed_fps": round(fps, 1),
            "capture_fps": round(self._capture_fps, 1),
            "inference_ms": round(avg_inference, 1),
            "objects": len(detections),
            "people": people,
            "vehicles": vehicles,
            "frames_processed": self._frames_processed,
            "frames_dropped": self._input.dropped,
            "detections_total": self._detections_total,
            "session_frames": self._session_frames,
            "session_detections": self._session_detections,
            "session_fps": round(session_fps, 2),
            "tracked": sum(1 for d in detections if d.track_id is not None),
            "trails": len(self._trails),
            "model_state": self._model_state,
            "model_error": self._model_error,
            "safety_state": self._safety_state,
            # The device actually in use, which may differ from the configured
            # one when CUDA is requested but unavailable.
            "device": self._detector.device if self._detector else "cpu",
            "tracking_mode": self._detector.tracking_mode if self._detector else "off",
            "recording": self._writer is not None,
            "camera": self._camera_name,
        }
        self.stats_ready.emit(stats)
        self.detections_ready.emit(list(detections))
