"""Outbound CRM sync — us → the client's tools (D-23).

Three properties this module exists to guarantee, in the order they matter:

**Nothing is delivered that the domain write did not commit.** Every event goes out
through the transactional outbox (BACKEND-PATTERNS §4): `enqueue_event` writes the
outbox row in the CALLER's transaction, so "lead created but the CRM never heard" and
"CRM told about a lead that rolled back" are both impossible.

**Every request is signed, and the signature covers the timestamp.** HMAC-SHA256 over
`{timestamp}.{body}` in `X-Calevate-Signature`, the scheme SEC-COMP §5 requires of our
inbound partners and therefore the one we owe ours. Signing the body alone would let a
captured request be replayed forever; the timestamp gives the receiver a window to
reject.

**Payloads are redacted by the same rule as everything else.** A lead's phone number is
PII whether it is in a log line or an HTTP body, so the envelope carries the masked form
unless the endpoint is explicitly configured otherwise — an opt-in the client makes
about their own data, recorded in the config row rather than assumed.

Delivery outcomes land in `webhook_deliveries(direction='out')`, which is the forensic
half of SEC-COMP §5 and the data the "webhook activity" screen reads.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.logging import get_logger, redact_mapping
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.reliability.service import enqueue_outbox

log = get_logger(__name__)

# The events a client endpoint may subscribe to (DATA-MODEL §6). Deliberately small:
# each one is a promise about payload shape we have to keep across versions.
EVENT_TYPES: tuple[str, ...] = (
    "lead.created",
    "lead.updated",
    "call.completed",
    "campaign.completed",
)

SIGNATURE_HEADER = "X-Calevate-Signature"
TIMESTAMP_HEADER = "X-Calevate-Timestamp"
EVENT_HEADER = "X-Calevate-Event"
DELIVERY_HEADER = "X-Calevate-Delivery"

# Receivers are third-party endpoints on Indian SMB infrastructure; slow is normal,
# hanging is not. The retry ladder is ARQ's, so the exhaustion threshold MUST be
# ARQ's budget — a local number larger than the real one means the last try does not
# know it is the last, and the exhausted alert never fires (found by the runbook
# audit, pinned by a test).
DELIVERY_TIMEOUT_S = 10.0
MAX_ATTEMPTS = WORKER_MAX_TRIES


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    delivered: bool
    status_code: int | None
    error: str | None = None


def sign_payload(secret: str, *, timestamp: str, body: str) -> str:
    """`t={ts},v1={hex}` — the timestamp is INSIDE the signed string.

    A signature over the body alone is a bearer token for that body forever. With the
    timestamp signed, a receiver that rejects old timestamps also rejects replays, and
    an attacker cannot move a valid signature onto a fresh timestamp.
    """
    mac = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


def verify_signature(secret: str, *, header: str, body: str, tolerance_s: int = 300) -> bool:
    """The receiver's side, shipped so our docs can point at real code (and so the
    tests assert the scheme rather than our implementation of it)."""
    parts = dict(piece.split("=", 1) for piece in header.split(",") if "=" in piece)
    timestamp, provided = parts.get("t"), parts.get("v1")
    if not timestamp or not provided:
        return False
    try:
        age = abs(int(datetime.now(UTC).timestamp()) - int(timestamp))
    except ValueError:
        return False
    if age > tolerance_s:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256)
    return hmac.compare_digest(expected.hexdigest(), provided)


def build_envelope(
    *, event: str, tenant_id: UUID, delivery_id: UUID, data: dict[str, Any]
) -> dict[str, Any]:
    """OUR envelope, stable across event types (D-23).

    `id` is the delivery id, not the object id, so a receiver deduplicating on it
    deduplicates RETRIES rather than collapsing two genuine updates to one lead.
    """
    return {
        "id": str(delivery_id),
        "event": event,
        "account_id": str(tenant_id),
        "created_at": datetime.now(UTC).isoformat(),
        "data": data,
    }


async def enqueue_event(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    event: str,
    data: dict[str, Any],
) -> int:
    """Fan the event out to every active endpoint subscribed to it — one outbox row per
    endpoint, in the caller's transaction.

    One row per endpoint rather than one per event: endpoints fail independently, and a
    shared row would make a dead endpoint retry deliveries that already succeeded
    elsewhere.
    """
    if event not in EVENT_TYPES:
        raise ValueError(f"unknown outbound event: {event}")

    endpoints = (
        (
            await session.execute(
                text(
                    "SELECT id FROM outbound_webhooks WHERE active = true AND kind = 'webhook' "
                    "AND :event = ANY(events)"
                ),
                {"event": event},
            )
        )
        .scalars()
        .all()
    )

    for endpoint_id in endpoints:
        await enqueue_outbox(
            session,
            queue="default",
            job="deliver_outbound_webhook",
            payload={
                "tenant_id": str(tenant_id),
                "endpoint_id": str(endpoint_id),
                "event": event,
                "data": data,
                # Minted HERE, not in the worker: ARQ replays the same payload on
                # retry, so a worker-side id would mint a new one per attempt and the
                # "one forensic row per delivery" claim would be false — and a receiver
                # deduplicating on it would treat every retry as a new event.
                "delivery_id": str(uuid7()),
            },
        )
    return len(endpoints)


async def load_endpoint(session: AsyncSession, endpoint_id: UUID) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                "SELECT id, url, secret_ref, mapping, active FROM outbound_webhooks WHERE id = :id"
            ),
            {"id": endpoint_id},
        )
    ).first()
    if row is None or not row[4]:
        return None
    return {"id": row[0], "url": row[1], "secret": row[2], "mapping": row[3] or {}}


def apply_mapping(data: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    """Rename our field names to the client's, if they asked us to.

    Absent mapping means our names. A mapping that names a field we did not send drops
    out silently rather than sending a null — a CRM column set to null on every sync is
    worse than a column that is simply not written.
    """
    if not mapping:
        return data
    renamed: dict[str, Any] = {}
    for ours, theirs in mapping.items():
        if ours in data:
            renamed[str(theirs)] = data[ours]
    return renamed


async def record_delivery(
    session: AsyncSession,
    *,
    delivery_id: UUID,
    endpoint_id: UUID,
    event: str,
    status: str,
    attempts: int,
    status_code: int | None,
) -> None:
    """Forensic log, upserted by delivery id so retries update one row (SEC-COMP §5).

    No payload column and no payload ref: the body is reconstructible from the domain
    row, and a table of un-redacted CRM payloads is a breach waiting for a query.
    """
    result = await session.execute(
        text(
            "UPDATE webhook_deliveries SET attempts = :attempts, status = :status, "
            "source = :src, last_at = now() WHERE id = :id"
        ),
        {
            "attempts": attempts,
            "status": status,
            "src": f"http_{status_code}" if status_code else "http",
            "id": delivery_id,
        },
    )
    if rowcount_of(result) == 0:
        await session.execute(
            text(
                "INSERT INTO webhook_deliveries (id, direction, source, event_type, status, "
                "attempts, endpoint_id, first_at, last_at, created_at) VALUES (:id, 'out', "
                ":src, :event, :status, :attempts, :endpoint, now(), now(), now())"
            ),
            {
                "id": delivery_id,
                "src": f"http_{status_code}" if status_code else "http",
                "event": event,
                "status": status,
                "attempts": attempts,
                "endpoint": endpoint_id,
            },
        )


async def deliver(
    *,
    url: str,
    secret: str,
    event: str,
    envelope: dict[str, Any],
    client: httpx.AsyncClient | None = None,
) -> DeliveryResult:
    """One signed POST. Raises nothing — the caller decides what a failure means.

    2xx is success. Everything else (including 3xx: a redirect to an unknown host is
    not a delivery we should follow with a signed body) is a failure the outbox retries.
    """
    body = json.dumps(envelope, separators=(",", ":"), default=str)
    timestamp = str(int(datetime.now(UTC).timestamp()))
    headers = {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: sign_payload(secret, timestamp=timestamp, body=body),
        TIMESTAMP_HEADER: timestamp,
        EVENT_HEADER: event,
        DELIVERY_HEADER: str(envelope["id"]),
        "User-Agent": "Calevate-Webhooks/1",
    }
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=DELIVERY_TIMEOUT_S, follow_redirects=False)
    try:
        response = await http.post(url, content=body, headers=headers)
        ok = 200 <= response.status_code < 300
        return DeliveryResult(
            delivered=ok,
            status_code=response.status_code,
            error=None if ok else f"HTTP {response.status_code}",
        )
    except httpx.HTTPError as exc:
        # The URL and the error TYPE are safe to log; the body never is.
        return DeliveryResult(delivered=False, status_code=None, error=type(exc).__name__)
    finally:
        if owns_client:
            await http.aclose()


def lead_payload(row: dict[str, Any], *, include_raw_phone: bool) -> dict[str, Any]:
    """What a `lead.*` event carries.

    `include_raw_phone` is a per-endpoint opt-in, not a default: hard rule 6 is about
    logs, but the same reasoning applies to anything leaving our boundary. A client who
    needs the number in their CRM says so once, in the config row, and that choice is
    auditable. Everyone else gets the masked form the dashboard shows.
    """
    payload = dict(row)
    if not include_raw_phone:
        masked = redact_mapping({"phone": payload.get("phone")})
        payload["phone"] = masked.get("phone")
    return payload


__all__ = [
    "DELIVERY_HEADER",
    "EVENT_HEADER",
    "EVENT_TYPES",
    "MAX_ATTEMPTS",
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "DeliveryResult",
    "apply_mapping",
    "build_envelope",
    "deliver",
    "enqueue_event",
    "lead_payload",
    "load_endpoint",
    "record_delivery",
    "sign_payload",
    "verify_signature",
]
