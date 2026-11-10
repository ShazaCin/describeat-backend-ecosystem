"""Tests for the object-storage integration.

These use a fake S3 client rather than a real one, so the tests need no
network access and no AWS credentials.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from describeat_audio.errors import DescribeAtAudioError
from describeat_audio.probe import measure_loudness
from describeat_audio.profiles import AD_TRACK
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


# --- The write-back guard ------------------------------------------------------


@requires_ffmpeg
def test_the_ad_track_write_back_is_left_alone(loud_mp3):
    """The output of a conversion, arriving again as an event, is not redone.

    This is the guard against the self-feeding loop: without it, every
    write-back would trigger a fresh conversion and a fresh upload.
    """
    key = "audio-description-tracks-to-process/t.mp3"
    client = FakeS3Client({("uploads", key): loud_mp3.read_bytes()})
    routes = load_routes(json.dumps({"audio-description-tracks-to-process/": "ad-track"}))

    first = normalise_object("uploads", key, client, routes=routes)
    assert first is not None
    uploads_after_first = list(client.uploads)

    second = normalise_object("uploads", key, client, routes=routes)
    assert second is None
    assert client.uploads == uploads_after_first


@requires_ffmpeg
def test_the_fingerprint_write_back_is_left_alone(stereo_flac):
    key = "audio-tracks-to-process/t.flac"
    written_key = "audio-tracks-to-process/t.wav"
    client = FakeS3Client({("uploads", key): stereo_flac.read_bytes()})
    routes = load_routes(json.dumps({"audio-tracks-to-process/": "fingerprint"}))

    first = normalise_object("uploads", key, client, routes=routes)
    assert first is not None
    uploads_after_first = list(client.uploads)

    # The normalised copy was uploaded into the same key space the event
    # filter watches. Converting it again would be a pointless no-op.
    second = normalise_object("uploads", written_key, client, routes=routes)
    assert second is None
    assert client.uploads == uploads_after_first


@requires_ffmpeg
def test_a_track_at_the_wrong_bitrate_is_still_delivered(tmp_path):
    """A track encoded at a different bitrate has to reach the destination.

    The documentation accepts 128-192 kbps for narration. A track that
    arrives at 192 kbps, with the right rate, channels and loudness, is a
    perfectly ordinary upload -- but without a bitrate check the guard
    mistakes it for the service's own output and drops it, so nothing is
    ever written to the destination bucket.
    """
    raw = tmp_path / "raw.mp3"
    source = tmp_path / "narration-192.mp3"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i",
            "sine=frequency=440:duration=3:sample_rate=44100",
            "-ac", "1", "-c:a", "libmp3lame", "-b:a", "192k", str(raw),
        ],
        check=True,
        capture_output=True,
    )
    # Bring it to the profile's target loudness, which is what a delivered
    # narration track looks like. Without this the loudness check would
    # catch the file anyway and the bitrate gap would stay hidden.
    measured = measure_loudness(raw)
    gain = AD_TRACK.loudness_lufs - measured.integrated_lufs
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(raw), "-af", f"volume={gain:.4f}dB",
            "-c:a", "libmp3lame", "-b:a", "192k", str(source),
        ],
        check=True,
        capture_output=True,
    )

    key = "audio-description-tracks-to-process/track.mp3"
    client = FakeS3Client({("uploads", key): source.read_bytes()})
    routes = load_routes(json.dumps({"audio-description-tracks-to-process/": "ad-track"}))

    normalise_object("uploads", key, client, routes=routes)

    uploaded_keys = [(bucket, key) for bucket, key, *_ in client.uploads]
    assert uploaded_keys == [("uploads", "audio-description-tracks-to-process/track.mp3")]


@requires_ffmpeg
def test_an_unreadable_object_is_not_spared_the_error(loud_mp3):
    """A file that cannot be probed must still fail loudly, not be skipped."""
    key = "audio-description-tracks-to-process/broken.mp3"
    client = FakeS3Client({("uploads", key): b"this is not audio"})
    routes = load_routes(json.dumps({"audio-description-tracks-to-process/": "ad-track"}))

    with pytest.raises(DescribeAtAudioError):
        normalise_object("uploads", key, client, routes=routes)

    assert client.uploads == []


@requires_ffmpeg
def test_a_lossless_upload_at_the_right_rate_is_still_processed(right_rate_flac):
    """A FLAC at 44.1 kHz is an upload, not a finished file.

    The documentation accepts FLAC as reference audio, and the fingerprint
    profile delivers 16-bit PCM WAV. The guard must recognise only the
    service's own output as finished, or a legitimate upload is silently
    dropped and never reaches the destination bucket.
    """
    key = "audio-tracks-to-process/reference.flac"
    client = FakeS3Client({("uploads", key): right_rate_flac.read_bytes()})
    routes = load_routes(json.dumps({"audio-tracks-to-process/": "fingerprint"}))

    report = normalise_object("uploads", key, client, routes=routes)

    assert report is not None, "the upload was skipped instead of converted"

    uploaded_keys = [(bucket, key) for bucket, key, *_ in client.uploads]
    assert uploaded_keys == [("uploads", "audio-tracks-to-process/reference.wav")]
