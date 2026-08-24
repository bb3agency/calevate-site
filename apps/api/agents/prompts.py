"""Prompt versioning + rollback (ROADMAP M2 "admin polish: prompt rollback" — backend).

Same doctrine as the KB (FLOWS §7): versions are IMMUTABLE history and rollback is
REPUBLISHING, not restoring. A rollback mints a NEW version whose body is copied from
the target — copy-forward, never pointer-rewind — so `agents.system_prompt_id` only
ever moves to a higher version and the audit trail never shows an agent silently
pointing backwards in time. No code path here UPDATEs an existing `prompt_versions`
row.

TWO SPEEDS (SURFACES §2b:101), and what changed here
----------------------------------------------------
"script/flow/actions/webhook edits require an explicit 'Apply to live calls'." A
script edit is the archetypal SLOW-lane change, and this module used to publish it
fastest of all: `write_prompt_version` re-published a LIVE agent in the same
transaction, so every version was born live and "nothing goes live silently" was
false for the one field with the largest blast radius. Prompt VERSIONING had an
explicit publish (FLOWS §7); prompt PUBLISHING did not.

So `agents.system_prompt_id` is now the DRAFT pointer and `agents.live_prompt_id` is
the APPLIED one (migration a4e7b2c95d18), and the rule this module enforces is:

- **live agent + hand-written script edit** -> STAGE. The draft pointer moves, the
  applied pointer does not, the engine is not touched. `agents/publishing.py` owns
  Apply and Undo.
- **draft or paused agent** -> APPLY. There is no blast radius to split: nothing of
  this agent is on the engine, so staging would only manufacture a pending change
  with no live counterpart. Two-speed publishing is a property of LIVE agents.
- **rollback** -> APPLY, and publish immediately, unchanged. FLOWS §7 defines
  rollback as "republish an earlier version", which IS an apply: someone watching a
  bad script take calls is not asking to stage a fix. Staging a rollback would make
  the recovery path need a second click at the worst possible moment.

Engine coherence for the paths that DO publish (rollback; the T0 fast lane in
`agents/t0.py`): the push happens AFTER the local rows are written but INSIDE the
transaction, so an engine failure rolls back the new version and the pointer together
(the same "never claim what the engine doesn't have" ordering argument as
`kb.publish_source`). Draft agents skip the engine entirely.

Notes live in the real `notes` column (migration 2faa301dc488): operator-facing
metadata about a version, kept apart from `compiled_t0_context`, which D-39 reserves
for the T0 compiler's build artifact — that compiler is `agents/t0.py`, and it mints
its versions through `insert_prompt_version` below rather than through an INSERT of
its own.
"""

from __future__ import annotations

import json
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
    structured_script: dict[str, Any] | None = None,
    apply_live: bool,
) -> int:
    """INSERT the next version and move the agent's pointer(s) to it. Never an UPDATE
    of an existing version row — that is the immutability invariant, enforced by shape.

    `apply_live` decides which pointers move, and it is keyword-only and REQUIRED on
    purpose: every caller has to state which lane it is on rather than inherit a
    default that decides whether a client's phone line changes today.

    - `apply_live=True`  -> both pointers move. The caller is expected to publish.
    - `apply_live=False` -> only the draft pointer moves; the engine keeps what it has.

    The single UPDATE below is also where the invariant `agents/service.py` depends on
    is established: when a divergence is CREATED (`apply_live=False`), the applied
    pointer is materialized from the CURRENT `system_prompt_id` if it was still NULL.
    That is the truth for every row written before this pointer existed and for every
    row `admin/intake.py` writes, because in both cases the version the agent pointed
    at is the version the engine was sent. It is what lets `publish_agent` read
    `COALESCE(live_prompt_id, system_prompt_id)` without ever picking up a draft:
    NULL can then only mean "the two pointers agree".

    `published_at` is set at insert: pointing the agent at a version IS publishing it
    here (creation and activation are one step, unlike the KB's approval gate).

    `compiled_t0_context` is the T0 compiler's build artifact (D-39) and is stamped at
    INSERT for the same reason: writing it onto an existing row afterwards would rewrite
    what an earlier publish said. It stays None for a hand-written version — the writer
    supplied a body, not a compiled block, and claiming otherwise would make
    `agents/t0.py` recompile from an artifact nobody built.

    `structured_script` is the authored STRUCTURED form (`CallScript`) this version's
    `body` was compiled from, stamped at INSERT beside `body` for the same immutability
    reason (migration c7e2b4f019ad). It stays None for a freeform version — one authored
    as raw text, whose `body` is the whole of what was written and which the builder
    reloads via `CallScript.from_freeform`. Serialised to JSON here rather than bound as a
    dict so this module's single `text()` INSERT stays one statement over `:structured`
    with an explicit `::jsonb` cast, never a second parameter-binding dialect.

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
                "compiled_t0_context, structured_script, notes, created_by, published_at, "
                "created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :version, :body, :compiled, "
                "CAST(:structured AS jsonb), :notes, :by, now(), now(), now())"
            ),
            {
                "id": version_id,
                "tid": tenant_id,
                "aid": agent_id,
                "version": version,
                "body": body,
                "compiled": compiled_t0_context,
                # JSON text or NULL — `CAST(... AS jsonb)` accepts both; None round-trips to
                # a SQL NULL, which is the "authored freeform" sentinel.
                "structured": (
                    json.dumps(structured_script) if structured_script is not None else None
                ),
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
            "UPDATE agents SET system_prompt_id = :vid, live_prompt_id = CASE "
            "WHEN :apply THEN :vid ELSE COALESCE(live_prompt_id, system_prompt_id) END, "
            "updated_at = now() WHERE id = :aid AND deleted_at IS NULL"
        ),
        {"vid": version_id, "aid": agent_id, "apply": apply_live},
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
    structured_script: dict[str, Any] | None = None,
) -> int:
    """New immutable version. On a LIVE agent it is STAGED, not published.

    The slow lane (SURFACES §2b:101). The engine keeps running the applied script
    until somebody presses Apply — `agents.publishing.apply_to_live` — so a script
    edit can never reach a client's callers as a side effect of saving a draft.
    A draft or paused agent has nothing live to protect, so its edits are applied as
    they are written and the first publish sends them.

    `structured_script` is the authored `CallScript` this `body` was compiled from
    (`agents/script_builder.py`), or None for a freeform (raw) write — stamped at INSERT
    beside the body so the builder can reload the exact structure the author last saw.
    """
    status, engine_ref = await _agent_state(session, agent_id)
    live = _is_live(status, engine_ref)
    version = await insert_prompt_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        body=body,
        notes=notes,
        created_by=created_by,
        structured_script=structured_script,
        apply_live=not live,
    )
    # ids and version only — prompt bodies can embed client business detail (rule 6).
    log.info(
        "prompt_version_written",
        extra={"agent_id": str(agent_id), "version": version, "live": live, "staged": live},
    )
    return version


async def list_prompt_versions(
    session: AsyncSession, agent_id: UUID, *, limit: int = 100
) -> list[dict[str, Any]]:
    """History, newest first. `active` = the version `agents.system_prompt_id` names —
    derived from the pointer rather than stored, so it cannot drift.

    404s an agent that is not there, through `_agent_state` — the same predicate the two
    WRITES in this module already go through, so all three answer one id the same way.
    Without it the empty list was ambiguous in the one direction that matters: "no script
    has been written yet" is a REAL state of a real agent (it is what `publish` refuses
    as `agent_has_no_script`), so a mistyped agent id, a neighbour's agent under RLS and
    a soft-deleted one all rendered as a live agent awaiting its first prompt.
    """
    await _agent_state(session, agent_id)
    rows = (
        await session.execute(
            text(
                "SELECT pv.id, pv.version, pv.notes, pv.created_at, "
                "(pv.id = a.system_prompt_id) AS active "
                "FROM prompt_versions pv JOIN agents a ON a.id = pv.agent_id "
                "WHERE pv.agent_id = :aid ORDER BY pv.version DESC LIMIT :limit"
            ),
            {"aid": agent_id, "limit": limit},
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

    APPLIED, not staged, and that is the deliberate exception to the slow lane above:
    FLOWS §7 defines rollback as "republish an earlier version", the body is one this
    agent has already spoken, and the person clicking it is watching a bad script take
    calls. Making the recovery path wait for a second click is the one place where
    "nothing goes live silently" would cost more than it protects. It is loud rather
    than silent by construction — `prompt_routes.rollback_prompt` writes an audit row
    naming both versions.
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
        apply_live=True,
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
