"""The hourly agent-move sweep visits every account even when one of them raises.

Both walks it drives (`walk_workspaces`, `resumed_walk`) move their cursor only once the body
returns, so an uncaught error would put the same account first again every hour and stop
every account behind it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from apps.api.db.base import uuid7
from apps.api.tenancy.engine_workspace import WorkspaceRow
from apps.workers import agent_moves, workspace_walk


@pytest.fixture
def alarms(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str | None]]:
    raised: list[tuple[str, str, str | None]] = []

    def _alert(stage: str, code: str, *, detail: str | None = None, **ids: str) -> None:
        raised.append((stage, code, detail))

    monkeypatch.setattr(agent_moves, "alert", _alert)
    return raised


async def test_one_failing_workspace_does_not_stop_the_others(
    monkeypatch: pytest.MonkeyPatch, alarms: list[tuple[str, str, str | None]]
) -> None:
    broken, healthy = uuid7(), uuid7()
    rows = [
        WorkspaceRow(tenant_id=broken, status="active", workspace_id="org_broken"),
        WorkspaceRow(tenant_id=healthy, status="active", workspace_id="org_healthy"),
    ]

    async def _rows(**_kw: Any) -> list[WorkspaceRow]:
        return rows

    async def _retire(_session: Any, *, tenant_id: UUID, workspace: str | None) -> int:
        if tenant_id == broken:
            raise RuntimeError("boom")
        return 0

    async def _owed(_session: Any, *, tenant_id: UUID, workspace: str) -> list[UUID]:
        return [uuid7()]

    queued: list[UUID] = []

    async def _queue(_session: Any, *, tenant_id: UUID, workspace: str, tick: str) -> int:
        queued.append(tenant_id)
        return 1

    async def _outside() -> tuple[int, int]:
        return 0, 0

    monkeypatch.setattr(agent_moves, "engine_has_workspaces", lambda *a: True)
    monkeypatch.setattr(workspace_walk, "active_workspaces", _rows)
    monkeypatch.setattr(agent_moves, "_retire_test_copies", _retire)
    monkeypatch.setattr(agent_moves, "agents_to_move", _owed)
    monkeypatch.setattr(agent_moves, "queue_agent_move", _queue)
    monkeypatch.setattr(agent_moves, "_retire_copies_outside_workspaces", _outside)

    summary = await agent_moves.sweep_agent_moves({})

    assert queued == [healthy]
    assert "failed=1" in summary
    assert alarms == [("WORKER_DELIVERY", "agent_move_sweep_failed", "1 account(s)")]


async def test_one_failing_account_outside_workspaces_does_not_stop_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken, healthy = uuid7(), uuid7()
    monkeypatch.setattr(
        agent_moves,
        "_ROUTED_TENANTS_SQL",
        f"SELECT x FROM (VALUES ('{broken}'::uuid), ('{healthy}'::uuid)) v(x)",
    )

    async def _none(**_kw: Any) -> list[WorkspaceRow]:
        return []

    seen: list[UUID] = []

    async def _retire(_session: Any, *, tenant_id: UUID, workspace: str | None) -> int:
        seen.append(tenant_id)
        if tenant_id == broken:
            raise RuntimeError("boom")
        return 2

    monkeypatch.setattr(agent_moves, "active_workspaces", _none)
    monkeypatch.setattr(agent_moves, "_retire_test_copies", _retire)

    assert await agent_moves._retire_copies_outside_workspaces() == (2, 1)
    assert sorted(seen) == sorted([broken, healthy])
