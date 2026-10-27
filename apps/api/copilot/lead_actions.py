"""Pip's Leads, Calls and Do-not-call buttons that lane L2 of D-893 added.

Each action calls the service the console's own button calls, under the permission that
button's route declares:

* `dnc_restore` — `POST /v1/dnc/{id}/restore` (`dnc.restore_optout`): a person's own opt-out
  restored on an attested ground. Confirm, and bound to the newest opt-out record the card
  showed, so one recorded meanwhile is refused rather than undone unseen. The route withholds
  it from a view-as session; Pip is closed to one altogether (`actions.assistant_closed_to`).
* `lead_view_save` — the Leads screen's "Save this view" (`crm.saved_views`). Immediate,
  with Undo: a private view is the person's own screen state.
* `leads_export` / `calls_export` — the two Export buttons: `calls:read_raw`, the same
  emailed code, and the same audit row, written when the file is downloaded
  (`crm/export_tickets.py` says why the confirm issues a ticket rather than a file).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.plans import IST
from apps.api.copilot import lens_args
from apps.api.copilot.account_actions import LEAD_SOURCE_MAPPING
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
    account_code,
    action_schema,
    parse_args,
)
from apps.api.core.errors import ProblemError
from apps.api.crm import export_tickets, saved_views
from apps.api.crm import lens as crm_lens
from apps.api.crm import service as crm_service
from apps.api.crm.schemas import (
    MAX_VIEW_LAST_DAYS,
    CallLensIn,
    LeadLensIn,
    SavedViewFilters,
    SavedViewIn,
    SavedViewUpdateIn,
    ViewDaysIn,
)


def _today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


# --- dnc_restore ---------------------------------------------------------------------------


class _DncRestoreArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: UUID
    ground: Literal["never_asked", "asked_to_be_called"]
    #: How and when they asked to be called; required for `asked_to_be_called`.
    note: str | None = Field(default=None, max_length=400)


class _DncRestoreSigned(_DncRestoreArgs):
    entry_id: UUID
    latest_evidence_id: UUID | None


_GROUND_WORDS: Final = {
    "never_asked": "they never asked not to be called (recorded by mistake)",
    "asked_to_be_called": "they have since asked to be called",
}


async def _restorable_entry(session: AsyncSession, actor: ToolActor, lead_id: UUID) -> UUID:
    """The opt-out entry suppressing this lead's number, found from the lead so the model is
    never told the number, or a refusal naming which kind of entry it is."""
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
    if not dnc.is_restorable(scope=str(row[1]), source=source):
        if dnc.is_removable(scope=str(row[1]), source=source):
            raise WriteRefusedError(
                "that number was added by hand, so it is not restored: use dnc_remove"
            )
        raise WriteRefusedError(
            "that number is on the list by a regulator or the platform-wide list and cannot "
            "come off here; tell the person support can look at a genuine mistake"
        )
    return UUID(str(row[0]))


async def _plan_dnc_restore(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    """READ ONLY. The card says how many opt-outs are on record and when the newest was,
    never the caller's words: this card is also a log line."""
    from apps.api.compliance import dnc

    parsed = parse_args(_DncRestoreArgs, args)
    note = " ".join((parsed.note or "").split()) or None
    if parsed.ground == "asked_to_be_called" and (note is None or len(note) < dnc.RESTORE_NOTE_MIN):
        raise WriteRefusedError(
            "say how and when they asked to be called, in the person's words, as `note`"
        )
    entry_id = await _restorable_entry(session, actor, parsed.lead_id)
    evidence = await dnc.optout_evidence(session, entry_id=entry_id)
    newest = evidence.records[0] if evidence.records else None
    on_record = (
        "No opt-out is on record for it."
        if newest is None
        else f"{len(evidence.records)} opt-out(s) on record, the newest on "
        f"{newest.recorded_at.astimezone(IST):%d %b %Y}."
    )
    return Plan(
        object_id=str(entry_id),
        title="Allow calls to someone who opted out",
        summary=(
            f"Take this lead's number off your do-not-call list because "
            f"{_GROUND_WORDS[parsed.ground]}. {on_record} You are confirming this is true."
        ),
        current="Opted out",
        proposed="Callable",
        cost=None,
        reversal="You can add the number back to the do-not-call list at any time.",
        args={
            "lead_id": str(parsed.lead_id),
            "ground": parsed.ground,
            "note": note,
            "entry_id": str(entry_id),
            "latest_evidence_id": None if newest is None else str(newest.id),
        },
    )


async def _execute_dnc_restore(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`dnc.restore_optout` — the restore route's call, which refuses when a newer opt-out
    was recorded since the card was read."""
    from apps.api.compliance import dnc

    parsed = parse_args(_DncRestoreSigned, args)
    restoration = await dnc.restore_optout(
        session,
        tenant_id=actor.tenant_id,
        entry_id=parsed.entry_id,
        ground=parsed.ground,
        note=parsed.note,
        latest_evidence_id=parsed.latest_evidence_id,
    )
    return Executed(
        applied=True,
        detail="That number is off your do-not-call list. Campaigns may call it again.",
        audit_summary={
            "source": restoration.source,
            "subject_ref": restoration.subject_ref,
            "ground": parsed.ground,
            "note": restoration.note,
        },
        audit_action=dnc.restore_audit_action(parsed.ground),
    )


DNC_RESTORE: Final = ActionTool(
    name="dnc_restore",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="dnc_list",
    audit_action="dnc.optout_restored",
    where="on the Do not call screen",
    schema=action_schema(
        "dnc_restore",
        "Propose taking a lead off do-not-call where the lead itself opted out, on the "
        "person's word that it was a mistake (never_asked) or that they since asked to be "
        "called (asked_to_be_called, with `note`: how and when). Hand-added: dnc_remove."
        + PROPOSES_ONLY,
        {
            "lead_id": {"type": "string"},
            "ground": {"type": "string", "enum": ["never_asked", "asked_to_be_called"]},
            "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
    ),
    plan=_plan_dnc_restore,
    execute=_execute_dnc_restore,
)


# --- lead_view_save ------------------------------------------------------------------------


class _ViewSaveArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    lens: dict[str, Any] | None
    #: Date ranges ending today are kept as "the last N days".
    rolling: bool | None = None


def _days(start: date | None, end: date | None, *, rolling: bool, today: date) -> ViewDaysIn | None:
    if start is None and end is None:
        return None
    if rolling and start is not None and end == today:
        span = (today - start).days + 1
        if 1 <= span <= MAX_VIEW_LAST_DAYS:
            return ViewDaysIn(last_days=span)
    return ViewDaysIn(from_day=start, to_day=end)


def view_filters(lens: LeadLensIn, *, me: UUID, rolling: bool, today: date) -> SavedViewFilters:
    """A lead lens as a saved view's filters. Refuses what a view cannot keep: a search or
    question (transient lookups, `SavedViewFilters`) and another person as the owner."""
    if lens.search or lens.ask:
        raise WriteRefusedError(
            "a saved view keeps filters, not a search or a question: leave them out"
        )
    if lens.assigned_to is not None and lens.assigned_to != me:
        raise WriteRefusedError("a saved view can keep 'assigned to me' only, not someone else")
    fields: dict[str, list[str]] = {}
    for entry in lens.f:
        key, _, value = entry.partition(":")
        fields.setdefault(key, []).append(value)
    return SavedViewFilters.model_validate(
        {
            "status": lens.status,
            "agent_id": lens.agent_id,
            "assigned_to_me": lens.assigned_to == me,
            "fields": fields,
            "created": _days(lens.created_from, lens.created_to, rolling=rolling, today=today),
            "last_call": _days(
                lens.last_call_from, lens.last_call_to, rolling=rolling, today=today
            ),
            "last_outcome": lens.last_outcome,
            "direction": lens.direction,
            "test_calls": lens.test_calls,
            "callback_open": lens.callback_open,
            "follow_up": lens.follow_up,
            "captured": list(lens.captured),
        }
    )


def _parsed_view(actor: ToolActor, args: Mapping[str, Any]) -> tuple[str, SavedViewFilters]:
    parsed = parse_args(_ViewSaveArgs, args)
    try:
        lens = lens_args.lead_lens(parsed.lens)
        filters = view_filters(
            lens, me=actor.user_id, rolling=parsed.rolling is not False, today=_today()
        )
    except lens_args.LensArgumentError as refused:
        raise WriteRefusedError(refused.reason) from refused
    except ValueError as invalid:
        raise WriteRefusedError("those filters cannot be kept in a view") from invalid
    return parsed.name.strip(), filters


async def _plan_view_save(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    name, filters = _parsed_view(actor, args)
    existing = await saved_views.find_view(session, user_id=actor.user_id, name=name)
    lens = filters.lens(_today())
    return Plan(
        object_id="" if existing is None else str(existing.id),
        title="Update a saved view" if existing else "Save a view of your leads",
        summary=f"“{name}” shows {crm_lens.describe_lead_lens(lens)}. Only you see it.",
        current=None if existing is None else "Saved earlier",
        proposed=name,
        cost=None,
        reversal="Undo removes the view, or puts back its earlier filters.",
        args={
            "name": name,
            "lens": args.get("lens"),
            "rolling": args.get("rolling"),
        },
    )


async def _execute_view_save(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`crm.saved_views.create_view` / `update_view`, the Save and Update buttons' calls."""
    name, filters = _parsed_view(actor, args)
    existing = await saved_views.find_view(session, user_id=actor.user_id, name=name)
    if existing is None:
        view = await saved_views.create_view(
            session, user_id=actor.user_id, payload=SavedViewIn(name=name, filters=filters)
        )
    else:
        view = await saved_views.update_view(
            session,
            existing.id,
            user_id=actor.user_id,
            payload=SavedViewUpdateIn(filters=filters),
        )
    return Executed(
        applied=True,
        detail=f"Saved. Pick “{name}” under Saved view on the Leads screen.",
        audit_summary={"view_id": str(view.id), "created": existing is None},
        object_id=str(view.id),
    )


async def _capture_view(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    name = str(args.get("name", "")).strip()
    found = await saved_views.find_view(session, user_id=actor.user_id, name=name)
    if found is None:
        return {"view_id": None}
    row = (
        await session.execute(
            text("SELECT filters FROM lead_saved_views WHERE id = :id AND user_id = :uid"),
            {"id": found.id, "uid": actor.user_id},
        )
    ).first()
    return {"view_id": str(found.id), "filters": None if row is None else row[0]}


async def _invert_view(session: AsyncSession, actor: ToolActor, record: UndoRecord) -> str:
    after = record.result_state
    view_id = after.get("view_id")
    if view_id is None:
        raise UndoRefusedError("that view no longer exists")
    live = await _capture_view(session, actor, record.args)
    if live != after:
        raise UndoRefusedError("that view was changed since, so it was left as it is")
    before = record.prior_state
    try:
        if before.get("view_id") is None:
            await saved_views.delete_view(session, UUID(str(view_id)), user_id=actor.user_id)
            return "The view is removed."
        await saved_views.update_view(
            session,
            UUID(str(view_id)),
            user_id=actor.user_id,
            payload=SavedViewUpdateIn(
                filters=SavedViewFilters.model_validate(before.get("filters") or {})
            ),
        )
    except ProblemError as exc:
        raise UndoRefusedError("that view could not be put back") from exc
    return "The view has its earlier filters again."


LEAD_VIEW_SAVE: Final = ActionTool(
    name="lead_view_save",
    tier="immediate",
    undo=Undo(capture=_capture_view, invert=_invert_view),
    permission="leads:write",
    object_type="lead_saved_view",
    audit_action="leads.view_saved",
    where="under Saved view on the Leads screen",
    schema=action_schema(
        "lead_view_save",
        "Save the leads `lens` as a named view only this person sees (same name: update it). "
        "rolling (default true): ranges ending today stay the last N days." + DOES_IT,
        {
            "name": {"type": "string"},
            "lens": lens_args.LEAD_LENS_SCHEMA,
            "rolling": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
        },
    ),
    plan=_plan_view_save,
    execute=_execute_view_save,
)


# --- exports -------------------------------------------------------------------------------

_READY: Final = (
    "Your file is ready: press Download on this card within ten minutes. It holds full phone "
    "numbers."
)


class _LeadsExportArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lens: dict[str, Any] | None


async def _plan_leads_export(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_LeadsExportArgs, args)
    try:
        lens = lens_args.lead_lens(parsed.lens)
    except lens_args.LensArgumentError as refused:
        raise WriteRefusedError(refused.reason) from refused
    if lens.ask:
        raise WriteRefusedError("an export takes filters, not a question: use the filters")
    try:
        scope = await crm_lens.resolve_lead_scope(session, lens)
    except ProblemError as exc:
        raise WriteRefusedError(exc.detail) from exc
    count = len(await crm_lens.lead_ids(session, scope))
    if count == 0:
        raise WriteRefusedError("no lead matches those filters, so there is nothing to export")
    if count > crm_service.MAX_EXPORT_ROWS:
        raise WriteRefusedError(
            f"that is {count} leads, over the {crm_service.MAX_EXPORT_ROWS} a file holds: "
            "narrow the filters"
        )
    return Plan(
        object_id="",
        title="Export leads",
        summary=(
            f"A spreadsheet of {count} {'lead' if count == 1 else 'leads'} "
            f"({crm_lens.describe_lead_lens(lens)}), with full phone numbers. "
            "It is recorded in your activity log."
        ),
        current=None,
        proposed=f"{count} rows",
        cost=None,
        reversal="A downloaded file cannot be taken back.",
        args={"lens": lens.model_dump(mode="json", exclude_defaults=True)},
    )


async def _execute_leads_export(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    del session
    parsed = parse_args(_LeadsExportArgs, args)
    lens = LeadLensIn.model_validate(parsed.lens or {})
    ticket = await export_tickets.issue(
        tenant_id=actor.tenant_id,
        user_id=actor.user_id,
        kind="leads",
        lens=lens.model_dump(mode="json", exclude_defaults=True),
    )
    return Executed(
        applied=True,
        detail=_READY,
        recorded="Prepared a leads export.",
        audit_summary={"lens_filters": sorted(lens.model_fields_set) or None},
        download_ticket=ticket,
    )


LEADS_EXPORT: Final = ActionTool(
    name="leads_export",
    tier="confirm",
    undo=None,
    permission="calls:read_raw",
    object_type="lead_export",
    audit_action="leads.export_prepared",
    where="as a download on this card",
    schema=action_schema(
        "leads_export",
        "Propose a spreadsheet of the leads `lens` matches, with full numbers, to download."
        + PROPOSES_ONLY,
        {"lens": lens_args.LEAD_LENS_SCHEMA},
    ),
    plan=_plan_leads_export,
    execute=_execute_leads_export,
    action_code=account_code("export_leads"),
)


class _CallsExportArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_lens: dict[str, Any] | None


def _call_lens(raw: object) -> CallLensIn:
    try:
        return lens_args.call_lens(raw)
    except lens_args.LensArgumentError as refused:
        raise WriteRefusedError(refused.reason.replace("`lens", "`call_lens")) from refused


async def _plan_calls_export(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_CallsExportArgs, args)
    lens = _call_lens(parsed.call_lens)
    try:
        filters = crm_lens.call_filters(lens)
    except ProblemError as exc:
        raise WriteRefusedError(exc.detail) from exc
    count = await crm_lens.count_calls(session, filters)
    if count == 0:
        raise WriteRefusedError("no call matches those filters, so there is nothing to export")
    if count > crm_service.MAX_EXPORT_ROWS:
        raise WriteRefusedError(
            f"that is {count} calls, over the {crm_service.MAX_EXPORT_ROWS} a file holds: "
            "narrow the dates"
        )
    return Plan(
        object_id="",
        title="Export calls",
        summary=(
            f"A spreadsheet of {count} {'call' if count == 1 else 'calls'} with each caller's "
            "full number. It is recorded in your activity log."
        ),
        current=None,
        proposed=f"{count} rows",
        cost=None,
        reversal="A downloaded file cannot be taken back.",
        args={"call_lens": lens.model_dump(mode="json", exclude_defaults=True)},
    )


async def _execute_calls_export(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    del session
    parsed = parse_args(_CallsExportArgs, args)
    lens = CallLensIn.model_validate(parsed.call_lens or {})
    ticket = await export_tickets.issue(
        tenant_id=actor.tenant_id,
        user_id=actor.user_id,
        kind="calls",
        lens=lens.model_dump(mode="json", exclude_defaults=True),
    )
    return Executed(
        applied=True,
        detail=_READY,
        recorded="Prepared a calls export.",
        audit_summary={"lens_filters": sorted(lens.model_fields_set) or None},
        download_ticket=ticket,
    )


CALLS_EXPORT: Final = ActionTool(
    name="calls_export",
    tier="confirm",
    undo=None,
    permission="calls:read_raw",
    object_type="call_export",
    audit_action="calls.export_prepared",
    where="as a download on this card",
    schema=action_schema(
        "calls_export",
        "Propose a spreadsheet of the calls `call_lens` matches, with full numbers, to download."
        + PROPOSES_ONLY,
        {"call_lens": lens_args.CALL_LENS_SCHEMA},
    ),
    plan=_plan_calls_export,
    execute=_execute_calls_export,
    action_code=account_code("export_calls"),
)


LEAD_ACTIONS: Final[tuple[ActionTool, ...]] = (
    LEAD_SOURCE_MAPPING,
    DNC_RESTORE,
    LEAD_VIEW_SAVE,
    LEADS_EXPORT,
    CALLS_EXPORT,
)


__all__ = ["LEAD_ACTIONS", "view_filters"]
