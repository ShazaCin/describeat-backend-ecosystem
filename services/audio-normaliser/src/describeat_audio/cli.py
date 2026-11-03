"""Command-line interface for the DescribeAT audio normaliser.

Two commands:

``normalise`` converts a file into a profile and reports what happened.
``inspect`` reports what a file contains without changing it.

Both print plain text rather than a table, so the output reads sensibly
through a screen reader and pipes cleanly into a log.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .errors import DescribeAtAudioError
from .normalise import default_destination, normalise
from .profiles import PROFILES, load_profile
from .probe import measure_loudness, probe


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="describeat-audio",
        description=(
            "Normalise audio for the DescribeAT backend: calibrate reference "
            "audio to fingerprint grade, or compress narration to the "
            "minimum size that still meets the quality floor."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    normalise_parser = subparsers.add_parser(
        "normalise",
        help="Convert an audio file into a profile.",
        description="Convert an audio file into a profile and verify the result.",
    )
    normalise_parser.add_argument("source", help="The file to convert.")
    normalise_parser.add_argument(
        "-p",
        "--profile",
        required=True,
        choices=sorted(PROFILES),
        help="The target profile.",
    )
    normalise_parser.add_argument(
        "-o",
        "--output",
        help=(
            "Where to write the result. Defaults to the source name with the "
            "profile's extension."
        ),
    )
    normalise_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the report as JSON instead of text.",
    )
    normalise_parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the post-conversion verification. Not recommended.",
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Report what an audio file contains.",
        description="Report what an audio file contains, without changing it.",
    )
    inspect_parser.add_argument("source", help="The file to inspect.")
    inspect_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the report as JSON instead of text.",
    )
    inspect_parser.add_argument(
        "--loudness",
        action="store_true",
        help="Also measure EBU R128 loudness. This reads the whole file.",
    )

    profiles_parser = subparsers.add_parser(
        "profiles",
        help="List the available profiles.",
        description="List the available profiles and what they produce.",
    )
    profiles_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the profiles as JSON instead of text.",
    )

    return parser


def _format_bytes(count: int) -> str:
    """Return a byte count in human-readable form."""
    value = float(count)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "bytes":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _format_duration(seconds: float) -> str:
    """Return a duration as hours, minutes and seconds."""
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    return f"{minutes}m {secs}s"


def _print_report(report, as_json: bool) -> None:
    """Print a normalisation report."""
    if as_json:
        print(json.dumps(report.describe(), indent=2))
        return

    profile = report.profile
    source = report.source
    output = report.output

    print(f"Profile: {profile.name}")
    print(f"  {profile.description}")
    print("")
    print(f"Source: {source.path}")
    print(f"  Format: {source.format_name} ({source.codec})")
    print(f"  Sample rate: {source.sample_rate_label}")
    print(f"  Channels: {source.channel_label}")
    print(f"  Duration: {_format_duration(source.duration_seconds)}")
    print(f"  Size: {_format_bytes(source.size_bytes)}")
    print("")
    print(f"Output: {output.path}")
    print(f"  Format: {output.format_name} ({output.codec})")
    print(f"  Sample rate: {output.sample_rate_label}")
    print(f"  Channels: {output.channel_label}")
    print(f"  Duration: {_format_duration(output.duration_seconds)}")
    print(f"  Size: {_format_bytes(output.size_bytes)}")

    if report.source_loudness:
        print(f"  Loudness before: {report.source_loudness.integrated_lufs:.2f} LUFS")
    if report.output_loudness:
        print(f"  Loudness after: {report.output_loudness.integrated_lufs:.2f} LUFS")

    if report.gain_applied_db:
        print(f"  Gain applied: {report.gain_applied_db:+.2f} dB")

    saved = report.size_saved_bytes
    if saved >= 0:
        print(f"  Saved: {_format_bytes(saved)} ({report.size_saved_ratio * 100:.0f} percent smaller)")
    else:
        print(f"  Larger by: {_format_bytes(-saved)}")

    if report.warnings:
        print("")
        print("Warnings:")
        for warning in report.warnings:
            print(f"  - {warning}")

    print("")
    print("Verified against the profile.")


def _print_inspect(info, loudness, as_json: bool) -> None:
    """Print the result of inspecting a file."""
    if as_json:
        payload = {"audio": info.describe()}
        if loudness:
            payload["loudness"] = loudness.describe()
        print(json.dumps(payload, indent=2))
        return

    print(f"File: {info.path}")
    print(f"  Format: {info.format_name} ({info.codec})")
    print(f"  Sample rate: {info.sample_rate_label}")
    print(f"  Channels: {info.channel_label}")
    print(f"  Duration: {_format_duration(info.duration_seconds)}")
    print(f"  Size: {_format_bytes(info.size_bytes)}")
    if info.bit_rate_bps:
        print(f"  Bit rate: {info.bit_rate_bps // 1000} kbps")
    if loudness:
        print(f"  Loudness: {loudness.integrated_lufs:.2f} LUFS")
        print(f"  True peak: {loudness.true_peak_dbtp:.2f} dBTP")
        print(f"  Loudness range: {loudness.loudness_range_lu:.2f} LU")


def _print_profiles(as_json: bool) -> None:
    """Print the available profiles."""
    if as_json:
        print(json.dumps({name: p.describe() for name, p in PROFILES.items()}, indent=2))
        return

    for name, profile in PROFILES.items():
        print(f"{name}:")
        print(f"  {profile.description}")
        print(f"  Sample rate: {profile.sample_rate} Hz")
        print(f"  Channels: {profile.channels if profile.channels is not None else 'preserved from source'}")
        if profile.bitrate_kbps:
            print(f"  Bit rate: {profile.bitrate_kbps} kbps")
        if profile.loudness_lufs is not None:
            print(f"  Loudness target: {profile.loudness_lufs} LUFS")
        print(f"  Lossless: {'yes' if profile.lossless else 'no'}")
        print("")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface.

    Args:
        argv: Arguments to parse. Defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code: 0 on success, 1 on a handled error.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "profiles":
            _print_profiles(args.json)
            return 0

        if args.command == "inspect":
            info = probe(args.source)
            loudness = measure_loudness(args.source) if args.loudness else None
            _print_inspect(info, loudness, args.json)
            return 0

        if args.command == "normalise":
            profile = load_profile(args.profile)
            destination = (
                Path(args.output)
                if args.output
                else default_destination(args.source, profile)
            )
            report = normalise(
                args.source,
                destination,
                profile,
                verify=not args.no_verify,
            )
            _print_report(report, args.json)
            return 0

    except DescribeAtAudioError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    parser.error(f"Unknown command {args.command!r}.")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
