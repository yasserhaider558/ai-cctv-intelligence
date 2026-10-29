"""Trail history and movement-direction tests."""

from __future__ import annotations

from detection.types import Detection
from tracking.trails import TrailStore, direction_label


def det(centre_x: float, centre_y: float, track_id: int | None = 1) -> Detection:
    return Detection(
        class_id=0, class_name="person", confidence=0.9,
        x1=centre_x - 10, y1=centre_y - 10, x2=centre_x + 10, y2=centre_y + 10,
        track_id=track_id,
    )


def test_direction_cardinals():
    assert direction_label(10, 0) == "E"
    assert direction_label(0, -10) == "N"
    assert direction_label(-10, 0) == "W"
    assert direction_label(0, 10) == "S"


def test_direction_diagonals():
    assert direction_label(10, -10) == "NE"
    assert direction_label(-10, -10) == "NW"
    assert direction_label(-10, 10) == "SW"
    assert direction_label(10, 10) == "SE"


def test_direction_below_threshold_is_blank():
    assert direction_label(2, 2, min_distance=6) == ""


def test_trail_records_positions():
    store = TrailStore()
    store.update([det(100, 100)], 1000.0)
    paths = store.update([det(140, 100)], 1000.4)
    assert 1 in paths
    assert len(paths[1]) == 2


def test_detection_gets_direction_and_speed():
    store = TrailStore()
    store.update([det(100, 100)], 1000.0)
    moving = det(200, 100)
    store.update([moving], 1000.5)
    assert moving.direction == "E"
    assert moving.speed_px_s > 0


def test_single_point_has_no_direction():
    store = TrailStore()
    only = det(100, 100)
    store.update([only], 1000.0)
    assert only.direction == ""


def test_stale_tracks_are_pruned():
    store = TrailStore(ttl_s=1.0)
    store.update([det(100, 100)], 1000.0)
    store.update([det(300, 300, track_id=2)], 1005.0)
    assert 1 not in store.paths()


def test_reset_clears_trails():
    store = TrailStore()
    store.update([det(100, 100)], 1000.0)
    store.reset()
    assert store.paths() == {}


def test_untracked_detections_are_ignored():
    store = TrailStore()
    paths = store.update([det(100, 100, track_id=None)], 1000.0)
    assert paths == {}
