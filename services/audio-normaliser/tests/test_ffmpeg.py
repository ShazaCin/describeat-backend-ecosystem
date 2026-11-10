"""Tests for the ffmpeg command construction.

These check the exact command line that gets built, without running an
encode. They exist because the command line is where the subtle mistakes
live: a filter chain that looks right in a report can be rejected by ffmpeg
at run time.
"""

from __future__ import annotations

from describeat_audio.ffmpeg import (
    build_encode_command,
    build_prepare_command,
)
from describeat_audio.profiles import load_profile


def _filter_argument(command) -> str:
    """Return the value of the -af argument from a built command."""
    args = command.as_list()
    return args[args.index("-af") + 1] if "-af" in args else ""


def _argument_after(command, flag: str) -> str:
    """Return the argument that follows a flag."""
    args = command.as_list()
    return args[args.index(flag) + 1]


# --- Stage one: prepare ------------------------------------------------------


def test_prepare_command_resamples_to_the_profile_rate():
    command = build_prepare_command(
        "in.flac", "mid.wav", load_profile("fingerprint"), prefer_soxr=False
    )
    assert "out_sample_rate=44100" in _filter_argument(command)


def test_prepare_command_writes_lossless_pcm():
    command = build_prepare_command(
        "in.flac", "mid.wav", load_profile("fingerprint"), prefer_soxr=False
    )
    assert _argument_after(command, "-c:a") == "pcm_s16le"


def test_prepare_command_does_not_force_a_channel_count_for_fingerprint():
    # Forcing -ac would either discard a channel or duplicate one. The
    # fingerprint profile preserves the source channel layout.
    command = build_prepare_command(
        "in.flac", "mid.wav", load_profile("fingerprint"), prefer_soxr=False
    )
    assert "-ac" not in command.as_list()


def test_prepare_command_forces_mono_for_the_ad_track():
    command = build_prepare_command(
        "in.mp3", "mid.wav", load_profile("ad-track"), prefer_soxr=False
    )
    assert _argument_after(command, "-ac") == "1"


def test_prepare_command_is_bit_exact_for_the_fingerprint_profile():
    command = build_prepare_command(
        "in.flac", "mid.wav", load_profile("fingerprint"), prefer_soxr=False
    )
    assert "+bitexact" in command.as_shell()
    assert "-map_metadata" in command.as_list()


def test_prepare_command_uses_soxr_when_asked():
    command = build_prepare_command(
        "in.flac", "mid.wav", load_profile("fingerprint"), prefer_soxr=True
    )
    assert "resampler=soxr" in _filter_argument(command)


def test_prepare_command_falls_back_to_plain_resampling():
    command = build_prepare_command(
        "in.flac", "mid.wav", load_profile("fingerprint"), prefer_soxr=False
    )
    chain = _filter_argument(command)
    assert "resampler=soxr" not in chain
    assert "out_sample_rate=44100" in chain


# --- Stage two: encode -------------------------------------------------------


def test_encode_command_uses_the_profile_codec_and_bitrate():
    command = build_encode_command("mid.wav", "out.mp3", load_profile("ad-track"))
    assert _argument_after(command, "-c:a") == "libmp3lame"
    assert _argument_after(command, "-b:a") == "128k"


def test_encode_command_sets_the_bitrate_exactly_once():
    command = build_encode_command("mid.wav", "out.mp3", load_profile("ad-track"))
    # A repeated -b:a is harmless to ffmpeg but signals a bug in the profile
    # definition, so assert it appears exactly once.
    assert command.as_list().count("-b:a") == 1


def test_encode_command_applies_the_gain_as_a_static_volume_filter():
    command = build_encode_command(
        "mid.wav", "out.mp3", load_profile("ad-track"), gain_db=6.5
    )
    chain = _filter_argument(command)
    assert "volume=6.5000dB" in chain
    # The correction must be a static gain, not a dynamic normaliser, which
    # would pump audibly on speech.
    assert "loudnorm" not in chain


def test_encode_command_omits_the_gain_when_it_is_zero():
    command = build_encode_command("mid.wav", "out.mp3", load_profile("ad-track"))
    assert "-af" not in command.as_list()


def test_encode_command_limits_the_true_peak():
    command = build_encode_command(
        "mid.wav", "out.mp3", load_profile("ad-track"), true_peak_dbtp=-1.5
    )
    chain = _filter_argument(command)
    assert "alimiter" in chain
    # The limiter's limit is a linear amplitude, not a decibel value.
    assert "limit=0.841395" in chain
    # Auto-leveling would undo the gain the limiter is protecting.
    assert "level=disabled" in chain


def test_encode_command_joins_filters_with_commas():
    command = build_encode_command(
        "mid.wav", "out.mp3", load_profile("ad-track"),
        gain_db=3.0, true_peak_dbtp=-1.5,
    )
    chain = _filter_argument(command)
    assert chain.count(",") == 1
    assert chain.startswith("volume=")


def test_command_as_shell_quotes_arguments_containing_spaces():
    command = build_prepare_command(
        "my movie.flac", "my track.wav", load_profile("fingerprint"), prefer_soxr=False
    )
    shell = command.as_shell()
    assert '"my movie.flac"' in shell
    assert '"my track.wav"' in shell
