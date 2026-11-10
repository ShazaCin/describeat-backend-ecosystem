"""Tests for inspecting audio files."""

from __future__ import annotations

import pytest

from describeat_audio.errors import NoAudioStreamError, ProbeError
from describeat_audio.probe import has_soxr, measure_loudness, probe

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg


def test_probe_reports_the_streams_properties(stereo_flac):
    info = probe(stereo_flac)

    assert info.codec == "flac"
    assert info.sample_rate == 48000
    assert info.channels == 2
    assert info.duration_seconds == pytest.approx(3.0, abs=0.2)
    assert info.size_bytes > 0
    assert info.is_lossless is True


def test_probe_knows_a_lossy_codec_is_lossy(loud_mp3):
    assert probe(loud_mp3).is_lossless is False


def test_probe_labels_are_human_readable(stereo_flac):
    info = probe(stereo_flac)

    assert info.sample_rate_label == "48 kHz"
    assert info.channel_label == "stereo"


def test_probe_channel_label_for_mono(low_rate_mono_wav):
    assert probe(low_rate_mono_wav).channel_label == "mono"


def test_probe_rejects_a_missing_file(tmp_path):
    with pytest.raises(ProbeError) as error:
        probe(tmp_path / "nope.mp3")
    assert "not found" in str(error.value).lower()


def test_probe_rejects_a_file_that_is_not_audio(tmp_path):
    text_file = tmp_path / "notes.txt"
    text_file.write_text("This is not audio.")

    with pytest.raises(ProbeError):
        probe(text_file)


def test_probe_rejects_a_video_file_with_no_audio_stream(tmp_path):
    video = tmp_path / "silent.mkv"
    # A one-frame video track with no audio at all.
    from describeat_audio.probe import ffmpeg_path
    import subprocess

    result = subprocess.run(
        [
            ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
            "-c:v", "libx264", str(video),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("This ffmpeg build cannot encode the test video.")

    with pytest.raises(NoAudioStreamError) as error:
        probe(video)
    assert "no audio stream" in str(error.value).lower()


def test_measure_loudness_reads_a_plausible_integrated_value(loud_mp3):
    loudness = measure_loudness(loud_mp3)

    assert -60.0 < loudness.integrated_lufs < 0.0
    assert loudness.true_peak_dbtp <= 0.0
    assert loudness.loudness_range_lu >= 0.0


def test_measure_loudness_of_silence_reports_a_very_low_value(silent_mp3):
    loudness = measure_loudness(silent_mp3)

    assert loudness.integrated_lufs < -40.0


def test_describe_is_json_serialisable(stereo_flac):
    import json

    json.dumps(probe(stereo_flac).describe())


def test_has_soxr_returns_a_boolean():
    # The result depends on the ffmpeg build, but it must be a bool and the
    # service must be able to run without SoX.
    assert isinstance(has_soxr(), bool)
