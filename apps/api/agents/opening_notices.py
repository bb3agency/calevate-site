"""Queue Pip to write the AI and recording notices into an agent's opening line (D-971).

Founder, 5 Nov 2026: "When an opening is saved, Pip weaves the notices into that agent's own
opening line in its own words, which the engine then speaks." The opening lines the engine
speaks are checked whenever an agent is put on the voice platform (`service.publish_agent`)
and whenever a notice switch moves (`publishing.set_disclosure_posture`); a line that does
not say exactly the notices switched on is written again by `workers/opening_notices`.

Until it is, nothing is lost: `engine.join_first_words` keeps the stored sentence beside an
opening that does not say a notice, so a call never goes out without one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from calevate_shared.call_script import CallScript
from calevate_shared.opening_notices import WovenNotices
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.logging import get_logger
from apps.api.engine import engine_capabilities
from apps.api.reliability.service import enqueue_outbox_once

log = get_logger(__name__)

WEAVE_JOB: Final = "weave_opening_notices"

#: The note on the script version the rewrite makes, shown in the script's history.
WEAVE_NOTE: Final = "Opening line now says the notices in its own words"


@dataclass(frozen=True, slots=True)
class OpeningToWeave:
    #: `opening_line`, or `outbound_opening_line` for the calls a "both" agent places (D-920).
    field: str
    placed: bool
    line: str


@dataclass(frozen=True, slots=True)
class WeaveState:
    """The agent's working script, its notices, and the lines that do not say them."""

    prompt_id: UUID
    staged: bool
    woven: WovenNotices
    todo: tuple[OpeningToWeave, ...]


def openings_to_weave(
    script: CallScript, *, direction: str, woven: WovenNotices
) -> tuple[OpeningToWeave, ...]:
    """The opening lines of `script` that do not say exactly the notices `woven` names. An
    empty line is the first-run writer's to fill, not this one's."""
    fields = [("opening_line", False)]
    if direction == "both":
        fields.append(("outbound_opening_line", True))
    return tuple(
        OpeningToWeave(field=field, placed=placed, line=line)
        for field, placed in fields
        if (line := str(getattr(script, field)).strip()) and not woven.matches(line)
    )


async def weave_state(session: AsyncSession, agent_id: UUID) -> WeaveState | None:
    """The agent's working script as `script_builder.replace_opening_line` reads it, or None
    for an agent that is gone, archived, or whose script is one piece of text (its opening is
    the owner's to edit there)."""
    row = (
        await session.execute(
            text(
                "SELECT a.system_prompt_id, a.direction, a.ai_disclosure_enabled, "
                "a.recording_notice_enabled, pv.structured_script, "
                "(a.live_prompt_id IS NOT NULL "
                "AND a.system_prompt_id IS DISTINCT FROM a.live_prompt_id) AS staged "
                "FROM agents a JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL AND a.status <> 'archived'"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None or not isinstance(row.structured_script, dict):
        return None
    woven = WovenNotices(
        ai=bool(row.ai_disclosure_enabled),
        recording=bool(row.recording_notice_enabled) and engine_capabilities().records_audio,
    )
    script = CallScript.model_validate(row.structured_script)
    return WeaveState(
        prompt_id=row.system_prompt_id,
        staged=bool(row.staged),
        woven=woven,
        todo=openings_to_weave(script, direction=str(row.direction), woven=woven),
    )


async def queue_opening_notices(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> bool:
    """Queue the rewrite when an opening line does not say the notices switched on; True when
    queued. Once per script version and switch state: a republish of the same version does
    not ask again, and a version waiting to go live is left until it does."""
    state = await weave_state(session, agent_id)
    if state is None or state.staged or not state.todo:
        return False
    payload: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "prompt_id": str(state.prompt_id),
    }
    queued = await enqueue_outbox_once(
        session,
        job=WEAVE_JOB,
        payload=payload,
        dedupe_key=(
            f"opening-notices:{agent_id}:{state.prompt_id}:"
            f"{int(state.woven.ai)}{int(state.woven.recording)}"
        ),
    )
    if queued is not None:
        log.info(
            "agent_opening_notices_queued",
            extra={"agent_id": str(agent_id), "lines": len(state.todo)},
        )
    return queued is not None


__all__ = [
    "WEAVE_JOB",
    "WEAVE_NOTE",
    "OpeningToWeave",
    "WeaveState",
    "openings_to_weave",
    "queue_opening_notices",
    "weave_state",
]
