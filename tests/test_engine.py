"""Event engine tests: cooldowns, class rules, region entry and loitering."""

from __future__ import annotations

from detection.types import Detection
from events.engine import EventEngine
from events.rules import EVENT_INTRUSION, EVENT_LOITERING, EVENT_PERSON, EVENT_VEHICLE

FULL_FRAME_REGION = [
    {"name": "Yard", "points": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]}
]


def person(track_id: int = 1, x: float = 100.0, y: float = 100.0) -> Detection:
    return Detection(
        class_id=0, class_name="person", confidence=0.9,
        x1=x, y1=y, x2=x + 40, y2=y + 120, track_id=track_id,
    )


def car(track_id: int = 2, x: float = 400.0, y: float = 300.0) -> Detection:
    return Detection(
        class_id=2, class_name="car", confidence=0.85,
        x1=x, y1=y, x2=x + 120, y2=y + 80, track_id=track_id,
    )


def base_settings(**overrides) -> dict:
    settings = {
        "person_detected": True,
        "vehicle_detected": True,
        "region_intrusion": False,
        "region_loitering": False,
        "cooldown_s": 15.0,
        "loiter_seconds": 8.0,
        "regions": [],
    }
    settings.update(overrides)
    return settings


def test_person_event_is_created():
    engine = EventEngine(base_settings())
    events = engine.evaluate([person()], 1280, 720, 1000.0)
    assert len(events) == 1
    assert events[0].event_type == EVENT_PERSON
    assert events[0].class_name == "person"
    assert events[0].track_id == 1


def test_cooldown_suppresses_repeat_events():
    engine = EventEngine(base_settings(cooldown_s=10.0))
    first = engine.evaluate([person()], 1280, 720, 1000.0)
    second = engine.evaluate([person()], 1280, 720, 1005.0)
    third = engine.evaluate([person()], 1280, 720, 1011.0)

    assert len(first) == 1
    assert second == []
    assert len(third) == 1


def test_different_tracks_are_independent():
    engine = EventEngine(base_settings(cooldown_s=30.0))
    events = engine.evaluate([person(1), person(2, x=300)], 1280, 720, 1000.0)
    assert len(events) == 2


def test_vehicle_event_uses_class_name():
    engine = EventEngine(base_settings())
    events = engine.evaluate([car()], 1280, 720, 1000.0)
    assert len(events) == 1
    assert events[0].event_type == EVENT_VEHICLE
    assert "Car" in events[0].title


def test_disabled_rules_produce_nothing():
    engine = EventEngine(base_settings(person_detected=False, vehicle_detected=False))
    assert engine.evaluate([person(), car()], 1280, 720, 1000.0) == []


def test_empty_frame_produces_nothing():
    engine = EventEngine(base_settings())
    assert engine.evaluate([], 1280, 720, 1000.0) == []
    assert engine.evaluate([person()], 0, 0, 1000.0) == []


def test_region_intrusion_fires_once_per_entry():
    engine = EventEngine(base_settings(
        region_intrusion=True, cooldown_s=0.0, regions=FULL_FRAME_REGION,
    ))
    first = engine.evaluate([person()], 1280, 720, 1000.0)
    assert any(event.event_type == EVENT_INTRUSION for event in first)

    second = engine.evaluate([person()], 1280, 720, 1001.0)
    assert not any(event.event_type == EVENT_INTRUSION for event in second)


def test_region_intrusion_requires_being_inside():
    region = [{"name": "Corner", "points": [[0.0, 0.0], [0.2, 0.0], [0.2, 0.2], [0.0, 0.2]]}]
    engine = EventEngine(base_settings(
        region_intrusion=True, cooldown_s=0.0, regions=region,
    ))
    # Person's foot point is at (120, 220) -> (0.09, 0.30), outside the corner.
    events = engine.evaluate([person()], 1280, 720, 1000.0)
    assert not any(event.event_type == EVENT_INTRUSION for event in events)


def test_loitering_fires_after_threshold():
    # Person events are disabled so the assertions isolate the region rule.
    engine = EventEngine(base_settings(
        person_detected=False,
        vehicle_detected=False,
        region_intrusion=False,
        region_loitering=True,
        loiter_seconds=3.0,
        cooldown_s=0.0,
        regions=FULL_FRAME_REGION,
    ))
    assert engine.evaluate([person()], 1280, 720, 1000.0) == []
    assert engine.evaluate([person()], 1280, 720, 1002.0) == []
    events = engine.evaluate([person()], 1280, 720, 1004.0)
    assert len(events) == 1
    assert events[0].event_type == EVENT_LOITERING
    assert events[0].region_name == "Yard"

    # Must not repeat for the same continuous presence.
    assert engine.evaluate([person()], 1280, 720, 1006.0) == []


def test_loitering_resets_after_leaving():
    engine = EventEngine(base_settings(
        person_detected=False,
        vehicle_detected=False,
        region_loitering=True,
        loiter_seconds=2.0,
        cooldown_s=0.0,
        regions=FULL_FRAME_REGION,
    ))
    engine.evaluate([person()], 1280, 720, 1000.0)
    # Leaving the frame clears presence.
    engine.evaluate([], 1280, 720, 1001.0)
    assert engine.evaluate([person()], 1280, 720, 1002.0) == []
    events = engine.evaluate([person()], 1280, 720, 1005.0)
    assert any(event.event_type == EVENT_LOITERING for event in events)


def test_reset_clears_cooldowns():
    engine = EventEngine(base_settings(cooldown_s=60.0))
    assert len(engine.evaluate([person()], 1280, 720, 1000.0)) == 1
    assert engine.evaluate([person()], 1280, 720, 1001.0) == []
    engine.reset()
    assert len(engine.evaluate([person()], 1280, 720, 1002.0)) == 1


def test_disabled_region_is_ignored():
    engine = EventEngine(base_settings(
        region_intrusion=True,
        cooldown_s=0.0,
        regions=[{"name": "Off", "points": FULL_FRAME_REGION[0]["points"], "enabled": False}],
    ))
    events = engine.evaluate([person()], 1280, 720, 1000.0)
    assert not any(event.event_type == EVENT_INTRUSION for event in events)


def test_region_events_are_flagged_as_region_events():
    engine = EventEngine(base_settings(
        region_intrusion=True, cooldown_s=0.0, regions=FULL_FRAME_REGION,
    ))
    events = engine.evaluate([person()], 1280, 720, 1000.0)
    intrusion = [event for event in events if event.event_type == EVENT_INTRUSION][0]
    assert intrusion.is_region_event
    assert intrusion.region_name == "Yard"
