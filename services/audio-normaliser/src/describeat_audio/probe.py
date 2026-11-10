"""Inspecting audio files with ffprobe, and measuring loudness with ffmpeg.

Nothing here mutates anything. These functions answer two questions:

*What is actually in this file?* -- answered by ffprobe's machine-readable
output, parsed into :class:`AudioInfo`.

*How loud is it?* -- answered by running ffmpeg's EBU R128 filter and reading
the JSON it emits, parsed into :class:`LoudnessInfo`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import NoAudioStreamError, ProbeError, ToolNotFoundError

#: How long to let a probe or measurement run before giving up. A measurement
#: pass reads the whole file, so this scales with track length; the default
#: covers a two-hour feature comfortably.
DEFAULT_TIMEOUT_SECONDS = 900


def _require(tool: str) -> str:
    """Return the absolute path to ``tool``, or explain that it is missing."""
    path = shutil.which(tool)
    if path is None:
        raise ToolNotFoundError(
            f"{tool} was not found on PATH. Install ffmpeg (which provides both "
            f"ffmpeg and ffprobe) and make sure it is on PATH."
        )
    return path


def ffmpeg_path() -> str:
    """Return the path to the ffmpeg binary."""
    return _require("ffmpeg")


def ffprobe_path() -> str:
    """Return the path to the ffprobe binary."""
    return _require("ffprobe")


def has_soxr() -> bool:
    """Report whether this ffmpeg build can actually use the SoX resampler.

    The filter list is not proof. A build can mention ``soxr`` and still
    fail at configure time with "Requested resampling engine is
    unavailable", which kills the whole filter graph. So this runs a
    one-sample conversion through the SoX resampler and checks that it
    worked.

    When SoX is missing we fall back to ffmpeg's own resampler rather than
    failing the job.
    """
    try:
        result = subprocess.run(
            [
                ffmpeg_path(),
                "-hide_banner",
                "-nostdin",
                "-f", "lavfi",
                "-i", "sine=frequency=440:duration=0.1:sample_rate=48000",
                "-af", "aresample=resampler=soxr:precision=28:out_sample_rate=44100",
                "-f", "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


@dataclass(frozen=True)
class AudioInfo:
    """What ffprobe found in an audio file."""

    path: str
    format_name: str
    codec: str
    sample_rate: int
    channels: int
    duration_seconds: float
    size_bytes: int
    bit_rate_bps: int | None = None
    sample_fmt: str | None = None

    @property
    def is_lossless(self) -> bool:
        """Whether the source codec is lossless."""
        return self.codec in {"pcm_s16le", "pcm_s24le", "pcm_s32le", "flac", "wavpack", "alac"}

    @property
    def sample_rate_label(self) -> str:
        """The sample rate in kHz, for human-readable messages."""
        return f"{self.sample_rate / 1000:g} kHz"

    @property
    def channel_label(self) -> str:
        """The channel count in words, for human-readable messages."""
        return {1: "mono", 2: "stereo"}.get(self.channels, f"{self.channels} channels")

    def describe(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary."""
        return {
            "path": self.path,
            "format": self.format_name,
            "codec": self.codec,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "duration_seconds": round(self.duration_seconds, 3),
            "size_bytes": self.size_bytes,
            "bit_rate_bps": self.bit_rate_bps,
            "sample_fmt": self.sample_fmt,
        }


@dataclass(frozen=True)
class LoudnessInfo:
    """EBU R128 loudness measurements for a file."""

    integrated_lufs: float
    true_peak_dbtp: float
    loudness_range_lu: float
    threshold_lufs: float

    def describe(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary."""
        return {
            "integrated_lufs": round(self.integrated_lufs, 2),
            "true_peak_dbtp": round(self.true_peak_dbtp, 2),
            "loudness_range_lu": round(self.loudness_range_lu, 2),
            "threshold_lufs": round(self.threshold_lufs, 2),
        }


def _to_float(value: Any, default: float = 0.0) -> float:
    """Parse a value that ffprobe may report as a string, number, or absent."""
    if value in (None, "", "N/A"):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def probe(path: str | Path, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> AudioInfo:
    """Inspect an audio file and return what is inside it.

    Args:
        path: File to inspect.
        timeout: Seconds to allow the probe to run.

    Raises:
        ToolNotFoundError: If ffprobe is not installed.
        ProbeError: If the file cannot be read or is not audio.
        NoAudioStreamError: If the file has no audio stream.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise ProbeError(f"File not found: {file_path}")

    try:
        result = subprocess.run(
            [
                ffprobe_path(),
                "-v", "error",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"Timed out while probing {file_path}.") from exc
    except OSError as exc:
        raise ProbeError(f"Could not run ffprobe on {file_path}: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        reason = detail[-1] if detail else "unknown error"
        raise ProbeError(f"ffprobe could not read {file_path}: {reason}")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe returned unreadable output for {file_path}.") from exc

    streams = payload.get("streams") or []
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not audio_streams:
        raise NoAudioStreamError(
            f"{file_path} contains no audio stream. It cannot be normalised."
        )

    stream = audio_streams[0]
    fmt = payload.get("format") or {}

    duration = _to_float(
        stream.get("duration"),
        _to_float(fmt.get("duration"), 0.0),
    )
    size_bytes = int(_to_float(fmt.get("size"), file_path.stat().st_size))

    return AudioInfo(
        path=str(file_path),
        format_name=str(fmt.get("format_name") or "unknown"),
        codec=str(stream.get("codec_name") or "unknown"),
        sample_rate=int(_to_float(stream.get("sample_rate"), 0)),
        channels=int(_to_float(stream.get("channels"), 0)),
        duration_seconds=duration,
        size_bytes=size_bytes,
        bit_rate_bps=int(_to_float(fmt.get("bit_rate"), 0)) or None,
        sample_fmt=stream.get("sample_fmt"),
    )


# The loudnorm filter prints its measurements as a JSON object embedded in
# the log. Extract the last such object, which is the one for our run.
_LOUDNORM_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


def measure_loudness(
    path: str | Path, timeout: int = DEFAULT_TIMEOUT_SECONDS
) -> LoudnessInfo:
    """Measure a file's EBU R128 integrated loudness, true peak and range.

    Args:
        path: File to measure.
        timeout: Seconds to allow the measurement to run.

    Raises:
        ToolNotFoundError: If ffmpeg is not installed.
        ProbeError: If the measurement cannot be completed.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise ProbeError(f"File not found: {file_path}")

    try:
        result = subprocess.run(
            [
                ffmpeg_path(),
                "-hide_banner",
                "-nostdin",
                "-i", str(file_path),
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
                "-f", "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"Timed out while measuring loudness of {file_path}.") from exc
    except OSError as exc:
        raise ProbeError(f"Could not run ffmpeg on {file_path}: {exc}") from exc

    matches = _LOUDNORM_JSON.findall(result.stderr or "")
    if not matches:
        detail = (result.stderr or "").strip().splitlines()
        reason = detail[-1] if detail else "no measurement returned"
        raise ProbeError(f"Could not measure loudness of {file_path}: {reason}")

    try:
        measurements = json.loads(matches[-1])
    except json.JSONDecodeError as exc:
        raise ProbeError(f"Could not parse loudness measurement for {file_path}.") from exc

    def reading(key: str) -> float:
        raw = measurements.get(key)
        # The filter reports -inf for genuinely silent material.
        if raw in (None, "", "-inf", "inf"):
            return float("-inf") if raw == "-inf" else 0.0
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0

    return LoudnessInfo(
        integrated_lufs=reading("input_i"),
        true_peak_dbtp=reading("input_tp"),
        loudness_range_lu=reading("input_lra"),
        threshold_lufs=reading("input_thresh"),
    )
