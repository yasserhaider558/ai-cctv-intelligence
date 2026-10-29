"""Polygonal regions of interest, stored in normalised coordinates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

Point = tuple[float, float]


def clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else float(value)


def validate_polygon(points: Sequence[Point]) -> bool:
    """A usable polygon needs at least three distinct vertices."""
    if points is None or len(points) < 3:
        return False
    unique = {(round(x, 5), round(y, 5)) for x, y in points}
    return len(unique) >= 3


def point_in_polygon(x: float, y: float, polygon: Sequence[Point]) -> bool:
    """Ray casting. Points on an edge count as inside."""
    if not polygon or len(polygon) < 3:
        return False
    inside = False
    count = len(polygon)
    j = count - 1
    for i in range(count):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        # Edge test first so boundary points are not ambiguous.
        cross = (x - xi) * (yj - yi) - (y - yi) * (xj - xi)
        if abs(cross) < 1e-9:
            if min(xi, xj) - 1e-9 <= x <= max(xi, xj) + 1e-9 and \
               min(yi, yj) - 1e-9 <= y <= max(yi, yj) + 1e-9:
                return True
        if (yi > y) != (yj > y):
            x_intersect = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_intersect:
                inside = not inside
        j = i
    return inside


def polygon_area(points: Sequence[Point]) -> float:
    """Shoelace area in the same units as the points."""
    if not points or len(points) < 3:
        return 0.0
    total = 0.0
    count = len(points)
    for i in range(count):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % count]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


@dataclass
class Region:
    name: str
    points: list[Point] = field(default_factory=list)
    color: str = "#4DA3FF"
    enabled: bool = True

    def to_pixels(self, width: int, height: int) -> list[Point]:
        return [(x * width, y * height) for x, y in self.points]

    def contains(self, x: float, y: float, width: int, height: int) -> bool:
        if width <= 0 or height <= 0:
            return False
        return point_in_polygon(x / width, y / height, self.points)

    def area_fraction(self) -> float:
        return polygon_area(self.points)

    def is_valid(self) -> bool:
        return bool(self.name.strip()) and validate_polygon(self.points)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "points": [[round(float(x), 6), round(float(y), 6)] for x, y in self.points],
            "color": self.color,
            "enabled": bool(self.enabled),
        }

    @staticmethod
    def from_dict(data: dict) -> "Region | None":
        try:
            name = str(data.get("name", "")).strip() or "Region"
            raw_points = data.get("points", [])
            points: list[Point] = []
            for item in raw_points:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    points.append((clamp01(float(item[0])), clamp01(float(item[1]))))
            if not validate_polygon(points):
                return None
            return Region(
                name=name,
                points=points,
                color=str(data.get("color", "#4DA3FF")),
                enabled=bool(data.get("enabled", True)),
            )
        except (TypeError, ValueError):
            return None


def regions_from_config(raw: Iterable | None) -> list[Region]:
    if not raw:
        return []
    regions: list[Region] = []
    for item in raw:
        if isinstance(item, dict):
            region = Region.from_dict(item)
            if region is not None:
                regions.append(region)
    return regions


def regions_to_config(regions: Iterable[Region]) -> list[dict]:
    return [region.to_dict() for region in regions]
