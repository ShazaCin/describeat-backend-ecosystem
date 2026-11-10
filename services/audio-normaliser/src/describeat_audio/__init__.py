"""Audio normalisation for the DescribeAT backend.

DescribeAT ingests two very different kinds of audio, and they need opposite
treatment:

``fingerprint``
    The *reference audio* -- the original film or series soundtrack that the
    fingerprinting engine hashes. Lossy compression destroys spectral detail,
    so this profile re-encodes to lossless PCM and resamples to a known rate.
    Match rate against a listener's microphone recording depends on it.

``ad-track``
    The *audio description narration* that listeners actually hear. Speech
    survives a far more aggressive encode, so this profile compresses to the
    smallest size that still meets the published quality floor.

The public API is small on purpose::

    from describeat_audio import normalise, load_profile

    profile = load_profile("ad-track")
    report = normalise("narration.wav", "narration.mp3", profile)
    print(report.output.integrated_lufs)
"""

from __future__ import annotations

from .errors import (
    ConformanceError,
    DescribeAtAudioError,
    NoAudioStreamError,
    NormalisationError,
    ProfileError,
    ProbeError,
    ToolNotFoundError,
)
from .normalise import NormalisationReport, normalise
from .profiles import PROFILES, AudioProfile, load_profile
from .probe import AudioInfo, LoudnessInfo, measure_loudness, probe

__version__ = "0.1.0"

__all__ = [
    "AudioInfo",
    "AudioProfile",
    "ConformanceError",
    "DescribeAtAudioError",
    "LoudnessInfo",
    "NoAudioStreamError",
    "NormalisationError",
    "NormalisationReport",
    "PROFILES",
    "ProfileError",
    "ProbeError",
    "ToolNotFoundError",
    "__version__",
    "load_profile",
    "measure_loudness",
    "normalise",
    "probe",
]
