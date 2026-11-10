"""End-to-end tests for the normaliser.

These run real conversions against real synthesised audio and then check the
result against the profile. They are the tests that would have caught the
two bugs found while building this service: a filter chain that ffmpeg
rejects, and a failed conversion that deletes its own input.
"""

from __future__ import annotations

import json

import pytest

from describeat_audio.errors import ConformanceError, ProbeError
from describeat_audio.normalise import (
    DURATION_TOLERANCE,
    default_destination,
    normalise,
    normalise_to_temp,
)
from describeat_audio.probe import measure_loudness, probe
from describeat_audio.profiles import load_profile

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg


# --- The fingerprint profile -------------------------------------------------


def test_fingerprint_profile_converts_48k_flac_to_44k_lossless_pcm(stereo_flac, tmp_path):
    destination = tmp_path / "reference.wav"
    report = normalise(stereo_flac, destination, load_profile("fingerprint"))

    assert destination.exists()
    assert report.output.sample_rate == 44100
    assert report.output.codec == "pcm_s16le"
    assert report.output.channels == 2


def test_fingerprint_profile_keeps_the_timeline(stereo_flac, tmp_path):
    destination = tmp_path / "reference.wav"
    report = normalise(stereo_flac, destination, load_profile("fingerprint"))

    drift = abs(report.output.duration_seconds - report.source.duration_seconds)
    assert drift <= report.source.duration_seconds * DURATION_TOLERANCE + 0.05


def test_fingerprint_profile_preserves_mono_sources(low_rate_mono_wav, tmp_path):
    destination = tmp_path / "coarse.wav"
    report = normalise(low_rate_mono_wav, destination, load_profile("fingerprint"))

    assert report.output.channels == 1
    assert report.output.sample_rate == 44100


def test_fingerprint_profile_warns_that_a_lossy_source_stays_lossy(stereo_flac, tmp_path):
    # A FLAC source is lossless, so no warning about the source is expected.
    report = normalise(
        stereo_flac, tmp_path / "reference.wav", load_profile("fingerprint")
    )
    assert not any("cannot be recovered" in w for w in report.warnings)


def test_fingerprint_profile_warns_when_the_source_was_lossy(loud_mp3, tmp_path):
    report = normalise(
        loud_mp3, tmp_path / "reference.wav", load_profile("fingerprint")
    )
    assert any("cannot be recovered" in w for w in report.warnings)


def test_fingerprint_profile_is_reproducible(stereo_flac, tmp_path):
    """The same input must produce byte-identical output every time.

    Reproducibility is what makes the fingerprint hash database meaningful:
    if re-uploading a title produced different bytes, the stored hashes
    would no longer match.
    """
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"

    normalise(stereo_flac, first, load_profile("fingerprint"))
    normalise(stereo_flac, second, load_profile("fingerprint"))

    assert first.read_bytes() == second.read_bytes()


# --- The AD track profile ----------------------------------------------------


def test_ad_track_profile_produces_mono_mp3_at_the_target_bitrate(loud_mp3, tmp_path):
    destination = tmp_path / "narration.mp3"
    report = normalise(loud_mp3, destination, load_profile("ad-track"))

    assert destination.exists()
    assert report.output.codec == "mp3"
    assert report.output.channels == 1
    assert report.output.sample_rate == 44100
    assert 120_000 <= (report.output.bit_rate_bps or 0) <= 140_000


def test_ad_track_profile_normalises_quiet_material_upward(quiet_mp3, tmp_path):
    destination = tmp_path / "narration.mp3"
    report = normalise(quiet_mp3, destination, load_profile("ad-track"))

    assert report.source_loudness.integrated_lufs < -30
    assert report.output_loudness.integrated_lufs == pytest.approx(-16.0, abs=1.0)


def test_ad_track_profile_normalises_loud_material_downward(loud_mp3, tmp_path):
    destination = tmp_path / "narration.mp3"
    report = normalise(loud_mp3, destination, load_profile("ad-track"))

    assert report.output_loudness.integrated_lufs == pytest.approx(-16.0, abs=1.0)


def test_ad_track_profile_makes_the_file_smaller(loud_mp3, tmp_path):
    destination = tmp_path / "narration.mp3"
    report = normalise(loud_mp3, destination, load_profile("ad-track"))

    assert report.output.size_bytes < report.source.size_bytes
    assert report.size_saved_bytes > 0


def test_ad_track_profile_keeps_the_timeline(loud_mp3, tmp_path):
    destination = tmp_path / "narration.mp3"
    report = normalise(loud_mp3, destination, load_profile("ad-track"))

    drift = abs(report.output.duration_seconds - report.source.duration_seconds)
    assert drift <= report.source.duration_seconds * DURATION_TOLERANCE + 0.05


def test_ad_track_profile_reports_the_stereo_to_mono_conversion(loud_mp3, tmp_path):
    report = normalise(loud_mp3, tmp_path / "narration.mp3", load_profile("ad-track"))
    assert any("stereo" in w and "mono" in w for w in report.warnings)


def test_ad_track_profile_measures_the_signal_it_actually_encodes(loud_mp3, tmp_path):
    """Regression test: loudness must be measured after the downmix.

    A stereo source downmixed to mono loses several decibels. Measuring
    the stereo source and then encoding mono applies the wrong gain, and
    the output lands well below target. The service measures the
    intermediate file instead, which is exactly what gets encoded.
    """
    destination = tmp_path / "narration.mp3"
    report = normalise(loud_mp3, destination, load_profile("ad-track"))

    # The output is on target...
    assert report.output_loudness.integrated_lufs == pytest.approx(-16.0, abs=1.0)

    # ...and the gain was calculated for the mono signal, not the stereo
    # one. A mono downmix of this material measures about 3 LU quieter than
    # the stereo source, so a gain calculated from the stereo measurement
    # would be about 3 dB too small.
    stereo_measurement = measure_loudness(loud_mp3).integrated_lufs
    assert report.source_loudness.integrated_lufs < stereo_measurement


def test_ad_track_profile_applies_a_gain_close_to_the_measured_difference(loud_mp3, tmp_path):
    destination = tmp_path / "narration.mp3"
    report = normalise(loud_mp3, destination, load_profile("ad-track"))

    expected = -16.0 - report.source_loudness.integrated_lufs
    assert report.gain_applied_db == pytest.approx(expected, abs=0.01)


def test_ad_track_profile_uses_a_static_gain_not_a_dynamic_normaliser(loud_mp3, tmp_path):
    """A dynamic normaliser rides the gain and pumps audibly on speech."""
    report = normalise(loud_mp3, tmp_path / "narration.mp3", load_profile("ad-track"))

    encode_command = report.commands[-1]
    assert "volume=" in encode_command
    assert "loudnorm" not in encode_command


def test_ad_track_profile_runs_two_stages(loud_mp3, tmp_path):
    report = normalise(loud_mp3, tmp_path / "narration.mp3", load_profile("ad-track"))
    assert len(report.commands) == 2


def test_fingerprint_profile_runs_one_stage(stereo_flac, tmp_path):
    report = normalise(
        stereo_flac, tmp_path / "reference.wav", load_profile("fingerprint")
    )
    assert len(report.commands) == 1


def test_ad_track_profile_keeps_the_true_peak_under_the_ceiling(loud_mp3, tmp_path):
    report = normalise(loud_mp3, tmp_path / "narration.mp3", load_profile("ad-track"))
    assert report.output_loudness.true_peak_dbtp <= -1.5 + 0.1


def test_ad_track_profile_leaves_no_intermediate_file_behind(loud_mp3, tmp_path):
    normalise(loud_mp3, tmp_path / "narration.mp3", load_profile("ad-track"))
    leftovers = [p.name for p in tmp_path.iterdir() if "intermediate" in p.name]
    assert leftovers == []


# --- Safety of the write -----------------------------------------------------


def test_converting_a_file_onto_itself_does_not_destroy_it(loud_mp3, tmp_path):
    """Regression test: a failed conversion must never delete its input.

    The first version of this service wrote straight to the destination and
    deleted it on failure. When the destination was the same path as the
    source -- which is exactly what happens when you normalise an MP3 to
    the MP3 profile -- the cleanup removed the original file.
    """
    working_copy = tmp_path / "narration.mp3"
    working_copy.write_bytes(loud_mp3.read_bytes())
    original_bytes = working_copy.read_bytes()

    normalise(working_copy, working_copy, load_profile("ad-track"))

    assert working_copy.exists()
    assert working_copy.stat().st_size > 0
    assert working_copy.read_bytes() != original_bytes


def test_a_failed_conversion_leaves_the_destination_untouched(stereo_flac, tmp_path):
    """A destination that already holds a good file must survive a failure."""
    destination = tmp_path / "narration.mp3"
    destination.write_bytes(b"existing content")
    existing = destination.read_bytes()

    # A source that does not exist makes the conversion fail before ffmpeg
    # runs, so the destination must be left alone.
    with pytest.raises(ProbeError):
        normalise(tmp_path / "missing.mp3", destination, load_profile("ad-track"))

    assert destination.read_bytes() == existing


def test_a_failed_conversion_leaves_no_temporary_files_behind(loud_mp3, tmp_path):
    destination = tmp_path / "narration.mp3"

    with pytest.raises(Exception):
        normalise(tmp_path / "missing.mp3", destination, load_profile("ad-track"))

    leftovers = [p for p in tmp_path.iterdir() if ".describeat-" in p.name]
    assert leftovers == []


# --- Helpers -----------------------------------------------------------------


def test_default_destination_uses_the_profile_extension(loud_mp3):
    destination = default_destination(loud_mp3, load_profile("ad-track"))
    assert destination.suffix == ".mp3"


def test_default_destination_changes_the_extension_for_lossless(loud_mp3):
    destination = default_destination(loud_mp3, load_profile("fingerprint"))
    assert destination.suffix == ".wav"


def test_normalise_to_temp_returns_a_usable_file(loud_mp3):
    path, report = normalise_to_temp(loud_mp3, load_profile("ad-track"))
    try:
        assert path.exists()
        assert report.output.codec == "mp3"
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_report_describes_the_whole_operation(loud_mp3, tmp_path):
    report = normalise(loud_mp3, tmp_path / "narration.mp3", load_profile("ad-track"))
    payload = report.describe()

    json.dumps(payload)
    assert payload["profile"]["name"] == "ad-track"
    assert payload["source"]["codec"] == "mp3"
    assert payload["output"]["channels"] == 1
    assert isinstance(payload["warnings"], list)
    assert payload["size_saved_bytes"] > 0


def test_report_names_the_final_destination_not_a_temporary_file(loud_mp3, tmp_path):
    destination = tmp_path / "narration.mp3"
    report = normalise(loud_mp3, destination, load_profile("ad-track"))

    assert report.output.path == str(destination)
    assert ".describeat-" not in report.output.path
