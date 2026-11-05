"""The one queue for an AI pass that reads an agent and writes its answer onto the agent row.

Two passes use it: the lead-detail suggestions (D-889, `agents/field_suggestions`) and the
caller-help judgement (`agents/caller_help`). Each owns four columns named after it,
`<column>_state`, `<column>_at`, `<column>_inputs` and the answer `<column>`, and one ARQ job.

The state ladder is `queued -> running -> done | failed | skipped`. A pass asked for while one
runs leaves the row `queued` with no job; the running pass sees that when it closes and queues
the next itself, so a change made mid-pass is never lost and two passes never run at once.
`<column>_inputs` holds the hash of what the last finished pass read, so a pass whose inputs
are unchanged spends nothing and triggers can be generous.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.transition import _identifier
from apps.api.reliability.service import enqueue_outbox

#: A pass `queued` or `running` longer than this has no live job behind it (a worker killed
#: mid-way) and may be queued again.
STALE_MINUTES: Final = 15


@dataclass(frozen=True, slots=True)
class PassSlot:
    """One pass's columns on `agents` and its job. `column` is a constant of ours, never input,
    which is what makes formatting it into SQL safe."""

    column: str
    job: str

    @property
    def state(self) -> str:
        return f"{self.column}_state"

    @property
    def at(self) -> str:
        return f"{self.column}_at"

    @property
    def inputs(self) -> str:
        return f"{self.column}_inputs"


def _on_slot(slot: PassSlot, sql: str) -> str:
    """`sql` with `{state}`, `{at}`, `{inputs}` and `{dead}` filled from the slot's columns.

    Each column goes through `_identifier()` here, so the promise in `PassSlot`'s docstring is
    checked at runtime and `scripts/check_raw_sql.py` can see it was: an attribute read such as
    `slot.state` is text that check cannot trace to a literal."""
    state = _identifier(slot.state, "pass state column")
    at = _identifier(slot.at, "pass time column")
    inputs = _identifier(slot.inputs, "pass inputs column")
    dead = (
        f"({state} IN ('queued', 'running') AND {at} < now() - interval '{STALE_MINUTES} minutes')"
    )
    return sql.format(state=state, at=at, inputs=inputs, dead=dead)


def dead_sql(slot: PassSlot) -> str:
    """True in SQL for a pass `queued` or `running` past `STALE_MINUTES`: no live job behind it."""
    return _on_slot(slot, "{dead}")


async def queue(
    session: AsyncSession, slot: PassSlot, *, tenant_id: UUID, agent_id: UUID, force: bool = False
) -> bool:
    """Ask for a pass over this agent, in the caller's transaction. True when a job was queued.

    A pass already queued is left as it is; one running is marked `queued` without a job. A
    dead one gets a fresh job, and the worker's claim lets only one of two run. `force`
    forgets the last reading's hash so the pass reads afresh even when nothing changed; it is
    on the row, not the job, because a pass already queued is the one that runs."""
    if force:
        await session.execute(
            text(_on_slot(slot, "UPDATE agents SET {inputs} = NULL WHERE id = :aid")),
            {"aid": agent_id},
        )
    prev = (
        await session.execute(
            text(
                _on_slot(
                    slot,
                    "WITH prev AS (SELECT {state} AS state, {dead} AS dead "
                    "  FROM agents WHERE id = :aid AND deleted_at IS NULL FOR UPDATE) "
                    "UPDATE agents a SET {state} = 'queued', {at} = now() FROM prev "
                    "WHERE a.id = :aid AND (prev.state IS DISTINCT FROM 'queued' OR prev.dead) "
                    "RETURNING prev.state, prev.dead",
                )
            ),
            {"aid": agent_id},
        )
    ).first()
    if prev is None:
        return False
    if prev[0] == "running" and not prev[1]:
        return False
    await enqueue(session, slot, tenant_id=tenant_id, agent_id=agent_id)
    return True


async def enqueue(
    session: AsyncSession, slot: PassSlot, *, tenant_id: UUID, agent_id: UUID
) -> None:
    """Promise the pass job with no state change: `queue` decides whether one is due."""
    await enqueue_outbox(
        session, job=slot.job, payload={"tenant_id": str(tenant_id), "agent_id": str(agent_id)}
    )


async def queue_first(
    session: AsyncSession, slot: PassSlot, *, tenant_id: UUID, agent_id: UUID
) -> bool:
    """The agent's first pass, once: a no-op when any pass was ever queued for it."""
    state = (
        await session.execute(
            text(_on_slot(slot, "SELECT {state} FROM agents WHERE id = :aid")), {"aid": agent_id}
        )
    ).first()
    if state is None or state[0] is not None:
        return False
    return await queue(session, slot, tenant_id=tenant_id, agent_id=agent_id)


async def claim(
    session: AsyncSession, slot: PassSlot, *, agent_id: UUID
) -> tuple[bool, str | None]:
    """Move a queued pass to `running`. Answers whether it was claimed, and the hash of the
    inputs the last finished pass read."""
    row = (
        await session.execute(
            text(
                _on_slot(
                    slot,
                    "UPDATE agents SET {state} = 'running', {at} = now(), "
                    "updated_at = now() WHERE id = :aid AND {state} = 'queued' "
                    "AND deleted_at IS NULL RETURNING {inputs}",
                )
            ),
            {"aid": agent_id},
        )
    ).first()
    return (row is not None, row[0] if row is not None else None)


async def finish(
    session: AsyncSession, slot: PassSlot, *, tenant_id: UUID, agent_id: UUID, state: str
) -> None:
    """Close the pass, or, when it was asked for again while it ran, start the next one."""
    closed = (
        await session.execute(
            text(
                _on_slot(
                    slot,
                    "UPDATE agents SET {state} = :state, {at} = now(), "
                    "updated_at = now() WHERE id = :aid AND {state} = 'running' RETURNING id",
                )
            ),
            {"state": state, "aid": agent_id},
        )
    ).first()
    if closed is None:
        await requeue_if_asked(session, slot, tenant_id=tenant_id, agent_id=agent_id)


async def requeue_if_asked(
    session: AsyncSession, slot: PassSlot, *, tenant_id: UUID, agent_id: UUID
) -> None:
    again = (
        await session.execute(
            text(_on_slot(slot, "SELECT {state} FROM agents WHERE id = :aid")), {"aid": agent_id}
        )
    ).scalar()
    if again == "queued":
        await enqueue(session, slot, tenant_id=tenant_id, agent_id=agent_id)


__all__ = [
    "STALE_MINUTES",
    "PassSlot",
    "claim",
    "dead_sql",
    "enqueue",
    "finish",
    "queue",
    "queue_first",
    "requeue_if_asked",
]
