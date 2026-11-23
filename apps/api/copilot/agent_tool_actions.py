"""Pip's actions on what an agent does in a call and what it writes down (D-893 lane L4):
its in-call actions (the Actions tab) and its lead details (the Lead details screen).

* `agent_action_set`, `agent_action_switch`, `agent_action_remove` — `actions/agent_tools`,
  the functions the Actions tab's Save, switches and Remove call, which re-sync a live
  agent's actions in the same request. Connecting an account (a key, an OAuth sign-in) stays
  on the Connections screen: Pip only points an action at a connection already made.
* `lead_fields_keep_draft`, `lead_fields_reset` — `agents/lead_fields_writes`, the Lead
  details screen's Keep and Start-again buttons.
* `lead_suggestion_answer` — `agents/field_suggestions.accept` / `.dismiss`.

All are `confirm`: an in-call action reaches callers (and an outside address) on a live
agent, lead details change what a live agent asks for from its next call, and none of the
writes has an exact inverse the page offers.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions import agent_tools
from apps.api.actions import service as actions_service
from apps.api.actions.models import ACTION_KINDS
from apps.api.actions.schema import ParamSpec, lead_field_key
from apps.api.agents import field_suggestions, lead_fields_writes
from apps.api.agents import lead_fields as lead_fields_service
from apps.api.campaigns.notes_live import queue_put_live
from apps.api.copilot.actions import (
    PROPOSES_ONLY,
    ActionTool,
    Executed,
    Plan,
    ToolActor,
    WriteRefusedError,
    action_schema,
    agent_name,
    parse_args,
)
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.errors import ProblemError
from apps.api.db.ownership import assert_visible

_ID: Final[dict[str, Any]] = {"type": "string", "description": "The agent's id, never invented."}
_NULLABLE_STR: Final[dict[str, Any]] = {"anyOf": [{"type": "string"}, {"type": "null"}]}


def _json_object(field: str, raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise WriteRefusedError(f"`{field}` is not valid JSON") from exc


# --- agent_action_set -------------------------------------------------------------------


class _ActionSetArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    action_id: UUID | None
    kind: (
        Literal[
            "custom_api", "whatsapp", "calendar", "sheets", "payment_link", "crm", "caller_lookup"
        ]
        | None
    )
    provider: Annotated[str, Field(max_length=40)] | None
    name: Annotated[str, Field(max_length=64)] | None
    description: Annotated[str, Field(max_length=2000)] | None
    pre_call_message: Annotated[str, Field(max_length=200)] | None
    connection_id: UUID | None
    params_json: Annotated[str, Field(max_length=20_000)] | None
    config_json: Annotated[str, Field(max_length=20_000)] | None


def _definition(
    parsed: _ActionSetArgs, current: actions_service.LoadedTool | None
) -> dict[str, Any]:
    """The whole action as it will be stored: what the request names, the rest kept."""

    def pick(value: Any, kept: Any) -> Any:
        return kept if value is None else value

    params = _json_object("params_json", parsed.params_json)
    config = _json_object("config_json", parsed.config_json)
    if params is not None and not isinstance(params, list):
        raise WriteRefusedError("`params_json` must be a JSON list")
    if config is not None and not isinstance(config, dict):
        raise WriteRefusedError("`config_json` must be a JSON object")
    held_credential = (
        None if current is None or current.credential_id is None else str(current.credential_id)
    )
    definition = {
        "kind": pick(parsed.kind, current.kind if current else None),
        "provider": pick(parsed.provider, current.provider if current else None),
        "name": pick(parsed.name, current.name if current else None),
        "description": pick(parsed.description, current.description if current else None),
        # Not Pip's to choose: a new action runs during the call (after-call work is a
        # Follow-up), and an older after-call one keeps running after the call.
        "trigger": current.trigger if current else "during_call",
        "pre_call_message": pick(
            parsed.pre_call_message, current.pre_call_message if current else None
        ),
        "credential_id": pick(
            None if parsed.connection_id is None else str(parsed.connection_id), held_credential
        ),
        "params": pick(params, current.params if current else []),
        "config": pick(config, current.config if current else None),
    }
    missing = [k for k in ("kind", "name", "description", "config") if definition[k] is None]
    if missing:
        # An owner describes what the action should do; the definition is Pip's to write.
        raise WriteRefusedError(
            "a new action needs "
            + ", ".join(f"`{m}`" for m in missing)
            + "; write them from what the person asked for (`config_json` is the kind's "
            "settings) and call again. Ask the person only for a fact only they know, such as "
            "a web address or a template name, in plain words and never for JSON"
        )
    try:
        for param in definition["params"]:
            ParamSpec.model_validate(param)
    except ValidationError as exc:
        paths = sorted(
            {".".join(str(p) for p in error["loc"]) for error in exc.errors() if error["loc"]}
        )
        named = ", ".join(f"`{path}`" for path in paths[:8]) or "an item"
        # A rule across fields (`ParamSpec._coherent`) has no path; its message is ours and
        # names the parameter, never a value.
        rules = "; ".join(e["msg"] for e in exc.errors() if e["type"] == "value_error")
        raise WriteRefusedError(
            f"in `params_json`, {named} was missing or the wrong shape"
            + (f" ({rules})" if rules else "")
            + ". Each item is "
            "{name, source: static|lead_var|ai, value (static), lead_var (lead_var), "
            "type and description (ai), required}; fix it and call again"
        ) from exc
    for key in ("name", "description", "pre_call_message"):
        if isinstance(definition[key], str):
            definition[key] = strip_invisible(definition[key].strip())
    return definition


def _definition_refused(problem: ProblemError) -> WriteRefusedError:
    """A stored-tool rule the definition broke, handed to the model to mend.

    Everything `check_definition` refuses is about the definition Pip wrote (a setting's
    shape, the name's pattern, a provider, during-call versus after-call), so it is a
    `WriteRefusedError` the model corrects inside the turn cap, not a `ProblemError` relayed
    to the owner as final: the console's "check the highlighted settings" names nothing in
    Pip's panel. The per-setting entries carry the field path and our sentence, no value.
    """
    settings = "; ".join(
        f"`{entry.get('field', '')}`: {entry.get('message', '')}"
        for entry in (problem.fields or [])[:8]
    )
    return WriteRefusedError(
        f"{problem.title}: {problem.detail}"
        + (f" ({settings})" if settings else "")
        + (f" {problem.remediation}" if problem.remediation else "")
        + " Fix the definition and call again; ask the person only for a fact only they know",
        plain=problem.title,
    )


async def _check_lead_fields(
    session: AsyncSession, agent_id: UUID, params: list[dict[str, Any]]
) -> None:
    """A `field:<key>` binding names a detail this agent captures, asked at plan time
    because `create_tool`/`update_tool` refuse it only after the owner has confirmed."""
    known = await actions_service.agent_field_keys(session, agent_id=agent_id)
    unknown = sorted(
        {
            key
            for param in params
            if param.get("source") == "lead_var"
            and (key := lead_field_key(param.get("lead_var"))) is not None
            and key not in known
        }
    )
    if unknown:
        raise WriteRefusedError(
            "this agent does not capture "
            + ", ".join(f"`field:{key}`" for key in unknown)
            + "; bind to one of its lead details (`agent_settings` part `lead_fields`) or "
            "let the agent ask (source `ai`)",
            plain="That action uses a detail this agent does not note down.",
        )


async def _plan_action_set(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_ActionSetArgs, args)
    name = await agent_name(session, parsed.agent_id)
    current = None
    if parsed.action_id is not None:
        current = await actions_service.get_agent_tool(
            session, agent_id=parsed.agent_id, tool_id=parsed.action_id
        )
        if current is None:
            raise WriteRefusedError(
                "that `action_id` is not one of this agent's actions; read them with "
                "`agent_settings` part `actions`"
            )
    definition = _definition(parsed, current)
    await assert_visible(
        session,
        "credential",
        None if definition["credential_id"] is None else UUID(definition["credential_id"]),
    )
    try:
        actions_service.check_definition(
            kind=definition["kind"],
            provider=definition["provider"],
            name=definition["name"],
            description=definition["description"],
            trigger=definition["trigger"],
            params=definition["params"],
            config=definition["config"],
            previous=current,
        )
    except ProblemError as problem:
        raise _definition_refused(problem) from problem
    await _check_lead_fields(session, parsed.agent_id, definition["params"])
    when = "during the call" if definition["trigger"] == "during_call" else "after the call"
    return Plan(
        object_id=str(parsed.agent_id),
        title="Change an in-call action" if current else "Add an in-call action",
        summary=(
            f"{'Change' if current else 'Add'} “{definition['name']}” "
            f"({definition['kind']}, {when}) on “{name}”: {definition['description']}"
            + (" Live calls use it at once." if current is None or current.enabled else "")
        ),
        current=None if current is None else f"{current.name}: {current.description}",
        proposed=f"{definition['name']}: {definition['description']}",
        cost=None,
        reversal="Switch it off or remove it on the agent's Actions tab at any time.",
        args={
            "agent_id": str(parsed.agent_id),
            "action_id": None if parsed.action_id is None else str(parsed.action_id),
            **definition,
        },
    )


async def _execute_action_set(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    agent_id = UUID(str(args["agent_id"]))
    credential = None if args.get("credential_id") is None else UUID(str(args["credential_id"]))
    common: dict[str, Any] = {
        "kind": str(args["kind"]),
        "provider": args.get("provider"),
        "name": str(args["name"]),
        "description": str(args["description"]),
        "trigger": str(args["trigger"]),
        "pre_call_message": args.get("pre_call_message"),
        "credential_id": credential,
        "params": list(args["params"]),
        "config": dict(args["config"]),
    }
    if args.get("action_id") is None:
        tool = await agent_tools.add_action(
            session,
            tenant_id=actor.tenant_id,
            agent_id=agent_id,
            impersonating=actor.impersonating,
            **common,
        )
    else:
        tool = await agent_tools.edit_action(
            session,
            agent_id=agent_id,
            tool_id=UUID(str(args["action_id"])),
            impersonating=actor.impersonating,
            **common,
        )
    return Executed(
        applied=True,
        detail=f"“{tool.name}” is saved and {'on' if tool.enabled else 'off'}.",
        audit_summary={
            "action_tool_id": str(tool.id),
            "kind": tool.kind,
            "created": args.get("action_id") is None,
            "enabled": tool.enabled,
        },
    )


AGENT_ACTION_SET: Final = ActionTool(
    name="agent_action_set",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="agent",
    audit_action="action_tool.saved",
    where="on the agent's Actions tab",
    schema=action_schema(
        "agent_action_set",
        "Propose adding (`action_id` null) or changing one of an agent's in-call actions "
        "(send a WhatsApp, book a slot, call a web address...). Null fields keep what the "
        "action has. A wrong shape is refused naming the setting to fix. Connecting an "
        "account is done on the Connections screen; send the person there. Actions run "
        "during the call only: something to do after a call (a thank-you WhatsApp) is a "
        "Follow-up started when a call ends (`follow_up_draft`), and sending call results to "
        "a sheet, a CRM or the person's own system is set up on Integrations." + PROPOSES_ONLY,
        {
            "agent_id": _ID,
            "action_id": {**_NULLABLE_STR, "description": "From `agent_settings` part `actions`."},
            "kind": {"anyOf": [{"type": "string", "enum": list(ACTION_KINDS)}, {"type": "null"}]},
            "provider": _NULLABLE_STR,
            "name": {**_NULLABLE_STR, "description": "lower_snake_case, e.g. send_price_list"},
            "description": {**_NULLABLE_STR, "description": "When the agent should use it."},
            "pre_call_message": {**_NULLABLE_STR, "description": "What the agent says first."},
            "connection_id": {**_NULLABLE_STR, "description": "A connection already made."},
            "params_json": {**_NULLABLE_STR, "description": "The values it sends, JSON list."},
            "config_json": {**_NULLABLE_STR, "description": "The kind's settings, JSON object."},
        },
    ),
    plan=_plan_action_set,
    execute=_execute_action_set,
)


# --- agent_action_switch / agent_action_remove ------------------------------------------


class _SwitchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    action_id: UUID | None
    enabled: bool


async def _one_tool(
    session: AsyncSession, agent_id: UUID, tool_id: UUID
) -> actions_service.LoadedTool:
    tool = await actions_service.get_agent_tool(session, agent_id=agent_id, tool_id=tool_id)
    if tool is None:
        raise WriteRefusedError(
            "that `action_id` is not one of this agent's actions; read them with "
            "`agent_settings` part `actions`"
        )
    return tool


async def _plan_switch(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_SwitchArgs, args)
    name = await agent_name(session, parsed.agent_id)
    word = "on" if parsed.enabled else "off"
    if parsed.action_id is None:
        held = await actions_service.actions_enabled(session, agent_id=parsed.agent_id)
        what, current = f"all of {name}'s in-call actions", "on" if held else "off"
    else:
        tool = await _one_tool(session, parsed.agent_id, parsed.action_id)
        what, current = f"“{tool.name}” on “{name}”", "on" if tool.enabled else "off"
    return Plan(
        object_id=str(parsed.agent_id),
        title=f"Switch {word} an in-call action" if parsed.action_id else f"Switch actions {word}",
        summary=f"Switch {word} {what}. Live calls follow at once.",
        current=current,
        proposed=word,
        cost=None,
        reversal=f"Switch it {'off' if parsed.enabled else 'on'} again on the Actions tab.",
        args={
            "agent_id": str(parsed.agent_id),
            "action_id": None if parsed.action_id is None else str(parsed.action_id),
            "enabled": parsed.enabled,
        },
    )


async def _execute_switch(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    del actor
    parsed = parse_args(_SwitchArgs, args)
    if parsed.action_id is None:
        await agent_tools.switch_all(session, agent_id=parsed.agent_id, enabled=parsed.enabled)
    else:
        await agent_tools.switch_action(
            session, agent_id=parsed.agent_id, tool_id=parsed.action_id, enabled=parsed.enabled
        )
    return Executed(
        applied=True,
        detail=f"Switched {'on' if parsed.enabled else 'off'}.",
        audit_summary={
            "action_tool_id": None if parsed.action_id is None else str(parsed.action_id),
            "enabled": parsed.enabled,
        },
    )


AGENT_ACTION_SWITCH: Final = ActionTool(
    name="agent_action_switch",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="agent",
    audit_action="action_tool.switched",
    where="on the agent's Actions tab",
    schema=action_schema(
        "agent_action_switch",
        "Propose switching one in-call action on or off, or all of an agent's actions "
        "(`action_id` null)." + PROPOSES_ONLY,
        {
            "agent_id": _ID,
            "action_id": _NULLABLE_STR,
            "enabled": {"type": "boolean"},
        },
    ),
    plan=_plan_switch,
    execute=_execute_switch,
)


class _RemoveArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    action_id: UUID


async def _plan_remove(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_RemoveArgs, args)
    name = await agent_name(session, parsed.agent_id)
    tool = await _one_tool(session, parsed.agent_id, parsed.action_id)
    return Plan(
        object_id=str(parsed.agent_id),
        title="Remove an in-call action",
        summary=f"Remove “{tool.name}” from “{name}”. Live calls stop using it at once.",
        current=f"{tool.name} ({'on' if tool.enabled else 'off'})",
        proposed="removed",
        cost=None,
        reversal="A removed action cannot be brought back; add it again on the Actions tab.",
        args={"agent_id": str(parsed.agent_id), "action_id": str(parsed.action_id)},
    )


async def _execute_remove(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    del actor
    parsed = parse_args(_RemoveArgs, args)
    await agent_tools.remove_action(session, agent_id=parsed.agent_id, tool_id=parsed.action_id)
    return Executed(
        applied=True,
        detail="The action is removed.",
        audit_summary={"action_tool_id": str(parsed.action_id)},
    )


AGENT_ACTION_REMOVE: Final = ActionTool(
    name="agent_action_remove",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="agent",
    audit_action="action_tool.deleted",
    where="on the agent's Actions tab",
    schema=action_schema(
        "agent_action_remove",
        "Propose removing one of an agent's in-call actions." + PROPOSES_ONLY,
        {"agent_id": _ID, "action_id": {"type": "string"}},
    ),
    plan=_plan_remove,
    execute=_execute_remove,
)


# --- lead details -----------------------------------------------------------------------
#
# What a call notes is its campaign's or line's own list (D-1028), so each write here names
# jobs and carries the digest of the list each showed when the card was made: a confirm that
# lands after a list changed is refused (`campaigns/notes.save_notes`) rather than replacing
# it. A job's engine agent learns its list at its next put-live (Start, a test call, Put it
# live), as after `notes_set`.

_JobKind = Literal["campaign", "line"]


def _job_word(kind: str) -> str:
    return "campaign" if kind == "campaign" else "line"


def _refs_arg(jobs: list[lead_fields_service.JobRow]) -> list[dict[str, str]]:
    return [{"job": j.kind, "job_id": str(j.id), "digest": j.digest} for j in jobs]


def _refs_of(raw: Any) -> list[lead_fields_service.JobRef]:
    return [
        lead_fields_service.JobRef(
            kind="campaign" if item["job"] == "campaign" else "line",
            job_id=UUID(str(item["job_id"])),
            digest=str(item["digest"]),
        )
        for item in raw or []
    ]


async def _open_jobs(session: AsyncSession, tenant_id: UUID) -> list[lead_fields_service.JobRow]:
    vertical = await lead_fields_service.vertical_of(session, tenant_id=tenant_id)
    starting = await lead_fields_service.starting_business_fields(
        session, tenant_id=tenant_id, vertical=vertical
    )
    return await lead_fields_service.jobs_with_fields(session, starting=starting)


def _jobs_words(jobs: list[lead_fields_service.JobRow]) -> str:
    return ", ".join(f"{_job_word(j.kind)} “{strip_invisible(j.name)}”" for j in jobs)


async def _queue_changed_live(
    session: AsyncSession, actor: ToolActor, written: list[lead_fields_service.JobWrite]
) -> None:
    """Put each job whose list changed on its calls once this commits, as the Lead details
    screen's applies do after theirs (`lead_fields_routes`)."""
    await queue_put_live(
        session,
        tenant_id=actor.tenant_id,
        jobs=[(w.kind, w.job_id) for w in written if w.changed],
    )


class _KeepArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep: Annotated[list[Annotated[str, Field(max_length=64)]], Field(max_length=40)]


async def _plan_keep(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    parsed = parse_args(_KeepArgs, args)
    draft = await lead_fields_service.read_draft(session, tenant_id=actor.tenant_id)
    if draft is None or draft.status != "done":
        raise WriteRefusedError("there is no finished draft of lead details to keep")
    if draft.reviewed:
        raise WriteRefusedError("the drafted lead details were already kept or discarded")
    labels = {field.key: field.label for field in draft.fields}
    unknown = [key for key in parsed.keep if key not in labels]
    if unknown:
        raise WriteRefusedError(
            "`keep` names keys that are not in the draft; use the draft's own keys"
        )
    keep = list(dict.fromkeys(parsed.keep))
    # The jobs the Lead details screen ticks by default: nobody chose their list.
    jobs = [j for j in await _open_jobs(session, actor.tenant_id) if j.untouched] if keep else []
    kept = ", ".join(labels[key] for key in keep)
    return Plan(
        object_id=str(actor.tenant_id),
        title="Keep the drafted lead details" if keep else "Discard the drafted lead details",
        summary=(
            f"Keep {kept}. New campaigns and lines start with them, and "
            + (_jobs_words(jobs) if jobs else "no campaign or line yet")
            + " (whose lists nobody changed) take them now; the rest of the draft is dropped."
            if keep
            else "Drop the whole draft. No campaign or line changes."
        ),
        current="a draft waiting for review",
        proposed=kept or "nothing kept",
        cost=None,
        reversal="This is done once; change each campaign's or line's list afterwards.",
        args={"keep": keep, "jobs": _refs_arg(jobs)},
    )


async def _execute_keep(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    keep = parse_args(_KeepArgs, {"keep": args["keep"]}).keep
    done = await lead_fields_writes.keep_draft(
        session, tenant_id=actor.tenant_id, keep=keep, jobs=_refs_of(args.get("jobs"))
    )
    await _queue_changed_live(session, actor, done.written)
    changed = sum(1 for w in done.written if w.changed)
    return Executed(
        applied=True,
        detail=f"Kept {len(done.kept)} detail(s); {changed} campaign(s) or line(s) changed.",
        audit_summary={
            "field_keys": [f.key for f in done.kept],
            "jobs": [f"{w.kind}:{w.job_id}" for w in done.written],
        },
    )


LEAD_FIELDS_KEEP_DRAFT: Final = ActionTool(
    name="lead_fields_keep_draft",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="organization",
    audit_action="lead_fields.draft_reviewed",
    where="on the Lead details screen",
    schema=action_schema(
        "lead_fields_keep_draft",
        "Propose keeping some of the lead details `lead_fields_draft` drafted (by key; an "
        "empty list discards the draft). Once per draft. What is kept becomes what new "
        "campaigns and lines start with, and goes onto the ones whose lists nobody changed."
        + PROPOSES_ONLY,
        {"keep": {"type": "array", "items": {"type": "string"}}},
    ),
    plan=_plan_keep,
    execute=_execute_keep,
)


class _JobArg(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job: _JobKind
    job_id: UUID


class _ResetArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobs: Annotated[list[_JobArg], Field(max_length=lead_fields_service.MAX_JOBS)] | None


async def _plan_reset(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    parsed = parse_args(_ResetArgs, args)
    fields = await lead_fields_writes.replacement_fields(
        session, tenant_id=actor.tenant_id, business_type=None
    )
    jobs = await _open_jobs(session, actor.tenant_id)
    if parsed.jobs is not None:
        named = {(j.job, j.job_id) for j in parsed.jobs}
        if not named <= {(j.kind, j.id) for j in jobs}:
            raise WriteRefusedError(
                "one of `jobs` is not an open campaign or line of this account; take the "
                "ids from `agent_detail`"
            )
        jobs = [j for j in jobs if (j.kind, j.id) in named]
    if not jobs:
        raise WriteRefusedError("this account has no open campaign or line to change")
    labels = ", ".join(field.label for field in fields)
    return Plan(
        object_id=str(actor.tenant_id),
        title="Start lead details again from the standard set",
        summary=(
            f"Give {_jobs_words(jobs)} these lead details: {labels}. Details already captured "
            "stay on their leads. Each asks for them from its next call."
        ),
        current="each campaign's or line's own list",
        proposed=labels,
        cost=None,
        reversal="Change each campaign's or line's list back on its What it notes.",
        args={"jobs": _refs_arg(jobs)},
    )


async def _execute_reset(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    done = await lead_fields_writes.replace_with_standard(
        session, tenant_id=actor.tenant_id, jobs=_refs_of(args.get("jobs"))
    )
    await _queue_changed_live(session, actor, done.written)
    changed = sum(1 for w in done.written if w.changed)
    return Executed(
        applied=changed > 0,
        detail=f"{changed} campaign(s) or line(s) now note the standard lead details.",
        audit_summary={
            "jobs": [f"{w.kind}:{w.job_id}" for w in done.written],
            "field_keys": [f.key for f in done.fields],
        },
    )


LEAD_FIELDS_RESET: Final = ActionTool(
    name="lead_fields_reset",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="organization",
    audit_action="lead_fields.replaced",
    where="on the Lead details screen",
    schema=action_schema(
        "lead_fields_reset",
        "Propose replacing what campaigns and lines note with the business's standard set (or "
        "the kept draft). `jobs` null means every open campaign and line; otherwise each is "
        "`{job: campaign|line, job_id}` from `agent_detail`." + PROPOSES_ONLY,
        {
            "jobs": {
                "anyOf": [
                    {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "job": {"type": "string", "enum": ["campaign", "line"]},
                                "job_id": {"type": "string"},
                            },
                            "required": ["job", "job_id"],
                            "additionalProperties": False,
                        },
                    },
                    {"type": "null"},
                ]
            }
        },
    ),
    plan=_plan_reset,
    execute=_execute_reset,
)


class _AnswerArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job: _JobKind
    job_id: UUID
    suggestion_id: Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]
    accept: bool


_KIND_WORDS: Final[dict[str, str]] = {
    "add_choices": "add the choices",
    "remove_choices": "remove the choices",
    "new_field": "add a new detail",
}


async def _plan_answer(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_AnswerArgs, args)
    state = await field_suggestions.read_state(session, parsed.job, parsed.job_id)
    chosen = next((s for s in state.suggestions if s.id == parsed.suggestion_id), None)
    if chosen is None:
        raise WriteRefusedError(
            "that suggestion is not waiting for this campaign or line; read them with "
            "`agent_settings` part `lead_fields`"
        )
    noun = _job_word(parsed.job)
    what = (
        f"{_KIND_WORDS[chosen.kind]} {', '.join(chosen.values)}".strip()
        + f" ({strip_invisible(chosen.field_label)})"
    )
    return Plan(
        object_id=str(parsed.job_id),
        title="Accept a suggested lead detail" if parsed.accept else "Turn down a suggestion",
        summary=(
            f"On this {noun}: {what}. Leads captured earlier keep their details. It asks for "
            "it from its next call."
            if parsed.accept
            else f"Turn down “{what}” for this {noun}. It is not offered again."
        ),
        current="suggested",
        proposed="accepted" if parsed.accept else "turned down",
        cost=None,
        reversal=(
            f"Change the {noun}'s What it notes to change it back."
            if parsed.accept
            else "A turned-down suggestion is not offered again."
        ),
        args={
            "job": parsed.job,
            "job_id": str(parsed.job_id),
            "suggestion_id": parsed.suggestion_id,
            "accept": parsed.accept,
        },
    )


async def _execute_answer(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_AnswerArgs, args)
    answer = field_suggestions.accept if parsed.accept else field_suggestions.dismiss
    chosen = await answer(session, parsed.job, parsed.job_id, suggestion_id=parsed.suggestion_id)
    if parsed.accept:
        # The accept route puts the job live after its commit; a dismissal changes no list.
        await queue_put_live(session, tenant_id=actor.tenant_id, jobs=[(parsed.job, parsed.job_id)])
    return Executed(
        applied=True,
        detail="Done: its list is updated."
        if parsed.accept
        else "Turned down; it will not be offered again.",
        # Kind, key and how many choices: the choice words are the business's wording.
        audit_summary={
            "job": parsed.job,
            "suggestion": chosen.id,
            "kind": chosen.kind,
            "field_key": chosen.field_key,
            "values": len(chosen.values),
            "accepted": parsed.accept,
        },
    )


LEAD_SUGGESTION_ANSWER: Final = ActionTool(
    name="lead_suggestion_answer",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="campaign",
    audit_action="lead_suggestions.answered",
    where="on the Lead details screen or the job's What it notes",
    schema=action_schema(
        "lead_suggestion_answer",
        "Propose accepting or turning down one suggested change to what a campaign or line "
        "notes (from `agent_settings` part `lead_fields`)." + PROPOSES_ONLY,
        {
            "job": {"type": "string", "enum": ["campaign", "line"]},
            "job_id": {
                "type": "string",
                "description": "The campaign's or line's id, never invented.",
            },
            "suggestion_id": {"type": "string"},
            "accept": {"type": "boolean"},
        },
    ),
    plan=_plan_answer,
    execute=_execute_answer,
)


#: Registration order is wire order and part of the cacheable prefix. New actions APPEND.
AGENT_TOOL_ACTIONS: Final[tuple[ActionTool, ...]] = (
    AGENT_ACTION_SET,
    AGENT_ACTION_SWITCH,
    AGENT_ACTION_REMOVE,
    LEAD_FIELDS_KEEP_DRAFT,
    LEAD_FIELDS_RESET,
    LEAD_SUGGESTION_ANSWER,
)

__all__ = [
    "AGENT_ACTION_REMOVE",
    "AGENT_ACTION_SET",
    "AGENT_ACTION_SWITCH",
    "AGENT_TOOL_ACTIONS",
    "LEAD_FIELDS_KEEP_DRAFT",
    "LEAD_FIELDS_RESET",
    "LEAD_SUGGESTION_ANSWER",
]
