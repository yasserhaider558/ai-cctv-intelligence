"""Default configuration values and static catalogues.

This module is deliberately free of Qt, numpy and OpenCV imports so that it can
be used from unit tests, from the database layer, and from worker threads.
"""

from __future__ import annotations

APP_NAME = "AI CCTV Intelligence"
APP_ORGANISATION = "AI CCTV"
APP_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# COCO class catalogue (the order matches every Ultralytics YOLO COCO model)
# ---------------------------------------------------------------------------

COCO_CLASSES: tuple[str, ...] = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
)

VEHICLE_CLASSES: frozenset[str] = frozenset(
    {"bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat"}
)

ANIMAL_CLASSES: frozenset[str] = frozenset(
    {"bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"}
)

#: COCO classes that can be used as a weapon. Note what is missing: COCO has no
#: "gun", "rifle" or "fight" class, so firearms are only detectable with a custom
#: checkpoint whose classes you then add to the hazard list in Settings.
HAZARD_CLASSES: tuple[str, ...] = ("knife", "baseball bat", "scissors")

#: Classes enabled out of the box. Chosen to match the brief (people, vehicles,
#: common domestic animals) without flooding the view with cutlery and chairs.
DEFAULT_ENABLED_CLASSES: tuple[str, ...] = (
    "person", "bicycle", "car", "motorcycle", "bus", "truck", "dog", "cat",
)

#: Explicit colours for the classes people look at most. Everything else falls
#: back to the generated palette below.
_CLASS_COLORS: dict[str, str] = {
    "person": "#FF4D5E",
    "bicycle": "#FF9F45",
    "car": "#4DA3FF",
    "motorcycle": "#FFC145",
    "bus": "#B388FF",
    "train": "#7C8CFF",
    "truck": "#2ED3A0",
    "boat": "#35C4E8",
    "dog": "#FFD166",
    "cat": "#FF7BD5",
}

#: Deterministic fallback palette (colour-blind friendly-ish, high contrast on
#: dark video).
_PALETTE: tuple[str, ...] = (
    "#4DA3FF", "#FF4D5E", "#2ED3A0", "#FFC145", "#B388FF", "#35C4E8",
    "#FF9F45", "#FF7BD5", "#9BE564", "#FFE066", "#7C8CFF", "#5EEAD4",
)


def class_color(class_name: str) -> str:
    """Return a stable hex colour for a class name."""
    explicit = _CLASS_COLORS.get(class_name)
    if explicit:
        return explicit
    if class_name in COCO_CLASSES:
        return _PALETTE[COCO_CLASSES.index(class_name) % len(_PALETTE)]
    # Stable hash for custom models with unknown class names.
    total = sum(ord(ch) for ch in class_name)
    return _PALETTE[total % len(_PALETTE)]


def is_vehicle(class_name: str) -> bool:
    return class_name in VEHICLE_CLASSES


def resolve_enabled_classes(detection: dict | None, events: dict | None) -> list[str]:
    """Detection classes plus the hazard classes.

    Hazard rules are pointless if the detector never looks for a knife, so the
    hazard list is unioned into the class filter. Everything found is still shown
    in the detection panel, because it really was detected.
    """
    enabled = {str(name) for name in ((detection or {}).get("enabled_classes") or [])}
    hazards = (events or {}).get("hazards") or {}
    if hazards.get("enabled", True):
        for name in hazards.get("classes") or []:
            text = str(name).strip()
            if text:
                enabled.add(text)
    return sorted(enabled)


# ---------------------------------------------------------------------------
# Default configuration tree
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict = {
    "app": {
        "theme": "dark",
        "log_level": "INFO",
        "first_run": True,
    },
    "detection": {
        "model": "yolov8n.pt",
        "device": "cpu",
        "confidence": 0.35,
        "iou": 0.45,
        "imgsz": 640,
        "max_detections": 100,
        "enabled": True,
        "tracking_enabled": True,
        "enabled_classes": list(DEFAULT_ENABLED_CLASSES),
        "show_trails": True,
        "trail_length": 32,
        "label_confidence": True,
        "label_track_id": True,
        "torch_threads": 0,
    },
    "video": {
        "max_display_fps": 30,
        "reconnect_attempts": 3,
        "reconnect_delay_s": 3.0,
        "webcam_width": 1280,
        "webcam_height": 720,
    },
    "safety_model": {
        "enabled": True,
        "model": "yolo_small_weights.pt",
        "classes": ["violence"],
        "confidence": 0.45,
        "iou": 0.45,
        "imgsz": 640,
        "run_every_n_frames": 2,
        "cooldown_s": 20.0,
    },
    "events": {
        "person_detected": True,
        "vehicle_detected": True,
        "cooldown_s": 15.0,
        "save_snapshots": False,
        "region_intrusion": False,
        "region_loitering": False,
        "loiter_seconds": 8.0,
        "regions": [],
        "max_stored_events": 20000,
        "hazards": {
            "enabled": True,
            "classes": list(HAZARD_CLASSES),
            "require_person_proximity": True,
            "proximity_factor": 0.75,
            "altercation_enabled": True,
            "altercation_overlap": 0.22,
            "altercation_min_seconds": 1.2,
            "cooldown_s": 30.0,
        },
    },
    "recording": {
        "fps": 15,
        "codec": "mp4v",
    },
    "storage": {
        "snapshot_dir": "data/snapshots",
        "recording_dir": "data/recordings",
    },
    "camera": {
        "last_source": {
            "kind": "file",
            "identifier": "",
            "name": "",
        },
    },
    "privacy": {
        "local_processing_only": True,
        "acknowledged": False,
    },
}
