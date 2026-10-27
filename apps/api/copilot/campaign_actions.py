"""Pip's remaining campaign buttons (D-893 lane L3): edit a draft (with its retry policy),
repeat, stop, delete, add contacts from a pasted or attached list, and take contacts off.

Every tool follows `docs/COPILOT-CONTRACT.md` and calls the function the campaign screen's
button calls (`campaigns.controls`, `campaigns.scheduling`, `campaigns.service.add_contacts`).
Create, copy, schedule, cancel a start, launch, pause, resume and adding leads by a lens live
in `console_actions.py`, `agent_actions.py`, `write_tools.py` and `set_actions.py`.

Tiers: `campaign_edit` is immediate with an exact Undo, because it accepts only a draft,
and a draft dials nobody. The rest are confirm: a repeat is every future launch, stop and
delete cannot be taken back, and the contact list is who will be called.

Launch and resume are not here, and nothing here runs the compliance gate: the gate runs
when a repeat FIRES (`scheduling.fire_schedule`) and on every dial (`check_dispatch`), as
for the screen's buttons.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any, Final
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns import controls as campaign_controls
from apps.api.campaigns import scheduling
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
from apps.api.core.errors import ProblemError
from apps.api.db.ownership import assert_visible
from apps.api.ingest.service import normalize_phone

IST: Final = ZoneInfo("Asia/Kolkata")

#: The most rows one Pip contact action carries. A longer list is the campaign screen's
#: upload, where the person sees the file they chose; past this the model would be
#: copying a spreadsheet into its own output, which is slow, costly and easy to get wrong.
MAX_CONTACTS_PER_ACTION: Final = 100

_HHMM: Final = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DAY_WORDS: Final = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_BILLED_PER_MINUTE: Final = (
    "Calls are billed per minute at your plan's rate — see Credits & billing for the amount."
)
_ID: Final = {"type": "string", "description": "The campaign's id, from `campaigns_list`."}


async def _campaign(session: AsyncSession, campaign_id: UUID) -> tuple[str, str]:
    """The campaign's name and status; a 404 for one this account cannot see (RLS)."""
    row = (
        await session.execute(
            text("SELECT name, status FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    return strip_invisible(str(row[0])), str(row[1])


def _gap_words(minutes: int) -> str:
    if minutes % 1440 == 0:
        return "1 day" if minutes == 1440 else f"{minutes // 1440} days"
    if minutes % 60 == 0:
        return "1 hour" if minutes == 60 else f"{minutes // 60} hours"
    return f"{minutes} min"


def _retry_words(policy: object) -> str:
    view = campaigns_service.retry_policy_view(policy)
    if view["max_attempts"] == 1:
        return "1 try"
    gaps = " then ".join(_gap_words(gap) for gap in view["gaps_minutes"])
    return f"{view['max_attempts']} tries, {gaps} apart"


def _hours_words(hours: Mapping[str, Any] | None) -> str:
    return "the whole allowed window" if not hours else f"{hours['start']} to {hours['end']} IST"


# =========================================================================================
# campaign_edit (immediate, Undo)
# =========================================================================================

#: The draft columns this tool may change, in the order the card lists them.
_EDITED: Final = ("name", "agent_id", "concurrency", "calling_hours", "retry_policy")


class _EditArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    name: Annotated[str, Field(min_length=2, max_length=120)] | None = None
    agent_id: UUID | None = None
    concurrency: Annotated[int, Field(ge=1, le=10)] | None = None
    #: "HH:MM-HH:MM" IST, or "all" for the whole allowed window.
    hours: str | None = None
    tries: Annotated[int, Field(ge=1, le=campaigns_service.MAX_RETRY_ATTEMPTS)] | None = None
    gaps_minutes: list[int] | None = None


def _hours_change(raw: str) -> dict[str, str] | None:
    value = raw.strip().lower()
    if value in ("all", "default"):
        return None
    start, _, end = value.partition("-")
    if not (_HHMM.match(start.strip()) and _HHMM.match(end.strip())):
        raise WriteRefusedError("`hours` is like 10:00-18:00 (India time), or `all`")
    return {"start": start.strip(), "end": end.strip()}


async def _snapshot(session: AsyncSession, campaign_id: UUID, *, lock: bool) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT status, name, agent_id, concurrency, calling_hours, retry_policy "
                "FROM campaigns WHERE id = :cid" + (" FOR UPDATE" if lock else "")
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    return {
        "status": str(row[0]),
        "name": str(row[1]),
        "agent_id": str(row[2]),
        "concurrency": int(row[3]),
        "calling_hours": row[4],
        "retry_policy": row[5],
    }


def _edit_changes(parsed: _EditArgs, current: Mapping[str, Any]) -> dict[str, Any]:
    """The columns to write, validated by the services the PATCH route uses."""
    changes: dict[str, Any] = {}
    if parsed.name is not None:
        changes["name"] = strip_invisible(parsed.name.strip())
    if parsed.agent_id is not None:
        changes["agent_id"] = parsed.agent_id
    if parsed.concurrency is not None:
        changes["concurrency"] = parsed.concurrency
    if parsed.hours is not None:
        hours = _hours_change(parsed.hours)
        changes["calling_hours"] = (
            None if hours is None else campaigns_service.validated_window(hours)
        )
    if parsed.tries is not None or parsed.gaps_minutes is not None:
        view = campaigns_service.retry_policy_view(current["retry_policy"])
        tries = parsed.tries or view["max_attempts"]
        gaps = parsed.gaps_minutes
        if gaps is None:
            # Keeping the gaps already chosen, cut or padded with the last one, so "try
            # five times" needs no second question about the waits.
            known = view["gaps_minutes"] or [campaigns_service.RETRY_GAP_CHOICES[2]]
            gaps = [known[min(i, len(known) - 1)] for i in range(tries - 1)]
        try:
            changes["retry_policy"] = campaigns_service.validated_retry_policy(tries, gaps)
        except ProblemError as exc:
            raise WriteRefusedError(
                f"tries is 1 to {campaigns_service.MAX_RETRY_ATTEMPTS} and gaps_minutes has "
                "one wait per retry, each one of "
                + ", ".join(str(g) for g in campaigns_service.RETRY_GAP_CHOICES)
            ) from exc
    if not changes:
        raise WriteRefusedError("name at least one setting to change")
    return changes


def _setting_words(column: str, value: Any, agent_names: Mapping[str, str]) -> str:
    if column == "name":
        return f"name “{value}”"
    if column == "agent_id":
        return f"agent “{agent_names.get(str(value), 'unknown')}”"
    if column == "concurrency":
        return f"{value} call(s) at once"
    if column == "calling_hours":
        return f"calls {_hours_words(value)}"
    return f"no answer: {_retry_words(value)}"


async def _agent_names(session: AsyncSession, ids: list[str]) -> dict[str, str]:
    rows = await session.execute(
        text("SELECT id, name FROM agents WHERE id = ANY(:ids)"),
        {"ids": [UUID(i) for i in ids]},
    )
    return {str(r[0]): strip_invisible(str(r[1])) for r in rows.all()}


async def _plan_edit(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_EditArgs, args)
    current = await _snapshot(session, parsed.campaign_id, lock=False)
    if current["status"] != "draft":
        raise WriteRefusedError(
            f"“{strip_invisible(current['name'])}” is {current['status']}; only a draft can be "
            "changed (cancel a scheduled start first, or copy it with campaign_clone)"
        )
    if parsed.agent_id is not None:
        await assert_visible(session, "agent", parsed.agent_id)
    changes = _edit_changes(parsed, current)
    names = await _agent_names(
        session, [current["agent_id"], *([str(parsed.agent_id)] if parsed.agent_id else [])]
    )
    was = [_setting_words(c, current[c], names) for c in _EDITED if c in changes]
    becomes = [_setting_words(c, changes[c], names) for c in _EDITED if c in changes]
    return Plan(
        object_id=str(parsed.campaign_id),
        title="Change this draft campaign",
        summary=f"On “{strip_invisible(current['name'])}”: " + "; ".join(becomes) + ".",
        current="; ".join(was),
        proposed="; ".join(becomes),
        cost=None,
        reversal="Undo puts the earlier settings back while it is still a draft.",
        args=parsed.model_dump(mode="json", exclude_none=True),
    )


async def _execute_edit(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`controls.update_draft` — `PATCH /v1/campaigns/{id}`'s call, with the route's own
    validators for the window and the retry policy."""
    del actor
    parsed = parse_args(_EditArgs, args)
    current = await _snapshot(session, parsed.campaign_id, lock=False)
    written = await campaign_controls.update_draft(
        session, campaign_id=parsed.campaign_id, changes=_edit_changes(parsed, current)
    )
    return Executed(
        applied=bool(written),
        detail="Saved. It is still a draft and calls nobody until it is launched.",
        audit_summary={"fields": written},
    )


async def _capture_edit(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    del actor
    return await _snapshot(session, UUID(str(args["campaign_id"])), lock=False)


async def _invert_edit(session: AsyncSession, actor: ToolActor, record: UndoRecord) -> str:
    del actor
    campaign_id = UUID(record.object_id)
    now = await _snapshot(session, campaign_id, lock=True)
    if now != dict(record.result_state):
        raise UndoRefusedError(
            "that campaign has been changed or launched since, so it was left as it is"
        )
    prior = record.prior_state
    await campaign_controls.update_draft(
        session,
        campaign_id=campaign_id,
        changes={
            "name": prior["name"],
            "agent_id": UUID(str(prior["agent_id"])),
            "concurrency": prior["concurrency"],
            "calling_hours": prior["calling_hours"],
            "retry_policy": prior["retry_policy"],
        },
    )
    return "The campaign's earlier settings are back."


CAMPAIGN_EDIT: Final = ActionTool(
    name="campaign_edit",
    tier="immediate",
    undo=Undo(capture=_capture_edit, invert=_invert_edit),
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.updated",
    where="on the campaign's Edit page",
    schema=action_schema(
        "campaign_edit",
        "Change a DRAFT campaign's name, agent, calls at once, calling hours or how often "
        "each person is tried. Leave out what stays." + DOES_IT,
        {
            "campaign_id": _ID,
            "name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "agent_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "concurrency": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "description": "Calls at once, 1 to 10.",
            },
            "hours": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "India time like 10:00-18:00, or `all` for the whole window.",
            },
            "tries": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "description": "Tries per person when nobody answers, 1 to 5.",
            },
            "gaps_minutes": {
                "anyOf": [{"type": "array", "items": {"type": "integer"}}, {"type": "null"}],
                "description": "One wait per retry: 15, 30, 60, 120, 240 or 1440.",
            },
        },
    ),
    plan=_plan_edit,
    execute=_execute_edit,
)


# =========================================================================================
# campaign_repeat (confirm)
# =========================================================================================


class _RepeatArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    days: Annotated[list[Annotated[int, Field(ge=1, le=7)]], Field(min_length=1, max_length=7)]
    at: str
    until: date | None = None


def _until_instant(day: date | None) -> datetime | None:
    """The end of that India day, as the screen's "Ends on" means it."""
    if day is None:
        return None
    return datetime.combine(day + timedelta(days=1), time(0), tzinfo=IST).astimezone(UTC)


async def _plan_repeat(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    parsed = parse_args(_RepeatArgs, args)
    if not _HHMM.match(parsed.at.strip()):
        raise WriteRefusedError("`at` is an India time like 10:30")
    name, status = await _campaign(session, parsed.campaign_id)
    if status not in ("draft", "scheduled"):
        raise WriteRefusedError(f"“{name}” is {status}; only a draft or scheduled one can repeat")
    days = sorted(set(parsed.days))
    words = ", ".join(_DAY_WORDS[d - 1] for d in days)
    ends = f" until {parsed.until:%d %b %Y}" if parsed.until else " until you stop it"
    blockers = await campaigns_service.launch_blockers(
        session, tenant_id=actor.tenant_id, campaign_id=parsed.campaign_id
    )
    warning = (
        " Right now it could not start: " + "; ".join(b.reason for b in blockers) + "."
        if blockers
        else ""
    )
    return Plan(
        object_id=str(parsed.campaign_id),
        title="Repeat this campaign",
        summary=(
            f"Start “{name}” every {words} at {parsed.at.strip()} IST{ends}, calling the "
            f"people on it not yet reached. Every launch check runs again each time.{warning}"
        ),
        current=status,
        proposed=f"Every {words} at {parsed.at.strip()} IST",
        cost=_BILLED_PER_MINUTE,
        reversal="Stop the repeat on the campaign's screen. Calls already placed stay placed.",
        args={
            "campaign_id": str(parsed.campaign_id),
            "days": days,
            "at": parsed.at.strip(),
            "until": parsed.until.isoformat() if parsed.until else None,
        },
    )


async def _execute_repeat(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`scheduling.schedule_recurrence` — `POST /v1/campaigns/{id}/recurrence`'s call."""
    parsed = parse_args(_RepeatArgs, args)
    result = await scheduling.schedule_recurrence(
        session,
        tenant_id=actor.tenant_id,
        campaign_id=parsed.campaign_id,
        days=parsed.days,
        at=datetime.strptime(parsed.at.strip(), "%H:%M").time(),
        until=_until_instant(parsed.until),
    )
    first = result.next_occurrence_at.astimezone(IST).strftime("%a %d %b, %H:%M IST")
    return Executed(
        applied=True,
        detail=f"It repeats; the next start is {first}.",
        audit_summary={
            "days": list(result.days),
            "at_ist": parsed.at.strip(),
            "until": result.until.isoformat() if result.until else None,
            "next_occurrence": result.next_occurrence_at.isoformat(),
        },
    )


CAMPAIGN_REPEAT: Final = ActionTool(
    name="campaign_repeat",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.recurrence_set",
    where="on the campaign's own screen",
    schema=action_schema(
        "campaign_repeat",
        "Propose starting a draft or scheduled campaign on the same weekdays and time every "
        "week; it replaces a one-time start." + PROPOSES_ONLY,
        {
            "campaign_id": _ID,
            "days": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Weekdays, 1 Monday to 7 Sunday.",
            },
            "at": {"type": "string", "description": "India time like 10:30."},
            "until": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "Last day YYYY-MM-DD, or null until stopped.",
            },
        },
    ),
    plan=_plan_repeat,
    execute=_execute_repeat,
)


# =========================================================================================
# campaign_stop and campaign_delete (confirm)
# =========================================================================================


class _IdArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID


async def _waiting(session: AsyncSession, campaign_id: UUID) -> int:
    return int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :cid "
                    "AND status = 'pending'"
                ),
                {"cid": campaign_id},
            )
        ).scalar()
        or 0
    )


async def _plan_stop(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_IdArgs, args)
    name, status = await _campaign(session, parsed.campaign_id)
    if status not in ("running", "paused", "scheduled"):
        raise WriteRefusedError(
            f"“{name}” is {status}; a draft is removed with campaign_delete"
            if status == "draft"
            else f"“{name}” is {status}, so there is nothing to stop"
        )
    left = await _waiting(session, parsed.campaign_id)
    return Plan(
        object_id=str(parsed.campaign_id),
        title="Stop this campaign for good",
        summary=(
            f"End “{name}”: the {left} people not yet called are never called by it, and any "
            "repeat ends. A call already ringing finishes."
        ),
        current=status,
        proposed="stopped",
        cost=None,
        reversal="This cannot be undone. Copy the campaign to call the same people later.",
        args={"campaign_id": str(parsed.campaign_id)},
    )


async def _execute_stop(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`controls.stop_campaign` — `POST /v1/campaigns/{id}/stop`'s call."""
    del actor
    parsed = parse_args(_IdArgs, args)
    moved = await campaign_controls.stop_campaign(session, campaign_id=parsed.campaign_id)
    return Executed(
        applied=moved,
        detail="Stopped; nobody else on its list is called." if moved else "Already stopped.",
        audit_summary={"moved": moved},
    )


CAMPAIGN_STOP: Final = ActionTool(
    name="campaign_stop",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.stopped",
    where="on the campaign's own screen",
    schema=action_schema(
        "campaign_stop",
        "Propose ending a running, paused or scheduled campaign for good. To stop for now: "
        "`campaign_pause`." + PROPOSES_ONLY,
        {"campaign_id": _ID},
    ),
    plan=_plan_stop,
    execute=_execute_stop,
)


async def _plan_delete(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_IdArgs, args)
    name, status = await _campaign(session, parsed.campaign_id)
    if status != "draft":
        raise WriteRefusedError(
            f"“{name}” is {status}; only a draft can be deleted, the others are stopped with "
            "campaign_stop"
        )
    contacts = int(
        (
            await session.execute(
                text("SELECT count(*) FROM campaign_contacts WHERE campaign_id = :cid"),
                {"cid": parsed.campaign_id},
            )
        ).scalar()
        or 0
    )
    return Plan(
        object_id=str(parsed.campaign_id),
        title="Delete this draft campaign",
        summary=(
            f"Delete the draft “{name}” and its list of {contacts} people. If it called "
            "anyone before, it is kept as stopped instead, so those calls keep their campaign."
        ),
        current="draft",
        proposed="deleted",
        cost=None,
        reversal="This cannot be undone.",
        args={"campaign_id": str(parsed.campaign_id)},
    )


async def _execute_delete(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`controls.delete_draft` — `DELETE /v1/campaigns/{id}`'s call."""
    del actor
    parsed = parse_args(_IdArgs, args)
    outcome = await campaign_controls.delete_draft(session, campaign_id=parsed.campaign_id)
    return Executed(
        applied=True,
        detail="The draft is deleted." if outcome == "deleted" else "It is kept as stopped.",
        audit_summary={"outcome": outcome, "from": "draft"},
    )


CAMPAIGN_DELETE: Final = ActionTool(
    name="campaign_delete",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.deleted",
    where="on the Campaigns screen",
    schema=action_schema(
        "campaign_delete",
        "Propose deleting a draft campaign and its list. A launched one: `campaign_stop`."
        + PROPOSES_ONLY,
        {"campaign_id": _ID},
    ),
    plan=_plan_delete,
    execute=_execute_delete,
)


# =========================================================================================
# campaign_contacts_add and campaign_contacts_remove (confirm)
# =========================================================================================


class _Contact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: Annotated[str, Field(max_length=40)]
    name: Annotated[str, Field(max_length=120)] | None = None


class _AddArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    contacts: Annotated[list[_Contact], Field(min_length=1, max_length=MAX_CONTACTS_PER_ACTION)]


async def _pre_launch(session: AsyncSession, campaign_id: UUID, *, verb: str) -> str:
    name, status = await _campaign(session, campaign_id)
    if status not in ("draft", "scheduled"):
        raise WriteRefusedError(f"“{name}” is {status}; people are {verb} only before it starts")
    return name


async def _plan_add(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    """The numbers are checked here as the upload checks them, so the card's count is the
    count that will be added; the rows are the person's own list, never a caller's words."""
    del actor
    parsed = parse_args(_AddArgs, args)
    name = await _pre_launch(session, parsed.campaign_id, verb="added")
    usable = [c for c in parsed.contacts if normalize_phone(c.phone) is not None]
    if not usable:
        raise WriteRefusedError("none of those is a phone number that can be called")
    shown = ", ".join(strip_invisible(c.name or "unnamed") for c in usable[:5])
    more = f" and {len(usable) - 5} more" if len(usable) > 5 else ""
    return Plan(
        object_id=str(parsed.campaign_id),
        title=f"Add {len(usable)} people to “{name}”",
        summary=(
            f"Add {len(usable)} people from your list to “{name}”: {shown}{more}. Numbers "
            "already on it, outside India or not valid are left out. Nobody is called until "
            "it is launched."
        ),
        current=None,
        proposed=f"{len(usable)} people added",
        cost=None,
        reversal="You can take them off again before it starts calling.",
        args={
            "campaign_id": str(parsed.campaign_id),
            "contacts": [c.model_dump(exclude_none=True) for c in usable],
        },
    )


async def _execute_add(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`campaigns.service.add_contacts` — `POST /v1/campaigns/{id}/contacts`'s call."""
    parsed = parse_args(_AddArgs, args)
    result = await campaigns_service.add_contacts(
        session,
        tenant_id=actor.tenant_id,
        campaign_id=parsed.campaign_id,
        contacts=[{"phone": c.phone, "name": c.name} for c in parsed.contacts],
    )
    skipped = sum(int(v) for k, v in result.items() if k != "added")
    return Executed(
        applied=bool(result["added"]),
        detail=f"Added {result['added']}; left out {skipped}.",
        audit_summary={"from": "pip", **{k: int(v) for k, v in result.items()}},
    )


CAMPAIGN_CONTACTS_ADD: Final = ActionTool(
    name="campaign_contacts_add",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.contacts_added",
    where="on the campaign's own screen",
    schema=action_schema(
        "campaign_contacts_add",
        "Propose adding people from a list the person pasted or attached (up to 100) to a "
        "draft or scheduled campaign. Leads already in the account: `campaign_add_leads`."
        + PROPOSES_ONLY,
        {
            "campaign_id": _ID,
            "contacts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "phone": {"type": "string"},
                        "name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    },
                    "required": ["phone", "name"],
                    "additionalProperties": False,
                },
            },
        },
    ),
    plan=_plan_add,
    execute=_execute_add,
)


class _RemoveArgs(BaseModel):
    """`who` from the model; `contact_ids` is the planner's own canonical form, which the
    confirm and the Approvals preview plan again (the model-facing schema has no such
    argument, so only a card this planner drew can carry it)."""

    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    who: (
        Annotated[
            list[Annotated[str, Field(min_length=1, max_length=120)]],
            Field(min_length=1, max_length=MAX_CONTACTS_PER_ACTION),
        ]
        | None
    ) = None
    contact_ids: (
        Annotated[list[UUID], Field(min_length=1, max_length=MAX_CONTACTS_PER_ACTION)] | None
    ) = None


_UNTRIED: Final = (
    "SELECT id, name FROM campaign_contacts WHERE campaign_id = :cid "
    "AND attempts = 0 AND status = 'pending' AND ({match}) ORDER BY created_at, id LIMIT :cap"
)


async def _plan_remove(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    """Each entry is a name or a number the person gave; it matches untried contacts by
    exact name (any case) or the same number. The matched ids are frozen into the card, so
    confirming removes exactly the people it listed, never someone added since."""
    del actor
    parsed = parse_args(_RemoveArgs, args)
    if (parsed.who is None) == (parsed.contact_ids is None):
        raise WriteRefusedError("give `who`: the names or numbers to take off")
    name = await _pre_launch(session, parsed.campaign_id, verb="taken off")
    params: dict[str, Any] = {"cid": parsed.campaign_id, "cap": MAX_CONTACTS_PER_ACTION}
    if parsed.contact_ids is not None:
        match = "id = ANY(:ids)"
        params["ids"] = parsed.contact_ids
    else:
        assert parsed.who is not None
        match = "phone_e164 = ANY(:phones) OR lower(name) = ANY(:names)"
        params["phones"] = [p for p in (normalize_phone(w) for w in parsed.who) if p]
        params["names"] = [w.strip().lower() for w in parsed.who]
    rows = (await session.execute(text(_UNTRIED.format(match=match)), params)).all()
    if not rows:
        raise WriteRefusedError(
            "nobody waiting on that campaign matches those names or numbers; people already "
            "called stay on it"
        )
    shown = ", ".join(strip_invisible(str(r[1] or "unnamed")) for r in rows[:5])
    more = f" and {len(rows) - 5} more" if len(rows) > 5 else ""
    return Plan(
        object_id=str(parsed.campaign_id),
        title=f"Take {len(rows)} people off “{name}”",
        summary=f"Take {shown}{more} off “{name}” before it calls them.",
        current=None,
        proposed=f"{len(rows)} people removed",
        cost=None,
        reversal="Add them again from the list or the leads before it starts.",
        args={"campaign_id": str(parsed.campaign_id), "contact_ids": [str(r[0]) for r in rows]},
    )


async def _execute_remove(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`controls.remove_contacts` — `POST /v1/campaigns/{id}/contacts/remove`'s call."""
    del actor
    parsed = parse_args(_RemoveArgs, args)
    assert parsed.contact_ids is not None  # the planner always freezes them
    removed = await campaign_controls.remove_contacts(
        session, campaign_id=parsed.campaign_id, contact_ids=parsed.contact_ids
    )
    return Executed(
        applied=bool(removed),
        detail=f"Took {removed} off the campaign.",
        audit_summary={"removed": removed},
    )


CAMPAIGN_CONTACTS_REMOVE: Final = ActionTool(
    name="campaign_contacts_remove",
    tier="confirm",
    undo=None,
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.contacts_removed",
    where="on the campaign's own screen",
    schema=action_schema(
        "campaign_contacts_remove",
        "Propose taking people off a campaign before it calls them, by the names or numbers "
        "the person gave." + PROPOSES_ONLY,
        {
            "campaign_id": _ID,
            "who": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Names or phone numbers, as the person said them.",
            },
        },
    ),
    plan=_plan_remove,
    execute=_execute_remove,
)


#: Registration order is wire order: APPEND only.
CAMPAIGN_ACTIONS: Final[tuple[ActionTool, ...]] = (
    CAMPAIGN_EDIT,
    CAMPAIGN_REPEAT,
    CAMPAIGN_STOP,
    CAMPAIGN_DELETE,
    CAMPAIGN_CONTACTS_ADD,
    CAMPAIGN_CONTACTS_REMOVE,
)
