"""Sealed tokens for carrier URLs that must carry data the reader cannot look up.

Two URLs need this, and both would otherwise print a phone number in an access log (hard
rule 6):

* the live-transfer URL, whose `<Dial>` document voice-runtime serves without touching the
  database (hard rule 3), so the destination travels inside the URL;
* the stream URL the answer leg hands the carrier, which carries the caller's number to the
  worker on Pipecat Cloud, a container that cannot reach our database at all.

So the payload is ENCRYPTED and authenticated (AES-256-GCM), not merely signed: a signed
token still prints the number in every proxy log between the carrier and the reader.

The key is derived from `CARRIER_CLAIM_SECRET` with HKDF and a domain label, so it never
equals the key the outbound call claim's HMAC uses. Holders: the API (mints transfer tokens),
voice-runtime (opens transfer tokens, seals caller claims) and the worker (opens caller
claims). The `purpose` string is the AEAD's associated data, so a token minted for one
purpose cannot be opened as another.

In `calevate_shared` rather than `apps/api/core` because the worker opens one and may not
import the monolith.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import time
from collections.abc import Mapping
from typing import Any, Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_INFO: Final = b"calevate-carrier-token-v1"
_NONCE_BYTES: Final = 12
#: The shortest secret accepted: RFC 2104 §3's floor for an HMAC key, which the call claim
#: derived from the same secret is.
MIN_SECRET_BYTES: Final = 32
#: Upper bound on an encoded token, so a stranger cannot make us decrypt a megabyte.
MAX_TOKEN_CHARS: Final = 2048


def _key(secret: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(secret.encode())


def usable_secret(secret: str | None) -> str | None:
    """The secret, or `None` when it is absent or shorter than the floor."""
    if not secret or len(secret.encode()) < MIN_SECRET_BYTES:
        return None
    return secret


def seal(
    secret: str, purpose: str, payload: Mapping[str, Any], *, ttl_s: int, now: float | None = None
) -> str:
    """Encrypt `payload` for `purpose`, valid for `ttl_s` seconds. URL-safe, no padding."""
    body = dict(payload)
    body["exp"] = int((time.time() if now is None else now) + ttl_s)
    nonce = os.urandom(_NONCE_BYTES)
    sealed = AESGCM(_key(secret)).encrypt(
        nonce, json.dumps(body, separators=(",", ":")).encode(), purpose.encode()
    )
    return base64.urlsafe_b64encode(nonce + sealed).rstrip(b"=").decode()


def open_sealed(
    secret: str | None, purpose: str, token: str, *, now: float | None = None
) -> dict[str, Any] | None:
    """The payload, or `None` for any failure: no key, malformed, forged, wrong purpose,
    or expired. Callers treat every failure alike and never echo the token."""
    key = usable_secret(secret)
    if key is None or not token or len(token) > MAX_TOKEN_CHARS:
        return None
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (binascii.Error, ValueError):
        return None
    if len(raw) <= _NONCE_BYTES:
        return None
    try:
        plain = AESGCM(_key(key)).decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], purpose.encode())
        body = json.loads(plain)
    except (InvalidTag, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    expiry = body.get("exp")
    if not isinstance(expiry, int) or expiry < (time.time() if now is None else now):
        return None
    return body


__all__ = ["MAX_TOKEN_CHARS", "MIN_SECRET_BYTES", "open_sealed", "seal", "usable_secret"]
