"""The rules of an inbound line (D-997, founder 16 Nov 2026).

A line says what one or more of the business's numbers say when called, in the voice of one
of its agents: the owner's main task, the sources from What your agents know it was written
from, its own call script (Pip writes it, the owner reviews it), and which of the agent's
actions it uses. Several numbers may share a line; a line may be a draft with no number, so a
trial account's first test call has something to ring.

The script and Pip's draft have the campaign's shape and readers
(`campaigns.workspace.read_call_script` / `read_script_proposal`), and Pip's draft is written
by the campaign's script writer, so a line and a campaign are reviewed the same way.

What reaches callers is the line's own engine agent (`inbound/publish.py`); nothing here talks
to the calling platform.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from calevate_shared.call_script import CallScript
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.field_suggestions import queue_job
from apps.api.campaigns import step_outcomes
from apps.api.campaigns.notes import starting_fields
from apps.api.campaigns.workspace import (
    MAIN_TASK_MAX,
    CampaignProposal,
    read_call_script,
    read_script_proposal,
)
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.kb.picks import LINE_PICKS, read_picks, replace_picks
from apps.api.reliability.service import enqueue_outbox

NAME_MAX: Final = 80
#: An action slug as `agent_tools` names it; a line can only switch off what an agent has.
ACTION_SLUG_MAX: Final = 64
#: The job that writes a line's script (`workers/campaign_script.draft_line_script`).
LINE_SCRIPT_JOB: Final = "draft_line_script"
DEFAULT_NAME: Final = "Calls to your number"
#: Most lines one account keeps open (archived ones do not count): the lines list is read
#: under it. Far past any business's numbers and the uses it puts them to.
MAX_LINES: Final = 50

ScriptProposal = CampaignProposal


@dataclass(frozen=True)
class LineNumber:
    id: UUID
    e164: str


@dataclass(frozen=True)
class Line:
    id: UUID
    name: str
    agent_id: UUID
    agent_name: str
    main_task: str
    script: CallScript | None
    proposal: ScriptProposal | None
    #: Moves on every saved script; `published_at` is when the version now live went out.
    version: int
    published_at: datetime | None
    engine_agent_ref: str | None
    actions_off: tuple[str, ...]
    sources: tuple[UUID, ...]
    numbers: tuple[LineNumber, ...]
    created_at: datetime

    @property
    def live(self) -> bool:
        """Its own engine agent holds the saved script, so a caller hears this line."""
        return self.engine_agent_ref is not None and self.published_at is not None


_LINES_SQL: Final = """
SELECT l.id, l.name, l.agent_id, a.name AS agent_name, l.main_task, l.script,
       l.script_proposal, l.version, l.published_at, l.engine_agent_ref, l.actions_off,
       l.created_at
FROM inbound_lines l JOIN agents a ON a.id = l.agent_id
WHERE l.archived_at IS NULL {where}
ORDER BY l.created_at, l.id
LIMIT :max_lines
"""


def _invalid(code: str, title: str, detail: str) -> ProblemError:
    return ProblemError(kind="validation", code=code, title=title, detail=detail)


def _clean(value: str, *, limit: int, field: str) -> str:
    cleaned = value.strip()
    if len(cleaned) > limit:
        raise _invalid(
            f"{field}_too_long", "That is too long", f"Keep this under {limit:,} characters."
        )
    return cleaned


async def _lines(session: AsyncSession, line_id: UUID | None = None) -> list[Line]:
    where = "AND l.id = :lid" if line_id is not None else ""
    rows = (
        await session.execute(
            text(_LINES_SQL.format(where=where)), {"lid": line_id, "max_lines": MAX_LINES}
        )
    ).all()
    if not rows:
        return []
    ids = [row.id for row in rows]
    numbers: dict[UUID, list[LineNumber]] = defaultdict(list)
    for nid, lid, e164 in (
        await session.execute(
            text(
                "SELECT id, inbound_line_id, e164 FROM phone_numbers "
                "WHERE inbound_line_id = ANY(:ids) AND released_at IS NULL ORDER BY e164"
            ),
            {"ids": ids},
        )
    ).all():
        numbers[lid].append(LineNumber(id=nid, e164=str(e164)))
    sources = await read_picks(session, LINE_PICKS, ids)
    now = datetime.now(UTC)
    return [
        Line(
            id=row.id,
            name=str(row.name),
            agent_id=row.agent_id,
            agent_name=str(row.agent_name),
            main_task=row.main_task or "",
            script=read_call_script(row.script),
            proposal=read_script_proposal(row.script_proposal, now=now),
            version=int(row.version),
            published_at=row.published_at,
            engine_agent_ref=row.engine_agent_ref,
            actions_off=tuple(row.actions_off or ()),
            sources=tuple(sources[row.id]),
            numbers=tuple(numbers[row.id]),
            created_at=row.created_at,
        )
        for row in rows
    ]


async def list_lines(session: AsyncSession) -> list[Line]:
    """Every line of the session's account that is not archived, oldest first. RLS scopes it."""
    return await _lines(session)


async def read_line(session: AsyncSession, line_id: UUID) -> Line:
    """One line, or 404: another account's id and an id nobody minted are one answer."""
    found = await _lines(session, line_id)
    if not found:
        raise ProblemError.not_found("Inbound line")
    return found[0]


async def _lock(session: AsyncSession, line_id: UUID) -> Any:
    row = (
        await session.execute(
            text(
                "SELECT id, tenant_id, agent_id, main_task, script, script_proposal, version "
                "FROM inbound_lines WHERE id = :lid AND archived_at IS NULL FOR UPDATE"
            ),
            {"lid": line_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Inbound line")
    return row


async def _refuse_unusable_agent(session: AsyncSession, agent_id: UUID) -> None:
    """A line speaks in the voice of a working agent of this account. RLS hides another
    account's agent, so it reads as missing."""
    found = (
        await session.execute(
            text(
                "SELECT 1 FROM agents WHERE id = :aid AND deleted_at IS NULL "
                "AND status <> 'archived'"
            ),
            {"aid": agent_id},
        )
    ).first()
    if found is None:
        raise ProblemError.not_found("Agent")


async def create_line(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    name: str | None = None,
    main_task: str | None = None,
    script: CallScript | None = None,
    created_by: UUID | None,
) -> UUID:
    """A new line in `agent_id`'s voice, a draft until its script is saved and published.
    Refused past `MAX_LINES` open lines; the account row is locked first, so two at once
    cannot both take the last place."""
    await _refuse_unusable_agent(session, agent_id)
    await session.execute(
        text("SELECT 1 FROM organizations WHERE id = :t FOR UPDATE"), {"t": tenant_id}
    )
    open_lines = (
        await session.execute(text("SELECT count(*) FROM inbound_lines WHERE archived_at IS NULL"))
    ).scalar_one()
    if int(open_lines) >= MAX_LINES:
        raise ProblemError.business_rule(
            "inbound_lines_full",
            f"You have {MAX_LINES} lines.",
            remediation="Archive a line you no longer use, then add this one.",
        )
    line_id = uuid7()
    # A new line notes what its voice's starting list holds, so it never starts noting
    # nothing; it is the line's own list from then on (D-1028).
    notes = await starting_fields(session, tenant_id=tenant_id)
    await session.execute(
        text(
            "INSERT INTO inbound_lines (id, tenant_id, name, agent_id, main_task, script, "
            "extraction_fields, created_by) "
            "VALUES (:id, :t, :n, :a, :m, CAST(:s AS jsonb), CAST(:f AS jsonb), :by)"
        ),
        {
            "f": json.dumps(notes),
            "id": line_id,
            "t": tenant_id,
            "n": _clean(name or "", limit=NAME_MAX, field="name") or DEFAULT_NAME,
            "a": agent_id,
            "m": _clean(main_task or "", limit=MAIN_TASK_MAX, field="main_task") or None,
            "s": script.model_dump_json() if script is not None else None,
            "by": created_by,
        },
    )
    await queue_job(session, "line", line_id)
    await step_outcomes.queue_after_save(session, "line", line_id, script)
    return line_id


async def update_line(
    session: AsyncSession,
    line_id: UUID,
    *,
    name: str | None = None,
    agent_id: UUID | None = None,
    main_task: str | None = None,
) -> bool:
    """Rename the line, give it another agent's voice, or save its main task. Returns whether
    what callers hear changed (a new voice), so the caller republishes it."""
    row = await _lock(session, line_id)
    sets: list[str] = []
    params: dict[str, Any] = {"lid": line_id}
    if name is not None:
        cleaned = _clean(name, limit=NAME_MAX, field="name")
        if not cleaned:
            raise _invalid("name_required", "Name this line", "Give the line a short name.")
        sets.append("name = :n")
        params["n"] = cleaned
    voice_changed = agent_id is not None and agent_id != row.agent_id
    if voice_changed:
        assert agent_id is not None
        await _refuse_unusable_agent(session, agent_id)
        sets.append("agent_id = :a")
        params["a"] = agent_id
        # The numbers follow the line's voice: the rest of the product reads a number's
        # agent (`phone_numbers.agent_id`) for what it does.
        await session.execute(
            text("UPDATE phone_numbers SET agent_id = :a WHERE inbound_line_id = :lid"),
            {"a": agent_id, "lid": line_id},
        )
        # The line's knowledge claims and its route are keyed on the agent as well as the
        # line; left on the old agent, that agent's next move would relabel or drop them.
        await session.execute(
            text("UPDATE engine_kb_routes SET agent_id = :a WHERE inbound_line_id = :lid"),
            {"a": agent_id, "lid": line_id},
        )
        await session.execute(
            text("UPDATE engine_agent_routes SET agent_id = :a WHERE inbound_line_id = :lid"),
            {"a": agent_id, "lid": line_id},
        )
    if main_task is not None:
        sets.append("main_task = :m")
        params["m"] = _clean(main_task, limit=MAIN_TASK_MAX, field="main_task") or None
    if sets:
        await session.execute(
            text(f"UPDATE inbound_lines SET {', '.join(sets)}, updated_at = now() WHERE id = :lid"),
            params,
        )
    if main_task is not None:
        await queue_job(session, "line", line_id)
    return voice_changed


async def set_sources(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    line_id: UUID,
    kb_source_ids: list[UUID],
    created_by: UUID | None,
) -> None:
    """The sources from What your agents know that Pip writes this line from, replacing the
    last choice. A source of another account is invisible under RLS and refused as missing."""
    await _lock(session, line_id)
    await replace_picks(
        session,
        LINE_PICKS,
        tenant_id=tenant_id,
        holder_id=line_id,
        kb_source_ids=kb_source_ids,
        created_by=created_by,
    )


async def set_actions_off(session: AsyncSession, line_id: UUID, slugs: list[str]) -> None:
    """Which of its agent's actions this line does not use; every other one is on."""
    await _lock(session, line_id)
    cleaned = sorted({s.strip() for s in slugs if s.strip()})
    if any(len(s) > ACTION_SLUG_MAX for s in cleaned):
        raise _invalid("action_unknown", "Unknown action", "Choose from the agent's actions.")
    await session.execute(
        text("UPDATE inbound_lines SET actions_off = :a, updated_at = now() WHERE id = :lid"),
        {"a": cleaned, "lid": line_id},
    )


async def save_script(session: AsyncSession, line_id: UUID, script: CallScript) -> int:
    """The owner's edit, or a reviewed Pip draft they kept. Measured as the line's own engine
    agent put-live sends, notes and call-back rules included, so a publish is never refused
    for its length. Returns the new version. Pip repairs any line the script checks fault once
    the owner stops saving (`agents/script_heal`)."""
    from apps.api.agents import script_builder, script_heal

    row = await _lock(session, line_id)
    await script_builder.refuse_job_if_too_long(
        session, kind="line", tenant_id=UUID(str(row.tenant_id)), job_id=line_id, script=script
    )
    version = (
        await session.execute(
            text(
                "UPDATE inbound_lines SET script = CAST(:s AS jsonb), version = version + 1, "
                "updated_at = now() WHERE id = :lid RETURNING version"
            ),
            {"s": script.model_dump_json(), "lid": line_id},
        )
    ).scalar_one()
    await queue_job(session, "line", line_id)
    await script_heal.queue_after_save(session, "line", line_id, script)
    await step_outcomes.queue_after_save(session, "line", line_id, script)
    return int(version)


async def request_proposal(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    line_id: UUID,
    requested_by: UUID | None,
    auto_save: bool = False,
    ask: dict[str, str] | None = None,
) -> ScriptProposal:
    """Ask Pip for the line's script. Needs a main task; replaces a ready draft; refused
    while one is still being written, so a second click does not spend twice.

    `auto_save`: the draft becomes the line's script as soon as it is written, with no
    review, while the line has none (the first run's line, Phase 3b).

    `ask` (`{"tone": ..., "instruction": ...}`, either may be absent) is how the owner wants
    this draft written, stored as a campaign's is (`campaigns.workspace.request_proposal`)."""
    row = await _lock(session, line_id)
    if not (row.main_task or "").strip():
        raise _invalid(
            "main_task_required",
            "Write the main task first",
            "Write the main task first, so Pip knows what callers need.",
        )
    now = datetime.now(UTC)
    pending = read_script_proposal(row.script_proposal, now=now)
    if pending is not None and pending.status == "drafting":
        raise ProblemError.conflict(
            "line_script_in_progress",
            "Pip is still writing this line's script.",
            remediation="Wait for it to appear, or press Stop first.",
        )
    proposal_id = uuid7()
    record: dict[str, Any] = {
        "id": str(proposal_id),
        "status": "drafting",
        "requested_at": now.isoformat(),
        "requested_by": None if requested_by is None else str(requested_by),
        "base_script": row.script,
    }
    if ask:
        record["ask"] = ask
    if auto_save:
        record["auto_save"] = True
    await session.execute(
        text("UPDATE inbound_lines SET script_proposal = CAST(:p AS jsonb) WHERE id = :lid"),
        {"p": json.dumps(record), "lid": line_id},
    )
    await enqueue_outbox(
        session,
        job=LINE_SCRIPT_JOB,
        payload={
            "tenant_id": str(tenant_id),
            "line_id": str(line_id),
            "proposal_id": str(proposal_id),
        },
    )
    proposal = read_script_proposal(record, now=now)
    assert proposal is not None
    return proposal


async def clear_proposal(session: AsyncSession, line_id: UUID, proposal_id: UUID) -> None:
    """Stop a draft being written, or discard or settle a written one. The job writes back by
    compare-and-set on the id, so a stopped draft is never resurrected."""
    await _lock(session, line_id)
    done = (
        await session.execute(
            text(
                "UPDATE inbound_lines SET script_proposal = NULL WHERE id = :lid "
                "AND script_proposal->>'id' = :pid RETURNING id"
            ),
            {"lid": line_id, "pid": str(proposal_id)},
        )
    ).first()
    if done is None:
        raise ProblemError.not_found("Draft")


async def assign_number(session: AsyncSession, line_id: UUID, number_id: UUID) -> UUID | None:
    """Put a number on this line; returns the line it answered for before, if another. The
    number takes calls from now on (`inbound` or `both`), and its agent is the line's voice,
    which is what the rest of the product reads a number's agent for."""
    row = await _lock(session, line_id)
    number = (
        await session.execute(
            text(
                "SELECT inbound_line_id, direction FROM phone_numbers "
                "WHERE id = :nid AND released_at IS NULL FOR UPDATE"
            ),
            {"nid": number_id},
        )
    ).first()
    if number is None:
        raise ProblemError.not_found("Phone number")
    await session.execute(
        text(
            "UPDATE phone_numbers SET inbound_line_id = :lid, agent_id = :a, "
            "direction = CASE WHEN direction = 'outbound' THEN 'both' ELSE direction END, "
            "updated_at = now() WHERE id = :nid"
        ),
        {"lid": line_id, "a": row.agent_id, "nid": number_id},
    )
    before = number.inbound_line_id
    return before if before is not None and before != line_id else None


async def first_line(session: AsyncSession) -> UUID | None:
    """The account's oldest line whose agent can still speak, which answers a newly bought
    number (founder, 16 Nov 2026). A line in a deleted agent's voice is passed over: it can
    never be put live (`publish_line` refuses it), so a number on it would ring nothing.
    None when no such line exists and the owner is asked to make one."""
    return (
        await session.execute(
            text(
                "SELECT l.id FROM inbound_lines l JOIN agents a ON a.id = l.agent_id "
                "WHERE l.archived_at IS NULL AND a.deleted_at IS NULL "
                "AND a.status <> 'archived' ORDER BY l.created_at, l.id LIMIT 1"
            )
        )
    ).scalar_one_or_none()


async def archive_line(session: AsyncSession, line_id: UUID) -> str | None:
    """Archive a line that answers no number; returns its engine agent to retire. Every
    number always has a line (founder, 16 Nov 2026), so one that still answers is refused."""
    await _lock(session, line_id)
    answering = (
        await session.execute(
            text(
                "SELECT count(*) FROM phone_numbers WHERE inbound_line_id = :lid "
                "AND released_at IS NULL"
            ),
            {"lid": line_id},
        )
    ).scalar_one()
    if answering:
        raise ProblemError.business_rule(
            "line_answers_numbers",
            "This line still answers a number.",
            remediation="Move its numbers to another line first.",
        )
    return (
        await session.execute(
            text(
                "UPDATE inbound_lines SET archived_at = now(), updated_at = now() "
                "WHERE id = :lid RETURNING engine_agent_ref"
            ),
            {"lid": line_id},
        )
    ).scalar_one_or_none()


__all__ = [
    "DEFAULT_NAME",
    "LINE_SCRIPT_JOB",
    "MAX_LINES",
    "NAME_MAX",
    "Line",
    "LineNumber",
    "ScriptProposal",
    "archive_line",
    "assign_number",
    "clear_proposal",
    "create_line",
    "first_line",
    "list_lines",
    "read_line",
    "request_proposal",
    "save_script",
    "set_actions_off",
    "set_sources",
    "update_line",
]
