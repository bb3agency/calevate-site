"""How many calling setups one client's workspace may hold, per client.

1. `workspace_agent_allowance` answers the operator's recorded cap for this client's workspace,
   else the console's `thinnest_agents_per_workspace`, and one client's cap never reaches
   another.
2. A client whose cap is 3 is not refused at 2 setups, and is at 3.
3. The admin route reads and records it: step-up on the write, an audit row, the range
   checked, refused before the workspace exists, 404 for an unknown client.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import engine_workspace_routes
from apps.api.agents import service as agents_service
from apps.api.agents.workspace_slots import (
    ENGINE_AGENT_ALLOWANCE_FULL_RULE,
    workspace_agent_allowance,
    workspace_agent_override,
)
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.conftest import create_org_with_receptionist
from tests.workspace_support import give_own_workspace

pytestmark = [pytest.mark.rls]


async def _org() -> dict[str, Any]:
    return await create_org_with_receptionist(
        name="Allowance Tea House",
        slug=f"al-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )


async def _set(tenant_id: UUID, value: int | None) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE tenant_engine_workspaces SET agent_allowance = :n WHERE tenant_id = :t"),
            {"n": value, "t": tenant_id},
        )


async def _fill(tenant_id: UUID, agent_id: UUID, workspace: str, count: int) -> None:
    async with tenant_session(tenant_id) as session:
        for n in range(count):
            await session.execute(
                text(
                    "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                    "agent_id, active, created_at, updated_at) VALUES (:e, :r, :t, :a, true, "
                    "now(), now())"
                ),
                {
                    "e": get_engine().name,
                    "r": f"agent_{n}_{uuid.uuid4().hex[:6]}@{workspace}",
                    "t": tenant_id,
                    "a": agent_id,
                },
            )


async def _admin_headers() -> dict[str, str]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return {"Authorization": f"Bearer dev:admin:{admin_id}"}


def _http() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_the_recorded_cap_wins_and_null_falls_back_to_the_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "thinnest_agents_per_workspace", 2)
    raised, plain = await _org(), await _org()
    await give_own_workspace(raised["id"])
    await give_own_workspace(plain["id"])
    await _set(raised["id"], 5)
    async with tenant_session(raised["id"]) as session:
        assert await workspace_agent_allowance(session, raised["id"]) == 5
        # Under the raised client's RLS, the other client's row is invisible either way.
        assert await workspace_agent_override(session, plain["id"]) is None
    async with tenant_session(plain["id"]) as session:
        assert await workspace_agent_override(session, plain["id"]) is None
        assert await workspace_agent_allowance(session, plain["id"]) == 2
    await _set(raised["id"], None)
    async with tenant_session(raised["id"]) as session:
        assert await workspace_agent_allowance(session, raised["id"]) == 2


async def test_a_client_without_a_workspace_row_has_the_console_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "thinnest_agents_per_workspace", 4)
    org = await _org()
    async with tenant_session(org["id"]) as session:
        assert await workspace_agent_allowance(session, org["id"]) == 4


async def test_the_column_refuses_a_cap_below_one() -> None:
    org = await _org()
    await give_own_workspace(org["id"])
    with pytest.raises(IntegrityError):
        await _set(org["id"], 0)


async def test_a_client_raised_to_three_is_not_refused_at_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "thinnest_agents_per_workspace", 2)
    org = await _org()
    workspace = await give_own_workspace(org["id"])
    await _fill(org["id"], org["agent_id"], workspace, 2)

    async def refusal() -> ProblemError | None:
        async with tenant_session(org["id"]) as session:
            return await agents_service.allowance_refusal(
                session, tenant_id=org["id"], workspace=workspace, context="test_call"
            )

    full = await refusal()
    assert full is not None and full.code == ENGINE_AGENT_ALLOWANCE_FULL_RULE
    await _set(org["id"], 3)
    assert await refusal() is None
    await _fill(org["id"], org["agent_id"], workspace, 1)
    full = await refusal()
    assert full is not None
    assert full.as_problem()["limit"] == 3
    assert "Your account can have 3, and all are in use" in full.detail


async def test_the_operator_reads_and_records_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "thinnest_agents_per_workspace", 2)
    monkeypatch.setattr(engine_workspace_routes, "engine_has_workspaces", lambda *_a: True)
    org = await _org()
    tenant_id = org["id"]
    workspace = await give_own_workspace(tenant_id)
    await _fill(tenant_id, org["agent_id"], workspace, 1)
    url = f"/v1/admin/engine-workspaces/tenants/{tenant_id}/agent-allowance"
    headers = await _admin_headers()
    confirmed = {**headers, "X-Confirm-Action": f"set_agent_allowance:{tenant_id}"}
    async with _http() as http:
        read = await http.get(url, headers=headers)
        unconfirmed = await http.put(url, json={"agent_allowance": 3}, headers=headers)
        zero = await http.put(url, json={"agent_allowance": 0}, headers=confirmed)
        too_many = await http.put(url, json={"agent_allowance": 1001}, headers=confirmed)
        raised = await http.put(url, json={"agent_allowance": 3}, headers=confirmed)
        cleared = await http.put(url, json={"agent_allowance": None}, headers=confirmed)
        client = await http.get(url, headers={"Authorization": "Bearer dev:client:x"})
    assert read.status_code == 200, read.text
    assert read.json() == {
        "limit": 2,
        "agent_allowance": None,
        "default": 2,
        "in_use": 1,
        "settable": True,
        "min_allowance": 1,
        "max_allowance": 1000,
    }
    assert unconfirmed.status_code == 403, unconfirmed.text
    assert zero.status_code == 422 and too_many.status_code == 422
    assert raised.status_code == 200, raised.text
    assert (raised.json()["limit"], raised.json()["agent_allowance"]) == (3, 3)
    assert cleared.status_code == 200, cleared.text
    assert (cleared.json()["limit"], cleared.json()["agent_allowance"]) == (2, None)
    assert client.status_code in (401, 403)
    async with tenant_session(tenant_id) as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'engine_workspace.agent_allowance_set'"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert audited == 2


async def test_no_cap_is_recorded_before_the_workspace_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_workspace_routes, "engine_has_workspaces", lambda *_a: True)
    org = await _org()
    tenant_id = org["id"]
    url = f"/v1/admin/engine-workspaces/tenants/{tenant_id}/agent-allowance"
    headers = await _admin_headers()
    async with _http() as http:
        read = await http.get(url, headers=headers)
        refused = await http.put(
            url,
            json={"agent_allowance": 3},
            headers={**headers, "X-Confirm-Action": f"set_agent_allowance:{tenant_id}"},
        )
        missing = await http.get(
            f"/v1/admin/engine-workspaces/tenants/{uuid.uuid4()}/agent-allowance",
            headers=headers,
        )
    assert read.status_code == 200, read.text
    assert (read.json()["settable"], read.json()["in_use"]) == (False, None)
    assert refused.status_code == 422, refused.text
    assert refused.json()["type"].endswith("/engine_workspace_not_provisioned")
    assert missing.status_code == 404
