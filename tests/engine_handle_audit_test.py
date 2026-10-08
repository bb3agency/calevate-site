"""D-688 left no way to write or read a workspace-scoped engine handle; this proves the audit
that finds any already stored (`scripts/engine_handle_audit.py`) sees each column it names.
"""

from __future__ import annotations

import importlib.util
import uuid

import pytest
from apps.api.db.session import tenant_session
from scripts import engine_handle_audit
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant


def test_nothing_in_the_tree_can_compose_a_scoped_handle_any_more() -> None:
    assert importlib.util.find_spec("calevate_shared.engine_scope") is None


async def test_the_audit_finds_a_scoped_handle_in_each_column_it_names(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant_id, agent_id = await _seed_tenant(f"ag_{uuid.uuid4().hex[:8]}@org_audit")
    scoped = f"ag_{uuid.uuid4()}@org_audit"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('thinnest', :ref, :tid, :aid, true, "
                "now(), now())"
            ),
            {"ref": scoped, "tid": tenant_id, "aid": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'inbound', 'completed', "
                "now(), now())"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"out_{uuid.uuid4()}@org_audit",
            },
        )
    try:
        counts = await engine_handle_audit.scoped_handle_counts([tenant_id])
        assert counts["engine_agent_routes.engine_agent_ref"] >= 1
        assert counts["agents.engine_agent_ref"] == 1
        assert counts["calls.engine_call_id"] == 1
        assert "engine_kb_routes.engine_kb_ref" in counts

        async def _scoped(_tenants: object = None) -> dict[str, int]:
            return counts

        monkeypatch.setattr(engine_handle_audit, "scoped_handle_counts", _scoped)
        assert await engine_handle_audit.main() == 1
        assert "FOUND agents.engine_agent_ref: 1" in capsys.readouterr().out

        async def _clean(_tenants: object = None) -> dict[str, int]:
            return dict.fromkeys(counts, 0)

        monkeypatch.setattr(engine_handle_audit, "scoped_handle_counts", _clean)
        assert await engine_handle_audit.main() == 0
    finally:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("DELETE FROM engine_agent_routes WHERE engine_agent_ref = :ref"),
                {"ref": scoped},
            )
