"""The API activity log's two halves: a Redis stream the request path appends to, and the
worker that moves it into `api_requests` (W2.8, D-1047).

WHY A STREAM AND NOT AN INSERT. The row is written after the response, but on the same
event loop; an INSERT there is a pool checkout and a transaction for every public request,
and a slow database would make every integration slow to log what it did. One XADD is a
single round trip to Redis. If Redis is down the entry is lost and the request is not:
this log is for the integrator's convenience, and the ledger of what a key DID is
`audit_log`, written in the request's own transaction.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.dnc import live_tenant_ids
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session
from apps.api.public_api.models import RETENTION_DAYS

log = get_logger(__name__)

STREAM: Final = "calevate:api_requests"
#: The stream is a buffer, not a store: trimmed near this length so a stopped worker
#: costs bounded memory. Roughly two hours of a busy account at its full rate.
STREAM_MAXLEN: Final = 200_000
FLUSH_BATCH: Final = 1000
#: Batches one flush tick moves at most, so a backlog drains over ticks.
FLUSH_BATCHES: Final = 10
SWEEP_BATCH: Final = 5000
#: What the console's activity list shows, at most.
ACTIVITY_LIMIT: Final = 100
HEALTH_WINDOW: Final = timedelta(hours=24)

_FIELDS: Final = (
    "tenant_id",
    "api_key_id",
    "method",
    "route",
    "status",
    "problem_code",
    "remediation",
    "trace_id",
    "latency_ms",
    "replayed",
    "api_version",
    "at",
)


async def record(entry: dict[str, str]) -> None:
    """Append one request. Never raises: a log we could not write is not a failed request."""
    try:
        await get_redis().xadd(STREAM, entry, maxlen=STREAM_MAXLEN, approximate=True)  # type: ignore[arg-type]
    except Exception:
        log.warning("api_activity_unavailable")


def _decoded(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _row(stream_id: str, fields: dict[str, str]) -> dict[str, Any] | None:
    try:
        return {
            "id": uuid7(),
            "stream_id": stream_id,
            "tid": UUID(fields["tenant_id"]),
            "kid": UUID(fields["api_key_id"]),
            "method": fields["method"],
            "route": fields["route"][:200],
            "status": int(fields["status"]),
            "code": fields.get("problem_code") or None,
            "remediation": (fields.get("remediation") or "")[:300] or None,
            "trace": (fields.get("trace_id") or "")[:64] or None,
            "latency": max(0, int(fields["latency_ms"])),
            "replayed": fields.get("replayed") == "1",
            "version": fields["api_version"][:10],
            "at": datetime.fromisoformat(fields["at"]),
        }
    except (KeyError, ValueError):
        return None


# Inserted only while the key exists: a key deleted between the request and the flush
# takes its log with it (the FK cascades), and the row would otherwise fail the batch.
_INSERT: Final = (
    "INSERT INTO api_requests (id, tenant_id, api_key_id, stream_id, method, route, status, "
    "problem_code, remediation, trace_id, latency_ms, replayed, api_version, created_at) "
    "SELECT :id, :tid, :kid, :stream_id, :method, :route, :status, :code, :remediation, "
    ":trace, :latency, :replayed, :version, :at "
    "WHERE EXISTS (SELECT 1 FROM api_keys WHERE id = :kid) "
    "ON CONFLICT (stream_id) DO NOTHING"
)


async def flush(*, batch: int = FLUSH_BATCH, batches: int = FLUSH_BATCHES) -> int:
    """Move buffered entries into `api_requests`, each under its own tenant's session.

    At-least-once and idempotent: entries are deleted from the stream only after their
    tenant's transaction commits, and `stream_id` is unique, so a retried flush skips what
    an interrupted one already wrote."""
    redis = get_redis()
    moved = 0
    for _ in range(batches):
        entries = await redis.xrange(STREAM, count=batch)
        if not entries:
            break
        by_tenant: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        done: list[str] = []
        for raw_id, raw_fields in entries:
            stream_id = _decoded(raw_id)
            row = _row(stream_id, {_decoded(k): _decoded(v) for k, v in raw_fields.items()})
            done.append(stream_id)
            if row is None:
                log.warning("api_activity_malformed_entry")
                continue
            by_tenant[row["tid"]].append(row)
        for tenant_id, rows in by_tenant.items():
            async with tenant_session(tenant_id) as session:
                await session.execute(text(_INSERT), rows)
            moved += len(rows)
        await redis.xdel(STREAM, *done)
        if len(entries) < batch:
            break
    return moved


async def sweep_expired(*, now: datetime | None = None) -> int:
    """Delete rows older than `RETENTION_DAYS`, account by account."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=RETENTION_DAYS)
    async with admin_session() as directory:
        tenants = await live_tenant_ids(directory)
    removed = 0
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as session:
            result = await session.execute(
                text(
                    "DELETE FROM api_requests WHERE id IN (SELECT id FROM api_requests "
                    "WHERE created_at < :cutoff ORDER BY created_at LIMIT :n)"
                ),
                {"cutoff": cutoff, "n": SWEEP_BATCH},
            )
            removed += int(getattr(result, "rowcount", 0) or 0)
    return removed


@dataclass(frozen=True, slots=True)
class ActivityRow:
    id: UUID
    api_key_id: UUID
    method: str
    route: str
    status: int
    problem_code: str | None
    remediation: str | None
    trace_id: str | None
    latency_ms: int
    replayed: bool
    created_at: datetime


async def list_activity(
    session: AsyncSession,
    *,
    api_key_id: UUID | None,
    failed_only: bool,
    limit: int = ACTIVITY_LIMIT,
) -> list[ActivityRow]:
    rows = (
        await session.execute(
            text(
                "SELECT id, api_key_id, method, route, status, problem_code, remediation, "
                "trace_id, latency_ms, replayed, created_at FROM api_requests "
                "WHERE (CAST(:kid AS uuid) IS NULL OR api_key_id = CAST(:kid AS uuid)) "
                "AND (NOT :failed OR status >= 400) ORDER BY created_at DESC, id DESC LIMIT :n"
            ),
            {"kid": api_key_id, "failed": failed_only, "n": min(limit, ACTIVITY_LIMIT)},
        )
    ).all()
    return [ActivityRow(*r) for r in rows]


@dataclass(frozen=True, slots=True)
class KeyHealth:
    requests: int
    failed: int
    last_rate_limited_at: datetime | None


async def key_health(
    session: AsyncSession, *, now: datetime | None = None
) -> dict[UUID, KeyHealth]:
    """Per key, over the last 24 hours: requests, failures, and the last 429."""
    since = (now or datetime.now(UTC)) - HEALTH_WINDOW
    rows = (
        await session.execute(
            text(
                "SELECT api_key_id, count(*), count(*) FILTER (WHERE status >= 400), "
                "max(created_at) FILTER (WHERE status = 429) FROM api_requests "
                "WHERE created_at >= :since GROUP BY api_key_id"
            ),
            {"since": since},
        )
    ).all()
    return {UUID(str(r[0])): KeyHealth(int(r[1]), int(r[2]), r[3]) for r in rows}


__all__ = [
    "ACTIVITY_LIMIT",
    "STREAM",
    "ActivityRow",
    "KeyHealth",
    "flush",
    "key_health",
    "list_activity",
    "record",
    "sweep_expired",
]
