"""Queue Pip to write the AI and recording notices into an agent's opening line (D-971).

Founder, 5 Nov 2026: "When an opening is saved, Pip weaves the notices into that agent's own
opening line in its own words, which the engine then speaks." The opening lines the engine
speaks are checked whenever an agent is put on the voice platform (`service.publish_agent`)
and whenever one of the account's notice switches moves (`publishing.set_account_notices`,
D-1021); a line that does not say exactly the notices switched on is written again by
`workers/opening_notices`. Each line is written for its direction: the opening an inbound
call hears, and the opening of the calls the agent places.

Until it is, nothing is lost: `engine.join_first_words` keeps the stored sentence beside an
opening that does not carry the woven words, so a call never goes out without one.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import CallScript
from calevate_shared.opening_notices import (
    NONE_SAID,
    OpeningNotices,
    SaidNotices,
    WovenNotices,
    kept_by_owner,
    said_in,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.call_notices import AI_NOTICE_SQL, RECORDING_NOTICE_SQL
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
    #: The words of `line` that already say a notice, as woven into it earlier.
    said: SaidNotices = NONE_SAID


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
    """The opening lines of `script` that do not say, in words woven into them, exactly the
    notices `woven` names. An empty line is the first-run writer's to fill, not this one's;
    a line the owner put back over the writer's (Undo) is theirs and keeps the stored
    sentences beside it."""
    fields = [("opening_line", False)]
    if direction == "both":
        fields.append(("outbound_opening_line", True))
    todo: list[OpeningToWeave] = []
    for field, placed in fields:
        line = str(getattr(script, field)).strip()
        notices = notices_of(script, placed=placed)
        if not line or kept_by_owner(notices, line):
            continue
        said = said_in(notices, line)
        if not woven.matches(said, line):
            todo.append(OpeningToWeave(field=field, placed=placed, line=line, said=said))
    return tuple(todo)


def notices_of(script: CallScript, *, placed: bool) -> OpeningNotices:
    """The notice writer's record for one of `script`'s opening lines."""
    return script.outbound_opening_notices if placed else script.opening_notices


async def weave_state(session: AsyncSession, agent_id: UUID) -> WeaveState | None:
    """The agent's working script as `script_builder.replace_opening_line` reads it, or None
    for an agent that is gone, archived, or whose script is one piece of text (its opening is
    the owner's to edit there)."""
    row = (
        await session.execute(
            text(
                f"SELECT a.system_prompt_id, a.direction, {AI_NOTICE_SQL} AS ai_on, "
                f"{RECORDING_NOTICE_SQL} AS recording_on, pv.structured_script, "
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
        ai=bool(row.ai_on),
        recording=bool(row.recording_on) and engine_capabilities().records_audio,
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


#: The job that writes the notices into an Inbound line's or a campaign's own script (D-1021).
HOLDER_WEAVE_JOB: Final = "weave_holder_opening_notices"

HolderKind = Literal["line", "campaign"]

#: A holder's own script, its voice, a stamp that moves with every saved script, and the
#: account's two switches (read on the holder's agent `a`, as every posture reads them).
#: A campaign has no script version, so its stamp is the script's own digest.
_HOLDER_SQL: Final[dict[str, str]] = {
    "line": (
        f"SELECT l.script, l.agent_id, CAST(l.version AS text) AS stamp, {AI_NOTICE_SQL} AS ai_on, "
        f"{RECORDING_NOTICE_SQL} AS recording_on FROM inbound_lines l "
        "JOIN agents a ON a.id = l.agent_id WHERE l.id = :hid AND l.archived_at IS NULL"
    ),
    "campaign": (
        f"SELECT c.script, c.agent_id, md5(CAST(c.script AS text)) AS stamp, {AI_NOTICE_SQL} "
        f"AS ai_on, {RECORDING_NOTICE_SQL} AS recording_on FROM campaigns c "
        "JOIN agents a ON a.id = c.agent_id WHERE c.id = :hid AND c.archived_at IS NULL"
    ),
}

#: Every holder of the account with a script of its own, for a switch flip to re-weave.
_ACCOUNT_HOLDERS_SQL: Final = (
    "SELECT 'line', id FROM inbound_lines WHERE archived_at IS NULL AND script IS NOT NULL "
    "UNION ALL SELECT 'campaign', id FROM campaigns "
    "WHERE archived_at IS NULL AND script IS NOT NULL"
)


@dataclass(frozen=True, slots=True)
class HolderWeaveState:
    """An Inbound line's or a campaign's own script, its notices and the lines that do not
    say them."""

    kind: HolderKind
    holder_id: UUID
    agent_id: UUID
    stamp: str
    script: CallScript
    woven: WovenNotices
    todo: tuple[OpeningToWeave, ...]


def holder_openings(
    kind: HolderKind, script: CallScript, *, woven: WovenNotices
) -> tuple[OpeningToWeave, ...]:
    """The openings of a holder's script that do not say exactly the notices switched on.

    A line answers calls, and may place call-backs with its placed-call opening (D-1019 D2),
    so both its openings are read as a "both" agent's are. A campaign only places calls, so
    its one opening is written as a placed call's (`placed`), kept in `opening_line`."""
    if kind == "line":
        return openings_to_weave(script, direction="both", woven=woven)
    return tuple(
        replace(line, placed=True)
        for line in openings_to_weave(script, direction="inbound", woven=woven)
    )


async def holder_weave_state(
    session: AsyncSession, kind: HolderKind, holder_id: UUID
) -> HolderWeaveState | None:
    """The holder's own script and what is left to weave, or None for a holder that is gone,
    archived or has no script of its own (it speaks its agent's, woven on the agent)."""
    row = (await session.execute(text(_HOLDER_SQL[kind]), {"hid": holder_id})).first()
    if row is None or not isinstance(row.script, dict):
        return None
    woven = WovenNotices(
        ai=bool(row.ai_on),
        recording=bool(row.recording_on) and engine_capabilities().records_audio,
    )
    script = CallScript.model_validate(row.script)
    return HolderWeaveState(
        kind=kind,
        holder_id=holder_id,
        agent_id=UUID(str(row.agent_id)),
        stamp=str(row.stamp),
        script=script,
        woven=woven,
        todo=holder_openings(kind, script, woven=woven),
    )


async def queue_holder_opening_notices(
    session: AsyncSession, *, tenant_id: UUID, kind: HolderKind, holder_id: UUID
) -> bool:
    """Queue the rewrite of a holder's openings that do not say the notices switched on, or
    say one switched off; True when queued. Once per saved script and switch state."""
    state = await holder_weave_state(session, kind, holder_id)
    if state is None or not state.todo:
        return False
    queued = await enqueue_outbox_once(
        session,
        job=HOLDER_WEAVE_JOB,
        payload={
            "tenant_id": str(tenant_id),
            "kind": kind,
            "holder_id": str(holder_id),
            "stamp": state.stamp,
        },
        dedupe_key=(
            f"opening-notices:{kind}:{holder_id}:{state.stamp}:"
            f"{int(state.woven.ai)}{int(state.woven.recording)}"
        ),
    )
    if queued is not None:
        log.info(
            "holder_opening_notices_queued",
            extra={"kind": kind, "holder_id": str(holder_id), "lines": len(state.todo)},
        )
    return queued is not None


async def queue_account_holder_notices(session: AsyncSession, *, tenant_id: UUID) -> int:
    """Queue the rewrite for every Inbound line and campaign of the account with a script of
    its own (D-1021): the account's switch moved, so an opening woven under the old state
    says a notice now off, or lacks one now on. Returns how many were queued."""
    rows = (await session.execute(text(_ACCOUNT_HOLDERS_SQL))).all()
    queued = 0
    for kind, holder_id in rows:
        if await queue_holder_opening_notices(
            session, tenant_id=tenant_id, kind=kind, holder_id=UUID(str(holder_id))
        ):
            queued += 1
    return queued


__all__ = [
    "HOLDER_WEAVE_JOB",
    "WEAVE_JOB",
    "WEAVE_NOTE",
    "HolderKind",
    "HolderWeaveState",
    "OpeningToWeave",
    "WeaveState",
    "holder_openings",
    "holder_weave_state",
    "notices_of",
    "openings_to_weave",
    "queue_account_holder_notices",
    "queue_holder_opening_notices",
    "queue_opening_notices",
    "weave_state",
]
