"""`/v1/campaigns/{campaign_id}/whatsapp-follow-up` (D-1041): the campaign card's WhatsApp
follow-up, read, set up by Pip, and switched on or off (`follow_ups/campaign_whatsapp`).

Reads are `leads:read`; the writes are `leads:dispatch`, as every `/v1/follow-ups` write,
because the Follow-up sends messages. Setting up spends the AI allowance, so a view-as session
is refused as on every Pip writer (`billing.ai_assist`). Every write is audited.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import assert_view_as_may, client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.core.schemas import Strict
from apps.api.follow_ups import campaign_whatsapp as cw

Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("leads:read"))]
Writer = Annotated[Principal, Depends(requires("leads:dispatch"))]

router = APIRouter(prefix="/v1/campaigns", tags=["follow-ups"])


class CampaignWhatsAppOutcomeOut(Strict):
    key: str
    label: str


class CampaignWhatsAppMadeOut(Strict):
    follow_up_id: UUID
    status: Literal["draft", "live", "paused", "off"]
    #: The message Pip wrote, as WhatsApp reviews it; null when the step names none.
    message: str | None
    #: WhatsApp's review of the message (`pending`, `approved`, `rejected`, ...).
    message_status: str | None
    #: The message's language as WhatsApp codes it (`te`, `hi`, `en`).
    message_language: str | None
    outcomes: list[CampaignWhatsAppOutcomeOut]
    wait_minutes: int
    sent: int
    replied: int
    has_unpublished_changes: bool


class CampaignWhatsAppOut(Strict):
    #: `not_connected` (no WhatsApp to send from, nothing made), `none` (ready to set up),
    #: `writing` (Pip is writing it), `failed` (the last try made nothing; `failure` says
    #: why) or `made`.
    phase: Literal["not_connected", "none", "writing", "failed", "made"]
    connected: bool
    failure: str | None
    made: CampaignWhatsAppMadeOut | None


class CampaignWhatsAppSwitchIn(Strict):
    on: bool


def _out(card: cw.Card) -> CampaignWhatsAppOut:
    made = card.made
    return CampaignWhatsAppOut(
        phase=card.phase,
        connected=card.connected,
        failure=card.failure,
        made=CampaignWhatsAppMadeOut(
            follow_up_id=made.id,
            status=made.status,  # type: ignore[arg-type]
            message=made.message,
            message_status=made.message_status,
            message_language=made.message_language,
            outcomes=[CampaignWhatsAppOutcomeOut(key=o.key, label=o.label) for o in made.outcomes],
            wait_minutes=made.wait_minutes,
            sent=made.sent,
            replied=made.replied,
            has_unpublished_changes=made.has_unpublished_changes,
        )
        if made is not None
        else None,
    )


@router.get(
    "/{campaign_id}/whatsapp-follow-up",
    response_model=CampaignWhatsAppOut,
    openapi_extra=permission_meta("leads:read"),
    summary="This campaign's WhatsApp follow-up, or what stops one being set up",
)
async def get_campaign_whatsapp(
    campaign_id: UUID, session: Session, _: Reader
) -> CampaignWhatsAppOut:
    return _out(await cw.card(session, campaign_id))


@router.post(
    "/{campaign_id}/whatsapp-follow-up",
    response_model=CampaignWhatsAppOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Have Pip write this campaign's WhatsApp follow-up; it is saved off",
)
async def set_up_campaign_whatsapp(
    campaign_id: UUID, session: Session, request: Request, principal: Writer
) -> CampaignWhatsAppOut:
    assert principal.tenant_id is not None
    assert_view_as_may(principal, "billing.ai_assist")
    card = await cw.set_up(session, tenant_id=principal.tenant_id, campaign_id=campaign_id)
    await write_audit(
        session,
        action="campaign.whatsapp_follow_up_requested",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="campaign",
        object_id=str(campaign_id),
        ip=client_request_ip(request),
        summary={"phase": card.phase},
    )
    return _out(card)


@router.post(
    "/{campaign_id}/whatsapp-follow-up/switch",
    response_model=CampaignWhatsAppOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Turn this campaign's WhatsApp follow-up on or off",
)
async def switch_campaign_whatsapp(
    campaign_id: UUID,
    payload: CampaignWhatsAppSwitchIn,
    session: Session,
    request: Request,
    principal: Writer,
) -> CampaignWhatsAppOut:
    assert principal.tenant_id is not None
    card = await cw.switch(
        session,
        tenant_id=principal.tenant_id,
        campaign_id=campaign_id,
        on=payload.on,
        user_id=principal.client_user_id,
    )
    assert card.made is not None
    await write_audit(
        session,
        action="follow_up.resumed" if payload.on else "follow_up.turned_off",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="follow_up",
        object_id=str(card.made.id),
        ip=client_request_ip(request),
        summary={"campaign_id": str(campaign_id), "status": card.made.status},
    )
    return _out(card)


__all__ = ["router"]
