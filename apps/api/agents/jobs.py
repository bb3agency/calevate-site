"""An agent's jobs: the inbound lines and campaigns that speak in its voice (founder, 16 Nov 2026).

An agent is staff with no script of its own; its work is the lines it answers for and the
campaigns it calls for, each with its own script and its own test call. The agent page lists
them in Try it (each opens that job's own test call) and counts them for the Overview's
"Give it a job" step and the readiness score.

Read under the caller's tenant session: both tables are FORCE-RLS'd, so another account's
agent id finds nothing.
"""

from __future__ import annotations

from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError

#: The most of each kind listed; an agent with more is still counted in full.
MAX_JOBS_LISTED: Final = 25

#: A campaign that can still be tested or run; a finished one is history, not a job.
OPEN_CAMPAIGN_STATUSES: Final = ("draft", "scheduled", "running", "paused")

_LINES_SQL: Final = (
    "SELECT id, name, published_at IS NOT NULL AS live FROM inbound_lines "
    "WHERE agent_id = :aid AND archived_at IS NULL ORDER BY created_at, id LIMIT :limit"
)
_CAMPAIGNS_SQL: Final = (
    "SELECT id, name, status FROM campaigns WHERE agent_id = :aid AND archived_at IS NULL "
    "AND status = ANY(:open) ORDER BY created_at DESC, id LIMIT :limit"
)
_COUNT_SQL: Final = (
    "SELECT (SELECT count(*) FROM inbound_lines WHERE agent_id = :aid AND archived_at IS NULL) "
    "+ (SELECT count(*) FROM campaigns WHERE agent_id = :aid AND archived_at IS NULL "
    "AND status = ANY(:open))"
)


class AgentJobOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["inbound_line", "campaign"]
    id: UUID
    name: str
    #: A line: put live (`published`) or a draft. A campaign: its own status.
    status: str


class AgentJobsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    #: Its inbound lines first, oldest first; then its open campaigns, newest first.
    jobs: list[AgentJobOut]
    #: Every job, including any past `MAX_JOBS_LISTED` of a kind.
    total: int


async def job_count(session: AsyncSession, agent_id: UUID) -> int:
    """How many inbound lines and open campaigns speak in this agent's voice."""
    row = await session.execute(
        text(_COUNT_SQL), {"aid": agent_id, "open": list(OPEN_CAMPAIGN_STATUSES)}
    )
    return int(row.scalar_one())


async def agent_jobs(session: AsyncSession, agent_id: UUID) -> AgentJobsOut:
    exists = (
        await session.execute(
            text("SELECT 1 FROM agents WHERE id = :aid AND deleted_at IS NULL"), {"aid": agent_id}
        )
    ).scalar()
    if exists is None:
        raise ProblemError.not_found("Agent")
    params = {"aid": agent_id, "limit": MAX_JOBS_LISTED, "open": list(OPEN_CAMPAIGN_STATUSES)}
    lines = (await session.execute(text(_LINES_SQL), params)).all()
    campaigns = (await session.execute(text(_CAMPAIGNS_SQL), params)).all()
    jobs = [
        AgentJobOut(
            kind="inbound_line",
            id=row.id,
            name=str(row.name),
            status="published" if row.live else "draft",
        )
        for row in lines
    ] + [
        AgentJobOut(kind="campaign", id=row.id, name=str(row.name), status=str(row.status))
        for row in campaigns
    ]
    return AgentJobsOut(agent_id=agent_id, jobs=jobs, total=await job_count(session, agent_id))


__all__ = [
    "MAX_JOBS_LISTED",
    "OPEN_CAMPAIGN_STATUSES",
    "AgentJobOut",
    "AgentJobsOut",
    "agent_jobs",
    "job_count",
]
