"""The API key's wire format: `cvk_live_<32 base62>_<6 base62 CRC32>` (D-1047).

The shape follows GitHub's 2021 token format (github.blog, "Behind GitHub's new
authentication token formats", 5 Apr 2021): a vendor prefix so a leaked key is
recognisable to a secret scanner and to the person who finds it, base62 so a double-click
selects the whole key, and a CRC32 of the random part encoded in six base62 characters at
the end so a scanner, and this module, can reject a mistyped or invented key offline,
before any database read.

The random part is 32 characters from `secrets` (log2(62^32) is about 190 bits). That
entropy is why the stored form is a plain SHA-256 rather than a password hash or an
HMAC under a pepper: there is no dictionary to walk, so a slow hash buys nothing, and a
pepper would be one more secret whose rotation kills every key in existence. The same
argument `core/ratelimit.fingerprint` makes for a session token.
"""

from __future__ import annotations

import hashlib
import secrets
import zlib
from typing import Final

_ALPHABET: Final = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
#: The only prefix minted today. `cvk_test_` is reserved for sandbox keys (W2.12) and is
#: refused until that exists, so a test key can never reach a live dial path by accident.
LIVE_PREFIX: Final = "cvk_live_"
RANDOM_LEN: Final = 32
CHECKSUM_LEN: Final = 6
TOKEN_LEN: Final = len(LIVE_PREFIX) + RANDOM_LEN + 1 + CHECKSUM_LEN
#: How much of the key the console shows back, so a person can tell two keys apart. The
#: prefix plus four random characters: 24 bits, too few to help a guess.
DISPLAY_LEN: Final = len(LIVE_PREFIX) + 4


def _base62(value: int, width: int) -> str:
    out = []
    for _ in range(width):
        value, digit = divmod(value, 62)
        out.append(_ALPHABET[digit])
    return "".join(reversed(out))


def _checksum(random_part: str) -> str:
    return _base62(zlib.crc32(random_part.encode("ascii")), CHECKSUM_LEN)


def mint() -> str:
    """A fresh key. Shown to its creator once; only its digest is kept."""
    random_part = "".join(secrets.choice(_ALPHABET) for _ in range(RANDOM_LEN))
    return f"{LIVE_PREFIX}{random_part}_{_checksum(random_part)}"


def well_formed(token: str) -> bool:
    """Prefix, length, alphabet and checksum, all offline. False costs no database read."""
    if len(token) != TOKEN_LEN or not token.startswith(LIVE_PREFIX):
        return False
    body = token[len(LIVE_PREFIX) :]
    random_part, sep, checksum = body[:RANDOM_LEN], body[RANDOM_LEN], body[RANDOM_LEN + 1 :]
    if sep != "_" or any(ch not in _ALPHABET for ch in random_part + checksum):
        return False
    return secrets.compare_digest(checksum, _checksum(random_part))


def digest(token: str) -> str:
    """What `api_keys.secret_sha256` holds: the hex SHA-256 of the whole key."""
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def display(token: str) -> str:
    return token[:DISPLAY_LEN]


__all__ = [
    "CHECKSUM_LEN",
    "DISPLAY_LEN",
    "LIVE_PREFIX",
    "RANDOM_LEN",
    "TOKEN_LEN",
    "digest",
    "display",
    "mint",
    "well_formed",
]
