"""`agent_settings`: one agent's set-up, a part at a time, for Pip's agent actions (D-893 L4).

One read with a `part` rather than five tools, so the cached prefix grows by one schema.
Each part reads what its screen reads, through the same services:

* `settings` — the Settings tab: how it sounds, how it handles a call, the longest call, the
  AI model and caller memory, each with the value in force.
* `script` — the Script tab: whether a draft or a saved change is waiting, and the versions.
* `handover` — the Hand-over list by name, and the business contacts that may be added.
  Never a phone number: they are staff mobiles (hard rule 6), and Pip names people.
* `actions` — the Actions tab: the master switch, each action, and the connections made.
* `lead_fields` — what it writes down, the suggestions waiting, and the account's draft.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions import credentials as action_credentials
from apps.api.actions import service as actions_service
from apps.api.agents import call_handling, field_suggestions, script_builder, voice_tuning
from apps.api.agents import handoff as handoff_service
from apps.api.agents import lead_fields as lead_fields_service
from apps.api.agents.llm_tiers import LLM_TIER_LABELS, tier_of_model
from apps.api.agents.models import CALL_CAP_DEFAULT_S
from apps.api.copilot.tools import ReadTool, ToolContext, _clean, ist_date
from apps.api.core.errors import ProblemError
from apps.api.db.ownership import assert_visible

PARTS: Final[tuple[str, ...]] = ("settings", "script", "handover", "actions", "lead_fields")
#: Versions listed in the `script` part; History on the Script tab pages the rest.
_VERSIONS_SHOWN: Final = 10


def _on(value: object) -> str:
    return "on" if value else "off"


async def _settings_part(session: AsyncSession, agent_id: UUID) -> list[str]:
    voice = await voice_tuning.read_voice_tuning(session, agent_id)
    handling = await call_handling.read_agent_call_handling(session, agent_id)
    row = (
        await session.execute(
            text(
                "SELECT max_call_duration_s, llm_model, caller_memory_enabled, "
                "caller_has_screen FROM agents WHERE id = :aid"
            ),
            {"aid": agent_id},
        )
    ).one()
    tuning = voice.tuning
    values = handling.resolved.values
    sources = handling.resolved.sources
    tier = tier_of_model(row[1]) if row[1] else None
    lines = [
        "Voice: "
        + ("Studio" if voice.studio else "Clear (only speed applies)")
        + f"; speed {tuning.speed or 'default'}, volume {tuning.volume or 'default'}, "
        f"emotion {tuning.emotion or 'default'}.",
        "Call handling (value, and whose it is): "
        + "; ".join(
            f"{field} {getattr(values, field)} ({sources[field]})"
            for field in call_handling.SETTING_FIELDS
        )
        + f"; opening_waits_for_caller {_on(handling.opening_waits_for_caller)}.",
        "Longest call: "
        + (
            f"{int(row[0]) // 60} min"
            if row[0] is not None
            else f"default ({CALL_CAP_DEFAULT_S // 60} min)"
        )
        + f". AI model: {LLM_TIER_LABELS[tier] if tier else 'the account default'}."
        + f" Caller memory: {_on(row[2])}. caller_has_screen: {_on(row[3])}.",
    ]
    return lines


async def _script_part(session: AsyncSession, agent_id: UUID) -> list[str]:
    draft = await script_builder.read_draft(session, agent_id)
    pending = (
        await session.execute(
            text(
                "SELECT system_prompt_id IS DISTINCT FROM live_prompt_id "
                "AND live_prompt_id IS NOT NULL FROM agents WHERE id = :aid"
            ),
            {"aid": agent_id},
        )
    ).scalar()
    versions = await script_builder.list_versions(session, agent_id, limit=_VERSIONS_SHOWN)
    lines = [
        "Draft: "
        + (
            f"unpublished changes saved {ist_date(draft.saved_at)} (`agent_script_put_live`)."
            if draft is not None
            else "none."
        ),
        "A saved change is waiting to go live (`agent_changes_apply` / `agent_script_discard`)."
        if pending
        else "No saved change is waiting.",
        "Versions, newest first:",
    ]
    lines.extend(
        f"- {v.version}{' (callers hear this)' if v.is_live else ''}: "
        f"{v.summary or 'no note'}, {ist_date(v.created_at)}"
        for v in versions
    )
    return lines


async def _handover_part(session: AsyncSession, agent_id: UUID) -> list[str]:
    held = (
        await session.execute(
            text("SELECT handoff_enabled, handoff_trigger FROM agents WHERE id = :aid"),
            {"aid": agent_id},
        )
    ).one()
    roster = await handoff_service.roster(session, agent_id=agent_id)
    contacts = (
        await session.execute(text("SELECT id, label FROM business_contacts ORDER BY label"))
    ).all()
    lines = [
        f"Hand-over: {_on(held[0])}. When: "
        + (str(held[1]) if held[1] else handoff_service.HANDOFF_TRIGGER_DEFAULT),
        "On the list, in order: "
        + (
            "; ".join(
                f"{m.label} ({'on' if m.active else 'off for now'}) [contact_id {m.contact_id}]"
                for m in roster
            )
            or "nobody"
        ),
        "Business contacts who can be added: "
        + ("; ".join(f"{r[1]} [contact_id {r[0]}]" for r in contacts) or "none yet"),
    ]
    return lines


async def _actions_part(session: AsyncSession, agent_id: UUID) -> list[str]:
    enabled = await actions_service.actions_enabled(session, agent_id=agent_id)
    tools = await actions_service.list_tools(session, agent_id=agent_id)
    connections = await action_credentials.list_credentials(session)
    lines = [f"In-call actions are switched {_on(enabled)} for this agent."]
    lines.extend(
        f"- {t.name} ({t.kind}, {t.trigger}, {_on(t.enabled)}): {t.description[:200]} "
        f"[action_id {t.id}]"
        for t in tools
    )
    if not tools:
        lines.append("It has no actions yet.")
    lines.append(
        "Connections made (`connection_id`): "
        + ("; ".join(f"{c.label} ({c.kind}) [{c.id}]" for c in connections) or "none")
    )
    return lines


async def _lead_fields_part(
    session: AsyncSession, context: ToolContext, agent_id: UUID
) -> list[str]:
    fields = await field_suggestions.current_fields(session, agent_id)
    state = await field_suggestions.read_state(session, agent_id=agent_id)
    assert context.tenant_id is not None
    draft = await lead_fields_service.read_draft(session, tenant_id=context.tenant_id)
    lines = [
        "It writes down: "
        + (", ".join(f"{f.label} ({f.key})" for f in fields) or "no business details yet")
        + "."
    ]
    lines.extend(
        f"- suggestion {s.id}: {s.kind} {s.field_label} {', '.join(s.values)} — {s.reason}"
        for s in state.suggestions
    )
    if not state.suggestions:
        lines.append("No suggestions are waiting.")
    if draft is not None and draft.status == "done" and not draft.reviewed:
        lines.append(
            "A drafted set waits to be kept (`lead_fields_keep_draft`): "
            + ", ".join(f"{f.label} ({f.key})" for f in draft.fields)
        )
    return lines


async def _agent_settings(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    try:
        agent_id = UUID(str(args.get("agent_id")))
    except ValueError:
        return (
            "`agent_id` was missing or is not an id. Take it from the SCREEN STATE or from "
            "an `agents_list` lookup, and call this again."
        )
    part = args.get("part")
    if part not in PARTS:
        return "`part` must be one of " + ", ".join(PARTS) + "."
    try:
        await assert_visible(session, "agent", agent_id)
    except ProblemError:
        return "No agent with that id in this account."
    if part == "settings":
        lines = await _settings_part(session, agent_id)
    elif part == "script":
        lines = await _script_part(session, agent_id)
    elif part == "handover":
        lines = await _handover_part(session, agent_id)
    elif part == "actions":
        lines = await _actions_part(session, agent_id)
    else:
        lines = await _lead_fields_part(session, context, agent_id)
    return _clean("\n".join(lines)) + f"\n[agent_id {agent_id}]"


AGENT_SETTINGS_READ: Final = ReadTool(
    name="agent_settings",
    description=(
        "One part of an agent's set-up: `settings` (voice, call handling, longest call, AI "
        "model, caller memory), `script` (draft and versions), `handover` (who it hands "
        "callers to, and contacts), `actions` (in-call actions and connections) or "
        "`lead_fields` (what it writes down and suggestions)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "The agent's id."},
            "part": {"type": "string", "enum": list(PARTS)},
        },
        "required": ["agent_id", "part"],
        "additionalProperties": False,
    },
    permission="agents:read",
    run=_agent_settings,
)

__all__ = ["AGENT_SETTINGS_READ", "PARTS"]
