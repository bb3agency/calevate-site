"""Take the trade plans' retired example lines off an account's agents (D-962).

The plans used to give every step a spoken example line, the same for every business of a type,
and a ready-made script stored them on the agent's steps. On the founder's Rytu Khata call of
2 Nov 2026 one of them ("you enquired with us earlier, do you still want it?") reached a caller
with nothing on the call saying so. The plans now hold no words (`agents/trade_playbooks`), but
the lines stay on every agent already made until something takes them off; this job does.

Queued through the outbox, one message per account with an agent, by migration
`e962a4c1d7b3`. Per agent, in its own transaction: every step whose example line is still a
retired line word for word (`agents/retired_lines.RETIRED_LINES`) has it emptied, in the current
script (a new version, and a live agent republished, through `script_builder.rewrite_script`)
and in the autosaved draft; a line anybody edited is never touched, and the agent then words
that step itself from its instruction. Each agent changed gets one audit row naming the version
and the step counts, never the lines. An agent the voice platform refuses rolls back alone, the
run ends `partial`, and re-queueing the message picks it up; a redelivery finds nothing left.

Lines are not put back on a downgrade: each removed line is in the agent's previous script
version, which the owner can restore from the version list, and putting a line back that the
founder retired would be the defect this job removes.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.agents.retired_lines import RETIRED_LINES
from apps.api.agents.script_builder import clear_example_lines
from apps.api.compliance.audit import write_audit
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session

log = get_logger(__name__)

JOB_NAME: Final = "strip_retired_example_lines"
AUDIT_ACTION: Final = "agent.retired_example_lines_cleared"
NOTES: Final = "Ready-made example lines taken off: each step is worded for your business"


async def _agent_ids(tenant_id: UUID) -> list[UUID]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT id FROM agents WHERE deleted_at IS NULL ORDER BY created_at, id")
            )
        ).all()
    return [UUID(str(r[0])) for r in rows]


async def _strip_agent(tenant_id: UUID, agent_id: UUID) -> bool:
    """Clear one agent's retired lines and audit it; True when anything changed."""
    async with tenant_session(tenant_id) as session:
        cleared = await clear_example_lines(
            session, tenant_id=tenant_id, agent_id=agent_id, lines=RETIRED_LINES, notes=NOTES
        )
        if not (cleared.script_steps or cleared.draft_steps):
            return False
        await write_audit(
            session,
            action=AUDIT_ACTION,
            actor_type="system",
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            summary={
                "version": cleared.version,
                "script_steps": cleared.script_steps,
                "draft_steps": cleared.draft_steps,
            },
        )
    return True


async def strip_retired_example_lines(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    written = refused = crashed = 0
    for agent_id in await _agent_ids(tenant_id):
        try:
            if await _strip_agent(tenant_id, agent_id):
                written += 1
        except ProblemError as exc:
            refused += 1
            log.warning(
                "retired_lines_refused", extra={"agent_id": str(agent_id), "reason": exc.code}
            )
        except Exception as exc:
            crashed += 1
            log.warning(
                "retired_lines_crashed",
                extra={"agent_id": str(agent_id), "error": type(exc).__name__},
            )
    if crashed:
        # After every other agent had its turn; the retry finds nothing left on those.
        raise RuntimeError(f"{crashed} agent(s) could not have their retired lines cleared")
    log.info(
        "retired_lines_cleared",
        extra={"tenant_id": str(tenant_id), "agents_written": written, "agents_refused": refused},
    )
    return "done" if not refused else "partial"


__all__ = ["AUDIT_ACTION", "JOB_NAME", "strip_retired_example_lines"]
