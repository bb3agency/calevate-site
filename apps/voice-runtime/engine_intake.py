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
from dataclasses import dataclass
from typing import Any, Literal

from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

# Bolna's static egress IP — their ONLY webhook authenticity control (D-31, TRD §5).
# Enforced at nginx AND here: nginx config drifts, this does not.
#
# This is the DEFAULT, not the source of truth. The address belongs to the vendor and
# they can change it without telling us; while it is wrong every webhook 401s and every
# call falls back to the 10-minute poller. Recovering from that must not require a code
# change and a deploy of the one service that is deliberately never redeployed
# casually (main.py) — so the effective set comes from `BOLNA_WEBHOOK_SOURCE_IPS`.
DEFAULT_BOLNA_SOURCE_IPS: frozenset[str] = frozenset({"13.203.39.153"})


def source_ips_from_settings(configured: str) -> frozenset[str]:
    """Parse the configured allowlist. Fails SAFE, never open.

    Three deliberate properties, because this string is the whole authenticity control
    for an unsigned engine:

    - entries must parse as literal IP addresses. A CIDR, a hostname or a `*` is not a
      supported entry, so nobody can turn the allowlist into a wildcard by typing one
      — and a typo cannot quietly widen trust;
    - unusable entries are dropped with a log line, not silently accepted;
    - if NOTHING usable remains, the built-in default stands. An empty allowlist would
      reject the engine itself, which is a total outage; an operator who wants to stop
      accepting webhooks stops the service, they do not blank a variable.
    """
    entries: set[str] = set()
    for part in configured.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            log.warning("webhook_allowlist_entry_ignored", extra={"reason": "not an ip address"})
            continue
        entries.add(candidate)
    return frozenset(entries) or DEFAULT_BOLNA_SOURCE_IPS


# Resolved once at import. `verify_source` reads this module global at call time, so
# tests patch the attribute and operators set the environment variable; neither has to
# edit code.
BOLNA_SOURCE_IPS: frozenset[str] = source_ips_from_settings(get_settings().bolna_webhook_source_ips)

# Edge networks whose forwarded-for header we trust. Everything else is spoofable, so
# the immediate peer must be one of these before we believe a header (DEPLOYMENT §5).
TRUSTED_PROXY_CIDRS: tuple[str, ...] = (
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
)

EngineName = Literal["bolna", "fake"]
VerifyMethod = Literal["hmac", "source_ip", "none"]


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


def client_ip(peer_ip: str | None, headers: dict[str, str]) -> str:
    """Real caller IP. A forwarded header is believed ONLY when the immediate peer is
    a trusted proxy — otherwise anyone could send `CF-Connecting-IP: 13.203.39.153`
    and walk straight through the allowlist."""
    peer = peer_ip or ""
    if not is_trusted_peer(peer):
        return peer
    forwarded = headers.get("cf-connecting-ip") or headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    return first or peer


def verify_source(engine: str, source_ip: str) -> IntakeVerdict:
    if engine == "bolna":
        if source_ip in BOLNA_SOURCE_IPS:
            # `source_ip`, not `hmac`: the caller must keep treating this as a hint.
            return IntakeVerdict(ok=True, method="source_ip")
        return IntakeVerdict(ok=False, method="source_ip", reason="source ip not allowlisted")
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


def extract(payload: dict[str, Any]) -> IntakeEvent | None:
    """Pull the dedupe key and the status. Returns None when the payload carries no
    execution id — an event we cannot key is an event we cannot dedupe, and processing
    it twice would double-meter a call."""
    execution_id = payload.get("execution_id") or payload.get("id")
    if not isinstance(execution_id, str) or not execution_id:
        return None
    agent_ref = payload.get("agent_id")
    return IntakeEvent(
        execution_id=execution_id,
        raw_status=str(payload.get("status") or "unknown").lower(),
        engine_agent_ref=str(agent_ref) if agent_ref else None,
    )


__all__ = [
    "BOLNA_SOURCE_IPS",
    "DEFAULT_BOLNA_SOURCE_IPS",
    "TRUSTED_PROXY_CIDRS",
    "EngineName",
    "IntakeEvent",
    "IntakeVerdict",
    "client_ip",
    "extract",
    "is_trusted_peer",
    "source_ips_from_settings",
    "verify_source",
]
