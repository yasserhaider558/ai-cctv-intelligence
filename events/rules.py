"""Event vocabulary shared by the engine, the database and the interface."""

from __future__ import annotations

from dataclasses import dataclass

EVENT_PERSON = "person"
EVENT_VEHICLE = "vehicle"
EVENT_INTRUSION = "intrusion"
EVENT_LOITERING = "loitering"
EVENT_HAZARD = "hazard"
EVENT_ARMED = "armed"
EVENT_ALTERCATION = "altercation"
EVENT_VIOLENCE = "violence"

ALL_EVENT_TYPES: tuple[str, ...] = (
    EVENT_PERSON, EVENT_VEHICLE, EVENT_INTRUSION, EVENT_LOITERING,
    EVENT_HAZARD, EVENT_ARMED, EVENT_ALTERCATION, EVENT_VIOLENCE,
)

EVENT_LABELS: dict[str, str] = {
    EVENT_PERSON: "Person detected",
    EVENT_VEHICLE: "Vehicle detected",
    EVENT_INTRUSION: "Region entry",
    EVENT_LOITERING: "Loitering",
    EVENT_HAZARD: "Hazardous object",
    EVENT_ARMED: "Possible weapon",
    EVENT_ALTERCATION: "Possible altercation",
    EVENT_VIOLENCE: "Violence detected",
}

EVENT_DESCRIPTIONS: dict[str, str] = {
    EVENT_PERSON: "A person was detected in the frame.",
    EVENT_VEHICLE: "A vehicle was detected in the frame.",
    EVENT_INTRUSION: "A tracked object entered a region you drew.",
    EVENT_LOITERING: "A tracked object stayed inside a region longer than the limit.",
    EVENT_HAZARD: "A class on the hazard list was detected.",
    EVENT_ARMED: "A hazard class was detected next to a person.",
    EVENT_ALTERCATION: "Two people overlapped and moved together for a sustained period.",
    EVENT_VIOLENCE: "The violence detection model reported a violent scene.",
}

# -- severity ---------------------------------------------------------------
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ALARM = "alarm"

#: How prominently an event is presented. Severity is derived from the event
#: type rather than stored, so the database schema stays unchanged.
EVENT_SEVERITY: dict[str, str] = {
    EVENT_PERSON: SEVERITY_INFO,
    EVENT_VEHICLE: SEVERITY_INFO,
    EVENT_INTRUSION: SEVERITY_WARNING,
    EVENT_LOITERING: SEVERITY_WARNING,
    EVENT_HAZARD: SEVERITY_WARNING,
    EVENT_ARMED: SEVERITY_ALARM,
    EVENT_ALTERCATION: SEVERITY_ALARM,
    EVENT_VIOLENCE: SEVERITY_ALARM,
}

ALARM_EVENT_TYPES: tuple[str, ...] = tuple(
    event_type for event_type, severity in EVENT_SEVERITY.items() if severity == SEVERITY_ALARM
)
WARNING_EVENT_TYPES: tuple[str, ...] = tuple(
    event_type
    for event_type, severity in EVENT_SEVERITY.items()
    if severity in (SEVERITY_WARNING, SEVERITY_ALARM)
)


def severity_for(event_type: str) -> str:
    return EVENT_SEVERITY.get(event_type, SEVERITY_INFO)


def event_label(event_type: str) -> str:
    return EVENT_LABELS.get(event_type, event_type.replace("_", " ").title())


@dataclass
class EventRecord:
    event_type: str
    title: str
    ts: float
    class_name: str = ""
    track_id: int | None = None
    confidence: float | None = None
    region_name: str = ""
    camera: str = ""
    snapshot: str = ""
    details: str = ""
    id: int | None = None

    @property
    def is_region_event(self) -> bool:
        return self.event_type in (EVENT_INTRUSION, EVENT_LOITERING)

    @property
    def label(self) -> str:
        return event_label(self.event_type)

    @property
    def severity(self) -> str:
        return severity_for(self.event_type)

    @property
    def is_alarm(self) -> bool:
        return self.severity == SEVERITY_ALARM
