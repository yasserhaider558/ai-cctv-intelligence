"""YOLO inference wrapper.

Design notes
------------
* The Ultralytics import happens inside :meth:`Detector.load` because importing
  torch costs several seconds. The interface is already on screen by then.
* Tracking uses Ultralytics' bundled ``bytetrack.yaml``. If that path fails on a
  given install we degrade to plain inference plus a small IoU tracker, and say
  so in the log rather than pretending IDs are still coming from ByteTrack.
* Nothing here fabricates detections. An empty result is a real empty result.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from detection.model_manager import download_help_text, resolve_model_path
from detection.types import Detection, DetectionResult
from tracking.fallback_tracker import SimpleTracker

log = logging.getLogger(__name__)


class DetectorError(RuntimeError):
    """Raised when the model cannot be loaded. Message is user-facing."""


def _to_numpy(value) -> np.ndarray | None:
    if value is None:
        return None
    if hasattr(value, "cpu"):
        try:
            value = value.cpu()
        except Exception:
            pass
    if hasattr(value, "numpy"):
        try:
            value = value.numpy()
        except Exception:
            pass
    return np.asarray(value)


class Detector:
    """Loads one YOLO checkpoint and runs inference on single frames."""

    def __init__(
        self,
        model_name: str = "yolov8n.pt",
        models_dir: str | Path = "models",
        device: str = "cpu",
        imgsz: int = 640,
        conf: float = 0.35,
        iou: float = 0.45,
        max_det: int = 100,
        enabled_classes: Sequence[str] | None = None,
        tracking: bool = True,
        torch_threads: int = 0,
    ) -> None:
        self._model_name = model_name
        self._models_dir = Path(models_dir)
        self._device = device or "cpu"
        self._imgsz = int(imgsz)
        self._conf = float(conf)
        self._iou = float(iou)
        self._max_det = int(max_det)
        self._enabled_classes = list(enabled_classes) if enabled_classes is not None else None
        self._tracking = bool(tracking)
        self._torch_threads = int(torch_threads or 0)

        self._model = None
        self._names: dict[int, str] = {}
        self._class_ids: list[int] | None = None
        self._fallback_active = False
        self._fallback: SimpleTracker | None = None
        self._device_note = ""
        self._loaded = False
        self._inference_count = 0

    # -- properties --------------------------------------------------------
    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def device(self) -> str:
        return self._device

    @property
    def device_note(self) -> str:
        """Explains an automatic device fallback, if one happened."""
        return self._device_note

    @property
    def tracking_mode(self) -> str:
        if not self._tracking:
            return "off"
        return "fallback-iou" if self._fallback_active else "bytetrack"

    @property
    def inference_count(self) -> int:
        return self._inference_count

    def available_classes(self) -> list[str]:
        if not self._names:
            return []
        return [self._names[i] for i in sorted(self._names)]

    # -- lifecycle ---------------------------------------------------------
    def load(self) -> None:
        """Import torch/Ultralytics and load the checkpoint. Raises DetectorError."""
        self._import_torch()

        try:
            from ultralytics import YOLO
        except Exception as exc:
            raise DetectorError(
                "The 'ultralytics' package is not available.\n\n"
                "Run setup.bat again, or install it manually:\n"
                "    .venv\\Scripts\\python.exe -m pip install ultralytics\n\n"
                f"Original error: {exc}"
            ) from exc

        self._configure_torch_threads()

        model_path = resolve_model_path(self._model_name, self._models_dir)
        self._models_dir.mkdir(parents=True, exist_ok=True)

        log.info("Loading YOLO model from %s", model_path)
        try:
            self._model = YOLO(str(model_path))
        except Exception as first_error:
            # Ultralytics may refuse an absolute path that does not exist yet.
            # Retrying with the bare name lets its downloader place the file.
            try:
                self._model = YOLO(Path(self._model_name).name)
            except Exception as exc:
                raise DetectorError(
                    f"Could not load the detection model '{self._model_name}'.\n\n"
                    f"{download_help_text()}\n\n"
                    f"Technical detail: {exc or first_error}"
                ) from exc

        names = getattr(self._model, "names", None) or {}
        if isinstance(names, dict):
            self._names = {int(k): str(v) for k, v in names.items()}
        elif isinstance(names, (list, tuple)):
            self._names = {i: str(v) for i, v in enumerate(names)}
        else:  # pragma: no cover - defensive
            self._names = {}

        self._resolve_device()
        self._rebuild_class_filter()
        self._warm_up()
        self._loaded = True
        log.info(
            "Model ready: %s on %s (%d classes, tracking=%s)",
            self._model_name, self._device, len(self._names), self.tracking_mode,
        )

    def _import_torch(self):
        """Import PyTorch, healing a partially initialised extension.

        On Windows a security scanner can read the freshly written DLLs while the
        process is loading them, which leaves ``torch._C`` incomplete. The
        symptom is an ``AttributeError`` such as "module 'torch._C' has no
        attribute '_has_gds'". Python caches that broken module, so a plain retry
        would hand back the same object - the entries have to be evicted first.
        """
        first_error: Exception | None = None
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                import torch

                # Importing the package is not proof that the C extension works:
                # a half-loaded _C imports fine and fails later. Touch it.
                torch.zeros(1).sum().item()
                if attempt > 1:
                    log.info("PyTorch imported successfully on attempt %d", attempt)
                return torch
            except Exception as exc:
                last_error = exc
                if first_error is None:
                    first_error = exc
                log.warning("PyTorch import attempt %d failed: %s", attempt, exc)
                for name in [
                    module_name
                    for module_name in list(sys.modules)
                    if module_name == "torch" or module_name.startswith("torch.")
                ]:
                    sys.modules.pop(name, None)
                if attempt < 3:
                    time.sleep(0.5 * attempt)

        detail = f"Original error: {first_error}"
        if last_error is not None and str(last_error) != str(first_error):
            detail += f"\nError after retrying: {last_error}"

        raise DetectorError(
            "PyTorch could not be imported, so object detection is unavailable.\n\n"
            f"Interpreter in use:\n    {sys.executable}\n\n"
            "This project must run inside its own environment:\n"
            "    .venv\\Scripts\\python.exe main.py\n"
            "or just start it with run.bat.\n\n"
            "If you are already using the project environment, the PyTorch "
            "installation is damaged. Reinstall it:\n"
            "    .venv\\Scripts\\python.exe -m pip install --force-reinstall torch torchvision\n\n"
            "A one-off failure during the first launch can also come from a security "
            "scanner reading the DLLs; press Retry before reinstalling.\n\n"
            f"{detail}"
        ) from last_error

    def _configure_torch_threads(self) -> None:
        try:
            import torch

            if self._torch_threads > 0:
                threads = self._torch_threads
            else:
                # Leave one core for the interface thread; a fully saturated CPU
                # makes the dashboard stutter even though inference is "fine".
                threads = max(1, (os.cpu_count() or 4) - 1)
            torch.set_num_threads(int(threads))
            log.debug("torch.set_num_threads(%d)", threads)
        except Exception:
            pass

    def _resolve_device(self) -> None:
        requested = (self._device or "cpu").strip().lower()
        if requested.startswith("cuda"):
            try:
                import torch

                if not torch.cuda.is_available():
                    self._device = "cpu"
                    self._device_note = (
                        "CUDA was requested but is not available in this PyTorch build. "
                        "Falling back to CPU inference."
                    )
                    log.warning(self._device_note)
            except Exception:
                self._device = "cpu"
        elif requested in ("", "auto"):
            self._device = "cpu"

    def _warm_up(self) -> None:
        """One dummy pass so the first real frame is not penalised."""
        try:
            blank = np.zeros((self._imgsz, self._imgsz, 3), dtype=np.uint8)
            self._model.predict(
                blank, imgsz=self._imgsz, device=self._device, verbose=False
            )
        except Exception as exc:
            if self._device != "cpu":
                log.warning("Warm-up failed on %s (%s); retrying on CPU", self._device, exc)
                self._device = "cpu"
                self._device_note = (
                    "GPU warm-up failed, so the detector switched to CPU. "
                    "Check your CUDA installation for GPU acceleration."
                )
                try:
                    blank = np.zeros((self._imgsz, self._imgsz, 3), dtype=np.uint8)
                    self._model.predict(
                        blank, imgsz=self._imgsz, device="cpu", verbose=False
                    )
                except Exception as exc2:
                    raise DetectorError(
                        "The model loaded but could not run inference.\n\n"
                        f"Technical detail: {exc2}"
                    ) from exc2
            else:
                raise DetectorError(
                    "The model loaded but could not run inference on the CPU.\n\n"
                    f"Technical detail: {exc}"
                ) from exc

    # -- runtime options ---------------------------------------------------
    def _rebuild_class_filter(self) -> None:
        if self._enabled_classes is None:
            self._class_ids = None
            return
        wanted = {name for name in self._enabled_classes}
        if not self._names:
            self._class_ids = None
            return
        ids = [i for i, name in self._names.items() if name in wanted]
        # An empty filter means "the user disabled every class". We keep an
        # empty list (not None) so inference is skipped entirely.
        self._class_ids = ids

    def set_runtime_options(
        self,
        conf: float | None = None,
        iou: float | None = None,
        imgsz: int | None = None,
        max_det: int | None = None,
        enabled_classes: Iterable[str] | None = None,
        tracking: bool | None = None,
        device: str | None = None,
    ) -> None:
        if conf is not None:
            self._conf = float(conf)
        if iou is not None:
            self._iou = float(iou)
        if imgsz is not None:
            self._imgsz = int(imgsz)
        if max_det is not None:
            self._max_det = int(max_det)
        if enabled_classes is not None:
            self._enabled_classes = list(enabled_classes)
            self._rebuild_class_filter()
        if device is not None and device != self._device:
            self._device = device
            self._device_note = ""
            self._resolve_device()
        if tracking is not None and bool(tracking) != self._tracking:
            self._tracking = bool(tracking)
            self._fallback_active = False
            self.reset_tracking()

    def reset_tracking(self) -> None:
        """Clear tracker state. Call this whenever the video source changes."""
        if self._fallback is not None:
            self._fallback.reset()
        try:
            if self._model is not None and getattr(self._model, "predictor", None) is not None:
                # Dropping the predictor is the only fully reliable reset across
                # Ultralytics versions: trackers are rebuilt on the next call.
                self._model.predictor = None
        except Exception:
            pass

    def close(self) -> None:
        self._model = None
        self._loaded = False
        self._fallback = None
        self._names = {}
        # Release the CUDA allocations too. Without this, reloading a model (or
        # opening a second window) can exhaust the 2 GB of a small GPU and the
        # next context initialisation blocks with no error message.
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    # -- inference ---------------------------------------------------------
    def infer(self, frame: np.ndarray) -> DetectionResult:
        if self._model is None:
            raise DetectorError("The detection model is not loaded.")
        if frame is None or frame.size == 0:
            return DetectionResult(error="Empty frame")
        if not frame.flags["C_CONTIGUOUS"]:
            frame = np.ascontiguousarray(frame)

        height, width = frame.shape[:2]
        if self._class_ids is not None and not self._class_ids:
            # Every class is disabled: no inference, no detections, no cost.
            return DetectionResult(
                detections=[], inference_ms=0.0, frame_size=(width, height),
                tracking_active=False,
            )

        kwargs = {
            "conf": self._conf,
            "iou": self._iou,
            "imgsz": self._imgsz,
            "max_det": self._max_det,
            "device": self._device,
            "verbose": False,
        }
        if self._class_ids is not None:
            kwargs["classes"] = self._class_ids

        started = time.perf_counter()
        tracking_active = False
        results = None

        if self._tracking and not self._fallback_active:
            try:
                results = self._model.track(
                    frame, persist=True, tracker="bytetrack.yaml", **kwargs
                )
                tracking_active = True
            except Exception as exc:
                log.warning(
                    "ByteTrack unavailable (%s). Switching to the built-in IoU tracker.", exc
                )
                self._fallback_active = True
                self._fallback = SimpleTracker()
                self.reset_tracking()

        if results is None:
            try:
                results = self._model.predict(frame, **kwargs)
            except Exception as exc:
                raise DetectorError(
                    "Inference failed. The camera feed is still running.\n\n"
                    f"Technical detail: {exc}"
                ) from exc
            if self._tracking and self._fallback is not None:
                tracking_active = True

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._inference_count += 1

        detections = self._parse(results, width, height)

        # ByteTrack assigns IDs itself. Only the degraded path needs our own
        # IoU association pass.
        if self._tracking and self._fallback_active and self._fallback is not None:
            self._fallback.update(detections)

        return DetectionResult(
            detections=detections,
            inference_ms=elapsed_ms,
            frame_size=(width, height),
            tracking_active=tracking_active and self._tracking,
        )

    def _parse(self, results, width: int, height: int) -> list[Detection]:
        if not results:
            return []
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return []
        try:
            count = len(boxes)
        except TypeError:  # pragma: no cover - defensive
            return []
        if count == 0:
            return []

        xyxy = _to_numpy(boxes.xyxy)
        confs = _to_numpy(boxes.conf)
        classes = _to_numpy(boxes.cls)
        if xyxy is None or confs is None or classes is None:
            return []

        ids_tensor = getattr(boxes, "id", None)
        ids = _to_numpy(ids_tensor) if ids_tensor is not None else None

        raw_names = getattr(result, "names", None) or self._names
        if isinstance(raw_names, dict):
            names = {int(k): str(v) for k, v in raw_names.items()}
        elif isinstance(raw_names, (list, tuple)):
            names = {i: str(v) for i, v in enumerate(raw_names)}
        else:  # pragma: no cover - defensive
            names = dict(self._names)
        enabled = set(self._enabled_classes) if self._enabled_classes is not None else None

        detections: list[Detection] = []
        for i in range(count):
            class_id = int(classes[i])
            name = names.get(class_id, f"class {class_id}")
            if enabled is not None and name not in enabled:
                continue
            x1, y1, x2, y2 = (float(v) for v in xyxy[i][:4])
            x1 = max(0.0, min(x1, width - 1.0))
            y1 = max(0.0, min(y1, height - 1.0))
            x2 = max(0.0, min(x2, width - 1.0))
            y2 = max(0.0, min(y2, height - 1.0))
            if x2 - x1 < 2 or y2 - y1 < 2:
                continue
            track_id = None
            if ids is not None and i < len(ids):
                value = float(ids[i])
                if value >= 0:
                    track_id = int(value)
            detections.append(
                Detection(
                    class_id=class_id,
                    class_name=name,
                    confidence=float(confs[i]),
                    x1=x1, y1=y1, x2=x2, y2=y2,
                    track_id=track_id,
                )
            )
        return detections
