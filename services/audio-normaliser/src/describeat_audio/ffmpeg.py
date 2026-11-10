"""Building and running the ffmpeg commands that produce each profile.

The command construction is kept separate from the execution so that the
exact ffmpeg invocation for a profile can be asserted in tests without
running an encode, and so that the command can be shown to an operator
before it is run.

There are two commands, and the order matters:

**Stage one, prepare.** Resample to the target rate and set the target
channel count, writing a lossless intermediate. This is where the channel
conversion happens.

**Stage two, encode.** Apply the loudness correction and encode for
delivery.

The split exists because of a subtlety that is easy to get wrong.
Loudness has to be measured on the signal that will actually be encoded.
A stereo source downmixed to mono loses several decibels, so measuring the
stereo source and then encoding mono applies the wrong gain and lands the
output well below target. Measuring the *intermediate file* removes the
problem entirely: the file on disk is exactly what gets encoded, so there is
no filter chain to keep in step.

For the fingerprint profile there is no loudness correction, so stage one is
also the final result.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .errors import NormalisationError, ToolNotFoundError
from .profiles import AudioProfile
from .probe import DEFAULT_TIMEOUT_SECONDS, ffmpeg_path, has_soxr


@dataclass(frozen=True)
class Command:
    """A ready-to-run ffmpeg invocation."""

    args: tuple[str, ...]

    def as_list(self) -> list[str]:
        """Return the arguments as a list suitable for subprocess."""
        return list(self.args)

    def as_shell(self) -> str:
        """Return the arguments as a copy-pasteable shell command."""
        parts = []
        for arg in self.args:
            parts.append(f'"{arg}"' if " " in arg else arg)
        return " ".join(parts)


def _resample_filter(sample_rate: int, prefer_soxr: bool) -> str:
    """Return an ffmpeg filter that resamples to ``sample_rate``.

    SoX is preferred because its resampling artefacts are quieter and more
    broadband-free. For the fingerprint profile that matters: spurious
    broadband energy looks like extra spectral peaks, and the fingerprint is
    made of spectral peaks.
    """
    if prefer_soxr:
        return f"aresample=resampler=soxr:precision=28:out_sample_rate={sample_rate}"
    return f"aresample=out_sample_rate={sample_rate}"


def build_prepare_command(
    source: str | Path,
    destination: str | Path,
    profile: AudioProfile,
    prefer_soxr: bool = True,
) -> Command:
    """Build the command that produces the lossless intermediate.

    The intermediate is always PCM in a WAV container. It is the signal
    that stage two encodes, and the signal that loudness is measured on.

    Args:
        source: Input file.
        destination: Where to write the intermediate.
        profile: Target profile.
        prefer_soxr: Whether to use the SoX resampler if it is available.

    Returns:
        The prepared :class:`Command`.
    """
    args: list[str] = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i", str(source),
        "-af", _resample_filter(profile.sample_rate, prefer_soxr),
    ]

    # The channel count is set with the output option rather than a filter,
    # so ffmpeg performs a proper downmix for any input layout.
    if profile.channels is not None:
        args.extend(["-ac", str(profile.channels)])

    args.extend(["-ar", str(profile.sample_rate)])
    args.extend(["-c:a", "pcm_s16le"])

    if profile.bitexact:
        # Strip container metadata and encoder timestamps so that running the
        # same conversion twice produces byte-identical output. That makes
        # the pipeline idempotent and makes checksums meaningful.
        args.extend(
            ["-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact"]
        )

    args.append(str(destination))
    return Command(tuple(args))


def build_encode_command(
    source: str | Path,
    destination: str | Path,
    profile: AudioProfile,
    gain_db: float = 0.0,
    true_peak_dbtp: float | None = None,
) -> Command:
    """Build the command that encodes the intermediate for delivery.

    The loudness correction is applied as a single static gain, so the
    programme's dynamics are left alone. A dynamic normaliser rides the gain
    to keep the level on target, which pumps audibly on speech, and narration
    is speech.

    Args:
        source: The intermediate to encode.
        destination: Where to write the result.
        profile: Target profile.
        gain_db: The static gain to apply, in decibels.
        true_peak_dbtp: When given, peaks are limited to this ceiling. This
            is the safety net for material whose true peak would otherwise
            exceed the target after the gain is applied.

    Returns:
        The prepared :class:`Command`.
    """
    args: list[str] = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i", str(source),
    ]

    filters: list[str] = []

    if gain_db:
        filters.append(f"volume={gain_db:.4f}dB")

    if true_peak_dbtp is not None:
        # The limiter's limit is a linear amplitude, not a decibel value.
        limit = 10 ** (true_peak_dbtp / 20)
        filters.append(
            f"alimiter=level=disabled:limit={limit:.6f}:attack=5:release=50"
        )

    if filters:
        args.extend(["-af", ",".join(filters)])

    args.extend(["-ar", str(profile.sample_rate)])
    args.extend(["-c:a", profile.codec])

    if profile.bitrate_kbps:
        args.extend(["-b:a", f"{profile.bitrate_kbps}k"])

    args.extend(profile.encoder_args)
    args.extend(profile.container_args)
    args.append(str(destination))

    return Command(tuple(args))


def run_command(
    command: Command,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run an ffmpeg command and raise if it fails.

    Args:
        command: The command to run.
        timeout: Seconds to allow the encode to run.

    Raises:
        ToolNotFoundError: If ffmpeg is not installed.
        NormalisationError: If ffmpeg exits non-zero.
    """
    try:
        result = subprocess.run(
            command.as_list(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise NormalisationError(
            "ffmpeg timed out. The file may be longer than the timeout allows."
        ) from exc
    except FileNotFoundError as exc:
        raise ToolNotFoundError("ffmpeg was not found on PATH.") from exc
    except OSError as exc:
        raise NormalisationError(f"Could not run ffmpeg: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        reason = detail[-1] if detail else f"exit code {result.returncode}"
        raise NormalisationError(f"ffmpeg failed: {reason}")

    return result


def soxr_available() -> bool:
    """Return whether the SoX resampler is available in this ffmpeg build."""
    return has_soxr()
