"""Camera source description and (de)serialisation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from utils.secrets import build_url_with_credentials, mask_url, protect, unprotect

SOURCE_WEBCAM = "webcam"
SOURCE_FILE = "file"
SOURCE_RTSP = "rtsp"
SOURCE_HLS = "hls"
SOURCE_EARTHCAM = "earthcam"

VALID_KINDS = (SOURCE_WEBCAM, SOURCE_FILE, SOURCE_RTSP, SOURCE_HLS, SOURCE_EARTHCAM)

#: Kinds that are opened from a URL rather than a local device or file.
NETWORK_KINDS = (SOURCE_RTSP, SOURCE_HLS, SOURCE_EARTHCAM)


def detect_stream_kind(url: str) -> str:
    """Classify a pasted network URL.

    RTSP needs the FFmpeg RTSP demuxer and optional credentials; HLS is plain
    HTTP. Guessing from the scheme keeps the interface to a single URL field.
    """
    text = (url or "").strip().lower()
    if text.startswith(("rtsp://", "rtsps://")):
        return SOURCE_RTSP
    return SOURCE_HLS


@dataclass
class CameraSource:
    """A video input the user has chosen.

    ``password`` is held in plain text only in memory. Whenever the source is
    written to disk the password goes through :func:`utils.secrets.protect`,
    which uses the Windows DPAPI.
    """

    kind: str = SOURCE_FILE
    identifier: str = ""
    name: str = ""
    username: str = ""
    password: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if self.kind not in VALID_KINDS:
            raise ValueError(f"Unknown source kind: {self.kind}")
        if not self.name:
            self.name = self.default_name()

    # -- presentation ------------------------------------------------------
    def default_name(self) -> str:
        if self.kind == SOURCE_WEBCAM:
            return f"Webcam {self.identifier}"
        if self.kind == SOURCE_FILE:
            stem = Path(self.identifier).name if self.identifier else "Video file"
            return stem
        if self.kind == SOURCE_HLS:
            return _host_label(self.identifier) or "Web stream"
        if self.kind == SOURCE_EARTHCAM:
            # Imported here so this module stays usable without the provider
            # catalogue (the database layer imports CameraSource).
            from cameras.earthcam import site_for

            return site_for(self.identifier).title
        return mask_url(self.identifier) or "IP camera"

    @property
    def display_name(self) -> str:
        return self.name or self.default_name()

    @property
    def is_live(self) -> bool:
        return self.kind in (SOURCE_WEBCAM, SOURCE_RTSP, SOURCE_HLS, SOURCE_EARTHCAM)

    def safe_identifier(self) -> str:
        """Identifier suitable for logs, tables and error dialogs."""
        if self.kind in NETWORK_KINDS:
            return mask_url(self.identifier)
        return self.identifier

    def open_target(self) -> Any:
        """The value handed to ``cv2.VideoCapture``."""
        if self.kind == SOURCE_WEBCAM:
            try:
                return int(self.identifier)
            except (TypeError, ValueError):
                return 0
        if self.kind == SOURCE_RTSP:
            return build_url_with_credentials(self.identifier, self.username, self.password)
        return self.identifier

    def exists(self) -> bool:
        if self.kind == SOURCE_FILE:
            return bool(self.identifier) and Path(self.identifier).is_file()
        return True

    # -- persistence -------------------------------------------------------
    def to_config(self) -> dict:
        return {
            "kind": self.kind,
            "identifier": self.identifier,
            "name": self.name,
            "username": self.username,
            "password_token": protect(self.password) if self.password else "",
        }

    @staticmethod
    def from_config(data: dict | None) -> "CameraSource | None":
        if not isinstance(data, dict):
            return None
        kind = str(data.get("kind", "")).strip()
        if kind not in VALID_KINDS:
            return None
        identifier = str(data.get("identifier", ""))
        if not identifier:
            return None
        return CameraSource(
            kind=kind,
            identifier=identifier,
            name=str(data.get("name", "")),
            username=str(data.get("username", "")),
            password=unprotect(str(data.get("password_token", ""))),
        )


VIDEO_FILE_FILTER = (
    "Video files (*.mp4 *.avi *.mkv *.mov *.wmv *.m4v *.mpg *.mpeg *.ts *.webm);;"
    "All files (*.*)"
)


def _host_label(url: str) -> str:
    """A short readable name for a stream URL: host plus last path segment."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    host = parsed.netloc or ""
    tail = parsed.path.rstrip("/").rsplit("/", 1)[-1] if parsed.path else ""
    if tail.endswith(".m3u8"):
        tail = tail[: -len(".m3u8")]
    label = f"{host}/{tail}" if tail else host
    return label[:60]
