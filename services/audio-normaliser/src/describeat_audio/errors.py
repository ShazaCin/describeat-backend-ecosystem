"""Exception hierarchy for the DescribeAT audio normaliser.

Every error raised by this package derives from :class:`DescribeAtAudioError`,
so a caller embedding the library can catch one type and be sure it did not
come from an unrelated bug.
"""

from __future__ import annotations


class DescribeAtAudioError(Exception):
    """Base class for all errors raised by this package."""


class ToolNotFoundError(DescribeAtAudioError):
    """ffmpeg or ffprobe is not installed, or not on PATH."""


class ProbeError(DescribeAtAudioError):
    """The input file could not be inspected."""


class NoAudioStreamError(ProbeError):
    """The input file is valid but contains no audio stream."""


class NormalisationError(DescribeAtAudioError):
    """ffmpeg could not produce the requested output."""


class ConformanceError(NormalisationError):
    """ffmpeg produced output that does not match the requested profile.

    This is deliberately distinct from a plain ffmpeg failure: it means the
    encode "succeeded" but the result is not usable (wrong sample rate, wrong
    channel count, wrong duration). Failing loudly here is the whole point of
    the service -- a silently wrong fingerprint source is worse than a failed
    upload.
    """


class ProfileError(DescribeAtAudioError):
    """An unknown or malformed profile was requested."""
