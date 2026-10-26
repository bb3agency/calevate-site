"""The phone swipe's actions and the desktop ⋯ menu's (D-869, founder decision f7d9f716 §7).

What already existed and is used as it is:

* **Call back now** — `POST /v1/leads/{id}/call` (`crm/lead_dial.place_lead_call`) and
  `POST /v1/calls/{id}/callback`: compliance-gated, `Idempotency-Key` required, audited.
* **Lead status** (won / lost / follow-up) — `PATCH /v1/leads/{id}`. Its undo is the same
  PATCH with the previous status and `expected_status` set to the one being undone, which
  makes it a compare-and-swap: a colleague's later change is not overwritten.
* **Cancel a call-back** — `DELETE /v1/callbacks/{id}`, the undo of "Call back later".

What this module adds:

* `set_call_follow_up` — mark a call `resolved` or `needs_you`, or clear the mark, with an
  optional expected current state (the undo).
* `schedule_lead_callback` — "Call back later" at a chosen time between 09:00 and 21:00
  IST, written into `scheduled_callbacks` so the existing tick dials it through the one
  outbound entry point and the compliance gate at its time.
* `whatsapp_options` / `send_whatsapp_follow_up` — an approved template from the account's
  own connected WhatsApp, only when the dispatch gate allows the number and the person's
  messaging consent is on record (`actions/whatsapp.assert_recipient_may_be_messaged`, the
  same two questions every WhatsApp send asks, in the same order).
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions import whatsapp as wa
from apps.api.actions.schema import WhatsAppConfig
from apps.api.billing.plans import IST
from apps.api.callbacks import service as callbacks
from apps.api.compliance.service import (
    PERSON_LEVEL_REFUSALS,
    DispatchDecision,
    check_dispatch,
    person_level_refusal,
)
from apps.api.compliance.trial_access import TRIAL_DIAL_REFUSALS
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm.models import CallFollowUpState
from apps.api.crm.service import lead_phone
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.whatsapp import accounts, templates

log = get_logger(__name__)

# --- call follow-up mark ------------------------------------------------------------


class CallFollowUpIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The mark to set; null clears it.
    state: CallFollowUpState | None
    #: For an undo: the mark you expect the call to hold now. When sent (null included), the
    #: change is refused with 409 if the call holds something else. Leave it out to set the
    #: mark whatever it is.
    expected_state: CallFollowUpState | None = None


class CallFollowUpOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: UUID
    state: CallFollowUpState | None
    #: What it held before this request — what an Undo sends back as `state`.
    previous_state: CallFollowUpState | None
    set_at: datetime | None
    #: Who set the mark (a `users.id`); null when cleared, or set by an operator viewing the
    #: account.
    set_by: UUID | None
    #: False when the call already held this mark (nothing changed, nothing audited).
    changed: bool


async def set_call_follow_up(
    session: AsyncSession,
    call_id: UUID,
    *,
    state: CallFollowUpState | None,
    expected: tuple[bool, CallFollowUpState | None],
    user_id: UUID | None,
) -> CallFollowUpOut:
    """Compare-and-swap on `follow_up_state`. `expected` is (was it sent, its value)."""
    current = (
        await session.execute(
            text(
                "SELECT follow_up_state, follow_up_set_at, follow_up_set_by FROM calls "
                "WHERE id = :id"
            ),
            {"id": call_id},
        )
    ).first()
    if current is None:
        raise ProblemError.not_found("Call")
    before: CallFollowUpState | None = current.follow_up_state
    check_expected, expected_value = expected
    if check_expected and before != expected_value:
        raise ProblemError.conflict(
            "call_follow_up_changed",
            "Someone else changed this call's mark since you last saw it.",
            remediation="Reload the call to see its mark now.",
        )
    if before == state:
        return CallFollowUpOut(
            call_id=call_id,
            state=state,
            previous_state=before,
            set_at=current.follow_up_set_at,
            set_by=current.follow_up_set_by,
            changed=False,
        )
    row = (
        await session.execute(
            text(
                "UPDATE calls SET follow_up_state = :state, "
                "follow_up_set_at = CASE WHEN CAST(:state AS text) IS NULL THEN NULL "
                "ELSE now() END, "
                "follow_up_set_by = CASE WHEN CAST(:state AS text) IS NULL THEN NULL "
                "ELSE CAST(:by AS uuid) END, updated_at = now() "
                "WHERE id = :id AND follow_up_state IS NOT DISTINCT FROM :before "
                "RETURNING follow_up_set_at, follow_up_set_by"
            ),
            {"id": call_id, "state": state, "by": user_id, "before": before},
        )
    ).first()
    if row is None:
        raise ProblemError.conflict(
            "call_follow_up_changed",
            "Someone else changed this call's mark at the same moment.",
            remediation="Reload the call to see its mark now.",
        )
    return CallFollowUpOut(
        call_id=call_id,
        state=state,
        previous_state=before,
        set_at=row[0],
        set_by=row[1],
        changed=True,
    )


# --- call back later ------------------------------------------------------------------

#: The window a scheduled call-back may be put in, IST. The same hours outbound calling
#: keeps (`calevate_shared.calling_window`), checked here so a person picking 21:30 is told
#: at once rather than finding the call refused at fire time.
WINDOW_OPENS: Final = time(9, 0)
WINDOW_CLOSES: Final = time(21, 0)
MIN_LEAD_TIME: Final = timedelta(minutes=2)
MAX_AHEAD: Final = timedelta(days=30)


class ScheduleCallbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: When to ring, with its offset (IST: +05:30). Between 09:00 and 21:00 IST, at least two
    #: minutes from now and at most 30 days ahead.
    at: datetime
    #: What the call is about, told to the agent. Optional; at most 200 characters.
    note: str | None = Field(default=None, max_length=callbacks.MAX_NOTE)
    #: The agent that places the call. Left out: the lead's own agent when it can place
    #: calls, else the account's first live agent that can (`contact_agent`).
    agent_id: UUID | None = None


class ScheduleCallbackOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["scheduled", "blocked"]
    #: The call-back row (`GET /v1/callbacks/{id}`); `DELETE` it to undo.
    callback_id: UUID | None = None
    requested_at: datetime | None = None
    #: True when an earlier "call back later" for this lead was moved rather than a new one made.
    rescheduled: bool = False
    blocked_reason: str | None = None
    blocked_rule: str | None = None


def check_schedule_time(at: datetime, *, now: datetime) -> None:
    if at.tzinfo is None:
        raise _bad_time("Send the time with its offset, for example 2026-10-25T16:00:00+05:30.")
    local = at.astimezone(IST)
    if not (WINDOW_OPENS <= local.time() < WINDOW_CLOSES):
        raise _bad_time("Pick a time between 9am and 9pm India time.")
    if at < now + MIN_LEAD_TIME:
        raise _bad_time("Pick a time at least two minutes from now.")
    if at > now + MAX_AHEAD:
        raise _bad_time("Pick a time within the next 30 days.")


def _bad_time(detail: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code="callback_time_not_allowed",
        title="That time cannot be used",
        detail=detail,
        remediation="Choose a time between 9am and 9pm India time, within the next 30 days.",
    )


#: Gate refusals that waiting until the chosen time cannot lift: about the person, about a
#: trial account, or about the agent itself (one that only answers calls never places one).
#: Refused at once rather than booked to fail. Hours, credit and the halt can change by then
#: and stay the gate's to apply at fire time.
STANDING_REFUSALS: Final = (
    PERSON_LEVEL_REFUSALS
    | TRIAL_DIAL_REFUSALS
    | frozenset({"agent_inbound_only", "agent_missing", "disclosure_missing"})
)

_FIND_CLIENT_SCHEDULED: Final = (
    "SELECT id FROM scheduled_callbacks WHERE lead_id = :lid AND status = 'scheduled' "
    "AND source_execution_id LIKE :prefix ORDER BY created_at DESC LIMIT 1"
)
_MOVE: Final = (
    "UPDATE scheduled_callbacks SET requested_at = :at, booked_at = now(), note = :note, "
    "agent_id = :aid, next_attempt_at = NULL, updated_at = now() "
    "WHERE id = :id AND status = 'scheduled' RETURNING requested_at"
)
#: The account's first live agent that places calls — the fallback when the lead's own
#: agent only answers them, which is the usual case for a lead an inbound line captured.
_OUTBOUND_AGENT: Final = (
    "SELECT id FROM agents WHERE deleted_at IS NULL AND status = 'live' "
    "AND direction IN ('outbound', 'both') ORDER BY created_at, id LIMIT 1"
)


async def contact_agent(session: AsyncSession, lead_id: UUID, requested: UUID | None) -> UUID:
    """Which agent contacts this lead: the one asked for; else the lead's own agent when it
    places calls; else the account's first live agent that does; else the lead's own (and
    the gate then says why it cannot)."""
    if requested is not None:
        found = (
            await session.execute(
                text("SELECT id FROM agents WHERE id = :id AND deleted_at IS NULL"),
                {"id": requested},
            )
        ).scalar_one_or_none()
        if found is None:
            raise ProblemError.not_found("Agent")
        return requested
    own = (
        await session.execute(
            text(
                "SELECT l.agent_id, a.direction FROM leads l JOIN agents a ON a.id = l.agent_id "
                "WHERE l.id = :lid AND l.deleted_at IS NULL"
            ),
            {"lid": lead_id},
        )
    ).first()
    if own is None:
        raise ProblemError.not_found("Lead")
    if own.direction != "inbound":
        return UUID(str(own.agent_id))
    other = (await session.execute(text(_OUTBOUND_AGENT))).scalar_one_or_none()
    return UUID(str(other)) if other is not None else UUID(str(own.agent_id))


async def standing_refusal(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, phone: str
) -> DispatchDecision | None:
    """The dispatch gate's refusal that waiting until a booked time cannot lift
    (`STANDING_REFUSALS`), or None. The person first, on its own: in `check_dispatch` the
    hours and the account come before the do-not-call list, so a booking made at night
    would otherwise never learn the number is on it. Asked by the call-back route and by
    Pip's call-back actions before they book or move one."""
    decision = await person_level_refusal(
        session, tenant_id=tenant_id, phone_e164=phone
    ) or await check_dispatch(session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone)
    if not decision.allowed and decision.rule in STANDING_REFUSALS:
        return decision
    return None


async def schedule_lead_callback(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    lead_id: UUID,
    at: datetime,
    note: str | None,
    agent_id: UUID | None = None,
    now: datetime | None = None,
) -> ScheduleCallbackOut:
    """Book (or move) this lead's client-scheduled call-back.

    The dispatch gate is asked NOW for the refusals that will still hold at the chosen time
    (`STANDING_REFUSALS`), so the person is told at once. Every other rule (hours, credit, the
    halt) is the gate's to apply at fire time, as for every call-back.
    """
    check_schedule_time(at, now=now or datetime.now(UTC))
    phone, _name = await lead_phone(session, lead_id)
    agent_id = await contact_agent(session, lead_id, agent_id)
    refused = await standing_refusal(session, tenant_id=tenant_id, agent_id=agent_id, phone=phone)
    if refused is not None:
        return ScheduleCallbackOut(
            status="blocked", blocked_reason=refused.reason, blocked_rule=refused.rule
        )
    clean_note = (note or "").strip() or None
    existing = (
        await session.execute(
            text(_FIND_CLIENT_SCHEDULED),
            {"lid": lead_id, "prefix": f"{callbacks.CLIENT_SCHEDULE_PREFIX}%"},
        )
    ).scalar_one_or_none()
    if existing is not None:
        moved = (
            await session.execute(
                text(_MOVE), {"id": existing, "at": at, "note": clean_note, "aid": agent_id}
            )
        ).first()
        if moved is not None:
            return ScheduleCallbackOut(
                status="scheduled", callback_id=existing, requested_at=moved[0], rescheduled=True
            )
    callback_id = uuid7()
    booked = await callbacks.book(
        session,
        callback_id=callback_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        source_call_id=None,
        source_execution_id=f"{callbacks.CLIENT_SCHEDULE_PREFIX}{callback_id}",
        lead_id=lead_id,
        phone_e164=phone,
        requested_at=at,
        booked_at=datetime.now(UTC),
        note=clean_note,
        language=None,
    )
    assert booked is not None, "a fresh execution id cannot lose the booking race"
    return ScheduleCallbackOut(status="scheduled", callback_id=booked[0], requested_at=booked[1])


# --- WhatsApp follow-up ---------------------------------------------------------------


class WhatsAppTemplateChoiceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    language: str
    category: str
    #: The business's own template text with `{{1}}`-style blanks.
    body: str
    #: One `{label, example}` per blank, in order — what the screen asks the person to fill.
    variables: list[dict[str, str]]


class WhatsAppOptionsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: True when a message can be sent to this lead now.
    available: bool
    #: Why not, in a sentence; null when available.
    reason: str | None
    #: The machine word: `whatsapp_not_connected`, `whatsapp_no_approved_template`,
    #: `whatsapp_recipient_not_opted_in`, `whatsapp_blocked_<rule>`.
    rule: str | None
    templates: list[WhatsAppTemplateChoiceOut]


class WhatsAppSendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: UUID
    #: One value per blank, in order. Plain text the business writes; never sent anywhere
    #: but into this one message.
    values: list[str] = Field(default_factory=list, max_length=templates.MAX_VARIABLES)
    #: The agent the gate asks as; left out, the same choice as a scheduled call-back
    #: (`contact_agent`).
    agent_id: UUID | None = None


class WhatsAppSendOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["sent", "blocked", "failed"]
    reason: str | None = None
    rule: str | None = None


async def _connected_account(session: AsyncSession) -> accounts.Account | None:
    for account in await accounts.list_accounts(session):
        if (
            account.status == "connected"
            and account.phone_number_id
            and account.credential_id is not None
        ):
            return account
    return None


_APPROVED_SQL: Final = (
    "SELECT id, name, language, category, body, variables FROM whatsapp_templates "
    "WHERE account_id = :aid AND status = 'approved' ORDER BY name, language LIMIT :n"
)


async def _approved(session: AsyncSession, account_id: UUID) -> list[WhatsAppTemplateChoiceOut]:
    rows = (
        await session.execute(
            text(_APPROVED_SQL), {"aid": account_id, "n": templates.MAX_TEMPLATES_PER_ACCOUNT}
        )
    ).all()
    return [
        WhatsAppTemplateChoiceOut(
            id=r.id,
            name=r.name,
            language=r.language,
            category=r.category,
            body=r.body,
            variables=[{str(k): str(v) for k, v in item.items()} for item in (r.variables or [])],
        )
        for r in rows
    ]


_NOT_CONNECTED: Final = (
    "whatsapp_not_connected",
    "Connect your WhatsApp in Settings to send messages to leads.",
)
_NO_TEMPLATE: Final = (
    "whatsapp_no_approved_template",
    "None of your WhatsApp messages is approved yet. Add one on the WhatsApp screen and wait "
    "for approval.",
)


_NOT_OPTED_IN_REASON: Final = (
    "This person has not agreed to receive WhatsApp messages. Record their consent first."
)


async def _gate(
    session: AsyncSession, *, tenant_id: UUID, lead_id: UUID, agent_id: UUID | None
) -> tuple[str, str] | str:
    """The normalized number when the lead may be messaged, else (rule, reason). The gate is
    asked as the agent that contacts this lead (`contact_agent`), as for a call."""
    phone, _name = await lead_phone(session, lead_id)
    sender = await contact_agent(session, lead_id, agent_id)
    try:
        return await wa.assert_recipient_may_be_messaged(
            session, tenant_id=tenant_id, agent_id=sender, recipient_e164=phone
        )
    except wa.WhatsAppNotOptedInError as refused:
        return (refused.code, _NOT_OPTED_IN_REASON)
    except wa.WhatsAppBlockedError as refused:
        return (refused.code, refused.reason or "This number may not be contacted right now.")


async def whatsapp_options(
    session: AsyncSession, *, tenant_id: UUID, lead_id: UUID, agent_id: UUID | None = None
) -> WhatsAppOptionsOut:
    account = await _connected_account(session)
    if account is None:
        await lead_phone(session, lead_id)
        return WhatsAppOptionsOut(
            available=False, rule=_NOT_CONNECTED[0], reason=_NOT_CONNECTED[1], templates=[]
        )
    choices = await _approved(session, account.id)
    gate = await _gate(session, tenant_id=tenant_id, lead_id=lead_id, agent_id=agent_id)
    if isinstance(gate, tuple):
        return WhatsAppOptionsOut(available=False, rule=gate[0], reason=gate[1], templates=choices)
    if not choices:
        return WhatsAppOptionsOut(
            available=False, rule=_NO_TEMPLATE[0], reason=_NO_TEMPLATE[1], templates=[]
        )
    return WhatsAppOptionsOut(available=True, rule=None, reason=None, templates=choices)


async def _send(request: Any) -> int:
    """Put the Graph request on the wire through the egress guard; the HTTP status."""
    from apps.api.actions.execution import send_prepared
    from apps.api.integrations.egress_guard import egress_client

    async with egress_client(timeout=10.0) as http:
        response = await send_prepared(request, client=http)
    return response.status_code


async def send_whatsapp_follow_up(
    session: AsyncSession, *, tenant_id: UUID, lead_id: UUID, payload: WhatsAppSendIn
) -> tuple[WhatsAppSendOut, str | None]:
    """The gate, the consent, then one template message. Returns the answer and the
    template's name (for the audit row and the lead's timeline)."""
    account = await _connected_account(session)
    if account is None:
        await lead_phone(session, lead_id)
        return WhatsAppSendOut(
            status="blocked", rule=_NOT_CONNECTED[0], reason=_NOT_CONNECTED[1]
        ), None
    chosen = next(
        (t for t in await _approved(session, account.id) if t.id == payload.template_id), None
    )
    if chosen is None:
        return (
            WhatsAppSendOut(
                status="blocked",
                rule="whatsapp_template_not_approved",
                reason="That message is not approved for sending. Pick an approved one.",
            ),
            None,
        )
    wanted = len(set(templates.blanks(chosen.body)))
    values = [v.strip() for v in payload.values]
    if len(values) != wanted or any(not v for v in values):
        raise ProblemError(
            kind="validation",
            code="whatsapp_values_mismatch",
            title="Fill in every blank",
            detail=f"This message has {wanted} blank(s) and {len(values)} value(s) were sent.",
            remediation="Send one value for each blank, in order.",
        )
    gate = await _gate(session, tenant_id=tenant_id, lead_id=lead_id, agent_id=payload.agent_id)
    if isinstance(gate, tuple):
        return WhatsAppSendOut(status="blocked", rule=gate[0], reason=gate[1]), chosen.name
    token = await accounts.account_token(session, tenant_id=tenant_id, account=account)
    request = wa.build_meta_cloud(
        WhatsAppConfig(
            recipient_param="phone",
            template=chosen.name,
            language=chosen.language,
            phone_number_id=account.phone_number_id,
        ),
        access_token=token,
        recipient_e164=gate,
        header_value=None,
        body_values=values,
    )
    status_code = await _send(request)
    if 200 <= status_code < 300:
        return WhatsAppSendOut(status="sent"), chosen.name
    log.warning(
        "lead_whatsapp_follow_up_failed",
        extra={"tenant_id": str(tenant_id), "lead_id": str(lead_id), "status_code": status_code},
    )
    return (
        WhatsAppSendOut(
            status="failed",
            rule=f"whatsapp_http_{status_code}",
            reason="WhatsApp did not accept the message. Try again in a minute.",
        ),
        chosen.name,
    )


async def record_whatsapp_on_timeline(
    session: AsyncSession, *, lead_id: UUID, template: str | None, out: WhatsAppSendOut, actor: str
) -> None:
    """One `notification` row on the lead's timeline, delivered or not: "we never followed
    up" is a fact the client is entitled to see (the hot-lead and escalation legs do the
    same). Template NAME and the rule only — never the values typed into it."""
    result = await session.execute(
        text(
            "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, created_at, "
            "updated_at) SELECT :id, tenant_id, id, 'notification', jsonb_build_object("
            "'channel', 'whatsapp', 'kind', 'client_follow_up', 'status', CAST(:status AS text), "
            "'template', CAST(:template AS text), 'rule', CAST(:rule AS text)), :actor, now(), "
            "now() FROM leads WHERE id = :lid"
        ),
        {
            "id": uuid7(),
            "lid": lead_id,
            "status": out.status,
            "template": template,
            "rule": out.rule,
            "actor": actor,
        },
    )
    if rowcount_of(result) == 0:
        raise ProblemError.not_found("Lead")


__all__ = [
    "MAX_AHEAD",
    "CallFollowUpIn",
    "CallFollowUpOut",
    "ScheduleCallbackIn",
    "ScheduleCallbackOut",
    "WhatsAppOptionsOut",
    "WhatsAppSendIn",
    "WhatsAppSendOut",
    "WhatsAppTemplateChoiceOut",
    "check_schedule_time",
    "record_whatsapp_on_timeline",
    "schedule_lead_callback",
    "send_whatsapp_follow_up",
    "set_call_follow_up",
    "standing_refusal",
    "whatsapp_options",
]
