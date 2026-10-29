"""Configuration package: static defaults plus a JSON-backed manager."""

from config.defaults import APP_NAME, APP_VERSION, COCO_CLASSES, DEFAULT_CONFIG
from config.settings import ConfigManager

__all__ = ["APP_NAME", "APP_VERSION", "COCO_CLASSES", "DEFAULT_CONFIG", "ConfigManager"]
