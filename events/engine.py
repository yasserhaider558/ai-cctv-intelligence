"""Event rules: plain detections, region entry, and loitering.

The engine is deliberately Qt-free and database-free. It receives detections and
returns :class:`EventRecord` objects; the caller decides whether to persist them.
That separation is what makes the cooldown and loitering logic unit-testable.

Cooldowns matter: without them a person standing in front of the camera would
create a "person detected" row for every processed frame - hundreds per minute.
"""

from __future__ import annotations

from typing import Sequence

from config.defaults import HAZARD_CLASSES, is_vehicle
from events.regions import Region, regions_from_config
from events.rules import (
    EVENT_ALTERCATION,
    EVENT_ARMED,
    EVENT_HAZARD,
    EVENT_INTRUSION,
    EVENT_LOITERING,
    EVENT_PERSON,
    EVENT_VEHICLE,
    EVENT_VIOLENCE,
    EventRecord,
)
from tracking.fallback_tracker import iou

_PRUNE_EVERY = 300


class EventEngine:
    def __init__(self, settings: dict | None = None, safety_model: dict | None = None) -> None:
        self._person_enabled = True
        self._vehicle_enabled = True
        self._intrusion_enabled = False
        self._loitering_enabled = False
        self._cooldown_s = 15.0
        self._loiter_seconds = 8.0
        self._regions: list[Region] = []

        # Hazard / safety heuristics. These are geometric rules over ordinary
        # detections, not a weapon or violence classifier - see the README.
        self._hazards_enabled = True
        self._hazard_classes: set[str] = set(HAZARD_CLASSES)
        self._require_proximity = True
        self._proximity_factor = 0.75
        self._altercation_enabled = True
        self._altercation_overlap = 0.22
        self._altercation_min_seconds = 1.2
        self._hazard_cooldown_s = 30.0
        self._pair_first: dict[tuple, float] = {}
        self._pair_fired: set[tuple] = set()

        # Violence model. Unlike the rules above, this one consumes real output
        # from a dedicated classifier-style detector, not a geometric heuristic.
        self._violence_enabled = False
        self._violence_classes: set[str] = {"violence"}
        self._violence_cooldown_s = 20.0

        self._last_fired: dict[tuple, float] = {}
        self._first_seen: dict[tuple, float] = {}
        self._last_seen: dict[tuple, float] = {}
        self._loiter_fired: set[tuple] = set()
        self._evaluations = 0

        if settings:
            self.configure(settings, safety_model)

    # -- configuration -----------------------------------------------------
    def configure(self, settings: dict, safety_model: dict | None = None) -> None:
        if not isinstance(settings, dict):
            return
        self._person_enabled = bool(settings.get("person_detected", self._person_enabled))
        self._vehicle_enabled = bool(settings.get("vehicle_detected", self._vehicle_enabled))
        self._intrusion_enabled = bool(settings.get("region_intrusion", self._intrusion_enabled))
        self._loitering_enabled = bool(settings.get("region_loitering", self._loitering_enabled))
        self._cooldown_s = max(0.0, float(settings.get("cooldown_s", self._cooldown_s)))
        self._loiter_seconds = max(0.5, float(settings.get("loiter_seconds", self._loiter_seconds)))
        if "regions" in settings:
            self._regions = regions_from_config(settings.get("regions"))

        hazards = settings.get("hazards")
        if isinstance(hazards, dict):
            self._hazards_enabled = bool(hazards.get("enabled", self._hazards_enabled))
            classes = hazards.get("classes")
            if isinstance(classes, (list, tuple)):
                self._hazard_classes = {str(c).strip().lower() for c in classes if str(c).strip()}
            self._require_proximity = bool(
                hazards.get("require_person_proximity", self._require_proximity)
            )
            self._proximity_factor = max(
                0.1, float(hazards.get("proximity_factor", self._proximity_factor))
            )
            self._altercation_enabled = bool(
                hazards.get("altercation_enabled", self._altercation_enabled)
            )
            self._altercation_overlap = min(
                0.95, max(0.05, float(hazards.get("altercation_overlap", self._altercation_overlap)))
            )
            self._altercation_min_seconds = max(
                0.2, float(hazards.get("altercation_min_seconds", self._altercation_min_seconds))
            )
            self._hazard_cooldown_s = max(
                0.0, float(hazards.get("cooldown_s", self._hazard_cooldown_s))
            )

        if isinstance(safety_model, dict):
            self._violence_enabled = bool(
                safety_model.get("enabled", self._violence_enabled)
            )
            classes = safety_model.get("classes")
            if isinstance(classes, (list, tuple)):
                self._violence_classes = {
                    str(item).strip().lower() for item in classes if str(item).strip()
                }
            self._violence_cooldown_s = max(
                0.0, float(safety_model.get("cooldown_s", self._violence_cooldown_s))
            )

    @property
    def regions(self) -> list[Region]:
        return list(self._regions)

    @property
    def cooldown_s(self) -> float:
        return self._cooldown_s

    def reset(self) -> None:
        """Forget presence state. Call when the video source changes."""
        self._last_fired.clear()
        self._clear_presence()
    # -- evaluation --------------------------------------------------------
    def evaluate(
        self,
        detections: Sequence,
        width: int,
        height: int,
        timestamp: float,
        camera: str = "",
    ) -> list[EventRecord]:
        events: list[EventRecord] = []
        if width <= 0 or height <= 0:
            return events
        if not detections:
            # Nothing is on screen, so nothing can be inside a region. Clearing
            # this is what makes a later re-entry count as a new entry.
            self._clear_presence()
            return events

        # 1. Plain class events -------------------------------------------
        for det in detections:
            if self._person_enabled and det.class_name == "person":
                if self._allow(("person", det.track_id), timestamp):
                    events.append(self._record(
                        EVENT_PERSON, "Person detected", det, timestamp, camera,
                    ))
            elif self._vehicle_enabled and is_vehicle(det.class_name):
                if self._allow(("vehicle", det.track_id), timestamp):
                    events.append(self._record(
                        EVENT_VEHICLE, f"{det.class_name.capitalize()} detected",
                        det, timestamp, camera,
                    ))

        # 2. Region events --------------------------------------------------
        if self._intrusion_enabled or self._loitering_enabled:
            seen_presence: set[tuple] = set()
            for det in detections:
                track_key = self._track_key(det)
                foot_x, foot_y = det.foot_point
                for region in self._regions:
                    if not region.enabled:
                        continue
                    presence_key = (track_key, region.name)
                    inside = region.contains(foot_x, foot_y, width, height)
                    if not inside:
                        self._first_seen.pop(presence_key, None)
                        self._last_seen.pop(presence_key, None)
                        self._loiter_fired.discard(presence_key)
                        continue

                    seen_presence.add(presence_key)
                    self._last_seen[presence_key] = timestamp
                    first = self._first_seen.get(presence_key)
                    if first is None:
                        self._first_seen[presence_key] = timestamp
                        if self._intrusion_enabled and self._allow(
                            ("intrusion", region.name, track_key), timestamp
                        ):
                            record = self._record(
                                EVENT_INTRUSION,
                                f"{det.class_name.capitalize()} entered '{region.name}'",
                                det, timestamp, camera,
                            )
                            record.region_name = region.name
                            events.append(record)
                    elif self._loitering_enabled and presence_key not in self._loiter_fired:
                        dwell = timestamp - first
                        if dwell >= self._loiter_seconds:
                            self._loiter_fired.add(presence_key)
                            if self._allow(("loiter", region.name, track_key), timestamp):
                                record = self._record(
                                    EVENT_LOITERING,
                                    f"{det.class_name.capitalize()} loitering in "
                                    f"'{region.name}' for {dwell:.0f}s",
                                    det, timestamp, camera,
                                )
                                record.region_name = region.name
                                events.append(record)

            # A tracked object that vanished from the frame must not keep its
            # "inside region" state, otherwise a re-entry would look continuous.
            for stale_key in [k for k in self._first_seen if k not in seen_presence]:
                self._first_seen.pop(stale_key, None)
                self._last_seen.pop(stale_key, None)
                self._loiter_fired.discard(stale_key)

        # 3. Hazard and safety events ---------------------------------------
        if self._hazards_enabled and self._hazard_classes:
            events.extend(self._evaluate_hazards(detections, timestamp, camera))

        # 4. Violence model --------------------------------------------------
        if self._violence_enabled and self._violence_classes:
            events.extend(self._evaluate_violence(detections, timestamp, camera))

        self._evaluations += 1
        if self._evaluations % _PRUNE_EVERY == 0:
            self._prune(timestamp)
        return events

    def _evaluate_hazards(self, detections, timestamp: float, camera: str) -> list[EventRecord]:
        """Turn hazard-class detections into warnings.

        Two shapes are supported: a bare hazardous object, or - the default - a
        hazardous object next to a person, which is the case that actually
        matters. Both are geometric rules over real detections; neither is a
        weapon classifier.
        """
        found: list[EventRecord] = []
        persons = [d for d in detections if d.class_name == "person"]
        hazards = [d for d in detections if d.class_name.lower() in self._hazard_classes]

        for obj in hazards:
            if self._require_proximity:
                if not persons:
                    continue
                nearest = min(persons, key=lambda person: self._distance_to(person, obj))
                if not self._is_near(nearest, obj):
                    continue
                key = ("armed", obj.class_name, obj.track_id, nearest.track_id)
                if not self._allow_with(key, timestamp, self._hazard_cooldown_s):
                    continue
                record = self._record(
                    EVENT_ARMED, f"Person near a {obj.class_name}", nearest, timestamp, camera,
                )
                record.details = (
                    f"{obj.class_name} {obj.confidence:.2f} (track {obj.track_id}) "
                    f"next to person track {nearest.track_id}"
                )
                found.append(record)
            else:
                key = ("hazard", obj.class_name, obj.track_id)
                if not self._allow_with(key, timestamp, self._hazard_cooldown_s):
                    continue
                found.append(self._record(
                    EVENT_HAZARD, f"{obj.class_name.capitalize()} detected",
                    obj, timestamp, camera,
                ))

        if self._altercation_enabled and len(persons) >= 2:
            found.extend(self._evaluate_altercations(persons, timestamp, camera))
        return found

    def _evaluate_altercations(
        self, persons, timestamp: float, camera: str
    ) -> list[EventRecord]:
        found: list[EventRecord] = []
        seen: set[tuple] = set()
        for index, first in enumerate(persons):
            for second in persons[index + 1:]:
                overlap = iou(
                    (first.x1, first.y1, first.x2, first.y2),
                    (second.x1, second.y1, second.x2, second.y2),
                )
                if overlap < self._altercation_overlap:
                    continue
                pair_key = tuple(sorted((self._track_key(first), self._track_key(second))))
                seen.add(pair_key)
                started = self._pair_first.get(pair_key)
                if started is None:
                    self._pair_first[pair_key] = timestamp
                    continue
                dwell = timestamp - started
                if dwell < self._altercation_min_seconds or pair_key in self._pair_fired:
                    continue
                if max(first.speed_px_s, second.speed_px_s) < 12.0:
                    continue
                self._pair_fired.add(pair_key)
                if not self._allow_with(
                    ("altercation", pair_key), timestamp, self._hazard_cooldown_s
                ):
                    continue
                record = self._record(
                    EVENT_ALTERCATION, "Possible altercation between two people",
                    first, timestamp, camera,
                )
                record.details = (
                    f"persons {first.track_id} and {second.track_id} "
                    f"overlapped for {dwell:.1f}s"
                )
                found.append(record)

        for stale in [key for key in self._pair_first if key not in seen]:
            self._pair_first.pop(stale, None)
            self._pair_fired.discard(stale)
        return found

    def _evaluate_violence(self, detections, timestamp: float, camera: str) -> list[EventRecord]:
        """Raise one alarm per cooldown window when the model reports violence.

        The violence detector runs without tracking, so hits usually carry no
        track ID; keying on ``None`` is what collapses a frame full of boxes into
        a single event instead of one per box.
        """
        found: list[EventRecord] = []
        for det in detections:
            if det.class_name.lower() not in self._violence_classes:
                continue
            if not self._allow_with(
                ("violence", det.track_id), timestamp, self._violence_cooldown_s
            ):
                continue
            record = self._record(
                EVENT_VIOLENCE, "Violence detected", det, timestamp, camera
            )
            record.details = f"{det.class_name} {det.confidence:.2f}"
            found.append(record)
        return found

    def _is_near(self, person, obj) -> bool:
        # Reach scales with the person's height, not their box width: a tall,
        # narrow box would otherwise get almost no margin.
        margin_x = person.height * 0.25 * self._proximity_factor
        margin_y = person.height * 0.15 * self._proximity_factor
        centre_x, centre_y = obj.center
        return (
            person.x1 - margin_x <= centre_x <= person.x2 + margin_x
            and person.y1 - margin_y <= centre_y <= person.y2 + margin_y
        )

    @staticmethod
    def _distance_to(person, obj) -> float:
        obj_x, obj_y = obj.center
        person_x, person_y = person.center
        return ((obj_x - person_x) ** 2 + (obj_y - person_y) ** 2) ** 0.5

    def _clear_presence(self) -> None:
        self._first_seen.clear()
        self._last_seen.clear()
        self._loiter_fired.clear()
        self._pair_first.clear()
        self._pair_fired.clear()

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _track_key(det) -> tuple:
        if det.track_id is not None:
            return ("id", int(det.track_id), det.class_name)
        # Without tracking, bucket by position so a stationary object keeps a
        # stable key instead of generating a new one every frame.
        cx, cy = det.center
        return ("pos", det.class_name, int(cx // 96), int(cy // 96))

    def _allow(self, key: tuple, timestamp: float) -> bool:
        return self._allow_with(key, timestamp, self._cooldown_s)

    def _allow_with(self, key: tuple, timestamp: float, cooldown: float) -> bool:
        last = self._last_fired.get(key)
        if last is not None and (timestamp - last) < cooldown:
            return False
        self._last_fired[key] = timestamp
        return True

    @staticmethod
    def _record(
        event_type: str, title: str, det, timestamp: float, camera: str
    ) -> EventRecord:
        return EventRecord(
            event_type=event_type,
            title=title,
            ts=float(timestamp),
            class_name=det.class_name,
            track_id=det.track_id,
            confidence=round(float(det.confidence), 3),
            camera=camera,
            details=f"confidence={det.confidence:.2f}",
        )

    def _prune(self, timestamp: float) -> None:
        stale = [k for k, ts in self._last_seen.items() if timestamp - ts > 300.0]
        for key in stale:
            self._last_seen.pop(key, None)
            self._first_seen.pop(key, None)
            self._loiter_fired.discard(key)
        if len(self._last_fired) > 2000:
            horizon = timestamp - 3600.0
            self._last_fired = {k: v for k, v in self._last_fired.items() if v >= horizon}

    def active_region_count(self) -> int:
        return sum(1 for region in self._regions if region.enabled)
