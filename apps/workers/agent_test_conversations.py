"""Runs one queued set of pre-launch test conversations (`agents/test_conversations.py`).

Claims the queued row, talks to the agent through the engine's test chat with a pause
between messages, and stores what the agent said. One attempt: a failed run is marked
failed with a machine code and the owner may start another.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.agents.test_conversations import result_dicts, run_scenarios
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.test_chat import RunsTestChat

log = get_logger(__name__)

#: The ARQ name; `agents/test_conversations.RUN_JOB` is the enqueue side's spelling.
JOB_NAME: Final = "run_agent_test_conversations"

#: Seconds between messages: the engine answers 429 to "messages sent faster than a person
#: types" (test-chat.md:438-445) without saying how fast that is.
PAUSE_S: Final = 4.0


async def _pause() -> None:
    await asyncio.sleep(PAUSE_S)


async def _finish(
    tenant_id: UUID, run_id: UUID, *, status: str, results: Any, failure: str | None
) -> None:
    import json

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agent_test_runs SET status = :status, "
                "results = CAST(:results AS jsonb), error_code = :code, completed_at = now(), "
                "updated_at = now() WHERE id = :id AND status = 'running'"
            ),
            {
                "status": status,
                "results": json.dumps(results) if results is not None else None,
                "code": failure,
                "id": run_id,
            },
        )


async def run_agent_test_conversations(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    run_id = UUID(str(payload["run_id"]))
    async with tenant_session(tenant_id) as session:
        claimed = (
            await session.execute(
                text(
                    "UPDATE agent_test_runs r SET status = 'running', updated_at = now() "
                    "FROM agents a WHERE r.id = :id AND r.status = 'queued' "
                    "AND a.id = r.agent_id RETURNING a.engine_agent_ref, a.direction, "
                    "a.language_primary"
                ),
                {"id": run_id},
            )
        ).first()
    if claimed is None:
        return "not_queued"
    engine = get_engine()
    if not isinstance(engine, RunsTestChat) or claimed[0] is None:
        await _finish(tenant_id, run_id, status="failed", results=None, failure="unavailable")
        return "failed"
    try:
        results = await run_scenarios(
            engine,
            engine_agent_ref=str(claimed[0]),
            direction=str(claimed[1]),
            language=str(claimed[2]),
            pause=_pause,
        )
    except ProblemError as exc:
        log.warning("agent_tests_failed", extra={"run_id": str(run_id), "reason": exc.code})
        await _finish(tenant_id, run_id, status="failed", results=None, failure=exc.code)
        return "failed"
    except Exception:
        log.exception("agent_tests_crashed", extra={"run_id": str(run_id)})
        await _finish(tenant_id, run_id, status="failed", results=None, failure="crashed")
        return "failed"
    await _finish(tenant_id, run_id, status="done", results=result_dicts(results), failure=None)
    log.info("agent_tests_done", extra={"run_id": str(run_id), "scenarios": len(results)})
    return "done"


__all__ = ["JOB_NAME", "PAUSE_S", "run_agent_test_conversations"]
