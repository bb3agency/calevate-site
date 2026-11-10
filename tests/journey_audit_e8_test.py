"""Journey audit E8 (10 Nov 2026): an owner's full session with Pip.

Each test failed on 380862cdc before its fix.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from apps.api.copilot import jobs, routines, write_tools
from apps.api.copilot.actions import WriteRefusedError
from apps.api.copilot.question_actions_test import _member
from apps.api.copilot.write_tools_test import _principal
from apps.api.db.session import tenant_session
from apps.api.tenancy.members import acting_member_role
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.conftest import turn_pip_on_for_tests
from tests.teach_questions_test import _tenant as _teach_tenant

_CLOSE = {
    # `ck_organizations_deleted_implies_churned`: a closed account is churned as well.
    "closed": "UPDATE organizations SET deleted_at = now(), status = 'churned' WHERE id = :t",
    "churned": "UPDATE organizations SET status = 'churned' WHERE id = :t",
}


def _user_of(token: str) -> UUID:
    return UUID(token.rsplit(":", 1)[1])


async def _end_account(tenant_id: UUID, how: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(text(_CLOSE[how]), {"t": tenant_id})


@pytest.mark.parametrize("how", ["closed", "churned"])
async def test_background_work_does_not_act_for_an_account_that_has_ended(how: str) -> None:
    """FAILS IF: a Pip job, routine or approved plan acts as a member of an account the
    member can no longer open. `_load_client_principal` refuses every request on a closed
    or churned account; queued work runs as `acting_member_role`, which only asked about
    the membership and the person, so a routine set up earlier kept spending model turns on
    the account's data and staging changes after it was closed."""
    tenant_id, _slug, token = await _make_tenant()
    await _end_account(tenant_id, how)
    async with tenant_session(tenant_id) as session:
        assert await acting_member_role(session, _user_of(token)) is None


async def test_a_suspended_account_s_background_work_still_runs() -> None:
    """A suspended client still signs in (`core/auth`: suspension stops dialling, nothing
    else), so their own Pip work still runs as them."""
    tenant_id, _slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'suspended' WHERE id = :t"), {"t": tenant_id}
        )
        assert await acting_member_role(session, _user_of(token)) == "owner"


async def test_a_closed_account_s_queued_job_makes_no_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the job worker runs Pip for an account closed after the job was queued."""
    from apps.api.copilot import service
    from apps.workers.copilot_jobs import run_copilot_job

    tenant_id, _slug, token = await _make_tenant()
    await turn_pip_on_for_tests(tenant_id)
    async with tenant_session(tenant_id) as session:
        job = await jobs.create_job(
            session,
            tenant_id=tenant_id,
            user_id=_user_of(token),
            goal="tidy my leads",
            screen_route="/c/{slug}/leads",
        )
    await _end_account(tenant_id, "closed")

    def _no_model(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("a model was asked for a closed account")

    monkeypatch.setattr(service, "run_copilot", _no_model)
    outcome = await run_copilot_job({}, {"job_id": str(job.id), "tenant_id": str(tenant_id)})
    assert outcome == "member_gone"
    async with tenant_session(tenant_id) as session:
        assert await jobs.job_status(session, job_id=job.id) == "failed"


async def test_a_churned_account_s_routine_starts_no_job() -> None:
    """FAILS IF: a due routine of a churned account queues a Pip job."""
    tenant_id, _slug, token = await _make_tenant()
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        created = await routines.create_routine(
            session,
            tenant_id=tenant_id,
            user_id=_user_of(token),
            name="Morning check",
            instruction="Tell me which hot leads nobody called back",
            days=0b1111111,
            at_minute=9 * 60,
            enabled=True,
            now=now,
        )
        await session.execute(
            text("UPDATE copilot_routines SET next_run_at = :slot WHERE id = :id"),
            {"slot": now - timedelta(minutes=1), "id": created.id},
        )
    await _end_account(tenant_id, "churned")
    async with tenant_session(tenant_id) as session:
        assert await routines.fire_due(session, routine_id=created.id, now=now) == "skipped"
        queued = (
            await session.execute(
                text("SELECT count(*) FROM copilot_jobs WHERE user_id = :u"),
                {"u": _user_of(token)},
            )
        ).scalar()
    assert queued == 0


# --- E8-02: a deleted agent, through Pip ----------------------------------------------------


def _test_case_args(agent_id: UUID) -> str:
    return json.dumps(
        {
            "agent_id": str(agent_id),
            "caller_lines": ["Do you deliver on Sunday?"],
            "expected": "Says yes, before noon.",
            "title": None,
        }
    )


async def _delete_agent(tenant_id: UUID, agent_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'archived', archived_at = now() WHERE id = :a"),
            {"a": agent_id},
        )


async def _saved_tests(tenant_id: UUID, agent_id: UUID) -> int:
    async with tenant_session(tenant_id) as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM agent_test_cases WHERE agent_id = :a"), {"a": agent_id}
            )
        ).scalar()
    return int(count or 0)


async def test_pip_cannot_add_a_test_to_a_deleted_agent() -> None:
    """FAILS IF: Pip saves a test on a deleted agent. `POST /v1/agents/{agent_id}/test-cases`
    is refused by the route guard for a deleted agent; Pip's guard only looked at tools whose
    `object_type` is `agent`, and `agent_test_add` records an `agent_test_case`."""
    tenant_id, agent_id, _slug = await _teach_tenant()
    user_id = await _member(tenant_id)
    await _delete_agent(tenant_id, agent_id)
    with pytest.raises(WriteRefusedError) as refused:
        await write_tools.run_immediate(
            "agent_test_add",
            _test_case_args(agent_id),
            principal=_principal(tenant_id, user_id),
            seed=f"e8-{uuid.uuid4()}",
            ip=None,
        )
    assert "deleted" in refused.value.reason
    assert await _saved_tests(tenant_id, agent_id) == 0


async def test_an_approval_waiting_on_an_agent_deleted_since_does_nothing() -> None:
    """FAILS IF: approving a change a background task staged runs it on an agent deleted
    after it was staged. An approval waits up to a day; staging checked the agent, Approve
    did not."""
    tenant_id, agent_id, _slug = await _teach_tenant()
    user_id = await _member(tenant_id)
    principal = _principal(tenant_id, user_id)
    async with tenant_session(tenant_id) as session:
        job = await jobs.create_job(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            goal="add a test",
            screen_route="/c/{slug}/agents",
        )
    staged = await write_tools.stage_for_approval(
        "agent_test_add", _test_case_args(agent_id), principal=principal, job_id=job.id
    )
    await _delete_agent(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        outcome = await write_tools.approve(session, staged.action_id, principal=principal, ip=None)
    assert outcome.applied is False
    assert await _saved_tests(tenant_id, agent_id) == 0
