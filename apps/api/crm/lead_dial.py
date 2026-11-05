"""Dial one lead now: the bodies of `POST /v1/leads/{lead_id}/call` and `POST /v1/calls/
{call_id}/callback`, each callable from two doors.

The console's "Call" and "Have the agent call back" buttons and the assistant's `call_place`
and `call_back` actions (confirm tier, D-694, D-893) come here, so the compliance gate, the
idempotency claim and the audit row are one implementation. The routes keep only what is
HTTP: the required `Idempotency-Key` header on the first.

THREE TRANSACTIONS, AND THE SPLIT IS LOAD-BEARING. The claim commits in its own session
before anything can ring; the gate and the dial run in the caller's session; the audit row
and the claim's completion commit in a third session after the phone has rung. A claim or
an audit row written into the caller's transaction would be erased by any later rollback,
and the retry the key exists to answer would ring the customer a second time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from calevate_shared.calling_window import (
    CALLING_HOURS_RULE,
    IST,
    ist_wall_clock,
    next_window_opening,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.compliance.service import check_dispatch
from apps.api.core.alerting import record_compliance_block
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.crm import service
from apps.api.crm.schemas import CallbackEligibilityOut, CallbackOut, CallLeadOut
from apps.api.db.session import tenant_session
from apps.api.reliability.service import (
    IdempotencyClaim,
    body_hash,
    claim_idempotency,
    complete_idempotency,
    fail_idempotency,
    mark_idempotency_in_doubt,
    scope_key,
)

#: The idempotency namespace both doors share, so a key sent through one is the same key
#: through the other.
CALL_ROUTE = "/v1/leads/{lead_id}/call"


async def _release_undialled_claim(tenant_id: UUID, claim: IdempotencyClaim) -> None:
    """Release a claim on a path that dialled nobody, in its own transaction (the
    request's is about to roll back), so the person's own retry is not refused."""
    async with tenant_session(tenant_id) as fail_session:
        await fail_idempotency(fail_session, claim=claim)


#: The label a person's "anything the agent should know" travels under in THIS CALL's
#: details line (`calevate_shared.engine.DETAILS_LINE`), ahead of the lead's stored details.
CALL_NOTE_LABEL = "Note"


class _PersonPlacedCall:
    """`dispatch_call`'s `on_reserved` for a call a person placed: marks the intent row
    `placed_by_person` in the intent's own transaction (so the mark exists before anything
    can ring and survives a lost engine response) and keeps the row's id for the reply."""

    def __init__(self) -> None:
        self.call_id: UUID | None = None

    async def __call__(self, intent: AsyncSession, call_id: UUID) -> None:
        self.call_id = call_id
        await intent.execute(
            text("UPDATE calls SET placed_by_person = true WHERE id = :id"), {"id": call_id}
        )


async def place_lead_call(
    session: AsyncSession,
    *,
    principal: Principal,
    lead_id: UUID,
    agent_id: UUID,
    context_note: str | None,
    idempotency_key: str,
    ip: str | None = None,
    audit_extra: dict[str, Any] | None = None,
    details: str | None = None,
) -> CallLeadOut:
    """Gate, then dial, one lead. `blocked` is an answer, not an exception.

    `audit_extra` is merged into the `lead.call_dispatched` summary — the assistant passes
    `{"via": "copilot"}` so the one row records which door the call came through.

    `details` is what the person wants the agent to know on this call; it rides THIS CALL's
    details line under `CALL_NOTE_LABEL`, before the lead's stored details.
    """
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    hashed: dict[str, Any] = {
        "lead_id": str(lead_id),
        "agent_id": agent_id,
        "context_note": context_note,
    }
    if details:
        # Only when present, so a key sent before `details` existed hashes as it did.
        hashed["details"] = details
    async with tenant_session(tenant_id) as claim_session:
        claim = await claim_idempotency(
            claim_session,
            scope=scope_key(tenant_id=tenant_id, user_id=principal.user_id),
            route=CALL_ROUTE,
            method="POST",
            key=idempotency_key,
            request_hash=body_hash(hashed),
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
        await _release_undialled_claim(tenant_id, claim)
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
                claim=claim,
                response_status=200,
                response_payload=result.model_dump(mode="json"),
            )
        return result

    from apps.api.agents.service import (
        DialUnconfirmedError,
        dial_was_not_placed,
        dispatch_call,
    )
    from apps.api.campaigns.contact_details import lead_details

    # Committed before the phone can ring: from here the key is never re-run, even past the
    # lease, unless a failure proves no line was seized.
    async with tenant_session(tenant_id) as doubt_session:
        await mark_idempotency_in_doubt(doubt_session, claim=claim)
    reserved = _PersonPlacedCall()
    try:
        # With no note, `dispatch_call` reads the lead's stored details itself.
        contact = (
            {CALL_NOTE_LABEL: details, **await lead_details(session, lead_id=lead_id)}
            if details
            else None
        )
        handle = await dispatch_call(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            lead_id=lead_id,
            phone_e164=phone,
            lead_name=name,
            context_note=context_note,
            contact_details=contact,
            on_reserved=reserved,
        )
    except DialUnconfirmedError as unconfirmed:
        # The claim stays `in_doubt`: releasing it would let the next press re-dial
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
            await _release_undialled_claim(tenant_id, claim)
        raise

    result = CallLeadOut(status="queued", call_handle=handle, call_id=reserved.call_id)
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
                "call_id": str(reserved.call_id) if reserved.call_id else None,
                "has_note": bool(context_note),
                "has_details": bool(details),
                **(audit_extra or {}),
            },
        )
        await complete_idempotency(
            record_session,
            claim=claim,
            response_status=200,
            response_payload=result.model_dump(mode="json"),
        )
    return result


#: The idempotency namespace of "call back about this call"; its key is the parent call, so
#: the button and Pip asking twice about one call ring the lead once.
CALL_BACK_ROUTE = "/v1/calls/{call_id}/callback"


async def call_back_check(
    session: AsyncSession, *, tenant_id: UUID, call_id: UUID
) -> CallbackEligibilityOut:
    """Whether this call may be followed up now, and why not: our chain rules, then the
    dispatch gate. A read, so the button renders disabled with the reason and Pip refuses
    before a card; neither counts as a blocked dial."""
    try:
        plan = await service.plan_callback(session, call_id)
    except ProblemError as problem:
        if problem.kind != "business_rule":
            raise
        return CallbackEligibilityOut(eligible=False, reason=problem.detail, rule=problem.code)
    decision = await check_dispatch(
        session, tenant_id=tenant_id, agent_id=plan.agent_id, phone_e164=plan.phone_e164
    )
    if decision.allowed:
        return CallbackEligibilityOut(eligible=True, follow_up_number=plan.depth + 1)
    if decision.rule == CALLING_HOURS_RULE:
        # The gate's sentence states the rule; on a call page read after 9 pm it sat under
        # the call with nothing saying it was about the "Call back now" button, and read as
        # a call back booked for nothing (4 Nov 2026 call review).
        now = datetime.now(UTC)
        opens = next_window_opening(ist_wall_clock(now))
        return CallbackEligibilityOut(
            eligible=False,
            reason=calling_hours_reason(opens, now=now),
            rule=decision.rule,
            opens_at=opens.astimezone(UTC),
        )
    return CallbackEligibilityOut(eligible=False, reason=decision.reason, rule=decision.rule)


def calling_hours_reason(opens: datetime, *, now: datetime, verb: str = "call back") -> str:
    """Why a call waits, and until when, as one sentence in IST. `verb` names the action
    the person pressed ("call back", "call")."""
    opens_ist = opens.astimezone(IST)
    day = (
        "today"
        if opens_ist.date() == ist_wall_clock(now).date()
        else "tomorrow"
        if opens_ist.date() == ist_wall_clock(now).date() + timedelta(days=1)
        else f"{opens_ist:%A}"
    )
    hour = opens_ist.hour % 12 or 12
    meridiem = "am" if opens_ist.hour < 12 else "pm"
    return (
        "Calls can only be placed between 9 am and 9 pm. "
        f"You can {verb} from {hour}:{opens_ist:%M} {meridiem} {day}."
    )


async def place_call_back(
    session: AsyncSession,
    *,
    principal: Principal,
    call_id: UUID,
    ip: str | None = None,
    audit_extra: dict[str, Any] | None = None,
) -> CallbackOut:
    """Re-dispatch the call's agent to the same lead, carrying our summary of the call.

    `place_lead_call`'s three transactions and claim rules, with the key derived from the
    CALL rather than sent by the client: "follow up this call" is naturally keyed by the
    call, so two tabs, the button and Pip, or two people on the team cannot ring the
    customer twice. The claim is scoped to the account, not the person: a per-user scope
    would give each teammate their own claim on the same call."""
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    plan = await service.plan_callback(session, call_id)
    async with tenant_session(tenant_id) as claim_session:
        claim = await claim_idempotency(
            claim_session,
            scope=scope_key(tenant_id=tenant_id, user_id=None),
            route=CALL_BACK_ROUTE,
            method="POST",
            key=str(call_id),
            request_hash=body_hash({"call_id": str(call_id)}),
        )
    if claim.state == "replay" and claim.response_payload:
        return CallbackOut.model_validate(claim.response_payload)

    try:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=plan.agent_id, phone_e164=plan.phone_e164
        )
    except Exception:
        await _release_undialled_claim(tenant_id, claim)
        raise
    if not decision.allowed:
        record_compliance_block(rule=decision.rule or "unknown")
        # RELEASED, NOT STORED — the opposite of `place_lead_call`, because the key is the
        # parent call and every later press reuses it: a stored refusal would answer every
        # press long after calling hours opened or the wallet was topped up. Nothing was
        # dialled, so nothing needs the claim.
        await _release_undialled_claim(tenant_id, claim)
        reason = decision.reason
        if decision.rule == CALLING_HOURS_RULE:
            now = datetime.now(UTC)
            reason = calling_hours_reason(next_window_opening(ist_wall_clock(now)), now=now)
        return CallbackOut(status="blocked", blocked_reason=reason, blocked_rule=decision.rule)

    from apps.api.agents.service import DialUnconfirmedError, dial_was_not_placed, dispatch_call

    async with tenant_session(tenant_id) as doubt_session:
        await mark_idempotency_in_doubt(doubt_session, claim=claim)
    reserved = _PersonPlacedCall()
    try:
        handle = await dispatch_call(
            session,
            tenant_id=tenant_id,
            agent_id=plan.agent_id,
            lead_id=plan.lead_id,
            phone_e164=plan.phone_e164,
            lead_name=plan.lead_name,
            context_note=plan.context_note,
            on_reserved=reserved,
        )
    except DialUnconfirmedError as unconfirmed:
        raise ProblemError(
            kind="dependency",
            code="dial_unconfirmed",
            title="We could not confirm whether the callback was placed",
            detail=(
                "The voice platform did not answer us, and it may have started the call anyway."
            ),
            remediation=(
                "Check this call's call-backs in a minute before trying again — calling "
                "again could ring them twice."
            ),
        ) from unconfirmed
    except Exception as refused:
        if dial_was_not_placed(refused):
            await _release_undialled_claim(tenant_id, claim)
        raise
    # The chain link stays on the caller's session: it is a pointer between two of our own
    # rows, and its loss costs a follow-up count, not a record of a call.
    await service.link_callback(session, handle=handle, parent_call_id=call_id)
    result = CallbackOut(
        status="queued",
        call_handle=handle,
        call_id=reserved.call_id,
        follow_up_number=plan.depth + 1,
    )
    async with tenant_session(tenant_id) as record_session:
        await write_audit(
            record_session,
            action="call.callback_dispatched",
            actor=principal,
            tenant_id=tenant_id,
            object_type="call",
            object_id=str(call_id),
            ip=ip,
            summary={"follow_up_number": plan.depth + 1, **(audit_extra or {})},
        )
        await complete_idempotency(
            record_session,
            claim=claim,
            response_status=200,
            response_payload=result.model_dump(mode="json"),
        )
    return result


__all__ = [
    "CALL_BACK_ROUTE",
    "CALL_NOTE_LABEL",
    "CALL_ROUTE",
    "call_back_check",
    "calling_hours_reason",
    "place_call_back",
    "place_lead_call",
]
