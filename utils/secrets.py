"""Credential handling and log sanitisation.

Camera URLs frequently embed a username and password. Two rules are enforced
throughout the application:

1. A password is never written to a log line, an error dialog or the database.
2. Stored passwords are encrypted with the Windows DPAPI where available, so a
   copied configuration file does not leak the credential to another user
   account.

DPAPI is per-user: the encrypted blob can only be decrypted by the same Windows
user on the same machine. That is exactly the right threat model for a local
surveillance workstation. If DPAPI is unavailable (non-Windows, or ctypes
failure) we fall back to base64 with an explicit marker so the UI can warn the
user that the value is only obfuscated, not encrypted.
"""

from __future__ import annotations

import base64
import re
import sys
from typing import Optional

_DPAPI_PREFIX = "dpapi:"
_PLAIN_PREFIX = "b64:"

#: ``scheme://user:password@host`` - the password group is replaced on output.
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)(?P<user>[^:/@\s]+):(?P<pw>[^@/\s]*)@")


# ---------------------------------------------------------------------------
# URL masking
# ---------------------------------------------------------------------------

def mask_url(url: str) -> str:
    """Return ``url`` with any embedded password replaced by ``***``.

    Safe to call on any string, including non-URLs.
    """
    if not url:
        return url
    return _URL_CREDENTIALS.sub(lambda m: f"{m.group('scheme')}{m.group('user')}:***@", url)


def split_url_credentials(url: str) -> tuple[str, Optional[str], Optional[str]]:
    """Split ``rtsp://user:pass@host`` into ``(url_without_credentials, user, pass)``."""
    if not url:
        return url, None, None
    match = _URL_CREDENTIALS.search(url)
    if not match:
        return url, None, None
    user = match.group("user")
    password = match.group("pw")
    clean = url[: match.start()] + f"{match.group('scheme')}" + url[match.end():]
    return clean, user, password


def build_url_with_credentials(url: str, username: str, password: str) -> str:
    """Inject credentials into a URL that has none, for OpenCV/FFmpeg use."""
    if not username:
        return url
    match = _URL_CREDENTIALS.search(url)
    if match:
        return url
    scheme_sep = url.find("://")
    if scheme_sep < 0:
        return url
    head = url[: scheme_sep + 3]
    tail = url[scheme_sep + 3:]
    if password:
        return f"{head}{username}:{password}@{tail}"
    return f"{head}{username}@{tail}"


# ---------------------------------------------------------------------------
# DPAPI (Windows)
# ---------------------------------------------------------------------------

class _DataBlob:  # pragma: no cover - platform specific
    """ctypes DATA_BLOB definition, built lazily to keep imports cheap."""

    @staticmethod
    def build(data: bytes):
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        buffer = ctypes.create_string_buffer(data, len(data))
        blob = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
        return blob, buffer, DATA_BLOB


def _dpapi_available() -> bool:
    return sys.platform == "win32"


def _dpapi_protect(data: bytes) -> Optional[bytes]:  # pragma: no cover - platform specific
    if not _dpapi_available():
        return None
    try:
        import ctypes

        in_blob, in_buffer, DATA_BLOB = _DataBlob.build(data)
        out_blob = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        ok = crypt32.CryptProtectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
        )
        _ = in_buffer
        if not ok:
            return None
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except Exception:
        return None


def _dpapi_unprotect(data: bytes) -> Optional[bytes]:  # pragma: no cover - platform specific
    if not _dpapi_available():
        return None
    try:
        import ctypes

        in_blob, in_buffer, DATA_BLOB = _DataBlob.build(data)
        out_blob = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
        )
        _ = in_buffer
        if not ok:
            return None
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def protect(plain: str) -> str:
    """Encrypt ``plain`` for storage. Returns a self-describing token."""
    if not plain:
        return ""
    raw = plain.encode("utf-8")
    encrypted = _dpapi_protect(raw)
    if encrypted is not None:
        return _DPAPI_PREFIX + base64.b64encode(encrypted).decode("ascii")
    return _PLAIN_PREFIX + base64.b64encode(raw).decode("ascii")


def unprotect(token: str) -> str:
    """Reverse :func:`protect`. Returns ``""`` when the token is unusable."""
    if not token:
        return ""
    try:
        if token.startswith(_DPAPI_PREFIX):
            blob = base64.b64decode(token[len(_DPAPI_PREFIX):].encode("ascii"))
            raw = _dpapi_unprotect(blob)
            return raw.decode("utf-8") if raw is not None else ""
        if token.startswith(_PLAIN_PREFIX):
            return base64.b64decode(token[len(_PLAIN_PREFIX):].encode("ascii")).decode("utf-8")
    except Exception:
        return ""
    return ""


def is_encrypted(token: str) -> bool:
    return bool(token) and token.startswith(_DPAPI_PREFIX)
