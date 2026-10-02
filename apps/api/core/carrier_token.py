"""Sealed tokens for carrier URLs that must carry data voice-runtime cannot look up.

A live transfer redirects the caller to a URL whose response is the `<Dial>` document, and
voice-runtime serves that document without touching the database (hard rule 3). So the
destination travels inside the URL. It is a phone number, and a URL path lands in access
logs, so the token is ENCRYPTED and authenticated (AES-256-GCM), not merely signed: a
signed token would still print the number in every proxy log (hard rule 6).

The key is derived from `CARRIER_CLAIM_SECRET`, which both the API (the minter) and
voice-runtime (the reader) already hold in the VPS environment, with a domain label so the
derived key never equals the caller-claim MAC key.
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
#: The shortest secret accepted, matching `worker_api.MIN_CALLER_CLAIM_KEY_BYTES`.
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
