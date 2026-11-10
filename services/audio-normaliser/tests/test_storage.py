"""Tests for the object-storage integration.

These use a fake S3 client rather than a real one, so the tests need no
network access and no AWS credentials.
"""

from __future__ import annotations

import json

import pytest

from describeat_audio.errors import DescribeAtAudioError
from describeat_audio.storage import (
    DEFAULT_ROUTES,
    Route,
    destination_key,
    handle_s3_event,
    load_routes,
    normalise_object,
    select_route,
)

from .conftest import requires_ffmpeg


class FakeS3Client:
    """A stand-in for a boto3 S3 client that keeps objects in a dict."""

    def __init__(self, objects: dict[tuple[str, str], bytes] | None = None):
        self.objects = dict(objects or {})
        self.downloads: list[tuple[str, str]] = []
        self.uploads: list[tuple[str, str, bytes]] = []

    def download_file(self, bucket: str, key: str, destination: str) -> None:
        self.downloads.append((bucket, key))
        with open(destination, "wb") as handle:
            handle.write(self.objects[(bucket, key)])

    def upload_file(self, source: str, bucket: str, key: str, ExtraArgs=None):
        with open(source, "rb") as handle:
            payload = handle.read()
        self.uploads.append((bucket, key, payload))
        self.objects[(bucket, key)] = payload


def _event(bucket: str, key: str) -> dict:
    return {
        "Records": [
            {"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}
        ]
    }


# --- Routing -----------------------------------------------------------------


def test_default_routes_cover_both_upload_paths():
    routes = load_routes("{}")
    assert routes == []


def test_load_routes_reads_the_default_when_nothing_is_configured(monkeypatch):
    monkeypatch.delenv("DESCRIBEAT_AUDIO_ROUTES", raising=False)
    routes = load_routes()

    assert {route.prefix: route.profile_name for route in routes} == DEFAULT_ROUTES


def test_load_routes_rejects_invalid_json():
    with pytest.raises(DescribeAtAudioError) as error:
        load_routes("{not json}")
    assert "not valid JSON" in str(error.value)


def test_load_routes_rejects_an_unknown_profile():
    with pytest.raises(DescribeAtAudioError) as error:
        load_routes(json.dumps({"prefix/": "nonsense"}))
    assert "unknown profile" in str(error.value)


def test_load_routes_puts_the_most_specific_prefix_first():
    routes = load_routes(
        json.dumps({"a/": "ad-track", "a/b/": "fingerprint"})
    )
    assert routes[0].prefix == "a/b/"


def test_select_route_matches_the_longest_prefix():
    routes = load_routes(
        json.dumps({"audio/": "ad-track", "audio/special/": "fingerprint"})
    )
    route = select_route("audio/special/thing.mp3", routes)
    assert route.profile_name == "fingerprint"


def test_select_route_returns_none_for_an_unmatched_key():
    routes = load_routes(json.dumps({"audio/": "ad-track"}))
    assert select_route("posters/poster.jpg", routes) is None


def test_destination_key_swaps_the_extension():
    assert destination_key("audio-tracks-to-process/abc.mp3", _profile()) == (
        "audio-tracks-to-process/abc.wav"
    )


def test_destination_key_keeps_forward_slashes():
    """Object keys are POSIX paths, whatever the host operating system.

    On Windows, treating a key as a pathlib.Path rewrites the separators
    and the result points at a different object than the one uploaded.
    """
    key = destination_key("audio-tracks-to-process/nested/abc.mp3", _profile())
    assert "/" in key
    assert "\\" not in key
    assert key == "audio-tracks-to-process/nested/abc.wav"


def test_destination_key_handles_a_key_with_no_extension():
    assert destination_key("audio-tracks-to-process/abc", _profile()) == (
        "audio-tracks-to-process/abc.wav"
    )


def _profile():
    from describeat_audio.profiles import load_profile

    return load_profile("fingerprint")


# --- Converting stored objects ------------------------------------------------


@requires_ffmpeg
def test_normalise_object_converts_and_uploads(loud_mp3):
    client = FakeS3Client({("uploads", "audio-description-tracks-to-process/t.mp3"): loud_mp3.read_bytes()})

    report = normalise_object(
        "uploads",
        "audio-description-tracks-to-process/t.mp3",
        client,
        routes=load_routes(json.dumps({"audio-description-tracks-to-process/": "ad-track"})),
    )

    assert report is not None
    assert report.output.codec == "mp3"
    assert client.uploads[0][0] == "uploads"
    assert client.uploads[0][1] == "audio-description-tracks-to-process/t.mp3"


@requires_ffmpeg
def test_normalise_object_writes_to_a_different_bucket(loud_mp3):
    client = FakeS3Client({("uploads", "audio-description-tracks-to-process/t.mp3"): loud_mp3.read_bytes()})

    normalise_object(
        "uploads",
        "audio-description-tracks-to-process/t.mp3",
        client,
        routes=load_routes(json.dumps({"audio-description-tracks-to-process/": "ad-track"})),
        destination_bucket="processed",
    )

    assert client.uploads[0][0] == "processed"


def test_normalise_object_ignores_an_unrouted_key():
    client = FakeS3Client()

    report = normalise_object(
        "uploads",
        "posters/poster.jpg",
        client,
        routes=load_routes(json.dumps({"audio/": "ad-track"})),
    )

    assert report is None
    assert client.uploads == []


# --- The event handler --------------------------------------------------------


@requires_ffmpeg
def test_handle_s3_event_normalises_an_uploaded_object(loud_mp3):
    client = FakeS3Client({("uploads", "audio-description-tracks-to-process/t.mp3"): loud_mp3.read_bytes()})

    reports = handle_s3_event(
        _event("uploads", "audio-description-tracks-to-process/t.mp3"),
        s3_client=client,
        routes=load_routes(json.dumps({"audio-description-tracks-to-process/": "ad-track"})),
    )

    assert len(reports) == 1
    assert reports[0].profile.name == "ad-track"


@requires_ffmpeg
def test_handle_s3_event_decodes_url_encoded_keys(loud_mp3):
    client = FakeS3Client({("uploads", "audio-description-tracks-to-process/my track.mp3"): loud_mp3.read_bytes()})

    reports = handle_s3_event(
        _event("uploads", "audio-description-tracks-to-process/my+track.mp3"),
        s3_client=client,
        routes=load_routes(json.dumps({"audio-description-tracks-to-process/": "ad-track"})),
    )

    assert len(reports) == 1


def test_handle_s3_event_raises_when_an_object_fails():
    class BrokenClient(FakeS3Client):
        def download_file(self, bucket, key, destination):
            raise RuntimeError("storage is unavailable")

    with pytest.raises(DescribeAtAudioError) as error:
        handle_s3_event(
            _event("uploads", "audio-description-tracks-to-process/t.mp3"),
            s3_client=BrokenClient(),
            routes=load_routes(json.dumps({"audio-description-tracks-to-process/": "ad-track"})),
        )

    assert "storage is unavailable" in str(error.value)


def test_handle_s3_event_ignores_an_empty_event():
    assert handle_s3_event({}, s3_client=FakeS3Client()) == []
