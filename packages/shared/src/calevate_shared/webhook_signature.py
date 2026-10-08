"""HMAC-SHA256 webhook signatures of the form `sha256=<hex digest of the raw body>`.

Shared because two deployables check the same scheme: the voice-runtime receiver, which may
not import an engine adapter (hard rule 3), and the adapter's own `verify_webhook`. One
implementation, so the two cannot disagree about what a valid delivery is.

Standard library only: the receiver's import surface is measured against the 500 ms ack.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Final

SHA256_PREFIX: Final = "sha256="


def sha256_signature(body: bytes, secret: str) -> str:
    """The header value a sender holding `secret` would put on `body`."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"{SHA256_PREFIX}{digest}"


def sha256_signature_matches(body: bytes, header: str | None, secret: str | None) -> bool:
    """Does `header` sign exactly these bytes under `secret`? False for anything missing.

    The comparison is constant-time over the whole header string, prefix included, so a
    header that differs only in its prefix is refused rather than normalised. The body must
    be the bytes as received: re-serialising parsed JSON changes them and fails every check.
    """
    if not header or not secret:
        return False
    expected = sha256_signature(body, secret)
    return hmac.compare_digest(expected.encode(), header.strip().encode())


def timestamped_sha256_signature(body: bytes, secret: str, *, signed_at: str) -> str:
    """`sha256=<hex HMAC of "<signed_at>.<body>">`: a signature that also covers WHEN.

    The scheme ThinnestAI's `x-thinnest-signature-v2` uses with `x-thinnest-delivered-at`
    (`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/webhooks.md:105`),
    and Stripe's before it. Signing the time is what lets a receiver reject a stale replay
    without a stranger being able to restamp it.
    """
    return sha256_signature(signed_at.encode() + b"." + body, secret)


def timestamped_sha256_signature_matches(
    body: bytes, header: str | None, secret: str | None, *, signed_at: str | None
) -> bool:
    """Does `header` sign `<signed_at>.<body>` under `secret`? False for anything missing."""
    if not signed_at:
        return False
    return sha256_signature_matches(signed_at.encode() + b"." + body, header, secret)


def signed_time_is_fresh(signed_at: str | None, *, now: datetime, tolerance: timedelta) -> bool:
    """Is an ISO 8601 instant within `tolerance` of `now`, either way?

    Absent, unparsable or zone-less is NOT fresh: the time is part of what was signed, so a
    value we cannot read is not a value we may wave through.
    """
    if not signed_at:
        return False
    try:
        at = datetime.fromisoformat(signed_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if at.tzinfo is None:
        return False
    return abs(now - at) <= tolerance


__all__ = [
    "SHA256_PREFIX",
    "sha256_signature",
    "sha256_signature_matches",
    "signed_time_is_fresh",
    "timestamped_sha256_signature",
    "timestamped_sha256_signature_matches",
]
