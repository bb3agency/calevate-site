"""The announcement bar (D-869): the admin console composes, clients read and dismiss.

ADMIN: `admin:tenants`, the operator permission for acting on clients — an announcement is
a message to clients and every operator who looks after them may write one. Every write is
audited with the fields that moved; the one-client audience records that client as the
audit row's tenant, so it appears in that client's own trail.

CLIENT: reading is `org:read`, which every role holds — a notice from Calevate is not a
privilege. Dismissing is the same permission, as a person's own act: an operator viewing the
account cannot put a notice away on the client's behalf, because the client would then
never see it.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.announcements import service
from apps.api.announcements.schemas import (
    AnnouncementAdminListOut,
    AnnouncementAdminOut,
    AnnouncementIn,
    AnnouncementListOut,
    AnnouncementUpdateIn,
)
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta

admin_router = APIRouter(prefix="/v1/admin/announcements", tags=["admin"])
router = APIRouter(prefix="/v1/announcements", tags=["announcements"])

AdminSession = Annotated[AsyncSession, Depends(admin_db)]
Session = Annotated[AsyncSession, Depends(db)]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]
Member = Annotated[Principal, Depends(requires("org:read", realm="client"))]


def _audit_summary(row: AnnouncementAdminOut) -> dict[str, object]:
    """Ids, words we chose and instants — the message itself is the operator's own text and
    is recorded so the trail says what clients were told."""
    return {
        "tone": row.tone,
        "audience": row.audience,
        "message": row.message,
        "link": row.link_url,
        "starts_at": row.starts_at.isoformat(),
        "ends_at": row.ends_at.isoformat() if row.ends_at else None,
    }


@admin_router.get(
    "",
    response_model=AnnouncementAdminListOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Announcements, newest first (scheduled and showing; add past=true for history)",
)
async def list_announcements(
    session: AdminSession,
    _: Operator,
    past: Annotated[bool, Query(description="Include ended and finished ones.")] = False,
    limit: Annotated[int, Query(ge=1, le=service.MAX_ADMIN_PAGE)] = 50,
) -> AnnouncementAdminListOut:
    items, total = await service.list_admin(session, include_past=past, limit=limit)
    return AnnouncementAdminListOut(items=items, total=total)


@admin_router.post(
    "",
    response_model=AnnouncementAdminOut,
    status_code=201,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Write an announcement for all clients, trial clients, paid clients or one client",
)
async def create_announcement(
    payload: AnnouncementIn, session: AdminSession, principal: Operator, request: Request
) -> AnnouncementAdminOut:
    row = await service.create(session, payload, admin_user_id=principal.user_id)
    await write_audit(
        session,
        action="announcement.created",
        actor=principal,
        tenant_id=row.target_tenant_id,
        object_type="platform_announcement",
        object_id=str(row.id),
        ip=client_request_ip(request),
        summary=_audit_summary(row),
    )
    return row


@admin_router.patch(
    "/{announcement_id}",
    response_model=AnnouncementAdminOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Change an announcement that has not been ended",
)
async def update_announcement(
    announcement_id: UUID,
    payload: AnnouncementUpdateIn,
    session: AdminSession,
    principal: Operator,
    request: Request,
) -> AnnouncementAdminOut:
    row, moved = await service.update(
        session, announcement_id, payload, admin_user_id=principal.user_id
    )
    if moved:
        await write_audit(
            session,
            action="announcement.updated",
            actor=principal,
            tenant_id=row.target_tenant_id,
            object_type="platform_announcement",
            object_id=str(row.id),
            ip=client_request_ip(request),
            summary={**_audit_summary(row), "changed": sorted(moved)},
        )
    return row


@admin_router.post(
    "/{announcement_id}/end",
    response_model=AnnouncementAdminOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Stop showing an announcement now",
)
async def end_announcement(
    announcement_id: UUID, session: AdminSession, principal: Operator, request: Request
) -> AnnouncementAdminOut:
    row, ended = await service.end(session, announcement_id, admin_user_id=principal.user_id)
    if ended:
        await write_audit(
            session,
            action="announcement.ended",
            actor=principal,
            tenant_id=row.target_tenant_id,
            object_type="platform_announcement",
            object_id=str(row.id),
            ip=client_request_ip(request),
            summary={"audience": row.audience},
        )
    return row


@router.get(
    "",
    response_model=AnnouncementListOut,
    openapi_extra=permission_meta("org:read"),
    summary="What Calevate is telling this account now, most urgent first, minus dismissed",
)
async def my_announcements(
    session: Session,
    principal: Member,
    limit: Annotated[int, Query(ge=1, le=service.MAX_ACTIVE)] = service.MAX_ACTIVE,
) -> AnnouncementListOut:
    assert principal.tenant_id is not None
    return AnnouncementListOut(
        items=await service.active_for(session, tenant_id=principal.tenant_id, limit=limit)
    )


@router.post(
    "/{announcement_id}/dismiss",
    status_code=204,
    response_class=Response,
    openapi_extra=permission_meta("org:read"),
    summary="Put an announcement away for this account",
)
async def dismiss_announcement(
    announcement_id: UUID, session: Session, principal: Member, request: Request
) -> Response:
    assert principal.tenant_id is not None
    if principal.client_user_id is None:
        raise ProblemError.forbidden(
            "Only someone in this account can put an announcement away; it stays for them."
        )
    if await service.dismiss(
        session, tenant_id=principal.tenant_id, announcement_id=announcement_id
    ):
        await write_audit(
            session,
            action="announcement.dismissed",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="platform_announcement",
            object_id=str(announcement_id),
            ip=client_request_ip(request),
        )
    return Response(status_code=204)


__all__ = ["admin_router", "router"]
