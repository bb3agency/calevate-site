"""What an API key may do with webhooks and the events feed (D-1049, MASTER-PLAN W2.6, W2.7).

THE HOOK FOR THE `/api/v1` ROUTER. Keys, their scopes and the machine principal are built
beside this (lane B1, `apps/api/api_keys/**`, `apps/api/public_api/**`); this module is
the integrations half and is called from there. It mounts nothing itself:

* `create_machine_endpoint`, `deactivate_machine_endpoint` — behind the `webhooks:manage`
  scope (`MACHINE_SCOPE`).
* `build_events_router(principal_dep, consumer_id_of, may_read_raw_phone)` — the feed's
  three routes, with the key's own auth dependency passed in, so B1's router includes it
  with `router.include_router(build_events_router(...))`.

**A key creates only endpoints that carry no call content.** A person turning on a
recording link or a transcript for a destination types an emailed code for that act
(D-730); a key cannot type one, so an endpoint a key creates has every opt-in off and
cannot subscribe to `call.recording_ready`, which exists to carry the link. Switching any
of them on later is the person's edit on the Integrations screen. A key deactivates only an
endpoint a key created: a destination a person set up is the person's to remove.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.schemas import Strict
from apps.api.integrations import feed, service

#: The scope a key needs to create and remove endpoints.
MACHINE_SCOPE: Final = "webhooks:manage"
#: The scope a key needs to read the events feed.
FEED_SCOPE: Final = "events:read"
#: Events a key may not subscribe an endpoint to (see the module docstring).
MACHINE_REFUSED_EVENTS: Final = frozenset({service.RECORDING_READY_EVENT})

ENDPOINT_CREATED_BY_KEY: Final = "integration_endpoint.created_by_key"
ENDPOINT_DISABLED_BY_KEY: Final = "integration_endpoint.disabled_by_key"


async def create_machine_endpoint(
    session: AsyncSession,
    *,
    actor: Principal,
    tenant_id: UUID,
    key_id: UUID,
    url: str,
    events: Sequence[str],
    auto_subscribe_new_events: bool = False,
    ip: str | None = None,
) -> service.CreatedEndpoint:
    """A webhook endpoint created by an API key: base bodies only, audited with the key."""
    refused = sorted(set(events) & MACHINE_REFUSED_EVENTS)
    if refused:
        raise ProblemError.forbidden(
            "An API key cannot subscribe to "
            + ", ".join(refused)
            + ": it carries a recording link, which a person switches on with a code."
        )
    # `*` for a key expands without the recording-ready event (no recording opt-in).
    created = await service.create_webhook_endpoint(
        session,
        tenant_id=tenant_id,
        url=url,
        events=events,
        include_recording_url=False,
        include_transcript=False,
        include_raw_transcript=False,
        role=None,
        auto_subscribe_new_events=auto_subscribe_new_events,
        managed_by_key_id=key_id,
    )
    await write_audit(
        session,
        action=ENDPOINT_CREATED_BY_KEY,
        actor=actor,
        tenant_id=tenant_id,
        object_type="outbound_webhook",
        object_id=str(created.id),
        ip=ip,
        summary={
            "key_id": str(key_id),
            "host": created.host,
            "port": created.port,
            "events": ",".join(sorted(created.events)),
            "auto_subscribe_new_events": auto_subscribe_new_events,
        },
    )
    return created


async def deactivate_machine_endpoint(
    session: AsyncSession,
    *,
    actor: Principal,
    tenant_id: UUID,
    key_id: UUID,
    endpoint_id: UUID,
    ip: str | None = None,
) -> bool:
    """Deactivate an endpoint a key created. True when this call switched it off."""
    managed = (
        await session.execute(
            text("SELECT managed_by_key_id IS NOT NULL FROM outbound_webhooks WHERE id = :id"),
            {"id": endpoint_id},
        )
    ).scalar()
    if managed is None:
        raise ProblemError.not_found("Endpoint")
    if not managed:
        raise ProblemError.forbidden(
            "This destination was set up by a person; remove it on the Integrations screen."
        )
    changed = await service.deactivate_endpoint(session, endpoint_id=endpoint_id)
    if changed:
        await write_audit(
            session,
            action=ENDPOINT_DISABLED_BY_KEY,
            actor=actor,
            tenant_id=tenant_id,
            object_type="outbound_webhook",
            object_id=str(endpoint_id),
            ip=ip,
            summary={"key_id": str(key_id)},
        )
    return changed


# --- the events feed's routes, for the `/api/v1` router ------------------------------

FeedEventName = Literal[
    "lead.created",
    "lead.updated",
    "call.completed",
    "call.updated",
    "call.recording_ready",
    "campaign.completed",
    "call.not_connected",
    "call.inbound_missed",
    "campaign.status_changed",
    "lead.consent_changed",
    "dnc.added",
]


class FeedEventOut(Strict):
    """One event in the webhook envelope's shape (WEBHOOKS §1.2). `id` and `event_id` are
    the same value: the `event_id` every webhook delivery of this event carries."""

    id: UUID
    event_id: UUID
    event: str
    account_id: UUID
    created_at: str
    data: dict[str, Any]


class FeedPageOut(Strict):
    events: list[FeedEventOut]
    #: Pass as `after` to read on; None when this page was empty.
    next_after: UUID | None


class FeedAckIn(Strict):
    event_id: UUID


class FeedCursorOut(Strict):
    #: The last event this key acknowledged; None before the first ack.
    after_event_id: UUID | None


def _page(rows: list[feed.FeedEvent], *, tenant_id: UUID, raw_phone: bool) -> FeedPageOut:
    return FeedPageOut(
        events=[
            FeedEventOut.model_validate(
                feed.serialize(row, tenant_id=tenant_id, include_raw_phone=raw_phone)
            )
            for row in rows
        ],
        next_after=rows[-1].id if rows else None,
    )


_Session = Annotated[AsyncSession, Depends(db)]


def build_events_router(
    principal_dep: Callable[..., Any],
    *,
    consumer_id_of: Callable[[Principal], UUID],
    may_read_raw_phone: Callable[[Principal], bool] = lambda _principal: False,
) -> APIRouter:
    """`GET /events`, `GET /events/next`, `POST /events/next/ack` for a key-authenticated
    router. `principal_dep` is the key's auth dependency (it enforces `FEED_SCOPE`);
    `consumer_id_of` names the cursor (the key id); `may_read_raw_phone` says whether this
    key may read full numbers rather than `[redacted]`."""
    router = APIRouter(tags=["events"])
    reader = Depends(principal_dep)

    @router.get("/events", response_model=FeedPageOut, summary="Events after a known event")
    async def list_feed_events(
        session: _Session,
        principal: Annotated[Principal, reader],
        after: Annotated[UUID | None, Query()] = None,
        type: Annotated[FeedEventName | None, Query()] = None,  # noqa: A002 - the published name
        limit: Annotated[int, Query(ge=1, le=feed.FEED_PAGE_MAX)] = feed.FEED_PAGE_DEFAULT,
    ) -> FeedPageOut:
        assert principal.tenant_id is not None
        rows = await feed.list_events(session, after=after, event_type=type, limit=limit)
        return _page(rows, tenant_id=principal.tenant_id, raw_phone=may_read_raw_phone(principal))

    @router.get(
        "/events/next", response_model=FeedPageOut, summary="Events after this key's cursor"
    )
    async def next_feed_events(
        session: _Session,
        principal: Annotated[Principal, reader],
        type: Annotated[FeedEventName | None, Query()] = None,  # noqa: A002 - the published name
        limit: Annotated[int, Query(ge=1, le=feed.FEED_PAGE_MAX)] = feed.FEED_PAGE_DEFAULT,
    ) -> FeedPageOut:
        assert principal.tenant_id is not None
        rows = await feed.next_events(
            session, consumer_id=consumer_id_of(principal), event_type=type, limit=limit
        )
        return _page(rows, tenant_id=principal.tenant_id, raw_phone=may_read_raw_phone(principal))

    @router.post(
        "/events/next/ack",
        response_model=FeedCursorOut,
        summary="Move this key's cursor to an event it processed",
    )
    async def ack_feed_events(
        payload: FeedAckIn, session: _Session, principal: Annotated[Principal, reader]
    ) -> FeedCursorOut:
        assert principal.tenant_id is not None
        cursor = await feed.ack(
            session,
            tenant_id=principal.tenant_id,
            consumer_id=consumer_id_of(principal),
            event_id=payload.event_id,
        )
        return FeedCursorOut(after_event_id=cursor.after_event_id)

    return router


__all__ = [
    "ENDPOINT_CREATED_BY_KEY",
    "ENDPOINT_DISABLED_BY_KEY",
    "FEED_SCOPE",
    "MACHINE_REFUSED_EVENTS",
    "MACHINE_SCOPE",
    "FeedAckIn",
    "FeedCursorOut",
    "FeedEventOut",
    "FeedPageOut",
    "build_events_router",
    "create_machine_endpoint",
    "deactivate_machine_endpoint",
]
