"""Send one approved WhatsApp message to a lead: the body of `POST /v1/leads/{lead_id}/
whatsapp`, callable from the lead's ⋯ menu and Pip's `lead_whatsapp_send` (D-869, D-893).

One implementation behind both doors, so the dispatch gate, the messaging consent, the
idempotency claim, the lead's timeline row and the audit row cannot differ between them.

The claim commits on its own before anything is sent. A failure BEFORE the send releases
it; from the send on it is completed, never released, because a message may have been
delivered and a retry of the same key must be answered rather than sent again.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.context import Principal
from apps.api.crm import swipe
from apps.api.db.session import tenant_session
from apps.api.reliability.service import (
    body_hash,
    claim_idempotency,
    complete_idempotency,
    fail_idempotency,
    scope_key,
)

#: The idempotency namespace both doors share.
WHATSAPP_ROUTE = "/v1/leads/{lead_id}/whatsapp"


async def send_lead_whatsapp(
    session: AsyncSession,
    *,
    principal: Principal,
    lead_id: UUID,
    payload: swipe.WhatsAppSendIn,
    idempotency_key: str,
    ip: str | None = None,
    audit_extra: dict[str, Any] | None = None,
    actor: str | None = None,
) -> swipe.WhatsAppSendOut:
    """Gate, consent, then one template message. `blocked` and `failed` are answers.

    `actor` names who sent it on the lead's timeline when that is not a person (a
    Follow-up's step, D-940); left out, it is the principal."""
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    async with tenant_session(tenant_id) as claim_session:
        claim = await claim_idempotency(
            claim_session,
            scope=scope_key(tenant_id=tenant_id, user_id=principal.user_id),
            route=WHATSAPP_ROUTE,
            method="POST",
            key=idempotency_key,
            request_hash=body_hash({"lead_id": str(lead_id), **payload.model_dump(mode="json")}),
        )
    if claim.state == "replay" and claim.response_payload:
        return swipe.WhatsAppSendOut.model_validate(claim.response_payload)
    try:
        out, template = await swipe.send_whatsapp_follow_up(
            session, tenant_id=tenant_id, lead_id=lead_id, payload=payload
        )
    except Exception:
        async with tenant_session(tenant_id) as fail_session:
            await fail_idempotency(fail_session, claim=claim)
        raise
    # The timeline row, the completed claim and the audit row commit together, and the
    # audit is the block's last statement: a failing audit rolls back the other two.
    async with tenant_session(tenant_id) as record_session:
        await swipe.record_whatsapp_on_timeline(
            record_session,
            lead_id=lead_id,
            template=template,
            out=out,
            actor=actor or str(principal.user_id),
        )
        await complete_idempotency(
            record_session,
            claim=claim,
            response_status=200,
            response_payload=out.model_dump(mode="json"),
        )
        await write_audit(
            record_session,
            action="lead.whatsapp_follow_up",
            actor=principal,
            tenant_id=tenant_id,
            object_type="lead",
            object_id=str(lead_id),
            ip=ip,
            summary={
                "status": out.status,
                "rule": out.rule,
                "template": template,
                **(audit_extra or {}),
            },
        )
    return out


__all__ = ["WHATSAPP_ROUTE", "send_lead_whatsapp"]
