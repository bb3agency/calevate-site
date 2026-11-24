"""Pip's script draft for a campaign or an Inbound line, followed live: the draft stream, the
cancel that Stop and the page share, and the compare-and-set Keep reads (Pip live, 24 Nov
2026).

THE STREAM IS A POLL HELD SERVER-SIDE, as the background-job stream is
(`copilot/routes.stream_copilot_job`): the writer stores its phase on the draft itself
(`workers/campaign_script._phase`), and the stream re-reads the holder's row once a second
under the caller's tenant session, so RLS decides what it can see and no broker or pub/sub
channel carries script words (CLAUDE.md "Do NOT"; `live/topics` notes carry no text).

RECONNECTING REPLAYS THE CURRENT STATE. A stream opened on a draft first says where it is
now: its phase, and for a ready draft every line and the diff. So a browser that reconnects
(the HTML Standard's EventSource reconnects on its own after a network error,
https://html.spec.whatwg.org/multipage/server-sent-events.html) needs no `Last-Event-ID`; a
holder with no draft answers 404, which ends the browser's reconnecting.

LINES ARRIVE AT READY, not as the model writes them. Gemini can stream a structured answer as
"valid partial JSON strings that can be concatenated" (https://aistudio.google.com/docs/
structured-output, read 24 Nov 2026), but the writer's first answer is not the draft: it is
edited again, shortened, reviewed and repaired before it is stored, and a refusal moves it to
the next model on the ladder. Lines streamed from the first answer would show the owner words
the draft may not keep, so they are sent once the draft is stored, in script order.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import CallScript
from fastapi.sse import ServerSentEvent
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.script_proposals import (
    WORKING_PHASES,
    DraftPhase,
    LineOp,
    script_diff,
)
from apps.api.campaigns.workspace import CampaignProposal, read_call_script, read_script_proposal
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session

HolderKind = Literal["campaign", "inbound_line"]

#: How often the stream re-reads the draft, and how long one stream stays open: the writer's
#: whole job budget (`core.queue.WORKER_JOB_TIMEOUT_S`). A stream still open after that ends,
#: and the browser's reconnect replays where the draft is.
POLL_S: Final = 1.0
MAX_S: Final = 300.0
#: Sent as the SSE `retry:` field on the first event.
RETRY_MS: Final = 3000

TERMINAL_PHASES: Final[frozenset[str]] = frozenset({"ready", "failed", "cancelled"})


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftPhaseEvent(_Event):
    phase: DraftPhase
    #: Failed: the note the owner reads. Otherwise null.
    detail: str | None = None


class DraftLineEvent(_Event):
    #: The line's script path (`stages.2.sounds_like`).
    path: str
    #: Where it is, in the owner's words (`script_proposals.line_label`).
    label: str
    text: str


class DraftChange(_Event):
    path: str
    label: str
    op: LineOp
    before: str | None
    after: str | None


class DraftDiffEvent(_Event):
    changes: list[DraftChange]
    proposal_id: UUID


class DraftCancelOut(_Event):
    #: False: there was no draft being written to cancel (already written, kept, discarded
    #: or never there). The holder is as it was either way.
    cancelled: bool


@dataclass(frozen=True, slots=True)
class DraftSnapshot:
    """The holder's saved script and its draft, read together."""

    script: CallScript | None
    proposal: CampaignProposal | None
    raw: dict[str, Any] | None


async def read_draft(session: AsyncSession, kind: HolderKind, holder_id: UUID) -> DraftSnapshot:
    """The holder's script and draft, or 404: another account's id and an id nobody minted
    are one answer (RLS hides the row)."""
    if kind == "campaign":
        row = (
            await session.execute(
                text("SELECT script, script_proposal FROM campaigns WHERE id = :hid"),
                {"hid": holder_id},
            )
        ).first()
    else:
        row = (
            await session.execute(
                text(
                    "SELECT script, script_proposal FROM inbound_lines "
                    "WHERE id = :hid AND archived_at IS NULL"
                ),
                {"hid": holder_id},
            )
        ).first()
    if row is None:
        raise ProblemError.not_found("Campaign" if kind == "campaign" else "Inbound line")
    raw = row.script_proposal if isinstance(row.script_proposal, dict) else None
    return DraftSnapshot(
        script=read_call_script(row.script),
        proposal=read_script_proposal(raw, now=datetime.now(UTC)),
        raw=raw,
    )


def phase_of(snapshot: DraftSnapshot) -> DraftPhaseEvent | None:
    """Where the draft is, or None with no draft. A draft not yet picked up by the writer
    reads as `reading`; one the writer abandoned reads as failed (`STALE_AFTER_S`)."""
    proposal, raw = snapshot.proposal, snapshot.raw or {}
    if proposal is None:
        return None
    if proposal.status == "ready":
        return DraftPhaseEvent(phase="ready")
    if proposal.status == "failed":
        return DraftPhaseEvent(phase="failed", detail=proposal.note)
    stored = raw.get("phase")
    return DraftPhaseEvent(phase=stored if stored in WORKING_PHASES else "reading")


def ready_events(
    proposal_id: UUID, base: CallScript | None, script: CallScript
) -> list[ServerSentEvent]:
    """A written draft's lines in script order, then its diff against the script it was
    written from."""
    changes = script_diff(base, script)
    events = [
        ServerSentEvent(
            event="line",
            data=DraftLineEvent(path=c.path, label=c.label, text=c.after or ""),
        )
        for c in changes
        if c.op != "removed"
    ]
    events.append(
        ServerSentEvent(
            event="diff",
            data=DraftDiffEvent(
                proposal_id=proposal_id,
                changes=[
                    DraftChange(path=c.path, label=c.label, op=c.op, before=c.before, after=c.after)
                    for c in changes
                ],
            ),
        )
    )
    return events


async def _snapshot(tenant_id: UUID, kind: HolderKind, holder_id: UUID) -> DraftSnapshot | None:
    try:
        async with tenant_session(tenant_id) as session:
            return await read_draft(session, kind, holder_id)
    except ProblemError:
        # The holder went (an archived line): the stream ends, and a reconnect answers 404.
        return None


async def draft_events(
    tenant_id: UUID, kind: HolderKind, holder_id: UUID
) -> AsyncIterator[ServerSentEvent]:
    """The holder's current draft followed to its end: a `phase` whenever it moves, and at
    ready its lines and diff. Ends after a terminal phase or `MAX_S`.

    A draft that disappears while it is written was stopped, unless the holder's script
    moved with it: a first-run draft (`auto_save`) becomes the script as it is stored, and
    is reported as ready against the script it was written from."""
    first = await _snapshot(tenant_id, kind, holder_id)
    if first is None or first.proposal is None:
        return
    proposal_id, base = first.proposal.id, first.proposal.base_script
    deadline = asyncio.get_running_loop().time() + MAX_S
    snapshot: DraftSnapshot | None = first
    sent: DraftPhaseEvent | None = None
    while True:
        proposal = None if snapshot is None else snapshot.proposal
        if snapshot is None or proposal is None or proposal.id != proposal_id:
            saved = snapshot is not None and snapshot.script not in (None, first.script)
            if saved and snapshot is not None and snapshot.script is not None:
                yield ServerSentEvent(event="phase", data=DraftPhaseEvent(phase="ready"))
                for event in ready_events(proposal_id, base, snapshot.script):
                    yield event
            else:
                yield ServerSentEvent(event="phase", data=DraftPhaseEvent(phase="cancelled"))
            return
        now = phase_of(snapshot)
        if now is not None and now != sent:
            yield ServerSentEvent(event="phase", data=now, retry=RETRY_MS if sent is None else None)
            sent = now
            if now.phase == "ready" and proposal.script is not None:
                for event in ready_events(proposal_id, base, proposal.script):
                    yield event
            if now.phase in TERMINAL_PHASES:
                return
        if asyncio.get_running_loop().time() >= deadline:
            return
        await asyncio.sleep(POLL_S)
        snapshot = await _snapshot(tenant_id, kind, holder_id)


async def ready_script(
    session: AsyncSession, kind: HolderKind, holder_id: UUID, proposal_id: UUID
) -> CallScript:
    """The written draft Keep saves, read under the holder's row lock: the compare-and-set
    Keep is guarded by. A draft replaced, stopped or kept since the browser saw it is a 409,
    so an old screen can never put a script live that is no longer the one on offer; another
    account's holder is a 404."""
    if kind == "campaign":
        row = (
            await session.execute(
                text("SELECT script_proposal FROM campaigns WHERE id = :hid FOR UPDATE"),
                {"hid": holder_id},
            )
        ).first()
    else:
        row = (
            await session.execute(
                text(
                    "SELECT script_proposal FROM inbound_lines "
                    "WHERE id = :hid AND archived_at IS NULL FOR UPDATE"
                ),
                {"hid": holder_id},
            )
        ).first()
    if row is None:
        raise ProblemError.not_found("Campaign" if kind == "campaign" else "Inbound line")
    proposal = read_script_proposal(row.script_proposal, now=datetime.now(UTC))
    if proposal is None or proposal.id != proposal_id:
        raise ProblemError.conflict(
            "script_draft_stale",
            "This draft is no longer the one Pip has ready.",
            remediation="Open the script again to see Pip's latest draft.",
        )
    if proposal.status != "ready" or proposal.script is None:
        raise ProblemError.conflict(
            "script_draft_not_ready",
            "Pip has not finished this draft.",
            remediation="Wait for it to appear, then keep it.",
        )
    return proposal.script


async def cancel_draft(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    holder_kind: HolderKind,
    holder_id: UUID,
    proposal_id: UUID,
) -> bool:
    """Cancel a draft still being written, by compare-and-set on its id, and leave the holder
    as it was before it was asked for: its script is never touched, and a campaign gets back
    the switch-back copy the request replaced (`workspace.request_proposal`'s `before_pip`).
    The writer's job sees the draft gone at its next phase and ends without storing anything
    (`workers/campaign_script._phase`). Returns whether a draft was cancelled; a written
    draft is left for Discard. Pip's Stop calls this for the drafts its run started."""
    if holder_kind == "campaign":
        done = (
            await session.execute(
                text(
                    "UPDATE campaigns SET "
                    "script_before_pip = CASE WHEN script_proposal ? 'before_pip' "
                    "THEN NULLIF(script_proposal->'before_pip'->'script', 'null'::jsonb) "
                    "ELSE script_before_pip END, "
                    "script_before_pip_at = CASE WHEN script_proposal ? 'before_pip' "
                    "THEN CAST(script_proposal->'before_pip'->>'at' AS timestamptz) "
                    "ELSE script_before_pip_at END, "
                    "script_proposal = NULL "
                    "WHERE id = :hid AND tenant_id = :t AND script_proposal->>'id' = :pid "
                    "AND script_proposal->>'status' = 'drafting' RETURNING id"
                ),
                {"hid": holder_id, "t": tenant_id, "pid": str(proposal_id)},
            )
        ).first()
    else:
        done = (
            await session.execute(
                text(
                    "UPDATE inbound_lines SET script_proposal = NULL "
                    "WHERE id = :hid AND tenant_id = :t AND script_proposal->>'id' = :pid "
                    "AND script_proposal->>'status' = 'drafting' RETURNING id"
                ),
                {"hid": holder_id, "t": tenant_id, "pid": str(proposal_id)},
            )
        ).first()
    return done is not None


__all__ = [
    "MAX_S",
    "POLL_S",
    "DraftCancelOut",
    "DraftChange",
    "DraftDiffEvent",
    "DraftLineEvent",
    "DraftPhaseEvent",
    "DraftSnapshot",
    "HolderKind",
    "cancel_draft",
    "draft_events",
    "phase_of",
    "read_draft",
    "ready_events",
    "ready_script",
]
