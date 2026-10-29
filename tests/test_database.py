"""Database and repository tests."""

from __future__ import annotations

import pytest

from database.db import Database
from database.repositories import EventRepository, SessionRepository


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "events.db")
    database.initialise()
    yield database
    database.close_all()


@pytest.fixture()
def events(db):
    return EventRepository(db)


@pytest.fixture()
def sessions(db):
    return SessionRepository(db)


def test_schema_created(db):
    healthy, error = db.health()
    assert healthy, error


def test_add_and_read_event(events):
    event_id = events.add(
        ts=1000.0,
        event_type="person",
        title="Person detected",
        class_name="person",
        track_id=7,
        confidence=0.91,
        camera="Front door",
    )
    assert event_id > 0

    row = events.get(event_id)
    assert row is not None
    assert row.title == "Person detected"
    assert row.track_id == 7
    assert row.class_name == "person"


def test_list_is_newest_first(events):
    events.add(ts=100.0, event_type="person", title="old")
    events.add(ts=300.0, event_type="vehicle", title="new")
    events.add(ts=200.0, event_type="person", title="middle")

    rows = events.list()
    assert [row.title for row in rows] == ["new", "middle", "old"]


def test_filter_by_type(events):
    events.add(ts=100.0, event_type="person", title="Person detected")
    events.add(ts=200.0, event_type="intrusion", title="Entered zone")

    rows = events.list(event_type="intrusion")
    assert len(rows) == 1
    assert rows[0].event_type == "intrusion"


def test_search_matches_title_and_class(events):
    events.add(ts=100.0, event_type="person", title="Person detected", class_name="person")
    events.add(ts=200.0, event_type="vehicle", title="Car detected", class_name="car")

    assert len(events.list(search="person")) == 1
    assert len(events.list(search="Car")) == 1
    assert len(events.list(search="nothing-here")) == 0


def test_time_range_filter(events):
    events.add(ts=100.0, event_type="person", title="old")
    events.add(ts=500.0, event_type="person", title="new")

    assert len(events.list(since=200.0)) == 1
    assert len(events.list(until=200.0)) == 1
    assert events.count(since=200.0) == 1


def test_delete_and_clear(events):
    first = events.add(ts=1.0, event_type="person", title="a")
    second = events.add(ts=2.0, event_type="person", title="b")
    events.add(ts=3.0, event_type="person", title="c")

    assert events.delete([first, second]) == 2
    assert events.count() == 1
    assert events.clear() == 1
    assert events.count() == 0


def test_prune_keeps_newest(events):
    for index in range(6):
        events.add(ts=float(index), event_type="person", title=f"e{index}")

    events.prune(2)
    rows = events.list()
    assert len(rows) == 2
    assert rows[0].title == "e5"
    assert rows[1].title == "e4"


def test_class_distribution(events):
    events.add(ts=1.0, event_type="person", title="p1", class_name="person")
    events.add(ts=2.0, event_type="person", title="p2", class_name="person")
    events.add(ts=3.0, event_type="vehicle", title="c1", class_name="car")

    distribution = dict(events.class_distribution())
    assert distribution["person"] == 2
    assert distribution["car"] == 1


def test_bucket_counts(events):
    events.add(ts=3600.0, event_type="person", title="a")
    events.add(ts=3650.0, event_type="person", title="b")
    events.add(ts=7300.0, event_type="person", title="c")

    buckets = dict(events.bucket_counts(0.0, 3600))
    assert buckets[3600] == 2
    assert buckets[7200] == 1


def test_sessions_uptime_and_fps(sessions):
    first = sessions.start("Front door", "file", 1000.0)
    sessions.finish(first, ended=1060.0, frames_processed=300, detections=42, avg_fps=9.5)

    second = sessions.start("Front door", "file", 2000.0)
    sessions.finish(second, ended=2030.0, frames_processed=100, detections=10, avg_fps=8.0)

    uptime = sessions.uptime_by_camera()
    assert len(uptime) == 1
    camera, seconds, count = uptime[0]
    assert camera == "Front door"
    assert seconds == pytest.approx(90.0)
    assert count == 2

    assert sessions.average_fps() == pytest.approx(8.75)
    frames, detections, count = sessions.totals()
    assert frames == 400
    assert detections == 52
    assert count == 2


def test_close_orphan_sessions(sessions):
    sessions.start("Cam", "rtsp", 1000.0)
    sessions.close_orphans(1100.0)
    rows = sessions.list()
    assert rows[0].ended == 1100.0
    assert rows[0].duration_s == pytest.approx(100.0)
