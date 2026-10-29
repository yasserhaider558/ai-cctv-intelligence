"""Filesystem layout helpers.

All runtime artefacts (database, logs, snapshots, recordings, downloaded model
weights) live under the project directory so the application is fully portable:
copy the folder to another machine and it still works.
"""

from __future__ import annotations

from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent

#: Where the Python environment lives. It sits on D: because the system drive is
#: nearly full and a CUDA build of PyTorch needs several gigabytes. setup.bat
#: creates it there and falls back to a local .venv when D: is unavailable.
EXTERNAL_VENV_DIR: Path = Path("D:/ai-cctv-env")


def venv_python() -> Path | None:
    """Return the interpreter of the project environment, if one exists."""
    for candidate in (
        EXTERNAL_VENV_DIR / "Scripts" / "python.exe",
        ROOT / ".venv" / "Scripts" / "python.exe",
    ):
        if candidate.is_file():
            return candidate
    return None


def project_root() -> Path:
    return ROOT


def config_path() -> Path:
    return ROOT / "config" / "config.json"


def data_dir() -> Path:
    return ROOT / "data"


def logs_dir() -> Path:
    return data_dir() / "logs"


def models_dir() -> Path:
    return ROOT / "models"


def database_path() -> Path:
    return data_dir() / "cctv.db"


def assets_dir() -> Path:
    return ROOT / "assets"


def resolve_path(value: str | Path, fallback: Path) -> Path:
    """Resolve a possibly-relative configured path against the project root."""
    if not value:
        return fallback
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate


def snapshots_dir(configured: str = "") -> Path:
    return resolve_path(configured, data_dir() / "snapshots")


def recordings_dir(configured: str = "") -> Path:
    return resolve_path(configured, data_dir() / "recordings")


def ensure_runtime_dirs() -> None:
    for path in (data_dir(), logs_dir(), models_dir(), assets_dir(),
                 data_dir() / "snapshots", data_dir() / "recordings"):
        path.mkdir(parents=True, exist_ok=True)
