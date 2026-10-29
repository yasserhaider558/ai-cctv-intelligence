"""RTSP / HTTP camera connection helpers.

OpenCV's FFmpeg backend is used directly. We force TCP transport because UDP
RTSP frequently fails on Windows firewalls and corporate networks, and we set an
open timeout so a dead address cannot freeze the application.
"""

from __future__ import annotations

import os
import socket
import time
from urllib.parse import urlparse

import cv2

from utils.logging_setup import get_logger
from utils.secrets import build_url_with_credentials, mask_url, split_url_credentials

log = get_logger(__name__)

# Applied before any capture is created. Both option spellings are supplied
# because the accepted name differs between FFmpeg versions; unknown keys are
# ignored by the FFmpeg demuxer.
_FFMPEG_OPTIONS = "rtsp_transport;tcp|stimeout;8000000|timeout;8000000"
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", _FFMPEG_OPTIONS)


def _apply_timeouts(capture: cv2.VideoCapture, timeout_ms: int) -> None:
    for prop_name in ("CAP_PROP_OPEN_TIMEOUT_MSEC", "CAP_PROP_READ_TIMEOUT_MSEC"):
        prop = getattr(cv2, prop_name, None)
        if prop is None:
            continue
        try:
            capture.set(prop, float(timeout_ms))
        except Exception:
            pass


def _tcp_reachable(host: str, port: int, timeout: float = 2.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def diagnose_failure(url: str, username: str = "") -> str:
    """Turn an opaque OpenCV failure into actionable guidance."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme in ("https", "rtsps") else 554)
    lines = [
        f"Could not open {mask_url(url)}",
        "",
        "Checks, in order:",
        f"  1. Is the camera reachable? Try pinging {host or 'the camera'} and "
        f"confirm TCP port {port} is open.",
        "  2. Does the stream require a username and password? Fill both fields; "
        "they are injected into the URL and never written to the log.",
        "  3. Is the stream path correct? Typical values are /stream1, "
        "/Streaming/Channels/101 or /h264.",
        "  4. Many cameras allow only one RTSP client. Close other viewers "
        "(VLC, the camera web page) and retry.",
    ]
    if host and not _tcp_reachable(host, int(port)):
        lines.insert(0, f"No TCP connection to {host}:{port} could be established.")
    elif username:
        lines.insert(0, f"{host}:{port} answered, but the stream was refused - "
                        "the credentials or the stream path are probably wrong.")
    return "\n".join(lines)


def test_stream(
    url: str,
    username: str = "",
    password: str = "",
    timeout_s: float = 10.0,
) -> tuple[bool, str, dict]:
    """Open the stream, read one frame, close it. Returns (ok, message, info)."""
    clean, url_user, url_password = split_url_credentials(url)
    user = username or url_user or ""
    secret = password or url_password or ""
    target = build_url_with_credentials(clean, user, secret)

    log.info("Testing stream %s", mask_url(target))
    capture = None
    started = time.perf_counter()
    try:
        capture = cv2.VideoCapture(target, cv2.CAP_FFMPEG)
        if not capture.isOpened():
            return False, diagnose_failure(target, user), {}
        _apply_timeouts(capture, int(timeout_s * 1000))
        ok, frame = capture.read()
        if not ok or frame is None:
            return False, diagnose_failure(target, user), {}
        height, width = frame.shape[:2]
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        elapsed = time.perf_counter() - started
        info = {"width": width, "height": height, "fps": fps, "open_ms": elapsed * 1000.0}
        return True, (
            f"Stream is live: {width}x{height}"
            + (f" at {fps:.0f} fps" if fps > 0 else "")
            + f" (opened in {elapsed * 1000:.0f} ms)."
        ), info
    except Exception as exc:
        log.warning("RTSP test raised: %s", exc)
        return False, diagnose_failure(target, user) + f"\n\nTechnical detail: {exc}", {}
    finally:
        if capture is not None:
            try:
                capture.release()
            except Exception:
                pass


def open_stream(url: str, username: str = "", password: str = "") -> cv2.VideoCapture | None:
    clean, url_user, url_password = split_url_credentials(url)
    user = username or url_user or ""
    secret = password or url_password or ""
    target = build_url_with_credentials(clean, user, secret)
    log.info("Opening stream %s", mask_url(target))
    try:
        capture = cv2.VideoCapture(target, cv2.CAP_FFMPEG)
        if capture is None or not capture.isOpened():
            if capture is not None:
                capture.release()
            return None
        _apply_timeouts(capture, 10000)
        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return capture
    except Exception as exc:
        log.warning("Opening stream failed: %s", exc)
        return None
