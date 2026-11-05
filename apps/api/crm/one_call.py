"""Make a call: one AI call to one person, now or at a chosen time, outside any campaign.

The body of `POST /v1/one-calls` and of Pip's `call_place`. It adds exactly one thing to
the paths that already existed, which is reaching a person by NUMBER: the number is
normalised, the person's lead is found or made, and from there the existing doors do the
work. A call now is `lead_dial.place_lead_call` (gate, idempotency claim, audit row); a
call now that follows up an earlier call is `lead_dial.place_call_back`; a call later is
`swipe.schedule_lead_callback`, one `scheduled_callbacks` row the existing dispatch tick
rings at its time through the same gate. There is no second dial path and no second
scheduler.

A NEW PERSON IS ASKED THE GATE BEFORE ANY LEAD IS MADE. A number the gate refuses (on the
do-not-call list, outside India, an agent that cannot place calls) leaves no lead behind:
holding a person's number because somebody typed it into a refused call is data with no
purpose. The lead, once the gate allows the call, is committed in its own transaction
before the dial, so a retry of the same attempt finds the same lead id and the dial's claim
answers it rather than ringing again; without that, a request that rolled back after the
phone rang would make the retry a different request.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.calling_window import (
    CALLING_HOURS_RULE,
    ist_wall_clock,
    next_window_opening,
)
from pydantic import Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.callbacks import service as callbacks
from apps.api.compliance.audit import write_audit
from apps.api.compliance.service import DispatchDecision, check_dispatch
from apps.api.core.alerting import record_compliance_block
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.schemas import Strict
from apps.api.crm import service, swipe
from apps.api.crm.lead_dial import calling_hours_reason, place_call_back, place_lead_call
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.reliability.service import (
    IdempotencyClaim,
    body_hash,
    claim_idempotency,
    complete_idempotency,
    fail_idempotency,
    scope_key,
)

#: The idempotency namespace of a call booked for a time; a call now is claimed under
#: `lead_dial.CALL_ROUTE` by `place_lead_call` itself.
ONE_CALL_SCHEDULE_ROUTE: Final = "/v1/one-calls#at"

#: The longest "why" and "details": THIS CALL's reason and details lines carry at most 150
#: characters each (`calevate_shared.engine.CALL_VARIABLE_VALUE_MAX`), so a longer one
#: would be cut where the person cannot see it.
REASON_MAX: Final = 150
DETAILS_MAX: Final = 150
NAME_MAX: Final = 120


class OneCallIn(Strict):
    """Who to call, with which agent, why, and when. Exactly one of `phone`, `lead_id` or
    `call_id` names the person."""

    #: The number as typed. Ten digits are read as an Indian mobile; anything else needs
    #: its country code.
    phone: str | None = Field(default=None, max_length=32)
    #: A lead already on file (a lead's Call button).
    lead_id: UUID | None = None
    #: Follow up this earlier call: the same person and agent, the agent told what that
    #: call was about (a call's Call button). `agent_id` and `reason` are not used.
    call_id: UUID | None = None
    #: The person's name, kept on a new lead; an existing lead's name is not replaced.
    name: str | None = Field(default=None, max_length=NAME_MAX)
    #: An agent that places calls.
    agent_id: UUID | None = None
    #: Why the agent is calling, said to the agent as THIS CALL's reason.
    reason: str | None = Field(default=None, max_length=REASON_MAX)
    #: Anything else the agent should know on this call.
    details: str | None = Field(default=None, max_length=DETAILS_MAX)
    #: When to call, with its offset (IST: +05:30); left out, now. Between 09:00 and 21:00
    #: IST, at least two minutes ahead, within 30 days.
    at: datetime | None = None

    @model_validator(mode="after")
    def _one_person(self) -> OneCallIn:
        named = [v for v in (self.phone, self.lead_id, self.call_id) if v is not None]
        if len(named) != 1:
            raise ValueError("Give exactly one of phone, lead_id or call_id.")
        if self.call_id is None and self.agent_id is None:
            raise ValueError("Choose the agent that makes the call.")
        return self


class OneCallOut(Strict):
    """`blocked` is an answer, not an error: `blocked_reason` is the gate's own sentence."""

    status: Literal["queued", "scheduled", "blocked"]
    #: The call placed now (`GET /v1/calls/{id}`, `GET /v1/calls/live`).
    call_id: UUID | None = None
    #: The person's lead, once there is one.
    lead_id: UUID | None = None
    #: The booking, for a call at a time (`GET /v1/callbacks/{id}`; `DELETE` to call it off).
    callback_id: UUID | None = None
    requested_at: datetime | None = None
    #: True when an earlier booked call to this person was moved rather than a new one made.
    rescheduled: bool = False
    #: When following up an earlier call: which follow-up this is.
    follow_up_number: int | None = None
    blocked_reason: str | None = None
    blocked_rule: str | None = None
    #: When `blocked_rule` is `calling_hours`: the next instant a call may be placed.
    opens_at: datetime | None = None


def _clean(value: str | None) -> str | None:
    return " ".join(value.split()) or None if value else None


def _blocked(decision_rule: str | None, reason: str | None) -> OneCallOut:
    """A refusal, with the next allowed time when it is the calling hours."""
    if decision_rule == CALLING_HOURS_RULE:
        now = datetime.now(UTC)
        opens = next_window_opening(ist_wall_clock(now))
        return OneCallOut(
            status="blocked",
            blocked_rule=decision_rule,
            blocked_reason=calling_hours_reason(opens, now=now, verb="call"),
            opens_at=opens.astimezone(UTC),
        )
    return OneCallOut(status="blocked", blocked_rule=decision_rule, blocked_reason=reason)


def normalised_phone(raw: str) -> str:
    """The typed number as E.164, or a validation problem naming the field."""
    from apps.api.ingest.service import normalize_phone

    phone = normalize_phone(raw)
    if phone is None:
        raise ProblemError(
            kind="validation",
            code="one_call_bad_phone",
            title="That number cannot be called",
            detail="Enter a 10-digit mobile number, or a number with its country code.",
            fields=[{"field": "phone", "rule": "format", "message": "not a phone number"}],
        )
    return phone


_FIND_LEAD: Final = (
    "SELECT id FROM leads WHERE phone_e164 = :phone AND agent_id = :aid AND deleted_at IS NULL"
)
# One lead per (tenant, phone, agent): the key the call's own filing upserts on
# (`workers/pipeline._upsert_lead`), so the call lands on this lead. A deleted lead under
# the same key is not brought back.
_MAKE_LEAD: Final = (
    "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, data, "
    "created_at, updated_at) VALUES (:id, :tid, :aid, :phone, :name, 'manual', 'new', "
    "'{}'::jsonb, now(), now()) "
    "ON CONFLICT (tenant_id, phone_e164, agent_id) DO UPDATE SET "
    "name = COALESCE(leads.name, EXCLUDED.name), updated_at = now() "
    "WHERE leads.deleted_at IS NULL RETURNING id"
)


async def _existing_lead(session: AsyncSession, *, phone: str, agent_id: UUID) -> UUID | None:
    found = (
        await session.execute(text(_FIND_LEAD), {"phone": phone, "aid": agent_id})
    ).scalar_one_or_none()
    return UUID(str(found)) if found is not None else None


async def _make_lead(tenant_id: UUID, *, phone: str, agent_id: UUID, name: str | None) -> UUID:
    """The person's lead, committed on its own (see the module docstring)."""
    async with tenant_session(tenant_id) as lead_session:
        lead_id = uuid7()
        row = (
            await lead_session.execute(
                text(_MAKE_LEAD),
                {"id": lead_id, "tid": tenant_id, "aid": agent_id, "phone": phone, "name": name},
            )
        ).scalar_one_or_none()
        if row is None:
            raise ProblemError.business_rule(
                "one_call_lead_deleted",
                "This person's record was deleted, so they cannot be called from here.",
            )
        made = UUID(str(row))
        if made == lead_id:
            # The client's CRM hears about a new lead the way it does for every other door.
            await service.emit_lead_created(lead_session, [made])
        return made


async def _gate_new_person(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, phone: str, later: bool
) -> DispatchDecision | None:
    """The gate's refusal for a person not on file yet, or None. A call later is refused
    now only for what waiting cannot lift (`swipe.STANDING_REFUSALS`), like every booked
    call; the rest is the gate's to apply at its time."""
    if later:
        return await swipe.standing_refusal(
            session, tenant_id=tenant_id, agent_id=agent_id, phone=phone
        )
    decision = await check_dispatch(
        session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
    )
    if decision.allowed:
        return None
    record_compliance_block(rule=decision.rule or "unknown")
    return decision


def _later_note(reason: str | None, details: str | None) -> str | None:
    """What a booked call tells the agent: the reason, then the details, within the
    booking's note (`callbacks.MAX_NOTE`), cut on a word."""
    note = " — ".join(part for part in (reason, details) if part) or None
    if note is None or len(note) <= callbacks.MAX_NOTE:
        return note
    cut = note[: callbacks.MAX_NOTE]
    space = cut.rfind(" ")
    return (cut[:space] if space > callbacks.MAX_NOTE // 2 else cut).rstrip(" ,;:—")


async def _lead_of_call(session: AsyncSession, call_id: UUID) -> tuple[UUID, UUID]:
    row = (
        await session.execute(
            text("SELECT lead_id, agent_id FROM calls WHERE id = :id"), {"id": call_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Call")
    if row[0] is None:
        raise ProblemError.business_rule(
            "one_call_no_person",
            "Nobody was filed from this call, so there is no one to call.",
        )
    return UUID(str(row[0])), UUID(str(row[1]))


async def _claim(
    tenant_id: UUID, *, user_id: UUID | None, key: str, request_hash: str
) -> IdempotencyClaim:
    """The booking's claim, committed on its own before the work starts so a concurrent
    repeat of the key is answered from it; the booking and its audit row then share the
    request's session, one transaction (as `crm/swipe_routes._claim`)."""
    async with tenant_session(tenant_id) as claim_session:
        return await claim_idempotency(
            claim_session,
            scope=scope_key(tenant_id=tenant_id, user_id=user_id),
            route=ONE_CALL_SCHEDULE_ROUTE,
            method="POST",
            key=key,
            request_hash=request_hash,
        )


async def _call_later(
    session: AsyncSession,
    *,
    principal: Principal,
    tenant_id: UUID,
    request: OneCallIn,
    idempotency_key: str,
    ip: str | None,
    audit_extra: dict[str, Any] | None,
) -> OneCallOut:
    """Book the call for its time: one claim, then the booking and its audit row in the
    request's transaction, as `POST /v1/leads/{id}/callbacks` does."""
    assert request.at is not None
    swipe.check_schedule_time(request.at, now=datetime.now(UTC))
    claim = await _claim(
        tenant_id,
        user_id=principal.user_id,
        key=idempotency_key,
        request_hash=body_hash(request.model_dump(mode="json")),
    )
    if claim.state == "replay" and claim.response_payload:
        return OneCallOut.model_validate(claim.response_payload)
    try:
        out = await _book(session, tenant_id=tenant_id, request=request)
        if out.status == "scheduled":
            await write_audit(
                session,
                action="lead.callback_scheduled",
                actor=principal,
                tenant_id=tenant_id,
                object_type="lead",
                object_id=str(out.lead_id),
                ip=ip,
                summary={
                    "callback_id": str(out.callback_id),
                    "at": request.at.isoformat(),
                    "rescheduled": out.rescheduled,
                    "has_note": bool(request.reason),
                    "via_one_call": True,
                    **(audit_extra or {}),
                },
            )
        await complete_idempotency(
            session, claim=claim, response_status=200, response_payload=out.model_dump(mode="json")
        )
    except Exception:
        async with tenant_session(tenant_id) as fail_session:
            await fail_idempotency(fail_session, claim=claim)
        raise
    return out


async def _book(session: AsyncSession, *, tenant_id: UUID, request: OneCallIn) -> OneCallOut:
    assert request.at is not None
    note = _later_note(_clean(request.reason), _clean(request.details))
    agent_id: UUID | None
    if request.call_id is not None:
        # The agent is `swipe.contact_agent`'s choice: the call's own agent may only answer.
        lead_id, _call_agent = await _lead_of_call(session, request.call_id)
        agent_id = None
        note = note or "A follow-up to their last call."
    elif request.lead_id is not None:
        lead_id = request.lead_id
        assert request.agent_id is not None
        agent_id = request.agent_id
    else:
        assert request.phone is not None and request.agent_id is not None
        agent_id = request.agent_id
        phone = normalised_phone(request.phone)
        found = await _existing_lead(session, phone=phone, agent_id=agent_id)
        if found is None:
            refused = await _gate_new_person(
                session, tenant_id=tenant_id, agent_id=agent_id, phone=phone, later=True
            )
            if refused is not None:
                return _blocked(refused.rule, refused.reason)
            found = await _make_lead(
                tenant_id, phone=phone, agent_id=agent_id, name=_clean(request.name)
            )
        lead_id = found
    booked = await swipe.schedule_lead_callback(
        session, tenant_id=tenant_id, lead_id=lead_id, at=request.at, note=note, agent_id=agent_id
    )
    if booked.status == "blocked":
        return _blocked(booked.blocked_rule, booked.blocked_reason)
    return OneCallOut(
        status="scheduled",
        lead_id=lead_id,
        callback_id=booked.callback_id,
        requested_at=booked.requested_at,
        rescheduled=booked.rescheduled,
    )


async def place_one_call(
    session: AsyncSession,
    *,
    principal: Principal,
    request: OneCallIn,
    idempotency_key: str,
    ip: str | None = None,
    audit_extra: dict[str, Any] | None = None,
) -> OneCallOut:
    """Call one person now, or book the call for `request.at`. See the module docstring."""
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    if request.at is not None:
        return await _call_later(
            session,
            principal=principal,
            tenant_id=tenant_id,
            request=request,
            idempotency_key=idempotency_key,
            ip=ip,
            audit_extra=audit_extra,
        )

    if request.call_id is not None:
        # Keyed by the earlier call, not the request: the call's own "Call back" door.
        back = await place_call_back(
            session, principal=principal, call_id=request.call_id, ip=ip, audit_extra=audit_extra
        )
        if back.status == "blocked":
            out = _blocked(back.blocked_rule, back.blocked_reason)
            return out
        lead_id, _agent = await _lead_of_call(session, request.call_id)
        return OneCallOut(
            status="queued",
            call_id=back.call_id,
            lead_id=lead_id,
            follow_up_number=back.follow_up_number,
        )

    assert request.agent_id is not None
    agent_id = request.agent_id
    if request.lead_id is not None:
        lead_id = request.lead_id
    else:
        assert request.phone is not None
        phone = normalised_phone(request.phone)
        found = await _existing_lead(session, phone=phone, agent_id=agent_id)
        if found is None:
            refused = await _gate_new_person(
                session, tenant_id=tenant_id, agent_id=agent_id, phone=phone, later=False
            )
            if refused is not None:
                return _blocked(refused.rule, refused.reason)
            found = await _make_lead(
                tenant_id, phone=phone, agent_id=agent_id, name=_clean(request.name)
            )
        lead_id = found

    placed = await place_lead_call(
        session,
        principal=principal,
        lead_id=lead_id,
        agent_id=agent_id,
        context_note=_clean(request.reason),
        details=_clean(request.details),
        idempotency_key=idempotency_key,
        ip=ip,
        audit_extra={"via_one_call": True, **(audit_extra or {})},
    )
    if placed.status == "blocked":
        out = _blocked(placed.blocked_rule, placed.blocked_reason)
        return out.model_copy(update={"lead_id": lead_id})
    return OneCallOut(status="queued", call_id=placed.call_id, lead_id=lead_id)


__all__ = [
    "DETAILS_MAX",
    "NAME_MAX",
    "ONE_CALL_SCHEDULE_ROUTE",
    "REASON_MAX",
    "OneCallIn",
    "OneCallOut",
    "normalised_phone",
    "place_one_call",
]
