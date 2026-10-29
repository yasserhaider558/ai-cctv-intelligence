"""Logging setup with credential scrubbing.

Every log record passes through :class:`_ScrubFilter`, which masks passwords in
RTSP-style URLs. That filter is the last line of defence: modules are also
expected to log ``mask_url(url)`` rather than the raw URL.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from utils.secrets import mask_url

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


class _ScrubFilter(logging.Filter):
    """Remove embedded credentials from anything that reaches a handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        scrubbed = mask_url(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        return True


def setup_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    """Configure console + rotating file logging. Idempotent."""
    global _configured
    logger = logging.getLogger()
    if _configured:
        logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
        return logger

    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    scrub = _ScrubFilter()

    console = logging.StreamHandler(stream=sys.stderr)
    console.setFormatter(formatter)
    console.addFilter(scrub)
    logger.addHandler(console)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(scrub)
        logger.addHandler(file_handler)
    except OSError:
        logger.warning("File logging unavailable; continuing with console output only")

    # Ultralytics and urllib3 are extremely chatty at INFO level.
    logging.getLogger("ultralytics").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)

    _configured = True
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
