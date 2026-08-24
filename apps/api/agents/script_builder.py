"""The structured call-script builder: load, save (staged), and preview a `CallScript`.

This is the API-side seam between the client-realm builder UI and the two things that
already existed one call apart and never met: `calevate_shared.call_script` (the pure
structured model + compiler) and `agents/prompts.py` (immutable versioned storage with the
two-speed draft/live pointers). The builder authors a `CallScript`; this module COMPILES it
to a `prompt_versions.body` and writes it through the existing slow lane, so a structured
edit stages exactly like a freeform one and never reaches a live call by accident (SURFACES
§2b, the same guarantee `write_prompt_version` gives every script edit).

WHY THE STRUCTURED FORM AND THE COMPILED BODY BOTH GET STORED. `body` is the source of
truth for what the engine runs — `agents/service._load_agent` joins it into the
`AgentConfig`, `compose_engine_prompt` wraps it. `structured_script` is the authored form
the builder reloads so an author sees the steps/FAQ they last wrote rather than the
compiled prose. They are written together at INSERT (`insert_prompt_version`), never apart,
so they cannot drift: the body is always the compile of the structure beside it.

WHY LOADING A LEGACY AGENT STILL WORKS. A prompt version written before the structured
model existed carries a `body` and a NULL `structured_script`. `CallScript.from_freeform`
represents that as a single raw-mode script, so the builder opens on it losslessly and
"save without editing" is a no-op on the engine prompt. This is the migration path from
hard rule 8's two-step angle: nothing is rewritten, the NULL sentinel IS the old data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from calevate_shared.call_script import CallScript, compile_call_script
from calevate_shared.engine import (
    AgentConfig,
    DisclosurePosture,
    compose_engine_prompt,
    compose_opening_line,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.prompts import write_prompt_version
from apps.api.core.errors import ProblemError


@dataclass(frozen=True, slots=True)
class LoadedScript:
    """A script as the builder needs it: the structured form, plus where it stands.

    `is_freeform` says the loaded version was authored as raw text (NULL
    `structured_script`) and is represented as a raw-mode `CallScript` — the UI opens such
    an agent in the raw-edit escape hatch rather than pretending it has structured steps.
    `version` is None when the agent has no script at all yet (a brand-new agent), which the
    builder renders as an empty structured script ready to author.
    """

    script: CallScript
    version: int | None
    is_freeform: bool
    has_pending: bool


@dataclass(frozen=True, slots=True)
class SavedScript:
    """The result of staging a structured script: which version, and whether it is waiting.

    `staged` True means the agent is live and the edit sits in the draft pointer awaiting
    an explicit Apply (SURFACES §2b); False means a draft/paused agent whose edit is
    applied as written. Mirrors `write_prompt_version`'s own two-speed decision so the UI
    can tell the author "waiting to apply" vs "saved".
    """

    version: int
    staged: bool


# The columns the builder reads about an agent: which prompt version is the DRAFT
# (`system_prompt_id`), whether a change is pending, and the four disclosure columns that
# compose the opening line the preview must show above the client's script.
_AGENT_SQL = (
    "SELECT a.system_prompt_id, a.live_prompt_id, a.name, a.direction, a.language_primary, "
    "a.status, a.ai_disclosure_line, a.ai_disclosure_enabled, "
    "a.recording_notice_line, a.recording_notice_enabled "
    "FROM agents a WHERE a.id = :aid AND a.deleted_at IS NULL"
)


async def _agent_or_404(session: AsyncSession, agent_id: UUID) -> Any:
    row = (await session.execute(text(_AGENT_SQL), {"aid": agent_id})).first()
    if row is None:
        # RLS makes a neighbour's agent and a missing one one answer, deliberately.
        raise ProblemError.not_found("Agent")
    return row


async def assert_agent_visible(session: AsyncSession, agent_id: UUID) -> None:
    """404 unless `agent_id` names an agent visible to the session's tenant (RLS).

    The ownership check the builder's read/write/preview paths get for free from
    `_agent_or_404`, exposed for the one route that acts on an agent WITHOUT first loading
    its script — the AI assist, which spends money and writes an audit row and so must
    refuse a neighbour's id before either happens (hard rule 1). One predicate, so all the
    `{agent_id}` script routes answer a stranger's id the same way.
    """
    await _agent_or_404(session, agent_id)


def _posture(row: Any) -> DisclosurePosture:
    return DisclosurePosture(
        ai_disclosure_line=str(row.ai_disclosure_line),
        ai_disclosure_enabled=bool(row.ai_disclosure_enabled),
        recording_notice_line=str(row.recording_notice_line),
        recording_notice_enabled=bool(row.recording_notice_enabled),
    )


async def _version_row(session: AsyncSession, version_id: UUID | None) -> Any | None:
    if version_id is None:
        return None
    return (
        await session.execute(
            text("SELECT version, body, structured_script FROM prompt_versions WHERE id = :vid"),
            {"vid": version_id},
        )
    ).first()


def _script_of(version_row: Any | None) -> tuple[CallScript, bool]:
    """The stored version as a `CallScript`, and whether it was freeform.

    A structured version carries JSON we validate back into a `CallScript`; a freeform one
    (NULL `structured_script`) becomes a raw-mode script over its `body`; no version at all
    is an empty structured script ready to author.
    """
    if version_row is None:
        return CallScript(), False
    structured = version_row.structured_script
    if structured is None:
        return CallScript.from_freeform(str(version_row.body)), True
    # Validated rather than trusted: a stored blob is a claim, and a shape the current model
    # rejects should surface as a clean error, not a half-populated editor.
    return CallScript.model_validate(structured), False


async def load_agent_script(
    session: AsyncSession, agent_id: UUID, *, applied: bool = False
) -> LoadedScript:
    """The agent's DRAFT script (or its APPLIED one), as a `CallScript` for the builder.

    `applied=False` (default) loads the draft pointer — what the client is editing.
    `applied=True` loads `live_prompt_id` — what callers currently hear — which the "Undo
    changes" affordance and a "compare to live" view read.
    """
    row = await _agent_or_404(session, agent_id)
    pointer = row.live_prompt_id if applied else row.system_prompt_id
    version_row = await _version_row(session, pointer)
    script, is_freeform = _script_of(version_row)
    return LoadedScript(
        script=script,
        version=int(version_row.version) if version_row is not None else None,
        is_freeform=is_freeform,
        has_pending=row.system_prompt_id != row.live_prompt_id,
    )


async def save_agent_script(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    script: CallScript,
    notes: str | None,
    created_by: UUID | None,
) -> SavedScript:
    """Compile `script` and write it as the next immutable version (staged on a live agent).

    The compile happens HERE, once, so the stored `body` is always the compile of the
    stored structure — there is no path that writes one without the other. Staging vs apply
    is `write_prompt_version`'s decision (it reads the agent's live status), so a structured
    edit and a freeform edit reach a live client's callers by the exact same gate.
    """
    body = compile_call_script(script)
    # `mode="json"` so the stored blob is JSON-native (str/int/list/dict), which is what the
    # `CAST(... AS jsonb)` in `insert_prompt_version` expects and what `model_validate`
    # reads back — no datetimes or enums to smuggle a Python type into the column.
    version = await write_prompt_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        body=body,
        notes=notes,
        created_by=created_by,
        structured_script=script.model_dump(mode="json"),
    )
    row = await _agent_or_404(session, agent_id)
    staged = row.status == "live" and row.system_prompt_id != row.live_prompt_id
    return SavedScript(version=version, staged=staged)


async def compiled_preview(session: AsyncSession, agent_id: UUID, script: CallScript) -> str:
    """The EXACT engine prompt this script would produce — opening, body, platform rules.

    "View compiled prompt" in the builder. It runs the real composer
    (`compose_engine_prompt`) over the real disclosure posture, so what the author sees is
    what the engine holds, INCLUDING the non-removable `TRUTHFUL_ANSWER_DIRECTIVE` appended
    last — which is the point of showing it: a client can watch the platform rules ride
    underneath their own script and cannot make them disappear from the preview.

    A minimal `AgentConfig` is built rather than reusing `agents/service._to_config`,
    because the preview must work for a script that has NOT been saved yet (there is no
    `prompt_versions.body` to join) and for a brand-new agent with no script at all. The
    fields compose actually reads are the system prompt and the opening line; the rest carry
    honest values from the agent row so the preview is not a lie about which agent it is.
    """
    row = await _agent_or_404(session, agent_id)
    config = AgentConfig(
        tenant_id="preview",
        agent_id=str(agent_id),
        name=str(row.name),
        direction=row.direction,
        language_primary=str(row.language_primary),
        system_prompt=compile_call_script(script),
        opening_line=compose_opening_line(_posture(row)),
    )
    return compose_engine_prompt(config)


__all__ = [
    "LoadedScript",
    "SavedScript",
    "assert_agent_visible",
    "compiled_preview",
    "load_agent_script",
    "save_agent_script",
]
