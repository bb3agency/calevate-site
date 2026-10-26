"""Give an account's agents a ready-made script's better example lines (D-888).

A starter's steps carry the trade plan's example line for each step (`agents/trade_playbooks`),
stored in the agent's script, so a plan line that taught the wrong thing stays on every agent
made with it until something rewrites it. The real-estate plan asked "two or three BHK?" and
offered "this weekend" for a visit, and on the calls of 25 Oct 2026 the agent steered a caller
who wanted five bedrooms and offered a weekend that had ended.

Queued through the outbox, one message per account, by the migration that ships the new lines
(`c8e4a1f7b2d5`); the payload carries old and new lines as that migration froze them. Per
agent, in one transaction, a step still holding an old line word for word gets the new one
(`script_builder.refresh_example_lines`, which republishes a live agent). A line anybody edited
is left alone; an agent the voice platform refuses rolls back alone, the run ends `partial`,
and re-queueing the payload picks it up. A redelivery finds nothing left to change.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.agents.script_builder import refresh_example_lines as refresh_agent_lines
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session

log = get_logger(__name__)

JOB_NAME: Final = "refresh_example_lines"


async def _agent_ids(tenant_id: UUID) -> list[UUID]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT id FROM agents WHERE deleted_at IS NULL ORDER BY created_at, id")
            )
        ).all()
    return [UUID(str(r[0])) for r in rows]


async def refresh_example_lines(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    replacements = {str(old): str(new) for old, new in payload["replacements"]}
    written = refused = crashed = 0
    for agent_id in await _agent_ids(tenant_id):
        try:
            async with tenant_session(tenant_id) as session:
                if await refresh_agent_lines(
                    session, tenant_id=tenant_id, agent_id=agent_id, replacements=replacements
                ):
                    written += 1
        except ProblemError as exc:
            refused += 1
            log.warning(
                "example_line_refresh_refused",
                extra={"agent_id": str(agent_id), "reason": exc.code},
            )
        except Exception as exc:
            crashed += 1
            log.warning(
                "example_line_refresh_crashed",
                extra={"agent_id": str(agent_id), "error": type(exc).__name__},
            )
    if crashed:
        # After every other agent had its turn; the retry finds nothing left on those.
        raise RuntimeError(f"{crashed} agent(s) could not take the new example lines")
    log.info(
        "example_lines_refreshed",
        extra={"tenant_id": str(tenant_id), "agents_written": written, "agents_refused": refused},
    )
    return "done" if not refused else "partial"


__all__ = ["JOB_NAME", "refresh_example_lines"]
