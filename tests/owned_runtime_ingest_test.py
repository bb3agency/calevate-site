"""A re-driven ingest must reach the post-call pipeline on an `owned_runtime` engine.

`reconcile_outstanding_calls` repairs a completed call whose pipeline left an owed artefact
behind by enqueueing `INGEST_JOB`, and ingest hands off to the post-call pipeline only when
the snapshot is `billable_ready`. The Pipecat adapter never sets that flag (the connected
minute is the carrier's to witness, `engine/pipecat.py::execution`), so on the only live
engine every repair ended at `awaiting_completion:completed`: the poller counted a repair,
nothing ran, and the call's extraction, lead and CRM fan-out stayed missing for good.

On an owned runtime the record IS ours and is final once the call is terminal — which is
exactly when the worker's settlement promises the pipeline — so terminal is the gate there.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.engine.pipecat import PIPECAT_CAPABILITIES
from apps.workers import pipeline
from calevate_shared.engine import ExecutionSnapshot

TENANT = uuid4()
AGENT = uuid4()
CALL = uuid4()


class _Engine:
    name = "pipecat"
    capabilities = PIPECAT_CAPABILITIES

    def __init__(self, snapshot: ExecutionSnapshot) -> None:
        self._snapshot = snapshot

    async def get_execution(self, execution_id: str) -> ExecutionSnapshot:
        return self._snapshot


def _snapshot(status: str, *, billable_ready: bool = False) -> ExecutionSnapshot:
    return ExecutionSnapshot(
        engine_call_id=f"pipecat:{TENANT}:{uuid4()}",
        engine_agent_ref=f"pipecat:{TENANT}:{AGENT}",
        status=status,  # type: ignore[arg-type]
        raw_status=status,
        terminal=status in pipeline.TERMINAL_STATUSES,
        billable_ready=billable_ready,
        engine="pipecat",
    )


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    jobs: list[tuple[str, dict[str, Any]]] = []

    @asynccontextmanager
    async def _no_session() -> Any:
        yield None

    async def _resolve(session: Any, engine: str, ref: str | None) -> tuple[UUID, UUID]:
        return TENANT, AGENT

    async def _upsert(*args: Any) -> UUID:
        return CALL

    async def _enqueue(job: str, payload: dict[str, Any], **kwargs: Any) -> None:
        jobs.append((job, payload))

    monkeypatch.setattr(pipeline, "untenanted_session", _no_session)
    monkeypatch.setattr(pipeline, "_resolve_agent", _resolve)
    monkeypatch.setattr(pipeline, "_upsert_call", _upsert)
    monkeypatch.setattr(pipeline, "enqueue", _enqueue)
    return jobs


async def test_terminal_owned_runtime_call_reaches_the_post_call_pipeline(
    monkeypatch: pytest.MonkeyPatch, enqueued: list[tuple[str, dict[str, Any]]]
) -> None:
    snap = _snapshot("completed")
    monkeypatch.setattr(pipeline, "get_engine", lambda: _Engine(snap))

    outcome = await pipeline._ingest_stages("pipecat", snap.engine_call_id, None, {})

    assert outcome == "pipeline_enqueued"
    assert [job for job, _ in enqueued] == [pipeline.POSTCALL_JOB]
    assert enqueued[0][1]["call_id"] == str(CALL)


async def test_live_owned_runtime_call_still_waits(
    monkeypatch: pytest.MonkeyPatch, enqueued: list[tuple[str, dict[str, Any]]]
) -> None:
    snap = _snapshot("in_progress")
    monkeypatch.setattr(pipeline, "get_engine", lambda: _Engine(snap))

    outcome = await pipeline._ingest_stages("pipecat", snap.engine_call_id, None, {})

    assert outcome == "awaiting_completion:in_progress"
    assert enqueued == []


async def test_rented_engine_still_waits_for_billable_ready(
    monkeypatch: pytest.MonkeyPatch, enqueued: list[tuple[str, dict[str, Any]]]
) -> None:
    """The vendor-hosted shape is unchanged: terminal is NOT ready there (D-31)."""
    snap = _snapshot("completed")
    engine = _Engine(snap)
    engine.capabilities = PIPECAT_CAPABILITIES.model_copy(update={"agent_hosting": "control_plane"})
    monkeypatch.setattr(pipeline, "get_engine", lambda: engine)

    outcome = await pipeline._ingest_stages("pipecat", snap.engine_call_id, None, {})

    assert outcome == "awaiting_completion:completed"
    assert enqueued == []
