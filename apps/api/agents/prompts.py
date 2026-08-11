"""Prompt versioning + rollback (ROADMAP M2 "admin polish: prompt rollback" — backend).

Same doctrine as the KB (FLOWS §7): versions are IMMUTABLE history and rollback is
REPUBLISHING, not restoring. A rollback mints a NEW version whose body is copied from
the target — copy-forward, never pointer-rewind — so `agents.system_prompt_id` only
ever moves to a higher version and the audit trail never shows an agent silently
pointing backwards in time. No code path here UPDATEs an existing `prompt_versions`
row.

Engine coherence: when the agent is LIVE (`status='live'` with an
`engine_agent_ref`), the write/rollback re-publishes through
`agents.service.publish_agent` in the SAME transaction — a prompt change that only
lands in our DB is a lie on the admin screen. The engine push happens AFTER the local
rows are written but INSIDE the transaction, so an engine failure rolls back the new
version and the pointer together (the same "never claim what the engine doesn't have"
ordering argument as `kb.publish_source`). Draft agents skip the engine entirely.

Notes live in the real `notes` column (migration 2faa301dc488): operator-facing
metadata about a version, kept apart from `compiled_t0_context`, which D-39 reserves
for the T0 compiler's build artifact — that compiler is `agents/t0.py`, and it mints
its versions through `insert_prompt_version` below rather than through an INSERT of
its own.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.service import publish_agent
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of

log = get_logger(__name__)


async def _agent_state(session: AsyncSession, agent_id: UUID) -> tuple[str, str | None]:
    """(status, engine_agent_ref) — and the existence check, so a bad agent id is a
    clean 404 rather than an FK IntegrityError from the version insert."""
    row = (
        await session.execute(
            text(
                "SELECT status, engine_agent_ref FROM agents WHERE id = :aid AND deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return str(row[0]), row[1]


def _is_live(status: str, engine_agent_ref: str | None) -> bool:
    return status == "live" and bool(engine_agent_ref)


async def insert_prompt_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    body: str,
    notes: str | None,
    created_by: UUID | None,
    compiled_t0_context: str | None = None,
) -> int:
    """INSERT the next version and move the agent's pointer to it. Never an UPDATE of
    an existing version row — that is the immutability invariant, enforced by shape.

    `published_at` is set at insert: pointing the agent at a version IS publishing it
    here (creation and activation are one step, unlike the KB's approval gate).

    `compiled_t0_context` is the T0 compiler's build artifact (D-39) and is stamped at
    INSERT for the same reason: writing it onto an existing row afterwards would rewrite
    what an earlier publish said. It stays None for a hand-written version — the writer
    supplied a body, not a compiled block, and claiming otherwise would make
    `agents/t0.py` recompile from an artifact nobody built.

    Public because it is the one place a `prompt_versions` row may be born:
    `agents/t0.py`'s recompile mints versions too (FLOWS §7), and a second insert
    statement is a second chance to forget the pointer, the UNIQUE race or the artifact.
    """
    current = (
        await session.execute(
            text("SELECT COALESCE(max(version), 0) FROM prompt_versions WHERE agent_id = :aid"),
            {"aid": agent_id},
        )
    ).scalar()
    version = int(current or 0) + 1
    version_id = uuid7()
    try:
        await session.execute(
            text(
                "INSERT INTO prompt_versions (id, tenant_id, agent_id, version, body, "
                "compiled_t0_context, notes, created_by, published_at, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :version, :body, :compiled, :notes, :by, now(), "
                "now(), now())"
            ),
            {
                "id": version_id,
                "tid": tenant_id,
                "aid": agent_id,
                "version": version,
                "body": body,
                "compiled": compiled_t0_context,
                "notes": notes,
                "by": created_by,
            },
        )
    except IntegrityError as exc:
        # UNIQUE(agent_id, version): two operators wrote at once and this one lost.
        # A lost race is a conflict, not a retry-with-n+2 (BACKEND-PATTERNS §5).
        raise ProblemError.conflict(
            "prompt_version_conflict",
            "Another prompt version was written for this agent at the same time.",
            remediation="Reload the version history and submit again.",
        ) from exc
    result = await session.execute(
        text(
            "UPDATE agents SET system_prompt_id = :vid, updated_at = now() "
            "WHERE id = :aid AND deleted_at IS NULL"
        ),
        {"vid": version_id, "aid": agent_id},
    )
    if rowcount_of(result) == 0:
        # The agent was deleted between the state read and the pointer write.
        raise ProblemError.not_found("Agent")
    return version


async def write_prompt_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    body: str,
    notes: str | None,
    created_by: UUID | None,
) -> int:
    """New immutable version; the agent points at it; a LIVE agent is re-published."""
    status, engine_ref = await _agent_state(session, agent_id)
    version = await insert_prompt_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        body=body,
        notes=notes,
        created_by=created_by,
    )
    if _is_live(status, engine_ref):
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    # ids and version only — prompt bodies can embed client business detail (rule 6).
    log.info(
        "prompt_version_written",
        extra={"agent_id": str(agent_id), "version": version, "live": _is_live(status, engine_ref)},
    )
    return version


async def list_prompt_versions(session: AsyncSession, agent_id: UUID) -> list[dict[str, Any]]:
    """History, newest first. `active` = the version `agents.system_prompt_id` names —
    derived from the pointer rather than stored, so it cannot drift."""
    rows = (
        await session.execute(
            text(
                "SELECT pv.id, pv.version, pv.notes, pv.created_at, "
                "(pv.id = a.system_prompt_id) AS active "
                "FROM prompt_versions pv JOIN agents a ON a.id = pv.agent_id "
                "WHERE pv.agent_id = :aid ORDER BY pv.version DESC"
            ),
            {"aid": agent_id},
        )
    ).all()
    return [
        {
            "id": r[0],
            "version": int(r[1]),
            "notes": r[2],
            "created_at": r[3],
            "active": bool(r[4]),
        }
        for r in rows
    ]


async def rollback_prompt(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    version: int,
    created_by: UUID | None = None,
) -> int:
    """Republish an earlier version's body as a NEW version and point the agent at it.

    Copy-forward keeps the history linear: v1..vN stay exactly as written, and the
    rollback itself is a visible, audited entry rather than a mutation of the past.
    Returns the NEW version number.
    """
    status, engine_ref = await _agent_state(session, agent_id)
    target = (
        await session.execute(
            text("SELECT body FROM prompt_versions WHERE agent_id = :aid AND version = :v"),
            {"aid": agent_id, "v": version},
        )
    ).first()
    if target is None:
        raise ProblemError.not_found("Prompt version")
    new_version = await insert_prompt_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        body=str(target[0]),
        notes=f"rollback to v{version}",
        created_by=created_by,
    )
    if _is_live(status, engine_ref):
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    log.info(
        "prompt_rolled_back",
        extra={"agent_id": str(agent_id), "to_version": version, "new_version": new_version},
    )
    return new_version


__all__ = [
    "insert_prompt_version",
    "list_prompt_versions",
    "rollback_prompt",
    "write_prompt_version",
]
