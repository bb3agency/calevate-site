"""A promised post-call pipeline that never metered the client's minute is re-driven.

On the owned runtime the worker's settlement writes the speech and language leg rows and the
call's turns before the post-call pipeline runs, and `PipecatEngine.list_executions` is empty
by design. So a pipeline that ran out of retries left a call that every sweep read as
finished: `reconcile_outstanding_calls` asked only about completed calls with no usage row
and no turn, and `_pipeline_settled` counted the worker's leg rows as the meter's. The
client was never debited, the call never extracted or filed, and only an alarm said so.

Run: uv run python -m pytest -q tests/owned_runtime_redrive_test.py
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.pipecat import PIPECAT_CAPABILITIES
from apps.api.reliability.service import enqueue_outbox_once
from apps.api.worker.service import POSTCALL_DEDUPE_PREFIX
from apps.workers import pipeline
from calevate_shared.engine import CostBreakdown, ExecutionSnapshot
from sqlalchemy import text
from tests.carrier_event_job_test import make_tenant

pytestmark = [pytest.mark.rls]


class _Engine:
    capabilities = PIPECAT_CAPABILITIES

    def __init__(self, snapshot: ExecutionSnapshot) -> None:
        self.name = get_settings().engine
        self.snapshot = snapshot

    async def get_execution(self, execution_id: str) -> ExecutionSnapshot:
        return self.snapshot


async def _settled_call(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, metered: bool
) -> tuple[uuid.UUID, str]:
    """What a worker settlement leaves: a completed row, a leg row, a turn, the promise."""
    call_id = uuid7()
    ecid = f"pipecat:{tenant_id}:{call_id}"
    began = datetime.now(UTC) - timedelta(minutes=25)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, ended_at, duration_s, created_at, updated_at) VALUES (:i, :t, :a, "
                ":e, 'inbound', 'completed', :b, :end, 60, :b, now())"
            ),
            {
                "i": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": ecid,
                "b": began,
                "end": began + timedelta(minutes=1),
            },
        )
        units = ["stt_min", "telephony_s"] if metered else ["stt_min"]
        for unit in units:
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, :u, 1, "
                    "NULL, :at, CAST(:m AS jsonb), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "u": unit,
                    "at": began,
                    "m": json.dumps({}),
                },
            )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "created_at, updated_at) VALUES (:i, :t, :c, 0, 'agent', 'hello', now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id},
        )
        await enqueue_outbox_once(
            session,
            job=pipeline.POSTCALL_JOB,
            payload={"tenant_id": str(tenant_id), "call_id": str(call_id)},
            dedupe_key=f"{POSTCALL_DEDUPE_PREFIX}{call_id}",
        )
    return call_id, ecid


def _snapshot(ecid: str, ref: str) -> ExecutionSnapshot:
    return ExecutionSnapshot(
        engine_call_id=ecid,
        engine_agent_ref=ref,
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=False,
        engine="pipecat",
        cost=CostBreakdown(
            total_inr=Decimal("0.50"),
            source_currency="INR",
            currency_stated=True,
            legs_metered_at_settlement=True,
        ),
    )


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    jobs: list[tuple[str, dict[str, Any]]] = []

    async def _enqueue(job: str, payload: dict[str, Any], **kwargs: Any) -> None:
        jobs.append((job, payload))

    monkeypatch.setattr(pipeline, "enqueue", _enqueue)
    monkeypatch.setattr(pipeline, "alert", lambda *a, **kw: None)
    return jobs


async def test_a_promised_pipeline_that_never_metered_is_redriven(
    monkeypatch: pytest.MonkeyPatch, enqueued: list[tuple[str, dict[str, Any]]]
) -> None:
    tenant_id, agent_id, ref = await make_tenant()
    _call_id, ecid = await _settled_call(tenant_id, agent_id, metered=False)

    async def _only_this_tenant() -> list[uuid.UUID]:
        return [tenant_id]

    monkeypatch.setattr(pipeline, "callable_tenants", _only_this_tenant)
    monkeypatch.setattr(pipeline, "get_engine", lambda: _Engine(_snapshot(ecid, ref)))

    outcome = await pipeline.reconcile_outstanding_calls({})

    assert outcome.startswith("repaired=1 probed=1 ")
    [(job, payload)] = enqueued
    assert job == pipeline.INGEST_JOB and payload["execution_id"] == ecid


async def test_a_call_whose_minute_was_metered_is_not_probed(
    monkeypatch: pytest.MonkeyPatch, enqueued: list[tuple[str, dict[str, Any]]]
) -> None:
    tenant_id, agent_id, ref = await make_tenant()
    _call_id, ecid = await _settled_call(tenant_id, agent_id, metered=True)

    async def _only_this_tenant() -> list[uuid.UUID]:
        return [tenant_id]

    monkeypatch.setattr(pipeline, "callable_tenants", _only_this_tenant)
    monkeypatch.setattr(pipeline, "get_engine", lambda: _Engine(_snapshot(ecid, ref)))

    outcome = await pipeline.reconcile_outstanding_calls({})

    assert outcome.startswith("repaired=0 probed=0 ")
    assert enqueued == []


async def test_the_worker_leg_rows_are_not_the_meters_artefact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_pipeline_settled` answered `settled` off the settlement's own leg rows."""
    tenant_id, agent_id, ref = await make_tenant()
    _call_id, ecid = await _settled_call(tenant_id, agent_id, metered=False)

    assert await pipeline._pipeline_settled(get_settings().engine, _snapshot(ecid, ref)) == (
        "unfinished_pipeline"
    )
