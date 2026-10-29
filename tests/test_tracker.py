"""Fallback IoU tracker tests."""

from __future__ import annotations

from detection.types import Detection
from tracking.fallback_tracker import SimpleTracker, iou


def det(x1: float, y1: float, x2: float, y2: float, class_name: str = "person") -> Detection:
    return Detection(
        class_id=0, class_name=class_name, confidence=0.9,
        x1=x1, y1=y1, x2=x2, y2=y2,
    )


def test_iou_identical_boxes():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0


def test_iou_disjoint_boxes():
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0


def test_iou_half_overlap():
    assert abs(iou((0, 0, 10, 10), (5, 0, 15, 10)) - (50 / 150)) < 1e-9


def test_iou_degenerate_boxes():
    assert iou((0, 0, 0, 0), (0, 0, 0, 0)) == 0.0


def test_same_object_keeps_id():
    tracker = SimpleTracker(iou_threshold=0.3)
    first = det(10, 10, 110, 210)
    tracker.update([first])
    assert first.track_id == 1

    second = det(14, 12, 114, 212)
    tracker.update([second])
    assert second.track_id == 1

    third = det(18, 15, 118, 215)
    tracker.update([third])
    assert third.track_id == 1


def test_new_object_gets_new_id():
    tracker = SimpleTracker(iou_threshold=0.3)
    first = det(10, 10, 110, 210)
    tracker.update([first])

    other = det(500, 400, 600, 600)
    tracker.update([other])

    assert first.track_id == 1
    assert other.track_id == 2


def test_different_classes_are_not_matched():
    tracker = SimpleTracker(iou_threshold=0.3)
    person = det(10, 10, 110, 210, "person")
    tracker.update([person])

    car = det(10, 10, 110, 210, "car")
    tracker.update([car])

    assert car.track_id != person.track_id


def test_expired_track_gets_new_id_on_return():
    tracker = SimpleTracker(iou_threshold=0.3, max_age=1)
    first = det(10, 10, 110, 210)
    tracker.update([first])
    original = first.track_id

    tracker.update([])  # age 1 - still alive
    tracker.update([])  # age 2 - evicted

    again = det(10, 10, 110, 210)
    tracker.update([again])
    assert again.track_id != original


def test_reset_clears_state():
    tracker = SimpleTracker()
    first = det(10, 10, 110, 210)
    tracker.update([first])
    tracker.reset()
    assert tracker.active_ids == []

    second = det(10, 10, 110, 210)
    tracker.update([second])
    assert second.track_id == 1


def test_multiple_objects_in_one_frame():
    tracker = SimpleTracker()
    a = det(0, 0, 50, 100)
    b = det(300, 300, 350, 400)
    tracker.update([a, b])
    assert {a.track_id, b.track_id} == {1, 2}
