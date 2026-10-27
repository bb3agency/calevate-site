"""Pip's agent set-up actions (D-893 lane L4): restore and get ready, the Script tab's
direct buttons, how an agent sounds and handles a call, and who it hands a caller to.

Each executor calls the function the page's own button calls (`docs/COPILOT-CONTRACT.md`
§2), so every refusal that button meets is met here:

* `agent_restore` — `lifecycle.restore_agent` (Agents, deleted list → Restore). Immediate:
  a restored agent comes back paused, answers nothing and calls nobody; Undo deletes it again.
* `agent_prepare` — `lifecycle.prepare_agent` ("Get it ready"). Confirm: it publishes to the
  voice platform, which holds one of the workspace's agent places.
* `agent_script_put_live` — `script_publish.put_draft_live` ("Put it live"), bound to the
  draft the card describes by its `saved_at`.
* `agent_script_discard` — `publishing.undo_staged` (Undo on a saved-but-not-live change).
* `agent_script_version_restore` — `script_builder.restore_into_draft` (History → Restore).
* `agent_settings_set` — the Settings tab's voice, call-handling, longest-call, model and
  caller-memory controls, each through its own writer; `scope` `all_agents` is the
  call-handling rows' "All my agents" (`call_handling.set_call_handling_for_all_agents`).
* `agent_handover_set` — `handoff.replace_handoff` (Hand-over list → Save).

Everything that can reach a caller of a live agent is `confirm`. A tool's tier is fixed per
tool, and a twin per setting for draft agents would cost the cached prefix more than the
click it saves.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Final, Literal, get_args
from uuid import UUID

from calevate_shared.engine import ByokVoiceTuning, LlmTier
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import call_handling, lifecycle, publishing, script_builder, voice_tuning
from apps.api.agents import handoff as handoff_service
from apps.api.agents.call_handling import SETTING_FIELDS
from apps.api.agents.llm_tiers import (
    LLM_TIER_LABELS,
    resolve_agent_tier,
    resolve_tier_choice,
    tier_of_model,
)
from apps.api.agents.models import (
    CALL_CAP_DEFAULT_S,
    CALL_CAP_MAX_S,
    CALL_CAP_MIN_S,
    FILLER_LINE_MAX_CHARS,
    FILLER_LINES_MAX,
    NUDGE_PHRASE_MAX_CHARS,
)
from apps.api.agents.script_publish import put_draft_live
from apps.api.compliance.caller_memory import CALLER_MEMORY_ATTESTATION_VERSION
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
    may_act,
    parse_args,
)
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.errors import ProblemError
from apps.api.db.ownership import assert_visible

_ID: Final[dict[str, Any]] = {"type": "string", "description": "The agent's id, never invented."}


class _AgentIdArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID


async def _name_status(session: AsyncSession, agent_id: UUID) -> tuple[str, str]:
    """One agent's name and status, or a 404 — under RLS also a neighbour's answer."""
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


# --- agent_restore (immediate) ----------------------------------------------------------


async def _plan_restore(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_AgentIdArgs, args)
    name, status = await _name_status(session, parsed.agent_id)
    if status != "archived":
        raise WriteRefusedError(
            f"“{name}” is {status}, not deleted, so there is nothing to restore"
        )
    return Plan(
        object_id=str(parsed.agent_id),
        title="Restore this agent",
        summary=(
            f"Bring “{name}” back from your deleted agents. It comes back paused: it answers "
            "nothing and calls nobody until it is published again. Numbers it had are not "
            "given back."
        ),
        current="deleted",
        proposed="paused",
        cost=None,
        reversal="Undo deletes it again.",
        args={"agent_id": str(parsed.agent_id)},
    )


async def _execute_restore(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_AgentIdArgs, args)
    result = await lifecycle.restore_agent(
        session, tenant_id=actor.tenant_id, agent_id=parsed.agent_id
    )
    return Executed(
        applied=result.changed,
        detail=(
            "The agent is back, paused. Publish it when you want it on the phone again."
            if result.changed
            else "That agent was not deleted, so nothing changed."
        ),
        audit_summary={"agent_id": str(parsed.agent_id), "status": result.status},
    )


async def _capture_restore(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    del actor
    agent_id = parse_args(_AgentIdArgs, args).agent_id
    row = (
        await session.execute(
            text(
                "SELECT status, (SELECT count(*) FROM phone_numbers pn WHERE pn.agent_id = a.id) "
                "FROM agents a WHERE a.id = :aid AND a.deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    return {} if row is None else {"status": str(row[0]), "numbers": int(row[1])}


async def _invert_restore(session: AsyncSession, actor: ToolActor, record: UndoRecord) -> str:
    """Delete it again through the console's Delete, while it is still the paused agent the
    restore left, with no number given to it since."""
    agent_id = UUID(str(record.args["agent_id"]))
    row = (
        await session.execute(
            text(
                "SELECT status, (SELECT count(*) FROM phone_numbers pn WHERE pn.agent_id = a.id) "
                "FROM agents a WHERE a.id = :aid AND a.deleted_at IS NULL FOR UPDATE OF a"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None or str(row[0]) == "archived":
        raise UndoRefusedError("that agent is already deleted")
    if {"status": str(row[0]), "numbers": int(row[1])} != dict(record.result_state):
        raise UndoRefusedError(
            "that agent has been changed since it was restored, so it was kept — delete it "
            "from the Agents screen if you no longer want it"
        )
    await lifecycle.archive_agent(session, tenant_id=actor.tenant_id, agent_id=agent_id)
    return "The agent is deleted again."


AGENT_RESTORE: Final = ActionTool(
    name="agent_restore",
    tier="immediate",
    undo=Undo(capture=_capture_restore, invert=_invert_restore),
    permission="org:manage",
    object_type="agent",
    audit_action="agent.restored",
    where="under Agents in your dashboard",
    acts_on_archived=True,
    schema=action_schema(
        "agent_restore",
        "Bring a deleted agent back. It returns paused, taking no calls." + DOES_IT,
        {"agent_id": _ID},
    ),
    plan=_plan_restore,
    execute=_execute_restore,
)


# --- agent_prepare (confirm) ------------------------------------------------------------


async def _plan_prepare(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_AgentIdArgs, args)
    name, status = await _name_status(session, parsed.agent_id)
    if status == "live":
        raise WriteRefusedError(f"“{name}” is already live, so it is already ready")
    return Plan(
        object_id=str(parsed.agent_id),
        title="Get this agent ready to try",
        summary=(
            f"Publish “{name}” to the calling system so you can try it in its Try it chat. "
            "No number is given to it and it places no calls."
        ),
        current=status,
        proposed="ready, not taking calls",
        cost=None,
        reversal="It stays off the phone; switch it on or delete it from the Agents screen.",
        args={"agent_id": str(parsed.agent_id)},
    )


async def _execute_prepare(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_AgentIdArgs, args)
    result = await lifecycle.prepare_agent(
        session, tenant_id=actor.tenant_id, agent_id=parsed.agent_id
    )
    return Executed(
        applied=True,
        detail="The agent is ready to try in its Try it chat. It takes no calls.",
        audit_summary={"agent_id": str(parsed.agent_id), "status": result.status},
    )


AGENT_PREPARE: Final = ActionTool(
    name="agent_prepare",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="agent",
    audit_action="agent.prepared",
    where="on the agent's Try it tab",
    schema=action_schema(
        "agent_prepare",
        "Propose getting a draft or paused agent ready to try in chat, without taking calls. "
        "To put it on the phone use `agent_publish`." + PROPOSES_ONLY,
        {"agent_id": _ID},
    ),
    plan=_plan_prepare,
    execute=_execute_prepare,
)


# --- the Script tab's direct buttons (confirm) ------------------------------------------


async def _versions(session: AsyncSession, agent_id: UUID) -> tuple[int | None, int | None]:
    """(saved version, version callers hear)."""
    row = (
        await session.execute(
            text(
                "SELECT d.version, l.version FROM agents a "
                "LEFT JOIN prompt_versions d ON d.id = a.system_prompt_id "
                "LEFT JOIN prompt_versions l ON l.id = a.live_prompt_id WHERE a.id = :aid"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:  # pragma: no cover - the caller has already resolved the agent
        raise ProblemError.not_found("Agent")
    return (
        None if row[0] is None else int(row[0]),
        None if row[1] is None else int(row[1]),
    )


class _PutLiveArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    summary: Annotated[str, Field(max_length=200)]


class _PutLiveSigned(_PutLiveArgs):
    draft_saved_at: datetime
    expected_version: int | None


async def _plan_put_live(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_PutLiveArgs, args)
    summary = strip_invisible(parsed.summary.strip())
    if not summary:
        raise WriteRefusedError("`summary` was blank: say in a few words what changed")
    name, status = await _name_status(session, parsed.agent_id)
    draft = await script_builder.read_draft(session, parsed.agent_id)
    if draft is None:
        raise WriteRefusedError(
            "this agent's script has no unpublished changes, so there is nothing to put live"
        )
    await script_builder.refuse_if_too_long(session, parsed.agent_id, draft.script)
    saved, heard = await _versions(session, parsed.agent_id)
    live = status == "live"
    return Plan(
        object_id=str(parsed.agent_id),
        title="Put the script changes live",
        summary=(
            f"Save the draft of {name}'s script, as it is on the Script tab now, as a new "
            f"version (“{summary}”)"
            + (
                " and put it in front of callers from their next call."
                if live
                else ". The agent is not live, so no caller hears it yet."
            )
        ),
        current=(
            "nothing saved yet" if heard is None and saved is None else f"version {heard or saved}"
        ),
        proposed="the reviewed draft, as a new version",
        cost=None,
        reversal=(
            "Every earlier version stays in History; restore one and put it live to go back. "
            "Calls already taken are not affected."
        ),
        args={
            "agent_id": str(parsed.agent_id),
            "summary": summary,
            "draft_saved_at": draft.saved_at.isoformat(),
            "expected_version": saved,
        },
    )


async def _execute_put_live(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`script_publish.put_draft_live`, which commits the version in its own transaction and
    then applies it; this session has only read the agent, so it holds no lock that the
    save would wait on."""
    del session
    parsed = parse_args(_PutLiveSigned, args)
    done = await put_draft_live(
        tenant_id=actor.tenant_id,
        agent_id=parsed.agent_id,
        summary=parsed.summary,
        created_by=actor.user_id,
        check_version=True,
        expected_version=parsed.expected_version,
        draft_saved_at=parsed.draft_saved_at,
    )
    return Executed(
        applied=True,
        detail=(
            f"Version {done.version} is live: callers hear it from their next call."
            if done.live
            else f"Saved as version {done.version}. Callers hear it once the agent is live."
        ),
        audit_summary={"version": done.version, "live": done.live},
    )


AGENT_SCRIPT_PUT_LIVE: Final = ActionTool(
    name="agent_script_put_live",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="agent",
    audit_action="agent.script_published",
    where="on the agent's Script tab",
    schema=action_schema(
        "agent_script_put_live",
        "Propose saving the agent's reviewed script draft as a version and putting it live. "
        "For a saved change already waiting use `agent_changes_apply`." + PROPOSES_ONLY,
        {
            "agent_id": _ID,
            "summary": {"type": "string", "description": "What changed, in a few words."},
        },
    ),
    plan=_plan_put_live,
    execute=_execute_put_live,
)


async def _plan_discard(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_AgentIdArgs, args)
    name, _status = await _name_status(session, parsed.agent_id)
    saved, heard = await _versions(session, parsed.agent_id)
    if saved is None or heard is None or saved == heard:
        raise WriteRefusedError(
            "that agent has no saved script change waiting to go live, so there is nothing "
            "to throw away"
        )
    return Plan(
        object_id=str(parsed.agent_id),
        title="Throw away the saved script change",
        summary=(
            f"Drop version {saved} of {name}'s script, which callers never heard. The script "
            f"goes back to version {heard}, the one callers hear now."
        ),
        current=f"version {saved} waiting",
        proposed=f"version {heard}",
        cost=None,
        reversal=f"Version {saved} stays in History and can be restored into the draft.",
        args={"agent_id": str(parsed.agent_id)},
    )


async def _execute_discard(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`publishing.undo_staged` — `POST .../script/undo`'s call, in its own session."""
    del session
    parsed = parse_args(_AgentIdArgs, args)
    result = await publishing.undo_staged(tenant_id=actor.tenant_id, agent_id=parsed.agent_id)
    return Executed(
        applied=result.undone,
        detail=(
            f"Version {result.discarded_version} is thrown away; the script is back to "
            f"version {result.live_version}."
            if result.undone
            else "Nothing was waiting to go live, so nothing changed."
        ),
        audit_summary={
            "discarded_version": result.discarded_version,
            "version": result.live_version,
        },
    )


AGENT_SCRIPT_DISCARD: Final = ActionTool(
    name="agent_script_discard",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="agent",
    audit_action="agent.changes_undone",
    where="on the agent's Script tab",
    schema=action_schema(
        "agent_script_discard",
        "Propose throwing away a live agent's saved script change that callers have not "
        "heard yet. To put it live instead use `agent_changes_apply`." + PROPOSES_ONLY,
        {"agent_id": _ID},
    ),
    plan=_plan_discard,
    execute=_execute_discard,
)


class _VersionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    version: Annotated[int, Field(ge=1)]


async def _plan_version_restore(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_VersionArgs, args)
    name, _status = await _name_status(session, parsed.agent_id)
    row = (
        await session.execute(
            text("SELECT notes FROM prompt_versions WHERE agent_id = :aid AND version = :v"),
            {"aid": parsed.agent_id, "v": parsed.version},
        )
    ).first()
    if row is None:
        raise WriteRefusedError(
            f"“{name}” has no script version {parsed.version}; read the History list first"
        )
    _saved, heard = await _versions(session, parsed.agent_id)
    has_draft = await script_builder.read_draft(session, parsed.agent_id) is not None
    note = strip_invisible(str(row[0])) if row[0] else None
    return Plan(
        object_id=str(parsed.agent_id),
        title="Restore an earlier script into the draft",
        summary=(
            f"Copy version {parsed.version}"
            + (f" (“{note}”)" if note else "")
            + f" of {name}'s script into the draft"
            + (", replacing the unpublished draft there now" if has_draft else "")
            + ". Callers keep hearing "
            + (f"version {heard}" if heard is not None else "nothing new")
            + " until the draft is put live."
        ),
        current="the unpublished draft" if has_draft else "no unpublished draft",
        proposed=f"version {parsed.version} in the draft",
        cost=None,
        reversal=(
            "Every version stays in History. A draft replaced here cannot be brought back."
            if has_draft
            else "Every version stays in History; change the draft again at any time."
        ),
        args={"agent_id": str(parsed.agent_id), "version": parsed.version},
    )


async def _execute_version_restore(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    del actor
    parsed = parse_args(_VersionArgs, args)
    await script_builder.restore_into_draft(session, parsed.agent_id, parsed.version)
    return Executed(
        applied=True,
        detail=(
            f"Version {parsed.version} is in the draft. Review it on the Script tab, then put "
            "it live when it is right."
        ),
        audit_summary={"version": parsed.version},
    )


AGENT_SCRIPT_VERSION_RESTORE: Final = ActionTool(
    name="agent_script_version_restore",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="agent",
    audit_action="agent.script_version_restored",
    where="on the agent's Script tab",
    schema=action_schema(
        "agent_script_version_restore",
        "Propose copying an earlier script version into the agent's draft (callers keep the "
        "live one). Versions are in `agent_settings` part `script`." + PROPOSES_ONLY,
        {
            "agent_id": _ID,
            "version": {"type": "integer", "description": "The version number."},
        },
    ),
    plan=_plan_version_restore,
    execute=_execute_version_restore,
)


# --- agent_settings_set (confirm) -------------------------------------------------------

Setting = Literal[
    "speed",
    "volume",
    "emotion",
    "opening_waits_for_caller",
    "turn_silence_ms",
    "end_call_on_finish",
    "nudge_after_seconds",
    "nudge_count",
    "nudge_phrase",
    "end_after_silence_seconds",
    "filler_lines",
    "ambience",
    "ambience_volume_pct",
    "longest_call_minutes",
    "ai_model",
    "caller_memory",
    "caller_has_screen",
]
SETTINGS: Final[tuple[str, ...]] = get_args(Setting)
#: Settings with no account default: each agent's own, on or off.
_PER_AGENT_SWITCHES: Final = frozenset({"opening_waits_for_caller", "caller_has_screen"})
VOICE_SETTINGS: Final = frozenset({"speed", "volume", "emotion"})
HANDLING_SETTINGS: Final = frozenset(
    {*call_handling.SETTING_FIELDS, *call_handling.AGENT_ONLY_FIELDS}
)
#: The one setting staff may change (`agents:write`, D-587); the rest are the owner's.
_STAFF_SETTINGS: Final = frozenset({"longest_call_minutes"})

_LABELS: Final[dict[str, str]] = {
    "speed": "speaking speed",
    "volume": "loudness",
    "emotion": "tone of voice",
    "opening_waits_for_caller": "waits for the person who picks up to speak first",
    "turn_silence_ms": "pause before replying",
    "end_call_on_finish": "hangs up when finished",
    "nudge_after_seconds": "checks on a quiet caller after",
    "nudge_count": "times it checks on a quiet caller",
    "nudge_phrase": "what it says to a quiet caller",
    "end_after_silence_seconds": "hangs up after silence of",
    "filler_lines": "lines while it looks something up",
    "ambience": "background sound",
    "ambience_volume_pct": "background sound level",
    "longest_call_minutes": "longest one call may run",
    "ai_model": "AI model",
    "caller_memory": "remembers returning callers",
    "caller_has_screen": "guides callers through their screen",
}

_ON: Final = frozenset({"on", "yes", "true"})
_OFF: Final = frozenset({"off", "no", "false"})
_DEFAULT: Final = "default"
_AMBIENCES: Final = ("off", "office", "office-quiet")


class _Change(BaseModel):
    model_config = ConfigDict(extra="forbid")

    setting: Setting
    value: Annotated[str, Field(max_length=600)]


#: Whom a call-handling change is for, as the Settings tab's "Just this agent" / "All my
#: agents" choice. The other settings are always the named agent's.
Scope = Literal["this_agent", "all_agents"]


class _SettingsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    changes: Annotated[list[_Change], Field(min_length=1, max_length=len(SETTINGS))]
    scope: Scope = "this_agent"


def _for_all(parsed: _SettingsArgs) -> bool:
    """Refuses the one call-handling setting that has no account default."""
    if parsed.scope != "all_agents":
        return False
    own = next((c.setting for c in parsed.changes if c.setting in _PER_AGENT_SWITCHES), None)
    if own is not None:
        raise WriteRefusedError(f"`{own}` is set per agent; send it with `scope` `this_agent`")
    return True


_OTHER_AGENTS_OWN: Final = (
    "SELECT " + ", ".join(SETTING_FIELDS) + " FROM agents WHERE deleted_at IS NULL AND id <> :aid"
)


async def _others_with_own(session: AsyncSession, agent_id: UUID, settings: list[str]) -> int:
    """How many other agents keep a value of their own for any of these settings, which
    "all agents" drops."""
    rows = (await session.execute(text(_OTHER_AGENTS_OWN), {"aid": agent_id})).all()
    return sum(
        1
        for row in rows
        if any(
            getattr(call_handling.settings_from_row(tuple(row)), s) is not None for s in settings
        )
    )


def _switch(setting: str, raw: str) -> bool:
    word = raw.strip().lower()
    if word in _ON:
        return True
    if word in _OFF:
        return False
    raise WriteRefusedError(f"`{setting}` takes `on` or `off`")


def _whole(setting: str, raw: str) -> int:
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise WriteRefusedError(f"`{setting}` takes a whole number, or `default`") from exc


def _parse(setting: str, raw: str) -> Any:
    """One change's value in the shape its writer takes; `default` follows the account's
    or the voice's own value (None)."""
    value = strip_invisible(raw.strip())
    defaultable = setting not in (*_PER_AGENT_SWITCHES, "caller_memory")
    if defaultable and value.lower() == _DEFAULT:
        return None
    if setting in (*_PER_AGENT_SWITCHES, "end_call_on_finish", "caller_memory"):
        return _switch(setting, value)
    if setting in ("speed", "volume"):
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise WriteRefusedError(f"`{setting}` takes a number, or `default`") from exc
    if setting == "emotion":
        if value not in voice_tuning.EMOTIONS:
            raise WriteRefusedError(
                "`emotion` is one of " + ", ".join(voice_tuning.EMOTIONS) + ", or `default`"
            )
        return value
    if setting == "nudge_phrase":
        if len(value) > NUDGE_PHRASE_MAX_CHARS:
            raise WriteRefusedError(
                f"`nudge_phrase` is at most {NUDGE_PHRASE_MAX_CHARS} characters"
            )
        return value
    if setting == "filler_lines":
        lines = [line.strip() for line in value.split("|") if line.strip()]
        if len(lines) > FILLER_LINES_MAX or any(len(x) > FILLER_LINE_MAX_CHARS for x in lines):
            raise WriteRefusedError(
                f"`filler_lines` is at most {FILLER_LINES_MAX} lines of "
                f"{FILLER_LINE_MAX_CHARS} characters, separated by |"
            )
        return lines
    if setting == "ambience":
        if value not in _AMBIENCES:
            raise WriteRefusedError("`ambience` is `off`, `office`, `office-quiet` or `default`")
        return value
    if setting == "longest_call_minutes":
        minutes = _whole(setting, value)
        if not CALL_CAP_MIN_S <= minutes * 60 <= CALL_CAP_MAX_S:
            raise WriteRefusedError(
                f"`longest_call_minutes` is {CALL_CAP_MIN_S // 60} to {CALL_CAP_MAX_S // 60}"
            )
        return minutes * 60
    if setting == "ai_model":
        tiers = get_args(LlmTier)
        if value not in tiers:
            raise WriteRefusedError("`ai_model` is " + ", ".join(tiers) + " or `default`")
        return value
    return _whole(setting, value)


def _shown(setting: str, value: Any) -> str:
    """A value as the person reads it on the card."""
    if value is None:
        if setting == "longest_call_minutes":
            return f"the default ({CALL_CAP_DEFAULT_S // 60} min)"
        return "the default"
    if isinstance(value, bool):
        return "on" if value else "off"
    if setting == "longest_call_minutes":
        return f"{int(value) // 60} min"
    if setting == "ai_model":
        return LLM_TIER_LABELS.get(value, str(value))
    if setting == "filler_lines":
        return " | ".join(value) if value else "the standard ones"
    if setting == "nudge_phrase":
        return f"“{value}”" if value else "the standard question"
    if setting == "turn_silence_ms":
        return f"{value} ms"
    if setting in ("nudge_after_seconds", "end_after_silence_seconds"):
        return f"{value} s"
    return str(value)


@dataclass(frozen=True, slots=True)
class _Current:
    voice: voice_tuning.VoiceTuningState
    handling: call_handling.AgentCallHandling
    cap_s: int | None
    model: str | None
    caller_memory: bool
    attested: bool
    caller_has_screen: bool


async def _current(session: AsyncSession, agent_id: UUID) -> _Current:
    row = (
        await session.execute(
            text(
                "SELECT a.max_call_duration_s, a.llm_model, a.caller_memory_enabled, "
                "a.caller_has_screen, "
                # Attested to the CURRENT statement (D-900): an older acceptance is asked again.
                "o.caller_memory_attested_at IS NOT NULL AND COALESCE("
                "o.caller_memory_attestation_version, 0) >= :statement FROM agents a "
                "JOIN organizations o ON o.id = a.tenant_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL"
            ),
            {"aid": agent_id, "statement": CALLER_MEMORY_ATTESTATION_VERSION},
        )
    ).first()
    if row is None:  # pragma: no cover - the caller has already resolved the agent
        raise ProblemError.not_found("Agent")
    return _Current(
        voice=await voice_tuning.read_voice_tuning(session, agent_id),
        handling=await call_handling.read_agent_call_handling(session, agent_id),
        cap_s=None if row[0] is None else int(row[0]),
        model=None if row[1] is None else str(row[1]),
        caller_memory=bool(row[2]),
        caller_has_screen=bool(row[3]),
        attested=bool(row[4]),
    )


def _current_value(current: _Current, setting: str) -> Any:
    if setting in VOICE_SETTINGS:
        return getattr(current.voice.tuning, setting)
    if setting == "opening_waits_for_caller":
        return current.handling.opening_waits_for_caller
    if setting in HANDLING_SETTINGS:
        own = getattr(current.handling.own, setting)
        return list(own) if isinstance(own, tuple) else own
    if setting == "longest_call_minutes":
        return current.cap_s
    if setting == "ai_model":
        return tier_of_model(current.model) if current.model is not None else None
    if setting == "caller_has_screen":
        return current.caller_has_screen
    return current.caller_memory


async def _owner_settings_allowed(
    session: AsyncSession, actor: ToolActor, settings: list[str]
) -> None:
    """The owner's settings need `org:manage`, the permission their own controls declare;
    the tool itself is `agents:write` so staff can change the longest call, as on the page."""
    owners = [s for s in settings if s not in _STAFF_SETTINGS]
    if owners and not await may_act(session, actor, "org:manage"):
        raise WriteRefusedError(
            "your role may not change "
            + ", ".join(_LABELS[s] for s in owners)
            + "; only the account owner can"
        )


def _refuse_handling(changes: dict[str, Any]) -> None:
    """The call-handling writer's own range checks, run while drawing the card."""
    named = {k: v for k, v in changes.items() if k in call_handling.SETTING_FIELDS}
    if not named:
        return
    if "filler_lines" in named and named["filler_lines"] is not None:
        named["filler_lines"] = call_handling.normalise_filler_lines(named["filler_lines"])
    call_handling.refuse_invalid_settings(call_handling.settings_of(named))


async def _plan_settings(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    parsed = parse_args(_SettingsArgs, args)
    names: list[str] = [change.setting for change in parsed.changes]
    if len(set(names)) != len(names):
        raise WriteRefusedError("name each setting once")
    await _owner_settings_allowed(session, actor, names)
    name, _status = await _name_status(session, parsed.agent_id)
    values: dict[str, Any] = {
        change.setting: _parse(change.setting, change.value) for change in parsed.changes
    }
    current = await _current(session, parsed.agent_id)
    studio_only = [s for s in ("volume", "emotion") if s in values and values[s] is not None]
    if studio_only and not current.voice.studio:
        raise WriteRefusedError(
            "loudness and tone of voice apply only to a Studio voice, and this agent's voice "
            "is not one; only `speed` can be changed"
        )
    voice = {s: v for s, v in values.items() if s in VOICE_SETTINGS}
    if voice:
        # The voice writer's own range check, so an out-of-range speed is refused on the
        # card rather than at the click.
        wanted = voice_tuning.replace_fields(current.voice.tuning, voice)
        voice_tuning.refuse_invalid_tuning(
            wanted
            if current.voice.studio
            else ByokVoiceTuning(speed=wanted.speed, model=wanted.model),
            audience="client",
            studio=current.voice.studio,
        )
    _refuse_handling(values)
    if "ai_model" in values and values["ai_model"] is not None:
        resolve_tier_choice(values["ai_model"], current_model=current.model, field="ai_model")
    if values.get("caller_memory") is True and not current.caller_memory and not current.attested:
        raise WriteRefusedError(
            "switching caller memory on first needs the owner to confirm what these calls "
            "collect, on the agent's Settings tab; send them there, do not switch it on here"
        )
    for_all = _for_all(parsed)
    shared = [s for s in values if for_all and s in call_handling.SETTING_FIELDS]

    def line(setting: str, value: Any) -> str:
        if setting not in shared:
            return f"{_LABELS[setting]}: {_shown(setting, value)}"
        shown = "Calevate's default" if value is None else _shown(setting, value)
        return f"every agent's {_LABELS[setting]}: {shown}"

    was = [
        line(s, getattr(current.handling.organization, s))
        if s in shared
        else line(s, _current_value(current, s))
        for s in values
    ]
    becomes = [line(s, v) for s, v in values.items()]
    summary = f"On “{name}”: " + "; ".join(becomes) + "."
    if shared:
        others = await _others_with_own(session, parsed.agent_id, shared)
        if others:
            summary += (
                f" {others} other agent{'s' if others != 1 else ''} with a setting of "
                f"{'their' if others != 1 else 'its'} own will use this too."
            )
    return Plan(
        object_id=str(parsed.agent_id),
        title=(
            "Change how your agents handle calls"
            if shared
            else "Change how this agent handles calls"
        ),
        summary=summary + " It applies from the next call.",
        current="; ".join(was),
        proposed="; ".join(becomes),
        cost=None,
        reversal="Change them back the same way, or on the agent's Settings tab.",
        args={
            "agent_id": str(parsed.agent_id),
            "changes": [
                {"setting": change.setting, "value": strip_invisible(change.value.strip())}
                for change in parsed.changes
            ],
            "scope": parsed.scope,
        },
    )


async def _execute_settings(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """Each group through its own control's writer. The two that open their own transaction
    (`set_call_cap`, `set_caller_memory`) go first, before this session locks the row
    (COPILOT-CONTRACT §3)."""
    parsed = parse_args(_SettingsArgs, args)
    agent_id = parsed.agent_id
    values: dict[str, Any] = {
        change.setting: _parse(change.setting, change.value) for change in parsed.changes
    }
    await _owner_settings_allowed(session, actor, list(values))
    moved: list[str] = []
    if "longest_call_minutes" in values:
        before = (
            await session.execute(
                text("SELECT max_call_duration_s FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar()
        await publishing.set_call_cap(
            tenant_id=actor.tenant_id,
            agent_id=agent_id,
            max_call_duration_s=values["longest_call_minutes"],
        )
        if before != values["longest_call_minutes"]:
            moved.append("longest_call_minutes")
    if "caller_memory" in values:
        memory = await publishing.set_caller_memory(
            tenant_id=actor.tenant_id,
            agent_id=agent_id,
            enabled=bool(values["caller_memory"]),
            attested_by=None,
        )
        if not memory.unchanged:
            moved.append("caller_memory")
    if "caller_has_screen" in values:
        screen = await publishing.set_caller_has_screen(
            tenant_id=actor.tenant_id, agent_id=agent_id, enabled=bool(values["caller_has_screen"])
        )
        if not screen.unchanged:
            moved.append("caller_has_screen")
    voice = {s: v for s, v in values.items() if s in VOICE_SETTINGS}
    if voice:
        _state, voice_moved = await voice_tuning.set_voice_tuning(
            session,
            tenant_id=actor.tenant_id,
            agent_id=agent_id,
            changes=voice,
            audience="client",
        )
        moved.extend(voice_moved)
    handling = {s: v for s, v in values.items() if s in HANDLING_SETTINGS}
    agents_reset: int | None = None
    if handling and _for_all(parsed):
        # The Settings tab's "All my agents": the same writer its save calls.
        result = await call_handling.set_call_handling_for_all_agents(
            session, tenant_id=actor.tenant_id, changes=handling
        )
        agents_reset = result.agents_reset
        moved.extend(f for f in result.moved if f not in moved)
        moved.extend(f for f in handling if result.agents_reset and f not in moved)
    elif handling:
        _handled, handling_moved = await call_handling.set_agent_call_handling(
            session, tenant_id=actor.tenant_id, agent_id=agent_id, changes=handling
        )
        moved.extend(handling_moved)
    if "ai_model" in values:
        before_model = (
            await session.execute(
                text("SELECT llm_model FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar()
        model = await resolve_agent_tier(session, agent_id, values["ai_model"], field="ai_model")
        await lifecycle.update_agent(
            session,
            tenant_id=actor.tenant_id,
            agent_id=agent_id,
            llm_model=model,
            set_llm_model=True,
        )
        if before_model != model:
            moved.append("ai_model")
    return Executed(
        applied=bool(moved),
        detail=(
            "Changed: " + ", ".join(_LABELS.get(s, s) for s in moved) + ". It applies from the "
            "next call."
            if moved
            else "The agent already had those settings, so nothing changed."
        ),
        # Setting names only: a phrase or a filler line is the business's own wording.
        audit_summary={
            "agent_id": str(agent_id),
            "changed": sorted(moved),
            "scope": parsed.scope,
            **({} if agents_reset is None else {"agents_reset": agents_reset}),
        },
    )


#: Words that say a call walks the person through something on their phone or computer
#: (D-906). A hint for Pip to ASK the owner, never a switch it flips: a false match costs one
#: question, which is why plain words like "app" and "website" are enough.
_SCREEN_WORDS: Final = re.compile(
    r"\b(?:install\w*|download\w*|apps?|website|web ?site|log ?in|sign ?(?:up|in)|browser|"
    r"chrome|tap|click|screen|online form|fill (?:in|out)|step by step|troubleshoot\w*)\b"
    r"|యాప్|ఇన్‌?స్టాల్|డౌన్‌?లోడ్|వెబ్‌?సైట్|లాగిన్|ఐకాన్"
    r"|ऐप|इंस्टॉल|डाउनलोड|वेबसाइट|लॉगिन",
    re.IGNORECASE,
)


async def screen_guide_hint(session: AsyncSession, agent_id: UUID, context: str) -> str:
    """A sentence for Pip when `context` (a campaign's name) plus the agent's live script say
    the calls are screen-guided and the agent's switch is off, or plainly are not and it is
    on; empty otherwise. Pip asks the owner, then proposes `agent_settings_set`."""
    row = (
        await session.execute(
            text(
                "SELECT a.caller_has_screen, pv.body FROM agents a LEFT JOIN prompt_versions pv "
                "ON pv.id = COALESCE(a.live_prompt_id, a.system_prompt_id) "
                "WHERE a.id = :aid AND a.deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        return ""
    guided = bool(_SCREEN_WORDS.search(f"{context}\n{row[1] or ''}"))
    if guided and not row[0]:
        return (
            " These calls look like they walk people through their phone or computer: ask "
            "the owner whether to switch on the agent's caller_has_screen (agent_settings_set)."
        )
    if row[0] and not guided:
        return (
            " Its agent is set to guide callers through a screen, which these calls do not "
            "seem to need: ask the owner whether to switch caller_has_screen off."
        )
    return ""


AGENT_SETTINGS_SET: Final = ActionTool(
    name="agent_settings_set",
    tier="confirm",
    undo=None,
    # `PATCH .../call-cap`'s; the owner's settings are checked against `org:manage` inside.
    permission="agents:write",
    object_type="agent",
    audit_action="agent.settings_set",
    where="on the agent's Settings tab",
    schema=action_schema(
        "agent_settings_set",
        "Propose changing how an agent sounds and handles calls. Each change is a `setting` "
        "and a `value` (`default` follows the account or voice default): speed and volume "
        "(numbers, 1 is the voice's own), emotion, opening_waits_for_caller (on/off), "
        "turn_silence_ms, end_call_on_finish (on/off), nudge_after_seconds (0 never), "
        "nudge_count, nudge_phrase, end_after_silence_seconds, filler_lines (separated by |), "
        "ambience (off, office, office-quiet), ambience_volume_pct, longest_call_minutes, "
        "ai_model (standard, plus, pro), caller_memory (on/off), caller_has_screen (on/off: "
        "on when the calls walk the person through something on their phone or computer, "
        "such as installing an app, a website or a form; ask the owner first). `scope` "
        "`all_agents` puts "
        "the call-handling settings (pause, hang-up, quiet caller, filler lines, background "
        "sound) on every agent of the account, replacing any agent's own; `default` then "
        "means Calevate's. Use it only when the person asks for all agents. Current values: "
        "`agent_settings`." + PROPOSES_ONLY,
        {
            "agent_id": _ID,
            "changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "setting": {"type": "string", "enum": list(SETTINGS)},
                        "value": {"type": "string"},
                    },
                    "required": ["setting", "value"],
                    "additionalProperties": False,
                },
            },
            "scope": {"type": "string", "enum": ["this_agent", "all_agents"]},
        },
    ),
    plan=_plan_settings,
    execute=_execute_settings,
)


# --- agent_handover_set (confirm) -------------------------------------------------------


class _Member(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_id: UUID
    active: bool


class _HandoverArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    enabled: bool
    trigger: Annotated[str, Field(max_length=1000)] | None
    members: Annotated[list[_Member], Field(max_length=handoff_service.MAX_HANDOFF_MEMBERS)] | None


async def _contacts(session: AsyncSession) -> dict[UUID, str]:
    """This business's contacts, id → label. Never the number (hard rule 6)."""
    rows = (
        await session.execute(text("SELECT id, label FROM business_contacts ORDER BY label"))
    ).all()
    return {UUID(str(r[0])): strip_invisible(str(r[1])) for r in rows}


async def _plan_handover(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_HandoverArgs, args)
    name, _status = await _name_status(session, parsed.agent_id)
    roster = await handoff_service.roster(session, agent_id=parsed.agent_id)
    contacts = await _contacts(session)
    held = (
        await session.execute(
            text("SELECT handoff_enabled, handoff_trigger FROM agents WHERE id = :aid"),
            {"aid": parsed.agent_id},
        )
    ).one()
    members: list[dict[str, Any]] = (
        [{"contact_id": str(m.contact_id), "active": m.active} for m in roster if m.contact_id]
        if parsed.members is None
        else [{"contact_id": str(m.contact_id), "active": m.active} for m in parsed.members]
    )
    unknown = [m["contact_id"] for m in members if UUID(m["contact_id"]) not in contacts]
    if unknown:
        raise WriteRefusedError(
            "a `contact_id` is not one of this business's contacts; read them with "
            "`agent_settings` part `handover`"
        )
    if len({m["contact_id"] for m in members}) != len(members):
        raise WriteRefusedError("list each person once")
    if parsed.enabled and not members:
        raise WriteRefusedError(
            "handing over is switched on but nobody is on the list; name at least one contact"
        )
    trigger = held[1] if parsed.trigger is None else strip_invisible(parsed.trigger.strip())

    def people(listed: list[dict[str, Any]]) -> str:
        names = [
            contacts[UUID(m["contact_id"])] + ("" if m["active"] else " (off for now)")
            for m in listed
        ]
        return ", ".join(names) or "nobody"

    was = [{"contact_id": str(m.contact_id), "active": m.active} for m in roster if m.contact_id]
    return Plan(
        object_id=str(parsed.agent_id),
        title="Change who this agent hands callers to",
        summary=(
            f"“{name}” "
            + ("may put a caller through to a person" if parsed.enabled else "will not hand over")
            + f", trying in this order: {people(members)}. It reaches calls the next time the "
            "agent is published."
        ),
        current=("on: " if held[0] else "off: ") + people(was),
        proposed=("on: " if parsed.enabled else "off: ") + people(members),
        cost=None,
        reversal="Change the list again on the agent's Hand-over section.",
        args={
            "agent_id": str(parsed.agent_id),
            "enabled": parsed.enabled,
            "trigger": trigger or None,
            "members": members,
        },
    )


async def _execute_handover(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`handoff.replace_handoff`; a person already on the list keeps their own hours and note."""
    agent_id = UUID(str(args["agent_id"]))
    kept = {
        m.contact_id: m
        for m in await handoff_service.roster(session, agent_id=agent_id)
        if m.contact_id is not None
    }
    members = [
        handoff_service.HandoffMemberWrite(
            contact_id=UUID(str(m["contact_id"])),
            active=bool(m["active"]),
            hours=kept[UUID(str(m["contact_id"]))].hours
            if UUID(str(m["contact_id"])) in kept
            else None,
            note=kept[UUID(str(m["contact_id"]))].note
            if UUID(str(m["contact_id"])) in kept
            else None,
        )
        for m in list(args["members"])
    ]
    await handoff_service.replace_handoff(
        session,
        tenant_id=actor.tenant_id,
        agent_id=agent_id,
        enabled=bool(args["enabled"]),
        trigger=None if args.get("trigger") is None else str(args["trigger"]),
        members=members,
    )
    return Executed(
        applied=True,
        detail=f"The hand-over list is saved with {len(members)} person(s).",
        audit_summary={"enabled": bool(args["enabled"]), "members": len(members)},
    )


AGENT_HANDOVER_SET: Final = ActionTool(
    name="agent_handover_set",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="agent",
    audit_action="agent.handoff.replace",
    where="on the agent's Hand-over section",
    schema=action_schema(
        "agent_handover_set",
        "Propose who an agent may put a caller through to, in order. People are business "
        "contacts from `agent_settings` part `handover`; never ask for or repeat a phone "
        "number." + PROPOSES_ONLY,
        {
            "agent_id": _ID,
            "enabled": {"type": "boolean", "description": "Hand callers over at all."},
            "trigger": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "When to hand over, in the owner's words; null keeps it.",
            },
            "members": {
                "anyOf": [
                    {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "contact_id": {"type": "string"},
                                "active": {"type": "boolean"},
                            },
                            "required": ["contact_id", "active"],
                            "additionalProperties": False,
                        },
                    },
                    {"type": "null"},
                ],
                "description": "The whole list in order, or null to keep it.",
            },
        },
    ),
    plan=_plan_handover,
    execute=_execute_handover,
)


#: Registration order is wire order and part of the cacheable prefix. New actions APPEND.
AGENT_SETUP_ACTIONS: Final[tuple[ActionTool, ...]] = (
    AGENT_RESTORE,
    AGENT_PREPARE,
    AGENT_SCRIPT_PUT_LIVE,
    AGENT_SCRIPT_DISCARD,
    AGENT_SCRIPT_VERSION_RESTORE,
    AGENT_SETTINGS_SET,
    AGENT_HANDOVER_SET,
)

__all__ = [
    "AGENT_HANDOVER_SET",
    "AGENT_PREPARE",
    "AGENT_RESTORE",
    "AGENT_SCRIPT_DISCARD",
    "AGENT_SCRIPT_PUT_LIVE",
    "AGENT_SCRIPT_VERSION_RESTORE",
    "AGENT_SETTINGS_SET",
    "AGENT_SETUP_ACTIONS",
    "SETTINGS",
]
