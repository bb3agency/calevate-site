"""ONE gate on every destination this platform will POST a lead to (D-23).

**What this stops.** `outbound_webhooks.url` is tenant-supplied and
`integrations.service.deliver` signs a lead's NAME AND PHONE NUMBER into a body and
POSTs it there. Validating that string as a URL says only that it is well-formed, so
any tenant `owner` could register `http://169.254.169.254/latest/meta-data/`, an RFC
1918 address, or `http://127.0.0.1:6379/` and turn our own delivery worker into an
internal client. Bodies are not stored back and redirects are not followed, so the read
channel is narrow — but `GET /v1/integrations/deliveries` publishes the status code and
the error type of every attempt, which is an internal port scanner with a UI, and the
POST itself is a PII egress channel into the private network whatever it answers.

**Where it is called, and why twice.** Registration (`integrations/routes.py`) and again
immediately before the request (`integrations/service.deliver`). The second call is the
one that matters and the one that is easy to leave out: the two events are minutes or
months apart, and the name a tenant registers is a name THEY control the DNS for. A
check done only at registration is defeated by answering with a public address once and
a private address afterwards — DNS rebinding, a time-of-check/time-of-use bug rather
than a filter bug, and the reason the OWASP SSRF Prevention Cheat Sheet's advice is to
validate the address the connection will actually use rather than the string a user
typed. Re-checking at connect narrows the window from "as long as the endpoint row
lives" to "the gap between our `getaddrinfo` and httpx's", which is the improvement that
is available without replacing the transport (see PINNING below).

**PINNING, considered and NOT done — and what remains open because of it.** The complete
close is to connect to the vetted IP literal and carry the hostname in `Host` +
`sni_hostname`, so no second resolution happens at all. It is deliberately not done
here: it moves this module into httpx's transport layer, changes what certificate
verification and virtual-host routing see for every legitimate client endpoint, and buys
a window measured in microseconds against an attacker who must already win a race
against their own TTL. If a rebinding attempt is ever OBSERVED — the `egress_refused`
log line below is what would show it — that is the trigger to take it, and it is a
transport change, not a rewrite of this file.

**The bypass classes this rejects, and the evidence for each.** A blocklist of textual
patterns is the wrong shape, because the attacker chooses the spelling and the resolver
chooses the address:

- **Alternate IPv4 spellings** — `http://2130706433/`, `http://0177.0.0.1/`,
  `http://0x7f000001/`. Not special-cased here ON PURPOSE: glibc's `getaddrinfo` parses
  them with the same `inet_aton` legacy rules the connection will use, so RESOLVING the
  host and judging the answer covers every spelling automatically, including ones nobody
  has written down. Verified on this interpreter — all three resolve to `127.0.0.1`.
  (Python's own `ipaddress` parser does NOT accept them, which is exactly why parsing
  the string instead of resolving it is the classic hole: bpo-36384 removed the
  ambiguous-format checks in 3.8.0a4, and leading zeros became an error again only in
  3.9.5/3.8.12. Two parsers with two answers is the bug.)
- **IPv4-mapped IPv6** — `http://[::ffff:127.0.0.1]/`. A live bypass class, not a
  hypothetical: SolaceLabs/solace-agent-mesh#1517 is a webhook SSRF guard defeated with
  exactly this notation.
- **IPv6 transition wrappers** — 6to4 (`2002:7f00:1::` carries 127.0.0.1, RFC 3056),
  Teredo (`2001::/32`, RFC 4380) and NAT64 (`64:ff9b::/96`, RFC 6052 + `64:ff9b:1::/48`,
  RFC 8215). pyLoad's CVE-2026-48737 is a guard bypassed through these wrappers.
- **Ranges a single stdlib property misses.** `is_global` is NOT sufficient by itself:
  measured on this interpreter, IPv4 multicast (`224.0.0.1`, `239.1.1.1`), IPv6
  multicast (`ff02::1`) and the NAT64 well-known prefix all report `is_global == True`.
  And the properties themselves have MOVED — CVE-2024-4032 corrected `is_private` /
  `is_global` against the IANA Special-Purpose Address Registries in 3.12.4, so their
  exact answers depend on the interpreter's patch level. Every category is therefore
  asserted explicitly and `is_global` is the catch-all UNDER them (it is what refuses
  100.64.0.0/10 carrier-grade NAT, RFC 6598), never the whole test.

**Ports.** 80 and 443 only. A webhook receiver on 8080 is a real thing and this refuses
it — deliberately. The alternative is that one accepted destination lets a tenant sweep
every port of a host that is otherwise legitimate, and the delivery screen reports the
result. A client whose CRM listens elsewhere puts it behind the reverse proxy they
already have; that is a smaller cost than the scanner.

Pairs with, and does not replace, `deliver`'s `follow_redirects=False`: a vetted address
is only vetted for the hop we make, so the redirect must stay unfollowed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})
ALLOWED_PORTS: Final[frozenset[int]] = frozenset({80, 443})
_DEFAULT_PORT: Final[dict[str, int]] = {"http": 80, "https": 443}

# A name that takes longer than this to resolve is refused rather than waited on. The
# lookup sits on a request path at registration and inside `DELIVERY_TIMEOUT_S` at
# delivery, and a tenant-controlled nameserver decides how long it takes to answer.
DNS_TIMEOUT_S: Final[float] = 5.0

# The IPv6 blocks whose entire purpose is to carry an IPv4 destination across a
# translator. Refused WHOLESALE rather than unwrapped: the embedded address sits at a
# different offset per prefix length (RFC 6052 §2.2), so unwrapping is four cases of
# bit-shuffling to reach a conclusion — no public webhook receiver is addressed through
# a NAT64 prefix — that the block test reaches in one line.
_TRANSLATION_PREFIXES: Final[tuple[ipaddress.IPv6Network, ...]] = (
    ipaddress.IPv6Network("64:ff9b::/96"),  # RFC 6052 §2.1 well-known prefix
    ipaddress.IPv6Network("64:ff9b:1::/48"),  # RFC 8215 local-use prefix
)

# Categories in the order they are reported. Most specific first, because Python answers
# True to several at once — 127.0.0.1 is loopback AND private, 169.254.169.254 is
# link-local AND private — and the client-facing sentence should name the one that
# explains the refusal.
_CATEGORY_ORDER: Final[tuple[str, ...]] = (
    "unspecified",
    "loopback",
    "link_local",
    "private",
    "multicast",
    "reserved",
    "not_globally_routable",
)

_CATEGORY_DETAIL: Final[dict[str, str]] = {
    "unspecified": "the unspecified address (0.0.0.0 or ::), which names no host",
    "loopback": "a loopback address, which is this server itself rather than yours",
    "link_local": ("a link-local address — the range cloud instance-metadata services answer on"),
    "private": "a private address on an internal network (RFC 1918 / RFC 4193)",
    "multicast": "a multicast address, which is not a single destination",
    "reserved": "an address in a reserved block that is not routed on the internet",
    "not_globally_routable": (
        "an address that is not routable on the public internet (for example carrier-"
        "grade NAT, RFC 6598)"
    ),
}


class EgressRefusedError(ProblemError):
    """A destination we will not send a lead to. A `ProblemError`, so the route needs no
    translation layer — FastAPI renders it as problem+json with the field named — and
    `deliver` needs only to read `.code` off it.

    `kind="validation"` (422) rather than `permission`: the tenant is allowed to
    configure endpoints, and this particular VALUE is the thing being refused.
    """

    def __init__(self, *, code: str, detail: str, remediation: str, rule: str, field: str) -> None:
        super().__init__(
            kind="validation",
            code=code,
            title="That destination cannot receive your leads",
            detail=detail,
            remediation=remediation,
            fields=[{"field": field, "rule": rule, "message": detail}],
        )


@dataclass(frozen=True, slots=True)
class VettedDestination:
    """What the guard proved, for the caller that has to write it down.

    `host` and `port` exist so the audit row can record WHERE a tenant pointed their
    leads without recording the URL: the path and query are tenant-authored free text
    and the delivery-body suite already carries one holding `?apikey=…`, so a ledger
    entry that quoted the whole URL would be an audit trail that leaks the credential it
    is auditing (hard rule 6).
    """

    scheme: str
    host: str
    port: int
    #: Every address the name resolved to, as strings. All of them were vetted — a
    #: round-robin record set that answers with one public and one private address is a
    #: rebinding attack that needs no second lookup.
    addresses: tuple[str, ...]


async def resolve_addresses(host: str, port: int) -> tuple[str, ...]:
    """Every address `host` resolves to right now, deduplicated, order preserved.

    THE SEAM. It is a module-level function rather than an inlined call so a test can
    substitute a resolver and exercise the rebinding case — which cannot be provoked
    against a real nameserver in a unit test — and so the suite does not depend on live
    DNS. Nothing else about the guard moves with it: the substitute returns addresses,
    and every judgement below is still made here.

    `loop.getaddrinfo` rather than `socket.getaddrinfo`: this runs on the API's event
    loop at registration, and a blocking lookup against a nameserver the TENANT operates
    would stall every other request in the process for as long as they cared to make it.
    """
    loop = asyncio.get_running_loop()
    infos = await asyncio.wait_for(
        loop.getaddrinfo(host, port, type=socket.SOCK_STREAM),
        timeout=DNS_TIMEOUT_S,
    )
    seen: dict[str, None] = {}
    for info in infos:
        # sockaddr is (host, port) for AF_INET and (host, port, flowinfo, scope_id) for
        # AF_INET6; the address is element 0 either way.
        seen.setdefault(str(info[4][0]), None)
    return tuple(seen)


def _embedded_ipv4(addr: IpAddress) -> tuple[ipaddress.IPv4Address, ...]:
    """The IPv4 address(es) an IPv6 address is carrying, if any.

    Unwrapped rather than trusted to `is_private`, because whether the stdlib unwraps
    these itself has changed between patch releases (CVE-2024-4032) and a guard that
    depends on which interpreter it runs under is a guard that will be wrong on one of
    them. Teredo yields the server AND the client half: both are IPv4 destinations the
    address names.
    """
    if not isinstance(addr, ipaddress.IPv6Address):
        return ()
    embedded: list[ipaddress.IPv4Address] = []
    if addr.ipv4_mapped is not None:  # ::ffff:0:0/96, RFC 4291 §2.5.5.2
        embedded.append(addr.ipv4_mapped)
    if addr.sixtofour is not None:  # 2002::/16, RFC 3056
        embedded.append(addr.sixtofour)
    if addr.teredo is not None:  # 2001::/32, RFC 4380
        embedded.extend(addr.teredo)
    return tuple(embedded)


def _refusal_category(addr: IpAddress) -> str | None:
    """Why this address may not receive a lead, or None if it may.

    Recursive on the embedded address first: an IPv6 wrapper is only ever as safe as the
    IPv4 destination inside it, and reporting "reserved" for `::ffff:169.254.169.254`
    would hide from the client that they pointed us at the metadata service.
    """
    for embedded in _embedded_ipv4(addr):
        category = _refusal_category(embedded)
        if category is not None:
            return category
    if isinstance(addr, ipaddress.IPv6Address) and any(
        addr in prefix for prefix in _TRANSLATION_PREFIXES
    ):
        return "reserved"
    if addr.is_unspecified:
        return "unspecified"
    if addr.is_loopback:
        return "loopback"
    if addr.is_link_local:
        return "link_local"
    if addr.is_private:
        return "private"
    if addr.is_multicast:
        return "multicast"
    if addr.is_reserved:
        return "reserved"
    if not addr.is_global:
        return "not_globally_routable"
    return None


def _category_of(address: str) -> str | None:
    """`_refusal_category` for a resolver's answer, which is a STRING.

    An answer we cannot parse is refused, not raised past: `getaddrinfo` can hand back a
    scoped form (`fe80::1%eth0`) and a substituted resolver can hand back anything at
    all, and an unparseable address is by definition one we cannot vet. Letting the
    `ValueError` escape would turn a hostile URL into a 500 — an unhandled exception on
    a tenant-controlled input, which is the shape of defect this whole module is about.
    """
    try:
        return _refusal_category(ipaddress.ip_address(address))
    except ValueError:
        return "not_globally_routable"


def _worst(categories: list[str]) -> str:
    """One category to report when a name resolved to several bad addresses. Ordered so
    the message is deterministic — a refusal whose wording depends on DNS record order
    is a refusal a client cannot search for twice."""
    for candidate in _CATEGORY_ORDER:
        if candidate in categories:
            return candidate
    return "not_globally_routable"


def loopback_is_allowed() -> bool:
    """Whether a receiver on THIS MACHINE is a legitimate destination.

    True under `APP_ENV=local` and nowhere else, and the relaxation is LOOPBACK ONLY.
    Stated here rather than discovered in review, because both halves are deliberate:

    - a developer running `python -m http.server 9000` and pointing an endpoint at
      `http://localhost:9000/hook` is the ordinary way this feature is worked on, and a
      guard that makes the local loop untestable gets switched off rather than fixed;
    - RFC 1918 stays refused even locally. `127.0.0.1` is "this process's own machine",
      which a developer indisputably controls; `192.168.1.50` is the office network, and
      that is precisely the class of destination this module exists to protect. The same
      argument refuses link-local locally — a laptop has no metadata service, but the
      test suite runs under `APP_ENV=local` and a relaxation that also disabled the
      tests proving the refusal would be worth less than no relaxation at all.

    The port rule is relaxed with it, and only for loopback: a dev receiver is on 9000,
    and refusing the port after allowing the host would be a half-open door.
    """
    return get_settings().app_env == "local"


async def assert_public_http_url(raw_url: str, *, field: str = "url") -> VettedDestination:
    """Refuse anything but a public http(s) destination on port 80/443. THE one gate.

    Raises `EgressRefusedError` (a `ProblemError`) naming the field, so a route can let it
    propagate and a worker can record `.code` as the delivery's reason.
    """
    parts = urlsplit(raw_url.strip())
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise EgressRefusedError(
            code="webhook_url_scheme_not_allowed",
            detail=(
                "Only http:// and https:// destinations can receive leads; "
                f"'{scheme or 'no scheme'}' cannot."
            ),
            remediation="Use the https:// URL of your endpoint.",
            rule="scheme",
            field=field,
        )

    try:
        # `.hostname` lowercases and strips the brackets off an IPv6 literal; `.port`
        # raises on a port outside 0..65535 rather than returning a nonsense integer.
        #
        # `is None` rather than `or`: `.port` returns 0 for `https://host:0/`, and `or`
        # would silently substitute 443 — vetting a port the request would not use. Zero
        # falls through to the ALLOWED_PORTS check below and is refused there, which is
        # the honest answer to a URL naming a port nothing listens on.
        host = parts.hostname
        port = _DEFAULT_PORT[scheme] if parts.port is None else parts.port
    except ValueError as exc:
        raise EgressRefusedError(
            code="webhook_url_port_not_allowed",
            detail="That URL does not carry a usable port number.",
            remediation="Leave the port off the URL to use the default for the scheme.",
            rule="port",
            field=field,
        ) from exc
    if not host:
        raise EgressRefusedError(
            code="webhook_url_host_missing",
            detail="That URL names no host to deliver to.",
            remediation="Include the full address of your endpoint, host and all.",
            rule="host",
            field=field,
        )

    try:
        addresses = await resolve_addresses(host, port)
    except (TimeoutError, OSError) as exc:
        # FAILS CLOSED, and that is the whole point of doing it here. A name we cannot
        # resolve is a name we cannot vet, and letting it through "because the request
        # would fail anyway" hands an attacker the one thing they need: control of
        # whether we look at all. NXDOMAIN on our lookup and an A record on httpx's is a
        # rebinding attack with an extra step. Same doctrine as
        # `parse_source_ip_allowlist` and `engine_intake.client_ip`.
        log.warning(
            "egress_refused",
            # Host, port and reason — never the URL. Path and query are tenant free text
            # and one of ours carries an API key (hard rule 6).
            extra={"host": host, "port": port, "reason": "unresolvable"},
        )
        raise EgressRefusedError(
            code="webhook_url_unresolvable",
            detail=f"'{host}' could not be resolved to an address.",
            remediation=("Check the hostname is spelled correctly and is published in public DNS."),
            rule="dns",
            field=field,
        ) from exc
    if not addresses:
        raise EgressRefusedError(
            code="webhook_url_unresolvable",
            detail=f"'{host}' resolved to no addresses at all.",
            remediation="Check the hostname is published in public DNS.",
            rule="dns",
            field=field,
        )

    refused = [category for category in map(_category_of, addresses) if category is not None]
    if refused:
        category = _worst(refused)
        if category == "loopback" and len(refused) == len(addresses) and loopback_is_allowed():
            # Local development only, loopback only, and the port rule goes with it.
            return VettedDestination(scheme=scheme, host=host, port=port, addresses=addresses)
        log.warning("egress_refused", extra={"host": host, "port": port, "reason": category})
        raise EgressRefusedError(
            code="webhook_url_not_public",
            detail=f"'{host}' resolves to {_CATEGORY_DETAIL[category]}.",
            remediation=(
                "Give us an address reachable from the public internet. Endpoints inside "
                "your own network cannot receive our deliveries."
            ),
            rule=category,
            field=field,
        )

    if port not in ALLOWED_PORTS:
        # After the address check, so a private host on a strange port is reported as
        # private — the fact the client has to act on — rather than as a port problem
        # they would "fix" by moving it to 443 and being refused again.
        raise EgressRefusedError(
            code="webhook_url_port_not_allowed",
            detail=f"Port {port} cannot be used; leads are delivered to 80 or 443 only.",
            remediation=(
                "Publish your endpoint on the standard http or https port, behind the "
                "reverse proxy or load balancer you already use."
            ),
            rule="port",
            field=field,
        )

    return VettedDestination(scheme=scheme, host=host, port=port, addresses=addresses)


__all__ = [
    "ALLOWED_PORTS",
    "ALLOWED_SCHEMES",
    "DNS_TIMEOUT_S",
    "EgressRefusedError",
    "VettedDestination",
    "assert_public_http_url",
    "loopback_is_allowed",
    "resolve_addresses",
]
