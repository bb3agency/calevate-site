"""The voice-runtime's engine twin (hard rule 2's "and its voice-runtime twin").

Deliberately tiny. The receiver has one job — decide whether an event is authentic
and what its dedupe key is — and hard rule 3 forbids paying for anything else on this
path: no HTTP client, no cost arithmetic, no transcript parsing, no ORM. The full
adapter (`apps/api/engine/`) does all of that later, in a worker, where a 200ms import
costs nothing.

So this module extracts exactly three fields and refuses to interpret the rest. The
payload is a HINT (D-31); the worker's authenticated Get Execution is the truth.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Literal, get_args

from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from calevate_shared.config import bolna_source_ips
from calevate_shared.engine import WEBHOOK_AUTH_BY_ENGINE

log = get_logger(__name__)

# Bolna's static egress IP is their ONLY webhook authenticity control (D-31, TRD §5),
# and it is enforced at nginx AND here: nginx config drifts, this does not.
#
# THE SET ITSELF IS NOT DEFINED HERE. It comes from `BOLNA_WEBHOOK_SOURCE_IPS` via
# `calevate_shared.config.bolna_source_ips`, which is the ONE resolver — the adapter's
# `verify_webhook` reads the same function, so an operator who rotates the variable
# during a vendor renumber (the documented recovery path, and the whole reason the
# setting exists) moves the receiver's answer and the adapter's verdict together. This
# module used to resolve the value once at import into a `BOLNA_SOURCE_IPS` global while
# the adapter matched a hardcoded constant; that pair agreed only until the recovery
# path was used, which is exactly when nobody is re-reading two files.
#
# Resolution stays O(1) per delivery: `get_settings` and the parse are both cached.

# Edge networks whose forwarded-for header we trust. Everything else is spoofable, so
# the immediate peer must be one of these before we believe a header (DEPLOYMENT §5).
TRUSTED_PROXY_CIDRS: tuple[str, ...] = (
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
)

# THE ONE header this service will take a client address from, and the ONE hop allowed to
# have written it. Everything about that choice is argued in `client_ip` below.
_EDGE_CLIENT_IP_HEADER = "cf-connecting-ip"

EngineName = Literal["bolna", "fake"]
VerifyMethod = Literal["hmac", "source_ip", "none"]

# The engines this service will answer for at all. Derived from the type rather than
# retyped, so the two can never drift. Used to bound anything the URL's `{engine}`
# segment is allowed to become — a metric label, in particular: on the refusal path that
# segment is an unauthenticated stranger's string.
KNOWN_ENGINES: frozenset[str] = frozenset(get_args(EngineName))


@dataclass(frozen=True, slots=True)
class IntakeVerdict:
    ok: bool
    method: VerifyMethod
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class IntakeEvent:
    """The three fields the receiver needs and nothing more."""

    execution_id: str
    raw_status: str
    engine_agent_ref: str | None


def is_trusted_peer(peer_ip: str) -> bool:
    try:
        address = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    return any(address in ipaddress.ip_network(cidr) for cidr in TRUSTED_PROXY_CIDRS)


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


def client_ip(peer_ip: str | None, headers: dict[str, str]) -> str | None:
    """The caller's address as this DEPLOYMENT can actually vouch for it, or None when it
    cannot be established — in which case the caller must refuse, never guess.

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

        Bolna → Cloudflare (proxied, Full strict, origin locked) → nginx → this container

    exactly ONE trusted hop in front of us, and that hop is nginx, which is only reachable
    from Cloudflare's ranges (`infra/nginx/snippets/calevate-origin.conf` — `allow` the CF
    ranges, `deny all`). Cloudflare sets `CF-Connecting-IP` to the address that connected
    to it on every proxied request and it is one of the headers Cloudflare refuses to let
    a Transform Rule modify, so from behind the origin lock it is the edge's statement,
    not the caller's. nginx neither sets nor clears it.

    So the hop count is one, and the value that hop guarantees is `CF-Connecting-IP`. That
    is the only thing read. `X-Forwarded-For` is NOT consulted at all: our nginx appends
    `$remote_addr` (already real-ip-restored) to whatever the caller sent, so its rightmost
    entry would merely restate `CF-Connecting-IP` — a second way to answer one question,
    which is how the two drift apart later. One header, one hop, one answer.

    FAILS CLOSED. Outside `local`, a peer that is not a trusted proxy, an absent header, or
    a header that is not a single literal IP all return None, and `verify_source` turns
    None into a refusal. An unsigned engine's only authenticity control must never degrade
    to "we could not tell, so we accepted it" — a misconfigured edge (real_ip missing, the
    header stripped) now shows up as `webhook_source_rejected` plus a 10-minute poller
    catch-up, not as an open door.

    LOCAL is the one environment with no edge in front, so the socket peer IS the caller
    (D-49 made `APP_ENV` explicit precisely so this branch cannot be reached by a
    production deploy that forgot to set it). A header is still honoured there when the
    peer is a trusted/loopback address, which keeps a dev proxy and the test suite working
    without any of it being reachable in staging or prod.
    """
    peer = peer_ip or ""
    trusted_peer = is_trusted_peer(peer)
    if get_settings().app_env == "local":
        if trusted_peer:
            return _literal_ip(headers.get(_EDGE_CLIENT_IP_HEADER, "")) or peer or None
        return peer or None
    if not trusted_peer:
        # Nothing reaches this service except through nginx on the container network. A
        # direct peer is either a misconfiguration or someone inside the perimeter, and
        # neither is a caller whose self-declared address we should be reading.
        return None
    return _literal_ip(headers.get(_EDGE_CLIENT_IP_HEADER, ""))


def verify_source(engine: str, source_ip: str | None) -> IntakeVerdict:
    """`source_ip` is None when `client_ip` could not establish one — see there.

    That is a REFUSAL for an allowlisted engine, with its own reason string so the alert
    tells an operator which half broke: "not allowlisted" is a vendor renumber (rotate
    `BOLNA_WEBHOOK_SOURCE_IPS`), "client ip not established" is the EDGE (real_ip or the
    `CF-Connecting-IP` line in `calevate-proxy.conf` is gone, or something is reaching the
    container without going through nginx). Two very different runbook entries, and an
    unsigned engine cannot afford them to look alike.

    WHICH METHOD APPLIES IS LOOKED UP, NOT HARD-CODED (D-93). This function used to open
    `if engine == "bolna":` — a vendor name compiled into the latency-critical receiver,
    so adopting an engine that SIGNS its webhooks meant editing this service and
    redeploying it in lockstep with the adapter, which hard rule 3's last clause exists to
    prevent. `WEBHOOK_AUTH_BY_ENGINE` is the one table both readers share (the adapters'
    own declarations are asserted equal to it by the conformance suite), and reading it
    costs one dict lookup on a path that must ack in under 500ms.

    It stays a TABLE rather than an import of the adapter's descriptor because hard rule 3
    forbids the heavy import here: reaching `EngineCapabilities` through
    `apps.api.engine` would pull httpx and the vendor client into the ack path.
    """
    method = WEBHOOK_AUTH_BY_ENGINE.get(engine)
    if method == "source_ip":
        if source_ip is not None and source_ip in bolna_source_ips(get_settings()):
            # `source_ip`, not `hmac`: the caller must keep treating this as a hint.
            return IntakeVerdict(ok=True, method="source_ip")
        return IntakeVerdict(
            ok=False,
            method="source_ip",
            reason="source ip not allowlisted"
            if source_ip is not None
            else "client ip not established",
        )
    if method == "hmac":
        # DECLARED BY AN ADAPTER, NOT IMPLEMENTED HERE — and refused rather than waved
        # through, which is the only safe direction. Writing a signature verifier for an
        # engine we have not adopted would mean inventing the header, the canonical string
        # and the digest, and an unverified vendor contract is exactly what D-31/D-32
        # forbid; getting any of the three wrong would produce a receiver that rejects
        # every real delivery and accepts nothing but our own test vectors.
        #
        # The refusal is not a gap that can be reached today: no signing engine is
        # selectable as `ENGINE=` (`config.EngineName`). It becomes reachable on the day
        # one is added, and on that day this is the line that says what is left to do.
        return IntakeVerdict(
            ok=False, method="hmac", reason="signature verification not implemented"
        )
    if engine == "fake":
        # The fake engine verifies NOTHING by design — that is how the whole pipeline
        # runs offline (DEV-SETUP §3). Which makes this route an unauthenticated write
        # endpoint, and the route table is identical in every environment: on a prod box
        # running ENGINE=bolna, `/hooks/v1/engine/fake` would hand any stranger who
        # found the URL an inbox claim, a forensic row and an ARQ job.
        #
        # So the door is open exactly where the fake engine is the engine. Nothing about
        # this widens trust anywhere else, and a deployment cannot receive events for an
        # engine it does not run.
        if get_settings().engine == "fake":
            return IntakeVerdict(ok=True, method="none", reason="fake engine")
        return IntakeVerdict(
            ok=False, method="none", reason="fake engine is not enabled in this environment"
        )
    return IntakeVerdict(ok=False, method="none", reason="unknown engine")


# The longest a keyable field may be. Bolna's execution ids are uuid-shaped (36 chars)
# and its status enum's longest member is `call-disconnected` (17), so 128 is several
# times either — generous enough that a vendor change does not start dropping real
# events, and far under the ~2704-byte ceiling a btree index tuple has.
#
# THE CEILING IS NOT COSMETIC. `execution_id` and `raw_status` are concatenated into
# `webhook_inbox_events.event_key`, which carries a UNIQUE index: a long enough value in
# either position makes Postgres answer `index row size N exceeds btree version 4
# maximum` and the whole ack becomes an unhandled 500. Same story for a NUL byte, which
# psycopg refuses outright. Both are worth exactly one 500 to learn, and at an endpoint
# whose vendor delivers at-most-once and never retries (D-31), that 500 is a lost call.
_MAX_KEY_FIELD = 128

# C0 + DEL. A control character has no business in an execution id or a status; NUL
# cannot be stored in a Postgres text column at all, and the rest are log- and
# key-injection material for a value we copy verbatim into a dedupe key and a job id.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _keyable(value: str) -> str | None:
    """`value` if it can safely become part of a durable key, else None."""
    if not value or len(value) > _MAX_KEY_FIELD or _CONTROL_CHARS.search(value):
        return None
    return value


def execution_key(payload: dict[str, Any]) -> str | None:
    """The execution id a payload can be keyed by, or None if it names none we can store.

    Split out of `extract` so the in-call tool route (`tool_routes.py`) can ask the same
    question without the status half — a tool call carries no lifecycle status, and
    inventing one for it would put a fictional transition into a dedupe key. Three
    spellings are accepted because the tool payload's shape is an ASSUMPTION about the
    engine's custom-function mechanism (OPERATIONS §2 gate 8), not a verified contract;
    the webhook path has always accepted the first two.
    """
    value = payload.get("execution_id") or payload.get("id") or payload.get("call_id")
    if not isinstance(value, str):
        return None
    return _keyable(value)


def extract(payload: dict[str, Any]) -> IntakeEvent | None:
    """Pull the dedupe key and the status. Returns None when the payload carries no
    execution id — an event we cannot key is an event we cannot dedupe, and processing
    it twice would double-meter a call.

    "Carries no execution id" now includes "carries one we refuse to store". The caller's
    answer to an unkeyable payload is already the right answer to an unstorable one: ack
    it, alert `webhook_unkeyable`, and let the 10-minute reconciliation poller be the
    truth (D-31). That is a deliberate answer; a 500 out of the database driver is not.
    """
    keyed_id = execution_key(payload)
    if keyed_id is None:
        return None
    raw_status = _keyable(str(payload.get("status") or "unknown").lower())
    if raw_status is None:
        return None
    # NOT fatal, unlike the two above: the ref is a hint the worker uses to resolve a
    # tenant, not part of any key, and the authenticated Get Execution is what actually
    # says which agent this was. An implausible one is dropped and the event still flows
    # — otherwise a junk field could suppress a real call's event entirely.
    agent_ref = payload.get("agent_id")
    return IntakeEvent(
        execution_id=keyed_id,
        raw_status=raw_status,
        engine_agent_ref=_keyable(str(agent_ref)) if agent_ref else None,
    )


__all__ = [
    "KNOWN_ENGINES",
    "TRUSTED_PROXY_CIDRS",
    "EngineName",
    "IntakeEvent",
    "IntakeVerdict",
    "client_ip",
    "execution_key",
    "extract",
    "is_trusted_peer",
    "verify_source",
]
