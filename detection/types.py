"""Pure data types shared by detection, tracking, events and the interface."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Detection:
    """One detected object in source-frame pixel coordinates."""

    class_id: int
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float
    track_id: int | None = None
    direction: str = ""
    speed_px_s: float = 0.0

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def foot_point(self) -> tuple[float, float]:
        """Bottom-centre of the box - a better anchor for region tests."""
        return (self.x1 + self.x2) / 2.0, self.y2

    def as_dict(self) -> dict:
        return {
            "class_id": self.class_id,
            "class_name": self.class_name,
            "confidence": round(self.confidence, 4),
            "box": [round(self.x1, 1), round(self.y1, 1), round(self.x2, 1), round(self.y2, 1)],
            "track_id": self.track_id,
            "direction": self.direction,
        }


@dataclass
class DetectionResult:
    """Output of a single inference pass."""

    detections: list[Detection] = field(default_factory=list)
    inference_ms: float = 0.0
    frame_size: tuple[int, int] = (0, 0)
    tracking_active: bool = False
    error: str = ""

    @property
    def count(self) -> int:
        return len(self.detections)

    def by_class(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for det in self.detections:
            counts[det.class_name] = counts.get(det.class_name, 0) + 1
        return counts

    def count_of(self, predicate) -> int:
        return sum(1 for det in self.detections if predicate(det))
