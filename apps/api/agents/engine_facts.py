"""The agent's business facts as a knowledge document, on an engine that keeps them out of the
prompt (D-678).

ThinnestAI re-sends `instructions` on every reply, so every character costs on every turn, and
holds at most 20,000 of them (`thinnest-findings/mirror/snapshots/2026-10-07/pages/
api-reference/agents/update-agent.md:426-431`); our platform rules already take a share. So on
an engine whose `HostedAgentLimits.facts_in_knowledge` is set (the founder's decision,
6 Oct 2026), the script is published WITHOUT its
[T0 FACTS] block (`agents/service._script_for`), the prompt tells the model to look the facts
up (`calevate_shared.engine.FACTS_IN_KNOWLEDGE_GUIDANCE`), and the block itself is pushed as
one knowledge document through the same `attach_kb` text path the KB publisher uses.

One document per VENDOR AGENT, recorded on its `engine_agent_routes` row with the digest of
the text it was made from:

* same digest and a recorded handle — nothing is sent;
* new facts — the new document is attached FIRST and the old one removed after, so the agent
  is never without its facts; if the old one cannot be removed the new one is removed again
  and the publish refuses, so the vendor never holds two disagreeing copies;
* no facts any more — the recorded document is removed.

A document the vendor no longer holds (404 on removal) is already gone, which is the
outcome wanted. Deleting the vendor agent deletes its knowledge with it (`agents.md:82`).

The agent's KB-publish lock is taken first (`kb/service.lock_agent_publishes`): the KB drift
sweep reads our recorded handles on either side of a vendor listing under the same lock, and
a facts swap in flight would otherwise read to it as a divergence.
"""

from __future__ import annotations

import hashlib
from typing import Final
from uuid import UUID

from calevate_shared.engine import KBSourceRef, VoiceEngine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.engine.hosted_platform import hosted_agent_limits
from apps.api.engine.vendor_http import EngineRejectedError

log = get_logger(__name__)

#: The document's title at the vendor. Not shown to callers.
FACTS_TITLE: Final = "Business facts"
FACTS_REPLACE_FAILED: Final = "engine_facts_replace_failed"


def _digest(facts: str) -> str:
    return hashlib.sha256(facts.encode()).hexdigest()


async def _remove(engine: VoiceEngine, ref: str, handle: str) -> None:
    """Remove one facts document; one the vendor no longer holds is already removed."""
    try:
        await engine.detach_kb(ref, handle)
    except EngineRejectedError as exc:
        if exc.vendor_status != 404:
            raise


async def sync_business_facts(
    session: AsyncSession,
    engine: VoiceEngine,
    *,
    agent_id: UUID,
    ref: str,
    facts: str | None,
) -> None:
    """Make the vendor agent `ref` hold `facts` as its one facts document, or none.

    For the publish paths, after the `engine_agent_routes` row for `ref` is written and in
    the same transaction. A no-op on an engine that keeps the facts in the prompt.
    """
    if not hosted_agent_limits(engine).facts_in_knowledge:
        return
    # Imported here: `kb.service` imports `agents.t0`, which imports `agents.service`, which
    # imports this module.
    from apps.api.kb.service import lock_agent_publishes

    await lock_agent_publishes(session, agent_id=agent_id)
    row = (
        await session.execute(
            text(
                "SELECT facts_kb_ref, facts_digest FROM engine_agent_routes "
                "WHERE engine = :e AND engine_agent_ref = :ref"
            ),
            {"e": engine.name, "ref": ref},
        )
    ).first()
    held, held_digest = (row[0], row[1]) if row is not None else (None, None)
    body = (facts or "").strip()
    digest = _digest(body) if body else None
    if digest == held_digest and (held is not None or digest is None):
        return

    new_handle: str | None = None
    if body:
        new_handle = await engine.attach_kb(
            ref, KBSourceRef(kb_id=f"facts:{agent_id}:{digest}", title=FACTS_TITLE, text=body)
        )
    if held is not None and held != new_handle:
        try:
            await _remove(engine, ref, held)
        except ProblemError as exc:
            if new_handle is not None:
                try:
                    await _remove(engine, ref, new_handle)
                except ProblemError:
                    log.error(
                        "engine_facts_orphaned",
                        extra={"agent_id": str(agent_id), "kb_handle": new_handle},
                    )
            log.warning(
                "engine_facts_replace_failed",
                extra={"agent_id": str(agent_id), "reason": exc.code},
            )
            raise ProblemError(
                kind="dependency",
                code=FACTS_REPLACE_FAILED,
                title="The agent's business facts could not be updated",
                detail=(
                    "The voice platform would not remove the previous copy of this agent's "
                    "business facts, so nothing was changed."
                ),
                remediation="Publish the agent again. If it keeps failing, contact us.",
            ) from exc
    await session.execute(
        text(
            "UPDATE engine_agent_routes SET facts_kb_ref = :h, facts_digest = :d, "
            "updated_at = now() WHERE engine = :e AND engine_agent_ref = :ref"
        ),
        {"h": new_handle, "d": digest if new_handle else None, "e": engine.name, "ref": ref},
    )
    log.info(
        "engine_facts_synced",
        extra={"agent_id": str(agent_id), "replaced": held is not None, "held": bool(body)},
    )


async def recorded_facts_handles(session: AsyncSession, *, agent_id: UUID) -> set[str]:
    """The facts document recorded for the agent's OWN vendor agent, for the KB
    reconciliation's "what do we believe is attached". Joined through `agents`, which is
    FORCE-RLS'd, so an untenanted read answers empty as `kb/service._ROUTE_JOIN` does; an
    experiment arm's copy is on the arm's vendor agent (`recorded_facts_handle`)."""
    rows = (
        await session.execute(
            text(
                "SELECT r.facts_kb_ref FROM engine_agent_routes r JOIN agents a "
                "ON a.id = r.agent_id AND a.engine_agent_ref = r.engine_agent_ref "
                "WHERE r.agent_id = :aid AND r.facts_kb_ref IS NOT NULL"
            ),
            {"aid": agent_id},
        )
    ).scalars()
    return {str(row) for row in rows}


async def recorded_facts_handle(session: AsyncSession, *, engine_agent_ref: str) -> str | None:
    """The facts document recorded for ONE vendor agent."""
    value = (
        await session.execute(
            text(
                "SELECT facts_kb_ref FROM engine_agent_routes "
                "WHERE engine_agent_ref = :ref AND facts_kb_ref IS NOT NULL"
            ),
            {"ref": engine_agent_ref},
        )
    ).scalar()
    return str(value) if value else None


__all__ = [
    "FACTS_REPLACE_FAILED",
    "FACTS_TITLE",
    "recorded_facts_handle",
    "recorded_facts_handles",
    "sync_business_facts",
]
