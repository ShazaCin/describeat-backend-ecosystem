"""Tests for the profile definitions.

These do not need ffmpeg; they check that the profiles say what the project
documents they should say.
"""

from __future__ import annotations

import pytest

from describeat_audio.errors import ProfileError
from describeat_audio.profiles import (
    AD_TRACK_MAX_BITRATE_KBPS,
    AD_TRACK_MIN_BITRATE_KBPS,
    AD_TRACK_SAMPLE_RATE,
    AD_TRACK_TARGET_LUFS,
    AD_TRACK_TARGET_TP,
    FINGERPRINT_SAMPLE_RATE,
    PROFILES,
    load_profile,
)


def test_both_profiles_are_registered():
    assert set(PROFILES) == {"fingerprint", "ad-track"}


def test_load_profile_returns_the_registered_profile():
    assert load_profile("ad-track") is PROFILES["ad-track"]


def test_load_profile_rejects_an_unknown_name():
    with pytest.raises(ProfileError) as error:
        load_profile("nonsense")
    assert "fingerprint" in str(error.value)
    assert "ad-track" in str(error.value)


def test_fingerprint_profile_is_lossless_at_the_documented_rate():
    profile = load_profile("fingerprint")
    assert profile.lossless is True
    assert profile.sample_rate == FINGERPRINT_SAMPLE_RATE
    assert profile.sample_rate in (44100, 48000)


def test_fingerprint_profile_preserves_the_source_channel_count():
    # The fingerprinting guidance calls for stereo but accepts mono. Forcing
    # a channel count here would either lose information or invent it.
    assert load_profile("fingerprint").channels is None


def test_fingerprint_profile_applies_no_loudness_normalisation():
    # The engine normalises spectral peaks itself, so re-shaping the
    # programme's dynamics beforehand would only degrade the source.
    assert load_profile("fingerprint").loudness_lufs is None


def test_ad_track_profile_uses_the_documented_quality_floor():
    profile = load_profile("ad-track")
    assert profile.bitrate_kbps == AD_TRACK_MIN_BITRATE_KBPS
    assert AD_TRACK_MIN_BITRATE_KBPS <= profile.bitrate_kbps <= AD_TRACK_MAX_BITRATE_KBPS


def test_ad_track_profile_is_mono_mp3_at_the_standard_rate():
    profile = load_profile("ad-track")
    assert profile.channels == 1
    assert profile.codec == "libmp3lame"
    assert profile.extension == "mp3"
    assert profile.sample_rate == AD_TRACK_SAMPLE_RATE
    assert profile.lossless is False


def test_ad_track_profile_targets_the_documented_loudness():
    profile = load_profile("ad-track")
    assert profile.loudness_lufs == AD_TRACK_TARGET_LUFS
    assert profile.true_peak_dbtp == AD_TRACK_TARGET_TP


def test_every_profile_preserves_duration():
    # A profile that trimmed or padded would invalidate every offset the
    # fingerprint engine reports.
    for profile in PROFILES.values():
        assert profile.preserves_duration is True


def test_describe_is_json_serialisable():
    import json

    for profile in PROFILES.values():
        json.dumps(profile.describe())
