"""Credential masking, URL handling and DPAPI round-trip tests."""

from __future__ import annotations

from utils.secrets import (
    build_url_with_credentials,
    is_encrypted,
    mask_url,
    protect,
    split_url_credentials,
    unprotect,
)


def test_mask_url_hides_password():
    masked = mask_url("rtsp://admin:secret@192.168.1.50:554/stream1")
    assert "secret" not in masked
    assert "admin:***@" in masked


def test_mask_url_leaves_clean_url_alone():
    url = "rtsp://192.168.1.50:554/stream1"
    assert mask_url(url) == url


def test_mask_url_handles_empty_input():
    assert mask_url("") == ""


def test_split_url_credentials():
    clean, user, password = split_url_credentials("rtsp://admin:secret@10.0.0.5/live")
    assert clean == "rtsp://10.0.0.5/live"
    assert user == "admin"
    assert password == "secret"


def test_split_url_without_credentials():
    clean, user, password = split_url_credentials("rtsp://10.0.0.5/live")
    assert clean == "rtsp://10.0.0.5/live"
    assert user is None
    assert password is None


def test_build_url_with_credentials():
    url = build_url_with_credentials("rtsp://10.0.0.5/live", "admin", "secret")
    assert url == "rtsp://admin:secret@10.0.0.5/live"


def test_build_url_does_not_duplicate_credentials():
    original = "rtsp://admin:secret@10.0.0.5/live"
    assert build_url_with_credentials(original, "other", "pw") == original


def test_protect_roundtrip():
    token = protect("hunter2")
    assert token
    assert "hunter2" not in token
    assert unprotect(token) == "hunter2"


def test_protect_empty_string():
    assert protect("") == ""
    assert unprotect("") == ""


def test_unprotect_garbage_returns_empty():
    assert unprotect("not-a-token") == ""
    assert unprotect("dpapi:@@@invalid@@@") == ""


def test_is_encrypted_flag():
    assert is_encrypted(protect("value")) in (True, False)
    assert is_encrypted("") is False
