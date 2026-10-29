"""Event detection: regions, rules and the evaluation engine."""

from events.engine import EventEngine
from events.regions import Region, point_in_polygon, regions_from_config, regions_to_config
from events.rules import ALL_EVENT_TYPES, EVENT_LABELS, EventRecord, event_label

__all__ = [
    "EventEngine",
    "Region",
    "point_in_polygon",
    "regions_from_config",
    "regions_to_config",
    "ALL_EVENT_TYPES",
    "EVENT_LABELS",
    "EventRecord",
    "event_label",
]
