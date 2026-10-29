"""Safety alert tests: hazardous objects, armed proximity, altercations."""

from __future__ import annotations

from config.defaults import resolve_enabled_classes
from detection.types import Detection
from events.engine import EventEngine
from events.rules import (
    EVENT_ALTERCATION,
    EVENT_ARMED,
    EVENT_HAZARD,
    EVENT_VIOLENCE,
    SEVERITY_ALARM,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    severity_for,
)


def person(track_id: int = 1, x: float = 100.0, y: float = 100.0, speed: float = 0.0) -> Detection:
    det = Detection(
        class_id=0, class_name="person", confidence=0.9,
        x1=x, y1=y, x2=x + 40, y2=y + 120, track_id=track_id,
    )
    det.speed_px_s = speed
    return det


def knife(track_id: int = 9, x: float = 120.0, y: float = 140.0) -> Detection:
    return Detection(
        class_id=43, class_name="knife", confidence=0.7,
        x1=x, y1=y, x2=x + 30, y2=y + 30, track_id=track_id,
    )


def settings(hazards: dict | None = None, **overrides) -> dict:
    base = {
        "person_detected": False,
        "vehicle_detected": False,
        "region_intrusion": False,
        "region_loitering": False,
        "cooldown_s": 0.0,
        "regions": [],
        "hazards": {
            "enabled": True,
            "classes": ["knife", "baseball bat"],
            "require_person_proximity": True,
            "proximity_factor": 0.75,
            "altercation_enabled": True,
            "altercation_overlap": 0.22,
            "altercation_min_seconds": 1.2,
            "cooldown_s": 30.0,
        },
    }
    base.update(overrides)
    if hazards:
        base["hazards"].update(hazards)
    return base


# -- severity --------------------------------------------------------------
def test_severity_mapping():
    assert severity_for("person") == SEVERITY_INFO
    assert severity_for("intrusion") == SEVERITY_WARNING
    assert severity_for("armed") == SEVERITY_ALARM
    assert severity_for("altercation") == SEVERITY_ALARM
    assert severity_for("violence") == SEVERITY_ALARM
    assert severity_for("unknown-type") == SEVERITY_INFO


# -- hazard objects --------------------------------------------------------
def test_hazard_object_alone_is_quiet_when_proximity_is_required():
    engine = EventEngine(settings())
    assert engine.evaluate([knife()], 1280, 720, 1000.0) == []


def test_hazard_object_alone_warns_when_proximity_is_not_required():
    engine = EventEngine(settings({"require_person_proximity": False}))
    events = engine.evaluate([knife()], 1280, 720, 1000.0)
    assert len(events) == 1
    assert events[0].event_type == EVENT_HAZARD
    assert events[0].severity == SEVERITY_WARNING


def test_knife_next_to_person_raises_armed_alert():
    engine = EventEngine(settings())
    events = engine.evaluate([person(), knife()], 1280, 720, 1000.0)
    armed = [event for event in events if event.event_type == EVENT_ARMED]
    assert len(armed) == 1
    assert armed[0].severity == SEVERITY_ALARM
    assert armed[0].track_id == 1  # attributed to the person, not the knife
    assert "knife" in armed[0].details


def test_distant_knife_is_ignored():
    engine = EventEngine(settings())
    events = engine.evaluate([person(), knife(x=900.0, y=400.0)], 1280, 720, 1000.0)
    assert not any(event.event_type == EVENT_ARMED for event in events)


def test_proximity_range_widens_the_match():
    far_knife = knife(x=170.0, y=140.0)  # centre (185, 155)
    tight = EventEngine(settings({"proximity_factor": 0.20}))
    assert not any(
        event.event_type == EVENT_ARMED
        for event in tight.evaluate([person(), far_knife], 1280, 720, 1000.0)
    )

    wide = EventEngine(settings({"proximity_factor": 1.60}))
    assert any(
        event.event_type == EVENT_ARMED
        for event in wide.evaluate([person(), knife(x=170.0, y=140.0)], 1280, 720, 1000.0)
    )


def test_armed_alert_respects_its_cooldown():
    engine = EventEngine(settings({"cooldown_s": 30.0}))
    first = engine.evaluate([person(), knife()], 1280, 720, 1000.0)
    assert any(event.event_type == EVENT_ARMED for event in first)

    second = engine.evaluate([person(), knife()], 1280, 720, 1005.0)
    assert not any(event.event_type == EVENT_ARMED for event in second)

    third = engine.evaluate([person(), knife()], 1280, 720, 1040.0)
    assert any(event.event_type == EVENT_ARMED for event in third)


def test_disabling_hazards_silences_everything():
    engine = EventEngine(settings({"enabled": False}))
    assert engine.evaluate([person(), knife()], 1280, 720, 1000.0) == []


def test_empty_hazard_class_list_is_harmless():
    engine = EventEngine(settings({"classes": []}))
    assert engine.evaluate([person(), knife()], 1280, 720, 1000.0) == []


# -- altercations ----------------------------------------------------------
def test_altercation_needs_sustained_overlap():
    engine = EventEngine(settings({"altercation_min_seconds": 1.2}))
    first = person(1, 100.0, 100.0, speed=30.0)
    second = person(2, 115.0, 100.0, speed=30.0)

    assert engine.evaluate([first, second], 1280, 720, 1000.0) == []
    events = engine.evaluate([first, second], 1280, 720, 1001.5)
    altercations = [event for event in events if event.event_type == EVENT_ALTERCATION]
    assert len(altercations) == 1
    assert altercations[0].severity == SEVERITY_ALARM


def test_altercation_requires_movement():
    engine = EventEngine(settings({"altercation_min_seconds": 0.5}))
    still_a = person(1, 100.0, 100.0, speed=0.0)
    still_b = person(2, 115.0, 100.0, speed=0.0)
    engine.evaluate([still_a, still_b], 1280, 720, 1000.0)
    events = engine.evaluate([still_a, still_b], 1280, 720, 1002.0)
    assert not any(event.event_type == EVENT_ALTERCATION for event in events)


def test_altercation_requires_two_people():
    engine = EventEngine(settings({"altercation_min_seconds": 0.5}))
    solo = person(1, 100.0, 100.0, speed=40.0)
    engine.evaluate([solo], 1280, 720, 1000.0)
    events = engine.evaluate([solo], 1280, 720, 1003.0)
    assert not any(event.event_type == EVENT_ALTERCATION for event in events)


def test_separated_people_do_not_trigger_altercation():
    engine = EventEngine(settings({"altercation_min_seconds": 0.5}))
    left = person(1, 100.0, 100.0, speed=40.0)
    right = person(2, 600.0, 100.0, speed=40.0)
    engine.evaluate([left, right], 1280, 720, 1000.0)
    events = engine.evaluate([left, right], 1280, 720, 1003.0)
    assert not any(event.event_type == EVENT_ALTERCATION for event in events)


def test_altercation_fires_once_per_pair():
    engine = EventEngine(settings({"altercation_min_seconds": 0.5, "cooldown_s": 30.0}))
    first = person(1, 100.0, 100.0, speed=30.0)
    second = person(2, 115.0, 100.0, speed=30.0)
    engine.evaluate([first, second], 1280, 720, 1000.0)
    engine.evaluate([first, second], 1280, 720, 1001.0)
    later = engine.evaluate([first, second], 1280, 720, 1002.0)
    assert not any(event.event_type == EVENT_ALTERCATION for event in later)


# -- class filter ----------------------------------------------------------
def test_hazard_classes_are_added_to_the_detection_filter():
    detection = {"enabled_classes": ["person", "car"]}
    events = {"hazards": {"enabled": True, "classes": ["knife", "baseball bat"]}}
    resolved = resolve_enabled_classes(detection, events)
    assert resolved == ["baseball bat", "car", "knife", "person"]


def test_disabled_hazards_do_not_widen_the_filter():
    detection = {"enabled_classes": ["person"]}
    events = {"hazards": {"enabled": False, "classes": ["knife"]}}
    assert resolve_enabled_classes(detection, events) == ["person"]


def test_filter_handles_missing_sections():
    assert resolve_enabled_classes(None, None) == []
    assert resolve_enabled_classes({"enabled_classes": []}, {"hazards": {}}) == []


# -- violence model --------------------------------------------------------
def violence(confidence: float = 0.8) -> Detection:
    return Detection(
        class_id=1, class_name="violence", confidence=confidence,
        x1=100, y1=100, x2=300, y2=300, track_id=None,
    )


def non_violence() -> Detection:
    return Detection(
        class_id=0, class_name="non_violence", confidence=0.9,
        x1=100, y1=100, x2=300, y2=300, track_id=None,
    )


def safety(enabled: bool = True, cooldown: float = 20.0) -> dict:
    return {"enabled": enabled, "classes": ["violence"], "cooldown_s": cooldown}


def test_violence_hit_raises_an_alarm():
    engine = EventEngine(settings(), safety())
    events = engine.evaluate([violence()], 1280, 720, 1000.0)
    alarms = [event for event in events if event.event_type == EVENT_VIOLENCE]
    assert len(alarms) == 1
    assert alarms[0].severity == SEVERITY_ALARM
    assert alarms[0].class_name == "violence"


def test_violence_is_ignored_when_the_model_is_disabled():
    engine = EventEngine(settings(), safety(enabled=False))
    assert engine.evaluate([violence()], 1280, 720, 1000.0) == []


def test_non_violence_class_is_ignored():
    engine = EventEngine(settings(), safety())
    assert engine.evaluate([non_violence()], 1280, 720, 1000.0) == []


def test_violence_alarm_respects_its_cooldown():
    engine = EventEngine(settings(), safety(cooldown=20.0))
    first = engine.evaluate([violence()], 1280, 720, 1000.0)
    second = engine.evaluate([violence()], 1280, 720, 1005.0)
    third = engine.evaluate([violence()], 1280, 720, 1030.0)

    assert any(event.event_type == EVENT_VIOLENCE for event in first)
    assert not any(event.event_type == EVENT_VIOLENCE for event in second)
    assert any(event.event_type == EVENT_VIOLENCE for event in third)


def test_many_violence_boxes_produce_one_alarm():
    engine = EventEngine(settings(), safety())
    boxes = [violence(0.8), violence(0.7), violence(0.6)]
    events = engine.evaluate(boxes, 1280, 720, 1000.0)
    assert len([event for event in events if event.event_type == EVENT_VIOLENCE]) == 1


def test_violence_and_heuristics_coexist():
    engine = EventEngine(settings(), safety())
    events = engine.evaluate([person(), knife(), violence()], 1280, 720, 1000.0)
    kinds = {event.event_type for event in events}
    assert EVENT_ARMED in kinds
    assert EVENT_VIOLENCE in kinds
