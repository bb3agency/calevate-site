"""The client assistant's console actions (D-698): the buttons on the Leads, Campaigns,
Agents, Calls, Call-backs, Knowledge base and Your phone number screens, as tools.

Every tool here follows `docs/COPILOT-CONTRACT.md`. Read §1 for the tiers before adding
one; what follows is only what is particular to this module.

═══ THE TIER OF EACH, IN ONE PLACE ═══

`immediate` (runs, leaves an Undo): assigning a lead, creating or cloning a DRAFT campaign,
editing an agent that is not live, and changing the fields an agent captures. None reaches
a caller or spends anything, and each inverse is exact.

`confirm` (a preview, then a click): anything that dials (`call_place`), books or moves an
automatic call-back, adds people to a campaign's dial list, schedules or resumes dialling,
puts an agent's change in front of callers (`agent_edit_live`, `agent_changes_apply`,
business hours), takes an agent off the phone or deletes it, removes a do-not-call entry,
renames or bulk-changes leads, adds or removes knowledge (it goes live at once), and buys
or releases a number.

Two of those are confirm for a reason that is not obvious. `lead_rename`: its inverse would
need the lead's OLD NAME stored in `copilot_actions.prior_state`, and that column holds ids,
statuses and our own object names only (the contract §2, and the published erasure
statement for the table in `scripts/check_erasure_coverage.py`) — a caller's name there is
one a per-subject erasure cannot find. `leads_bulk_update`: the founder asked for a count
preview before a bulk change, and a preview is the confirm card.

═══ WHAT IS DELIBERATELY NOT HERE ═══

The no-cold-calls pledge, legal acceptance and KYC uploads: no tool may exist (D-694). A
test call to the owner's own phone: no route exists to call (the trial lane, D-697). Free
text prompt editing: the console edits a structured script, and the assistant applies or
discards what was saved there (`agent_changes_apply`) rather than writing a second editor.

═══ SERVICES THAT OPEN THEIR OWN TRANSACTION ═══

`set_agent_voice`, `set_disclosure_posture`, `apply_to_live` and `purchase_engine_number`
each open their own session (they push to the voice platform inside it). They are called
BEFORE anything in the action's own transaction touches the agent row, and the inverse
compares without `FOR UPDATE`, because a row lock held by the outer transaction would
deadlock the inner one. The compare-and-swap is then the service's own lock.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Final, Literal, get_args
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import lifecycle
from apps.api.agents.languages import LANGUAGE_LABELS, PRODUCT_LANGUAGES, OfferedLanguage
from apps.api.campaigns import service as campaigns_service
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
)
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.crm import service as crm_service
from apps.api.crm.schemas import LeadStatus
from apps.api.db.base import uuid7
from apps.api.db.ownership import assert_visible

IST: Final = ZoneInfo("Asia/Kolkata")

#: What every voice minute costs, said the same way as `agent_actions._BILLED_PER_MINUTE`
#: and for its reason: the rate is the plan's, never a figure typed into a prompt module.
_BILLED_PER_MINUTE: Final = (
    "Calls are billed per minute at your plan's rate — see Credits & billing for the amount."
)

#: The most leads one bulk or campaign action may name. `POST /v1/leads/bulk` takes 500;
#: a list longer than this is a screen's job, where a person can see what they selected.
MAX_LEADS_PER_ACTION: Final = 100

_MAX_NAME: Final = 120


def _principal_of(actor: ToolActor) -> Principal:
    """The principal a service that writes its own audit row needs (`place_lead_call`)."""
    return Principal(
        realm="client",
        user_id=actor.user_id,
        tenant_id=actor.tenant_id,
        role=actor.role,
        impersonating=actor.impersonating,
    )


def _ist_instant(raw: str, *, field: str) -> datetime:
    """`YYYY-MM-DDTHH:MM` read as India time, refused unless it is in the future."""
    try:
        local = datetime.fromisoformat(raw.strip())
    except ValueError as exc:
        raise WriteRefusedError(f"`{field}` must look like 2026-10-12T10:30 (India time)") from exc
    instant = (local if local.tzinfo else local.replace(tzinfo=IST)).astimezone(UTC)
    if instant <= datetime.now(UTC) + timedelta(minutes=1):
        raise WriteRefusedError(f"`{field}` is in the past, so ask the person for a later time")
    return instant


def _ist_words(instant: datetime) -> str:
    return instant.astimezone(IST).strftime("%a %d %b %Y, %H:%M IST")


async def _agent_name_status(session: AsyncSession, agent_id: UUID) -> tuple[str, str]:
    await assert_visible(session, "agent", agent_id)
    row = (
        await session.execute(
            text("SELECT name, status FROM agents WHERE id = :aid AND deleted_at IS NULL"),
            {"aid": agent_id},
        )
    ).first()
    if row is None:  # pragma: no cover - `assert_visible` has already 404'd an absent row
        raise ProblemError.not_found("Agent")
    return strip_invisible(str(row[0])), str(row[1])


async def _campaign_name_status(session: AsyncSession, campaign_id: UUID) -> tuple[str, str]:
    row = (
        await session.execute(
            text("SELECT name, status FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
        )
    ).first()
    if row is None:
        # RLS makes a neighbour's campaign the same answer, deliberately.
        raise ProblemError.not_found("Campaign")
    return strip_invisible(str(row[0])), str(row[1])


def _clean_name(raw: str, *, what: str) -> str:
    name = strip_invisible(raw.strip())
    if len(name) < 2:
        raise WriteRefusedError(f"the {what} name was blank, so ask the person what to call it")
    if len(name) > _MAX_NAME:
        raise WriteRefusedError(f"the {what} name is longer than {_MAX_NAME} characters")
    return name


# =========================================================================================
# LEADS
# =========================================================================================


class _LeadAssignArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: UUID
    #: None takes the lead away from whoever owns it.
    user_id: UUID | None


async def _member_name(session: AsyncSession, user_id: UUID | None) -> str:
    """A colleague's display name under RLS on `memberships`, or a refusal for a stranger."""
    if user_id is None:
        return "nobody"
    row = (
        await session.execute(
            text(
                "SELECT u.name FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.user_id = :uid AND u.deactivated_at IS NULL"
            ),
            {"uid": user_id},
        )
    ).first()
    if row is None:
        raise WriteRefusedError(
            "that person is not on this account's team, so look them up with `team_members`"
        )
    return strip_invisible(str(row[0] or "a team member"))


async def _plan_lead_assign(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_LeadAssignArgs, args)
    lead = await crm_service.get_lead(session, parsed.lead_id)
    current = await _member_name(session, lead.assigned_to) if lead.assigned_to else "nobody"
    proposed = await _member_name(session, parsed.user_id)
    return Plan(
        object_id=str(parsed.lead_id),
        title="Change who owns this lead",
        summary=f"Give this lead to {proposed}. It belonged to {current}.",
        current=current,
        proposed=proposed,
        cost=None,
        reversal=f"Undo gives it back to {current}.",
        args={
            "lead_id": str(parsed.lead_id),
            "user_id": None if parsed.user_id is None else str(parsed.user_id),
        },
    )


async def _execute_lead_assign(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`crm_service.update_lead(assignee=...)` — `PATCH /v1/leads/{id}`'s call."""
    parsed = parse_args(_LeadAssignArgs, args)
    before = await crm_service.get_lead(session, parsed.lead_id)
    after = await crm_service.update_lead(
        session,
        parsed.lead_id,
        status=None,
        name=None,
        assignee=crm_service.AssigneeChange(user_id=parsed.user_id),
        actor=str(actor.user_id),
    )
    applied = before.assigned_to != after.assigned_to
    return Executed(
        applied=applied,
        detail="The lead's owner has changed." if applied else "It already had that owner.",
        audit_summary={
            "assigned_to": None if parsed.user_id is None else str(parsed.user_id),
            "moved": applied,
        },
    )


async def _capture_lead_assign(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    del actor
    lead = await crm_service.get_lead(session, parse_args(_LeadAssignArgs, args).lead_id)
    return {"assigned_to": None if lead.assigned_to is None else str(lead.assigned_to)}


async def _invert_lead_assign(session: AsyncSession, actor: ToolActor, record: UndoRecord) -> str:
    lead_id = UUID(str(record.args["lead_id"]))
    row = (
        await session.execute(
            text("SELECT assigned_to FROM leads WHERE id = :lid AND deleted_at IS NULL FOR UPDATE"),
            {"lid": lead_id},
        )
    ).first()
    if row is None:
        raise UndoRefusedError("that lead has been deleted, so there is nothing to give back")
    now = None if row[0] is None else str(row[0])
    if now != record.result_state.get("assigned_to"):
        raise UndoRefusedError("that lead has changed hands again since, so it was left alone")
    prior = record.prior_state.get("assigned_to")
    await crm_service.update_lead(
        session,
        lead_id,
        status=None,
        name=None,
        assignee=crm_service.AssigneeChange(user_id=None if prior is None else UUID(str(prior))),
        actor=str(actor.user_id),
    )
    return "The lead is back with its previous owner."


LEAD_ASSIGN: Final = ActionTool(
    name="lead_assign",
    tier="immediate",
    undo=Undo(capture=_capture_lead_assign, invert=_invert_lead_assign),
    permission="leads:write",
    object_type="lead",
    # The PATCH route writes no audit row (the lead's own timeline records it); an act a
    # machine performed needs one naming the person who asked.
    audit_action="lead.assigned",
    where="on the lead's own screen",
    schema=action_schema(
        "lead_assign",
        "Give one lead to a team member, or take it away from its owner. Find the person's "
        "id with `team_members`." + DOES_IT,
        {
            "lead_id": {"type": "string", "description": "The lead's id, never invented."},
            "user_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "The team member's id from `team_members`, or null for nobody.",
            },
        },
    ),
    plan=_plan_lead_assign,
    execute=_execute_lead_assign,
)


class _LeadRenameArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: UUID
    name: str


async def _plan_lead_rename(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    """The OLD name is not quoted: it is a caller's name, and this card is also a log line."""
    del actor
    parsed = parse_args(_LeadRenameArgs, args)
    name = _clean_name(parsed.name, what="lead's")
    await crm_service.get_lead(session, parsed.lead_id)
    return Plan(
        object_id=str(parsed.lead_id),
        title="Rename this lead",
        summary=f"Change this lead's name to “{name}”.",
        current=None,
        proposed=name,
        cost=None,
        reversal="You can change the name again on the lead's screen; the old name is not kept.",
        args={"lead_id": str(parsed.lead_id), "name": name},
    )


async def _execute_lead_rename(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_LeadRenameArgs, args)
    before = await crm_service.get_lead(session, parsed.lead_id)
    await crm_service.update_lead(
        session, parsed.lead_id, status=None, name=parsed.name, actor=str(actor.user_id)
    )
    applied = before.name != parsed.name
    return Executed(
        applied=applied,
        detail="The lead has its new name." if applied else "It already had that name.",
        # The name is a caller's personal data and `audit_log` is append-only.
        audit_summary={"renamed": applied},
    )


LEAD_RENAME: Final = ActionTool(
    name="lead_rename",
    tier="confirm",
    undo=None,
    permission="leads:write",
    object_type="lead",
    audit_action="lead.renamed",
    where="on the lead's own screen",
    schema=action_schema(
        "lead_rename",
        "Propose changing the name on one lead, for example to correct a misheard name."
        + PROPOSES_ONLY,
        {
            "lead_id": {"type": "string", "description": "The lead's id, never invented."},
            "name": {"type": "string", "description": "The corrected name, as the person said it."},
        },
    ),
    plan=_plan_lead_rename,
    execute=_execute_lead_rename,
)


class _LeadsBulkArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_ids: Annotated[list[UUID], Field(min_length=1, max_length=MAX_LEADS_PER_ACTION)]
    action: Literal["status", "assign"]
    status: LeadStatus | None
    user_id: UUID | None
    #: Set by the PLANNER, never the model: how many of the ids were found, so a list that
    #: changed between the card and the click is refused exactly as `POST /v1/leads/bulk`
    #: refuses a moved `expected_count`.
    expected: int | None = None


async def _plan_leads_bulk(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_LeadsBulkArgs, {**args, "expected": None})
    if parsed.action == "status" and parsed.status is None:
        raise WriteRefusedError("a status change needs `status`")
    targets = await crm_service.resolve_bulk_targets(session, ids=list(parsed.lead_ids))
    if not targets.ids:
        raise ProblemError.not_found("Lead")
    if parsed.action == "status":
        change = f"mark them {parsed.status}"
    else:
        change = f"give them to {await _member_name(session, parsed.user_id)}"
    missing = (
        f" {len(targets.missing)} of the ids named no lead and are left out."
        if targets.missing
        else ""
    )
    return Plan(
        object_id="",
        title=f"Change {len(targets.ids)} leads",
        summary=f"For {len(targets.ids)} lead(s), {change}.{missing}",
        current=None,
        proposed=f"{len(targets.ids)} lead(s): {change}",
        cost=None,
        reversal=(
            "There is no single undo for a bulk change; each lead can be changed back on "
            "the Leads screen."
        ),
        args={
            "lead_ids": [str(i) for i in targets.ids],
            "action": parsed.action,
            "status": parsed.status,
            "user_id": None if parsed.user_id is None else str(parsed.user_id),
            "expected": len(targets.ids),
        },
    )


async def _execute_leads_bulk(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`resolve_bulk_targets` then `apply_bulk_leads` — `POST /v1/leads/bulk`'s two calls."""
    parsed = parse_args(_LeadsBulkArgs, args)
    targets = await crm_service.resolve_bulk_targets(session, ids=list(parsed.lead_ids))
    if parsed.expected is not None and len(targets.ids) != parsed.expected:
        raise ProblemError(
            kind="conflict",
            code="lead_bulk_set_moved",
            title="The selection changed",
            detail="Some of these leads changed since the preview, so nothing was done.",
            remediation="Ask the assistant again to see the new count.",
        )
    outcome = await crm_service.apply_bulk_leads(
        session,
        targets=targets,
        action=parsed.action,
        status=parsed.status,
        assignee=(
            crm_service.AssigneeChange(user_id=parsed.user_id)
            if parsed.action == "assign"
            else None
        ),
        actor=str(actor.user_id),
    )
    return Executed(
        applied=outcome.changed > 0,
        detail=(
            f"{outcome.changed} lead(s) changed, {outcome.unchanged} were already that way"
            + (f", {len(outcome.failures)} could not be changed" if outcome.failures else "")
            + "."
        ),
        audit_summary={
            "action": parsed.action,
            "requested": outcome.requested,
            "changed": outcome.changed,
            "unchanged": outcome.unchanged,
            "failed": len(outcome.failures),
        },
    )


LEADS_BULK_UPDATE: Final = ActionTool(
    name="leads_bulk_update",
    tier="confirm",
    undo=None,
    permission="leads:write",
    object_type="lead",
    audit_action="lead.bulk_action",
    where="on the Leads screen",
    schema=action_schema(
        "leads_bulk_update",
        f"Propose changing the status or the owner of up to {MAX_LEADS_PER_ACTION} leads at "
        "once. The person sees how many leads it affects before confirming." + PROPOSES_ONLY,
        {
            "lead_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The leads' ids, from the SCREEN STATE selection or a lookup.",
            },
            "action": {"type": "string", "enum": ["status", "assign"]},
            "status": {
                "anyOf": [{"type": "string", "enum": list(get_args(LeadStatus))}, {"type": "null"}],
                "description": "With `status`, the new status; null with `assign`.",
            },
            "user_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "With `assign`: the team member's id, or null for nobody.",
            },
        },
    ),
    plan=_plan_leads_bulk,
    execute=_execute_leads_bulk,
)


class _DncRemoveArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: UUID


async def _dnc_entry_for(session: AsyncSession, actor: ToolActor, lead_id: UUID) -> UUID:
    """The do-not-call entry suppressing this lead's number — found by the server from the
    lead, so the model is never told a number — or a refusal that says which kind it is."""
    from apps.api.compliance import dnc

    phone, _name = await crm_service.lead_phone(session, lead_id)
    row = (
        await session.execute(
            text(
                "SELECT id, scope, source FROM dnc_list WHERE phone_e164 = :p "
                "AND (tenant_id = :t OR tenant_id IS NULL) "
                "ORDER BY (scope = 'global') DESC LIMIT 1"
            ),
            {"p": phone, "t": actor.tenant_id},
        )
    ).first()
    if row is None:
        raise WriteRefusedError("that lead's number is not on the do-not-call list")
    source = None if row[2] is None else str(row[2])
    if not dnc.is_removable(scope=str(row[1]), source=source):
        # THE LAW PATH (hard rule 5): a consumer's own opt-out, a regulator's entry and the
        # platform-wide list are never lifted here, and `remove_entry` would refuse them too.
        raise WriteRefusedError(
            "that number is on the list because the person asked not to be called, or by a "
            "regulator or the platform-wide list, and that cannot be undone here — tell the "
            "person so, and that support can look at a genuine mistake"
        )
    return UUID(str(row[0]))


async def _plan_dnc_remove(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    parsed = parse_args(_DncRemoveArgs, args)
    entry_id = await _dnc_entry_for(session, actor, parsed.lead_id)
    return Plan(
        object_id=str(entry_id),
        title="Allow calls to this lead again",
        summary=(
            "Take this lead's number off your do-not-call list, where it was added by hand. "
            "Campaigns and call-backs may call it again afterwards."
        ),
        current="On your do-not-call list",
        proposed="Callable",
        cost=None,
        reversal="You can add the number back to the do-not-call list at any time.",
        args={"lead_id": str(parsed.lead_id), "entry_id": str(entry_id)},
    )


class _DncRemoveSigned(_DncRemoveArgs):
    entry_id: UUID


async def _execute_dnc_remove(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`dnc.remove_entry` — `DELETE /v1/dnc/{entry_id}`'s call, which re-checks removability
    inside the DELETE so a concurrent upgrade to an opt-out is never lifted."""
    from apps.api.compliance import dnc

    del actor
    parsed = parse_args(_DncRemoveSigned, args)
    removal = await dnc.remove_entry(session, entry_id=parsed.entry_id)
    return Executed(
        applied=True,
        detail="That number is off your do-not-call list.",
        audit_summary={"source": removal.source, "subject_ref": removal.subject_ref},
    )


DNC_REMOVE: Final = ActionTool(
    name="dnc_remove",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="dnc_list",
    audit_action="dnc.removed",
    where="on the Do not call screen",
    schema=action_schema(
        "dnc_remove",
        "Propose taking one lead's number off this account's do-not-call list. Only an entry "
        "added by hand can be removed; a caller's own request not to be called never can, "
        "and you must say so if refused. Name the lead by id; you are never told the "
        "number." + PROPOSES_ONLY,
        {"lead_id": {"type": "string", "description": "The lead's id, never invented."}},
    ),
    plan=_plan_dnc_remove,
    execute=_execute_dnc_remove,
)


# =========================================================================================
# CALLS AND CALL-BACKS
# =========================================================================================


class _CallPlaceArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: UUID
    agent_id: UUID
    note: Annotated[str, Field(max_length=500)] | None


async def _plan_call_place(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    """READ ONLY, and it asks the dial gate (`check_dispatch`) so a call the platform will
    refuse — calling hours, do-not-call, KYC, the pledge, credit, the big red switch — is
    refused here with the gate's own reason rather than after a click. The gate runs again
    at the click."""
    from apps.api.compliance.service import check_dispatch

    parsed = parse_args(_CallPlaceArgs, args)
    agent_name, _status = await _agent_name_status(session, parsed.agent_id)
    phone, _name = await crm_service.lead_phone(session, parsed.lead_id)
    decision = await check_dispatch(
        session, tenant_id=actor.tenant_id, agent_id=parsed.agent_id, phone_e164=phone
    )
    if not decision.allowed:
        raise WriteRefusedError(
            "this call cannot be placed right now and nothing was proposed — "
            f"{decision.rule}: {decision.reason}. Tell the person exactly this"
        )
    note = None if parsed.note is None else (strip_invisible(parsed.note.strip()) or None)
    return Plan(
        object_id=str(parsed.lead_id),
        title="Call this lead now",
        summary=f"“{agent_name}” calls this lead now. Their phone rings as soon as you confirm.",
        current=None,
        proposed="A call now",
        cost=_BILLED_PER_MINUTE,
        reversal="A call cannot be taken back once it has started ringing.",
        args={
            "lead_id": str(parsed.lead_id),
            "agent_id": str(parsed.agent_id),
            "note": note,
            # One attempt per proposal: the dial's idempotency key, so a retried confirm
            # answers with the first result rather than ringing twice.
            "attempt": str(uuid4()),
        },
    )


class _CallPlaceSigned(_CallPlaceArgs):
    attempt: UUID


async def _execute_call_place(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`crm.lead_dial.place_lead_call` — the body of `POST /v1/leads/{id}/call`, so the gate
    runs again at the click, the claim is the button's, and the `lead.call_dispatched` row
    is written by the same code."""
    from apps.api.crm.lead_dial import place_lead_call

    parsed = parse_args(_CallPlaceSigned, args)
    result = await place_lead_call(
        session,
        principal=_principal_of(actor),
        lead_id=parsed.lead_id,
        agent_id=parsed.agent_id,
        context_note=parsed.note,
        idempotency_key=f"copilot:{parsed.attempt}",
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
        detail="The call is being placed. It appears in Call logs as it happens.",
        audit_summary={"status": "queued", "agent_id": str(parsed.agent_id)},
    )


CALL_PLACE: Final = ActionTool(
    name="call_place",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="lead",
    # `place_lead_call` writes `lead.call_dispatched` itself; this row records that the
    # person confirmed the assistant's proposal.
    audit_action="lead.call_requested",
    where="in Call logs",
    schema=action_schema(
        "call_place",
        "Propose having one of the account's agents call one lead now. Every calling rule "
        "is checked first (calling hours, do-not-call, verification, credit) and a refusal "
        "comes back with the reason — relay it, do not retry." + PROPOSES_ONLY,
        {
            "lead_id": {"type": "string", "description": "The lead's id, never invented."},
            "agent_id": {
                "type": "string",
                "description": "The agent that makes the call, from `agents_list`.",
            },
            "note": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "A short note for the agent about why it is calling, or null.",
            },
        },
    ),
    plan=_plan_call_place,
    execute=_execute_call_place,
)


class _CallbackBookArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: UUID
    agent_id: UUID
    at: str
    note: Annotated[str, Field(max_length=500)] | None


async def _plan_callback_book(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_CallbackBookArgs, args)
    when = _ist_instant(parsed.at, field="at")
    agent_name, _status = await _agent_name_status(session, parsed.agent_id)
    await crm_service.get_lead(session, parsed.lead_id)
    note = None if parsed.note is None else (strip_invisible(parsed.note.strip()) or None)
    return Plan(
        object_id=str(parsed.lead_id),
        title="Book a call-back",
        summary=(
            f"“{agent_name}” calls this lead back at {_ist_words(when)}. The call is placed "
            "automatically then, inside calling hours and only if every calling rule still "
            "allows it."
        ),
        current=None,
        proposed=_ist_words(when),
        cost=_BILLED_PER_MINUTE,
        reversal="You can cancel or move it from the Call-backs screen until it is placed.",
        args={
            "lead_id": str(parsed.lead_id),
            "agent_id": str(parsed.agent_id),
            "at": when.isoformat(),
            "note": note,
        },
    )


async def _execute_callback_book(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`callbacks.service.book` — the one writer of a call-back, which the voice worker's
    "call me back" tool also uses. The execution id is ours, so a later move finds it."""
    from apps.api.callbacks import service as callbacks_service

    parsed = parse_args(_CallbackBookArgs, args)
    phone, _name = await crm_service.lead_phone(session, parsed.lead_id)
    callback_id = uuid7()
    when = datetime.fromisoformat(parsed.at)
    booked = await callbacks_service.book(
        session,
        callback_id=callback_id,
        tenant_id=actor.tenant_id,
        agent_id=parsed.agent_id,
        source_call_id=None,
        source_execution_id=f"copilot:{callback_id}",
        lead_id=parsed.lead_id,
        phone_e164=phone,
        requested_at=when,
        booked_at=datetime.now(UTC),
        note=parsed.note,
        language=None,
    )
    if booked is None:  # pragma: no cover - a fresh execution id cannot lose the upsert
        raise ProblemError.conflict("callback_not_booked", "That call-back could not be booked.")
    return Executed(
        applied=True,
        detail=f"Call-back booked for {_ist_words(when)}.",
        audit_summary={"callback_id": str(booked[0]), "agent_id": str(parsed.agent_id)},
        object_id=str(booked[0]),
    )


CALLBACK_BOOK: Final = ActionTool(
    name="callback_book",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="callback",
    audit_action="callback.booked",
    where="on the Call-backs screen",
    schema=action_schema(
        "callback_book",
        "Propose booking an automatic call-back to one lead at a time the person gives. "
        "The platform places the call itself at that time." + PROPOSES_ONLY,
        {
            "lead_id": {"type": "string", "description": "The lead's id, never invented."},
            "agent_id": {
                "type": "string",
                "description": "The agent that will call, from `agents_list`.",
            },
            "at": {
                "type": "string",
                "description": "When, in India time, like 2026-10-12T10:30. Ask if not given.",
            },
            "note": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "What the call-back is about, or null.",
            },
        },
    ),
    plan=_plan_callback_book,
    execute=_execute_callback_book,
)


class _CallbackMoveArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    callback_id: UUID
    at: str


async def _waiting_callback(session: AsyncSession, callback_id: UUID) -> dict[str, Any]:
    from apps.api.callbacks import service as callbacks_service

    row = await callbacks_service.get_callback(session, callback_id)
    if row is None:
        raise ProblemError.not_found("Call-back")
    if row["status"] != "scheduled":
        raise WriteRefusedError(
            f"that call-back is {row['status']}, not waiting, so it cannot be changed"
        )
    return row


async def _plan_callback_reschedule(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_CallbackMoveArgs, args)
    when = _ist_instant(parsed.at, field="at")
    row = await _waiting_callback(session, parsed.callback_id)
    current = _ist_words(row["requested_at"])
    return Plan(
        object_id=str(parsed.callback_id),
        title="Move this call-back",
        summary=f"Move the call-back from {current} to {_ist_words(when)}.",
        current=current,
        proposed=_ist_words(when),
        cost=_BILLED_PER_MINUTE,
        reversal="You can move or cancel it again until it is placed.",
        args={"callback_id": str(parsed.callback_id), "at": when.isoformat()},
    )


async def _execute_callback_reschedule(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`callbacks.service.book` on the row's own execution id: its upsert moves a WAITING
    promise and changes nothing that is already being dialled."""
    from apps.api.callbacks import service as callbacks_service

    parsed = parse_args(_CallbackMoveArgs, args)
    row = await _waiting_callback(session, parsed.callback_id)
    origin = (
        await session.execute(
            text(
                "SELECT source_execution_id, source_call_id, language FROM scheduled_callbacks "
                "WHERE id = :id"
            ),
            {"id": parsed.callback_id},
        )
    ).first()
    assert origin is not None  # `_waiting_callback` read the same row
    when = datetime.fromisoformat(parsed.at)
    booked = await callbacks_service.book(
        session,
        callback_id=parsed.callback_id,
        tenant_id=actor.tenant_id,
        agent_id=row["agent_id"],
        source_call_id=origin[1],
        source_execution_id=str(origin[0]),
        lead_id=row["lead_id"],
        phone_e164=row["phone_e164"],
        requested_at=when,
        booked_at=datetime.now(UTC),
        note=row["note"],
        language=origin[2],
    )
    applied = booked is not None
    return Executed(
        applied=applied,
        detail=(
            f"The call-back is now at {_ist_words(when)}."
            if applied
            else "The call-back could not be moved; it may already be under way."
        ),
        audit_summary={"moved": applied},
    )


CALLBACK_RESCHEDULE: Final = ActionTool(
    name="callback_reschedule",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="callback",
    audit_action="callback.rescheduled",
    where="on the Call-backs screen",
    schema=action_schema(
        "callback_reschedule",
        "Propose moving a waiting call-back to another time." + PROPOSES_ONLY,
        {
            "callback_id": {"type": "string", "description": "From `callbacks_list`."},
            "at": {
                "type": "string",
                "description": "The new time in India time, like 2026-10-12T10:30.",
            },
        },
    ),
    plan=_plan_callback_reschedule,
    execute=_execute_callback_reschedule,
)


class _CallbackCancelArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    callback_id: UUID


async def _plan_callback_cancel(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_CallbackCancelArgs, args)
    row = await _waiting_callback(session, parsed.callback_id)
    when = _ist_words(row["requested_at"])
    return Plan(
        object_id=str(parsed.callback_id),
        title="Cancel this call-back",
        summary=f"Cancel the call-back due {when}. The caller will not be called.",
        current=f"Due {when}",
        proposed="Cancelled",
        cost=None,
        reversal="A cancelled call-back cannot be restored; book a new one instead.",
        args={"callback_id": str(parsed.callback_id)},
    )


async def _execute_callback_cancel(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`callbacks.service.cancel_one` with the reason `DELETE /v1/callbacks/{id}` gives."""
    from apps.api.callbacks import service as callbacks_service

    del actor
    parsed = parse_args(_CallbackCancelArgs, args)
    stopped = await callbacks_service.cancel_one(
        session, parsed.callback_id, reason="You called this off."
    )
    if not stopped:
        raise ProblemError.conflict(
            "callback_not_stoppable",
            "That call-back is no longer waiting, so it was not cancelled.",
        )
    return Executed(applied=True, detail="The call-back is cancelled.", audit_summary={})


CALLBACK_CANCEL: Final = ActionTool(
    name="callback_cancel",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="callback",
    audit_action="callback.cancelled",
    where="on the Call-backs screen",
    schema=action_schema(
        "callback_cancel",
        "Propose cancelling a waiting call-back so the caller is not called." + PROPOSES_ONLY,
        {"callback_id": {"type": "string", "description": "From `callbacks_list`."}},
    ),
    plan=_plan_callback_cancel,
    execute=_execute_callback_cancel,
)


# =========================================================================================
# CAMPAIGNS
# =========================================================================================

CampaignClassification = Literal["service", "transactional", "promotional"]

_CLASSIFICATION_WORDS: Final[dict[str, str]] = {
    "service": "service calls to existing customers",
    "transactional": "transactional calls",
    "promotional": "promotional calls",
}


async def _refuse_a_taken_campaign_name(session: AsyncSession, name: str) -> None:
    taken = (
        await session.execute(
            text(
                "SELECT count(*) FROM campaigns WHERE lower(name) = lower(:n) "
                "AND status <> 'cancelled'"
            ),
            {"n": name},
        )
    ).scalar()
    if taken:
        raise WriteRefusedError(
            "this account already has a campaign with that name, so ask the person for a "
            "different one rather than making a second"
        )


class _CampaignCreateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    agent_id: UUID
    classification: CampaignClassification


async def _plan_campaign_create(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_CampaignCreateArgs, args)
    name = _clean_name(parsed.name, what="campaign")
    agent_name, _status = await _agent_name_status(session, parsed.agent_id)
    await _refuse_a_taken_campaign_name(session, name)
    return Plan(
        object_id="",
        title="Create a draft campaign",
        summary=(
            f"Create a draft campaign “{name}” for {_CLASSIFICATION_WORDS[parsed.classification]}, "
            f"made by “{agent_name}”. A draft calls nobody: it needs contacts and a launch."
        ),
        current=None,
        proposed=f"{name} — draft",
        cost=None,
        reversal="Undo removes the draft while it is still empty.",
        args={
            "name": name,
            "agent_id": str(parsed.agent_id),
            "classification": parsed.classification,
        },
    )


async def _execute_campaign_create(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`campaigns_service.create_campaign` — `POST /v1/campaigns`'s call, with the create
    form's own defaults (three calls at a time, the platform's calling window, no number
    or template chosen yet)."""
    parsed = parse_args(_CampaignCreateArgs, args)
    campaign_id = await campaigns_service.create_campaign(
        session,
        tenant_id=actor.tenant_id,
        agent_id=parsed.agent_id,
        name=parsed.name,
        classification=parsed.classification,
        number_id=None,
        dlt_template_id=None,
        concurrency=3,
    )
    return Executed(
        applied=True,
        detail=f"“{parsed.name}” exists as a draft. Add contacts to it, then launch it.",
        audit_summary={"campaign_id": str(campaign_id), "classification": parsed.classification},
        object_id=str(campaign_id),
    )


async def _capture_campaign(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    """Before a create there is no row; after it, the name and status the inverse needs."""
    del actor
    raw = args.get("campaign_id_created") or args.get("campaign_id")
    if not isinstance(raw, str):
        return {"exists": False}
    row = (
        await session.execute(
            text("SELECT name, status FROM campaigns WHERE id = :cid"), {"cid": UUID(raw)}
        )
    ).first()
    if row is None:
        return {"exists": False}
    return {"exists": True, "name": str(row[0]), "status": str(row[1])}


async def _invert_campaign_create(
    session: AsyncSession, actor: ToolActor, record: UndoRecord
) -> str:
    """Cancel the draft — `set_campaign_status` from `draft`, the primitive the pause and
    resume buttons use — only while it is the untouched, empty draft the assistant made."""
    del actor
    campaign_id = UUID(record.object_id)
    row = (
        await session.execute(
            text("SELECT name, status FROM campaigns WHERE id = :cid FOR UPDATE"),
            {"cid": campaign_id},
        )
    ).first()
    if row is None or str(row[1]) == "cancelled":
        raise UndoRefusedError("that campaign has already been removed")
    contacts = (
        await session.execute(
            text("SELECT count(*) FROM campaign_contacts WHERE campaign_id = :cid"),
            {"cid": campaign_id},
        )
    ).scalar()
    if str(row[1]) != "draft" or str(row[0]) != record.result_state.get("name") or contacts:
        raise UndoRefusedError(
            "that campaign has been changed or given contacts since it was created, so it was kept"
        )
    await campaigns_service.set_campaign_status(
        session, campaign_id=campaign_id, to_status="cancelled", from_statuses=("draft",)
    )
    return "The draft campaign has been removed."


# `run_immediate` asks the capture about the object a create PRODUCED under
# `<object_type>_id`, which for a clone collides with the SOURCE campaign's own argument.
# The clone therefore names its source `source_campaign_id`, and the create path reads the
# produced id from `campaign_id`.
async def _capture_campaign_created(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    return await _capture_campaign(session, actor, {"campaign_id": args.get("campaign_id")})


CAMPAIGN_CREATE: Final = ActionTool(
    name="campaign_create",
    tier="immediate",
    undo=Undo(capture=_capture_campaign_created, invert=_invert_campaign_create),
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.created",
    where="on the Campaigns screen",
    schema=action_schema(
        "campaign_create",
        "Create a new outbound campaign as a DRAFT. A draft calls nobody until it has "
        "contacts and somebody launches it. Ask for a missing name, agent or kind of calls "
        "in one short question first." + DOES_IT,
        {
            "name": {"type": "string", "description": "What to call the campaign."},
            "agent_id": {"type": "string", "description": "The agent that makes the calls."},
            "classification": {
                "type": "string",
                "enum": list(_CLASSIFICATION_WORDS),
                "description": (
                    "`service` for calls to existing customers about their own business, "
                    "`transactional` for confirmations and reminders, `promotional` for offers."
                ),
            },
        },
    ),
    plan=_plan_campaign_create,
    execute=_execute_campaign_create,
)


class _CampaignCloneArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_campaign_id: UUID
    name: str | None


async def _plan_campaign_clone(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_CampaignCloneArgs, args)
    source_name, _status = await _campaign_name_status(session, parsed.source_campaign_id)
    name = _clean_name(parsed.name or f"Copy of {source_name}"[:_MAX_NAME], what="campaign")
    await _refuse_a_taken_campaign_name(session, name)
    return Plan(
        object_id="",
        title="Copy this campaign",
        summary=(
            f"Create a draft “{name}” with the same agent, kind of calls, number, template, "
            f"calling hours and pace as “{source_name}”. Its contacts are NOT copied."
        ),
        current=None,
        proposed=f"{name} — draft",
        cost=None,
        reversal="Undo removes the copy while it is still empty.",
        args={"source_campaign_id": str(parsed.source_campaign_id), "name": name},
    )


async def _execute_campaign_clone(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`create_campaign` again, fed the source's settings. The consent declaration is NOT
    copied: it is a statement about a LIST, and the copy has none yet."""
    parsed = parse_args(_CampaignCloneArgs, args)
    row = (
        await session.execute(
            text(
                "SELECT agent_id, classification, number_id, dlt_template_id, concurrency, "
                "calling_hours FROM campaigns WHERE id = :cid"
            ),
            {"cid": parsed.source_campaign_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    assert parsed.name is not None  # the planner always names it
    campaign_id = await campaigns_service.create_campaign(
        session,
        tenant_id=actor.tenant_id,
        agent_id=UUID(str(row[0])),
        name=parsed.name,
        classification=str(row[1]),
        number_id=None if row[2] is None else UUID(str(row[2])),
        dlt_template_id=None if row[3] is None else UUID(str(row[3])),
        concurrency=int(row[4]),
        calling_hours=row[5] if isinstance(row[5], dict) else None,
    )
    return Executed(
        applied=True,
        detail=f"“{parsed.name}” is a draft copy. Add contacts to it, then launch it.",
        audit_summary={
            "campaign_id": str(campaign_id),
            "source_campaign_id": str(parsed.source_campaign_id),
        },
        object_id=str(campaign_id),
    )


CAMPAIGN_CLONE: Final = ActionTool(
    name="campaign_clone",
    tier="immediate",
    undo=Undo(capture=_capture_campaign_created, invert=_invert_campaign_create),
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.created",
    where="on the Campaigns screen",
    schema=action_schema(
        "campaign_clone",
        "Copy an existing campaign's settings into a new DRAFT, without its contacts." + DOES_IT,
        {
            "source_campaign_id": {
                "type": "string",
                "description": "The campaign to copy, from `campaigns_list` or the SCREEN STATE.",
            },
            "name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "A name for the copy, or null for 'Copy of …'.",
            },
        },
    ),
    plan=_plan_campaign_clone,
    execute=_execute_campaign_clone,
)


class _CampaignLeadsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    lead_ids: Annotated[list[UUID], Field(min_length=1, max_length=MAX_LEADS_PER_ACTION)]


async def _plan_campaign_add_leads(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_CampaignLeadsArgs, args)
    name, status = await _campaign_name_status(session, parsed.campaign_id)
    if status not in ("draft", "scheduled"):
        raise WriteRefusedError(
            f"“{name}” is {status}; contacts can only be added before it starts"
        )
    unique = list(dict.fromkeys(parsed.lead_ids))
    found = (
        await session.execute(
            text("SELECT count(*) FROM leads WHERE id = ANY(:ids) AND deleted_at IS NULL"),
            {"ids": unique},
        )
    ).scalar()
    if not found:
        raise ProblemError.not_found("Lead")
    return Plan(
        object_id=str(parsed.campaign_id),
        title="Add leads to this campaign",
        summary=(
            f"Add {found} lead(s) to “{name}”. They are called when the campaign runs; "
            "numbers on your do-not-call list are removed before the first dial."
        ),
        current=status,
        proposed=f"{found} more contact(s)",
        cost=_BILLED_PER_MINUTE,
        reversal="Contacts cannot be taken off a campaign from here once added.",
        args={"campaign_id": str(parsed.campaign_id), "lead_ids": [str(i) for i in unique]},
    )


async def _execute_campaign_add_leads(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`campaigns_service.add_contacts` — `POST /v1/campaigns/{id}/contacts`'s call — fed
    from the leads' own records, so no number passes through the model."""
    parsed = parse_args(_CampaignLeadsArgs, args)
    contacts = []
    for lead_id in parsed.lead_ids:
        try:
            phone, name = await crm_service.lead_phone(session, lead_id)
        except ProblemError:
            continue
        contacts.append({"phone": phone, "name": name})
    result = await campaigns_service.add_contacts(
        session, tenant_id=actor.tenant_id, campaign_id=parsed.campaign_id, contacts=contacts
    )
    return Executed(
        applied=result["added"] > 0,
        detail=(
            f"{result['added']} contact(s) added"
            + (f", {result['duplicate']} were already on it" if result.get("duplicate") else "")
            + "."
        ),
        audit_summary={key: int(value) for key, value in result.items()},
    )


CAMPAIGN_ADD_LEADS: Final = ActionTool(
    name="campaign_add_leads",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.contacts_added",
    where="on the campaign's own screen",
    schema=action_schema(
        "campaign_add_leads",
        f"Propose adding up to {MAX_LEADS_PER_ACTION} of this account's leads to a draft "
        "or scheduled campaign's call list. A CSV list is uploaded on the campaign screen "
        "instead." + PROPOSES_ONLY,
        {
            "campaign_id": {"type": "string", "description": "The campaign's id."},
            "lead_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The leads' ids, from the SCREEN STATE selection or a lookup.",
            },
        },
    ),
    plan=_plan_campaign_add_leads,
    execute=_execute_campaign_add_leads,
)


class _CampaignScheduleArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    start_at: str


async def _plan_campaign_schedule(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    parsed = parse_args(_CampaignScheduleArgs, args)
    when = _ist_instant(parsed.start_at, field="start_at")
    name, status = await _campaign_name_status(session, parsed.campaign_id)
    if status not in ("draft", "scheduled"):
        raise WriteRefusedError(f"“{name}” is {status}, so it cannot be scheduled")
    blockers = await campaigns_service.launch_blockers(
        session, tenant_id=actor.tenant_id, campaign_id=parsed.campaign_id
    )
    warning = (
        " Right now it could not start: "
        + "; ".join(blocker.reason for blocker in blockers)
        + ". If that is still true at the start time, it does not start."
        if blockers
        else ""
    )
    return Plan(
        object_id=str(parsed.campaign_id),
        title="Schedule this campaign",
        summary=(
            f"Start dialling “{name}” at {_ist_words(when)}, inside its calling hours. Every "
            f"launch check runs again at that time.{warning}"
        ),
        current=status,
        proposed=f"Starts {_ist_words(when)}",
        cost=_BILLED_PER_MINUTE,
        reversal=(
            "You can cancel the schedule before it starts. Calls already placed cannot be recalled."
        ),
        args={"campaign_id": str(parsed.campaign_id), "start_at": when.isoformat()},
    )


async def _execute_campaign_schedule(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`scheduling.schedule_campaign` — `POST /v1/campaigns/{id}/schedule`'s call."""
    from apps.api.campaigns import scheduling

    parsed = parse_args(_CampaignScheduleArgs, args)
    result = await scheduling.schedule_campaign(
        session,
        tenant_id=actor.tenant_id,
        campaign_id=parsed.campaign_id,
        start_at=datetime.fromisoformat(parsed.start_at),
    )
    return Executed(
        applied=True,
        detail=(
            f"Scheduled. The first call goes out no earlier than "
            f"{_ist_words(result.first_dial_not_before)}."
        ),
        audit_summary={"start_at": result.start_at.isoformat()},
    )


CAMPAIGN_SCHEDULE: Final = ActionTool(
    name="campaign_schedule",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.scheduled",
    where="on the campaign's own screen",
    schema=action_schema(
        "campaign_schedule",
        "Propose starting a draft campaign automatically at a later time. Every launch "
        "check runs again at that time." + PROPOSES_ONLY,
        {
            "campaign_id": {"type": "string", "description": "The campaign's id."},
            "start_at": {
                "type": "string",
                "description": "When to start, in India time, like 2026-10-12T10:30.",
            },
        },
    ),
    plan=_plan_campaign_schedule,
    execute=_execute_campaign_schedule,
)


class _CampaignIdArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID


async def _plan_campaign_unschedule(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_CampaignIdArgs, args)
    name, status = await _campaign_name_status(session, parsed.campaign_id)
    if status != "scheduled":
        raise WriteRefusedError(f"“{name}” is {status}, so it has no start to cancel")
    return Plan(
        object_id=str(parsed.campaign_id),
        title="Cancel this campaign's scheduled start",
        summary=f"“{name}” will not start on its own; it goes back to being a draft.",
        current="scheduled",
        proposed="draft",
        cost=None,
        reversal="You can schedule or launch it again later.",
        args={"campaign_id": str(parsed.campaign_id)},
    )


async def _execute_campaign_unschedule(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`scheduling.unschedule_campaign` — `DELETE /v1/campaigns/{id}/schedule`'s call."""
    from apps.api.campaigns import scheduling

    parsed = parse_args(_CampaignIdArgs, args)
    result = await scheduling.unschedule_campaign(
        session, tenant_id=actor.tenant_id, campaign_id=parsed.campaign_id
    )
    return Executed(
        applied=True,
        detail=f"The scheduled start is cancelled; the campaign is {result.status}.",
        audit_summary={"kind": result.kind},
    )


CAMPAIGN_UNSCHEDULE: Final = ActionTool(
    name="campaign_unschedule",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.schedule_cancelled",
    where="on the campaign's own screen",
    schema=action_schema(
        "campaign_unschedule",
        "Propose cancelling a campaign's scheduled start, so it stays a draft." + PROPOSES_ONLY,
        {"campaign_id": {"type": "string", "description": "The campaign's id."}},
    ),
    plan=_plan_campaign_unschedule,
    execute=_execute_campaign_unschedule,
)


async def _plan_campaign_resume(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_CampaignIdArgs, args)
    name, status = await _campaign_name_status(session, parsed.campaign_id)
    if status != "paused":
        raise WriteRefusedError(f"“{name}” is {status}, not paused, so there is nothing to resume")
    pending = (
        await session.execute(
            text(
                "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :cid "
                "AND status = 'pending'"
            ),
            {"cid": parsed.campaign_id},
        )
    ).scalar()
    return Plan(
        object_id=str(parsed.campaign_id),
        title="Resume calling on this campaign",
        summary=(
            f"Start dialling “{name}” again; {int(pending or 0)} contact(s) are still waiting. "
            "Every call is still checked against do-not-call, calling hours and credit."
        ),
        current="paused",
        proposed="running",
        cost=_BILLED_PER_MINUTE,
        reversal="You can pause it again. Calls already placed cannot be recalled.",
        args={"campaign_id": str(parsed.campaign_id)},
    )


async def _execute_campaign_resume(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`POST /v1/campaigns/{id}/resume`'s two calls: the archived-agent refusal, then the CAS
    from `paused`."""
    del actor
    parsed = parse_args(_CampaignIdArgs, args)
    await campaigns_service.assert_agent_still_assignable(session, campaign_id=parsed.campaign_id)
    moved = await campaigns_service.set_campaign_status(
        session, campaign_id=parsed.campaign_id, to_status="running", from_statuses=("paused",)
    )
    return Executed(
        applied=moved,
        detail="Dialling has resumed." if moved else "It was already running.",
        audit_summary={"moved": moved},
    )


CAMPAIGN_RESUME: Final = ActionTool(
    name="campaign_resume",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.resumed",
    where="on the campaign's own screen",
    schema=action_schema(
        "campaign_resume",
        "Propose resuming a paused campaign, so it starts dialling again." + PROPOSES_ONLY,
        {"campaign_id": {"type": "string", "description": "The campaign's id."}},
    ),
    plan=_plan_campaign_resume,
    execute=_execute_campaign_resume,
)


# =========================================================================================
# AGENTS
# =========================================================================================


class _AgentEditArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    language_primary: OfferedLanguage | None
    voice_id: Annotated[str, Field(max_length=200)] | None
    ai_disclosure_enabled: bool | None
    recording_notice_enabled: bool | None


_AGENT_EDIT_COLUMNS: Final = (
    "status, language_primary, tts_voice, ai_disclosure_enabled, recording_notice_enabled"
)


async def _agent_settings(session: AsyncSession, agent_id: UUID) -> dict[str, Any]:
    await assert_visible(session, "agent", agent_id)
    row = (
        await session.execute(
            text(
                f"SELECT {_AGENT_EDIT_COLUMNS} FROM agents WHERE id = :aid AND deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:  # pragma: no cover - `assert_visible` has already 404'd an absent row
        raise ProblemError.not_found("Agent")
    return {
        "status": str(row[0]),
        "language_primary": str(row[1]),
        "voice_id": None if row[2] is None else str(row[2]),
        "ai_disclosure_enabled": bool(row[3]),
        "recording_notice_enabled": bool(row[4]),
    }


def _on_off(value: bool) -> str:
    return "on" if value else "off"


def _describe_edit(parsed: _AgentEditArgs, current: dict[str, Any]) -> tuple[list[str], list[str]]:
    """What changes, as `(was, becomes)` phrases — only for the fields the request names."""
    was: list[str] = []
    becomes: list[str] = []
    if parsed.language_primary is not None:
        was.append(
            "speaks "
            + LANGUAGE_LABELS.get(current["language_primary"], current["language_primary"])
        )
        becomes.append(f"speaks {LANGUAGE_LABELS[parsed.language_primary]}")
    if parsed.voice_id is not None:
        was.append(f"voice {current['voice_id'] or 'the default'}")
        becomes.append(f"voice {strip_invisible(parsed.voice_id)}")
    if parsed.ai_disclosure_enabled is not None:
        was.append(f"AI disclosure {_on_off(current['ai_disclosure_enabled'])}")
        becomes.append(f"AI disclosure {_on_off(parsed.ai_disclosure_enabled)}")
    if parsed.recording_notice_enabled is not None:
        was.append(f"recording notice {_on_off(current['recording_notice_enabled'])}")
        becomes.append(f"recording notice {_on_off(parsed.recording_notice_enabled)}")
    return was, becomes


_TRUTHFUL_ANYWAY: Final = (
    " Whatever the notices say, the agent always answers truthfully when asked whether it is "
    "an AI or whether the call is recorded."
)


async def _plan_agent_edit_common(
    session: AsyncSession, args: Mapping[str, Any], *, live: bool
) -> tuple[_AgentEditArgs, Plan]:
    parsed = parse_args(_AgentEditArgs, args)
    current = await _agent_settings(session, parsed.agent_id)
    name, _status = await _agent_name_status(session, parsed.agent_id)
    was, becomes = _describe_edit(parsed, current)
    if not becomes:
        raise WriteRefusedError("name at least one thing to change on the agent")
    if live and current["status"] != "live":
        raise WriteRefusedError(
            "that agent is not live, so use `agent_edit`, which applies at once with an Undo"
        )
    if not live and current["status"] == "live":
        raise WriteRefusedError(
            "that agent is live, so this change would reach callers at once — use "
            "`agent_edit_live`, which the person confirms first"
        )
    notices = (
        parsed.ai_disclosure_enabled is not None or parsed.recording_notice_enabled is not None
    )
    plan = Plan(
        object_id=str(parsed.agent_id),
        title="Change this agent" if not live else "Change this live agent",
        summary=(
            f"On “{name}”: "
            + "; ".join(becomes)
            + "."
            + (
                " Callers hear it from their next call."
                if live
                else " It is not live, so no caller hears it yet."
            )
            + (_TRUTHFUL_ANYWAY if notices else "")
        ),
        current="; ".join(was),
        proposed="; ".join(becomes),
        cost=None,
        reversal=(
            "Change it back the same way. Calls already taken are not affected."
            if live
            else "Undo puts every one of these back."
        ),
        args={
            "agent_id": str(parsed.agent_id),
            "language_primary": parsed.language_primary,
            "voice_id": None
            if parsed.voice_id is None
            else strip_invisible(parsed.voice_id.strip()),
            "ai_disclosure_enabled": parsed.ai_disclosure_enabled,
            "recording_notice_enabled": parsed.recording_notice_enabled,
        },
    )
    return parsed, plan


async def _apply_agent_settings(
    session: AsyncSession,
    actor: ToolActor,
    *,
    agent_id: UUID,
    language_primary: str | None,
    voice_id: str | None,
    ai_disclosure_enabled: bool | None,
    recording_notice_enabled: bool | None,
) -> None:
    """The three console buttons, in the order their transactions allow (module docstring):
    `set_agent_voice` and `set_disclosure_posture` own their sessions and go first, then
    `lifecycle.update_agent` in this one. Each re-publishes a live agent itself."""
    from apps.api.agents.publishing import set_agent_voice, set_disclosure_posture

    if voice_id is not None:
        await set_agent_voice(
            tenant_id=actor.tenant_id, agent_id=agent_id, voice_id=voice_id, audience="client"
        )
    if ai_disclosure_enabled is not None or recording_notice_enabled is not None:
        await set_disclosure_posture(
            tenant_id=actor.tenant_id,
            agent_id=agent_id,
            ai_disclosure_enabled=ai_disclosure_enabled,
            recording_notice_enabled=recording_notice_enabled,
        )
    if language_primary is not None:
        await lifecycle.update_agent(
            session, tenant_id=actor.tenant_id, agent_id=agent_id, language_primary=language_primary
        )


async def _execute_agent_edit(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_AgentEditArgs, args)
    before = await _agent_settings(session, parsed.agent_id)
    await _apply_agent_settings(
        session,
        actor,
        agent_id=parsed.agent_id,
        language_primary=parsed.language_primary,
        voice_id=parsed.voice_id,
        ai_disclosure_enabled=parsed.ai_disclosure_enabled,
        recording_notice_enabled=parsed.recording_notice_enabled,
    )
    after = await _agent_settings(session, parsed.agent_id)
    changed = sorted(key for key in before if key != "status" and before[key] != after[key])
    return Executed(
        applied=bool(changed),
        detail=(
            "The agent is updated: " + ", ".join(key.replace("_", " ") for key in changed) + "."
            if changed
            else "The agent already had those settings, so nothing changed."
        ),
        audit_summary={"agent_id": str(parsed.agent_id), "fields": changed},
    )


async def _plan_agent_edit(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    _parsed, plan = await _plan_agent_edit_common(session, args, live=False)
    return plan


async def _plan_agent_edit_live(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    _parsed, plan = await _plan_agent_edit_common(session, args, live=True)
    return plan


async def _capture_agent_edit(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    del actor
    return await _agent_settings(session, parse_args(_AgentEditArgs, args).agent_id)


async def _invert_agent_edit(session: AsyncSession, actor: ToolActor, record: UndoRecord) -> str:
    """Put back the fields the edit changed, through the same three buttons — only while the
    agent still holds what the edit left and is still not live. Compared WITHOUT a row lock,
    because two of the three services lock the row in their own transaction."""
    agent_id = UUID(str(record.args["agent_id"]))
    now = await _agent_settings(session, agent_id)
    if now["status"] == "live":
        raise UndoRefusedError(
            "that agent has gone live since, so changing it back would reach callers — change "
            "it on the Agents screen instead"
        )
    if any(now[key] != record.result_state.get(key) for key in now if key != "status"):
        raise UndoRefusedError("that agent has been changed again since, so it was left alone")
    prior = record.prior_state
    changed = {key for key in now if key != "status" and prior.get(key) != now[key]}
    if "voice_id" in changed and prior.get("voice_id") is None:
        raise UndoRefusedError(
            "the agent had no voice chosen before, so there is no voice to put back — pick one "
            "on the Agents screen"
        )
    await _apply_agent_settings(
        session,
        actor,
        agent_id=agent_id,
        language_primary=prior["language_primary"] if "language_primary" in changed else None,
        voice_id=prior["voice_id"] if "voice_id" in changed else None,
        ai_disclosure_enabled=(
            prior["ai_disclosure_enabled"] if "ai_disclosure_enabled" in changed else None
        ),
        recording_notice_enabled=(
            prior["recording_notice_enabled"] if "recording_notice_enabled" in changed else None
        ),
    )
    return "The agent's settings are back as they were."


_AGENT_EDIT_PROPERTIES: Final[dict[str, Any]] = {
    "agent_id": {"type": "string", "description": "The agent's id, never invented."},
    "language_primary": {
        "anyOf": [{"type": "string", "enum": list(PRODUCT_LANGUAGES)}, {"type": "null"}],
        "description": "The language it should mainly speak, or null to leave it.",
    },
    "voice_id": {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "description": "A voice id from `voices_offered`, or null to leave it.",
    },
    "ai_disclosure_enabled": {
        "anyOf": [{"type": "boolean"}, {"type": "null"}],
        "description": "Say it is an AI at the start of each call, or null to leave it.",
    },
    "recording_notice_enabled": {
        "anyOf": [{"type": "boolean"}, {"type": "null"}],
        "description": "Say the call is recorded at the start, or null to leave it.",
    },
}

AGENT_EDIT: Final = ActionTool(
    name="agent_edit",
    tier="immediate",
    undo=Undo(capture=_capture_agent_edit, invert=_invert_agent_edit),
    permission="org:manage",
    object_type="agent",
    audit_action="agent.updated",
    where="under Agents in your dashboard",
    schema=action_schema(
        "agent_edit",
        "Change a DRAFT or PAUSED agent's language, voice, or opening notices (saying it is "
        "an AI, saying the call is recorded). The notices never change the agent's opening "
        "line, which is part of its script; a notice switched on is said before it. For a "
        "LIVE agent use `agent_edit_live`." + DOES_IT,
        _AGENT_EDIT_PROPERTIES,
    ),
    plan=_plan_agent_edit,
    execute=_execute_agent_edit,
)

AGENT_EDIT_LIVE: Final = ActionTool(
    name="agent_edit_live",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="agent",
    audit_action="agent.updated",
    where="under Agents in your dashboard",
    schema=action_schema(
        "agent_edit_live",
        "Propose changing a LIVE agent's language, voice, or opening notices. Callers hear "
        "the change from their next call." + PROPOSES_ONLY,
        _AGENT_EDIT_PROPERTIES,
    ),
    plan=_plan_agent_edit_live,
    execute=_execute_agent_edit,
)


class _CaptureField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    type: Literal["text", "number", "bool", "enum", "date"]
    enum_values: list[str] | None
    reason: str
    required: bool


class _CaptureFieldsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    fields: Annotated[list[_CaptureField], Field(max_length=40)]


async def _current_fields(session: AsyncSession, agent_id: UUID) -> list[dict[str, Any]]:
    await assert_visible(session, "agent", agent_id)
    row = (
        await session.execute(
            text(
                "SELECT s.fields FROM agents a LEFT JOIN extraction_schemas s "
                "ON s.id = a.extraction_schema_id WHERE a.id = :aid"
            ),
            {"aid": agent_id},
        )
    ).first()
    return list(row[0] or []) if row is not None else []


def _extraction_fields(raw: list[Any]) -> list[Any]:
    """Through `ExtractionField` itself, so its validators run exactly as on the form."""
    from calevate_shared.extraction import ExtractionField
    from pydantic import ValidationError

    try:
        return [ExtractionField.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise WriteRefusedError(
            "one of the fields is not valid: keys are lower-case letters, digits and "
            "underscores, and an `enum` field needs its choices"
        ) from exc


async def _plan_capture_fields(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    from apps.api.agents.extraction_routes import validate_fields

    parsed = parse_args(_CaptureFieldsArgs, args)
    fields = _extraction_fields([field.model_dump() for field in parsed.fields])
    validate_fields(fields)
    name, _status = await _agent_name_status(session, parsed.agent_id)
    current = await _current_fields(session, parsed.agent_id)
    proposed = ", ".join(field.label for field in fields) or "nothing"
    return Plan(
        object_id=str(parsed.agent_id),
        title="Change what this agent captures",
        summary=f"“{name}” will capture: {proposed}. It applies from the next call.",
        current=", ".join(str(item.get("label", item.get("key"))) for item in current) or "nothing",
        proposed=proposed,
        cost=None,
        reversal="Undo puts the previous list back. Calls already taken keep what they captured.",
        args={
            "agent_id": str(parsed.agent_id),
            "fields": [field.model_dump(mode="json") for field in fields],
        },
    )


async def _execute_capture_fields(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`validate_fields` then `write_schema` — `PUT /v1/agents/{id}/extraction-schema`'s two
    steps, unchanged."""
    del actor
    from apps.api.agents.extraction_routes import validate_fields, write_schema

    agent_id = UUID(str(args["agent_id"]))
    fields = _extraction_fields(list(args["fields"]))
    validate_fields(fields)
    result = await write_schema(session, agent_id=agent_id, fields=fields)
    return Executed(
        applied=bool(result.changed),
        detail=(
            f"The agent now captures {len(result.fields)} field(s)."
            if result.changed
            else "The agent already captured exactly those fields."
        ),
        audit_summary={
            "agent_id": str(agent_id),
            "fields": len(result.fields),
            "changed": result.changed,
        },
    )


async def _capture_capture_fields(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    """The field DEFINITIONS (keys, labels, types) — the business's own configuration, never
    a value any caller gave."""
    del actor
    return {"fields": await _current_fields(session, UUID(str(args["agent_id"])))}


async def _invert_capture_fields(
    session: AsyncSession, actor: ToolActor, record: UndoRecord
) -> str:
    del actor
    from apps.api.agents.extraction_routes import write_schema

    agent_id = UUID(str(record.args["agent_id"]))
    await session.execute(
        text("SELECT 1 FROM agents WHERE id = :aid FOR UPDATE"), {"aid": agent_id}
    )
    if await _current_fields(session, agent_id) != list(record.result_state.get("fields", [])):
        raise UndoRefusedError(
            "those fields have been changed again since, so they were left alone"
        )
    await write_schema(
        session, agent_id=agent_id, fields=_extraction_fields(list(record.prior_state["fields"]))
    )
    return "The agent captures the fields it captured before."


AGENT_CAPTURE_FIELDS_SET: Final = ActionTool(
    name="agent_capture_fields_set",
    tier="immediate",
    undo=Undo(capture=_capture_capture_fields, invert=_invert_capture_fields),
    permission="org:manage",
    object_type="agent",
    audit_action="agent.extraction_schema_set",
    where="on the agent's Fields tab",
    schema=action_schema(
        "agent_capture_fields_set",
        "Set the WHOLE list of things an agent writes down from each call (for example "
        "budget, preferred date). Send every field to keep, not only the new one — read the "
        "current list with `agent_detail` first." + DOES_IT,
        {
            "agent_id": {"type": "string", "description": "The agent's id, never invented."},
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "lower_snake_case, e.g. budget"},
                        "label": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["text", "number", "bool", "enum", "date"],
                        },
                        "enum_values": {
                            "anyOf": [
                                {"type": "array", "items": {"type": "string"}},
                                {"type": "null"},
                            ]
                        },
                        "reason": {"type": "string", "description": "Why the business needs it."},
                        "required": {"type": "boolean"},
                    },
                    "required": ["key", "label", "type", "enum_values", "reason", "required"],
                    "additionalProperties": False,
                },
            },
        },
    ),
    plan=_plan_capture_fields,
    execute=_execute_capture_fields,
)


class _AgentIdArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID


async def _plan_agent_changes_apply(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_AgentIdArgs, args)
    name, status = await _agent_name_status(session, parsed.agent_id)
    row = (
        await session.execute(
            text(
                "SELECT d.version, l.version FROM agents a "
                "LEFT JOIN prompt_versions d ON d.id = a.system_prompt_id "
                "LEFT JOIN prompt_versions l ON l.id = a.live_prompt_id WHERE a.id = :aid"
            ),
            {"aid": parsed.agent_id},
        )
    ).first()
    if status != "live" or row is None or row[0] is None or row[0] == row[1]:
        raise WriteRefusedError(
            "that agent has no saved script change waiting to go live, so there is nothing to apply"
        )
    return Plan(
        object_id=str(parsed.agent_id),
        title="Put the saved script live",
        summary=(
            f"“{name}” starts using script version {row[0]} (callers hear version {row[1]} now). "
            "The platform is checked to hold the new script before anything changes."
        ),
        current=f"version {row[1]}",
        proposed=f"version {row[0]}",
        cost=None,
        reversal=(
            "Calls taken on the new script cannot be undone; save and apply another "
            "version to change it."
        ),
        args={"agent_id": str(parsed.agent_id), "expected_version": int(row[0])},
    )


class _AgentApplySigned(_AgentIdArgs):
    expected_version: int


async def _execute_agent_changes_apply(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`publishing.apply_to_live` — `POST /v1/agents/{id}/script/apply`'s call, with the
    version the card showed as its CAS."""
    from apps.api.agents.publishing import apply_to_live

    del session
    parsed = parse_args(_AgentApplySigned, args)
    result = await apply_to_live(
        tenant_id=actor.tenant_id,
        agent_id=parsed.agent_id,
        expected_version=parsed.expected_version,
    )
    return Executed(
        applied=result.applied,
        detail=(
            f"Script version {result.live_version} is live."
            if result.applied
            else "Nothing was waiting to go live."
        ),
        audit_summary={"live_version": result.live_version, "engine_synced": result.engine_synced},
    )


AGENT_CHANGES_APPLY: Final = ActionTool(
    name="agent_changes_apply",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="agent",
    audit_action="agent.changes_applied",
    where="on the agent's Script tab",
    schema=action_schema(
        "agent_changes_apply",
        "Propose putting a live agent's saved-but-not-live script change in front of "
        "callers. `agent_detail` says whether one is waiting." + PROPOSES_ONLY,
        {"agent_id": {"type": "string", "description": "The agent's id, never invented."}},
    ),
    plan=_plan_agent_changes_apply,
    execute=_execute_agent_changes_apply,
)


async def _plan_agent_deactivate(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_AgentIdArgs, args)
    name, status = await _agent_name_status(session, parsed.agent_id)
    if status != "live":
        raise WriteRefusedError(f"“{name}” is {status}, not live, so it is already off the phone")
    return Plan(
        object_id=str(parsed.agent_id),
        title="Take this agent off the phone",
        summary=(
            f"Pause “{name}”: it stops answering its numbers and stops placing calls. Callers "
            "to its numbers will not reach it until it is published again."
        ),
        current="live",
        proposed="paused",
        cost=None,
        reversal="You can publish it again from the Agents screen.",
        args={"agent_id": str(parsed.agent_id)},
    )


async def _execute_agent_deactivate(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`lifecycle.deactivate_agent` — `POST /v1/agents/{id}/deactivate`'s call."""
    parsed = parse_args(_AgentIdArgs, args)
    result = await lifecycle.deactivate_agent(
        session, tenant_id=actor.tenant_id, agent_id=parsed.agent_id
    )
    return Executed(
        applied=result.changed,
        detail="The agent is paused." if result.changed else "It was already paused.",
        audit_summary={"agent_id": str(parsed.agent_id), "status": result.status},
    )


AGENT_DEACTIVATE: Final = ActionTool(
    name="agent_deactivate",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="agent",
    audit_action="agent.deactivated",
    where="under Agents in your dashboard",
    schema=action_schema(
        "agent_deactivate",
        "Propose pausing a live agent so it stops answering and placing calls." + PROPOSES_ONLY,
        {"agent_id": {"type": "string", "description": "The agent's id, never invented."}},
    ),
    plan=_plan_agent_deactivate,
    execute=_execute_agent_deactivate,
)


async def _plan_agent_delete(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_AgentIdArgs, args)
    name, status = await _agent_name_status(session, parsed.agent_id)
    if status == "live":
        raise WriteRefusedError(f"“{name}” is live; pause it first (`agent_deactivate`)")
    return Plan(
        object_id=str(parsed.agent_id),
        title="Delete this agent",
        summary=(
            f"Delete “{name}”. Its numbers are released from it and it no longer uses your "
            "knowledge. Its calls and leads stay."
        ),
        current=status,
        proposed="deleted",
        cost=None,
        reversal=(
            "A deleted agent can be restored from the Agents screen; its numbers are not "
            "given back."
        ),
        args={"agent_id": str(parsed.agent_id)},
    )


async def _execute_agent_delete(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`lifecycle.archive_agent` — the console's Delete (`POST /v1/agents/{id}/archive`)."""
    parsed = parse_args(_AgentIdArgs, args)
    result = await lifecycle.archive_agent(
        session, tenant_id=actor.tenant_id, agent_id=parsed.agent_id
    )
    return Executed(
        applied=result.changed,
        detail="The agent is deleted." if result.changed else "It was already deleted.",
        audit_summary={"agent_id": str(parsed.agent_id), "status": result.status},
    )


AGENT_DELETE: Final = ActionTool(
    name="agent_delete",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="agent",
    audit_action="agent.archived",
    where="under Agents in your dashboard",
    schema=action_schema(
        "agent_delete",
        "Propose deleting an agent that is not live." + PROPOSES_ONLY,
        {"agent_id": {"type": "string", "description": "The agent's id, never invented."}},
    ),
    plan=_plan_agent_delete,
    execute=_execute_agent_delete,
)


class _HoursDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    opens: str | None
    closes: str | None
    closed: bool


class _HoursArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: Annotated[list[_HoursDay], Field(min_length=7, max_length=7)]


async def _plan_business_hours(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    from pydantic import ValidationError

    from apps.api.tenancy.business_profile import hours_line, load_profile
    from apps.api.tenancy.profile_service import ProfilePatch

    parsed = parse_args(_HoursArgs, args)
    try:
        patch = ProfilePatch.model_validate({"hours": [day.model_dump() for day in parsed.hours]})
    except ValidationError as exc:
        raise WriteRefusedError(
            "the hours must name all seven days once, each either closed or with opening and "
            "closing times like 09:30"
        ) from exc
    assert patch.hours is not None
    profile = await load_profile(session, tenant_id=actor.tenant_id)
    proposed: dict[str, dict[str, str] | None] = {
        day.day: None if day.closed else {"opens": str(day.opens), "closes": str(day.closes)}
        for day in patch.hours
    }
    return Plan(
        object_id=str(actor.tenant_id),
        title="Change your business hours",
        summary=(
            "Your agents will tell callers these hours and use them to decide when you are "
            f"open: {hours_line(proposed)}. Live agents are updated straight away."
        ),
        current=hours_line(profile.hours) or "not set",
        proposed=hours_line(proposed) or "",
        cost=None,
        reversal="Change them again on the Business profile screen.",
        args={"hours": [day.model_dump() for day in patch.hours]},
    )


async def _execute_business_hours(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`profile_service.save_profile` — `PATCH /v1/business-profile`'s call (D-695), which
    brings every agent up to date in the same transaction."""
    from apps.api.tenancy.profile_service import ProfilePatch, save_profile

    patch = ProfilePatch.model_validate({"hours": list(args["hours"])})
    steps, updated = await save_profile(
        session, tenant_id=actor.tenant_id, patch=patch, user_id=actor.user_id
    )
    return Executed(
        applied=True,
        detail=f"Your business hours are saved; {updated} agent(s) were updated.",
        audit_summary={"sections": sorted(steps), "agents_updated": updated},
    )


BUSINESS_HOURS_SET: Final = ActionTool(
    name="business_hours_set",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="organization",
    audit_action="business_profile.updated",
    where="on the Business profile screen",
    schema=action_schema(
        "business_hours_set",
        "Propose new opening hours for the business, all seven days. Every agent uses them, "
        "and live agents are updated at once." + PROPOSES_ONLY,
        {
            "hours": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "day": {
                            "type": "string",
                            "enum": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                        },
                        "opens": {
                            "anyOf": [{"type": "string"}, {"type": "null"}],
                            "description": "HH:MM",
                        },
                        "closes": {
                            "anyOf": [{"type": "string"}, {"type": "null"}],
                            "description": "HH:MM",
                        },
                        "closed": {"type": "boolean"},
                    },
                    "required": ["day", "opens", "closes", "closed"],
                    "additionalProperties": False,
                },
                "description": "Exactly seven entries, one per day.",
            }
        },
    ),
    plan=_plan_business_hours,
    execute=_execute_business_hours,
)


#: The profile sections `business_profile_set` may replace. Contacts are NOT among them:
#: each carries a phone number, and the model is never told one — they are edited on the
#: Business profile screen.
_PROFILE_SECTIONS: Final = ("branches", "services", "faqs", "staff", "booking_rules", "languages")


async def _plan_business_profile(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    """READ ONLY. The sections are validated through `ProfilePatch` itself — the PATCH
    route's own model — so a price, a list length or a language the form refuses is refused
    here too, before a card is drawn."""
    from pydantic import ValidationError

    from apps.api.tenancy.business_profile import load_profile
    from apps.api.tenancy.profile_service import ProfilePatch

    unknown = set(args) - set(_PROFILE_SECTIONS)
    if unknown:
        raise WriteRefusedError(
            "only branches, services, faqs, staff, booking_rules and languages can be set "
            "here; contacts are edited on the Business profile screen"
        )
    sent = {key: value for key, value in args.items() if value is not None}
    if not sent:
        raise WriteRefusedError("name at least one section of the business profile to replace")
    try:
        patch = ProfilePatch.model_validate(sent)
    except ValidationError as exc:
        fields = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
        raise WriteRefusedError(
            "these sections are not valid as given: "
            + ", ".join(fields)
            + " (prices are digits only, like 1500 or 1500.50)"
        ) from exc
    profile = await load_profile(session, tenant_id=actor.tenant_id)

    def _size(section: str, value: Any) -> str:
        if section == "booking_rules":
            return "set" if value else "empty"
        return f"{len(value or [])} item(s)"

    names = sorted(sent)
    current = "; ".join(f"{name} {_size(name, getattr(profile, name))}" for name in names)
    proposed = "; ".join(f"{name} {_size(name, getattr(patch, name))}" for name in names)
    return Plan(
        object_id=str(actor.tenant_id),
        title="Change your business profile",
        summary=(
            "Replace " + ", ".join(names) + " in your business profile. Every agent answers "
            "from it, and live agents are updated straight away."
        ),
        current=current,
        proposed=proposed,
        cost=None,
        reversal="Change them again on the Business profile screen; the old entries are not kept.",
        args=patch.model_dump(mode="json", exclude_unset=True),
    )


async def _execute_business_profile(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`profile_service.save_profile` — `PATCH /v1/business-profile`'s call (D-695). It
    takes the knowledge lock and brings every agent's facts up to date itself; nothing here
    writes an agent's facts directly."""
    from apps.api.tenancy.profile_service import ProfilePatch, save_profile

    patch = ProfilePatch.model_validate(dict(args))
    steps, updated = await save_profile(
        session, tenant_id=actor.tenant_id, patch=patch, user_id=actor.user_id
    )
    return Executed(
        applied=True,
        detail=f"Your business profile is saved; {updated} agent(s) were updated.",
        audit_summary={"sections": sorted(steps), "agents_updated": updated},
    )


def _nullable_list(item: dict[str, Any], description: str) -> dict[str, Any]:
    return {
        "anyOf": [{"type": "array", "items": item}, {"type": "null"}],
        "description": description + " Null leaves it as it is; a list REPLACES it whole.",
    }


def _strict_object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_NULLABLE_TEXT: Final = {"anyOf": [{"type": "string"}, {"type": "null"}]}

BUSINESS_PROFILE_SET: Final = ActionTool(
    name="business_profile_set",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="organization",
    audit_action="business_profile.updated",
    where="on the Business profile screen",
    schema=action_schema(
        "business_profile_set",
        "Propose replacing sections of the business profile every agent answers from: "
        "branches and addresses, services and prices, FAQs, staff, booking rules, "
        "languages. Send the WHOLE section, including what should stay — read it from the "
        "Business profile screen state first. Hours have their own tool; contacts are "
        "edited on the screen." + PROPOSES_ONLY,
        {
            "branches": _nullable_list(
                _strict_object({"label": {"type": "string"}, "address": {"type": "string"}}),
                "Every branch with its address.",
            ),
            "services": _nullable_list(
                _strict_object(
                    {
                        "name": {"type": "string"},
                        "price_inr": {**_NULLABLE_TEXT, "description": "Digits, e.g. 1500"},
                        "notes": _NULLABLE_TEXT,
                    }
                ),
                "Every service, with its price in rupees where there is one.",
            ),
            "faqs": _nullable_list(
                _strict_object({"question": {"type": "string"}, "answer": {"type": "string"}}),
                "Every frequently asked question with the answer to give.",
            ),
            "staff": _nullable_list(
                _strict_object(
                    {
                        "name": {"type": "string"},
                        "pronunciation": _NULLABLE_TEXT,
                        "role": _NULLABLE_TEXT,
                    }
                ),
                "Every staff member callers may ask for.",
            ),
            "booking_rules": {
                **_NULLABLE_TEXT,
                "description": "How bookings work, in the owner's words, or null to leave it.",
            },
            "languages": {
                "anyOf": [
                    {"type": "array", "items": {"type": "string", "enum": list(PRODUCT_LANGUAGES)}},
                    {"type": "null"},
                ],
                "description": "Every language the business serves callers in, or null.",
            },
        },
    ),
    plan=_plan_business_profile,
    execute=_execute_business_profile,
)


# =========================================================================================
# KNOWLEDGE
# =========================================================================================


class _KnowledgeLinkArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(max_length=200)] | None
    url: Annotated[str, Field(max_length=2048)]


async def _plan_knowledge_link(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del session
    from urllib.parse import urlsplit

    from apps.api.copilot.actions import actor_realm
    from apps.api.kb.curation import goes_live_without_review

    parsed = parse_args(_KnowledgeLinkArgs, args)
    url = strip_invisible(parsed.url.strip())
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise WriteRefusedError("`url` must be a web address starting with https://")
    live = goes_live_without_review(realm=actor_realm(actor), impersonating=actor.impersonating)
    name = None if parsed.name is None else (strip_invisible(parsed.name.strip()) or None)
    return Plan(
        object_id="",
        title="Add a web page to your knowledge",
        summary=(
            f"Read the page at {parts.hostname} and add it to the knowledge every agent "
            "answers from. "
            + ("It goes to your agents without review" if live else "It goes to review first")
            + ", and the page is re-read when it changes."
        ),
        current=None,
        proposed=name or parts.hostname,
        cost=None,
        reversal="You can remove it from the Knowledge base screen.",
        args={"name": name, "url": url},
    )


async def _execute_knowledge_link(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`kb.uploads.create_link` — `POST /v1/kb/links`'s call, with its SSRF gate."""
    from apps.api.copilot.actions import actor_realm
    from apps.api.kb.curation import goes_live_without_review
    from apps.api.kb.uploads import create_link

    parsed = parse_args(_KnowledgeLinkArgs, args)
    created = await create_link(
        session,
        tenant_id=actor.tenant_id,
        name=parsed.name,
        url=parsed.url,
        submitted_by=actor.user_id,
        auto_approve=goes_live_without_review(
            realm=actor_realm(actor), impersonating=actor.impersonating
        ),
    )
    return Executed(
        applied=True,
        detail="The page is added; it is being read now and appears under Knowledge.",
        audit_summary={"upload_id": str(created["id"]), "source_id": str(created["source_id"])},
        object_id=str(created["source_id"]),
    )


KNOWLEDGE_LINK_ADD: Final = ActionTool(
    name="knowledge_link_add",
    tier="confirm",
    undo=None,
    # `requires_kb_curation()`'s permission, which `may_act` answers with the owner's switch.
    permission="kb:write",
    object_type="kb_source",
    audit_action="kb.link_added",
    where="under Knowledge",
    schema=action_schema(
        "knowledge_link_add",
        "Propose adding a web page the person names to the business's knowledge. Only a page "
        "they gave you — never one you chose." + PROPOSES_ONLY,
        {
            "name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "A short title, or null to use the page's own.",
            },
            "url": {"type": "string", "description": "The full web address."},
        },
    ),
    plan=_plan_knowledge_link,
    execute=_execute_knowledge_link,
)


class _KnowledgeRemoveArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_id: UUID


async def _upload_row(session: AsyncSession, upload_id: UUID) -> tuple[str, str]:
    row = (
        await session.execute(
            text(
                "SELECT s.name, u.source_id FROM kb_uploads u "
                "JOIN kb_sources s ON s.id = u.source_id "
                "WHERE u.id = :uid"
            ),
            {"uid": upload_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Knowledge document")
    return strip_invisible(str(row[0])), str(row[1])


async def _plan_knowledge_remove(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_KnowledgeRemoveArgs, args)
    name, source_id = await _upload_row(session, parsed.upload_id)
    return Plan(
        object_id=source_id,
        title="Remove this from your knowledge",
        summary=f"Take “{name}” off every agent and delete it.",
        current="In your knowledge",
        proposed="Deleted",
        cost=None,
        reversal="This cannot be undone; you would add the document or page again.",
        args={"upload_id": str(parsed.upload_id)},
    )


async def _execute_knowledge_remove(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`kb.uploads.remove_upload` — `DELETE /v1/kb/uploads/{id}`'s call."""
    from apps.api.kb.uploads import remove_upload

    parsed = parse_args(_KnowledgeRemoveArgs, args)
    await remove_upload(session, tenant_id=actor.tenant_id, upload_id=parsed.upload_id)
    return Executed(
        applied=True,
        detail="It is removed from every agent and deleted.",
        audit_summary={"upload_id": str(parsed.upload_id)},
    )


KNOWLEDGE_REMOVE: Final = ActionTool(
    name="knowledge_remove",
    tier="confirm",
    undo=None,
    permission="kb:write",
    object_type="kb_source",
    audit_action="kb.removed",
    where="under Knowledge",
    schema=action_schema(
        "knowledge_remove",
        "Propose removing a document or web page from the business's knowledge. Take the "
        "`upload_id` from `knowledge_sources`; typed facts are edited on the Knowledge "
        "base screen." + PROPOSES_ONLY,
        {"upload_id": {"type": "string", "description": "From `knowledge_sources`."}},
    ),
    plan=_plan_knowledge_remove,
    execute=_execute_knowledge_remove,
)


# =========================================================================================
# PHONE NUMBERS
# =========================================================================================


class _NumberBuyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city: Annotated[str, Field(min_length=1, max_length=60)]
    agent_id: UUID | None
    direction: Literal["inbound", "outbound", "both"]


async def _plan_number_buy(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    """READ ONLY: the purchase gates (`purchase_readiness`) and the first number available in
    the city. The number is signed into the proposal and shown masked — the model never
    holds a full number."""
    from apps.api.campaigns import engine_numbers
    from apps.api.campaigns.engine_number_purchase import purchase_readiness
    from apps.api.tenancy.engine_workspace import engine_has_workspaces
    from apps.workers.redaction import redact

    parsed = parse_args(_NumberBuyArgs, args)
    if not engine_has_workspaces():
        raise WriteRefusedError("numbers are not bought in the app on this account's phone system")
    readiness = await purchase_readiness(session, tenant_id=actor.tenant_id)
    if readiness.step != "ready":
        raise WriteRefusedError(
            f"a number cannot be bought yet ({readiness.blocker or readiness.step}); the Your "
            "phone number screen says what is missing"
        )
    if parsed.agent_id is not None:
        await _agent_name_status(session, parsed.agent_id)
    city = strip_invisible(parsed.city.strip())
    page = await engine_numbers.search_available(
        session, actor.tenant_id, city=city, pattern=None, cursor=None
    )
    if not page.numbers:
        raise WriteRefusedError(f"no number is available in {city} right now")
    number = page.numbers[0].number
    price = readiness.client_inr_per_month
    masked = redact(number).text
    return Plan(
        object_id="",
        title="Buy a phone number",
        summary=(
            f"Rent the number {masked} in {city} in your business's name"
            + (" for the chosen agent" if parsed.agent_id else "")
            + ". The first month is charged now."
        ),
        current=None,
        proposed=masked,
        cost=(
            f"₹{price} a month, the first month charged from your credit now."
            if price is not None
            else "A monthly rental, charged from your credit."
        ),
        reversal="You can release it later; the month already paid is not refunded.",
        args={
            "city": city,
            "agent_id": None if parsed.agent_id is None else str(parsed.agent_id),
            "direction": parsed.direction,
            "number": number,
            "attempt": str(uuid4()),
        },
    )


class _NumberBuySigned(_NumberBuyArgs):
    number: str
    attempt: UUID


async def _execute_number_buy(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`purchase_engine_number` — `POST /v1/numbers/own/purchase`'s call (D-693), which runs
    every gate again, checks the wallet and charges the first month."""
    from apps.api.campaigns.engine_number_purchase import purchase_engine_number

    del session
    parsed = parse_args(_NumberBuySigned, args)
    bought = await purchase_engine_number(
        tenant_id=actor.tenant_id,
        number=parsed.number,
        agent_id=parsed.agent_id,
        direction=parsed.direction,
        idempotency_key=f"copilot:{parsed.attempt}",
        requested_by="client",
    )
    return Executed(
        applied=not bought.replayed,
        detail="The number is yours and appears on the Your phone number screen.",
        audit_summary={
            "inr_per_month": None
            if bought.client_inr_per_month is None
            else str(bought.client_inr_per_month),
            "attachment": bought.attachment,
        },
        object_id=str(bought.number_id),
    )


NUMBER_BUY: Final = ActionTool(
    name="number_buy",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="phone_number",
    audit_action="number.bought",
    where="on the Your phone number screen",
    schema=action_schema(
        "number_buy",
        "Propose renting a new phone number in a city (see `numbers_available`). It spends "
        "credit: the first month is charged on confirm." + PROPOSES_ONLY,
        {
            "city": {"type": "string", "description": "A city from `numbers_available`."},
            "agent_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "The agent that should answer or call from it, or null.",
            },
            "direction": {"type": "string", "enum": ["inbound", "outbound", "both"]},
        },
    ),
    plan=_plan_number_buy,
    execute=_execute_number_buy,
)


class _NumberReleaseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number_id: UUID


async def _plan_number_release(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    from apps.api.tenancy.engine_workspace import engine_has_workspaces
    from apps.workers.redaction import redact

    parsed = parse_args(_NumberReleaseArgs, args)
    if not engine_has_workspaces():
        raise WriteRefusedError(
            "numbers are not released in the app on this account's phone system"
        )
    row = (
        await session.execute(
            text("SELECT e164 FROM phone_numbers WHERE id = :nid AND released_at IS NULL"),
            {"nid": parsed.number_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Phone number")
    masked = redact(str(row[0])).text
    return Plan(
        object_id=str(parsed.number_id),
        title="Release this phone number",
        summary=(
            f"Give up {masked}. Calls to it stop reaching your agents, and it cannot be got back."
        ),
        current=masked,
        proposed="Released",
        cost="The month already paid is not refunded.",
        reversal="A released number cannot be recovered.",
        args={"number_id": str(parsed.number_id)},
    )


async def _execute_number_release(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`release_engine_number(by_admin=False)` — `POST /v1/numbers/own/{id}/release`'s call."""
    from apps.api.campaigns.engine_number_purchase import release_engine_number

    parsed = parse_args(_NumberReleaseArgs, args)
    released = await release_engine_number(
        session, tenant_id=actor.tenant_id, number_id=parsed.number_id, by_admin=False
    )
    return Executed(
        applied=released,
        detail="The number is released." if released else "It was already released.",
        audit_summary={"refunded": False},
    )


NUMBER_RELEASE: Final = ActionTool(
    name="number_release",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="phone_number",
    audit_action="number.released",
    where="on the Your phone number screen",
    schema=action_schema(
        "number_release",
        "Propose giving up one of the account's phone numbers for good." + PROPOSES_ONLY,
        {"number_id": {"type": "string", "description": "From `numbers_list`."}},
    ),
    plan=_plan_number_release,
    execute=_execute_number_release,
)


# =========================================================================================
# TEST CALL (the free trial's, D-697)
# =========================================================================================


class _TestCallArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    lead_id: UUID


async def _plan_test_call(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    """READ ONLY. The person is named by a LEAD (the model never holds a number), and the
    trial's own gate — `check_dispatch(trial_call=True)`: the trial's minutes and daily cap,
    the pledge, calling hours, do-not-call — is asked so a refusal comes back before a card."""
    from apps.api.agents.trial_calls import NOT_READY_REASON, trial_calling_ready
    from apps.api.compliance.service import check_dispatch

    parsed = parse_args(_TestCallArgs, args)
    agent_name, _status = await _agent_name_status(session, parsed.agent_id)
    phone, _name = await crm_service.lead_phone(session, parsed.lead_id)
    if not trial_calling_ready():
        raise WriteRefusedError(f"no test call was proposed — {NOT_READY_REASON}")
    decision = await check_dispatch(
        session,
        tenant_id=actor.tenant_id,
        agent_id=parsed.agent_id,
        phone_e164=phone,
        trial_call=True,
    )
    if not decision.allowed:
        raise WriteRefusedError(
            "this test call cannot be placed and nothing was proposed — "
            f"{decision.rule}: {decision.reason}. Tell the person exactly this"
        )
    return Plan(
        object_id=str(parsed.agent_id),
        title="Place a test call",
        summary=f"“{agent_name}” calls this lead now as a test call from Calevate's trial number.",
        current=None,
        proposed="A test call now",
        cost="It uses your trial's free minutes.",
        reversal="A call cannot be taken back once it has started ringing.",
        args={
            "agent_id": str(parsed.agent_id),
            "lead_id": str(parsed.lead_id),
            "attempt": str(uuid4()),
        },
    )


class _TestCallSigned(_TestCallArgs):
    attempt: UUID


async def _execute_test_call(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`agents.trial_calls.place_trial_call` — `POST /v1/trial/calls`'s function, which runs
    the gate again, holds the one trial line and writes `trial.test_call_placed`."""
    from apps.api.agents.trial_calls import place_trial_call

    parsed = parse_args(_TestCallSigned, args)
    phone, _name = await crm_service.lead_phone(session, parsed.lead_id)
    result = await place_trial_call(
        session,
        principal=_principal_of(actor),
        agent_id=parsed.agent_id,
        number=phone,
        idempotency_key=f"copilot:{parsed.attempt}",
    )
    if result.status == "blocked":
        return Executed(
            applied=False,
            detail=f"The test call was not placed: {result.blocked_reason}",
            audit_summary={"status": "blocked", "rule": result.blocked_rule},
        )
    return Executed(
        applied=True,
        detail="The test call is being placed. It appears in Call logs as it happens.",
        audit_summary={"status": "queued"},
    )


AGENT_TEST_CALL: Final = ActionTool(
    name="agent_test_call",
    tier="confirm",
    undo=None,
    # `POST /v1/trial/calls`'s permission.
    permission="leads:dispatch",
    object_type="agent",
    audit_action="trial.test_call_requested",
    where="in Call logs",
    schema=action_schema(
        "agent_test_call",
        "Propose a free-trial TEST CALL: one agent calls one lead (for example the owner "
        "saved as a lead) from Calevate's trial number. For a paying account use "
        "`call_place`." + PROPOSES_ONLY,
        {
            "agent_id": {"type": "string", "description": "The agent to test, never invented."},
            "lead_id": {"type": "string", "description": "Who it calls, by lead id."},
        },
    ),
    plan=_plan_test_call,
    execute=_execute_test_call,
)


#: Registration order is wire order (the cacheable prompt prefix). New actions APPEND.
CONSOLE_ACTIONS: Final[tuple[ActionTool, ...]] = (
    LEAD_ASSIGN,
    LEAD_RENAME,
    LEADS_BULK_UPDATE,
    DNC_REMOVE,
    CALL_PLACE,
    CALLBACK_BOOK,
    CALLBACK_RESCHEDULE,
    CALLBACK_CANCEL,
    CAMPAIGN_CREATE,
    CAMPAIGN_CLONE,
    CAMPAIGN_ADD_LEADS,
    CAMPAIGN_SCHEDULE,
    CAMPAIGN_UNSCHEDULE,
    CAMPAIGN_RESUME,
    AGENT_EDIT,
    AGENT_EDIT_LIVE,
    AGENT_CAPTURE_FIELDS_SET,
    AGENT_CHANGES_APPLY,
    AGENT_DEACTIVATE,
    AGENT_DELETE,
    BUSINESS_HOURS_SET,
    KNOWLEDGE_LINK_ADD,
    KNOWLEDGE_REMOVE,
    NUMBER_BUY,
    NUMBER_RELEASE,
    AGENT_TEST_CALL,
    BUSINESS_PROFILE_SET,
)

__all__ = ["CONSOLE_ACTIONS"]
