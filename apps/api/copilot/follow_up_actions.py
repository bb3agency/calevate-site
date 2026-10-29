"""Pip builds and runs Follow-ups (D-940), area `leads`.

Reads: `follow_ups_list` (the account's Follow-ups, the ready-made ones and what steps may
name: calling agents with their outcome keys, approved WhatsApp messages, after-call actions,
and how a definition is written) and `follow_up_read` (one, with its steps, problems, counts
and recent runs). Both `leads:read`, client realm only, like the screen.

Actions, all `confirm` and all `leads:dispatch` (the permission every `/v1/follow-ups` write
declares), each calling the function its route calls (`follow_ups/service.py`):

* `follow_up_draft` — a new draft, or a rewrite of an existing one, from the person's
  sentence or a ready-made one. The planner runs the server's own checks
  (`definition.parse_steps`, `shape_problems`, `service.problems_of`) and refuses with every
  problem, so Pip fixes the call before the person sees a card. An id the account does not
  have is one of those problems, which is what stops an invented agent or template.
* `follow_up_publish`, `follow_up_pause`, `follow_up_resume`, `follow_up_turn_off`. Pause and
  resume undo each other through the activity log; turning off stops the runs going, which
  no inverse brings back, and a published version is permanent, so neither has an Undo.
* `follow_up_start` — a plan over leads (`plans.set_action_tool`), any size: the same plan
  `POST /v1/follow-ups/{id}/start` builds and approves for more than 200 leads.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot import plans
from apps.api.copilot.actions import (
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
from apps.api.copilot.lens_args import LEAD_LENS_SCHEMA
from apps.api.copilot.set_actions import LEAD_IDS_SCHEMA, chosen_leads
from apps.api.copilot.tools import ReadTool, ToolContext, _clean
from apps.api.core.errors import ProblemError
from apps.api.follow_ups import definition as d
from apps.api.follow_ups import runner, service, starters

_WHERE: Final = "on the Follow-ups screen"
_PERMISSION: Final = "leads:dispatch"
_RUNS_SHOWN: Final = 10
_BILLED: Final = "Calls it places are billed per minute at your plan's rate."
#: Our own call outcomes (`calls.outcome_tag`), which every agent's `decide` can name.
_CALL_OUTCOMES: Final = ("answered", "missed", "call_back_booked", "transferred", "hung_up_early")

_STATUS_WORDS: Final = {"draft": "Draft", "live": "On", "paused": "Paused", "off": "Off"}

#: What a `needs` entry of a ready-made one asks of the account, and how to meet it.
_NEEDS: Final = {
    "outbound_agent": "a published agent that makes calls (agents_do agent_create, agent_publish)",
    "whatsapp_template": "an approved WhatsApp message (the WhatsApp screen)",
    "team_address": "a confirmed team alert email (team_do team_alert_contact)",
}

#: How a definition is written, returned by `follow_ups_list` and with every refusal of a
#: draft rather than carried in the tool array, which every request pays for.
FORMAT: Final = (
    "How to write one (follow_up_draft):\n"
    'trigger: {"kind":"new_lead","source_ids":null} | {"kind":"call_ended","agent_ids":null,'
    '"calls":"inbound|outbound|both","outcomes":["missed"]} | {"kind":"manual"} | '
    '{"kind":"lead_date","field":"visit_date","offset_days":-1,"at":"10:00"}; any may add '
    '"only_if":{"lead_status":[...],"source_ids":[...] (new_lead only),'
    '"field":{"key":"...","equals":"..."}}.\n'
    'steps: run in order, each {"id":"s1","kind":...}; an exit names a LATER step id, or null '
    "to end.\n"
    "- call: agent_id (null: the lead's own agent), wait_minutes 0-1440, retries 0-3, "
    "retry_minutes 10-1440, next {answered, not_reached}\n"
    "- decide: on {<outcome key>: step}, other; needs a call before it (or a call_ended "
    "trigger)\n"
    "- wait: one of minutes, hours, days; or until_field (+offset_days, at HH:MM); next\n"
    "- whatsapp: template_id, values [{source: lead_field (+key) | lead_name | agent_name | "
    "business_name | text (+text)}] one per blank; next {sent, not_sent}\n"
    "- assign: user_id; next\n"
    "- set_status: status contacted|interested|hot|won|lost; next\n"
    "- tell_team: contact_id (null: the default address), why (up to 120 characters); next; "
    "needs a call before it\n"
    "- action: action_id; next {done, failed}; needs a call before it\n"
    "- end: goal true|false\n"
    "settings: goal (an outcome key a decide checks), stop_on_reply, stop_on_won_lost, again "
    "never|after_last|after_30_days, max_days 1-30, starts_per_hour.\n"
    "Ids: agents, messages and actions as listed here; teammates: team_find team_members; "
    "lead sources: integrations_find integrations_status. Never invent one."
)

_FOLLOW_UP_ID: Final = {"type": "string", "description": "Its id from follow_ups_list."}
_NULLABLE_STR: Final = {"anyOf": [{"type": "string"}, {"type": "null"}]}


def _status(row: service.Row) -> str:
    word = _STATUS_WORDS.get(row.status, row.status)
    if row.live_number is not None:
        word += f" (version {row.live_number})"
    if row.has_unpublished_changes and row.status != "draft":
        word += ", unpublished changes"
    return word


def _step_lines(steps: Sequence[d.AnyStep], names: d.Names) -> str:
    return "\n".join(f"{n}. {d.summary(step, names)}" for n, step in enumerate(steps, 1))


def _has_call(steps: Sequence[d.AnyStep]) -> bool:
    return any(isinstance(step, d.CallStep) for step in steps)


async def _row(session: AsyncSession, raw: Any) -> service.Row:
    """The Follow-up `raw` names, or a refusal pointing at the read that lists them."""
    try:
        return await service.get(session, UUID(str(raw)))
    except (ValueError, ProblemError):
        raise WriteRefusedError(
            "`follow_up_id` is not a Follow-up of this account; see follow_ups_list"
        ) from None


def _problem_text(problems: Sequence[d.Problem]) -> str:
    return "; ".join(
        f"{p.step_id or 'trigger/settings'} ({p.code}): {p.message.rstrip('.')}" for p in problems
    )


# --- follow_ups_list (read) ----------------------------------------------------------


async def _ingredients(session: AsyncSession) -> list[str]:
    from apps.api.agents.call_outcomes import outcomes_in_use
    from apps.api.whatsapp import templates

    lines = ["What steps can name, each [id]:"]
    agents = (
        await session.execute(
            text(
                "SELECT id, name, direction, engine_agent_ref, business_outcomes FROM agents "
                "WHERE deleted_at IS NULL AND archived_at IS NULL ORDER BY created_at"
            )
        )
    ).all()
    for agent in agents:
        calls = str(agent[2]) in ("outbound", "both")
        state = ("calls" if agent[3] else "calls once published") if calls else "answers only"
        keys = ", ".join(o.key for o in outcomes_in_use(agent[4])[0])
        lines.append(f"- agent [{agent[0]}] {_clean(str(agent[1]))} ({state}); outcomes: {keys}")
    lines.append(f"- call outcomes any decide may name: {', '.join(_CALL_OUTCOMES)}")
    messages = (
        await session.execute(
            text(
                "SELECT id, name, body FROM whatsapp_templates WHERE status = 'approved' "
                "ORDER BY name LIMIT 50"
            )
        )
    ).all()
    for message in messages:
        blanks = len(set(templates.blanks(str(message[2]))))
        lines.append(
            f"- WhatsApp message [{message[0]}] {_clean(str(message[1]))}, {blanks} blank(s)"
        )
    if not messages:
        lines.append("- no approved WhatsApp message yet, so no whatsapp step can be published")
    actions = (
        await session.execute(
            text("SELECT id, name FROM action_tools WHERE enabled ORDER BY name LIMIT 50")
        )
    ).all()
    lines += [f"- after-call action [{a[0]}] {_clean(str(a[1]))}" for a in actions]
    return lines


async def _follow_ups_list(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`GET /v1/follow-ups` and `GET /v1/follow-ups/starters`, with what steps may name."""
    del context, args
    rows = await service.list_all(session)
    counts = await service.counts(session, [r.id for r in rows])
    lines = [f"{len(rows)} Follow-up(s), each [id]:" if rows else "No Follow-ups yet."]
    for row in rows:
        c = counts[row.id]
        lines.append(
            f"- [{row.id}] {_clean(row.name)} · {_status(row)} · {d.starts_when(row.trigger)} · "
            f"{c.running + c.waiting} going, {c.goal_30d} reached the goal in 30 days"
        )
    lines.append("Ready-made (follow_up_draft starter):")
    for starter in await starters.for_account(session):
        if not starter.available:
            state = "already made"
        elif starter.needs:
            state = "needs " + "; ".join(_NEEDS[need] for need in starter.needs)
        else:
            state = "ready"
        lines.append(f"- {starter.key}: {starter.name} ({state})")
    lines += await _ingredients(session)
    lines.append(FORMAT)
    lines.append(f"They are listed {_WHERE}.")
    return "\n".join(lines)


FOLLOW_UPS_LIST: Final = ReadTool(
    name="follow_ups_list",
    description=(
        "The account's Follow-ups with ids, the ready-made ones, the agents, WhatsApp messages "
        "and actions steps may name, and how to write steps."
    ),
    parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    permission="leads:read",
    run=_follow_ups_list,
)


# --- follow_up_read (read) -----------------------------------------------------------


def _step_json(step: d.AnyStep) -> str:
    """The step as stored, so Pip can rewrite it exactly; client-written text cleaned."""
    raw = step.model_dump(mode="json")
    if isinstance(raw.get("why"), str):
        raw["why"] = _clean(raw["why"])
    for value in raw.get("values") or []:
        if isinstance(value.get("text"), str):
            value["text"] = _clean(value["text"])
    return json.dumps(raw, ensure_ascii=False, separators=(",", ":"))


async def _follow_up_read(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`GET /v1/follow-ups/{id}` and the first page of its runs."""
    del context
    try:
        row = await service.get(session, UUID(str(args.get("follow_up_id"))))
    except (ValueError, ProblemError):
        return "No Follow-up with that id in this account; see follow_ups_list."
    names = await service.names(session)
    problems = await service.problems_of(session, row.trigger, row.steps, row.settings)
    c = (await service.counts(session, [row.id]))[row.id]
    trigger = json.dumps(d.dump_trigger(row.trigger), separators=(",", ":"))
    settings = json.dumps(d.dump_settings(row.settings), separators=(",", ":"))
    lines = [
        f"[{row.id}] {_clean(row.name)} · {_status(row)} · {d.starts_when(row.trigger)}",
        f"trigger: {trigger}",
        f"settings: {settings}",
        "Steps" + (" (the draft)" if row.draft is not None else "") + ":",
        *(f"- {d.summary(s, names)} · {_step_json(s)}" for s in row.steps),
        "Problems before it can publish: " + _problem_text(problems)
        if problems
        else "No problems.",
        f"Now: {c.running} running, {c.waiting} waiting; last 30 days: {c.done_30d} finished, "
        f"{c.goal_30d} reached the goal.",
    ]
    views, _cursor = await service.list_runs(
        session, row.id, status=None, cursor=None, limit=_RUNS_SHOWN
    )
    steps = await service.run_steps(session, [v.id for v in views])
    if views:
        lines.append("Latest leads in it:")
    for view in views:
        step = d.step_by_id(steps.get(view.id, []), view.step_id)
        at = d.summary(step, names) if step is not None else view.step_id
        lines.append(
            f"- {_clean(view.lead_name or 'A lead')} · {view.status} · at: {at}"
            + (f" · last: {view.last_result}" if view.last_result else "")
            + (f" · ended: {view.end_reason}" if view.end_reason else "")
        )
    return "\n".join(lines)


FOLLOW_UP_READ: Final = ReadTool(
    name="follow_up_read",
    description="One Follow-up: steps, status, problems, counts and its latest runs.",
    parameters={
        "type": "object",
        "properties": {"follow_up_id": _FOLLOW_UP_ID},
        "required": ["follow_up_id"],
        "additionalProperties": False,
    },
    permission="leads:read",
    run=_follow_up_read,
)


# --- follow_up_draft (confirm) -------------------------------------------------------


class _DraftArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    follow_up_id: UUID | None = None
    name: str | None = Field(default=None, max_length=80)
    starter: str | None = None
    trigger: Any = None
    steps: Any = None
    settings: Any = None


def _json_arg(value: Any) -> Any:
    """An object or list the model sent as JSON text, read as what it holds."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _refuse_problems(problems: Sequence[d.Problem]) -> WriteRefusedError:
    return WriteRefusedError(
        "the draft was not shown to the person because the server found problems: "
        + _problem_text(problems)
        + ". Fix them and call again; if a missing thing is the account's (an agent, a "
        "message, a team address), tell the person what to add.\n" + FORMAT
    )


async def _from_starter(
    session: AsyncSession, key: str
) -> tuple[str, d.AnyTrigger, list[d.AnyStep], d.Settings]:
    found = {s.key: s for s in await starters.for_account(session)}
    starter = found.get(key)
    if starter is None:
        raise WriteRefusedError(
            "`starter` is not a ready-made Follow-up; the keys are: " + ", ".join(found)
        )
    if not starter.available:
        raise WriteRefusedError(
            f"this account already has {starter.name}; open it with follow_up_read instead"
        )
    if starter.needs:
        raise WriteRefusedError(
            f"{starter.name} needs what the account does not have yet: "
            + "; ".join(_NEEDS[need] for need in starter.needs)
            + ". Tell the person, and offer to make it once they have."
        )
    return starter.name, starter.trigger, list(starter.steps), starter.settings


def _parsed(
    raw_trigger: Any, raw_steps: Any, raw_settings: Any
) -> tuple[d.AnyTrigger | None, list[d.AnyStep], d.Settings | None, list[d.Problem]]:
    problems: list[d.Problem] = []
    trigger: d.AnyTrigger | None = None
    settings: d.Settings | None = None
    try:
        trigger = d.load_trigger(raw_trigger)
    except ValidationError:
        problems.append(d.Problem(None, "trigger_invalid", "The trigger could not be read."))
    steps, step_problems = d.parse_steps(raw_steps)
    problems += step_problems
    try:
        settings = d.load_settings(raw_settings)
    except ValidationError:
        problems.append(d.Problem(None, "settings_invalid", "The settings could not be read."))
    return trigger, steps, settings, problems


async def _plan_draft(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_DraftArgs, args)
    existing = None if parsed.follow_up_id is None else await _row(session, parsed.follow_up_id)
    if parsed.starter is not None:
        if existing is not None:
            raise WriteRefusedError("a ready-made one starts a new Follow-up; leave out the id")
        name, trigger, steps, settings = await _from_starter(session, parsed.starter)
        name = (parsed.name or name).strip()
    else:
        if parsed.trigger is None or parsed.steps is None:
            raise WriteRefusedError(
                "give `trigger` and `steps` (or a ready-made `starter`).\n" + FORMAT
            )
        found, steps, found_settings, problems = _parsed(
            _json_arg(parsed.trigger), _json_arg(parsed.steps), _json_arg(parsed.settings)
        )
        if problems or found is None or found_settings is None:
            raise _refuse_problems(problems)
        trigger, settings = found, found_settings
        name = (parsed.name or (existing.name if existing else "")).strip()
        if not name:
            raise WriteRefusedError("give the Follow-up a short `name`")
    problems = await service.problems_of(session, trigger, steps, settings)
    if problems:
        raise _refuse_problems(problems)
    names = await service.names(session)
    when = d.starts_when(trigger)
    if existing is None:
        title, current = "Make a Follow-up", None
        summary = f"“{name}”: {when}. It is saved as a draft; nothing runs until it is published."
    else:
        title = "Rewrite a Follow-up's draft"
        current = _step_lines(existing.steps, names)
        summary = f"“{name}”: {when}. The draft is replaced" + (
            "; the live version keeps running until this is published."
            if existing.live_number
            else "."
        )
    return Plan(
        object_id="" if existing is None else str(existing.id),
        title=title,
        summary=summary,
        current=current,
        proposed=_step_lines(steps, names),
        cost=None,
        reversal="It is a draft: nothing runs until it is published, and it can be changed on "
        "the Follow-ups screen.",
        args={
            "follow_up_id": None if existing is None else str(existing.id),
            "name": name,
            "starter": parsed.starter,
            "trigger": d.dump_trigger(trigger),
            "steps": d.dump_steps(steps),
            "settings": d.dump_settings(settings),
        },
    )


async def _execute_draft(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    trigger = d.load_trigger(args["trigger"])
    steps = d.load_steps(args["steps"])
    settings = d.load_settings(args["settings"])
    if args.get("follow_up_id"):
        row = await service.save_draft(
            session,
            UUID(str(args["follow_up_id"])),
            trigger=trigger,
            steps=steps,
            settings=settings,
            name=str(args["name"]),
        )
        return Executed(
            applied=True,
            detail="The draft is saved. Publish it to put it live.",
            audit_summary={"steps": len(row.steps), "trigger": row.trigger.kind},
            audit_action="follow_up.draft_saved",
        )
    row = await service.create(
        session,
        tenant_id=actor.tenant_id,
        name=str(args["name"]),
        trigger=trigger,
        steps=steps,
        settings=settings,
        starter=args.get("starter"),
        user_id=actor.user_id,
    )
    return Executed(
        applied=True,
        detail="Saved as a draft. Publish it to put it live.",
        audit_summary={
            "steps": len(row.steps),
            "starter": row.starter or "",
            "trigger": row.trigger.kind,
        },
        object_id=str(row.id),
    )


FOLLOW_UP_DRAFT: Final = ActionTool(
    name="follow_up_draft",
    tier="confirm",
    undo=None,
    permission=_PERMISSION,
    object_type="follow_up",
    audit_action="follow_up.created",
    where=_WHERE,
    schema=action_schema(
        "follow_up_draft",
        "A new Follow-up draft from their sentence or a ready-made `starter`, or a rewrite of "
        "a draft (`follow_up_id`). The step format and every id are in follow_ups_list; the "
        "server refuses with its problems, which you fix before the person sees a card."
        + PROPOSES_ONLY,
        {
            "follow_up_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "The Follow-up whose draft to rewrite; null makes a new one.",
            },
            "name": _NULLABLE_STR,
            "starter": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "A ready-made one's key from follow_ups_list.",
            },
            "trigger": {"anyOf": [{"type": "object"}, {"type": "null"}]},
            "steps": {"anyOf": [{"type": "array", "items": {"type": "object"}}, {"type": "null"}]},
            "settings": {"anyOf": [{"type": "object"}, {"type": "null"}]},
        },
    ),
    plan=_plan_draft,
    execute=_execute_draft,
)


# --- publish, pause, resume, turn off (confirm) --------------------------------------


class _OneArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    follow_up_id: UUID


class _PublishArgs(_OneArgs):
    expected_updated_at: datetime | None = None


def _one_schema(name: str, description: str) -> dict[str, Any]:
    return action_schema(name, description + PROPOSES_ONLY, {"follow_up_id": _FOLLOW_UP_ID})


async def _going(session: AsyncSession, row: service.Row) -> int:
    c = (await service.counts(session, [row.id]))[row.id]
    return c.running + c.waiting


async def _plan_publish(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    row = await _row(session, parse_args(_PublishArgs, args).follow_up_id)
    if not row.has_unpublished_changes:
        raise WriteRefusedError(f"nothing new to publish: it is {_status(row)}")
    problems = await service.problems_of(session, row.trigger, row.steps, row.settings)
    if problems:
        raise WriteRefusedError(
            "it cannot be published yet: "
            + _problem_text(problems)
            + ". Fix them with follow_up_draft, or tell the person what the account needs."
        )
    if row.status != "paused" and await service.overlaps(session, row, row.trigger):
        raise WriteRefusedError(
            "another Follow-up that is on already starts for new leads from these sources; "
            "it must be paused or turned off first (follow_up_pause, follow_up_turn_off)"
        )
    names = await service.names(session)
    becomes = "stays paused" if row.status == "paused" else "goes on"
    return Plan(
        object_id=str(row.id),
        title="Publish a Follow-up",
        summary=(
            f"Publish “{row.name}” and it {becomes}: {d.starts_when(row.trigger)}. Leads "
            "already in it keep the version they started on."
        ),
        current=_STATUS_WORDS.get(row.status, row.status),
        proposed=_step_lines(row.steps, names),
        cost=_BILLED if _has_call(row.steps) else None,
        reversal="Pause it or turn it off at any time; calls placed and messages sent cannot "
        "be recalled.",
        args={"follow_up_id": str(row.id), "expected_updated_at": row.updated_at.isoformat()},
    )


async def _execute_publish(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_PublishArgs, args)
    expected = (
        parsed.expected_updated_at or (await service.get(session, parsed.follow_up_id)).updated_at
    )
    row = await service.publish(
        session,
        parsed.follow_up_id,
        tenant_id=actor.tenant_id,
        expected_updated_at=expected,
        user_id=actor.user_id,
    )
    state = "It is paused; resume it to start leads." if row.status == "paused" else "It is on."
    return Executed(
        applied=True,
        detail=f"Published as version {row.live_number}. {state}",
        audit_summary={"version": row.live_number or 0, "status": row.status},
    )


FOLLOW_UP_PUBLISH: Final = ActionTool(
    name="follow_up_publish",
    tier="confirm",
    undo=None,
    permission=_PERMISSION,
    object_type="follow_up",
    audit_action="follow_up.published",
    where=_WHERE,
    schema=_one_schema(
        "follow_up_publish", "Publish a Follow-up's draft so it runs; refused with its problems."
    ),
    plan=_plan_publish,
    execute=_execute_publish,
)


async def _capture_status(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    del actor
    row = await service.get(session, parse_args(_OneArgs, args).follow_up_id)
    return {"status": row.status}


async def _invert_status(session: AsyncSession, actor: ToolActor, record: UndoRecord) -> str:
    """Put the status back through the screen's own pause, resume or turn off, if nobody
    moved it since (the row lock makes the compare and the swap one step)."""
    follow_up_id = UUID(str(record.args["follow_up_id"]))
    try:
        row = await service.get(session, follow_up_id, lock=True)
    except ProblemError:
        raise UndoRefusedError("that Follow-up is gone, so there is nothing to undo") from None
    if row.status != record.result_state.get("status"):
        raise UndoRefusedError("it has been changed since, so it was left as it is now")
    prior = record.prior_state.get("status")
    if prior == "live":
        await service.resume(session, follow_up_id, tenant_id=actor.tenant_id)
        return "It is on again; leads waiting in it carry on."
    if prior == "off":
        await service.turn_off(session, follow_up_id)
        return "It is off again."
    await service.pause(session, follow_up_id)
    return "It is paused again."


#: Pause and resume are each other's inverse.
_STATUS_UNDO: Final = Undo(capture=_capture_status, invert=_invert_status)


async def _plan_pause(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    row = await _row(session, parse_args(_OneArgs, args).follow_up_id)
    if row.status != "live":
        raise WriteRefusedError(f"only a Follow-up that is on can be paused; it is {_status(row)}")
    going = await _going(session, row)
    return Plan(
        object_id=str(row.id),
        title="Pause a Follow-up",
        summary=(
            f"Pause “{row.name}”: no new leads start, the {going} lead(s) in it wait where "
            "they are, and calls it booked are called off until it is resumed."
        ),
        current="On",
        proposed="Paused",
        cost=None,
        reversal="Resume it at any time; Undo resumes it too.",
        args={"follow_up_id": str(row.id)},
    )


async def _execute_pause(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    del actor
    await service.pause(session, parse_args(_OneArgs, args).follow_up_id)
    return Executed(applied=True, detail="Paused.", audit_summary={})


FOLLOW_UP_PAUSE: Final = ActionTool(
    name="follow_up_pause",
    tier="confirm",
    undo=_STATUS_UNDO,
    permission=_PERMISSION,
    object_type="follow_up",
    audit_action="follow_up.paused",
    where=_WHERE,
    schema=_one_schema("follow_up_pause", "Pause a Follow-up that is on; leads wait in place."),
    plan=_plan_pause,
    execute=_execute_pause,
)


async def _plan_resume(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    row = await _row(session, parse_args(_OneArgs, args).follow_up_id)
    if row.status not in ("paused", "off"):
        raise WriteRefusedError(f"only a paused or turned-off one can resume; it is {_status(row)}")
    if row.live_version_id is None:
        raise WriteRefusedError("it was never published; propose follow_up_publish instead")
    live = await runner.version(session, row.live_version_id)
    if await service.overlaps(session, row, live.trigger):
        raise WriteRefusedError(
            "another Follow-up that is on already starts for new leads from these sources; "
            "it must be paused or turned off first"
        )
    if row.status == "paused":
        going = await _going(session, row)
        summary = (
            f"Resume “{row.name}”: new leads start again and the {going} lead(s) waiting in it "
            "carry on, with their calls booked again at once."
        )
    else:
        summary = (
            f"Turn “{row.name}” back on: new leads start again. Leads it stopped when it was "
            "turned off do not restart."
        )
    return Plan(
        object_id=str(row.id),
        title="Turn a Follow-up back on",
        summary=summary,
        current=_STATUS_WORDS[row.status],
        proposed="On",
        cost=_BILLED if _has_call(live.steps) else None,
        reversal="Pause it again at any time; Undo puts it back as it was. Calls placed cannot "
        "be recalled.",
        args={"follow_up_id": str(row.id)},
    )


async def _execute_resume(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    await service.resume(
        session, parse_args(_OneArgs, args).follow_up_id, tenant_id=actor.tenant_id
    )
    return Executed(applied=True, detail="It is on.", audit_summary={})


FOLLOW_UP_RESUME: Final = ActionTool(
    name="follow_up_resume",
    tier="confirm",
    undo=_STATUS_UNDO,
    permission=_PERMISSION,
    object_type="follow_up",
    audit_action="follow_up.resumed",
    where=_WHERE,
    schema=_one_schema("follow_up_resume", "Turn a paused or turned-off Follow-up back on."),
    plan=_plan_resume,
    execute=_execute_resume,
)


async def _plan_turn_off(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    row = await _row(session, parse_args(_OneArgs, args).follow_up_id)
    if row.status not in ("live", "paused"):
        raise WriteRefusedError(
            f"it is not on, so there is nothing to turn off; it is {_status(row)}"
        )
    going = await _going(session, row)
    return Plan(
        object_id=str(row.id),
        title="Turn off a Follow-up",
        summary=f"Turn off “{row.name}”: no new leads start, and the {going} lead(s) in it stop.",
        current=_STATUS_WORDS[row.status],
        proposed="Off",
        cost=None,
        reversal="It can be turned back on, but the leads it stops do not restart.",
        args={"follow_up_id": str(row.id)},
    )


async def _execute_turn_off(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    del actor
    await service.turn_off(session, parse_args(_OneArgs, args).follow_up_id)
    return Executed(applied=True, detail="It is off.", audit_summary={})


FOLLOW_UP_TURN_OFF: Final = ActionTool(
    name="follow_up_turn_off",
    tier="confirm",
    undo=None,
    permission=_PERMISSION,
    object_type="follow_up",
    audit_action="follow_up.turned_off",
    where=_WHERE,
    schema=_one_schema("follow_up_turn_off", "Turn a Follow-up off; the leads in it stop."),
    plan=_plan_turn_off,
    execute=_execute_turn_off,
)


# --- follow_up_start (plan) ----------------------------------------------------------


class _StartChange(BaseModel):
    model_config = ConfigDict(extra="ignore")

    follow_up_id: UUID


async def _live(session: AsyncSession, row: service.Row) -> runner.LiveFollowUp:
    if row.status != "live" or row.live_version_id is None:
        raise WriteRefusedError(
            f"it must be on before leads can start; it is {_status(row)} "
            "(follow_up_publish or follow_up_resume)"
        )
    return await runner.version(session, row.live_version_id)


async def _prepare_start(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> plans.Prepared:
    del actor
    row = await _row(session, args.get("follow_up_id"))
    await _live(session, row)
    targets, lens_text = await chosen_leads(session, args)
    return plans.Prepared(
        targets=targets,
        lens_text=lens_text,
        title=f"Start {len(targets)} leads on a Follow-up",
        why=f"Start them on “{row.name}”",
        change={"follow_up_id": str(row.id)},
    )


async def _exclude_start(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], lead_ids: Sequence[UUID]
) -> dict[UUID, str]:
    del actor
    parsed = _StartChange.model_validate(change)
    rows = await session.execute(
        text(
            "SELECT lead_id FROM follow_up_runs WHERE follow_up_id = :fid "
            "AND lead_id = ANY(:ids) AND status IN ('running', 'waiting')"
        ),
        {"fid": parsed.follow_up_id, "ids": list(lead_ids)},
    )
    return {UUID(str(r[0])): "Already going through it." for r in rows.all()}


async def _estimate_start(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], n: int
) -> plans.Estimate:
    del actor, n
    row = await service.get(session, _StartChange.model_validate(change).follow_up_id)
    live = await _live(session, row)
    if _has_call(live.steps):
        # How many calls a lead gets depends on how each call goes, so no total is given.
        return plans.Estimate(inr=None, note=_BILLED)
    return plans.Estimate(inr=Decimal(0), note="It places no calls.")


async def _run_start(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], lead_id: UUID
) -> plans.TargetOutcome:
    """`service.start_leads` for one lead: the route's function, so a Follow-up turned off
    since the plan refuses here (the worker records the refusal's sentence)."""
    parsed = _StartChange.model_validate(change)
    outcome = await service.start_leads(
        session, parsed.follow_up_id, tenant_id=actor.tenant_id, lead_ids=[lead_id]
    )
    if outcome.started:
        return plans.TargetOutcome("done")
    return plans.TargetOutcome("skipped", "Already in it, or its rules leave this lead out.")


START_LEADS: Final = plans.SetAction(
    target_type="lead",
    prepare=_prepare_start,
    exclude=_exclude_start,
    estimate=_estimate_start,
    run_one=_run_start,
)

FOLLOW_UP_START: Final = plans.set_action_tool(
    name="follow_up_start",
    permission=_PERMISSION,
    object_type="follow_up",
    audit_action="follow_up.started",
    where=_WHERE,
    description=(
        "Start leads on a Follow-up that is on, chosen by `lens` (the filters from "
        "`leads_search`) or the `lead_ids` ticked on screen, any number. The person approves "
        "one plan."
    ),
    properties={
        "follow_up_id": _FOLLOW_UP_ID,
        "lens": LEAD_LENS_SCHEMA,
        "lead_ids": LEAD_IDS_SCHEMA,
    },
    action=START_LEADS,
)


#: Appended to `WRITE_TOOLS` in this order (wire order).
FOLLOW_UP_ACTIONS: Final[tuple[ActionTool, ...]] = (
    FOLLOW_UP_DRAFT,
    FOLLOW_UP_PUBLISH,
    FOLLOW_UP_PAUSE,
    FOLLOW_UP_RESUME,
    FOLLOW_UP_TURN_OFF,
    FOLLOW_UP_START,
)
#: Composed into the CLIENT realm's reads only (`service.realm_read_tools`), like the screen.
FOLLOW_UP_READS: Final[tuple[ReadTool, ...]] = (FOLLOW_UPS_LIST, FOLLOW_UP_READ)

__all__ = [
    "FOLLOW_UPS_LIST",
    "FOLLOW_UP_ACTIONS",
    "FOLLOW_UP_DRAFT",
    "FOLLOW_UP_PAUSE",
    "FOLLOW_UP_PUBLISH",
    "FOLLOW_UP_READ",
    "FOLLOW_UP_READS",
    "FOLLOW_UP_RESUME",
    "FOLLOW_UP_START",
    "FOLLOW_UP_TURN_OFF",
    "FORMAT",
    "START_LEADS",
]
