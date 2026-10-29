"""SQLite persistence.

Connections are thread-local: the inference thread writes events while the
interface thread reads them, and SQLite objects must not be shared across
threads. WAL journaling keeps those concurrent readers from blocking the writer.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    event_type  TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    class_name  TEXT    DEFAULT '',
    track_id    INTEGER,
    confidence  REAL,
    region_name TEXT    DEFAULT '',
    camera      TEXT    DEFAULT '',
    snapshot    TEXT    DEFAULT '',
    details     TEXT    DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON events (event_type);
CREATE INDEX IF NOT EXISTS idx_events_class ON events (class_name);

CREATE TABLE IF NOT EXISTS sessions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    camera           TEXT    NOT NULL,
    source_type      TEXT    DEFAULT '',
    started          REAL    NOT NULL,
    ended            REAL,
    frames_processed INTEGER DEFAULT 0,
    frames_dropped   INTEGER DEFAULT 0,
    detections       INTEGER DEFAULT 0,
    avg_fps          REAL    DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions (started DESC);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Database:
    """Owns the SQLite file and hands out per-thread connections."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._lock = threading.Lock()
        self._ready = False

    @property
    def path(self) -> Path:
        return self._path

    def connection(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._path), timeout=10.0)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
            except sqlite3.DatabaseError:
                pass
            self._local.conn = conn
            with self._lock:
                self._connections.append(conn)
        return conn

    def initialise(self) -> None:
        """Create the schema if it does not exist yet."""
        conn = self.connection()
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        conn.commit()
        self._ready = True

    def health(self) -> tuple[bool, str]:
        try:
            self.initialise()
            conn = self.connection()
            conn.execute("SELECT 1").fetchone()
            return True, ""
        except Exception as exc:  # pragma: no cover - filesystem dependent
            return False, str(exc)

    def close_all(self) -> None:
        with self._lock:
            connections = list(self._connections)
            self._connections.clear()
        for conn in connections:
            try:
                conn.commit()
                conn.close()
            except Exception:
                pass
        self._local = threading.local()
