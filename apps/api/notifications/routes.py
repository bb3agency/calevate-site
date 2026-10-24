"""`/v1/notifications` — the bell's feed and its read mark (D-869).

`leads:read`, the permission of the needs-attention queue the feed is built from
(`GET /v1/attention`): the bell shows the same items, so it answers to the same readers.
Marking the feed read is the reader's own act on their own mark; an operator viewing the
account has no mark there, and the call is answered without writing one.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.notifications import service
from apps.api.notifications.service import NotificationFeedOut, SeenIn, SeenOut

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])

Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("leads:read", realm="client"))]
#: Marking the bell read writes a per-person row, so it needs a mutating permission (D-22);
#: `leads:write` is the one every client role that works the queue holds.
Worker = Annotated[Principal, Depends(requires("leads:write", realm="client"))]


@router.get(
    "",
    response_model=NotificationFeedOut,
    openapi_extra=permission_meta("leads:read"),
    summary="The bell: needs-attention items and announcements, newest first, with unread",
)
async def get_feed(
    session: Session,
    principal: Reader,
    limit: Annotated[int, Query(ge=1, le=service.MAX_FEED)] = 30,
) -> NotificationFeedOut:
    assert principal.tenant_id is not None
    return await service.feed(
        session, tenant_id=principal.tenant_id, user_id=principal.client_user_id, limit=limit
    )


@router.post(
    "/seen",
    response_model=SeenOut,
    openapi_extra=permission_meta("leads:write"),
    summary="Mark the bell read up to an instant (now by default)",
)
async def mark_seen(payload: SeenIn, session: Session, principal: Worker) -> SeenOut:
    assert principal.tenant_id is not None
    person = principal.client_user_id
    if person is None:
        return SeenOut(seen_through=None)
    return SeenOut(
        seen_through=await service.mark_seen(
            session, tenant_id=principal.tenant_id, user_id=person, through=payload.through
        )
    )


__all__ = ["router"]
