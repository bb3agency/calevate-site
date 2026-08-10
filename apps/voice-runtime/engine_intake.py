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

# Bolna's static egress IP — their ONLY webhook authenticity control (D-31, TRD §5).
# Enforced at nginx AND here: nginx config drifts, this does not.
BOLNA_SOURCE_IPS: frozenset[str] = frozenset({"13.203.39.153"})

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
        return IntakeVerdict(ok=True, method="none", reason="fake engine")
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
    "TRUSTED_PROXY_CIDRS",
    "EngineName",
    "IntakeEvent",
    "IntakeVerdict",
    "client_ip",
    "extract",
    "is_trusted_peer",
    "verify_source",
]
