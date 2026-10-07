"""HMAC-SHA256 webhook signatures of the form `sha256=<hex digest of the raw body>`.

Shared because two deployables check the same scheme: the voice-runtime receiver, which may
not import an engine adapter (hard rule 3), and the adapter's own `verify_webhook`. One
implementation, so the two cannot disagree about what a valid delivery is.

Standard library only: the receiver's import surface is measured against the 500 ms ack.
"""

from __future__ import annotations

import hashlib
import hmac
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


__all__ = ["SHA256_PREFIX", "sha256_signature", "sha256_signature_matches"]
