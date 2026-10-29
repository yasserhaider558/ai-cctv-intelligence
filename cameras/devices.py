"""Webcam enumeration.

Probing a device index means actually opening it, which takes a few hundred
milliseconds per index. Callers therefore run :func:`enumerate_webcams` on a
worker thread and keep the interface responsive.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import cv2

from utils.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class WebcamDevice:
    index: int
    width: int = 0
    height: int = 0

    @property
    def label(self) -> str:
        if self.width and self.height:
            return f"Camera {self.index} ({self.width}x{self.height})"
        return f"Camera {self.index}"


def _silence_opencv() -> None:
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:
        pass


def preferred_backend() -> int:
    """DirectShow avoids the slow MSMF enumeration on Windows."""
    if sys.platform == "win32":
        return cv2.CAP_DSHOW
    return cv2.CAP_ANY


def enumerate_webcams(max_index: int = 5) -> list[WebcamDevice]:
    """Return the webcams that can actually be opened."""
    _silence_opencv()
    backend = preferred_backend()
    devices: list[WebcamDevice] = []
    for index in range(max_index):
        capture = None
        try:
            capture = cv2.VideoCapture(index, backend)
            if capture is None or not capture.isOpened():
                continue
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            devices.append(WebcamDevice(index=index, width=width, height=height))
        except Exception as exc:  # pragma: no cover - driver dependent
            log.debug("Webcam probe %d failed: %s", index, exc)
        finally:
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    pass
    log.info("Webcam scan found %d device(s)", len(devices))
    return devices


def open_webcam(index: int, width: int = 0, height: int = 0) -> cv2.VideoCapture | None:
    """Open a webcam, preferring DirectShow on Windows."""
    _silence_opencv()
    backends = [preferred_backend()]
    if sys.platform == "win32":
        backends.append(cv2.CAP_MSMF)
    for backend in backends:
        capture = None
        try:
            capture = cv2.VideoCapture(int(index), backend)
            if capture is None or not capture.isOpened():
                if capture is not None:
                    capture.release()
                continue
            if width:
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
            if height:
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
            # Keep only the newest frame in the driver queue to cut latency.
            try:
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            return capture
        except Exception as exc:  # pragma: no cover - driver dependent
            log.debug("Opening webcam %s with backend %s failed: %s", index, backend, exc)
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    pass
    return None
