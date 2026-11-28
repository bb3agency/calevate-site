"""The events feed: every outbound event, readable by pulling (D-1049, MASTER-PLAN W2.7).

A receiver behind a firewall cannot take a webhook. It reads the same events here instead:
`list_events` pages through them after a known event, and `next_events` + `ack` give each
consumer (an API key) a durable cursor, so a consumer that acknowledges what it processed
reads every event once per cursor.

**One row per event, written by the fan-out** (`service.enqueue_events`) in the caller's
transaction, before and independent of any endpoint: a tenant with no endpoint at all still
has a feed. The row's `id` is the `event_id` every webhook delivery of the same event
carries, so a consumer using both dedupes on one key.

**Ordered by commit visibility, not by id.** A uuid7 id is minted when the event happens;
a transaction that minted an earlier id can commit after one that minted a later id, and a
cursor that had moved past the later one would never see the earlier. Each row records the
id of the transaction that wrote it (`txid`), and the feed serves only rows written by a
transaction older than every transaction still running (`VISIBLE_SQL`, the snapshot's
`xmin`): nothing can commit behind such a row any more. The order is `(txid, id)`. The
cost is that an event is readable once every transaction older than it has ended, which
under a long transaction is that transaction's length.

**Stored as the domain data, masked when read.** The fan-out masks per endpoint; the feed
cannot, because the reader is a key, not an endpoint. `data` is what the producer passed
(the raw phone included), and `serialize` masks the phone unless the caller says the reader
may have it. Transcripts and recording links are never in it: those are per-endpoint
opt-ins added after this row is written.

**Kept 30 days**, deleted by `workers/webhooks_feed.sweep_integration_events`, and deleted
by a data principal's erasure (`workers/retention._erase_integration_events`). Rows are
never updated (a trigger refuses it), but they are deleted, so the table is not one of the
append-only ledgers.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

#: How long an event stays readable.
FEED_RETENTION: Final = timedelta(days=30)
#: The most events one read returns.
FEED_PAGE_MAX: Final = 100
FEED_PAGE_DEFAULT: Final = 50

#: Rows whose writing transaction can no longer have anything commit before it.
VISIBLE_SQL: Final = "e.txid < (pg_snapshot_xmin(pg_current_snapshot())::text)::bigint"
#: Still inside the retention window (the sweep may not have run yet).
IN_WINDOW_SQL: Final = "e.created_at > now() - CAST(:retention AS interval)"

#: Namespace for the ids of events that happen at most once per subject (`once_key`).
_ONCE_NAMESPACE: Final = uuid.UUID("0f6b7d36-1c1e-4d0e-9a51-3d2a2c7b9e10")


def once_event_id(once_key: str) -> UUID:
    """The fixed id of an event that happens at most once (`call.not_connected` for one
    call). A re-run of the producer inserts the same id, which the table refuses, and the
    fan-out skips it: the database decides, as `enqueue_outbox_once` does."""
    return uuid.uuid5(_ONCE_NAMESPACE, once_key)


def _uuid_or_none(value: Any) -> str | None:
    """A subject id lifted into its column only when it is one; the body keeps it anyway."""
    try:
        return str(UUID(str(value))) if value else None
    except ValueError:
        return None


def _subject_ids(data: dict[str, Any]) -> tuple[str | None, str | None]:
    return _uuid_or_none(data.get("lead_id")), _uuid_or_none(data.get("call_id"))


async def record_events(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    event: str,
    rows: Sequence[dict[str, Any]],
    once_keys: Sequence[str | None] | None = None,
) -> list[UUID | None]:
    """One feed row per object, in the caller's transaction. Returns each row's event id,
    or None where `once_keys` named an event that was already recorded.

    `lead_id` and `call_id` are lifted out of `data` into columns so an erasure finds the
    row by the subject's lead or call without parsing JSON."""
    keys = list(once_keys) if once_keys is not None else [None] * len(rows)
    ids: list[UUID | None] = []
    for data, once_key in zip(rows, keys, strict=True):
        event_id = once_event_id(once_key) if once_key else uuid7()
        lead_id, call_id = _subject_ids(data)
        inserted = (
            await session.execute(
                text(
                    "INSERT INTO integration_events (id, tenant_id, event_type, data, lead_id, "
                    "call_id, created_at) VALUES (:id, :tid, :event, CAST(:data AS jsonb), "
                    "CAST(:lead AS uuid), CAST(:call AS uuid), now()) "
                    "ON CONFLICT (id) DO NOTHING RETURNING id"
                ),
                {
                    "id": event_id,
                    "tid": tenant_id,
                    "event": event,
                    "data": json.dumps(data, default=str),
                    "lead": lead_id,
                    "call": call_id,
                },
            )
        ).first()
        ids.append(event_id if inserted is not None else None)
    return ids


@dataclass(frozen=True, slots=True)
class FeedEvent:
    id: UUID
    event: str
    created_at: datetime
    data: dict[str, Any]


def serialize(
    row: FeedEvent, *, tenant_id: UUID, include_raw_phone: bool = False
) -> dict[str, Any]:
    """The webhook envelope's shape (WEBHOOKS §1.2), with the feed's own `id` = `event_id`."""
    from apps.api.integrations.service import lead_payload

    return {
        "id": str(row.id),
        "event_id": str(row.id),
        "event": row.event,
        "account_id": str(tenant_id),
        "created_at": row.created_at.isoformat(),
        "data": lead_payload(row.data, include_raw_phone=include_raw_phone),
    }


_SELECT: Final = "SELECT e.id, e.event_type, e.created_at, e.data FROM integration_events e "


def _rows(result: Sequence[Any]) -> list[FeedEvent]:
    return [
        FeedEvent(id=UUID(str(r[0])), event=str(r[1]), created_at=r[2], data=dict(r[3] or {}))
        for r in result
    ]


def _bounded(limit: int) -> int:
    return max(1, min(int(limit), FEED_PAGE_MAX))


async def _position(session: AsyncSession, event_id: UUID) -> tuple[int, UUID]:
    """Where an event sits in the feed. Not found: swept, erased, not yet visible, or
    another account's (RLS makes the last indistinguishable on purpose)."""
    row = (
        await session.execute(
            text(
                f"SELECT e.txid, e.id FROM integration_events e WHERE e.id = :id AND {VISIBLE_SQL}"
            ),
            {"id": event_id},
        )
    ).first()
    if row is None:
        raise ProblemError(
            kind="not_found",
            code="feed_event_unknown",
            title="That event is not in the feed",
            detail=(
                "No event with that id can be read: it is older than 30 days, was erased, "
                "or is not one of this account's."
            ),
            remediation="Read from the start of the feed again, without `after`.",
        )
    return int(row[0]), UUID(str(row[1]))


async def list_events(
    session: AsyncSession,
    *,
    after: UUID | None = None,
    event_type: str | None = None,
    limit: int = FEED_PAGE_DEFAULT,
) -> list[FeedEvent]:
    """Events after `after` (exclusive), oldest first, optionally of one type. Runs inside
    the reader's `tenant_session`: RLS is the tenant scoping."""
    params: dict[str, Any] = {"limit": _bounded(limit), "retention": FEED_RETENTION}
    clauses = [VISIBLE_SQL, IN_WINDOW_SQL]
    if after is not None:
        txid, last_id = await _position(session, after)
        clauses.append("(e.txid, e.id) > (:txid, :last_id)")
        params.update(txid=txid, last_id=last_id)
    if event_type is not None:
        clauses.append("e.event_type = :event_type")
        params["event_type"] = event_type
    result = (
        await session.execute(
            text(
                _SELECT + "WHERE " + " AND ".join(clauses) + " ORDER BY e.txid, e.id LIMIT :limit"
            ),
            params,
        )
    ).all()
    return _rows(result)


@dataclass(frozen=True, slots=True)
class Cursor:
    consumer_id: UUID
    after_event_id: UUID | None
    updated_at: datetime | None


async def read_cursor(session: AsyncSession, *, consumer_id: UUID) -> Cursor:
    row = (
        await session.execute(
            text(
                "SELECT after_event_id, updated_at FROM integration_event_cursors "
                "WHERE consumer_id = :cid"
            ),
            {"cid": consumer_id},
        )
    ).first()
    if row is None:
        return Cursor(consumer_id=consumer_id, after_event_id=None, updated_at=None)
    return Cursor(
        consumer_id=consumer_id,
        after_event_id=UUID(str(row[0])) if row[0] else None,
        updated_at=row[1],
    )


async def next_events(
    session: AsyncSession,
    *,
    consumer_id: UUID,
    event_type: str | None = None,
    limit: int = FEED_PAGE_DEFAULT,
) -> list[FeedEvent]:
    """The events after this consumer's cursor. Reading moves nothing: the cursor moves
    only on `ack`, so a consumer that crashes before acknowledging reads the same events
    again. The cursor is a stored position, so an event swept since it was acknowledged
    does not lose the consumer its place."""
    params: dict[str, Any] = {
        "limit": _bounded(limit),
        "retention": FEED_RETENTION,
        "cid": consumer_id,
    }
    clauses = [
        VISIBLE_SQL,
        IN_WINDOW_SQL,
        "NOT EXISTS (SELECT 1 FROM integration_event_cursors c WHERE c.consumer_id = :cid "
        "AND c.after_txid IS NOT NULL AND (e.txid, e.id) <= (c.after_txid, c.after_event_id))",
    ]
    if event_type is not None:
        clauses.append("e.event_type = :event_type")
        params["event_type"] = event_type
    result = (
        await session.execute(
            text(
                _SELECT + "WHERE " + " AND ".join(clauses) + " ORDER BY e.txid, e.id LIMIT :limit"
            ),
            params,
        )
    ).all()
    return _rows(result)


async def ack(
    session: AsyncSession, *, tenant_id: UUID, consumer_id: UUID, event_id: UUID
) -> Cursor:
    """Move this consumer's cursor to `event_id`, forward only.

    An acknowledgement behind the cursor (a retried ack, a second worker) leaves it where it
    is: the upsert's WHERE compares positions, so two concurrent acks end on the later one
    whichever commits last."""
    txid, last_id = await _position(session, event_id)
    await session.execute(
        text(
            "INSERT INTO integration_event_cursors (consumer_id, tenant_id, after_txid, "
            "after_event_id, created_at, updated_at) VALUES (:cid, :tid, :txid, :eid, now(), "
            "now()) ON CONFLICT (consumer_id) DO UPDATE SET after_txid = EXCLUDED.after_txid, "
            "after_event_id = EXCLUDED.after_event_id, updated_at = now() "
            "WHERE integration_event_cursors.after_txid IS NULL "
            "OR (integration_event_cursors.after_txid, integration_event_cursors.after_event_id) "
            "< (EXCLUDED.after_txid, EXCLUDED.after_event_id)"
        ),
        {"cid": consumer_id, "tid": tenant_id, "txid": txid, "eid": last_id},
    )
    return await read_cursor(session, consumer_id=consumer_id)


__all__ = [
    "FEED_PAGE_DEFAULT",
    "FEED_PAGE_MAX",
    "FEED_RETENTION",
    "Cursor",
    "FeedEvent",
    "ack",
    "list_events",
    "next_events",
    "once_event_id",
    "read_cursor",
    "record_events",
    "serialize",
]
