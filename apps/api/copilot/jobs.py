"""Background jobs: a request bigger than one answer, run by a worker (D-694 item 7).

WHY A JOB AND NOT A LONGER REQUEST. The interactive answer is bounded by
`service.TOTAL_BUDGET_S` and `service.MAX_TURNS`, and those bounds are what keep the stream
inside the edge's read timeout (`copilot/deadline_test.py`) and a person from watching a
spinner for minutes. A request that needs more — "call back every missed lead from
yesterday", "tidy every lead with no status" — is handed to an ARQ worker instead
(`apps/workers/copilot_jobs.py`), which runs the SAME tool loop under `service.JOB_LIMITS`
and writes its progress here. The panel reads it by polling `GET /v1/copilot/jobs/{id}` or
by `GET /v1/copilot/jobs/{id}/events`, a stream that re-reads this row.

THE ENQUEUE GOES THROUGH THE OUTBOX, in the same transaction as the row, so a job row never
exists without its work being queued and a queued job never points at a row that rolled
back (BACKEND-PATTERNS, the reliability triad).

NOTHING IRREVERSIBLE RUNS UNATTENDED. Inside a job a confirm-tier action is not proposed —
nobody is watching for a five-minute card — it is staged in the Approvals inbox
(`write_tools.stage_for_approval`) and runs only when a person approves it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.memory import redacted_content
from apps.api.copilot.models import MAX_CONTENT_CHARS, MAX_JOB_PROGRESS
from apps.api.copilot.sanitize import strip_invisible
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox

#: The ARQ function that runs a job. Registered in `apps/workers/settings.FUNCTIONS`.
COPILOT_JOB: Final = "run_copilot_job"

#: How many jobs one person may have queued or running at once. A guard against a model
#: that starts a job per turn, and against a double-click.
MAX_ACTIVE_JOBS_PER_USER: Final = 2

#: The longest one progress entry's text may be.
MAX_PROGRESS_TEXT: Final = 300

JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]
ProgressKind = Literal["step", "action", "approval", "text", "note"]

#: Recent jobs a person may list.
JOBS_PAGE_MAX: Final = 20


@dataclass(frozen=True, slots=True)
class JobRow:
    id: UUID
    tenant_id: UUID
    user_id: UUID
    status: str
    goal: str
    screen_route: str
    progress: list[dict[str, Any]]
    result: str | None
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


_COLUMNS: Final = (
    "id, tenant_id, user_id, status, goal, screen_route, progress, result, error_code, "
    "created_at, started_at, finished_at"
)


def _job(record: Any) -> JobRow:
    return JobRow(
        id=record[0],
        tenant_id=record[1],
        user_id=record[2],
        status=record[3],
        goal=record[4],
        screen_route=record[5],
        progress=list(record[6] or []),
        result=record[7],
        error_code=record[8],
        created_at=record[9],
        started_at=record[10],
        finished_at=record[11],
    )


class TooManyJobsError(Exception):
    """This person already has the most background jobs one person may run at once."""


async def create_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    goal: str,
    screen_route: str,
) -> JobRow:
    """Insert one queued job and its outbox message, in the caller's transaction."""
    active = (
        await session.execute(
            text(
                "SELECT count(*) FROM copilot_jobs WHERE user_id = :uid "
                "AND status IN ('queued', 'running')"
            ),
            {"uid": user_id},
        )
    ).scalar_one()
    if int(active) >= MAX_ACTIVE_JOBS_PER_USER:
        raise TooManyJobsError
    cleaned = redacted_content(goal) or "A task the assistant was asked to do."
    job_id = uuid7()
    record = (
        await session.execute(
            text(
                "INSERT INTO copilot_jobs (id, tenant_id, user_id, status, goal, screen_route, "
                "progress, created_at, updated_at) VALUES (:id, :tid, :uid, 'queued', :goal, "
                f":route, '[]'::jsonb, now(), now()) RETURNING {_COLUMNS}"
            ),
            {
                "id": job_id,
                "tid": tenant_id,
                "uid": user_id,
                "goal": cleaned[:MAX_CONTENT_CHARS],
                "route": screen_route[:200],
            },
        )
    ).one()
    await enqueue_outbox(
        session,
        job=COPILOT_JOB,
        payload={"job_id": str(job_id), "tenant_id": str(tenant_id)},
    )
    return _job(record)


async def read_job(session: AsyncSession, *, job_id: UUID, user_id: UUID) -> JobRow | None:
    """One job, if it is THIS person's. RLS scopes the tenant; the predicate scopes the
    person, because one colleague's background work is not another's to read."""
    record = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM copilot_jobs WHERE id = :id AND user_id = :uid"),
            {"id": job_id, "uid": user_id},
        )
    ).first()
    return None if record is None else _job(record)


async def list_jobs(session: AsyncSession, *, user_id: UUID, limit: int) -> list[JobRow]:
    bounded = max(1, min(limit, JOBS_PAGE_MAX))
    records = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM copilot_jobs WHERE user_id = :uid "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"uid": user_id, "limit": bounded},
        )
    ).all()
    return [_job(record) for record in records]


async def claim_job(session: AsyncSession, *, job_id: UUID) -> JobRow | None:
    """`queued` → `running`, as a CAS. None when another worker (or a retry) got it."""
    record = (
        await session.execute(
            text(
                "UPDATE copilot_jobs SET status = 'running', started_at = now(), "
                f"updated_at = now() WHERE id = :id AND status = 'queued' RETURNING {_COLUMNS}"
            ),
            {"id": job_id},
        )
    ).first()
    return None if record is None else _job(record)


def progress_entry(
    kind: ProgressKind, words: str, *, action_id: UUID | str | None = None
) -> dict[str, Any]:
    """One progress entry: a kind, a redacted, bounded sentence, and its instant."""
    cleaned = strip_invisible(redacted_content(words) or "")
    if len(cleaned) > MAX_PROGRESS_TEXT:
        cleaned = cleaned[: MAX_PROGRESS_TEXT - 1].rstrip() + "…"
    entry: dict[str, Any] = {
        "at": datetime.now(UTC).isoformat(),
        "kind": kind,
        "text": cleaned or "…",
    }
    if action_id is not None:
        entry["action_id"] = str(action_id)
    return entry


async def append_progress(
    session: AsyncSession, *, job_id: UUID, entries: list[dict[str, Any]]
) -> None:
    """Append entries, keeping only the newest `MAX_JOB_PROGRESS` — the list is bounded in
    the schema too (`ck_copilot_jobs_progress_cap`), and this keeps a long job inside it."""
    if not entries:
        return
    await session.execute(
        text(
            "UPDATE copilot_jobs SET progress = ("
            "  SELECT COALESCE(jsonb_agg(e ORDER BY ord), '[]'::jsonb) FROM ("
            "    SELECT e, ord FROM jsonb_array_elements(progress || CAST(:entries AS jsonb)) "
            "    WITH ORDINALITY AS t(e, ord) ORDER BY ord DESC LIMIT :cap"
            "  ) AS kept"
            "), updated_at = now() WHERE id = :id"
        ),
        {"id": job_id, "entries": json.dumps(entries), "cap": MAX_JOB_PROGRESS},
    )


async def finish_job(
    session: AsyncSession,
    *,
    job_id: UUID,
    status: Literal["done", "failed"],
    result: str | None,
    error_code: str | None = None,
) -> None:
    cleaned = None if result is None else (redacted_content(result) or None)
    await session.execute(
        text(
            "UPDATE copilot_jobs SET status = :status, result = :result, error_code = :code, "
            "finished_at = now(), updated_at = now() WHERE id = :id AND status = 'running'"
        ),
        {
            "id": job_id,
            "status": status,
            "result": None if cleaned is None else cleaned[: MAX_CONTENT_CHARS * 2],
            "code": error_code,
        },
    )


async def cancel_job(session: AsyncSession, *, job_id: UUID, user_id: UUID) -> bool:
    """Stop a job that has not finished. A running job sees it at its next progress write
    and stops; a queued one is never started."""
    result = await session.execute(
        text(
            "UPDATE copilot_jobs SET status = 'cancelled', finished_at = now(), "
            "updated_at = now() WHERE id = :id AND user_id = :uid "
            "AND status IN ('queued', 'running')"
        ),
        {"id": job_id, "uid": user_id},
    )
    return bool(getattr(result, "rowcount", 0))


async def job_status(session: AsyncSession, *, job_id: UUID) -> str | None:
    value = (
        await session.execute(
            text("SELECT status FROM copilot_jobs WHERE id = :id"), {"id": job_id}
        )
    ).scalar()
    return None if value is None else str(value)


__all__ = [
    "COPILOT_JOB",
    "JOBS_PAGE_MAX",
    "MAX_ACTIVE_JOBS_PER_USER",
    "JobRow",
    "TooManyJobsError",
    "append_progress",
    "cancel_job",
    "claim_job",
    "create_job",
    "finish_job",
    "job_status",
    "list_jobs",
    "progress_entry",
    "read_job",
]
