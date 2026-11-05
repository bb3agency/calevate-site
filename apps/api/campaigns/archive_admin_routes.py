"""An operator archives, restores or deletes a client's campaign, and the client is told (F-10).

The same service as the client's buttons and Pip (`campaigns/archive`), so the rules are the
same: archive anything (a running campaign is paused first), restore to paused or draft and
never to running, delete only a draft that never dialled. What the operator adds is a reason,
required, and a notice to the client in the app, by email and, where the owner opted in, on
WhatsApp (`workers/campaign_archive_notice`), promised in the same transaction as the act.

Admin realm, `admin:tenants`, and step-up on the two that take something away from the client
(archive and delete): the `X-Confirm-Action` value names the act and the campaign, so a
confirmation for one cannot be replayed on another. `core.deps.db` resolves the tenant from the
principal and an admin principal has none, so each route opens `tenant_session(tenant_id)` on
the path parameter, the house pattern for admin work on one client (`admin/closure_routes`);
a campaign id from another tenant reads as absent there (RLS), never as found.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns import archive
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.db.session import tenant_session
from apps.workers.campaign_archive_notice import (
    EVENT_ARCHIVED,
    EVENT_DELETED,
    enqueue_campaign_notice,
)

router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/campaigns", tags=["admin"])

Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]


def archive_confirmation(campaign_id: UUID) -> str:
    """The `X-Confirm-Action` value for archiving THIS campaign."""
    return f"archive_campaign:{campaign_id}"


def delete_confirmation(campaign_id: UUID) -> str:
    """The `X-Confirm-Action` value for deleting THIS draft."""
    return f"delete_campaign:{campaign_id}"


class AdminArchiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Why, in words the client will read in the app and the email. Required.
    reason: str = Field(min_length=archive.MIN_REASON_CHARS, max_length=archive.MAX_REASON_CHARS)


class AdminArchiveOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: False when nothing moved (already archived, or already restored): no notice is sent.
    changed: bool
    #: The status it holds now.
    status: str
    #: Whether the client was told (a notice is queued only when something changed).
    client_notified: bool


async def _slug(session: AsyncSession, tenant_id: UUID) -> str:
    row = (
        await session.execute(
            text("SELECT slug FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar()
    return str(row or "")


@router.post(
    "/{campaign_id}/archive",
    response_model=AdminArchiveOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Archive a client's campaign with a reason; the client is told",
    description=(
        "Archives the campaign through the same rules as the client's own button (a running "
        "campaign is paused first; its calls, leads and charges are kept) and tells the "
        "client in the app, by email and, where the owner opted in, on WhatsApp. Needs "
        "`X-Confirm-Action: archive_campaign:<campaign_id>` and a recent second factor."
    ),
)
async def admin_archive(
    tenant_id: UUID,
    campaign_id: UUID,
    payload: AdminArchiveIn,
    request: Request,
    principal: Operator,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> AdminArchiveOut:
    step_up.require(x_confirm_action, archive_confirmation(campaign_id))
    async with tenant_session(tenant_id) as scoped:
        result = await archive.archive_campaign(
            scoped,
            campaign_id=campaign_id,
            by=principal.user_id,
            realm="admin",
            reason=payload.reason,
        )
        if result.changed:
            reason = archive.clean_reason(payload.reason, required=True) or ""
            await enqueue_campaign_notice(
                scoped,
                tenant_id=tenant_id,
                event=EVENT_ARCHIVED,
                campaign=result.name,
                reason=reason,
                slug=await _slug(scoped, tenant_id),
            )
            await write_audit(
                scoped,
                action="campaign.archived",
                actor=principal,
                tenant_id=tenant_id,
                object_type="campaign",
                object_id=str(campaign_id),
                ip=client_request_ip(request),
                summary={
                    "from": result.status_before,
                    "to": result.status_after,
                    "by": "admin",
                    "reason": reason,
                },
            )
    return AdminArchiveOut(
        changed=result.changed, status=result.status_after, client_notified=result.changed
    )


@router.post(
    "/{campaign_id}/restore",
    response_model=AdminArchiveOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Restore a client's archived campaign (paused or draft, never running)",
)
async def admin_restore(
    tenant_id: UUID,
    campaign_id: UUID,
    request: Request,
    principal: Operator,
) -> AdminArchiveOut:
    """Gives something back, so no step-up and no notice: the client sees it on their list."""
    async with tenant_session(tenant_id) as scoped:
        result = await archive.restore_campaign(scoped, campaign_id=campaign_id)
        if result.changed:
            await write_audit(
                scoped,
                action="campaign.restored",
                actor=principal,
                tenant_id=tenant_id,
                object_type="campaign",
                object_id=str(campaign_id),
                ip=client_request_ip(request),
                summary={
                    "status": result.status_after,
                    "by": "admin",
                    "archived_by": str(result.undid[0]) if result.undid[0] else None,
                    "archived_by_realm": result.undid[1],
                },
            )
    return AdminArchiveOut(
        changed=result.changed, status=result.status_after, client_notified=False
    )


@router.delete(
    "/{campaign_id}",
    response_model=AdminArchiveOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Delete a client's draft that never made a call, with a reason; the client is told",
    description=(
        "Deletes only a draft that never dialled; anything else is refused with "
        "`campaign_has_history` (archive it instead). Needs "
        "`X-Confirm-Action: delete_campaign:<campaign_id>` and a recent second factor."
    ),
)
async def admin_delete(
    tenant_id: UUID,
    campaign_id: UUID,
    payload: AdminArchiveIn,
    request: Request,
    principal: Operator,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> AdminArchiveOut:
    step_up.require(x_confirm_action, delete_confirmation(campaign_id))
    reason = archive.clean_reason(payload.reason, required=True) or ""
    async with tenant_session(tenant_id) as scoped:
        name = await archive.delete_campaign(scoped, campaign_id=campaign_id)
        await enqueue_campaign_notice(
            scoped,
            tenant_id=tenant_id,
            event=EVENT_DELETED,
            campaign=name,
            reason=reason,
            slug=await _slug(scoped, tenant_id),
        )
        await write_audit(
            scoped,
            action="campaign.deleted",
            actor=principal,
            tenant_id=tenant_id,
            object_type="campaign",
            object_id=str(campaign_id),
            ip=client_request_ip(request),
            summary={"from": "draft", "name": name, "by": "admin", "reason": reason},
        )
    return AdminArchiveOut(changed=True, status="deleted", client_notified=True)


__all__ = ["archive_confirmation", "delete_confirmation", "router"]
