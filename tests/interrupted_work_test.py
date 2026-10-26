"""A Pip job or teaching that a `job_timeout` overrun left in flight is ended as failed.

arq does not retry a run it timed out, so without the sweep the row stays `running` /
`sorting` for ever. The sweep must end only rows past `STALE_AFTER`, leave a live run
alone, and find the account from the outbox.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.copilot import jobs
from apps.api.db.session import tenant_session
from apps.api.teach import teaching
from apps.workers import interrupted_work
from apps.workers.settings import CRON_JOBS
from sqlalchemy import text
from tests.api_security_test import _make_tenant


def _user_of(token: str) -> UUID:
    return UUID(token.rsplit(":", 1)[1])


async def _running_job(tenant_id: UUID, user_id: UUID, *, age: timedelta) -> UUID:
    async with tenant_session(tenant_id) as session:
        job = await jobs.create_job(
            session, tenant_id=tenant_id, user_id=user_id, goal="tidy", screen_route="/c/x"
        )
        await jobs.claim_job(session, job_id=job.id)
        await session.execute(
            text("UPDATE copilot_jobs SET updated_at = :at WHERE id = :id"),
            {"at": datetime.now(UTC) - age, "id": job.id},
        )
    return job.id


async def _sorting_teaching(tenant_id: UUID, *, age: timedelta) -> UUID:
    async with tenant_session(tenant_id) as session:
        started = await teaching.start_teaching(
            session, tenant_id=tenant_id, input_kind="text", words="Open 9 to 9", requested_by=None
        )
        await session.execute(
            text("UPDATE kb_teachings SET status = 'sorting', updated_at = :at WHERE id = :id"),
            {"at": datetime.now(UTC) - age, "id": started.id},
        )
    return started.id


async def _row(tenant_id: UUID, table: str, row_id: UUID) -> tuple[Any, ...]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(f"SELECT status, error_code FROM {table} WHERE id = :id"), {"id": row_id}
            )
        ).one()
    return tuple(row)


async def test_the_outbox_names_the_account_that_queued_the_work() -> None:
    tenant_id, _slug, token = await _make_tenant()
    await _running_job(tenant_id, _user_of(token), age=timedelta(0))
    assert tenant_id in await interrupted_work.tenants_with_recent_work(datetime.now(UTC))


async def test_stale_work_is_ended_and_a_live_run_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    stale_job = await _running_job(tenant_id, user_id, age=timedelta(hours=1))
    live_job = await _running_job(tenant_id, user_id, age=timedelta(minutes=1))
    stale_teaching = await _sorting_teaching(tenant_id, age=timedelta(hours=1))
    live_teaching = await _sorting_teaching(tenant_id, age=timedelta(minutes=1))

    async def _only(_now: datetime) -> list[UUID]:
        return [tenant_id]

    monkeypatch.setattr(interrupted_work, "tenants_with_recent_work", _only)
    outcome = await interrupted_work.end_interrupted_work({})
    assert "jobs=1 teachings=1 failed=0" in outcome

    assert await _row(tenant_id, "copilot_jobs", stale_job) == (
        "failed",
        interrupted_work.INTERRUPTED_JOB_CODE,
    )
    assert (await _row(tenant_id, "copilot_jobs", live_job))[0] == "running"
    assert await _row(tenant_id, "kb_teachings", stale_teaching) == (
        "failed",
        interrupted_work.INTERRUPTED_TEACHING_CODE,
    )
    assert (await _row(tenant_id, "kb_teachings", live_teaching))[0] == "sorting"
    async with tenant_session(tenant_id) as session:
        ended = await jobs.read_job(session, job_id=stale_job, user_id=user_id)
    assert ended is not None and ended.result == interrupted_work.INTERRUPTED_JOB_RESULT

    # The freed slot is usable again: one live job plus one new one is the limit.
    async with tenant_session(tenant_id) as session:
        await jobs.create_job(
            session, tenant_id=tenant_id, user_id=user_id, goal="again", screen_route="/c/x"
        )


def test_the_sweep_is_registered_and_outlives_the_job_timeout() -> None:
    from apps.workers.settings import WorkerSettings

    assert f"cron:{interrupted_work.JOB_NAME}" in {job.name for job in CRON_JOBS}
    assert interrupted_work.STALE_AFTER.total_seconds() > WorkerSettings.job_timeout
