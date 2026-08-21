"""Ordering audit of the ingest path: webhook receiver → inbox → ARQ → pipeline.

Three defects, one shape. Each is a step recorded BEFORE the thing it stands for was
made durable, so a failure in between leaves a claim behind with no work under it:

1. the voice-runtime's Redis fast-path key, written before the inbox claim committed —
   a rolled-back transaction left an hour-long key answering every retry `duplicate`
   with no inbox row and no job;
2. `ingest_engine_event` closing the inbox row (`processed`) before the post-call job
   was queued — a crash in between left the webhook permanently deduped and the
   pipeline unqueued;
3. the same function re-raising a plain exception to ask for a retry. arq 0.28 retries
   only for `Retry`, `RetryJob` or `CancelledError`; anything else sets `finish=True`
   and the job leaves the queue after ONE attempt.

**Attempt counts come from a real worker, never from an injected `job_try`.** A test
that writes `ctx["job_try"]` itself can only confirm that an `if` compares two integers
correctly — it cannot notice that the branch is unreachable, which is precisely how (3)
survived a review round. `_run_to_exhaustion` below runs the REAL job function on a REAL
`arq.Worker` and counts the attempts arq actually made.

Scope discipline: other suites hammer the same Postgres and Redis. Every id, queue name
and event key here carries `RUN`, and nothing counts a whole table.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from uuid import UUID

import pytest
import webhook_routes
from apps.api.core.errors import ProblemError
from apps.api.core.queue import WORKER_MAX_TRIES, redis_settings
from apps.api.db.base import uuid7
from apps.api.db.session import untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.reliability.service import body_hash, claim_inbox_event
from apps.workers import pipeline
from calevate_shared.engine import ExecutionSnapshot
from httpx import ASGITransport, AsyncClient
from main import app as voice_app  # apps/voice-runtime is on the pytest path (D-18)
from sqlalchemy import text
from tests.platform_support import requires_posix_signals
from tests.smoke_pipeline_test import _seed_tenant

RUN = uuid.uuid4().hex[:12]
HOOK = "/hooks/v1/engine/fake"
PROVIDER = f"ingestorder-{RUN}"


@pytest.fixture(autouse=True)
def _fast_ladder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real backoff is 30s and 120s; the ladder's SHAPE is what is under test, not its
    pace. `alert` is silenced because the terminal branch fires it by design and this
    file is not asserting on the log."""
    monkeypatch.setattr(pipeline, "RETRY_BACKOFF_S", (0.02, 0.02))
    monkeypatch.setattr(pipeline, "alert", lambda *a, **k: None)


@pytest.fixture(scope="module", autouse=True)
async def _clean_up_after_ourselves() -> Any:
    yield
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM webhook_inbox_events WHERE provider = :p"), {"p": PROVIDER}
        )


# --------------------------------------------------------------------- harness


async def _run_to_exhaustion(func: Any, payload: Any) -> int:
    """Run ONE job on a REAL arq worker until it stops being retried; return the number
    of attempts the worker actually made.

    Nothing here is simulated: `ctx["job_try"]` is written by arq and the retry decision
    is arq's. Burst mode drains what is ready and returns, so a deferred retry needs
    another pass — the loop is the scheduler.
    """
    from arq import create_pool
    from arq.worker import Worker

    # A queue and a job id unique per CALL: two tests running the same job on the same
    # queue would collide on arq's job-id dedupe, and the second would silently enqueue
    # nothing — which reads exactly like "the job was never retried".
    run_id = uuid7().hex
    queue_name = f"ingestorder:{RUN}:{run_id}"
    attempts = 0
    real = func

    async def counting(ctx: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        return await real(ctx, *args, **kwargs)

    # arq registers a function under its __qualname__, and a closure's qualname is
    # `_run_to_exhaustion.<locals>.counting` — enqueueing under the real name would miss.
    counting.__name__ = func.__name__
    counting.__qualname__ = func.__name__
    settings = redis_settings()
    worker = Worker(
        functions=[counting],
        redis_settings=settings,
        queue_name=queue_name,
        max_tries=WORKER_MAX_TRIES,
        burst=True,
        poll_delay=0.02,
        keep_result=1,
        retry_jobs=True,
        handle_signals=False,
    )
    pool = await create_pool(settings, default_queue_name=queue_name)
    enqueued = await pool.enqueue_job(func.__name__, payload, _job_id=run_id)
    assert enqueued is not None, "the harness must actually enqueue the job it measures"
    try:
        stagnant = 0
        seen = 0
        for _ in range(WORKER_MAX_TRIES * 4):
            await worker.main()
            if attempts >= WORKER_MAX_TRIES:
                break
            if attempts == seen:
                # A job that is NOT being retried leaves the queue immediately; waiting
                # for a ladder that does not exist is how this harness would hang.
                stagnant += 1
                if attempts and stagnant >= 2:
                    break
            else:
                stagnant, seen = 0, attempts
            await asyncio.sleep(0.05)
    finally:
        await worker.close()
        await pool.aclose()
    return attempts


async def _seed_inbox(event_key: str) -> UUID:
    """An inbox row in `processing`, exactly as the receiver leaves it for the worker."""
    async with untenanted_session() as session:
        claim = await claim_inbox_event(
            session,
            provider=PROVIDER,
            event_key=event_key,
            payload_hash=body_hash({"event_key": event_key}),
            event_name="completed",
        )
    assert claim.state == "claimed"
    return claim.row_id


async def _inbox_status(row_id: UUID) -> str | None:
    async with untenanted_session() as session:
        return (
            await session.execute(
                text("SELECT status FROM webhook_inbox_events WHERE id = :id"), {"id": row_id}
            )
        ).scalar()


async def _staged_call(label: str) -> tuple[UUID, str, str]:
    """A provisioned tenant whose engine holds one completed inbound call.

    Returns (tenant_id, agent_ref, execution_id). Nothing has been ingested yet.
    """
    reset_engine_cache()
    agent_ref = f"fakeagent_{label}_{RUN}"
    tenant_id, _agent_id = await _seed_tenant(agent_ref)
    execution_id = f"exec_{label}_{RUN}"
    get_engine().seed_inbound_call(  # type: ignore[attr-defined]
        call_id=execution_id,
        agent_ref=agent_ref,
        from_e164=f"+9198{uuid.uuid4().int % 100000000:08d}",
        to_e164="+911140000000",
    )
    return tenant_id, agent_ref, execution_id


class _RefusingEngine:
    """An engine whose authenticated read always fails the same way."""

    name = "fake"

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        raise self._exc


# --- 1. the fast path must not outlive the transaction it stands for ----------


async def test_a_failed_claim_does_not_leave_a_key_that_swallows_the_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Redis SETNX was taken BEFORE the durable claim committed.

    Redis being down degrades correctly — that path was already covered. The hole is the
    other direction: if the claim or the enqueue then fails, the transaction rolls back
    and the key survives for its full hour, so every retry of that event is answered
    `duplicate` with no inbox row and no job behind it. Bolna delivers at most once, so
    the 10-minute reconciliation poller becomes the only recovery for an event we already
    told the vendor we had accepted.

    Here the first delivery's enqueue fails; the second, identical delivery must still be
    ACCEPTED and must leave a real inbox row and a real job.
    """
    execution_id = f"exec_fastpath_{RUN}"
    raw_status = f"completed-{RUN}"
    body = {"execution_id": execution_id, "status": raw_status, "agent_id": f"agent_{RUN}"}

    seen = 0
    real_enqueue = webhook_routes.enqueue

    async def _flaky(job: str, *args: Any, **kwargs: Any) -> str | None:
        nonlocal seen
        seen += 1
        if seen == 1:
            raise RuntimeError("redis refused the ingest job")
        return await real_enqueue(job, *args, **kwargs)

    monkeypatch.setattr(webhook_routes, "enqueue", _flaky)

    transport = ASGITransport(app=voice_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://runtime") as http:
        first = await http.post(HOOK, json=body)
        assert first.status_code >= 500, "the premise: this delivery did NOT get processed"
        second = await http.post(HOOK, json=body)

    assert second.status_code == 202, second.text
    assert second.json()["status"] == "accepted", (
        "a delivery whose claim never committed must be retryable; the fast-path key "
        "outlived the transaction and swallowed it"
    )

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status FROM webhook_inbox_events WHERE provider = 'fake' "
                    "AND event_key = :k"
                ),
                {"k": f"{execution_id}:{raw_status}"},
            )
        ).first()
    assert row is not None, "the accepted retry must leave the durable inbox row behind"
    assert row[0] == "enqueued", "and the job it stands for must actually have been queued"
    assert seen == 2, "the second delivery reached the queue rather than being deduped away"


async def test_a_settled_delivery_is_still_absorbed_before_postgres() -> None:
    """The other half, so the fix above cannot over-correct into "no fast path at all".

    A repeat of a delivery that DID settle must still be answered from Redis, and it must
    not write a second forensic row.
    """
    execution_id = f"exec_absorb_{RUN}"
    raw_status = f"completed-absorb-{RUN}"
    body = {"execution_id": execution_id, "status": raw_status}

    transport = ASGITransport(app=voice_app)
    async with AsyncClient(transport=transport, base_url="http://runtime") as http:
        first = await http.post(HOOK, json=body)
        second = await http.post(HOOK, json=body)

    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "duplicate", "the fast path must still absorb a repeat"

    async with untenanted_session() as session:
        deliveries = (
            await session.execute(
                text(
                    "SELECT count(*) FROM webhook_deliveries WHERE source = 'fake' "
                    "AND event_type = :e AND direction = 'in'"
                ),
                {"e": raw_status},
            )
        ).scalar()
    assert deliveries == 1, "a duplicate must not inflate the forensic trail"


# --- 2. the inbox row is closed LAST ------------------------------------------


@requires_posix_signals
async def test_the_inbox_row_is_not_closed_before_the_pipeline_is_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`processed` is what makes a webhook permanently deduped, so writing it before the
    post-call job is queued is backwards: a crash in between leaves the event deduped
    forever and the pipeline never queued. The poller bounds the damage; the ordering is
    still wrong, and a `processed` row is one nothing will ever re-claim.

    The enqueue is made to fail. Whatever else happens, the row must not read `processed`
    — and it must be re-claimable, which is the property the whole inbox rests on.
    """
    tenant_id, agent_ref, execution_id = await _staged_call("order")
    event_key = f"{execution_id}:completed"
    row_id = await _seed_inbox(event_key)

    async def _boom(job: str, *args: Any, **kwargs: Any) -> str | None:
        raise RuntimeError("redis refused the post-call job")

    monkeypatch.setattr(pipeline, "enqueue", _boom)

    await _run_to_exhaustion(
        pipeline.ingest_engine_event,
        {
            "engine": "fake",
            "execution_id": execution_id,
            "engine_agent_ref": agent_ref,
            "inbox_row_id": str(row_id),
        },
    )

    status = await _inbox_status(row_id)
    assert status != "processed", (
        "the event was marked handled while the pipeline job it owed never reached the "
        "queue — nothing will ever re-drive it from the webhook"
    )
    assert status == "failed", "a job that could not finish records its own defeat"

    # The point of `failed`: `claim_inbox_event` re-claims it by CAS, so a replay or the
    # poller can still drive this event to completion.
    async with untenanted_session() as session:
        again = await claim_inbox_event(
            session,
            provider=PROVIDER,
            event_key=event_key,
            payload_hash=body_hash({"event_key": event_key}),
            event_name="completed",
        )
    assert again.state == "claimed", "an unfinished event must stay re-claimable"

    # And nothing partial leaked: the call row is upserted before the enqueue, which is
    # deliberate (the dashboard's live tile), but no lead may exist without a pipeline.
    from apps.api.db.session import tenant_session

    async with tenant_session(tenant_id) as session:
        leads = (
            await session.execute(
                text("SELECT count(*) FROM leads WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
    assert leads == 0, "the pipeline never ran, so there is no lead"


async def test_a_completed_event_still_closes_its_inbox_row() -> None:
    """HOLDS, and guards the reordering from the obvious over-correction: on the happy
    path the row must still end up `processed`, not left open for the lease to reap."""
    _tenant_id, agent_ref, execution_id = await _staged_call("happy")
    row_id = await _seed_inbox(f"{execution_id}:completed")

    result = await pipeline.ingest_engine_event(
        {},
        {
            "engine": "fake",
            "execution_id": execution_id,
            "engine_agent_ref": agent_ref,
            "inbox_row_id": str(row_id),
        },
    )

    assert result == "pipeline_enqueued"
    assert await _inbox_status(row_id) == "processed"


# --- 3. the retry ladder is real, and it is not offered to everything ---------


@requires_posix_signals
async def test_an_unreachable_engine_is_retried_by_a_real_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ingest job re-raised whatever the fetch threw, expecting the ladder that
    `WorkerSettings.max_tries = 3` promises. arq 0.28 gives that ladder only to
    `arq.Retry` — anything else finishes the job on its FIRST attempt.

    A transport failure is the case that costs a call: the engine was never asked, the
    webhook is at-most-once, and without a retry the event waits for the 10-minute
    poller. This runs a real worker and counts the attempts arq actually made.
    """
    row_id = await _seed_inbox(f"transient:{RUN}")
    unreachable = ProblemError(
        kind="dependency",
        code="engine_unreachable",
        title="Voice engine unreachable",
        detail="The voice platform did not respond.",
    )
    monkeypatch.setattr(pipeline, "get_engine", lambda: _RefusingEngine(unreachable))

    attempts = await _run_to_exhaustion(
        pipeline.ingest_engine_event,
        {"engine": "fake", "execution_id": f"exec_transient_{RUN}", "inbox_row_id": str(row_id)},
    )

    assert attempts == WORKER_MAX_TRIES, (
        f"an engine that never answered must get the ladder; the worker ran it {attempts} time(s)"
    )
    assert await _inbox_status(row_id) == "failed", "and every attempt records its own defeat"


@requires_posix_signals
async def test_an_execution_the_engine_never_heard_of_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of a retry policy: knowing what NOT to retry.

    `engine_rejected` is the engine ANSWERING — for a re-fetch, overwhelmingly a 404 for
    an execution id it does not hold (a replayed webhook, an id from another account).
    The same GET will fail identically thirty seconds and two minutes later, so the
    ladder buys nothing but a later alert and three times the load on a platform that is
    already saying no.
    """
    row_id = await _seed_inbox(f"permanent:{RUN}")
    rejected = ProblemError(
        kind="dependency",
        code="engine_rejected",
        title="Voice engine rejected the request",
        detail="The voice platform could not complete this operation.",
    )
    monkeypatch.setattr(pipeline, "get_engine", lambda: _RefusingEngine(rejected))

    attempts = await _run_to_exhaustion(
        pipeline.ingest_engine_event,
        {"engine": "fake", "execution_id": f"exec_permanent_{RUN}", "inbox_row_id": str(row_id)},
    )

    assert attempts == 1, f"a rejection is not a blip; it was attempted {attempts} times"
    assert await _inbox_status(row_id) == "failed"
