"""Is a carrier's HTTP request really the carrier's? Pure checks: no IO, no settings.

`carrier_routes.authenticate` applies two independent controls in a fixed order — the
source-address allowlist, then the request signature — and decides the policy (which key,
whether a signature is required). This module only answers the two questions.

THE VOBIZ SIGNATURE (VERIFIED-VENDOR-DOCS, `vobiz-findings/mirror/pages/concepts/
validating-callbacks.md:15-52`): `X-Vobiz-Signature-V3 = base64(HMAC-SHA256(auth_token,
base_url + "." + nonce))`, the nonce in `X-Vobiz-Signature-V3-Nonce`, and `base_url` the
callback URL with its query stripped. `X-Vobiz-Signature-MA-V3` is the same computation
under the parent account's token, sent on sub-account callbacks (`:24-27`, `:72`).

What a valid signature proves is narrow and worth stating: Vobiz requested THIS PATH. The
body is not signed (`:66-70`), so `From`, `CallUUID` and every other field stay claims —
which is why the caller number still travels to the worker under our own MAC rather than
being believed because the request verified.

Replay: the vendor's nonces are random rather than time-based, and remembering them is
left to the receiver (`:304`). It is not done here — that would put a Redis round trip on
the answer route, which today performs no IO — and the events route needs no help: its
inbox already makes a replayed (CallUUID, Event) a no-op.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Final, Literal
from urllib.parse import quote, unquote

#: How a request was admitted, for the log line and the forensic row. Ordered by strength.
AuthMethod = Literal["signature", "source_ip", "none"]

#: What a signature check found. `unverifiable` is a signature we hold no key for.
SignatureOutcome = Literal["verified", "absent", "invalid", "unverifiable"]

IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


@dataclass(frozen=True, slots=True)
class SignatureScheme:
    """Where a carrier puts its signature, and the header carrying the nonce it signed."""

    header: str
    nonce_header: str
    #: Further headers holding the same computation under another key of the account
    #: (Vobiz's parent-account variant). Any one of them verifying is enough.
    alternate_headers: tuple[str, ...] = ()


VOBIZ_SIGNATURE_V3: Final = SignatureScheme(
    header="X-Vobiz-Signature-V3",
    nonce_header="X-Vobiz-Signature-V3-Nonce",
    alternate_headers=("X-Vobiz-Signature-MA-V3",),
)


def vobiz_v3_signature(key: str, base_url: str, nonce: str) -> str:
    """The V3 value Vobiz sends for `base_url` and `nonce` under `key`."""
    digest = hmac.new(key.encode(), f"{base_url}.{nonce}".encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def check_signature(
    headers: Mapping[str, str],
    scheme: SignatureScheme,
    *,
    key: str | None,
    base_urls: Iterable[str],
) -> SignatureOutcome:
    """Does any presented signature verify for any of `base_urls`? Constant-time compare.

    `headers` should be case-insensitive (Starlette's are); header names are the vendor's
    spelling.
    """
    presented = [
        value for name in (scheme.header, *scheme.alternate_headers) if (value := headers.get(name))
    ]
    if not presented:
        return "absent"
    if not key:
        return "unverifiable"
    nonce = headers.get(scheme.nonce_header, "")
    if not nonce:
        return "invalid"
    for base_url in base_urls:
        expected = vobiz_v3_signature(key, base_url, nonce).encode()
        # Every candidate is compared, never short-circuited on the first byte that
        # differs, and the loop is over OUR candidates, not the sender's.
        if any(hmac.compare_digest(value.encode(), expected) for value in presented):
            return "verified"
    return "invalid"


def signed_base_urls(public_base: str, *, raw_path: bytes | None, path: str) -> tuple[str, ...]:
    """The URLs the carrier may have signed for this request, rebuilt from CONFIGURATION.

    Never `request.url`: behind Cloudflare and nginx the scheme and host this process sees
    are the proxy's, and a mismatch would fail every call. The public origin is
    `Settings.webhook_base_url`; the path is the request's own, query stripped.

    TWO SPELLINGS OF THE PATH, both ours. The raw bytes are what the carrier sent and what
    nginx forwards unchanged (`proxy_pass` with no URI part); the canonical form re-quotes
    each decoded segment the way `calevate_shared.carrier` mints it (`%3A` for the ref's
    colons). A proxy that re-encodes the path differently still verifies, and neither form
    can name a resource other than the one being requested.
    """
    base = public_base.rstrip("/")
    candidates: list[str] = []
    if raw_path:
        candidates.append(base + raw_path.split(b"?", 1)[0].decode("latin-1"))
    canonical = "/".join(quote(unquote(segment), safe="") for segment in path.split("/"))
    if base + canonical not in candidates:
        candidates.append(base + canonical)
    return tuple(candidates)


@lru_cache(maxsize=64)
def parse_networks(entries: tuple[str, ...]) -> tuple[tuple[IpNetwork, ...], int]:
    """Addresses or CIDRs as networks, and how many entries were not one.

    Cached: the allowlist is read per request from settings and almost never changes, so
    the parse is paid once per distinct value.
    """
    networks: list[IpNetwork] = []
    invalid = 0
    for entry in entries:
        candidate = entry.strip()
        if not candidate:
            continue
        try:
            networks.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            invalid += 1
    return tuple(networks), invalid


def split_list(value: str | None) -> tuple[str, ...]:
    """A comma-separated setting as its non-blank entries."""
    if not value:
        return ()
    return tuple(entry.strip() for entry in value.split(",") if entry.strip())


def ip_in(source_ip: str, networks: Iterable[IpNetwork]) -> bool:
    try:
        address = ipaddress.ip_address(source_ip)
    except ValueError:
        return False
    return any(address in network for network in networks)


__all__ = [
    "VOBIZ_SIGNATURE_V3",
    "AuthMethod",
    "IpNetwork",
    "SignatureOutcome",
    "SignatureScheme",
    "check_signature",
    "ip_in",
    "parse_networks",
    "signed_base_urls",
    "split_list",
    "vobiz_v3_signature",
]
