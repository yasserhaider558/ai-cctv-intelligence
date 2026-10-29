"""Per-track motion history: trails, direction and speed.

Tracking IDs are temporary, frame-local identifiers. They let the application
follow the *same* object for a few seconds and draw its path; they say nothing
about who the object is.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, Iterable

_DIRECTION_LABELS = ("E", "NE", "N", "NW", "W", "SW", "S", "SE")


def direction_label(dx: float, dy: float, min_distance: float = 6.0) -> str:
    """Map a screen-space displacement to an 8-way compass label.

    Image coordinates grow downwards, so ``dy`` is negated before the angle is
    taken; the result then matches what a viewer sees.
    """
    if math.hypot(dx, dy) < min_distance:
        return ""
    angle = math.degrees(math.atan2(-dy, dx)) % 360.0
    index = int((angle + 22.5) // 45.0) % 8
    return _DIRECTION_LABELS[index]


class TrailStore:
    """Keeps a short positional history for every live tracking ID."""

    def __init__(
        self,
        max_points: int = 32,
        ttl_s: float = 3.0,
        direction_window_s: float = 0.8,
        min_displacement_px: float = 6.0,
    ) -> None:
        self.max_points = max(2, int(max_points))
        self.ttl_s = float(ttl_s)
        self.direction_window_s = float(direction_window_s)
        self.min_displacement_px = float(min_displacement_px)
        self._points: dict[int, Deque[tuple[float, float, float]]] = {}

    def reset(self) -> None:
        self._points.clear()

    def update(self, detections: Iterable, timestamp: float) -> dict[int, list[tuple[float, float]]]:
        """Record positions and annotate detections with direction/speed."""
        seen: set[int] = set()
        for det in detections:
            if det.track_id is None:
                continue
            track_id = int(det.track_id)
            seen.add(track_id)
            cx, cy = det.center
            history = self._points.get(track_id)
            if history is None:
                history = deque(maxlen=self.max_points)
                self._points[track_id] = history
            history.append((float(timestamp), float(cx), float(cy)))
            while history and timestamp - history[0][0] > self.ttl_s:
                history.popleft()

            if len(history) >= 2:
                reference = history[0]
                for point in history:
                    if timestamp - point[0] <= self.direction_window_s:
                        reference = point
                        break
                dx = history[-1][1] - reference[1]
                dy = history[-1][2] - reference[2]
                dt = max(1e-3, history[-1][0] - reference[0])
                det.direction = direction_label(dx, dy, self.min_displacement_px)
                det.speed_px_s = math.hypot(dx, dy) / dt
            else:
                det.direction = ""
                det.speed_px_s = 0.0

        self._prune(timestamp, seen)
        return self.paths()

    def _prune(self, timestamp: float, seen: set[int]) -> None:
        stale = [
            track_id
            for track_id, history in self._points.items()
            if track_id not in seen and (not history or timestamp - history[-1][0] > self.ttl_s)
        ]
        for track_id in stale:
            self._points.pop(track_id, None)

    def paths(self) -> dict[int, list[tuple[float, float]]]:
        return {track_id: [(x, y) for _, x, y in history] for track_id, history in self._points.items()}

    def path_for(self, track_id: int) -> list[tuple[float, float]]:
        history = self._points.get(int(track_id))
        if not history:
            return []
        return [(x, y) for _, x, y in history]

    def __len__(self) -> int:
        return len(self._points)
