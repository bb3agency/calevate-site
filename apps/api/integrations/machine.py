"""What an API key may do with webhooks and the events feed (D-1049, MASTER-PLAN W2.6, W2.7).

THE HOOK FOR THE `/api/v1` ROUTER. Keys, their scopes and the machine principal are built
beside this (lane B1, `apps/api/api_keys/**`, `apps/api/public_api/**`); this module is
the integrations half and is called from there. It mounts nothing itself:

* `create_machine_endpoint`, `deactivate_machine_endpoint` — behind the `webhooks:manage`
  scope (`MACHINE_SCOPE`).
* `feed_page` and the feed's models — the three feed routes are in `public_api/routes.py`.

**A key creates only endpoints that carry no call content.** A person turning on a
recording link or a transcript for a destination types an emailed code for that act
(D-730); a key cannot type one, so an endpoint a key creates has every opt-in off and
cannot subscribe to `call.recording_ready`, which exists to carry the link. Switching any
of them on later is the person's edit on the Integrations screen. A key deactivates only an
endpoint a key created: a destination a person set up is the person's to remove.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.context import Principal
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


# --- the events feed, as the `/api/v1` routes answer it ---------------------------------

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


def feed_page(rows: list[feed.FeedEvent], *, tenant_id: UUID, raw_phone: bool) -> FeedPageOut:
    """One page of the feed as a key reads it."""
    return FeedPageOut(
        events=[
            FeedEventOut.model_validate(
                feed.serialize(row, tenant_id=tenant_id, include_raw_phone=raw_phone)
            )
            for row in rows
        ],
        next_after=rows[-1].id if rows else None,
    )


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
    "create_machine_endpoint",
    "deactivate_machine_endpoint",
    "feed_page",
]
