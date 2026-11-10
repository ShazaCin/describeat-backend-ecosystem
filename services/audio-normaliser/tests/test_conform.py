"""Tests for :func:`already_conforms`, the decision behind the write-back guard.

The structural cases run on hand-built probe results, so they need no
ffmpeg and run anywhere. The real-file cases below them run actual
conversions and mark themselves for ffmpeg individually.
"""

from __future__ import annotations

import pytest

from describeat_audio.errors import NormalisationError
from describeat_audio.normalise import already_conforms, normalise
from describeat_audio.probe import AudioInfo, LoudnessInfo, measure_loudness, probe
from describeat_audio.profiles import AD_TRACK, FINGERPRINT, load_profile

from .conftest import requires_ffmpeg


def _info(
    codec: str = "pcm_s16le",
    sample_rate: int = 44100,
    channels: int = 2,
    stream_bit_rate_bps: int | None = None,
) -> AudioInfo:
    return AudioInfo(
        path="x",
        format_name="wav",
        codec=codec,
        sample_rate=sample_rate,
        channels=channels,
        duration_seconds=3.0,
        size_bytes=1000,
        stream_bit_rate_bps=stream_bit_rate_bps,
    )


def _mp3_info(stream_bit_rate_bps: int | None) -> AudioInfo:
    """An AD-track-shaped probe result: mono MP3 at 44.1 kHz."""
    return _info(
        codec="mp3",
        sample_rate=44100,
        channels=1,
        stream_bit_rate_bps=stream_bit_rate_bps,
    )


def _loudness(lufs: float = -16.0) -> LoudnessInfo:
    return LoudnessInfo(
        integrated_lufs=lufs,
        true_peak_dbtp=-3.0,
        loudness_range_lu=4.0,
        threshold_lufs=-26.0,
    )


# --- The fingerprint profile: structure is enough ------------------------------


def test_a_44k_lossless_file_conforms_to_the_fingerprint_profile():
    assert already_conforms(_info(), FINGERPRINT)


def test_a_lossy_codec_does_not_conform_to_the_fingerprint_profile():
    assert not already_conforms(_info(codec="mp3"), FINGERPRINT)


def test_a_coarse_sample_rate_does_not_conform():
    assert not already_conforms(_info(sample_rate=22050), FINGERPRINT)


def test_a_lossless_codec_other_than_the_profiles_own_does_not_conform():
    """A lossless file is not the same thing as a *finished* file.

    The fingerprint profile writes 16-bit PCM. A 24-bit WAV or a FLAC at
    the right rate is a legitimate upload that still needs converting, so
    the guard must not mistake it for the service's own output.
    """
    assert not already_conforms(_info(codec="pcm_s24le"), FINGERPRINT)
    assert not already_conforms(_info(codec="pcm_s32le"), FINGERPRINT)
    assert not already_conforms(_info(codec="flac"), FINGERPRINT)


# --- The AD-track profile: the measurement is part of the decision -------------


def test_a_structural_match_alone_is_not_enough_for_the_loudness_profile():
    assert not already_conforms(_mp3_info(128_000), AD_TRACK)


def test_a_structural_match_on_target_conforms():
    assert already_conforms(_mp3_info(128_000), AD_TRACK, _loudness(-16.0))


def test_a_structural_match_off_target_does_not_conform():
    assert not already_conforms(_mp3_info(128_000), AD_TRACK, _loudness(-35.0))


def test_an_unmeasurable_loudness_does_not_conform():
    assert not already_conforms(_mp3_info(128_000), AD_TRACK, _loudness(float("-inf")))


def test_the_tolerated_deviation_is_the_documented_one():
    """One LU over or under target still conforms; two does not."""
    assert already_conforms(_mp3_info(128_000), AD_TRACK, _loudness(-16.9))
    assert already_conforms(_mp3_info(128_000), AD_TRACK, _loudness(-15.1))
    assert not already_conforms(_mp3_info(128_000), AD_TRACK, _loudness(-17.2))
    assert not already_conforms(_mp3_info(128_000), AD_TRACK, _loudness(-14.8))


# --- The AD-track profile: the bitrate is part of the decision ----------------


def test_the_profile_bitrate_conforms():
    """The service writes 128 kbps, and that is what the guard looks for."""
    assert already_conforms(_mp3_info(128_000), AD_TRACK, _loudness(-16.0))


def test_a_higher_bitrate_does_not_conform():
    """A file encoded at a different bitrate still has to be converted.

    The documentation accepts 128-192 kbps for narration, and a track
    arriving at 192 kbps with the right rate, channels and loudness is a
    perfectly ordinary upload. Treating it as already normalised means it
    is never delivered at all.
    """
    assert not already_conforms(_mp3_info(192_000), AD_TRACK, _loudness(-16.0))
    assert not already_conforms(_mp3_info(320_000), AD_TRACK, _loudness(-16.0))


def test_a_lower_bitrate_does_not_conform():
    assert not already_conforms(_mp3_info(64_000), AD_TRACK, _loudness(-16.0))


def test_a_variable_bitrate_file_does_not_conform():
    """A VBR encode reports a different figure, so it is not our output."""
    assert not already_conforms(_mp3_info(38_375), AD_TRACK, _loudness(-16.0))


def test_an_unmeasurable_bitrate_does_not_conform():
    """A file whose stream bitrate cannot be read is never assumed finished."""
    assert not already_conforms(_mp3_info(None), AD_TRACK, _loudness(-16.0))


def test_the_tolerated_bitrate_deviation_is_the_documented_one():
    """The encoder's rounding is absorbed; a real step up is not."""
    assert already_conforms(_mp3_info(128_000 + 1_500), AD_TRACK, _loudness(-16.0))
    assert already_conforms(_mp3_info(128_000 - 1_500), AD_TRACK, _loudness(-16.0))
    assert not already_conforms(_mp3_info(128_000 + 4_000), AD_TRACK, _loudness(-16.0))
    assert not already_conforms(_mp3_info(128_000 - 4_000), AD_TRACK, _loudness(-16.0))


# --- Real files ----------------------------------------------------------------


@requires_ffmpeg
def test_the_fingerprint_output_reports_as_conforming(stereo_flac, tmp_path):
    destination = tmp_path / "reference.wav"
    profile = load_profile("fingerprint")
    normalise(stereo_flac, destination, profile)

    assert not already_conforms(probe(stereo_flac), profile)
    assert already_conforms(probe(destination), profile)


@requires_ffmpeg
def test_the_ad_track_output_only_conforms_once_measured(quiet_mp3, tmp_path):
    destination = tmp_path / "ad.mp3"
    profile = load_profile("ad-track")
    normalise(quiet_mp3, destination, profile)

    on_target = probe(destination)
    assert not already_conforms(on_target, profile)
    assert already_conforms(on_target, profile, measure_loudness(destination))


@requires_ffmpeg
def test_a_structurally_matching_but_quiet_file_still_needs_processing(mono_quiet_mp3):
    profile = load_profile("ad-track")
    structured = probe(mono_quiet_mp3)

    # No measurement supplied: never treated as done.
    assert not already_conforms(structured, profile)
    # Measured: far off target, so genuinely not done either.
    assert not already_conforms(structured, profile, measure_loudness(mono_quiet_mp3))


@requires_ffmpeg
def test_a_silent_file_stops_with_a_plain_message(digital_silence_wav, tmp_path):
    destination = tmp_path / "out.mp3"

    with pytest.raises(NormalisationError) as error:
        normalise(digital_silence_wav, destination, load_profile("ad-track"))

    assert "silent" in str(error.value).lower()
    assert not destination.exists()
