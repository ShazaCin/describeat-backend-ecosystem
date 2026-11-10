"""Shared fixtures for the audio normaliser tests.

The tests need real audio files, so the fixtures here synthesise them with
ffmpeg rather than checking binaries into the repository. That keeps the
repository small and means the fixtures are exactly what the encoder will
produce.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from describeat_audio.probe import ffmpeg_path, ffprobe_path

#: Marks a test that needs the ffmpeg and ffprobe binaries.
requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required for this test",
)


def _synthesise(path, *, sample_rate, channels, duration, codec, gain_db=None):
    """Create a test audio file using ffmpeg's synthetic sources.

    The gain is applied inside the filter graph rather than with a separate
    ``-af``, because ffmpeg refuses to combine a simple filter with a
    complex one on the same stream.
    """
    args = [
        ffmpeg_path(),
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration}:sample_rate={sample_rate}",
    ]

    if channels == 2:
        args += [
            "-f", "lavfi",
            "-i", f"sine=frequency=660:duration={duration}:sample_rate={sample_rate}",
        ]

    volume = f"volume={gain_db}dB" if gain_db is not None else "anull"

    if channels == 2:
        graph = (
            f"[0:a]{volume}[a0];"
            f"[1:a]{volume}[a1];"
            "[a0][a1]join=inputs=2:channel_layout=stereo[a]"
        )
        args += ["-filter_complex", graph, "-map", "[a]"]
    else:
        graph = f"[0:a]{volume}[a]"
        args += ["-filter_complex", graph, "-map", "[a]"]

    args += ["-ac", str(channels)]

    if codec == "libmp3lame":
        args += ["-b:a", "192k"]

    args += ["-c:a", codec, str(path)]

    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not synthesise {path}: {result.stderr.strip()}"
        )
    return path


@pytest.fixture
def stereo_flac(tmp_path):
    """A lossless 48 kHz stereo file -- the wrong rate for the fingerprint profile."""
    return _synthesise(
        tmp_path / "reference.flac",
        sample_rate=48000,
        channels=2,
        duration=3,
        codec="flac",
    )


@pytest.fixture
def right_rate_flac(tmp_path):
    """A lossless 44.1 kHz stereo FLAC -- the right rate, but still an input.

    The project documentation accepts FLAC as reference audio, and the
    fingerprint profile writes 16-bit PCM. A FLAC at the right rate is
    therefore a legitimate upload that still has to be converted.
    """
    return _synthesise(
        tmp_path / "reference-44k.flac",
        sample_rate=44100,
        channels=2,
        duration=3,
        codec="flac",
    )


@pytest.fixture
def low_rate_mono_wav(tmp_path):
    """A 22.05 kHz mono WAV -- too coarse for the fingerprint profile."""
    return _synthesise(
        tmp_path / "coarse.wav",
        sample_rate=22050,
        channels=1,
        duration=3,
        codec="pcm_s16le",
    )


@pytest.fixture
def loud_mp3(tmp_path):
    """A loud stereo MP3, for testing loudness normalisation downward."""
    return _synthesise(
        tmp_path / "loud.mp3",
        sample_rate=44100,
        channels=2,
        duration=3,
        codec="libmp3lame",
        gain_db=6,
    )


@pytest.fixture
def quiet_mp3(tmp_path):
    """A quiet stereo MP3, for testing loudness normalisation upward."""
    return _synthesise(
        tmp_path / "quiet.mp3",
        sample_rate=44100,
        channels=2,
        duration=3,
        codec="libmp3lame",
        gain_db=-20,
    )


@pytest.fixture
def digital_silence_wav(tmp_path):
    """A file whose samples are all zero, for the truly unmeasurable case.

    A very quiet signal (the ``silent_mp3`` fixture) still measures as a
    very low loudness. Genuine digital silence is what makes loudnorm
    report ``-inf``, which is the case the normaliser has to refuse in
    plain words.
    """
    path = tmp_path / "silence.wav"
    args = [
        ffmpeg_path(),
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=mono",
        "-t", "2",
        "-c:a", "pcm_s16le",
        str(path),
    ]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Could not synthesise {path}: {result.stderr.strip()}")
    return path


@pytest.fixture
def mono_quiet_mp3(tmp_path):
    """A mono 44.1 kHz MP3 that is far below the -16 LUFS target.

    Structurally it already looks like the AD-track profile's output; only
    the measured loudness disqualifies it. That is the file on which the
    guard's decision must rest on the measurement, not on the format.
    """
    return _synthesise(
        tmp_path / "mono-quiet.mp3",
        sample_rate=44100,
        channels=1,
        duration=3,
        codec="libmp3lame",
        gain_db=-24,
    )


@pytest.fixture
def silent_mp3(tmp_path):
    """A silent MP3, for testing the edge case of unmeasurable loudness."""
    return _synthesise(
        tmp_path / "silent.mp3",
        sample_rate=44100,
        channels=1,
        duration=2,
        codec="libmp3lame",
        gain_db=-70,
    )
