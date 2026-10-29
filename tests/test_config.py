"""Configuration manager tests."""

from __future__ import annotations

import json

from config.defaults import DEFAULT_CONFIG
from config.settings import ConfigManager


def test_creates_file_with_defaults(tmp_path):
    path = tmp_path / "config.json"
    config = ConfigManager(path)
    assert path.is_file()
    assert config.get("detection.confidence") == DEFAULT_CONFIG["detection"]["confidence"]
    assert config.get("events.cooldown_s") == 15.0


def test_missing_key_returns_default(tmp_path):
    config = ConfigManager(tmp_path / "config.json")
    assert config.get("does.not.exist", "fallback") == "fallback"
    assert config.get("does.not.exist") is None


def test_set_persists_across_instances(tmp_path):
    path = tmp_path / "config.json"
    first = ConfigManager(path)
    first.set("detection.confidence", 0.72)
    first.set("events.regions", [{"name": "Gate", "points": [[0, 0], [1, 0], [1, 1]]}])

    second = ConfigManager(path)
    assert second.get("detection.confidence") == 0.72
    assert second.get("events.regions")[0]["name"] == "Gate"


def test_partial_file_is_merged_with_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"detection": {"confidence": 0.9}}), encoding="utf-8")

    config = ConfigManager(path)
    assert config.get("detection.confidence") == 0.9
    # Keys that were not in the file must still be present.
    assert config.get("detection.imgsz") == 640
    assert config.get("video.reconnect_attempts") == 3


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not valid json", encoding="utf-8")

    config = ConfigManager(path)
    assert config.get("detection.confidence") == DEFAULT_CONFIG["detection"]["confidence"]


def test_update_applies_multiple_values(tmp_path):
    config = ConfigManager(tmp_path / "config.json")
    config.update({"detection.confidence": 0.5, "events.person_detected": False})
    assert config.get("detection.confidence") == 0.5
    assert config.get("events.person_detected") is False


def test_reset_restores_defaults(tmp_path):
    config = ConfigManager(tmp_path / "config.json")
    config.set("detection.confidence", 0.99)
    config.reset()
    assert config.get("detection.confidence") == DEFAULT_CONFIG["detection"]["confidence"]


def test_snapshot_is_a_copy(tmp_path):
    config = ConfigManager(tmp_path / "config.json")
    snapshot = config.snapshot()
    snapshot["detection"]["confidence"] = 0.01
    assert config.get("detection.confidence") != 0.01
