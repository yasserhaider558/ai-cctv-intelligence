"""Model file resolution and download diagnostics.

Ultralytics downloads pretrained weights on first use. That download is a real
network operation and can fail for reasons the user must be able to act on, so
this module turns it into explicit, human-readable state instead of a stack
trace.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

#: Known-good pretrained checkpoints, newest first. The UI offers these.
SUGGESTED_MODELS: tuple[tuple[str, str], ...] = (
    ("yolov8n.pt", "YOLOv8 Nano - fastest, best for CPU-only machines"),
    ("yolov8s.pt", "YOLOv8 Small - better accuracy, needs more CPU/GPU"),
    ("yolov8m.pt", "YOLOv8 Medium - GPU recommended"),
    ("yolo11n.pt", "YOLO11 Nano - newest generation, similar speed to v8n"),
    ("yolo11s.pt", "YOLO11 Small - GPU recommended"),
)

_DOWNLOAD_HELP = (
    "The model weights could not be found or downloaded.\n\n"
    "Fix it in one of these ways:\n"
    "  1. Check your internet connection and start the camera again - the "
    "weights download automatically on first use.\n"
    "  2. Download the file manually in a browser from\n"
    "     https://github.com/ultralytics/assets/releases\n"
    "     and place it in the 'models' folder of this project, keeping the "
    "file name (for example yolov8n.pt).\n"
    "  3. Point Settings > Detection > Model at a local .pt file you already have.\n\n"
    "No detection is performed until a model is available. The video feed "
    "itself still works."
)


@dataclass
class ModelInfo:
    name: str
    path: Path
    exists: bool
    size_mb: float

    @property
    def status_text(self) -> str:
        if self.exists:
            return f"{self.path.name} ({self.size_mb:.1f} MB)"
        return f"{self.path.name} (not downloaded yet)"


def resolve_model_path(name: str, models_dir: Path) -> Path:
    """Turn a model name into an absolute path inside ``models_dir``."""
    raw = Path(str(name).strip() or "yolov8n.pt")
    if raw.is_absolute():
        return raw
    # A bare file name goes into models/. A relative path with directories is
    # resolved against the project root by the caller; treat it as-is here.
    if raw.parent == Path("."):
        return models_dir / raw.name
    return raw


def describe_model(name: str, models_dir: Path) -> ModelInfo:
    path = resolve_model_path(name, models_dir)
    exists = path.is_file()
    size_mb = (path.stat().st_size / (1024 * 1024)) if exists else 0.0
    return ModelInfo(name=name, path=path, exists=exists, size_mb=size_mb)


def download_help_text() -> str:
    return _DOWNLOAD_HELP


def adopt_stray_weights(name: str, models_dir: Path) -> Path | None:
    """If Ultralytics dropped the weights into the working directory, move them.

    ``YOLO("yolov8n.pt")`` downloads next to the process working directory. We
    prefer everything under ``models/`` so the project stays tidy.
    """
    target = models_dir / Path(name).name
    if target.is_file():
        return target
    stray = Path.cwd() / Path(name).name
    if stray.is_file():
        try:
            models_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(stray), str(target))
            return target
        except OSError:
            return stray
    return None
