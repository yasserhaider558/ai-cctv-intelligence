"""Region geometry tests."""

from __future__ import annotations

import pytest

from events.regions import (
    Region,
    point_in_polygon,
    polygon_area,
    regions_from_config,
    regions_to_config,
    validate_polygon,
)

SQUARE = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
TRIANGLE = [(0.2, 0.2), (0.8, 0.2), (0.5, 0.8)]


def test_point_inside_square():
    assert point_in_polygon(0.5, 0.5, SQUARE)


def test_point_outside_square():
    assert not point_in_polygon(1.5, 0.5, SQUARE)
    assert not point_in_polygon(0.5, -0.2, SQUARE)


def test_point_on_edge_counts_as_inside():
    assert point_in_polygon(0.0, 0.5, SQUARE)
    assert point_in_polygon(1.0, 1.0, SQUARE)


def test_point_inside_triangle():
    assert point_in_polygon(0.5, 0.4, TRIANGLE)
    assert not point_in_polygon(0.25, 0.7, TRIANGLE)


def test_degenerate_polygon_is_not_inside():
    assert not point_in_polygon(0.5, 0.5, [])
    assert not point_in_polygon(0.5, 0.5, [(0, 0), (1, 1)])


def test_validate_polygon():
    assert validate_polygon(SQUARE)
    assert not validate_polygon([(0, 0), (1, 1)])
    assert not validate_polygon([(0.5, 0.5), (0.5, 0.5), (0.5, 0.5)])


def test_polygon_area():
    assert polygon_area(SQUARE) == pytest.approx(1.0)
    assert polygon_area(TRIANGLE) == pytest.approx(0.18)
    assert polygon_area([]) == 0.0


def test_region_contains_uses_normalised_coordinates():
    region = Region(name="Gate", points=SQUARE)
    assert region.contains(640, 360, 1280, 720)
    assert not region.contains(-10, 360, 1280, 720)


def test_region_to_pixels():
    region = Region(name="Gate", points=[(0.5, 0.5), (1.0, 1.0), (0.5, 1.0)])
    pixels = region.to_pixels(1000, 500)
    assert pixels[0] == (500.0, 250.0)


def test_region_roundtrip():
    region = Region(name="Driveway", points=TRIANGLE, color="#FF0000", enabled=False)
    restored = Region.from_dict(region.to_dict())
    assert restored is not None
    assert restored.name == "Driveway"
    assert restored.color == "#FF0000"
    assert restored.enabled is False
    assert len(restored.points) == 3


def test_region_from_invalid_dict_returns_none():
    assert Region.from_dict({"name": "bad", "points": [[0, 0]]}) is None
    assert Region.from_dict({"name": "bad", "points": "nope"}) is None


def test_config_conversion_skips_invalid_entries():
    raw = [
        {"name": "A", "points": [[0, 0], [1, 0], [1, 1]]},
        {"name": "B", "points": [[0, 0]]},
        "garbage",
    ]
    regions = regions_from_config(raw)
    assert len(regions) == 1
    assert regions[0].name == "A"
    assert len(regions_to_config(regions)) == 1
