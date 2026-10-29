"""Analytics computed from stored events and recorded sessions.

Every number returned here comes from the SQLite database. When there is no data
the service returns zeros and empty lists, and the interface shows an empty
state - it never invents a plausible-looking chart.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

RANGES: dict[str, tuple[str, int | None]] = {
    "24h": ("Last 24 hours", 24 * 3600),
    "7d": ("Last 7 days", 7 * 24 * 3600),
    "30d": ("Last 30 days", 30 * 24 * 3600),
    "all": ("All time", None),
}


def range_start(key: str, now: float | None = None) -> float | None:
    """Epoch start for a range key, or ``None`` for all time."""
    now = time.time() if now is None else now
    span = RANGES.get(key, RANGES["24h"])[1]
    return None if span is None else now - span


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours:02d}h"


@dataclass
class Summary:
    total_events: int = 0
    events_in_range: int = 0
    distinct_classes: int = 0
    region_events: int = 0
    sessions: int = 0
    total_uptime_s: float = 0.0
    average_fps: float = 0.0
    frames_processed: int = 0
    detections_total: int = 0

    @property
    def uptime_text(self) -> str:
        return format_duration(self.total_uptime_s)


class AnalyticsService:
    def __init__(self, event_repo, session_repo) -> None:
        self._events = event_repo
        self._sessions = session_repo

    def summary(self, since: float | None = None) -> Summary:
        summary = Summary()
        try:
            summary.total_events = self._events.count()
            summary.events_in_range = self._events.count(since=since)
            summary.distinct_classes = len(self._events.class_distribution(since))
            types = dict(self._events.type_distribution(since))
            summary.region_events = int(types.get("intrusion", 0)) + int(types.get("loitering", 0))
            frames, detections, sessions = self._sessions.totals(since)
            summary.frames_processed = frames
            summary.detections_total = detections
            summary.sessions = sessions
            summary.average_fps = self._sessions.average_fps(since)
            uptime_rows = self._sessions.uptime_by_camera(since)
            summary.total_uptime_s = sum(row[1] for row in uptime_rows)
        except Exception:
            return Summary()
        return summary

    def class_distribution(self, since: float | None = None) -> list[tuple[str, int]]:
        try:
            return self._events.class_distribution(since)
        except Exception:
            return []

    def type_distribution(self, since: float | None = None) -> list[tuple[str, int]]:
        try:
            return self._events.type_distribution(since)
        except Exception:
            return []

    def event_series(
        self, since: float | None, bucket_seconds: int = 3600
    ) -> list[tuple[int, int]]:
        if since is None:
            since = time.time() - 24 * 3600
        try:
            return self._events.bucket_counts(since, bucket_seconds)
        except Exception:
            return []

    def uptime(self, since: float | None = None) -> list[tuple[str, float, int]]:
        try:
            return self._sessions.uptime_by_camera(since)
        except Exception:
            return []

    def recent(self, limit: int = 10):
        try:
            return self._events.recent(limit)
        except Exception:
            return []
