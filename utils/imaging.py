"""Frame annotation and Qt image conversion.

Annotations are burned into the frame with OpenCV rather than painted by the
widget. That guarantees the boxes always line up pixel-for-pixel with the frame
they were computed from, even when the interface is busy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import cv2
import numpy as np
from PySide6.QtGui import QImage

from config.defaults import class_color

# A region description as consumed by :func:`annotate_frame`:
# (name, [(x, y), ...] in pixels, "#RRGGBB")
RegionOverlay = tuple[str, Sequence[tuple[float, float]], str]


def hex_to_bgr(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    if len(text) != 6:
        return (255, 255, 255)
    return (int(text[4:6], 16), int(text[2:4], 16), int(text[0:2], 16))


def to_qimage(frame_bgr: np.ndarray) -> QImage:
    """Convert an OpenCV BGR frame into a detached QImage."""
    if frame_bgr is None:
        return QImage()
    if frame_bgr.ndim == 2:
        frame_bgr = cv2.cvtColor(frame_bgr, cv2.COLOR_GRAY2BGR)
    elif frame_bgr.shape[2] == 4:
        frame_bgr = cv2.cvtColor(frame_bgr, cv2.COLOR_BGRA2BGR)
    if not frame_bgr.flags["C_CONTIGUOUS"]:
        frame_bgr = np.ascontiguousarray(frame_bgr)
    height, width = frame_bgr.shape[:2]
    image = QImage(
        frame_bgr.data, width, height, 3 * width, QImage.Format.Format_BGR888
    )
    # copy() detaches from the numpy buffer, which is freed as soon as this
    # function returns.
    return image.copy()


def _draw_label(
    canvas: np.ndarray,
    text: str,
    x: int,
    y: int,
    color_bgr: tuple[int, int, int],
    font_scale: float,
    thickness: int,
) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    (text_w, text_h), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    pad = max(3, int(round(4 * font_scale * 2)))
    top = y - text_h - baseline - pad
    if top < 0:
        top = y
        y = y + text_h + baseline + pad
    left = max(0, min(x, canvas.shape[1] - text_w - pad * 2))
    right = min(canvas.shape[1] - 1, left + text_w + pad * 2)
    bottom = min(canvas.shape[0] - 1, top + text_h + baseline + pad)

    cv2.rectangle(canvas, (left, top), (right, bottom), color_bgr, -1)
    # Dark text on a saturated chip reads better than white on mid-tones.
    luminance = 0.114 * color_bgr[0] + 0.587 * color_bgr[1] + 0.299 * color_bgr[2]
    text_color = (18, 22, 28) if luminance > 150 else (255, 255, 255)
    cv2.putText(
        canvas, text, (left + pad, bottom - baseline - pad // 2),
        font, font_scale, text_color, thickness, cv2.LINE_AA,
    )


def annotate_frame(
    frame: np.ndarray,
    detections: Iterable,
    regions: Sequence[RegionOverlay] | None = None,
    trails: dict[int, Sequence[tuple[float, float]]] | None = None,
    show_trails: bool = True,
    show_confidence: bool = True,
    show_track_id: bool = True,
) -> np.ndarray:
    """Return a copy of ``frame`` with regions, trails and detection boxes drawn."""
    if frame is None:
        return frame
    canvas = frame.copy()
    height, width = canvas.shape[:2]
    if height == 0 or width == 0:
        return canvas

    scale = max(1.0, width / 1280.0)
    thickness = max(2, int(round(2 * scale)))
    font_scale = 0.45 * scale
    text_thickness = max(1, int(round(scale)))

    # --- configured regions ------------------------------------------------
    for name, points, color_hex in regions or []:
        if len(points) < 3:
            continue
        pts = np.array([[int(round(px)), int(round(py))] for px, py in points], dtype=np.int32)
        color_bgr = hex_to_bgr(color_hex)
        overlay = canvas.copy()
        cv2.fillPoly(overlay, [pts], color_bgr)
        cv2.addWeighted(overlay, 0.12, canvas, 0.88, 0, canvas)
        cv2.polylines(canvas, [pts], True, color_bgr, thickness, cv2.LINE_AA)
        if name:
            _draw_label(canvas, name, int(pts[0][0]), int(pts[0][1]),
                        color_bgr, font_scale * 0.9, text_thickness)

    # --- tracking trails ---------------------------------------------------
    if show_trails and trails:
        for track_id, points in trails.items():
            if len(points) < 2:
                continue
            pts = np.array([[int(round(px)), int(round(py))] for px, py in points], dtype=np.int32)
            cv2.polylines(canvas, [pts], False, (255, 255, 255), max(1, thickness - 1), cv2.LINE_AA)
            cv2.circle(canvas, tuple(int(v) for v in pts[-1]), thickness + 1, (255, 255, 255), -1, cv2.LINE_AA)

    # --- detections --------------------------------------------------------
    for det in detections:
        color_bgr = hex_to_bgr(class_color(det.class_name))
        x1, y1 = int(round(det.x1)), int(round(det.y1))
        x2, y2 = int(round(det.x2)), int(round(det.y2))
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color_bgr, thickness, cv2.LINE_AA)

        parts = [det.class_name]
        if show_confidence:
            parts.append(f"{det.confidence * 100:.0f}%")
        if show_track_id and det.track_id is not None:
            parts.append(f"#{det.track_id}")
        if det.direction:
            parts.append(det.direction)
        _draw_label(canvas, " ".join(parts), x1, max(y1, 0), color_bgr, font_scale, text_thickness)

    return canvas


def save_snapshot(frame: np.ndarray, path: str | Path, quality: int = 88) -> bool:
    """Write a JPEG evidence frame. Returns ``True`` on success."""
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        return bool(cv2.imwrite(str(target), frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]))
    except Exception:
        return False


def fit_size(width: int, height: int, max_width: int, max_height: int) -> tuple[int, int]:
    """Scale ``width``/``height`` down to fit inside the given box, keeping ratio."""
    if width <= 0 or height <= 0 or max_width <= 0 or max_height <= 0:
        return (max(1, max_width), max(1, max_height))
    ratio = min(max_width / width, max_height / height)
    if ratio >= 1.0:
        return (width, height)
    return (max(1, int(width * ratio)), max(1, int(height * ratio)))
