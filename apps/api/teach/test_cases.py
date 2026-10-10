"""Saved test cases: "Make this call a test" (founder decision 11, 10 Oct 2026).

A test case is caller lines plus the behaviour the owner expects, for one agent. It is
usually made from a real call: the caller's turns come from `transcript_turns.text_redacted`
(hard rule 5: never the raw text), and the owner edits them before saving. A run sends the
lines, in one conversation, to the LIVE agent through the engine's test chat (the same
harness as the pre-launch test conversations, `agents/test_conversations.py`) and keeps the
agent's replies on the row for the owner to compare with what they expected. There is no
machine verdict: whether a reply does what the owner wanted is theirs to judge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.test_conversations import readiness
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox
from apps.api.teach.models import (
    MAX_CASE_EXPECTED_CHARS,
    MAX_CASE_LINE_CHARS,
    MAX_CASE_LINES,
)

#: The worker job (`apps/workers/agent_test_cases.JOB_NAME`).
RUN_CASES_JOB: Final = "run_agent_test_cases"

#: The most saved tests one agent keeps; each run sends every line of every test.
MAX_CASES_PER_AGENT: Final = 20
MAX_TITLE_CHARS: Final = 120


@dataclass(frozen=True, slots=True)
class CaseDraft:
    """What the "Make this call a test" form starts from."""

    call_id: UUID
    agent_id: UUID
    agent_name: str | None
    caller_lines: list[str]
    title: str


@dataclass(frozen=True, slots=True)
class TestCase:
    id: UUID
    agent_id: UUID
    source_call_id: UUID | None
    title: str
    caller_lines: list[str]
    expected: str
    status: str
    last_result: list[dict[str, Any]] | None
    last_error: str | None
    last_run_at: datetime | None
    last_prompt_version: int | None
    created_at: datetime


_COLUMNS = (
    "id, agent_id, source_call_id, title, caller_lines, expected, status, last_result, "
    "last_error, last_run_at, last_prompt_version, created_at"
)


def _case_of(row: Any) -> TestCase:
    return TestCase(
        id=row.id,
        agent_id=row.agent_id,
        source_call_id=row.source_call_id,
        title=row.title,
        caller_lines=[str(line) for line in row.caller_lines or []],
        expected=row.expected,
        status=row.status,
        last_result=list(row.last_result) if row.last_result is not None else None,
        last_error=row.last_error,
        last_run_at=row.last_run_at,
        last_prompt_version=row.last_prompt_version,
        created_at=row.created_at,
    )


def clean_lines(lines: list[str]) -> list[str]:
    cleaned = [" ".join(line.split())[:MAX_CASE_LINE_CHARS] for line in lines]
    cleaned = [line for line in cleaned if line]
    if not cleaned:
        raise ProblemError.business_rule(
            "test_case_no_lines", "Keep at least one thing the caller says."
        )
    if len(cleaned) > MAX_CASE_LINES:
        raise ProblemError.business_rule(
            "test_case_too_many_lines",
            f"A test sends at most {MAX_CASE_LINES} caller lines.",
            remediation="Keep the lines where the agent went wrong.",
        )
    return cleaned


def clean_expected(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ProblemError.business_rule(
            "test_case_no_expectation", "Say what the agent should do instead."
        )
    return cleaned[:MAX_CASE_EXPECTED_CHARS]


async def draft_from_call(session: AsyncSession, call_id: UUID) -> CaseDraft:
    """The call's caller lines, redacted, as the starting point of a test."""
    call = (
        await session.execute(
            text(
                "SELECT c.id, c.agent_id, a.name, c.headline FROM calls c "
                "LEFT JOIN agents a ON a.id = c.agent_id "
                "WHERE c.id = :id AND c.erased_subject_ref IS NULL"
            ),
            {"id": call_id},
        )
    ).first()
    if call is None:
        raise ProblemError.not_found("Call")
    turns = (
        await session.execute(
            text(
                "SELECT text_redacted FROM transcript_turns "
                "WHERE call_id = :id AND speaker = 'caller' AND text_redacted IS NOT NULL "
                "AND btrim(text_redacted) <> '' ORDER BY idx LIMIT :limit"
            ),
            {"id": call_id, "limit": MAX_CASE_LINES},
        )
    ).scalars()
    lines = [" ".join(str(t).split())[:MAX_CASE_LINE_CHARS] for t in turns]
    title = (call[3] or "Test from a call")[:MAX_TITLE_CHARS]
    return CaseDraft(
        call_id=call[0], agent_id=call[1], agent_name=call[2], caller_lines=lines, title=title
    )


async def create_case(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call_id: UUID | None,
    agent_id: UUID | None,
    title: str,
    caller_lines: list[str],
    expected: str,
    created_by: UUID | None,
) -> TestCase:
    if call_id is not None:
        draft = await draft_from_call(session, call_id)
        if agent_id is not None and agent_id != draft.agent_id:
            raise ProblemError.business_rule(
                "test_case_wrong_agent", "A test made from a call belongs to that call's agent."
            )
        agent_id = draft.agent_id
    if agent_id is None:
        raise ProblemError.business_rule("test_case_needs_agent", "Choose the agent to test.")
    exists = (
        await session.execute(
            text("SELECT 1 FROM agents WHERE id = :id AND deleted_at IS NULL FOR UPDATE"),
            {"id": agent_id},
        )
    ).scalar()
    if exists is None:
        raise ProblemError.not_found("Agent")
    count = int(
        (
            await session.execute(
                text("SELECT count(*) FROM agent_test_cases WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
        ).scalar()
        or 0
    )
    if count >= MAX_CASES_PER_AGENT:
        raise ProblemError.business_rule(
            "test_cases_full",
            f"This agent already has {MAX_CASES_PER_AGENT} saved tests.",
            remediation="Delete a test that no longer matters, then save this one.",
        )
    clean_title = " ".join(title.split())[:MAX_TITLE_CHARS] or "Test from a call"
    row = (
        await session.execute(
            text(
                "INSERT INTO agent_test_cases (id, tenant_id, agent_id, source_call_id, title, "
                "caller_lines, expected, status, created_by, created_at, updated_at) VALUES "
                "(:id, :tid, :aid, :call, :title, CAST(:lines AS jsonb), :expected, 'idle', "
                f":by, now(), now()) RETURNING {_COLUMNS}"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "call": call_id,
                "title": clean_title,
                "lines": json.dumps(clean_lines(caller_lines)),
                "expected": clean_expected(expected),
                "by": created_by,
            },
        )
    ).one()
    return _case_of(row)


async def list_cases(session: AsyncSession, agent_id: UUID) -> list[TestCase]:
    rows = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM agent_test_cases WHERE agent_id = :aid "
                "ORDER BY created_at DESC, id DESC LIMIT :limit"
            ),
            {"aid": agent_id, "limit": MAX_CASES_PER_AGENT},
        )
    ).all()
    return [_case_of(row) for row in rows]


async def delete_case(session: AsyncSession, *, agent_id: UUID, case_id: UUID) -> None:
    result = await session.execute(
        text("DELETE FROM agent_test_cases WHERE id = :id AND agent_id = :aid RETURNING id"),
        {"id": case_id, "aid": agent_id},
    )
    if result.first() is None:
        raise ProblemError.not_found("Saved test")


async def request_run(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> list[TestCase]:
    """Queue every saved test of this agent for one run against the live agent."""
    ready = await readiness(session, agent_id)
    if not ready.available:
        raise ProblemError.business_rule("agent_tests_unavailable", ready.reason or "")
    await session.execute(
        text("SELECT 1 FROM agents WHERE id = :aid FOR UPDATE"), {"aid": agent_id}
    )
    queued = (
        await session.execute(
            text(
                "UPDATE agent_test_cases SET status = 'queued', updated_at = now() "
                "WHERE agent_id = :aid AND status = 'idle' RETURNING id"
            ),
            {"aid": agent_id},
        )
    ).all()
    if not queued:
        busy = (
            await session.execute(
                text(
                    "SELECT 1 FROM agent_test_cases WHERE agent_id = :aid "
                    "AND status IN ('queued', 'running') LIMIT 1"
                ),
                {"aid": agent_id},
            )
        ).scalar()
        if busy is None:
            raise ProblemError.business_rule(
                "test_cases_none", "There are no saved tests for this agent yet."
            )
    else:
        await enqueue_outbox(
            session,
            job=RUN_CASES_JOB,
            payload={"tenant_id": str(tenant_id), "agent_id": str(agent_id)},
        )
    return await list_cases(session, agent_id)


__all__ = [
    "MAX_CASES_PER_AGENT",
    "RUN_CASES_JOB",
    "CaseDraft",
    "TestCase",
    "clean_expected",
    "clean_lines",
    "create_case",
    "delete_case",
    "draft_from_call",
    "list_cases",
    "request_run",
]
