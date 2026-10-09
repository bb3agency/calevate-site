"""Dial one lead now: the body of `POST /v1/leads/{lead_id}/call`, callable from two doors.

The console's "Call" button and the assistant's `call_place` action (confirm tier, D-694)
both come here, so the compliance gate, the idempotency claim and the audit row are one
implementation. The route keeps only what is HTTP: the required `Idempotency-Key` header.

THREE TRANSACTIONS, AND THE SPLIT IS LOAD-BEARING. The claim commits in its own session
before anything can ring; the gate and the dial run in the caller's session; the audit row
and the claim's completion commit in a third session after the phone has rung. A claim or
an audit row written into the caller's transaction would be erased by any later rollback,
and the retry the key exists to answer would ring the customer a second time.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.compliance.service import check_dispatch
from apps.api.core.alerting import record_compliance_block
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.crm import service
from apps.api.crm.schemas import CallLeadOut
from apps.api.db.session import tenant_session
from apps.api.reliability.service import (
    body_hash,
    claim_idempotency,
    complete_idempotency,
    fail_idempotency,
    scope_key,
)

#: The idempotency namespace both doors share, so a key sent through one is the same key
#: through the other.
CALL_ROUTE = "/v1/leads/{lead_id}/call"


async def _release_undialled_claim(tenant_id: UUID, record_id: UUID) -> None:
    """Release a claim on a path that dialled nobody, in its own transaction (the
    request's is about to roll back), so the person's own retry is not refused."""
    async with tenant_session(tenant_id) as fail_session:
        await fail_idempotency(fail_session, record_id=record_id)


async def place_lead_call(
    session: AsyncSession,
    *,
    principal: Principal,
    lead_id: UUID,
    agent_id: UUID,
    context_note: str | None,
    idempotency_key: str,
    ip: str | None,
    audit_extra: dict[str, Any] | None = None,
) -> CallLeadOut:
    """Gate, then dial, one lead. `blocked` is an answer, not an exception.

    `audit_extra` is merged into the `lead.call_dispatched` summary — the assistant passes
    `{"via": "copilot"}` so the one row records which door the call came through.
    """
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    async with tenant_session(tenant_id) as claim_session:
        claim = await claim_idempotency(
            claim_session,
            scope=scope_key(tenant_id=tenant_id, user_id=principal.user_id),
            route=CALL_ROUTE,
            method="POST",
            key=idempotency_key,
            request_hash=body_hash(
                {"lead_id": str(lead_id), "agent_id": agent_id, "context_note": context_note}
            ),
        )
    if claim.state == "replay" and claim.response_payload:
        return CallLeadOut.model_validate(claim.response_payload)

    try:
        phone, name = await service.lead_phone(session, lead_id)
        # D-21: a client-initiated dial runs the same pre-checks as webhook dispatch, and a
        # DECISION comes back so the caller can say why it refused.
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
        )
    except Exception:
        await _release_undialled_claim(tenant_id, claim.record_id)
        raise
    if not decision.allowed:
        # Counted here and not inside `check_dispatch`: the eligibility read calls the same
        # function to render a disabled button, and a page load is not a blocked dial.
        record_compliance_block(rule=decision.rule or "unknown")
        result = CallLeadOut(
            status="blocked", blocked_reason=decision.reason, blocked_rule=decision.rule
        )
        async with tenant_session(tenant_id) as done_session:
            await complete_idempotency(
                done_session,
                record_id=claim.record_id,
                response_status=200,
                response_payload=result.model_dump(),
            )
        return result

    from apps.api.agents.service import (
        DialUnconfirmedError,
        dial_was_not_placed,
        dispatch_call,
    )

    try:
        handle = await dispatch_call(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            lead_id=lead_id,
            phone_e164=phone,
            lead_name=name,
            context_note=context_note,
        )
    except DialUnconfirmedError as unconfirmed:
        # The claim stays `processing`: releasing it would let the next press re-dial
        # somebody whose phone may be ringing now.
        raise ProblemError(
            kind="dependency",
            code="dial_unconfirmed",
            title="We could not confirm whether the call was placed",
            detail=(
                "The voice platform did not answer us, and it may have started the call anyway."
            ),
            remediation=(
                "Check this lead's call log in a minute before trying again — calling "
                "again could ring them twice."
            ),
        ) from unconfirmed
    except Exception as refused:
        # Only a failure that PROVES no line was seized releases the key.
        if dial_was_not_placed(refused):
            await _release_undialled_claim(tenant_id, claim.record_id)
        raise

    result = CallLeadOut(status="queued", call_handle=handle)
    async with tenant_session(tenant_id) as record_session:
        await write_audit(
            record_session,
            action="lead.call_dispatched",
            actor=principal,
            tenant_id=tenant_id,
            object_type="lead",
            object_id=str(lead_id),
            ip=ip,
            summary={
                "agent_id": str(agent_id),
                "has_note": bool(context_note),
                **(audit_extra or {}),
            },
        )
        await complete_idempotency(
            record_session,
            record_id=claim.record_id,
            response_status=200,
            response_payload=result.model_dump(),
        )
    return result


__all__ = ["CALL_ROUTE", "place_lead_call"]
