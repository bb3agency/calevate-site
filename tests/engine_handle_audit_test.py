"""The handle audit (D-693): a stored handle scoped to a workspace that is not its tenant's own
is a fault; an unscoped one is an object still in the platform account, reported only."""

from __future__ import annotations

import uuid

import pytest
from apps.api.db.session import tenant_session
from calevate_shared.engine_scope import scoped_handle
from scripts import engine_handle_audit
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant
from tests.workspace_support import give_own_workspace


async def test_the_audit_tells_a_foreign_handle_from_one_in_the_platform_account(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    legacy_ref = f"ag_{uuid.uuid4().hex[:8]}"
    tenant_id, agent_id = await _seed_tenant(legacy_ref)
    own = await give_own_workspace(tenant_id)
    foreign = scoped_handle(f"ag_{uuid.uuid4()}", "org_someone-else")
    mine = scoped_handle(f"out_{uuid.uuid4()}", own)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('thinnest', :ref, :tid, :aid, true, "
                "now(), now())"
            ),
            {"ref": foreign, "tid": tenant_id, "aid": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'inbound', 'completed', "
                "now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "aid": agent_id, "ecid": mine},
        )
    try:
        report = await engine_handle_audit.handle_report([tenant_id])
        assert report["engine_agent_routes.engine_agent_ref"]["foreign"] == 1
        assert report["agents.engine_agent_ref"] == {"platform_account": 1, "foreign": 0}
        assert report["calls.engine_call_id"] == {"platform_account": 0, "foreign": 0}

        async def _report(_tenants: object = None) -> dict[str, dict[str, int]]:
            return report

        monkeypatch.setattr(engine_handle_audit, "handle_report", _report)
        assert await engine_handle_audit.main() == 1
        assert "FOUND engine_agent_routes.engine_agent_ref: foreign=1" in capsys.readouterr().out

        async def _clean(_tenants: object = None) -> dict[str, dict[str, int]]:
            return {k: {"platform_account": 3, "foreign": 0} for k in report}

        monkeypatch.setattr(engine_handle_audit, "handle_report", _clean)
        assert await engine_handle_audit.main() == 0
    finally:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("DELETE FROM engine_agent_routes WHERE engine_agent_ref = :ref"),
                {"ref": foreign},
            )
