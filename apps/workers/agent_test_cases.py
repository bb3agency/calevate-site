"""Runs an agent's saved test cases against the LIVE agent (`apps/api/teach/test_cases.py`).

Each test is one conversation in the engine's sandboxed test chat: its caller lines are sent
in order with the session carried between them, and the agent's replies are stored on the
test for the owner to compare with what they expected. A pause separates messages because
the engine refuses messages sent faster than a person types (test-chat.md:438-445).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.hosted_platform import hosted_agent_limits
from apps.api.engine.test_chat import RunsTestChat
from apps.api.teach.test_cases import RUN_CASES_JOB
from apps.workers.agent_test_conversations import PAUSE_S

log = get_logger(__name__)

JOB_NAME: Final = RUN_CASES_JOB


async def _pause() -> None:
    await asyncio.sleep(PAUSE_S)


async def _store(
    tenant_id: UUID,
    case_id: UUID,
    *,
    result: list[dict[str, Any]] | None,
    error: str | None,
    version: int | None,
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agent_test_cases SET status = 'idle', "
                "last_result = COALESCE(CAST(:result AS jsonb), last_result), "
                "last_error = :error, last_run_at = now(), last_prompt_version = :version, "
                "updated_at = now() WHERE id = :id AND status = 'running'"
            ),
            {
                "id": case_id,
                "result": json.dumps(result) if result is not None else None,
                "error": error,
                "version": version,
            },
        )


async def run_case_lines(
    engine: RunsTestChat, ref: str, lines: list[str], *, knowledge_tool: str | None, pause: Any
) -> list[dict[str, Any]]:
    """Send each line in one conversation; answer what the agent said to each."""
    session: str | None = None
    turns: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if index:
            await pause()
        turn = await engine.test_chat(ref, line, session=session)
        session = turn.session or session
        turns.append(
            {
                "said": line,
                "reply": turn.reply,
                "looked_up_knowledge": knowledge_tool is not None and knowledge_tool in turn.tools,
                "cut_short": turn.failed_part_way,
            }
        )
    return turns


async def run_agent_test_cases(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    agent_id = UUID(str(payload["agent_id"]))
    async with tenant_session(tenant_id) as session:
        agent = (
            await session.execute(
                text(
                    "SELECT a.engine_agent_ref, pv.version FROM agents a "
                    "LEFT JOIN prompt_versions pv ON pv.id = a.live_prompt_id WHERE a.id = :aid"
                ),
                {"aid": agent_id},
            )
        ).first()
        cases = (
            await session.execute(
                text(
                    "UPDATE agent_test_cases SET status = 'running', updated_at = now() "
                    "WHERE agent_id = :aid AND status = 'queued' RETURNING id, caller_lines"
                ),
                {"aid": agent_id},
            )
        ).all()
    if not cases:
        return "nothing_queued"
    engine = get_engine()
    version = int(agent[1]) if agent is not None and agent[1] is not None else None
    if agent is None or agent[0] is None or not isinstance(engine, RunsTestChat):
        for case_id, _lines in cases:
            await _store(tenant_id, case_id, result=None, error="unavailable", version=version)
        return "unavailable"
    knowledge_tool = hosted_agent_limits(engine).knowledge_tool
    for index, (case_id, lines) in enumerate(cases):
        if index:
            await _pause()
        try:
            turns = await run_case_lines(
                engine,
                str(agent[0]),
                [str(line) for line in lines],
                knowledge_tool=knowledge_tool,
                pause=_pause,
            )
        except ProblemError as exc:
            log.warning(
                "agent_test_case_failed", extra={"case_id": str(case_id), "reason": exc.code}
            )
            await _store(tenant_id, case_id, result=None, error=exc.code, version=version)
            continue
        except Exception:
            log.exception("agent_test_case_crashed", extra={"case_id": str(case_id)})
            await _store(tenant_id, case_id, result=None, error="crashed", version=version)
            continue
        await _store(tenant_id, case_id, result=turns, error=None, version=version)
    log.info("agent_test_cases_done", extra={"agent_id": str(agent_id), "cases": len(cases)})
    return "done"


__all__ = ["JOB_NAME", "run_agent_test_cases", "run_case_lines"]
