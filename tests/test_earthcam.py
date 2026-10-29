"""Tests for the EarthCam catalogue, playlist rewriting and source plumbing.

Nothing here touches the network or OpenCV: the resolver is exercised through its
pure helpers, and the capture object is only imported where it is needed.
"""

from __future__ import annotations

import base64
import urllib.parse

import pytest

from cameras import earthcam
from cameras.source import SOURCE_EARTHCAM, CameraSource


def test_catalogue_is_multi_country_and_unique() -> None:
    countries = {site.country for site in earthcam.CATALOGUE}
    pages = [site.page for site in earthcam.CATALOGUE]
    assert len(earthcam.CATALOGUE) >= 5
    assert len(countries) >= 3, "the list must not be single-country"
    assert len(pages) == len(set(pages)), "duplicate camera page in the catalogue"
    assert all(page.startswith("https://www.earthcam.com/") for page in pages)


def test_every_site_has_a_readable_title() -> None:
    for site in earthcam.CATALOGUE:
        assert site.title
        assert "·" in site.title
        assert site.country and site.label


def test_site_for_exact_and_trailing_slash() -> None:
    site = earthcam.CATALOGUE[0]
    assert earthcam.site_for(site.page) is site
    assert earthcam.site_for(site.page.rstrip("/")) is site


def test_site_for_unknown_page_degrades_gracefully() -> None:
    site = earthcam.site_for("https://www.earthcam.com/somewhere/else/")
    assert site.page == "https://www.earthcam.com/somewhere/else/"
    assert site.title


def test_rewrite_playlist_points_relative_uris_at_the_relay() -> None:
    body = b"#EXTM3U\n#EXT-X-VERSION:4\nchunklist_1.m3u8?t=abc\n"
    base = "https://videos-3.earthcam.com/fecnetwork/1.flv/playlist.m3u8?t=abc"
    out = earthcam.rewrite_playlist(body, base).decode()

    lines = out.splitlines()
    assert lines[0] == "#EXTM3U"
    assert lines[1] == "#EXT-X-VERSION:4"
    assert lines[2].startswith("/segment?u=")

    token = lines[2].split("u=", 1)[1]
    target = base64.urlsafe_b64decode(token.encode()).decode()
    assert target == "https://videos-3.earthcam.com/fecnetwork/1.flv/chunklist_1.m3u8?t=abc"


def test_rewrite_playlist_handles_absolute_uris() -> None:
    body = b"#EXTM3U\nhttps://videos-3.earthcam.com/a/b.ts\n"
    out = earthcam.rewrite_playlist(body, "https://videos-3.earthcam.com/x/y.m3u8")
    assert "/segment?u=" in out.decode()


def test_rewrite_playlist_rewrites_uri_attributes() -> None:
    body = b'#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n'
    out = earthcam.rewrite_playlist(body, "https://videos-3.earthcam.com/a/b.m3u8").decode()
    line = out.splitlines()[1]
    assert line.startswith('#EXT-X-MAP:URI="/segment?u=')
    token = line.split("u=", 1)[1].rstrip('"')
    assert base64.urlsafe_b64decode(token.encode()).decode() == (
        "https://videos-3.earthcam.com/a/init.mp4"
    )


def test_rewrite_playlist_keeps_comments_and_blank_lines() -> None:
    body = b"#EXTM3U\n\n#EXT-X-ENDLIST\n"
    out = earthcam.rewrite_playlist(body, "https://videos-3.earthcam.com/a/b.m3u8")
    assert out.decode().splitlines() == ["#EXTM3U", "", "#EXT-X-ENDLIST"]


def test_relay_refuses_foreign_hosts() -> None:
    with pytest.raises(earthcam.EarthCamError):
        earthcam._fetch("https://example.com/stream.m3u8", timeout=1.0)


def test_earthcam_source_round_trips_through_config() -> None:
    site = earthcam.CATALOGUE[1]
    source = CameraSource(kind=SOURCE_EARTHCAM, identifier=site.page)
    assert source.is_live
    assert source.display_name == site.title

    restored = CameraSource.from_config(source.to_config())
    assert restored is not None
    assert restored.kind == SOURCE_EARTHCAM
    assert restored.identifier == site.page
    assert restored.display_name == site.title


def test_earthcam_identifier_is_masked_in_logs() -> None:
    source = CameraSource(kind=SOURCE_EARTHCAM, identifier="https://www.earthcam.com/x/")
    # Page URLs carry no credentials, but they are still network identifiers.
    assert "://" in source.safe_identifier()


def test_relay_path_encodes_the_target() -> None:
    path = earthcam._relay_path("https://videos-3.earthcam.com/a/b.ts?t=1&x=2")
    query = urllib.parse.urlparse(path).query
    encoded = urllib.parse.parse_qs(query)["u"][0]
    assert base64.urlsafe_b64decode(encoded.encode()).decode() == (
        "https://videos-3.earthcam.com/a/b.ts?t=1&x=2"
    )
