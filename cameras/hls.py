"""HLS (``.m3u8``) playlist handling.

HLS travels over plain HTTP, so unlike RTSP it needs no credential handling of
its own. The catch is that a playlist can open successfully while containing no
playable segment, so every open is validated by decoding an actual frame.
"""

from __future__ import annotations

import time

import cv2

from utils.logging_setup import get_logger

log = get_logger(__name__)

_READ_ATTEMPTS = 3


def _looks_like_url(url: str) -> bool:
    return url.lower().startswith(("http://", "https://"))


def open_hls(url: str) -> cv2.VideoCapture | None:
    """Open an HLS playlist and return it only once a frame decodes."""
    if not _looks_like_url(url):
        return None
    try:
        capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    except Exception as exc:  # pragma: no cover - backend dependent
        log.warning("HLS open raised: %s", exc)
        return None
    if not capture.isOpened():
        capture.release()
        return None
    for _ in range(_READ_ATTEMPTS):
        try:
            ok, frame = capture.read()
        except Exception:
            ok, frame = False, None
        if ok and frame is not None:
            return capture
    capture.release()
    return None


def test_hls(url: str) -> tuple[bool, str, dict]:
    """Open the playlist, decode one frame, and describe what was found."""
    started = time.perf_counter()
    if not _looks_like_url(url):
        return False, "An HLS URL must start with http:// or https://.", {}
    if ".m3u8" not in url.lower():
        log.info("HLS URL does not contain '.m3u8'; trying it anyway")

    try:
        capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    except Exception as exc:
        return False, f"OpenCV could not open this playlist.\n\n{exc}", {}

    try:
        if not capture.isOpened():
            return False, _failure_help(url), {}

        ok, frame = False, None
        for _ in range(_READ_ATTEMPTS):
            ok, frame = capture.read()
            if ok and frame is not None:
                break
        if not ok or frame is None:
            return False, _failure_help(url), {}

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or frame.shape[1])
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or frame.shape[0])
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        message = (
            "The playlist opened and decoded a frame.\n\n"
            f"Resolution: {width} x {height}\n"
            f"Reported frame rate: {fps:.1f} fps\n"
            f"Time to first frame: {elapsed_ms:.0f} ms\n\n"
            "This proves the stream is reachable right now. Live playlists expire "
            "and some services rotate their access tokens."
        )
        return True, message, {
            "width": width,
            "height": height,
            "fps": fps,
            "open_ms": round(elapsed_ms),
        }
    finally:
        capture.release()


def _failure_help(url: str) -> str:
    return (
        "The HLS playlist could not be opened, or it contained no playable "
        "frame.\n\n"
        f"URL: {url}\n\n"
        "Checks:\n"
        "  1. Open the URL in a browser. If it downloads a .m3u8 file, the "
        "stream is fine and FFmpeg should be able to read it.\n"
        "  2. If the browser shows a player but the raw URL fails, the service "
        "is protecting the stream (signed token, referer check, DRM) and it "
        "will not play here.\n"
        "  3. Live playlists expire - a URL copied an hour ago may be dead.\n"
        "  4. Corporate networks often block the segment requests even when the "
        "playlist itself loads.\n\n"
        "Only connect streams you are permitted to access."
    )
