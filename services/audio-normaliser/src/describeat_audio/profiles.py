"""Target profiles for the two kinds of audio DescribeAT ingests.

A *profile* is a complete, checkable description of what the output file
should look like. Two are defined:

``fingerprint``
    The reference audio the fingerprinting engine hashes. The engine extracts
    spectral peaks, so anything lossy erodes the very detail it depends on.
    This profile therefore produces lossless PCM at a fixed sample rate, and
    it never truncates or time-stretches the source -- the offsets it yields
    are meaningless if the timeline shifts.

``ad-track``
    The narration listeners hear. It is speech, which survives a far more
    aggressive encode, so this profile targets the *smallest* file that still
    meets the published quality floor: 128 kbps mono MP3 at 44.1 kHz, loudness
    normalised to -16 LUFS per the EBU R128 convention.

Every field in these profiles maps onto something the project documents, so
that the service can be checked against the docs rather than against taste.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import ProfileError

# --- Published quality floors ------------------------------------------------
#
# These constants are the contract. Changing one is a change to what
# DescribeAT promises listeners, not a tuning knob.

#: Integrated loudness target for AD tracks, in LUFS (EBU R128).
AD_TRACK_TARGET_LUFS = -16.0

#: True-peak ceiling for AD tracks, in dBTP. Keeps transients from clipping
#: on lossy encoders.
AD_TRACK_TARGET_TP = -1.5

#: Loudness range that should be preserved, in LU. Narrows the normalisation
#: so a single loud passage does not drag quiet speech down with it.
AD_TRACK_TARGET_LRA = 11.0

#: Lowest bitrate the project documents for narration speech.
AD_TRACK_MIN_BITRATE_KBPS = 128

#: Highest bitrate the project documents for narration speech.
AD_TRACK_MAX_BITRATE_KBPS = 192

#: Sample rate the project documents as standard for narration.
AD_TRACK_SAMPLE_RATE = 44100

#: Sample rate the project documents for reference audio, and the one the
#: fingerprinting guidance calls for ("Use at least 16kHz, ideally 44.1kHz").
FINGERPRINT_SAMPLE_RATE = 44100

#: The other documented reference rate. Offered because some capture chains
#: only produce 48 kHz and resampling down loses information.
FINGERPRINT_SAMPLE_RATE_ALT = 48000


@dataclass(frozen=True)
class AudioProfile:
    """A named, fully specified target format for one kind of audio.

    Attributes:
        name: Identifier used on the command line and in JSON reports.
        description: One-line human summary.
        codec: ffmpeg encoder name.
        extension: Output file extension, without the dot.
        container: ffmpeg muxer name.
        sample_rate: Target sample rate in Hz.
        channels: Target channel count. ``None`` preserves the source count.
        bitrate_kbps: Constant bitrate for lossy profiles.
        loudness_lufs: Integrated loudness target. ``None`` disables loudness
            processing, which is the correct default for reference audio.
        true_peak_dbtp: True-peak ceiling, only meaningful with loudness
            processing enabled.
        loudness_range_lu: Maximum loudness range to preserve.
        lossless: Whether the encode preserves the source samples exactly.
        bitexact: Whether to strip metadata and timestamps for reproducibility.
        container_args: Extra muxing arguments.
        encoder_args: Extra encoder arguments.
    """

    name: str
    description: str
    codec: str
    extension: str
    container: str
    sample_rate: int
    channels: int | None = None
    bitrate_kbps: int | None = None
    loudness_lufs: float | None = None
    true_peak_dbtp: float | None = None
    loudness_range_lu: float | None = None
    lossless: bool = True
    bitexact: bool = False
    container_args: tuple[str, ...] = field(default_factory=tuple)
    encoder_args: tuple[str, ...] = field(default_factory=tuple)

    @property
    def preserves_duration(self) -> bool:
        """Whether this profile is expected to keep the source timeline intact.

        Both current profiles do. It is recorded explicitly because a profile
        that trimmed or padded would invalidate every offset the fingerprint
        engine reports.
        """
        return True

    def describe(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary of the profile."""
        return {
            "name": self.name,
            "description": self.description,
            "codec": self.codec,
            "container": self.container,
            "extension": self.extension,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "bitrate_kbps": self.bitrate_kbps,
            "loudness_lufs": self.loudness_lufs,
            "true_peak_dbtp": self.true_peak_dbtp,
            "lossless": self.lossless,
        }


FINGERPRINT = AudioProfile(
    name="fingerprint",
    description=(
        "Reference audio for the fingerprinting engine: lossless PCM at "
        "44.1 kHz, source channels and timeline preserved."
    ),
    codec="pcm_s16le",
    extension="wav",
    container="wav",
    sample_rate=FINGERPRINT_SAMPLE_RATE,
    channels=None,
    lossless=True,
    bitexact=True,
)

AD_TRACK = AudioProfile(
    name="ad-track",
    description=(
        "Audio description narration for listeners: mono MP3 at 128 kbps, "
        "44.1 kHz, normalised to -16 LUFS."
    ),
    codec="libmp3lame",
    extension="mp3",
    container="mp3",
    sample_rate=AD_TRACK_SAMPLE_RATE,
    channels=1,
    bitrate_kbps=AD_TRACK_MIN_BITRATE_KBPS,
    loudness_lufs=AD_TRACK_TARGET_LUFS,
    true_peak_dbtp=AD_TRACK_TARGET_TP,
    loudness_range_lu=AD_TRACK_TARGET_LRA,
    lossless=False,
    bitexact=False,
)

#: All profiles, keyed by name.
PROFILES: dict[str, AudioProfile] = {
    profile.name: profile for profile in (FINGERPRINT, AD_TRACK)
}


def load_profile(name: str) -> AudioProfile:
    """Return the profile registered under ``name``.

    Raises:
        ProfileError: If no such profile exists.
    """
    try:
        return PROFILES[name]
    except KeyError:
        known = ", ".join(sorted(PROFILES))
        raise ProfileError(f"Unknown profile {name!r}. Known profiles: {known}.") from None
