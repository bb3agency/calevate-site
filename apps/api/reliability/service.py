"""The reliability triad (BACKEND-PATTERNS §4) + the CAS primitive (§5).

Three mechanisms, one idea: **at-least-once delivery plus idempotent consumers is
effectively exactly-once**, and every claim is a conditional UPDATE whose `rowcount ==
0` means "another worker won" — never an exception, never a lock held across a
network call.

- **Idempotency** guards client-initiated mutations (call-this-lead, campaign launch,
  KB publish): the same key replays the stored response instead of dialling twice.
- **Outbox** makes side effects survive a crash: the row is written in the SAME
  transaction as the domain write, so "lead created but notification lost" cannot
  happen. A separate dispatcher publishes it.
- **Inbox** dedupes provider events. Bolna webhooks are at-most-once and unsigned
  (D-31), so this is where an execution_id becomes a single unit of work.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert, record_outbox_dlq_depth, record_outbox_lag
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of

log = get_logger(__name__)

IDEMPOTENCY_TTL = timedelta(hours=24)
OUTBOX_MAX_ATTEMPTS = 5
OUTBOX_BATCH = 50


def body_hash(payload: Any) -> str:
    """Stable hash of a request/event body. Sorted keys so key order is not a
    'different request'."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def scope_key(*, tenant_id: UUID | None, user_id: UUID | None) -> str:
    """HMAC fingerprint of tenant/user — RAW IDS ARE NEVER STORED in the idempotency
    table (§4). Two tenants sending the same Idempotency-Key stay independent."""
    settings = get_settings()
    material = (settings.audit_chain_secret or f"local-dev:{settings.app_env}").encode()
    return hmac.new(material, f"{tenant_id}:{user_id}".encode(), hashlib.sha256).hexdigest()


# --- Idempotency --------------------------------------------------------------

IdempotencyState = Literal["fresh", "replay"]


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    state: IdempotencyState
    record_id: UUID
    response_status: int | None = None
    response_payload: dict[str, Any] | None = None


async def claim_idempotency(
    session: AsyncSession,
    *,
    scope: str,
    route: str,
    method: str,
    key: str,
    request_hash: str,
) -> IdempotencyClaim:
    """Returns `fresh` (caller does the work) or `replay` (caller returns the stored
    response with `Idempotent-Replayed: true`).

    409s, both deliberate:
    - same key + DIFFERENT body → the client reused a key for a new request;
    - status PROCESSING → the first attempt is still in flight.
    """
    record_id = uuid7()
    inserted = await session.execute(
        text(
            "INSERT INTO idempotency_records (id, scope_key, route, method, idempotency_key, "
            "request_hash, status, expires_at, created_at, updated_at) "
            "VALUES (:id, :scope, :route, :method, :key, :hash, 'processing', :expires, "
            "now(), now()) "
            "ON CONFLICT (scope_key, route, method, idempotency_key) DO NOTHING "
            "RETURNING id"
        ),
        {
            "id": record_id,
            "scope": scope,
            "route": route,
            "method": method,
            "key": key,
            "hash": request_hash,
            "expires": datetime.now(UTC) + IDEMPOTENCY_TTL,
        },
    )
    if inserted.first() is not None:
        return IdempotencyClaim(state="fresh", record_id=record_id)

    existing = (
        await session.execute(
            text(
                "SELECT id, request_hash, status, response_status, response_payload "
                "FROM idempotency_records WHERE scope_key = :scope AND route = :route "
                "AND method = :method AND idempotency_key = :key"
            ),
            {"scope": scope, "route": route, "method": method, "key": key},
        )
    ).first()
    if existing is None:  # pragma: no cover — TTL sweep raced the conflict
        return IdempotencyClaim(state="fresh", record_id=record_id)

    found_id, found_hash, status, response_status, response_payload = existing
    if found_hash != request_hash:
        raise ProblemError.conflict(
            "idempotency_key_reused",
            "This Idempotency-Key was already used for a different request body.",
            remediation="Use a fresh key for a new request.",
        )
    if status == "processing":
        raise ProblemError(
            kind="conflict",
            code="idempotent_request_in_flight",
            title="Request already in progress",
            detail="An identical request is still being processed.",
            remediation="Retry in a few seconds.",
            headers={"Retry-After": "3"},
        )
    if status == "failed":
        # CAS the failed record back to processing; whoever wins retries.
        retried = await session.execute(
            text(
                "UPDATE idempotency_records SET status = 'processing', updated_at = now() "
                "WHERE id = :id AND status = 'failed'"
            ),
            {"id": found_id},
        )
        if rowcount_of(retried) == 0:
            raise ProblemError.conflict(
                "idempotent_request_in_flight", "An identical request is being retried."
            )
        return IdempotencyClaim(state="fresh", record_id=found_id)

    return IdempotencyClaim(
        state="replay",
        record_id=found_id,
        response_status=response_status,
        response_payload=response_payload,
    )


async def complete_idempotency(
    session: AsyncSession,
    *,
    record_id: UUID,
    response_status: int,
    response_payload: dict[str, Any],
) -> None:
    await session.execute(
        text(
            "UPDATE idempotency_records SET status = 'completed', response_status = :status, "
            "response_payload = CAST(:payload AS jsonb), updated_at = now() WHERE id = :id"
        ),
        {"id": record_id, "status": response_status, "payload": json.dumps(response_payload)},
    )


async def fail_idempotency(session: AsyncSession, *, record_id: UUID) -> None:
    await session.execute(
        text("UPDATE idempotency_records SET status = 'failed', updated_at = now() WHERE id = :id"),
        {"id": record_id},
    )


async def sweep_idempotency(session: AsyncSession) -> int:
    result = await session.execute(text("DELETE FROM idempotency_records WHERE expires_at < now()"))
    return int(rowcount_of(result) or 0)


# --- Outbox -------------------------------------------------------------------


async def enqueue_outbox(
    session: AsyncSession,
    *,
    queue: str,
    job: str,
    payload: dict[str, Any],
) -> UUID:
    """Write the side effect in the CALLER'S transaction. Do not commit here — the
    whole point is that this row and the domain write share a fate."""
    message_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO outbox_messages (id, queue, job, payload, status, attempt_count, "
            "created_at, updated_at) VALUES (:id, :queue, :job, CAST(:payload AS jsonb), "
            "'pending', 0, now(), now())"
        ),
        {"id": message_id, "queue": queue, "job": job, "payload": json.dumps(payload)},
    )
    return message_id


@dataclass(frozen=True, slots=True)
class OutboxMessageRow:
    id: UUID
    queue: str
    job: str
    payload: dict[str, Any]
    attempt_count: int


async def claim_outbox_batch(
    session: AsyncSession, *, limit: int = OUTBOX_BATCH
) -> list[OutboxMessageRow]:
    """Oldest-first claim by conditional UPDATE. `attempt_count` bumps on claim, so a
    message that keeps killing its worker still walks to the DLQ instead of looping.

    MATERIALIZED + a tiebreak on `id` for the same reason as the campaign dispatcher's
    claim: `WHERE id IN (SELECT ... LIMIT :n FOR UPDATE SKIP LOCKED)` lets the planner
    rescan the LIMIT subquery per candidate row, and outbox rows enqueued in one
    transaction share `created_at` to the microsecond — so each rescan breaks the tie
    differently and the batch comes back larger than `limit`. Here that is a latency
    spike rather than corruption, but `limit` should mean what it says.
    """
    rows = (
        await session.execute(
            text(
                "WITH picked AS MATERIALIZED ("
                "  SELECT id FROM outbox_messages WHERE status = 'pending' "
                "  ORDER BY created_at, id LIMIT :limit FOR UPDATE SKIP LOCKED"
                ") "
                "UPDATE outbox_messages o SET attempt_count = o.attempt_count + 1, "
                "updated_at = now() FROM picked WHERE o.id = picked.id "
                "RETURNING o.id, o.queue, o.job, o.payload, o.attempt_count"
            ),
            {"limit": limit},
        )
    ).all()
    return [
        OutboxMessageRow(id=r[0], queue=r[1], job=r[2], payload=r[3] or {}, attempt_count=r[4])
        for r in rows
    ]


async def mark_outbox_published(session: AsyncSession, *, message_id: UUID, job_id: str) -> None:
    await session.execute(
        text(
            "UPDATE outbox_messages SET status = 'published', job_id = :job_id, "
            "published_at = now(), updated_at = now() WHERE id = :id AND status = 'pending'"
        ),
        {"id": message_id, "job_id": job_id},
    )


async def mark_outbox_failed(
    session: AsyncSession, *, message_id: UUID, error: str, attempt_count: int
) -> None:
    """< OUTBOX_MAX_ATTEMPTS stays pending (retried next tick); at the ceiling it goes
    to `failed` — the outbox DLQ — and alerts. Ops replays a DLQ row by flipping it
    back to pending with an audit note."""
    terminal = attempt_count >= OUTBOX_MAX_ATTEMPTS
    await session.execute(
        text(
            "UPDATE outbox_messages SET status = :status, last_error = :error, "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": message_id, "status": "failed" if terminal else "pending", "error": error[:500]},
    )
    if terminal:
        alert(
            "OUTBOX_DISPATCH",
            "outbox_dead_letter",
            detail=error[:200],
            message_id=str(message_id),
        )


async def record_outbox_metrics(session: AsyncSession) -> None:
    row = (
        await session.execute(
            text(
                "SELECT COALESCE(EXTRACT(EPOCH FROM (now() - MIN(created_at))), 0) "
                "FROM outbox_messages WHERE status = 'pending'"
            )
        )
    ).first()
    record_outbox_lag(float(row[0]) if row else 0.0)
    dlq = (
        await session.execute(text("SELECT count(*) FROM outbox_messages WHERE status = 'failed'"))
    ).scalar()
    record_outbox_dlq_depth(int(dlq or 0))


async def replay_dead_letters(session: AsyncSession, *, limit: int = 100) -> int:
    """The ops "replay dead letter" action. Attempts reset so the message gets a fresh
    budget; the caller writes the audit note."""
    result = await session.execute(
        text(
            "UPDATE outbox_messages SET status = 'pending', attempt_count = 0, "
            "updated_at = now() WHERE id IN (SELECT id FROM outbox_messages "
            "WHERE status = 'failed' ORDER BY created_at LIMIT :limit)"
        ),
        {"limit": limit},
    )
    return int(rowcount_of(result) or 0)


# --- Webhook inbox ------------------------------------------------------------

InboxState = Literal["claimed", "duplicate"]


@dataclass(frozen=True, slots=True)
class InboxClaim:
    state: InboxState
    row_id: UUID


async def claim_inbox_event(
    session: AsyncSession,
    *,
    provider: str,
    event_key: str,
    payload_hash: str,
    event_name: str | None = None,
) -> InboxClaim:
    """Durable dedupe. Same (provider, event_key) with a DIFFERENT payload_hash is a
    409 — that is a spoof or corruption signal, not a retry (§4).

    A previously FAILED row is re-claimable via CAS: engine events are at-most-once,
    so a failed processing attempt must not permanently poison the key.
    """
    row_id = uuid7()
    inserted = await session.execute(
        text(
            "INSERT INTO webhook_inbox_events (id, provider, event_key, payload_hash, status, "
            "event_name, created_at, updated_at) VALUES (:id, :provider, :key, :hash, "
            "'processing', :name, now(), now()) "
            "ON CONFLICT (provider, event_key) DO NOTHING RETURNING id"
        ),
        {
            "id": row_id,
            "provider": provider,
            "key": event_key,
            "hash": payload_hash,
            "name": event_name,
        },
    )
    if inserted.first() is not None:
        return InboxClaim(state="claimed", row_id=row_id)

    existing = (
        await session.execute(
            text(
                "SELECT id, payload_hash, status FROM webhook_inbox_events "
                "WHERE provider = :provider AND event_key = :key"
            ),
            {"provider": provider, "key": event_key},
        )
    ).first()
    if existing is None:  # pragma: no cover
        return InboxClaim(state="claimed", row_id=row_id)

    found_id, found_hash, status = existing
    if found_hash != payload_hash:
        # NOT an error we swallow: an identical event id with different content means
        # someone is replaying a doctored payload at an unsigned endpoint (D-31).
        alert("ROUTE_HANDLER", "webhook_payload_mismatch", provider=provider, event_key=event_key)
        raise ProblemError.conflict(
            "webhook_payload_mismatch",
            "This event id was already received with different content.",
        )
    if status == "failed":
        retried = await session.execute(
            text(
                "UPDATE webhook_inbox_events SET status = 'processing', updated_at = now() "
                "WHERE id = :id AND status = 'failed'"
            ),
            {"id": found_id},
        )
        if rowcount_of(retried):
            return InboxClaim(state="claimed", row_id=found_id)
    # Make the retry visible: the activity view's "deduplicated" count is this
    # counter, and without it a vendor retrying fifteen times looks like one quiet
    # arrival and a client concluding that events vanish.
    await session.execute(
        text(
            "UPDATE webhook_inbox_events SET duplicate_count = duplicate_count + 1, "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": found_id},
    )
    return InboxClaim(state="duplicate", row_id=found_id)


async def mark_inbox_enqueued(session: AsyncSession, *, row_id: UUID) -> None:
    await session.execute(
        text(
            "UPDATE webhook_inbox_events SET status = 'enqueued', enqueued_at = now(), "
            "updated_at = now() WHERE id = :id AND status = 'processing'"
        ),
        {"id": row_id},
    )


async def mark_inbox_processed(session: AsyncSession, *, row_id: UUID) -> None:
    await session.execute(
        text(
            "UPDATE webhook_inbox_events SET status = 'processed', processed_at = now(), "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": row_id},
    )


async def mark_inbox_failed(session: AsyncSession, *, row_id: UUID, error: str) -> None:
    await session.execute(
        text(
            "UPDATE webhook_inbox_events SET status = 'failed', last_error = :error, "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": row_id, "error": error[:500]},
    )


__all__ = [
    "IDEMPOTENCY_TTL",
    "OUTBOX_MAX_ATTEMPTS",
    "IdempotencyClaim",
    "InboxClaim",
    "OutboxMessageRow",
    "body_hash",
    "claim_idempotency",
    "claim_inbox_event",
    "claim_outbox_batch",
    "complete_idempotency",
    "enqueue_outbox",
    "fail_idempotency",
    "mark_inbox_enqueued",
    "mark_inbox_failed",
    "mark_inbox_processed",
    "mark_outbox_failed",
    "mark_outbox_published",
    "record_outbox_metrics",
    "replay_dead_letters",
    "scope_key",
    "sweep_idempotency",
]
