"""Typed query helpers for events and camera sessions.

Nothing here knows about Qt or about the event rules; repositories take plain
values and return dataclasses, which keeps them straightforward to unit test.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable, Sequence

from database.db import Database


@dataclass
class EventRow:
    id: int
    ts: float
    event_type: str
    title: str
    class_name: str = ""
    track_id: int | None = None
    confidence: float | None = None
    region_name: str = ""
    camera: str = ""
    snapshot: str = ""
    details: str = ""

    @staticmethod
    def from_row(row: sqlite3.Row) -> "EventRow":
        return EventRow(
            id=row["id"],
            ts=row["ts"],
            event_type=row["event_type"],
            title=row["title"],
            class_name=row["class_name"] or "",
            track_id=row["track_id"],
            confidence=row["confidence"],
            region_name=row["region_name"] or "",
            camera=row["camera"] or "",
            snapshot=row["snapshot"] or "",
            details=row["details"] or "",
        )


@dataclass
class SessionRow:
    id: int
    camera: str
    source_type: str
    started: float
    ended: float | None
    frames_processed: int
    frames_dropped: int
    detections: int
    avg_fps: float

    @property
    def duration_s(self) -> float:
        if self.ended is None:
            return 0.0
        return max(0.0, self.ended - self.started)


class EventRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- writes ------------------------------------------------------------
    def add(
        self,
        ts: float,
        event_type: str,
        title: str,
        class_name: str = "",
        track_id: int | None = None,
        confidence: float | None = None,
        region_name: str = "",
        camera: str = "",
        snapshot: str = "",
        details: str = "",
    ) -> int:
        conn = self._db.connection()
        cursor = conn.execute(
            "INSERT INTO events (ts, event_type, title, class_name, track_id, confidence,"
            " region_name, camera, snapshot, details) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ts, event_type, title, class_name, track_id, confidence,
             region_name, camera, snapshot, details),
        )
        conn.commit()
        return int(cursor.lastrowid or 0)

    def delete(self, event_ids: Sequence[int]) -> int:
        if not event_ids:
            return 0
        placeholders = ",".join("?" for _ in event_ids)
        conn = self._db.connection()
        cursor = conn.execute(f"DELETE FROM events WHERE id IN ({placeholders})",
                              tuple(int(i) for i in event_ids))
        conn.commit()
        return int(cursor.rowcount or 0)

    def clear(self) -> int:
        conn = self._db.connection()
        cursor = conn.execute("DELETE FROM events")
        conn.commit()
        return int(cursor.rowcount or 0)

    def prune(self, keep: int) -> int:
        """Keep only the newest ``keep`` events."""
        if keep <= 0:
            return 0
        conn = self._db.connection()
        cursor = conn.execute(
            "DELETE FROM events WHERE id NOT IN "
            "(SELECT id FROM events ORDER BY ts DESC, id DESC LIMIT ?)",
            (int(keep),),
        )
        conn.commit()
        return int(cursor.rowcount or 0)

    # -- reads -------------------------------------------------------------
    @staticmethod
    def _where(
        search: str,
        event_type: str,
        since: float | None,
        until: float | None,
        event_types: Sequence[str] | None = None,
    ):
        clauses: list[str] = []
        params: list = []
        if since is not None:
            clauses.append("ts >= ?")
            params.append(float(since))
        if until is not None:
            clauses.append("ts <= ?")
            params.append(float(until))
        if event_types:
            placeholders = ",".join("?" for _ in event_types)
            clauses.append(f"event_type IN ({placeholders})")
            params.extend(str(item) for item in event_types)
        elif event_type and event_type != "all":
            clauses.append("event_type = ?")
            params.append(event_type)
        if search:
            like = f"%{search.strip()}%"
            clauses.append(
                "(title LIKE ? OR class_name LIKE ? OR region_name LIKE ? OR camera LIKE ?"
                " OR CAST(track_id AS TEXT) LIKE ?)"
            )
            params.extend([like, like, like, like, like])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def list(
        self,
        search: str = "",
        event_type: str = "all",
        since: float | None = None,
        until: float | None = None,
        limit: int = 500,
        offset: int = 0,
        event_types: Sequence[str] | None = None,
    ) -> list[EventRow]:
        where, params = self._where(search, event_type, since, until, event_types)
        sql = f"SELECT * FROM events{where} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])
        rows = self._db.connection().execute(sql, params).fetchall()
        return [EventRow.from_row(r) for r in rows]

    def get(self, event_id: int) -> EventRow | None:
        row = self._db.connection().execute(
            "SELECT * FROM events WHERE id = ?", (int(event_id),)
        ).fetchone()
        return EventRow.from_row(row) if row else None

    def count(
        self,
        search: str = "",
        event_type: str = "all",
        since: float | None = None,
        until: float | None = None,
        event_types: Sequence[str] | None = None,
    ) -> int:
        where, params = self._where(search, event_type, since, until, event_types)
        row = self._db.connection().execute(
            f"SELECT COUNT(*) AS n FROM events{where}", params
        ).fetchone()
        return int(row["n"]) if row else 0

    def class_distribution(self, since: float | None = None) -> list[tuple[str, int]]:
        sql = ("SELECT class_name, COUNT(*) AS n FROM events "
               "WHERE class_name != ''")
        params: list = []
        if since is not None:
            sql += " AND ts >= ?"
            params.append(float(since))
        sql += " GROUP BY class_name ORDER BY n DESC"
        rows = self._db.connection().execute(sql, params).fetchall()
        return [(r["class_name"], int(r["n"])) for r in rows]

    def type_distribution(self, since: float | None = None) -> list[tuple[str, int]]:
        sql = "SELECT event_type, COUNT(*) AS n FROM events"
        params: list = []
        if since is not None:
            sql += " WHERE ts >= ?"
            params.append(float(since))
        sql += " GROUP BY event_type ORDER BY n DESC"
        rows = self._db.connection().execute(sql, params).fetchall()
        return [(r["event_type"], int(r["n"])) for r in rows]

    def bucket_counts(self, since: float, bucket_seconds: int) -> list[tuple[int, int]]:
        """Event counts per fixed time bucket, as ``(bucket_start, count)``."""
        bucket = max(60, int(bucket_seconds))
        sql = (
            "SELECT CAST(ts / ? AS INTEGER) * ? AS bucket, COUNT(*) AS n "
            "FROM events WHERE ts >= ? GROUP BY bucket ORDER BY bucket"
        )
        rows = self._db.connection().execute(sql, (bucket, bucket, float(since))).fetchall()
        return [(int(r["bucket"]), int(r["n"])) for r in rows]

    def recent(self, limit: int = 10) -> list[EventRow]:
        rows = self._db.connection().execute(
            "SELECT * FROM events ORDER BY ts DESC, id DESC LIMIT ?", (int(limit),)
        ).fetchall()
        return [EventRow.from_row(r) for r in rows]

    def event_types(self) -> list[str]:
        rows = self._db.connection().execute(
            "SELECT DISTINCT event_type FROM events ORDER BY event_type"
        ).fetchall()
        return [r["event_type"] for r in rows]

    def all_snapshot_paths(self) -> Iterable[str]:
        rows = self._db.connection().execute(
            "SELECT snapshot FROM events WHERE snapshot != ''"
        ).fetchall()
        return [r["snapshot"] for r in rows]


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def start(self, camera: str, source_type: str, started: float) -> int:
        conn = self._db.connection()
        cursor = conn.execute(
            "INSERT INTO sessions (camera, source_type, started) VALUES (?,?,?)",
            (camera, source_type, float(started)),
        )
        conn.commit()
        return int(cursor.lastrowid or 0)

    def finish(
        self,
        session_id: int,
        ended: float,
        frames_processed: int = 0,
        frames_dropped: int = 0,
        detections: int = 0,
        avg_fps: float = 0.0,
    ) -> None:
        conn = self._db.connection()
        conn.execute(
            "UPDATE sessions SET ended = ?, frames_processed = ?, frames_dropped = ?,"
            " detections = ?, avg_fps = ? WHERE id = ?",
            (float(ended), int(frames_processed), int(frames_dropped),
             int(detections), float(avg_fps), int(session_id)),
        )
        conn.commit()

    def close_orphans(self, ended: float) -> None:
        """Sessions left open by a crash would inflate uptime; close them."""
        conn = self._db.connection()
        conn.execute("UPDATE sessions SET ended = ? WHERE ended IS NULL", (float(ended),))
        conn.commit()

    def list(self, limit: int = 100) -> list[SessionRow]:
        rows = self._db.connection().execute(
            "SELECT * FROM sessions ORDER BY started DESC LIMIT ?", (int(limit),)
        ).fetchall()
        return [
            SessionRow(
                id=r["id"], camera=r["camera"], source_type=r["source_type"] or "",
                started=r["started"], ended=r["ended"],
                frames_processed=int(r["frames_processed"] or 0),
                frames_dropped=int(r["frames_dropped"] or 0),
                detections=int(r["detections"] or 0),
                avg_fps=float(r["avg_fps"] or 0.0),
            )
            for r in rows
        ]

    def uptime_by_camera(self, since: float | None = None) -> list[tuple[str, float, int]]:
        sql = ("SELECT camera, SUM(COALESCE(ended, started) - started) AS secs, COUNT(*) AS n "
               "FROM sessions")
        params: list = []
        if since is not None:
            sql += " WHERE started >= ?"
            params.append(float(since))
        sql += " GROUP BY camera ORDER BY secs DESC"
        rows = self._db.connection().execute(sql, params).fetchall()
        return [(r["camera"], float(r["secs"] or 0.0), int(r["n"])) for r in rows]

    def average_fps(self, since: float | None = None) -> float:
        sql = "SELECT AVG(avg_fps) AS fps FROM sessions WHERE avg_fps > 0"
        params: list = []
        if since is not None:
            sql += " AND started >= ?"
            params.append(float(since))
        row = self._db.connection().execute(sql, params).fetchone()
        return float(row["fps"]) if row and row["fps"] is not None else 0.0

    def totals(self, since: float | None = None) -> tuple[int, int, int]:
        """(frames_processed, detections, session_count)"""
        sql = "SELECT SUM(frames_processed) AS f, SUM(detections) AS d, COUNT(*) AS n FROM sessions"
        params: list = []
        if since is not None:
            sql += " WHERE started >= ?"
            params.append(float(since))
        row = self._db.connection().execute(sql, params).fetchone()
        if not row:
            return (0, 0, 0)
        return (int(row["f"] or 0), int(row["d"] or 0), int(row["n"] or 0))
