"""D-694: background jobs and the Approvals inbox.

A job is a row and its outbox message, written together; its rows are invisible across
tenants; a confirm-tier step a job reaches waits for a person, who approves it against the
world as it is then, or declines it.
"""

from __future__ import annotations

import json
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.copilot import jobs, service, write_tools
from apps.api.copilot.models import MAX_JOB_PROGRESS
from apps.api.core.context import Principal
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app


def _user_of(token: str) -> UUID:
    return UUID(token.rsplit(":", 1)[1])


def _principal(tenant_id: UUID, user_id: UUID, *, role: str = "owner") -> Principal:
    return Principal(realm="client", user_id=user_id, tenant_id=tenant_id, role=role)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _job(tenant_id: UUID, token: str, goal: str = "tidy my leads") -> jobs.JobRow:
    async with tenant_session(tenant_id) as session:
        return await jobs.create_job(
            session,
            tenant_id=tenant_id,
            user_id=_user_of(token),
            goal=goal,
            screen_route="/c/{slug}/leads",
        )


async def _lead_of(tenant_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text("SELECT id FROM leads LIMIT 1"))).first()
    assert row is not None
    return UUID(str(row[0]))


async def _dnc_count(tenant_id: UUID) -> int:
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
    return int(value or 0)


def test_the_job_limits_fit_inside_the_worker_and_leave_the_panel_alone() -> None:
    """A job ends with a sentence of its own before arq's `job_timeout` cancels it, and the
    interactive limits are the constants `deadline_test.py` measures, unchanged."""
    from apps.workers.settings import WorkerSettings

    limits = service.job_limits(UUID(int=1))
    assert limits.total_budget_s < WorkerSettings.job_timeout
    assert limits.mode == "job"
    assert service.INTERACTIVE_LIMITS.max_turns == service.MAX_TURNS
    assert service.INTERACTIVE_LIMITS.total_budget_s == service.TOTAL_BUDGET_S


async def test_a_job_is_a_row_and_its_outbox_message_together() -> None:
    tenant_id, _slug, token = await _make_tenant()
    job = await _job(tenant_id, token)
    assert job.status == "queued"
    async with untenanted_session() as session:
        queued = (
            await session.execute(
                text("SELECT job FROM outbox_messages WHERE payload->>'job_id' = :j"),
                {"j": str(job.id)},
            )
        ).all()
    assert [row[0] for row in queued] == [jobs.COPILOT_JOB]


async def test_a_person_may_run_only_two_jobs_at_once() -> None:
    tenant_id, _slug, token = await _make_tenant()
    await _job(tenant_id, token)
    await _job(tenant_id, token)
    with pytest.raises(jobs.TooManyJobsError):
        await _job(tenant_id, token)


async def test_copilot_jobs_rls_returns_zero_rows_across_tenants() -> None:
    tenant_a, _slug_a, token_a = await _make_tenant()
    tenant_b, slug_b, token_b = await _make_tenant()
    job = await _job(tenant_a, token_a)
    async with tenant_session(tenant_b) as session:
        seen = (await session.execute(text("SELECT count(*) FROM copilot_jobs"))).scalar()
    assert seen == 0
    async with _client() as http:
        response = await http.get(f"/v1/copilot/jobs/{job.id}", headers=_headers(token_b, slug_b))
    assert response.status_code == 404


async def test_progress_is_bounded_and_the_job_route_reads_it() -> None:
    tenant_id, slug, token = await _make_tenant()
    job = await _job(tenant_id, token)
    async with tenant_session(tenant_id) as session:
        await jobs.claim_job(session, job_id=job.id)
        await jobs.append_progress(
            session,
            job_id=job.id,
            entries=[jobs.progress_entry("step", f"step {n}") for n in range(MAX_JOB_PROGRESS + 5)],
        )
    async with _client() as http:
        response = await http.get(f"/v1/copilot/jobs/{job.id}", headers=_headers(token, slug))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "running"
    assert len(body["progress"]) == MAX_JOB_PROGRESS
    # The NEWEST are kept.
    assert body["progress"][-1]["text"] == f"step {MAX_JOB_PROGRESS + 4}"


async def test_cancel_stops_a_queued_job() -> None:
    tenant_id, slug, token = await _make_tenant()
    job = await _job(tenant_id, token)
    async with _client() as http:
        response = await http.post(
            f"/v1/copilot/jobs/{job.id}/cancel", headers=_headers(token, slug)
        )
    assert response.json()["status"] == "cancelled"
    async with tenant_session(tenant_id) as session:
        assert await jobs.claim_job(session, job_id=job.id) is None


async def _stage_dnc(tenant_id: UUID, token: str) -> write_tools.StagedApproval:
    job = await _job(tenant_id, token)
    return await write_tools.stage_for_approval(
        "dnc_add",
        json.dumps({"lead_id": str(await _lead_of(tenant_id)), "reason": "manual"}),
        principal=_principal(tenant_id, _user_of(token)),
        job_id=job.id,
    )


async def test_a_staged_action_changes_nothing_until_it_is_approved() -> None:
    """NOTHING IRREVERSIBLE RUNS UNATTENDED: staging is a read, approval is the act."""
    tenant_id, slug, token = await _make_tenant()
    staged = await _stage_dnc(tenant_id, token)
    assert await _dnc_count(tenant_id) == 0

    async with _client() as http:
        inbox = await http.get("/v1/copilot/approvals", headers=_headers(token, slug))
        assert [row["id"] for row in inbox.json()["actions"]] == [str(staged.action_id)]
        approved = await http.post(
            f"/v1/copilot/approvals/{staged.action_id}/approve", headers=_headers(token, slug)
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["applied"] is True
        again = await http.post(
            f"/v1/copilot/approvals/{staged.action_id}/approve", headers=_headers(token, slug)
        )
    assert again.status_code == 409
    assert await _dnc_count(tenant_id) == 1
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, pending_args FROM copilot_actions WHERE id = :i"),
                {"i": staged.action_id},
            )
        ).first()
    assert row is not None
    assert row[0] == "done"
    assert row[1] is None, "executable intent must not outlive the decision"


async def test_a_declined_action_never_runs() -> None:
    tenant_id, slug, token = await _make_tenant()
    staged = await _stage_dnc(tenant_id, token)
    async with _client() as http:
        declined = await http.post(
            f"/v1/copilot/approvals/{staged.action_id}/reject", headers=_headers(token, slug)
        )
    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "rejected"
    assert await _dnc_count(tenant_id) == 0


async def test_another_tenant_cannot_approve() -> None:
    tenant_a, _slug_a, token_a = await _make_tenant()
    _tenant_b, slug_b, token_b = await _make_tenant()
    staged = await _stage_dnc(tenant_a, token_a)
    async with _client() as http:
        crossed = await http.post(
            f"/v1/copilot/approvals/{staged.action_id}/approve", headers=_headers(token_b, slug_b)
        )
    assert crossed.status_code == 404
    assert await _dnc_count(tenant_a) == 0


async def test_an_immediate_tool_is_never_staged() -> None:
    tenant_id, _slug, token = await _make_tenant()
    job = await _job(tenant_id, token)
    with pytest.raises(write_tools.WriteRefusedError):
        await write_tools.stage_for_approval(
            "lead_set_status",
            json.dumps({"lead_id": str(await _lead_of(tenant_id)), "status": "hot"}),
            principal=_principal(tenant_id, _user_of(token)),
            job_id=job.id,
        )


async def test_a_staff_member_cannot_stage_what_their_role_cannot_do() -> None:
    tenant_id, _slug, token = await _make_tenant(role="staff")
    job = await _job(tenant_id, token)
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await write_tools.stage_for_approval(
            "dnc_add",
            json.dumps({"lead_id": str(await _lead_of(tenant_id)), "reason": "manual"}),
            principal=_principal(tenant_id, _user_of(token), role="staff"),
            job_id=job.id,
        )
    assert "role may not" in refused.value.reason
