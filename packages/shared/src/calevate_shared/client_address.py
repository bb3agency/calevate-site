"""THE ONE answer to "which address is this request from", for every deployable.

It lived in `apps/voice-runtime/engine_intake.py`, where it was written for the unsigned
engine's source-IP allowlist, and `apps/api` had a second answer that read the socket
peer — so behind the edge the API stamped the PROXY's address on every `audit_log` row
(SEC-COMP §5 wants the caller's) and spent a per-IP signup quota against that one shared
value. Two answers to one question is a defect even when both work (CLAUDE.md, "one way
per problem"), and here one of them was wrong.

It lives in `calevate_shared` rather than in either service because BOTH need it and
neither may import the other: hard rule 3 forbids `apps/voice-runtime` growing a
dependency on `apps/api`, and the import-linter contract "shared package imports no app
code" forbids the reverse — which is why `app_env` is a PARAMETER here and not a
`get_settings()` call. The function is pure: one parse of a short string, no IO, no
settings lookup, callable from the 500ms ack path and from a test with no environment.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping

# Edge networks whose forwarded-for header we trust. Everything else is spoofable, so
# the immediate peer must be one of these before we believe a header (DEPLOYMENT §5).
TRUSTED_PROXY_CIDRS: tuple[str, ...] = (
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
)

#: Parsed once at import rather than per call. `is_trusted_peer` runs on every engine
#: delivery inside the ack budget AND now on every authenticated API request, and
#: `ip_network` on four literals is the kind of cost that is invisible until it is in
#: two hot paths instead of one.
_TRUSTED_NETWORKS = tuple(ipaddress.ip_network(cidr) for cidr in TRUSTED_PROXY_CIDRS)

# THE ONE header any Calevate service will take a client address from, and the ONE hop
# allowed to have written it. Everything about that choice is argued in `client_ip`.
EDGE_CLIENT_IP_HEADER = "cf-connecting-ip"


def is_trusted_peer(peer_ip: str) -> bool:
    try:
        address = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    return any(address in network for network in _TRUSTED_NETWORKS)


def _literal_ip(value: str) -> str | None:
    """`value` if it is exactly one IP address, else None.

    "Exactly one" is doing real work: a comma-separated list, a `host:port`, an empty
    string and a stray `unknown` all fail `ip_address` and therefore all fail closed.
    One parse of a short string — the whole cost this function adds to the ack path.
    """
    candidate = value.strip()
    if not candidate:
        return None
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return candidate


def client_ip(peer_ip: str | None, headers: Mapping[str, str], *, app_env: str) -> str | None:
    """The caller's address as this DEPLOYMENT can actually vouch for it, or None when it
    cannot be established — in which case the caller decides, per surface, whether that
    is a refusal (the engine receiver), a null column (an audit row) or a degraded
    shared bucket (a limiter). Never a guess.

    WHAT WAS WRONG BEFORE. This function preferred `CF-Connecting-IP` and otherwise took
    the LEFTMOST `X-Forwarded-For` entry. The leftmost entry is the one the ORIGINAL
    CALLER wrote: every proxy in the chain appends, so position 0 is attacker input by
    construction. MDN states the rule plainly — "any security-related use of
    X-Forwarded-For (such as for rate limiting or IP-based access control) must only use
    IP addresses added by a trusted proxy" (developer.mozilla.org/en-US/docs/Web/HTTP/
    Reference/Headers/X-Forwarded-For), and RFC 7239 §8.1 says the same of `Forwarded`:
    the field "cannot be relied upon to be correct... it may be modified by every node on
    the way to the server, including the client making the request", so only the entries
    your own trusted proxies appended mean anything. The established remedy is to know how
    many trusted hops sit in front and count that many from the RIGHT (adam-p.ca's
    "The perils of the 'real' client IP" is the canonical write-up; express's
    `trust proxy` hop-count and nginx's `real_ip_recursive` are the same idea in two other
    stacks). Leftmost-wins was safe here only because `CF-Connecting-IP` happened to
    always be present — i.e. the entire authenticity control for an unsigned engine rested
    on a fallback never being reached.

    WHAT THIS DEPLOYMENT PROMISES, which is what is implemented (DEPLOYMENT §1, §5):

        caller → Cloudflare (proxied, Full strict, origin locked) → nginx → container

    exactly ONE trusted hop in front of us, and that hop is nginx, which is only reachable
    from Cloudflare's ranges (`infra/nginx/snippets/calevate-origin.conf` — `allow` the CF
    ranges, `deny all`). Cloudflare sets `CF-Connecting-IP` to the address that connected
    to it on every proxied request and it is one of the headers Cloudflare refuses to let
    a Transform Rule modify, so from behind the origin lock it is the edge's statement,
    not the caller's. Our nginx then OVERWRITES it with `$remote_addr` — already real-ip
    restored — for every vhost, api included (`snippets/calevate-proxy.conf`, included by
    all four server blocks), so a forgery from inside the perimeter is replaced by the
    forger's own address rather than passed through.

    So the hop count is one, and the value that hop guarantees is `CF-Connecting-IP`. That
    is the only thing read. `X-Forwarded-For` is NOT consulted at all: our nginx appends
    `$remote_addr` (already real-ip-restored) to whatever the caller sent, so its rightmost
    entry would merely restate `CF-Connecting-IP` — a second way to answer one question,
    which is how the two drift apart later. One header, one hop, one answer.

    FAILS CLOSED. Outside `local`, a peer that is not a trusted proxy, an absent header, or
    a header that is not a single literal IP all return None. On the engine receiver
    `verify_source` turns None into a refusal: an unsigned engine's only authenticity
    control must never degrade to "we could not tell, so we accepted it" — a misconfigured
    edge (real_ip missing, the header stripped) shows up as `webhook_source_rejected` plus
    a 10-minute poller catch-up, not as an open door.

    LOCAL is the one environment with no edge in front, so the socket peer IS the caller
    (D-49 made `APP_ENV` explicit precisely so this branch cannot be reached by a
    production deploy that forgot to set it). A header is still honoured there when the
    peer is a trusted/loopback address, which keeps a dev proxy and the test suite working
    without any of it being reachable in staging or prod.
    """
    peer = peer_ip or ""
    trusted_peer = is_trusted_peer(peer)
    if app_env == "local":
        if trusted_peer:
            return _literal_ip(headers.get(EDGE_CLIENT_IP_HEADER, "")) or peer or None
        return peer or None
    if not trusted_peer:
        # Nothing reaches these services except through nginx on the container network. A
        # direct peer is either a misconfiguration or someone inside the perimeter, and
        # neither is a caller whose self-declared address we should be reading.
        return None
    return _literal_ip(headers.get(EDGE_CLIENT_IP_HEADER, ""))


__all__ = [
    "EDGE_CLIENT_IP_HEADER",
    "TRUSTED_PROXY_CIDRS",
    "client_ip",
    "is_trusted_peer",
]
