"""AWS Lambda entry point for the audio normaliser.

Configure the function with an S3 event notification on the upload bucket.
The handler normalises each uploaded object and writes the result back to
storage.

Configuration comes from environment variables:

``DESCRIBEAT_AUDIO_DESTINATION_BUCKET``
    Where to write normalised files. Defaults to the source bucket.

``DESCRIBEAT_AUDIO_ROUTES``
    A JSON object mapping source key prefixes to profile names. For
    example::

        {"audio-tracks-to-process/": "fingerprint",
         "audio-description-tracks-to-process/": "ad-track"}

    Objects whose key matches no prefix are left alone.

The function needs ``s3:GetObject`` on the source bucket and
``s3:PutObject`` on the destination bucket.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .storage import DESTINATION_BUCKET_ENV, handle_s3_event


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Normalise every audio object in an S3 event.

    Args:
        event: The S3 event payload.
        context: The Lambda context. Unused.

    Returns:
        A summary of what was converted.
    """
    destination_bucket = os.environ.get(DESTINATION_BUCKET_ENV) or None

    reports = handle_s3_event(event, destination_bucket=destination_bucket)

    summary = {
        "normalised": len(reports),
        "results": [
            {
                "profile": report.profile.name,
                "source": report.source.path,
                "output": report.output.path,
                "size_saved_bytes": report.size_saved_bytes,
                "warnings": list(report.warnings),
            }
            for report in reports
        ],
    }

    # The result is also written to the log, so it is visible in CloudWatch
    # even when the invocation is triggered by something other than the
    # console.
    print(json.dumps(summary, indent=2))

    return summary
