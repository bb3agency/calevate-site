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

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions import agent_tools
from apps.api.actions import service as actions_service
from apps.api.actions.models import ACTION_KINDS
from apps.api.agents import field_suggestions, lead_fields_writes
from apps.api.agents import lead_fields as lead_fields_service
from apps.api.copilot.actions import (
    PROPOSES_ONLY,
    ActionTool,
    Executed,
    Plan,
    ToolActor,
    WriteRefusedError,
    action_schema,
    parse_args,
)
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.errors import ProblemError
from apps.api.db.ownership import assert_visible

_ID: Final[dict[str, Any]] = {"type": "string", "description": "The agent's id, never invented."}
_NULLABLE_STR: Final[dict[str, Any]] = {"anyOf": [{"type": "string"}, {"type": "null"}]}


async def _agent_name(session: AsyncSession, agent_id: UUID) -> str:
    await assert_visible(session, "agent", agent_id)
    row = (
        await session.execute(
            text("SELECT name FROM agents WHERE id = :aid AND deleted_at IS NULL"),
            {"aid": agent_id},
        )
    ).first()
    if row is None:  # pragma: no cover - `assert_visible` has already 404'd an absent row
        raise ProblemError.not_found("Agent")
    return strip_invisible(str(row[0]))


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
    trigger: Literal["during_call", "after_call"] | None
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
        "trigger": pick(parsed.trigger, current.trigger if current else "during_call"),
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
        raise WriteRefusedError(
            "a new action needs " + ", ".join(f"`{m}`" for m in missing) + "; ask the person"
        )
    for key in ("name", "description", "pre_call_message"):
        if isinstance(definition[key], str):
            definition[key] = strip_invisible(definition[key].strip())
    return definition


async def _plan_action_set(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_ActionSetArgs, args)
    name = await _agent_name(session, parsed.agent_id)
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
    actions_service.check_definition(
        kind=definition["kind"],
        provider=definition["provider"],
        name=definition["name"],
        description=definition["description"],
        trigger=definition["trigger"],
        params=definition["params"],
        config=definition["config"],
    )
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
        "account is done on the Connections screen; send the person there." + PROPOSES_ONLY,
        {
            "agent_id": _ID,
            "action_id": {**_NULLABLE_STR, "description": "From `agent_settings` part `actions`."},
            "kind": {"anyOf": [{"type": "string", "enum": list(ACTION_KINDS)}, {"type": "null"}]},
            "provider": _NULLABLE_STR,
            "name": {**_NULLABLE_STR, "description": "lower_snake_case, e.g. send_price_list"},
            "description": {**_NULLABLE_STR, "description": "When the agent should use it."},
            "trigger": {
                "anyOf": [
                    {"type": "string", "enum": ["during_call", "after_call"]},
                    {"type": "null"},
                ]
            },
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
    name = await _agent_name(session, parsed.agent_id)
    word = "on" if parsed.enabled else "off"
    if parsed.action_id is None:
        held = await actions_service.actions_enabled(session, agent_id=parsed.agent_id)
        what, current = f"all of “{name}”'s in-call actions", "on" if held else "off"
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
    name = await _agent_name(session, parsed.agent_id)
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
    agents = [
        str(a["name"])
        for a in await lead_fields_service.agents_with_fields(session)
        if not a["fields"]
    ]
    kept = ", ".join(labels[key] for key in keep)
    return Plan(
        object_id=str(actor.tenant_id),
        title="Keep the drafted lead details" if keep else "Discard the drafted lead details",
        summary=(
            f"Keep {kept}. They go onto "
            + (", ".join(agents) if agents else "no agent yet")
            + " (agents with no details of their own) and every new agent; the rest of the "
            "draft is dropped. Live agents ask for them from their next call."
            if keep
            else "Drop the whole draft. No agent changes."
        ),
        current="a draft waiting for review",
        proposed=kept or "nothing kept",
        cost=None,
        reversal="This is done once; edit each agent's lead details afterwards.",
        args={"keep": keep},
    )


async def _execute_keep(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_KeepArgs, args)
    reviewed = await lead_fields_writes.keep_draft(
        session, tenant_id=actor.tenant_id, keep=parsed.keep
    )
    changed = sum(1 for w in reviewed.written if w.changed)
    return Executed(
        applied=True,
        detail=f"Kept {len(reviewed.kept)} detail(s); {changed} agent(s) changed.",
        audit_summary={
            "field_keys": [f.key for f in reviewed.kept],
            "agents": [str(w.agent_id) for w in reviewed.written],
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
        "empty list discards the draft). Once per draft." + PROPOSES_ONLY,
        {"keep": {"type": "array", "items": {"type": "string"}}},
    ),
    plan=_plan_keep,
    execute=_execute_keep,
)


class _ResetArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_ids: Annotated[list[UUID], Field(max_length=50)] | None


async def _plan_reset(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    parsed = parse_args(_ResetArgs, args)
    fields = await lead_fields_writes.replacement_fields(
        session, tenant_id=actor.tenant_id, business_type=None
    )
    agents = await lead_fields_service.agents_with_fields(session)
    if parsed.agent_ids is not None:
        known = {a["id"] for a in agents}
        if any(agent_id not in known for agent_id in parsed.agent_ids):
            raise ProblemError.not_found("Agent")
        agents = [a for a in agents if a["id"] in set(parsed.agent_ids)]
    labels = ", ".join(field.label for field in fields)
    return Plan(
        object_id=str(actor.tenant_id),
        title="Start lead details again from the standard set",
        summary=(
            f"Give {', '.join(str(a['name']) for a in agents) or 'no agent'} these lead "
            f"details: {labels}. Each gets a new version; details already captured stay on "
            "their leads. Live agents ask for them from their next call."
        ),
        current="each agent's own lead details",
        proposed=labels,
        cost=None,
        reversal="Edit each agent's lead details afterwards; earlier versions are kept.",
        args={
            "agent_ids": None
            if parsed.agent_ids is None
            else [str(agent_id) for agent_id in parsed.agent_ids]
        },
    )


async def _execute_reset(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_ResetArgs, args)
    done = await lead_fields_writes.replace_with_standard(
        session, tenant_id=actor.tenant_id, agent_ids=parsed.agent_ids
    )
    changed = sum(1 for w in done.written if w.changed)
    return Executed(
        applied=changed > 0,
        detail=f"{changed} agent(s) now capture the standard lead details.",
        audit_summary={
            "agents": [str(w.agent_id) for w in done.written],
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
        "Propose replacing agents' lead details with the business's standard set (or the "
        "kept draft). `agent_ids` null means every agent." + PROPOSES_ONLY,
        {
            "agent_ids": {
                "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]
            }
        },
    ),
    plan=_plan_reset,
    execute=_execute_reset,
)


class _AnswerArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
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
    name = await _agent_name(session, parsed.agent_id)
    state = await field_suggestions.read_state(session, agent_id=parsed.agent_id)
    chosen = next((s for s in state.suggestions if s.id == parsed.suggestion_id), None)
    if chosen is None:
        raise WriteRefusedError(
            "that suggestion is not waiting for this agent; read them with `agent_settings` "
            "part `lead_fields`"
        )
    what = (
        f"{_KIND_WORDS[chosen.kind]} {', '.join(chosen.values)}".strip()
        + f" ({strip_invisible(chosen.field_label)})"
    )
    return Plan(
        object_id=str(parsed.agent_id),
        title="Accept a suggested lead detail" if parsed.accept else "Turn down a suggestion",
        summary=(
            f"On “{name}”: {what}. Saved as a new version; leads captured earlier keep their "
            "details. A live agent asks for it from its next call."
            if parsed.accept
            else f"Turn down “{what}” for “{name}”. It is not offered again."
        ),
        current="suggested",
        proposed="accepted" if parsed.accept else "turned down",
        cost=None,
        reversal=(
            "Edit the agent's lead details to change it back."
            if parsed.accept
            else "A turned-down suggestion is not offered again."
        ),
        args={
            "agent_id": str(parsed.agent_id),
            "suggestion_id": parsed.suggestion_id,
            "accept": parsed.accept,
        },
    )


async def _execute_answer(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    del actor
    parsed = parse_args(_AnswerArgs, args)
    answer = field_suggestions.accept if parsed.accept else field_suggestions.dismiss
    chosen = await answer(session, agent_id=parsed.agent_id, suggestion_id=parsed.suggestion_id)
    return Executed(
        applied=True,
        detail="Done: the agent's lead details are updated."
        if parsed.accept
        else "Turned down; it will not be offered again.",
        # Kind, key and how many choices: the choice words are the business's wording.
        audit_summary={
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
    object_type="agent",
    audit_action="agent.lead_suggestion_answered",
    where="on the Lead details screen",
    schema=action_schema(
        "lead_suggestion_answer",
        "Propose accepting or turning down one suggested change to an agent's lead details "
        "(from `agent_settings` part `lead_fields`)." + PROPOSES_ONLY,
        {
            "agent_id": _ID,
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
