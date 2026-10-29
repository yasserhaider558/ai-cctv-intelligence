"""EarthCam live street cameras.

EarthCam does not publish an API, but every camera page carries its player
configuration in the HTML: ``html5_streamingdomain`` and ``html5_streampath``.
Concatenated, they give a real HLS playlist with a session token, which is what
this module resolves at connect time. Tokens expire, so the page is read on every
connection rather than cached.

One wrinkle makes the difference between "works" and "403": the media host
requires a ``Referer`` header. OpenCV's FFmpeg backend ignores the header option,
so the playlist is served through a tiny loopback relay that adds the header and
rewrites the child playlists and segments back through itself. The interface
never sees the token, and the stream is still the operator's own.

The catalogue is a curated list of camera pages, grouped by country. A camera can
go offline or be moved by EarthCam at any time; when that happens the connection
fails with the page URL in the message instead of showing a stale picture.
"""

from __future__ import annotations

import base64
import http.server
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

EARTHCAM_HOME = "https://www.earthcam.com"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_DOMAIN = re.compile(r'"html5_streamingdomain"\s*:\s*"([^"]+)"')
_PATH = re.compile(r'"html5_streampath"\s*:\s*"([^"]+)"')
_URI_ATTR = re.compile(r'URI="([^"]+)"')

_ALLOWED_SUFFIX = ".earthcam.com"


class EarthCamError(RuntimeError):
    """Raised when a camera page or its stream cannot be used."""


@dataclass(frozen=True)
class EarthCamSite:
    country: str
    city: str
    label: str
    page: str

    @property
    def title(self) -> str:
        return f"{self.city} · {self.label}"


#: Curated camera pages. Every entry below was opened and decoded before being
#: listed; cameras that advertise a stream but never produce a frame (Las Vegas,
#: Nashville, San Francisco, Seattle at the time of writing) are deliberately
#: absent. See README section 6.
CATALOGUE: tuple[EarthCamSite, ...] = (
    EarthCamSite("United States", "New York", "Times Square", "https://www.earthcam.com/usa/newyork/timessquare/"),
    EarthCamSite("United States", "New Orleans", "Bourbon Street", "https://www.earthcam.com/usa/louisiana/neworleans/bourbonstreet/"),
    EarthCamSite("United States", "Chicago", "Chicago River", "https://www.earthcam.com/usa/illinois/chicago/"),
    EarthCamSite("United Kingdom", "London", "Abbey Road", "https://www.earthcam.com/world/england/london/abbeyroad/"),
    EarthCamSite("Ireland", "Dublin", "O'Connell Street", "https://www.earthcam.com/world/ireland/dublin/"),
    EarthCamSite("Netherlands", "Amsterdam", "Dam Square", "https://www.earthcam.com/world/netherlands/amsterdam/"),
    EarthCamSite("South Africa", "Cape Town", "Cape Town", "https://www.earthcam.com/world/southafrica/capetown/"),
)

SITE_BY_PAGE: dict[str, EarthCamSite] = {site.page: site for site in CATALOGUE}


def site_for(page: str) -> EarthCamSite:
    """Look up a stored page URL, tolerating a trailing slash difference."""
    site = SITE_BY_PAGE.get(page)
    if site is not None:
        return site
    for candidate in CATALOGUE:
        if candidate.page.rstrip("/") == (page or "").rstrip("/"):
            return candidate
    return EarthCamSite("EarthCam", "Live camera", "EarthCam", page)


def _unescape(value: str) -> str:
    return value.replace("\\/", "/").replace("\\u0026", "&")


def resolve_stream(page: str, timeout: float = 20.0) -> str:
    """Return the HLS playlist URL advertised by ``page``.

    The URL carries a short-lived token, so it is resolved per connection and
    never written to the configuration.
    """
    request = urllib.request.Request(
        page,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html", "Referer": EARTHCAM_HOME},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            html = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise EarthCamError(f"The camera page returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise EarthCamError(f"Could not reach the camera page: {exc.reason}") from exc
    except OSError as exc:
        raise EarthCamError(f"Could not read the camera page: {exc}") from exc

    domain = _DOMAIN.search(html)
    path = _PATH.search(html)
    if not domain or not path:
        raise EarthCamError(
            "This camera page does not advertise a video stream.\n\n"
            "EarthCam shows a still image for some locations; those cannot be "
            "played here. Pick another camera."
        )
    return _unescape(domain.group(1)).rstrip("/") + "/" + _unescape(path.group(1)).lstrip("/")


# ---------------------------------------------------------------------------
# Loopback relay: adds the Referer and keeps the playlist self-contained
# ---------------------------------------------------------------------------


def _fetch(upstream: str, timeout: float) -> tuple[bytes, str]:
    if not urllib.parse.urlparse(upstream).hostname or not urllib.parse.urlparse(upstream).hostname.endswith(_ALLOWED_SUFFIX):
        raise EarthCamError("Refusing to proxy a host outside earthcam.com.")
    request = urllib.request.Request(
        upstream,
        headers={"User-Agent": USER_AGENT, "Referer": EARTHCAM_HOME, "Accept": "*/*"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "")


def rewrite_playlist(body: bytes, base_url: str) -> bytes:
    """Point every child URI in a playlist back at the relay.

    Handles both plain URI lines and ``URI="..."`` attributes such as
    ``#EXT-X-MAP``, so fragmented streams work as well as MPEG-TS ones.
    """
    lines: list[str] = []
    for line in body.decode("utf-8", "replace").splitlines():
        if line and not line.startswith("#"):
            lines.append(_relay_path(urllib.parse.urljoin(base_url, line.strip())))
        elif 'URI="' in line:
            lines.append(
                _URI_ATTR.sub(
                    lambda match: f'URI="{_relay_path(urllib.parse.urljoin(base_url, match.group(1)))}"',
                    line,
                )
            )
        else:
            lines.append(line)
    return "\n".join(lines).encode("utf-8")


def _relay_path(absolute: str) -> str:
    token = base64.urlsafe_b64encode(absolute.encode("utf-8")).decode("ascii")
    return f"/segment?u={token}"


class _RelayHandler(http.server.BaseHTTPRequestHandler):
    upstream = ""
    timeout = 20.0
    # Keep-alive: FFmpeg requests a playlist plus a segment every couple of
    # seconds, and a fresh TCP connection for each of them adds latency for no
    # benefit. Every response below sets Content-Length, so this is safe.
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # keep the console quiet
        return

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/master.m3u8":
            target = self.upstream
        elif parsed.path == "/segment":
            encoded = urllib.parse.parse_qs(parsed.query).get("u", [""])[0]
            try:
                target = base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
            except Exception:
                self.send_error(400, "Bad segment token")
                return
        else:
            self.send_error(404)
            return

        try:
            body, content_type = _fetch(target, self.timeout)
        except Exception:
            self.send_error(502, "Upstream fetch failed")
            return

        if body[:7] == b"#EXTM3U":
            body = rewrite_playlist(body, target)
            content_type = "application/vnd.apple.mpegurl"

        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class _RelayServer(http.server.ThreadingHTTPServer):
    """Threaded relay server that ignores clients hanging up mid-response."""

    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        import sys

        error = sys.exception() if hasattr(sys, "exception") else None
        if isinstance(error, (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


class HlsRelay:
    """Serve one HLS playlist to OpenCV over 127.0.0.1 with a Referer added."""

    def __init__(self, upstream: str, timeout: float = 20.0) -> None:
        self._upstream = upstream
        self._timeout = timeout
        self._server: _RelayServer | None = None
        self._thread: threading.Thread | None = None
        self._url = ""

    @property
    def url(self) -> str:
        return self._url

    def start(self) -> str:
        handler = type(
            "_BoundRelayHandler",
            (_RelayHandler,),
            {"upstream": self._upstream, "timeout": self._timeout},
        )
        self._server = _RelayServer(("127.0.0.1", 0), handler)
        port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="earthcam-relay", daemon=True
        )
        self._thread.start()
        self._url = f"http://127.0.0.1:{port}/master.m3u8"
        return self._url

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is None:
            return
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Capture object - same surface the capture thread uses on cv2.VideoCapture
# ---------------------------------------------------------------------------


class EarthCamCapture:
    """A live HLS stream, opened through the relay.

    Frames are pulled by a small daemon reader thread rather than read on demand:
    ``cv2.VideoCapture.read()`` has no timeout, so a stalled segment would block
    the capture thread forever and the interface would sit on "Connecting…" with
    no way back. The reader keeps the newest frame in a one-slot queue and
    :meth:`read` gives up after ``read_timeout``, which the capture thread turns
    into a reconnect.
    """

    def __init__(
        self,
        page: str,
        timeout: float = 20.0,
        read_timeout: float = 15.0,
        should_stop=None,
    ) -> None:
        import queue

        import cv2

        self._page = page
        self._relay: HlsRelay | None = None
        self._capture = None
        self._queue: queue.Queue = queue.Queue(maxsize=4)
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None
        self._read_timeout = float(read_timeout)
        self._should_stop = should_stop or (lambda: False)
        self.last_error = ""

        stream = resolve_stream(page, timeout=timeout)
        relay = HlsRelay(stream, timeout=timeout)
        local_url = relay.start()
        capture = cv2.VideoCapture(local_url, cv2.CAP_FFMPEG)
        if not capture.isOpened():
            relay.stop()
            capture.release()
            raise EarthCamError(
                "The camera page offers a stream, but it did not open.\n\n"
                "The camera is probably offline, or its token was refused. "
                "Try another camera."
            )
        # Prove a frame decodes: an opened playlist can still be empty.
        ok, frame = capture.read()
        if not ok or frame is None:
            relay.stop()
            capture.release()
            raise EarthCamError(
                "The stream opened but produced no frame.\n\n"
                "The camera is most likely offline right now."
            )
        self._relay = relay
        self._capture = capture
        self._queue.put_nowait(frame)

        # HLS arrives a segment at a time, so FFmpeg hands over two seconds of
        # video in a few milliseconds. The reader thread paces delivery at the
        # stream's own frame rate; the queue only absorbs jitter.
        reported = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        self._fps = reported if 5.0 <= reported <= 60.0 else 15.0
        self._interval = 1.0 / self._fps

        self._reader = threading.Thread(
            target=self._pump, name="earthcam-reader", daemon=True
        )
        self._reader.start()

    def _pump(self) -> None:
        """Read frames and release them at the stream's own frame rate.

        HLS arrives a segment at a time: FFmpeg hands over two seconds of video
        in a few milliseconds. Releasing that burst immediately makes the capture
        thread drain it and then starve, so the pipeline ends up processing about
        one frame per segment. Pacing here spreads each burst over its real
        duration and keeps the queue small.
        """
        capture = self._capture
        next_at = 0.0
        while not self._stop.is_set() and capture is not None:
            try:
                ok, frame = capture.read()
            except Exception:
                ok, frame = False, None
            if not ok or frame is None:
                self._offer(None)
                return

            delay = next_at - time.monotonic()
            if delay > 0:
                time.sleep(min(delay, 0.25))
            next_at = max(time.monotonic(), next_at) + self._interval
            self._offer(frame)

    def _offer(self, item) -> None:
        """Keep the newest frame; drop the older one instead of blocking."""
        while True:
            try:
                self._queue.put_nowait(item)
                return
            except Exception:
                try:
                    self._queue.get_nowait()
                except Exception:
                    return

    # -- cv2.VideoCapture surface -----------------------------------------
    def isOpened(self) -> bool:  # noqa: N802
        return self._capture is not None and not self._stop.is_set()

    def read(self):
        if self._capture is None:
            return False, None

        # Wait in short slices so an interruption (disconnect) is noticed
        # immediately instead of after the full read timeout.
        deadline = time.monotonic() + self._read_timeout
        while not self._stop.is_set():
            try:
                if self._should_stop():
                    return False, None
            except Exception:
                pass
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                item = self._queue.get(timeout=min(0.2, remaining))
            except Exception:
                continue
            if item is None:
                return False, None
            return True, item

        self.last_error = "No frame arrived in time."
        return False, None

    def get(self, prop: int) -> float:
        return self._capture.get(prop) if self._capture is not None else 0.0

    def set(self, prop: int, value: float) -> bool:
        # Live streams have nothing to seek to.
        return False

    def release(self) -> None:
        # Order matters: stop the flag, close the relay so the reader's blocking
        # read fails, then drop the reference. Calling release() on the capture
        # while the reader is inside read() is not safe.
        self._stop.set()
        relay, self._relay = self._relay, None
        if relay is not None:
            relay.stop()
        self._capture = None

    # -- extras ------------------------------------------------------------
    @property
    def page(self) -> str:
        return self._page

    @property
    def site(self) -> EarthCamSite:
        return site_for(self._page)


def open_earthcam_capture(
    page: str, timeout: float = 20.0, should_stop=None
) -> tuple[EarthCamCapture | None, str]:
    """Open an EarthCam page as a live stream. Returns ``(capture, error)``."""
    if not page:
        return None, "No EarthCam camera was selected."
    try:
        return EarthCamCapture(page, timeout=timeout, should_stop=should_stop), ""
    except EarthCamError as exc:
        return None, str(exc)
    except Exception as exc:  # pragma: no cover - defensive
        return None, f"Unexpected error while opening the camera: {exc}"
