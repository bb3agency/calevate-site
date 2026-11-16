"""The first run's agent says its AI notice (D-864), switched on by `switch_on_first_notice`
after "Name and voice" makes it.

Every agent is created with both notices off (D-669), so without the job the first run's agent
would open with no AI notice. These make the agent through `PUT /v1/first-run/agent`, as the
screen does, run the job it queued, and read the agent the way the agent screen does
(`roster.agent_by_id`).
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.agents import roster
from apps.api.agents.publishing import set_disclosure_posture
from apps.api.compliance.audit import write_audit
from apps.api.compliance.disclosure import ai_disclosure_for
from apps.api.db.session import tenant_session
from apps.api.first_run import routes as first_run_routes
from apps.workers import first_run as worker
from sqlalchemy import text
from tests.first_run_test import _owner, _tenant
from tests.first_run_work_test import _made


@pytest.fixture(autouse=True)
def _no_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _none(_tenant_id: uuid.UUID, _language: str, **_kw: object) -> None:
        return None

    monkeypatch.setattr(first_run_routes, "pick_voice", _none)


async def _first_agent() -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = await _tenant()
    body = await _made(tenant_id, await _owner(tenant_id))
    return tenant_id, uuid.UUID(body["agent_id"])


async def _notice(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    payload = {"tenant_id": str(tenant_id), "agent_id": str(agent_id)}
    return await worker.switch_on_first_notice({}, payload)


async def test_the_first_agents_ai_notice_is_switched_on_and_audited_as_the_system() -> None:
    tenant_id, agent_id = await _first_agent()
    assert await _notice(tenant_id, agent_id) == "done"
    async with tenant_session(tenant_id) as session:
        agent = await roster.agent_by_id(session, agent_id)
        audited = (
            (
                await session.execute(
                    text("SELECT actor_type FROM audit_log WHERE action = :a AND object_id = :o"),
                    {"a": "agent.ai_disclosure_enabled", "o": str(agent_id)},
                )
            )
            .scalars()
            .all()
        )
        business = (await session.execute(text("SELECT name FROM organizations"))).scalar_one()
    assert agent is not None
    assert agent.ai_disclosure_enabled
    assert not agent.recording_notice_enabled, "the recording notice stays the owner's choice"
    assert agent.ai_disclosure_line.strip() == ai_disclosure_for(
        language="te-IN", business=str(business), name="Anjali"
    )
    assert audited == ["system"]
    # A second delivery changes nothing and writes no second audit row.
    assert await _notice(tenant_id, agent_id) == "done"
    async with tenant_session(tenant_id) as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM audit_log WHERE action = :a AND object_id = :o"),
                {"a": "agent.ai_disclosure_enabled", "o": str(agent_id)},
            )
        ).scalar_one()
    assert count == 1


async def test_the_notice_stays_off_when_the_owner_switched_it_off() -> None:
    tenant_id, agent_id = await _first_agent()
    assert await _notice(tenant_id, agent_id) == "done"
    await set_disclosure_posture(
        tenant_id=tenant_id,
        agent_id=agent_id,
        ai_disclosure_enabled=False,
        recording_notice_enabled=None,
    )
    async with tenant_session(tenant_id) as session:
        await write_audit(
            session,
            action="agent.ai_disclosure_disabled",
            actor_type="user",
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip="203.0.113.7",
        )
    assert await _notice(tenant_id, agent_id) == "off"
    async with tenant_session(tenant_id) as session:
        agent = await roster.agent_by_id(session, agent_id)
    assert agent is not None and not agent.ai_disclosure_enabled
