"""A small IoU tracker used when Ultralytics' ByteTrack is unavailable.

This is *not* ByteTrack. It is a deliberately simple greedy IoU associator that
keeps IDs stable across consecutive frames, which is what the interface needs in
order to keep showing ``#12`` for the same car. When it is active the detector
reports ``tracking_mode == "fallback-iou"`` and the interface says so, so nobody
mistakes it for the real thing.

All functions are pure Python so they can be unit tested without torch, OpenCV
or Qt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    """Intersection over union for two ``(x1, y1, x2, y2)`` boxes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    intersection = inter_w * inter_h
    if intersection <= 0.0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection
    return intersection / union if union > 0.0 else 0.0


@dataclass
class _Track:
    track_id: int
    box: tuple[float, float, float, float]
    class_name: str
    last_frame: int
    hits: int = 1
    history: list[tuple[float, float]] = field(default_factory=list)


class SimpleTracker:
    """Greedy IoU association with age-based eviction."""

    def __init__(self, iou_threshold: float = 0.3, max_age: int = 20) -> None:
        self.iou_threshold = float(iou_threshold)
        self.max_age = int(max_age)
        self._tracks: dict[int, _Track] = {}
        self._next_id = 1
        self._frame = 0

    @property
    def active_ids(self) -> list[int]:
        return sorted(self._tracks)

    def reset(self) -> None:
        self._tracks.clear()
        self._next_id = 1
        self._frame = 0

    def update(self, detections: Iterable) -> None:
        """Assign ``track_id`` on each detection in place."""
        detections = list(detections)
        self._frame += 1

        candidates: list[tuple[float, int, int]] = []
        for det_index, det in enumerate(detections):
            box = (det.x1, det.y1, det.x2, det.y2)
            for track in self._tracks.values():
                if track.class_name != det.class_name:
                    continue
                score = iou(box, track.box)
                if score >= self.iou_threshold:
                    candidates.append((score, track.track_id, det_index))

        candidates.sort(reverse=True)
        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()
        for score, track_id, det_index in candidates:
            if track_id in matched_tracks or det_index in matched_dets:
                continue
            det = detections[det_index]
            track = self._tracks[track_id]
            track.box = (det.x1, det.y1, det.x2, det.y2)
            track.last_frame = self._frame
            track.hits += 1
            det.track_id = track_id
            matched_tracks.add(track_id)
            matched_dets.add(det_index)

        for det_index, det in enumerate(detections):
            if det_index in matched_dets:
                continue
            track_id = self._next_id
            self._next_id += 1
            det.track_id = track_id
            self._tracks[track_id] = _Track(
                track_id=track_id,
                box=(det.x1, det.y1, det.x2, det.y2),
                class_name=det.class_name,
                last_frame=self._frame,
            )
            matched_tracks.add(track_id)

        expired = [
            track_id
            for track_id, track in self._tracks.items()
            if self._frame - track.last_frame > self.max_age
        ]
        for track_id in expired:
            self._tracks.pop(track_id, None)
