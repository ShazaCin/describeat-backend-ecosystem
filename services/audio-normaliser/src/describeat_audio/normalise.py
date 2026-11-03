"""Turning an uploaded file into a file that matches a profile.

The entry point is :func:`normalise`. It probes the source, runs the
conversion, then *verifies* the result against the profile and fails loudly
if the output does not conform.

That verification step is the important one. Without it, a conversion that
half-worked -- right container, wrong sample rate; right duration, wrong
channel count -- would be stored as the reference audio and quietly produce
fingerprints that never match. A loud failure at upload time is far cheaper
than a catalogue full of unmatched titles.

The conversion runs in one or two stages, depending on the profile:

* A profile with a loudness target is converted in two stages. The first
  stage resamples and sets the channel count into a lossless intermediate.
  The second stage measures that intermediate, applies the loudness
  correction as a single static gain, and encodes for delivery.

  The split matters. Loudness has to be measured on the signal that will
  actually be encoded, and a stereo source downmixed to mono loses several
  decibels. Measuring the source and then encoding mono applies the wrong
  gain and lands the output several decibels below target. Measuring the
  intermediate file removes the problem: the file on disk is exactly what
  gets encoded.

* A profile with no loudness target is converted in a single stage, because
  there is nothing to measure.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConformanceError, NormalisationError, ProbeError
from .ffmpeg import (
    build_encode_command,
    build_prepare_command,
    run_command,
    soxr_available,
)
from .probe import AudioInfo, LoudnessInfo, measure_loudness, probe
from .profiles import AudioProfile

#: How far the output duration may differ from the source, as a fraction.
#: 0.1% of a two-hour film is about seven seconds; anything beyond that
#: suggests the timeline shifted and the fingerprint offsets would be wrong.
DURATION_TOLERANCE = 0.001

#: How far the measured loudness may land from the target, in LU.
LOUDNESS_TOLERANCE_LU = 1.0


@dataclass(frozen=True)
class NormalisationReport:
    """What the service did, and what the result looks like.

    Attributes:
        profile: The profile that was applied.
        source: Properties of the input file.
        output: Properties of the output file.
        source_loudness: Loudness measured on the input, if measured.
        output_loudness: Loudness measured on the output, if measured.
        gain_applied_db: The static loudness gain that was applied.
        commands: The ffmpeg commands that were run, in order.
        warnings: Non-fatal observations worth surfacing to the operator.
    """

    profile: AudioProfile
    source: AudioInfo
    output: AudioInfo
    source_loudness: LoudnessInfo | None
    output_loudness: LoudnessInfo | None
    gain_applied_db: float
    commands: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def size_saved_bytes(self) -> int:
        """Bytes removed by the conversion. May be negative for upsampling."""
        return self.source.size_bytes - self.output.size_bytes

    @property
    def size_saved_ratio(self) -> float:
        """Fraction of the original size removed, between -1 and 1."""
        if self.source.size_bytes <= 0:
            return 0.0
        return self.size_saved_bytes / self.source.size_bytes

    def describe(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary of the whole operation."""
        return {
            "profile": self.profile.describe(),
            "source": self.source.describe(),
            "output": self.output.describe(),
            "source_loudness": self.source_loudness.describe() if self.source_loudness else None,
            "output_loudness": self.output_loudness.describe() if self.output_loudness else None,
            "gain_applied_db": round(self.gain_applied_db, 2),
            "commands": list(self.commands),
            "warnings": list(self.warnings),
            "size_saved_bytes": self.size_saved_bytes,
            "size_saved_ratio": round(self.size_saved_ratio, 4),
        }


def _check_conformance(
    profile: AudioProfile,
    source: AudioInfo,
    output: AudioInfo,
    output_loudness: LoudnessInfo | None,
) -> list[str]:
    """Verify the output against the profile, raising on any hard failure.

    Returns:
        A list of non-fatal warnings.

    Raises:
        ConformanceError: If the output violates the profile.
    """
    warnings: list[str] = []

    if output.sample_rate != profile.sample_rate:
        raise ConformanceError(
            f"Output sample rate is {output.sample_rate} Hz but the "
            f"{profile.name!r} profile requires {profile.sample_rate} Hz."
        )

    if profile.channels is not None and output.channels != profile.channels:
        raise ConformanceError(
            f"Output has {output.channels} channels but the {profile.name!r} "
            f"profile requires {profile.channels}."
        )

    if profile.channels is None and output.channels != source.channels:
        raise ConformanceError(
            f"Output has {output.channels} channels but the source had "
            f"{source.channels}. The {profile.name!r} profile preserves the "
            f"source channel layout."
        )

    if profile.lossless and output.codec not in {"pcm_s16le", "pcm_s24le", "pcm_s32le", "flac"}:
        raise ConformanceError(
            f"Output codec is {output.codec!r} but the {profile.name!r} "
            f"profile requires a lossless encode."
        )

    if not profile.lossless and output.codec != "mp3":
        raise ConformanceError(
            f"Output codec is {output.codec!r} but the {profile.name!r} "
            f"profile requires mp3."
        )

    if profile.preserves_duration and source.duration_seconds > 0:
        drift = abs(output.duration_seconds - source.duration_seconds)
        allowed = max(source.duration_seconds * DURATION_TOLERANCE, 0.05)
        if drift > allowed:
            raise ConformanceError(
                f"Output duration is {output.duration_seconds:.3f}s but the "
                f"source was {source.duration_seconds:.3f}s, a drift of "
                f"{drift:.3f}s. The timeline must be preserved or the "
                f"fingerprint offsets will be wrong."
            )

    if profile.loudness_lufs is not None and output_loudness is not None:
        deviation = abs(output_loudness.integrated_lufs - profile.loudness_lufs)
        if deviation > LOUDNESS_TOLERANCE_LU:
            raise ConformanceError(
                f"Output loudness is {output_loudness.integrated_lufs:.2f} LUFS "
                f"but the {profile.name!r} profile targets "
                f"{profile.loudness_lufs:.2f} LUFS."
            )

    # Soft observations. These are not failures, but an operator should know.
    if profile.lossless and not source.is_lossless:
        warnings.append(
            f"The source was {source.codec}, which is lossy. Lossy input "
            f"cannot be recovered by a lossless output, so the fingerprint "
            f"quality is limited by the source file, not by this conversion."
        )

    if profile.loudness_lufs is None:
        warnings.append(
            "No loudness normalisation was applied. The fingerprinting engine "
            "normalises spectral peaks itself, so leaving the programme "
            "dynamics alone is the correct choice for reference audio."
        )

    if source.sample_rate != profile.sample_rate:
        warnings.append(
            f"The source was {source.sample_rate_label} and was resampled to "
            f"{profile.sample_rate / 1000:g} kHz."
        )

    if profile.channels is not None and source.channels != profile.channels:
        warnings.append(
            f"The source was {source.channel_label} and was converted to "
            f"{output.channel_label}."
        )

    if output.size_bytes > source.size_bytes:
        warnings.append(
            f"The output is larger than the source "
            f"({output.size_bytes} bytes against {source.size_bytes} bytes). "
            f"For reference audio that is expected: lossless PCM is bigger "
            f"than the compressed source it replaced."
        )

    return warnings


def normalise(
    source: str | Path,
    destination: str | Path,
    profile: AudioProfile,
    verify: bool = True,
    measure_output_loudness: bool = True,
) -> NormalisationReport:
    """Convert an audio file into the given profile and verify the result.

    The conversion is written to a temporary file alongside the destination
    and moved into place only once it has been verified. That has two
    consequences worth knowing about:

    * A failed conversion never leaves a half-written file where a complete
      one is expected, and never destroys the file that was already there.
    * Converting a file onto itself is safe. The source is read in full
      before the result replaces it, so the original is not lost.

    Args:
        source: The file to convert.
        destination: Where to write the converted file.
        profile: The target profile.
        verify: Whether to check the output against the profile afterwards.
            Leave this on outside of tests.
        measure_output_loudness: Whether to measure the output's loudness for
            the report. Only meaningful for profiles with a loudness target.

    Returns:
        A :class:`NormalisationReport` describing what happened.

    Raises:
        ProbeError: If the source cannot be read.
        NormalisationError: If ffmpeg fails.
        ConformanceError: If the output does not match the profile.
    """
    source_path = Path(source)
    destination_path = Path(destination)

    source_info = probe(source_path)

    warnings: list[str] = []
    commands: list[str] = []

    destination_path.parent.mkdir(parents=True, exist_ok=True)

    # Encode to a sibling temporary file. Keeping it in the same directory
    # means the final move is a rename within one filesystem, which is
    # effectively atomic.
    handle, temporary_name = tempfile.mkstemp(
        dir=str(destination_path.parent),
        prefix=f".{destination_path.stem}.describeat-",
        suffix=f".{profile.extension}",
    )
    os.close(handle)
    temporary_path = Path(temporary_name)

    source_loudness: LoudnessInfo | None = None
    output_loudness: LoudnessInfo | None = None
    gain_applied_db = 0.0

    try:
        if profile.loudness_lufs is None:
            # No loudness target: one stage, straight to the final format.
            command = build_prepare_command(
                source_path,
                temporary_path,
                profile,
                prefer_soxr=soxr_available(),
            )
            run_command(command)
            commands.append(command.as_shell())
        else:
            # Stage one: resample and set the channel count into a
            # lossless intermediate. This is the signal that gets measured
            # and, in stage two, encoded.
            intermediate_path = temporary_path.with_suffix(".intermediate.wav")
            try:
                prepare = build_prepare_command(
                    source_path,
                    intermediate_path,
                    profile,
                    prefer_soxr=soxr_available(),
                )
                run_command(prepare)
                commands.append(prepare.as_shell())

                # Measure the intermediate, not the source. The intermediate
                # is what actually gets encoded, so this is the signal the
                # gain has to be calculated for.
                intermediate_loudness = measure_loudness(intermediate_path)
                source_loudness = intermediate_loudness

                gain_applied_db = (
                    profile.loudness_lufs - intermediate_loudness.integrated_lufs
                )

                # Stage two: apply the correction as one static gain and
                # encode for delivery.
                encode = build_encode_command(
                    intermediate_path,
                    temporary_path,
                    profile,
                    gain_db=gain_applied_db,
                    true_peak_dbtp=profile.true_peak_dbtp,
                )
                run_command(encode)
                commands.append(encode.as_shell())
            finally:
                intermediate_path.unlink(missing_ok=True)

        if not temporary_path.exists():
            raise NormalisationError(
                f"ffmpeg reported success but no output file was written to "
                f"{destination_path}."
            )

        output_info = probe(temporary_path)

        if measure_output_loudness and profile.loudness_lufs is not None:
            output_loudness = measure_loudness(temporary_path)

        if verify:
            warnings.extend(
                _check_conformance(profile, source_info, output_info, output_loudness)
            )

        os.replace(temporary_path, destination_path)
    except BaseException:
        # Remove only the temporary file. The destination and the source are
        # never touched here, so a failure can never destroy existing audio.
        temporary_path.unlink(missing_ok=True)
        raise

    # The probe ran against the temporary file, so report the path the
    # listener will actually see.
    output_info = AudioInfo(
        path=str(destination_path),
        format_name=output_info.format_name,
        codec=output_info.codec,
        sample_rate=output_info.sample_rate,
        channels=output_info.channels,
        duration_seconds=output_info.duration_seconds,
        size_bytes=output_info.size_bytes,
        bit_rate_bps=output_info.bit_rate_bps,
        sample_fmt=output_info.sample_fmt,
    )

    return NormalisationReport(
        profile=profile,
        source=source_info,
        output=output_info,
        source_loudness=source_loudness,
        output_loudness=output_loudness,
        gain_applied_db=gain_applied_db,
        commands=tuple(commands),
        warnings=tuple(warnings),
    )


def normalise_to_temp(
    source: str | Path,
    profile: AudioProfile,
    suffix: str | None = None,
    **kwargs: Any,
) -> tuple[Path, NormalisationReport]:
    """Convert a file into a temporary directory and return the result.

    Useful when the caller wants to upload the converted file somewhere
    before committing to a final location.

    Args:
        source: The file to convert.
        profile: The target profile.
        suffix: Extension for the temporary file. Defaults to the profile's.
        **kwargs: Passed through to :func:`normalise`.

    Returns:
        The path to the converted file and the report.
    """
    extension = suffix if suffix is not None else profile.extension
    temp_dir = Path(tempfile.mkdtemp(prefix="describeat-audio-"))
    destination = temp_dir / f"{Path(source).stem}.{extension}"
    report = normalise(source, destination, profile, **kwargs)
    return destination, report


def default_destination(source: str | Path, profile: AudioProfile) -> Path:
    """Return the conventional output path for a source file and profile."""
    source_path = Path(source)
    return source_path.with_suffix(f".{profile.extension}")
