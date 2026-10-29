"""Application entry point.

Run with:
    python main.py

or through run.bat, which activates the virtual environment first.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_VENV_MARKER = "AI_CCTV_VENV_REEXEC"


def _relaunch_in_venv() -> int | None:
    """Hand over to the project virtual environment if started elsewhere.

    Typing ``python main.py`` in PowerShell picks up whatever interpreter is on
    PATH. That one may lack the pinned wheels entirely, or - worse - have an
    older, half-broken PyTorch that fails with a misleading C-extension error.
    The project ships its own environment, so we use it and say so.
    """
    if os.environ.get(_VENV_MARKER) == "1":
        return None

    from utils.paths import venv_python

    target_python = venv_python()
    if target_python is None:
        return None

    try:
        if Path(sys.executable).resolve() == target_python.resolve():
            return None
    except OSError:
        return None

    print("=" * 70)
    print("Starting the application inside its own virtual environment.")
    print(f"  interpreter used now : {sys.executable}")
    print(f"  restarting with      : {target_python}")
    print("=" * 70)
    print()

    environment = dict(os.environ)
    environment[_VENV_MARKER] = "1"
    try:
        completed = subprocess.run(
            [str(target_python), str(Path(__file__).resolve()), *sys.argv[1:]],
            env=environment,
        )
        return int(completed.returncode)
    except OSError as exc:
        print(f"Could not start {target_python}: {exc}", file=sys.stderr)
        return 1


def _fail(message: str, detail: str = "") -> int:
    """Report a startup failure on the console and, if possible, in a dialog."""
    text = message if not detail else f"{message}\n\n{detail}"
    print("\n" + "=" * 72, file=sys.stderr)
    print("STARTUP FAILED", file=sys.stderr)
    print(text, file=sys.stderr)
    print("=" * 72 + "\n", file=sys.stderr)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "AI CCTV Intelligence", text)
        _ = app
    except Exception:
        pass
    return 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)

    relaunched = _relaunch_in_venv()
    if relaunched is not None:
        return relaunched

    try:
        from PySide6.QtWidgets import QApplication
    except Exception as exc:
        return _fail(
            "PySide6 is not installed, so the interface cannot start.",
            "Run setup.bat, or install the dependencies manually:\n"
            "    python -m pip install -r requirements.txt\n\n"
            f"Technical detail: {exc}",
        )

    from config.defaults import APP_NAME, APP_ORGANISATION, APP_VERSION
    from config.settings import ConfigManager
    from utils.logging_setup import get_logger, setup_logging
    from utils.paths import (
        config_path,
        data_dir,
        database_path,
        ensure_runtime_dirs,
        logs_dir,
        models_dir,
        recordings_dir,
        snapshots_dir,
    )

    ensure_runtime_dirs()

    try:
        config = ConfigManager(config_path())
    except Exception as exc:
        return _fail("The configuration file could not be loaded.", str(exc))

    setup_logging(logs_dir(), str(config.get("app.log_level", "INFO")))
    log = get_logger("main")
    log.info("Starting %s %s", APP_NAME, APP_VERSION)

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORGANISATION)
    app.setApplicationVersion(APP_VERSION)

    # Only one instance may run. Two copies load two CUDA models each, and on a
    # 2 GB GPU the second one blocks inside CUDA initialisation with no error -
    # the window simply stops responding. Refusing the second copy is kinder.
    from PySide6.QtCore import QLockFile

    lock = QLockFile(str(data_dir() / "app.lock"))
    lock.setStaleLockTime(30_000)
    if not lock.tryLock(200):
        message = (
            "The application is already running.\n\n"
            "Only one copy can use the camera and the GPU at a time. "
            "Switch to the window that is already open, or close it and try again."
        )
        print(message, file=sys.stderr)
        if QApplication.platformName() != "offscreen":
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(None, APP_NAME, message)
        return 0
    try:
        app.setStyle("Fusion")
    except Exception:
        pass

    from ui import theme

    app.setStyleSheet(theme.STYLESHEET)

    def _hook(exc_type, exc_value, exc_tb) -> None:
        log.error(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_tb),
        )
        traceback.print_exception(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook

    # -- storage -----------------------------------------------------------
    from database.db import Database
    from database.repositories import EventRepository, SessionRepository

    db = Database(database_path())
    healthy, error = db.health()
    if not healthy:
        log.error("Database unavailable: %s", error)
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(
            None,
            "Database unavailable",
            "The local event database could not be opened, so event history and "
            "analytics will be unavailable this session.\n\n"
            "Live video and detection still work.\n\n"
            f"Technical detail: {error}",
        )
    else:
        try:
            SessionRepository(db).close_orphans(time.time())
        except Exception:
            pass

    event_repo = EventRepository(db)
    session_repo = SessionRepository(db)

    from analytics.analytics import AnalyticsService

    analytics = AnalyticsService(event_repo, session_repo)

    # -- pipeline ----------------------------------------------------------
    from cameras.pipeline import PipelineController

    snap_dir = snapshots_dir(str(config.get("storage.snapshot_dir", "")))
    rec_dir = recordings_dir(str(config.get("storage.recording_dir", "")))
    for folder in (snap_dir, rec_dir, models_dir()):
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("Could not create %s: %s", folder, exc)

    pipeline = PipelineController(
        config=config,
        event_repo=event_repo,
        session_repo=session_repo,
        models_dir=models_dir(),
        snapshot_dir=snap_dir,
        recording_dir=rec_dir,
    )

    # -- window ------------------------------------------------------------
    from ui.main_window import MainWindow

    window = MainWindow(
        config=config,
        db=db,
        event_repo=event_repo,
        session_repo=session_repo,
        analytics=analytics,
        pipeline=pipeline,
        models_dir=models_dir(),
        snapshot_dir=snap_dir,
        recording_dir=rec_dir,
    )
    window.show()

    log.info("Interface ready")
    exit_code = app.exec()
    log.info("Application exited with code %d", exit_code)
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
