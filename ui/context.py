"""Shared application context handed to every page.

Passing one object keeps page constructors short and makes the dependencies of
each page explicit instead of hiding them in module-level globals.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from analytics.analytics import AnalyticsService
from cameras.pipeline import PipelineController
from config.settings import ConfigManager
from database.db import Database
from database.repositories import EventRepository, SessionRepository


@dataclass
class AppContext:
    config: ConfigManager
    db: Database
    event_repo: EventRepository
    session_repo: SessionRepository
    analytics: AnalyticsService
    pipeline: PipelineController
    models_dir: Path
    snapshot_dir: Path
    recording_dir: Path
    notify: Callable[[str, str], None]

    # -- convenience -------------------------------------------------------
    def snapshot_setting(self) -> bool:
        return bool(self.config.get("events.save_snapshots", False))
