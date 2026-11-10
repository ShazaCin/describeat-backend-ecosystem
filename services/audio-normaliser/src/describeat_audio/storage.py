"""Normalising audio that lands in object storage.

This module turns the normaliser into something that can sit in the upload
path: an S3 event arrives, the referenced object is fetched, converted, and
written back to storage under a new key.

It is deliberately separate from the core normaliser. The core has no
knowledge of AWS, so it stays testable without a network and usable from
any other platform. This module is the thin adapter around it.

``boto3`` is imported lazily, inside the functions that need it, so the core
package can be installed and tested without the AWS SDK present.
"""

from __future__ import annotations

import json
import os
import posixpath
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .errors import DescribeAtAudioError
from .normalise import NormalisationReport, already_conforms, normalise
from .profiles import AudioProfile, load_profile
from .probe import measure_loudness, probe

#: Environment variable naming the S3 bucket that receives normalised files.
DESTINATION_BUCKET_ENV = "DESCRIBEAT_AUDIO_DESTINATION_BUCKET"

#: Environment variable holding the JSON mapping of source prefixes to
#: profiles. For example::
#:
#:     {"audio-tracks-to-process/": "fingerprint",
#:      "audio-description-tracks-to-process/": "ad-track"}
#:
#: The first matching prefix wins, so put the more specific prefixes first.
ROUTE_RULES_ENV = "DESCRIBEAT_AUDIO_ROUTES"

#: Default routing, matching the S3 layout the admin portal uploads to.
DEFAULT_ROUTES: dict[str, str] = {
    "audio-tracks-to-process/": "fingerprint",
    "audio-description-tracks-to-process/": "ad-track",
}


@dataclass(frozen=True)
class Route:
    """One rule mapping a source key prefix to a target profile."""

    prefix: str
    profile_name: str

    def matches(self, key: str) -> bool:
        """Whether this route applies to the given object key."""
        return key.startswith(self.prefix)


def load_routes(raw: str | None = None) -> list[Route]:
    """Build the routing table from configuration.

    Args:
        raw: A JSON object mapping prefixes to profile names. When omitted,
            the ``DESCRIBEAT_AUDIO_ROUTES`` environment variable is used,
            falling back to :data:`DEFAULT_ROUTES`.

    Returns:
        The routes, longest prefix first so the most specific rule wins.

    Raises:
        DescribeAtAudioError: If the configuration is not valid JSON or
            names a profile that does not exist.
    """
    if raw is None:
        raw = os.environ.get(ROUTE_RULES_ENV)

    if not raw:
        raw = json.dumps(DEFAULT_ROUTES)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DescribeAtAudioError(
            f"{ROUTE_RULES_ENV} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(parsed, dict):
        raise DescribeAtAudioError(
            f"{ROUTE_RULES_ENV} must be a JSON object mapping key prefixes to "
            f"profile names."
        )

    routes: list[Route] = []
    for prefix, profile_name in parsed.items():
        try:
            load_profile(profile_name)
        except DescribeAtAudioError as exc:
            raise DescribeAtAudioError(
                f"Route {prefix!r} names an unknown profile {profile_name!r}: {exc}"
            ) from exc
        routes.append(Route(prefix=str(prefix), profile_name=str(profile_name)))

    # Longest prefix first, so a specific rule beats a general one.
    routes.sort(key=lambda route: len(route.prefix), reverse=True)
    return routes


def select_route(key: str, routes: Iterable[Route]) -> Route | None:
    """Return the route that applies to a key, or ``None`` if none does."""
    for route in routes:
        if route.matches(key):
            return route
    return None


def destination_key(key: str, profile: AudioProfile) -> str:
    """Return the key to write the normalised file to.

    The normalised file replaces the extension but keeps the directory
    structure, so an upload at ``audio-tracks-to-process/abc.mp3`` becomes
    ``audio-tracks-to-process/abc.wav`` for the fingerprint profile.

    Object keys always use forward slashes, whatever the host operating
    system, so the key is handled as a POSIX path rather than a
    :class:`pathlib.Path`. On Windows, ``Path`` would rewrite the separators
    and produce a key that no longer points at the same object.
    """
    stem, extension = posixpath.splitext(key)
    return f"{stem}.{profile.extension}"


def _already_normalised(source_path: Path, profile: AudioProfile) -> bool:
    """Whether a downloaded file already meets its route's profile.

    This is the write-back guard. When the normaliser writes its result back
    into the bucket it read from -- the default -- that write is itself an
    upload, arrives as a new event, and matches the same route the upload
    did. Without the guard, each pass would re-run ffmpeg and upload again,
    self-feeding: lossless-to-lossless as a no-op, or worse on the lossy
    profile, a re-encode that loses a generation each round trip.

    A file is "already normalised" when it conforms to the profile: codec,
    sample rate and channel count from the probe, and -- only for the
    loudness profile -- a measured loudness already within tolerance. The
    loudness pass costs one read of the file, but it is what lets the guard
    skip with confidence instead of guessing from extensions.

    A file that cannot even be probed is *not* treated as already
    normalised: the conversion is left to run and raise its proper error.
    """
    try:
        info = probe(source_path)
    except DescribeAtAudioError:
        return False

    loudness = None
    if profile.loudness_lufs is not None:
        try:
            loudness = measure_loudness(source_path)
        except DescribeAtAudioError:
            return False

    return already_conforms(info, profile, loudness)


def normalise_object(
    bucket: str,
    key: str,
    s3_client: Any,
    routes: Sequence[Route] | None = None,
    destination_bucket: str | None = None,
    downloader: Callable[[str, str, Path], None] | None = None,
) -> NormalisationReport | None:
    """Fetch, convert and store one object.

    Args:
        bucket: The bucket the object was uploaded to.
        key: The key of the uploaded object.
        s3_client: A boto3 S3 client.
        routes: The routing table. Loaded from configuration when omitted.
        destination_bucket: Where to write the result. Defaults to the
            source bucket.
        downloader: Optional callable used to fetch the object, for testing.
            It receives ``(bucket, key, destination_path)``.

    Returns:
        The report for the conversion, or ``None`` when nothing was done:
        either no route matched the key, or the object already conforms to
        its profile (the write-back guard -- see :func:`_already_normalised`).
    """
    routes = list(routes) if routes is not None else load_routes()

    route = select_route(key, routes)
    if route is None:
        return None

    profile = load_profile(route.profile_name)
    target_bucket = destination_bucket or bucket
    target_key = destination_key(key, profile)

    with tempfile.TemporaryDirectory(prefix="describeat-audio-") as workdir:
        source_path = Path(workdir) / f"source{posixpath.splitext(key)[1]}"
        target_path = Path(workdir) / f"target.{profile.extension}"

        if downloader is not None:
            downloader(bucket, key, source_path)
        else:
            s3_client.download_file(bucket, key, str(source_path))

        # The write-back guard: an object that already conforms to its
        # profile is the output of an earlier run. Processing it again would
        # be a no-op or a generation-losing re-encode that fires the bucket
        # notification once more, so report "nothing to do" instead.
        if _already_normalised(source_path, profile):
            return None

        report = normalise(source_path, target_path, profile)

        s3_client.upload_file(
            str(target_path),
            target_bucket,
            target_key,
            ExtraArgs={"ContentType": f"audio/{profile.extension}"},
        )

    return report


def handle_s3_event(
    event: dict[str, Any],
    s3_client: Any = None,
    routes: Sequence[Route] | None = None,
    destination_bucket: str | None = None,
) -> list[NormalisationReport]:
    """Handle an S3 event notification containing one or more uploads.

    Every object in the event is normalised. A failure on one object does
    not stop the others, because a single bad upload should not block the
    rest of a batch. Failures are reported in the returned list's companion
    log and re-raised at the end so the caller can decide whether to fail
    the whole invocation.

    Args:
        event: The S3 event payload.
        s3_client: A boto3 S3 client. Created from the default session
            when omitted.
        routes: The routing table. Loaded from configuration when omitted.
        destination_bucket: Where to write results. Defaults to the source
            bucket.

    Returns:
        The reports for the objects that were converted.

    Raises:
        DescribeAtAudioError: If any object failed to convert.
    """
    if s3_client is None:
        import boto3

        s3_client = boto3.client("s3")

    reports: list[NormalisationReport] = []
    failures: list[str] = []

    for record in event.get("Records", []):
        s3_data = record.get("s3", {})
        bucket = s3_data.get("bucket", {}).get("name")
        key = s3_data.get("object", {}).get("key")
        if not bucket or not key:
            continue

        # S3 event keys are URL-encoded.
        from urllib.parse import unquote_plus

        key = unquote_plus(key)

        try:
            report = normalise_object(
                bucket, key, s3_client, routes=routes, destination_bucket=destination_bucket
            )
        except DescribeAtAudioError as exc:
            failures.append(f"s3://{bucket}/{key}: {exc}")
            continue
        except Exception as exc:  # pragma: no cover - defensive
            failures.append(f"s3://{bucket}/{key}: {exc}")
            continue

        if report is not None:
            reports.append(report)

    if failures:
        raise DescribeAtAudioError(
            "Could not normalise every object:\n" + "\n".join(failures)
        )

    return reports
