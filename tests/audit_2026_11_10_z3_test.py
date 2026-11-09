"""Backend audit round 5, lane Z3 (10 Nov 2026): the engine boundary.

- Z3-01: a call an agent took before its route was retired (the agent recreated in its
  client's own workspace, an experiment concluded) is recorded when its results arrive
  after the retirement, instead of being dropped as "unmapped" with no minute metered. A
  call that began after the retirement, and any call of an account under erasure, still is.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers import pipeline
from calevate_shared.engine import ExecutionSnapshot
from sqlalchemy import text
from tests.thinnest_call_lifecycle_test import _routed_tenant


def _finished_call(engine_call_id: str, *, began: datetime) -> ExecutionSnapshot:
    return ExecutionSnapshot(
        engine_call_id=engine_call_id,
        direction="inbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        started_at=began,
        ended_at=began + timedelta(seconds=61),
        duration_s=61,
        from_e164="+919800000002",
    )


async def _retired_route(tenant_id: uuid.UUID) -> str:
    """The tenant's only route, switched off now, as the retire job and experiment
    conclusion leave it."""
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text(
                    "UPDATE engine_agent_routes SET active = false, updated_at = now() "
                    "WHERE tenant_id = :t RETURNING engine_agent_ref"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    return str(ref)


async def _ingest(
    monkeypatch: pytest.MonkeyPatch, snapshot: ExecutionSnapshot, ref: str
) -> tuple[str, list[str]]:
    queued: list[str] = []
    alarms: list[str] = []

    async def _truth(*_a: Any, **_k: Any) -> ExecutionSnapshot:
        return snapshot

    async def _enqueue(job: str, *_a: Any, **_k: Any) -> str:
        queued.append(job)
        return "job"

    monkeypatch.setattr(pipeline, "execution_truth", _truth)
    monkeypatch.setattr(pipeline, "enqueue", _enqueue)
    monkeypatch.setattr(pipeline, "alert", lambda _stage, code, **_k: alarms.append(code))
    outcome = await pipeline._ingest_stages(
        "fake", snapshot.engine_call_id, None, {"engine_agent_ref": ref}
    )
    return outcome, alarms


async def _call_row(tenant_id: uuid.UUID, engine_call_id: str) -> tuple[Any, ...] | None:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT agent_id, status, duration_s FROM calls WHERE engine_call_id = :e"),
                {"e": engine_call_id},
            )
        ).first()
    return tuple(row) if row is not None else None


async def test_a_call_taken_before_its_route_was_retired_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _routed_tenant()
    began = datetime.now(UTC) - timedelta(minutes=3)
    ref = await _retired_route(tenant_id)
    call = f"in_{uuid.uuid4()}"

    outcome, alarms = await _ingest(monkeypatch, _finished_call(call, began=began), ref)

    assert outcome == "pipeline_enqueued", (
        "a call the client's agent took before the route was retired is the client's call"
    )
    assert alarms == []
    assert await _call_row(tenant_id, call) == (agent_id, "completed", 61)


async def test_a_call_that_began_after_its_route_was_retired_still_raises_the_alarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _agent_id = await _routed_tenant()
    ref = await _retired_route(tenant_id)
    call = f"in_{uuid.uuid4()}"

    outcome, alarms = await _ingest(
        monkeypatch, _finished_call(call, began=datetime.now(UTC) + timedelta(minutes=1)), ref
    )

    assert outcome == "unmapped"
    assert alarms == ["engine_agent_route_withdrawn"]
    assert await _call_row(tenant_id, call) is None


async def test_an_account_under_erasure_records_no_call_from_a_retired_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _agent_id = await _routed_tenant()
    began = datetime.now(UTC) - timedelta(minutes=3)
    ref = await _retired_route(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO tenant_erasure_requests (id, tenant_id, reason, requested_at, "
                "created_at) VALUES (:id, :t, 'engagement ended', now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id},
        )
    call = f"in_{uuid.uuid4()}"

    outcome, alarms = await _ingest(monkeypatch, _finished_call(call, began=began), ref)

    assert outcome == "unmapped"
    assert alarms == ["engine_agent_route_withdrawn"]
    assert await _call_row(tenant_id, call) is None


async def test_the_poller_finds_the_row_of_a_call_on_a_retired_route() -> None:
    """Read as `missing_call`, the poller re-drove such a call on every tick into the same
    `unmapped` refusal."""
    tenant_id, agent_id = await _routed_tenant()
    began = datetime.now(UTC) - timedelta(minutes=3)
    ref = await _retired_route(tenant_id)
    snapshot = _finished_call(f"in_{uuid.uuid4()}", began=began).model_copy(
        update={"engine_agent_ref": ref}
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, ended_at, duration_s, created_at, updated_at) VALUES (:id, :t, :a, "
                ":e, 'inbound', 'completed', :s, :end, 61, now(), now())"
            ),
            {
                "id": uuid7(),
                "t": tenant_id,
                "a": agent_id,
                "e": snapshot.engine_call_id,
                "s": snapshot.started_at,
                "end": snapshot.ended_at,
            },
        )

    assert await pipeline._pipeline_settled("fake", snapshot) != "missing_call"
