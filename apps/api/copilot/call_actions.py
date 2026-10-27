"""Pip's call and call-back actions that had a button and no assistant door (D-893 lane L1).

Each calls the function its console button calls, so the gate, the claim and the audit row
are the button's:

* `call_back` — "Have the agent call back now" on a call page: `crm/lead_dial.
  place_call_back`, keyed on the call, carrying our summary of it.
* `call_follow_up_set` — the call's "Done" / "Needs you" mark: `crm/swipe.
  set_call_follow_up`. Immediate with an Undo: it changes our own row and reaches nobody.
* `call_translate` — "Try again" on a call's English: `crm/translation.retranslate`. It
  spends the AI allowance, so it is confirm-first.
* `lead_whatsapp_send` — the lead's ⋯ "WhatsApp": `crm/lead_message.send_lead_whatsapp`.
* `callbacks_change_bulk` — move or call off many waiting call-backs as one plan; each
  target runs `crm/swipe.change_callback`, the Call-backs screen's row and bulk function.

Retrying unanswered calls is `calls_place_bulk` with `lens.last_outcome = missed`: the plan
already re-asks the gate per lead, and a second tool would be a second answer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, Final
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import require_ai_assist
from apps.api.billing.plans import IST
from apps.api.copilot import lens_args, plans
from apps.api.copilot.actions import (
    DOES_IT,
    PROPOSES_ONLY,
    ActionTool,
    Executed,
    Plan,
    ToolActor,
    Undo,
    UndoRecord,
    UndoRefusedError,
    WriteRefusedError,
    action_schema,
    parse_args,
    principal_of,
)
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.errors import ProblemError
from apps.api.crm import lead_dial, lead_message, swipe, translation
from apps.api.crm import lens as crm_lens
from apps.api.crm.models import CallFollowUpState
from apps.api.db.ownership import assert_visible
from apps.api.whatsapp import templates

_BILLED: Final = "Billed per minute at your plan's rate."


def _ist_words(instant: datetime) -> str:
    return instant.astimezone(IST).strftime("%a %d %b %Y, %H:%M IST")


class _CallArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: UUID


# --- call_back ------------------------------------------------------------------------


async def _plan_call_back(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    """READ ONLY: our chain rules and the dial gate, refused before a card in their words."""
    parsed = parse_args(_CallArgs, args)
    await assert_visible(session, "call", parsed.call_id)
    check = await lead_dial.call_back_check(
        session, tenant_id=actor.tenant_id, call_id=parsed.call_id
    )
    if not check.eligible:
        raise WriteRefusedError(
            f"this call-back cannot be placed and nothing was proposed — {check.rule}: "
            f"{check.reason}. Tell the person exactly this"
        )
    return Plan(
        object_id=str(parsed.call_id),
        title="Call back about this call",
        summary=(
            "The agent on this call rings the same person now, with a short summary of this "
            "call so it carries on where it left off."
        ),
        current=None,
        proposed=f"Follow-up call {check.follow_up_number}",
        cost=_BILLED,
        reversal="A call cannot be taken back once it has started ringing.",
        args={"call_id": str(parsed.call_id)},
    )


async def _execute_call_back(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_CallArgs, args)
    result = await lead_dial.place_call_back(
        session,
        principal=principal_of(actor),
        call_id=parsed.call_id,
        audit_extra={"via": "copilot"},
    )
    if result.status == "blocked":
        return Executed(
            applied=False,
            detail=f"The call was not placed: {result.blocked_reason}",
            audit_summary={"status": "blocked", "rule": result.blocked_rule},
        )
    return Executed(
        applied=True,
        detail="The call-back is being placed. It appears in Call logs as it happens.",
        audit_summary={"status": "queued", "follow_up_number": result.follow_up_number},
    )


CALL_BACK: Final = ActionTool(
    name="call_back",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="call",
    # `place_call_back` writes `call.callback_dispatched` itself; this row records that the
    # person confirmed the assistant's proposal.
    audit_action="call.callback_requested",
    where="in Call logs",
    schema=action_schema(
        "call_back",
        "Have the call's agent ring the same person now, carrying a summary of that call; "
        "a later time is `callback_book`." + PROPOSES_ONLY,
        {"call_id": {"type": "string", "description": "The earlier call's id."}},
    ),
    plan=_plan_call_back,
    execute=_execute_call_back,
)


# --- call_follow_up_set ---------------------------------------------------------------


_MARK_WORDS: Final[dict[str | None, str]] = {
    "resolved": "done",
    "needs_you": "needs you",
    None: "not marked",
}


class _FollowUpArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: UUID
    state: CallFollowUpState | None


async def _current_mark(session: AsyncSession, call_id: UUID) -> CallFollowUpState | None:
    row = (
        await session.execute(
            text("SELECT follow_up_state FROM calls WHERE id = :id"), {"id": call_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Call")
    mark: CallFollowUpState | None = row[0]
    return mark


async def _plan_follow_up(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_FollowUpArgs, args)
    await assert_visible(session, "call", parsed.call_id)
    current = await _current_mark(session, parsed.call_id)
    return Plan(
        object_id=str(parsed.call_id),
        title="Mark this call",
        summary=f"Mark this call {_MARK_WORDS[parsed.state]}.",
        current=_MARK_WORDS[current],
        proposed=_MARK_WORDS[parsed.state],
        cost=None,
        reversal="Undo puts the earlier mark back.",
        args={"call_id": str(parsed.call_id), "state": parsed.state},
    )


async def _execute_follow_up(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_FollowUpArgs, args)
    out = await swipe.set_call_follow_up(
        session,
        parsed.call_id,
        state=parsed.state,
        expected=(False, None),
        user_id=principal_of(actor).client_user_id,
    )
    words = _MARK_WORDS[parsed.state]
    return Executed(
        applied=out.changed,
        detail=f"Marked {words}." if out.changed else f"It was already {words}.",
        audit_summary={"state": out.state, "previous": out.previous_state},
    )


async def _capture_mark(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    del actor
    return {"state": await _current_mark(session, UUID(str(args["call_id"])))}


async def _invert_mark(session: AsyncSession, actor: ToolActor, record: UndoRecord) -> str:
    """The same compare-and-swap the screen's Undo sends: refused if someone marked it since."""
    prior: CallFollowUpState | None = record.prior_state.get("state")
    try:
        await swipe.set_call_follow_up(
            session,
            UUID(str(record.args["call_id"])),
            state=prior,
            expected=(True, record.result_state.get("state")),
            user_id=principal_of(actor).client_user_id,
        )
    except ProblemError as problem:
        if problem.kind != "conflict":
            raise
        raise UndoRefusedError(
            "someone has marked that call since, so it was left as it is"
        ) from problem
    return f"The call is {_MARK_WORDS[prior]} again."


CALL_FOLLOW_UP_SET: Final = ActionTool(
    name="call_follow_up_set",
    tier="immediate",
    undo=Undo(capture=_capture_mark, invert=_invert_mark),
    permission="leads:write",
    object_type="call",
    audit_action="call.follow_up_marked",
    where="on the call and in Call logs",
    schema=action_schema(
        "call_follow_up_set",
        "Mark one call's follow-up done (`resolved`), `needs_you`, or clear it (null)." + DOES_IT,
        {
            "call_id": {"type": "string", "description": "The call's id."},
            "state": {
                "anyOf": [{"type": "string", "enum": ["resolved", "needs_you"]}, {"type": "null"}]
            },
        },
    ),
    plan=_plan_follow_up,
    execute=_execute_follow_up,
)


# --- call_translate -------------------------------------------------------------------


async def _plan_translate(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    """READ ONLY: a call with nothing to retry, or an account at its ceiling, is refused
    before the card, as the button answers before it queues."""
    parsed = parse_args(_CallArgs, args)
    await assert_visible(session, "call", parsed.call_id)
    state = await translation.translation_state(session, parsed.call_id)
    if state not in translation.RETRYABLE_STATES:
        raise WriteRefusedError(
            f"this call's English is `{state}`, so there is nothing to make again; tell the "
            "person, and read it with call_detail if it is ready"
        )
    await require_ai_assist(session, tenant_id=actor.tenant_id)
    return Plan(
        object_id=str(parsed.call_id),
        title="Put this call into English",
        summary=(
            "This call's conversation is put into English again, with phone numbers and "
            "other identifiers hidden. It shows on the call page in a minute or two."
        ),
        current="No English yet",
        proposed="English on the call page",
        cost="Uses your account's AI help allowance.",
        reversal="The English stays on the call once it is made.",
        args={"call_id": str(parsed.call_id)},
    )


async def _execute_translate(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_CallArgs, args)
    state, retried = await translation.retranslate(
        session, tenant_id=actor.tenant_id, call_id=parsed.call_id
    )
    return Executed(
        applied=retried and state == "pending",
        detail=(
            "The English is being made; it shows on the call page in a minute or two."
            if retried
            else f"Nothing to do: the call's English is {state.replace('_', ' ')}."
        ),
        audit_summary={"state": state},
    )


CALL_TRANSLATE: Final = ActionTool(
    name="call_translate",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="call",
    audit_action="call.translation_requested",
    where="on the call page",
    schema=action_schema(
        "call_translate",
        "Make a call's English again when it failed or was never made." + PROPOSES_ONLY,
        {"call_id": {"type": "string", "description": "The call's id."}},
    ),
    plan=_plan_translate,
    execute=_execute_translate,
)


# --- lead_whatsapp_send ---------------------------------------------------------------


class _WhatsAppArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: UUID
    template_id: UUID | None
    values: list[Annotated[str, Field(max_length=200)]] = Field(max_length=templates.MAX_VARIABLES)


def _template_menu(choices: Sequence[swipe.WhatsAppTemplateChoiceOut]) -> str:
    return "; ".join(
        f"[template_id {t.id}] {strip_invisible(t.name)} ({t.language}), blanks: "
        + (", ".join(strip_invisible(v.get("label", "?")) for v in t.variables) or "none")
        for t in choices
    )


async def _plan_whatsapp(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    """READ ONLY: the lead's options as the ⋯ menu reads them. Without a template, or with a
    wrong one, the refusal lists the approved messages and their blanks, so the next call
    can be right without a separate read."""
    parsed = parse_args(_WhatsAppArgs, args)
    options = await swipe.whatsapp_options(
        session, tenant_id=actor.tenant_id, lead_id=parsed.lead_id
    )
    if not options.available:
        raise WriteRefusedError(
            f"no WhatsApp message can be sent to this lead now — {options.rule}: "
            f"{options.reason}. Tell the person exactly this"
        )
    chosen = next((t for t in options.templates if t.id == parsed.template_id), None)
    if chosen is None:
        raise WriteRefusedError(
            "pick one approved message by its template_id and give one value per blank, in "
            "order: " + _template_menu(options.templates)
        )
    values = [strip_invisible(v).strip() for v in parsed.values]
    blanks = len(set(templates.blanks(chosen.body)))
    if len(values) != blanks or any(not v for v in values):
        raise WriteRefusedError(
            f"that message has {blanks} blank(s); ask the person for each and pass them in "
            "`values`, in order"
        )
    filled = chosen.body
    for index, value in enumerate(values, start=1):
        filled = filled.replace(f"{{{{{index}}}}}", value)
    return Plan(
        object_id=str(parsed.lead_id),
        title="Send a WhatsApp message",
        summary=f"Send “{strip_invisible(chosen.name)}” to this lead: {strip_invisible(filled)}",
        current=None,
        proposed="One WhatsApp message",
        cost="WhatsApp may charge your connected WhatsApp account for the message.",
        reversal="A sent message cannot be taken back.",
        args={
            "lead_id": str(parsed.lead_id),
            "template_id": str(chosen.id),
            "values": values,
            # The send's idempotency key, so a retried confirm answers with the first result
            # rather than sending twice.
            "attempt": str(uuid4()),
        },
    )


class _WhatsAppSigned(_WhatsAppArgs):
    attempt: UUID


async def _execute_whatsapp(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_WhatsAppSigned, args)
    if parsed.template_id is None:
        raise WriteRefusedError("`template_id` was missing")
    out = await lead_message.send_lead_whatsapp(
        session,
        principal=principal_of(actor),
        lead_id=parsed.lead_id,
        payload=swipe.WhatsAppSendIn(template_id=parsed.template_id, values=parsed.values),
        idempotency_key=f"copilot:{parsed.attempt}",
        audit_extra={"via": "copilot"},
    )
    if out.status != "sent":
        return Executed(
            applied=False,
            detail=f"The message was not sent: {out.reason}",
            audit_summary={"status": out.status, "rule": out.rule},
        )
    return Executed(
        applied=True,
        detail="The WhatsApp message is sent. It shows on the lead's timeline.",
        audit_summary={"status": "sent"},
    )


LEAD_WHATSAPP_SEND: Final = ActionTool(
    name="lead_whatsapp_send",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="lead",
    # `send_lead_whatsapp` writes `lead.whatsapp_follow_up` itself; this row records the
    # person's confirmation.
    audit_action="lead.whatsapp_requested",
    where="on the lead's timeline",
    schema=action_schema(
        "lead_whatsapp_send",
        "Send one approved WhatsApp message to a lead who agreed to receive them. Without "
        "`template_id` the refusal lists the approved messages and their blanks." + PROPOSES_ONLY,
        {
            "lead_id": {"type": "string", "description": "The lead's id."},
            "template_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "values": {
                "type": "array",
                "items": {"type": "string"},
                "description": "One value per blank, in order, from the person.",
            },
        },
    ),
    plan=_plan_whatsapp,
    execute=_execute_whatsapp,
)


# --- callbacks_change_bulk ------------------------------------------------------------


#: The call-backs a selection may name explicitly; anything larger is a lens.
MAX_NAMED_CALLBACKS: Final = 500


class _BulkCallbackChange(BaseModel):
    model_config = ConfigDict(extra="ignore")

    change: swipe.CallbackChange
    at: str | None = None


def _move_time(raw: str | None) -> datetime:
    if raw is None:
        raise WriteRefusedError("moving needs `at`; ask the person when")
    try:
        local = datetime.fromisoformat(raw.strip())
    except ValueError as exc:
        raise WriteRefusedError("`at` must look like 2026-10-28T10:30 (India time)") from exc
    instant = local if local.tzinfo else local.replace(tzinfo=IST)
    try:
        swipe.check_schedule_time(instant, now=datetime.now(UTC))
    except ProblemError as problem:
        raise WriteRefusedError(f"{problem.detail} Ask the person for another time") from problem
    return instant.astimezone(UTC)


async def _chosen_callbacks(
    session: AsyncSession, args: Mapping[str, Any]
) -> tuple[list[UUID], str]:
    """`callback_ids` from `callbacks_list`, or the waiting call-backs of the leads `lens`
    names. Exactly one."""
    raw_ids = args.get("callback_ids")
    raw_lens = args.get("lens")
    if raw_ids and raw_lens:
        raise WriteRefusedError("give `lens` or `callback_ids`, not both")
    if raw_ids:
        if not isinstance(raw_ids, list) or len(raw_ids) > MAX_NAMED_CALLBACKS:
            raise WriteRefusedError(
                f"`callback_ids` takes at most {MAX_NAMED_CALLBACKS}; use `lens` for more"
            )
        try:
            wanted = [UUID(str(value)) for value in raw_ids]
        except ValueError as exc:
            raise WriteRefusedError("`callback_ids` holds something that is not an id") from exc
        rows = await session.execute(
            text("SELECT id FROM scheduled_callbacks WHERE id = ANY(:ids)"), {"ids": wanted}
        )
        found = {UUID(str(r[0])) for r in rows.all()}
        ids = [value for value in dict.fromkeys(wanted) if value in found]
        return ids, f"the {len(ids)} call-backs you chose"
    if raw_lens is None:
        raise WriteRefusedError(
            "say which call-backs: `callback_ids` from callbacks_list, or a leads `lens`"
        )
    try:
        lens = lens_args.lead_lens(raw_lens)
    except lens_args.LensArgumentError as refused:
        raise WriteRefusedError(refused.reason) from refused
    scope = await crm_lens.resolve_lead_scope(session, lens)
    lead_ids = await crm_lens.lead_ids(session, scope)
    rows = await session.execute(
        text(
            "SELECT id FROM scheduled_callbacks WHERE lead_id = ANY(:ids) "
            "AND status = 'scheduled' ORDER BY requested_at, id"
        ),
        {"ids": lead_ids},
    )
    return (
        [UUID(str(r[0])) for r in rows.all()],
        "waiting call-backs of " + crm_lens.describe_lead_lens(lens),
    )


async def _prepare_change(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> plans.Prepared:
    del actor
    parsed = parse_args(_BulkCallbackChange, args)
    when = _move_time(parsed.at) if parsed.change == "move" else None
    targets, lens_text = await _chosen_callbacks(session, args)
    n = len(targets)
    return plans.Prepared(
        targets=targets,
        lens_text=lens_text,
        title=f"Move {n} call-backs" if when else f"Call off {n} call-backs",
        why=f"Move each to {_ist_words(when)}" if when else "Nobody is rung for them",
        change={"change": parsed.change, "at": None if when is None else when.isoformat()},
    )


async def _exclude_change(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], ids: Sequence[UUID]
) -> dict[UUID, str]:
    """Not waiting any more; and for a move, the standing refusals the new time cannot lift."""
    rows = await session.execute(
        text(
            "SELECT id, status, agent_id, phone_e164 FROM scheduled_callbacks WHERE id = ANY(:ids)"
        ),
        {"ids": list(ids)},
    )
    left_out: dict[UUID, str] = {}
    for r in rows.all():
        callback_id = UUID(str(r[0]))
        if r[1] != "scheduled":
            left_out[callback_id] = "It is no longer waiting."
        elif change.get("change") == "move":
            refused = await swipe.standing_refusal(
                session, tenant_id=actor.tenant_id, agent_id=UUID(str(r[2])), phone=str(r[3])
            )
            if refused is not None:
                left_out[callback_id] = refused.reason or "The calling rules do not allow it."
    return left_out


async def _no_cost(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], n: int
) -> plans.Estimate:
    del session, actor, change, n
    return plans.NO_COST


async def _run_change(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], callback_id: UUID
) -> plans.TargetOutcome:
    """`swipe.change_callback` — the Call-backs screen's own function, per call-back."""
    parsed = _BulkCallbackChange.model_validate(change)
    out = await swipe.change_callback(
        session,
        tenant_id=actor.tenant_id,
        callback_id=callback_id,
        change=parsed.change,
        at=None if parsed.at is None else datetime.fromisoformat(parsed.at),
    )
    if out.status in ("cancelled", "moved"):
        return plans.TargetOutcome("done")
    return plans.TargetOutcome("skipped", out.reason or "It is no longer waiting.")


CHANGE_CALLBACKS: Final = plans.SetAction(
    target_type="callback",
    prepare=_prepare_change,
    exclude=_exclude_change,
    estimate=_no_cost,
    run_one=_run_change,
)

CALLBACKS_CHANGE_BULK: Final = plans.set_action_tool(
    name="callbacks_change_bulk",
    permission="leads:dispatch",
    object_type="callback",
    audit_action="callback.bulk_changed",
    where="on the Call-backs screen",
    description=(
        "Move (`at`, India time) or call off many waiting call-backs, by `callback_ids` or a "
        "leads `lens`. The person approves one plan."
    ),
    properties={
        "change": {"type": "string", "enum": ["move", "cancel"]},
        "at": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "callback_ids": {
            "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]
        },
        "lens": lens_args.LEAD_LENS_SCHEMA,
    },
    action=CHANGE_CALLBACKS,
)


CALL_ACTIONS: Final = (
    CALL_BACK,
    CALL_FOLLOW_UP_SET,
    CALL_TRANSLATE,
    LEAD_WHATSAPP_SEND,
    CALLBACKS_CHANGE_BULK,
)

__all__ = [
    "CALLBACKS_CHANGE_BULK",
    "CALL_ACTIONS",
    "CALL_BACK",
    "CALL_FOLLOW_UP_SET",
    "CALL_TRANSLATE",
    "CHANGE_CALLBACKS",
    "LEAD_WHATSAPP_SEND",
]
