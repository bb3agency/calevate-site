"""Two runs of ONE call's post-call pipeline, overlapping.

`pipeline_audit_test` proves every stage is re-runnable — SEQUENTIALLY. That is a
different claim, and the difference is where the money is: three of these stages are
check-then-write (`_meter`'s "have we metered this call", `_already_enqueued`'s "have we
promised this side effect"), and a check-then-write that is correct sequentially is
correct in every test in this repo and wrong the first time two runs overlap.

WHAT WAS MEASURED, before the lock existed. Two `_meter` calls for one call, launched
together:

    usage_events rows: 10 for a five-row call
    spend_state:       1.5833 minutes counted as 3.1666

which is a client billed twice for one call AND a spend cap that arms at half their real
usage. `usage_events` carries an append-only trigger (hard rule 4), so neither number can
be corrected by an UPDATE — the remedy is a compensating entry somebody writes by hand,
if anybody ever notices.

The defence that existed was the ARQ job id, keyed on the call. It is real and it is the
FIRST line, not the last: its window is `keep_result` (3600s), a `job_timeout = 300`
cancellation can leave a transaction in flight while its retry starts, and an operator
replay or a lost Redis removes it entirely. `lock_call_writes` makes it a database fact.

**THE CONCURRENCY HERE IS REAL, AND THIS FILE PROVES IT RATHER THAN CLAIMING IT.** The
last test removes the lock and asserts the SAME harness produces the double — a
concurrent test that never actually raced is the commonest way to be fooled, and a
negative control is the only thing that rules it out.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.workers import pipeline
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

RUN = uuid.uuid4().hex[:12]


@pytest.fixture(autouse=True)
def _stub_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_copy(*, source_url: str, tenant_id: UUID, call_id: UUID) -> str:
        return f"recordings/{tenant_id}/{call_id}.wav"

    monkeypatch.setattr(pipeline, "copy_recording", _fake_copy)


async def _staged(label: str) -> tuple[UUID, str, UUID]:
    """A tenant with one completed inbound call, ingested. The pipeline has NOT run."""
    reset_engine_cache()
    agent_ref = f"concurrent_{label}_{RUN}"
    tenant_id, _agent_id = await _seed_tenant(agent_ref)
    execution_id = f"exec_{label}_{RUN}"
    get_engine().seed_inbound_call(  # type: ignore[attr-defined]
        call_id=execution_id,
        agent_ref=agent_ref,
        from_e164=f"+9198{uuid.uuid4().int % 100000000:08d}",
        to_e164="+911140000000",
    )

    async def _swallow(job: str, *args: Any, **kwargs: Any) -> str:
        return "queued"

    real = pipeline.enqueue
    pipeline.enqueue = _swallow  # type: ignore[assignment]
    try:
        await pipeline.ingest_engine_event(
            {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
        )
    finally:
        pipeline.enqueue = real  # type: ignore[assignment]

    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :e"), {"e": execution_id}
            )
        ).scalar()
    return tenant_id, execution_id, UUID(str(call_id))


async def _subscribe_crm(tenant_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, events, active, "
                "created_at, updated_at) VALUES (:id, :tid, 'webhook', "
                "'https://crm.example.invalid/hook', ARRAY['call.completed'], true, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id},
        )


async def _ledger(tenant_id: UUID, call_id: UUID) -> dict[str, Any]:
    """What the client is billed and what their cap has been told. Counts only."""
    async with tenant_session(tenant_id) as session:
        usage = (
            await session.execute(
                text("SELECT count(*) FROM usage_events WHERE call_id = :c"), {"c": call_id}
            )
        ).scalar()
        spend = (
            await session.execute(
                text("SELECT minutes_used, spend_used FROM spend_state WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).first()
    return {
        "usage_rows": int(usage or 0),
        "minutes": spend[0] if spend else None,
        "spend": spend[1] if spend else None,
    }


async def _outbox_count(job: str, matcher: dict[str, Any]) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload @> CAST(:matcher AS jsonb)"
                    ),
                    {"job": job, "matcher": json.dumps(matcher)},
                )
            ).scalar()
            or 0
        )


async def _both(coro_factory: Any) -> list[Any]:
    """Launch two of the same unit of work on one event loop and let them interleave.

    `asyncio.gather` is what makes this a race rather than two sequential runs: each
    statement is an await, so the two coroutines advance in lockstep and BOTH reach the
    "have we done this already" read before either commits its answer. The negative
    control at the bottom of this file is the evidence that this is enough — with the
    lock removed, the same two lines produce the double.
    """
    return list(await asyncio.gather(coro_factory(), coro_factory(), return_exceptions=True))


# ================================================================== 1. the money ledger


async def test_two_overlapping_runs_meter_a_call_exactly_once() -> None:
    """Hard rule 4 + 7. `usage_events` is append-only and priced in INR: a second set of
    rows is a second charge on an invoice, and there is no UPDATE that removes it."""
    tenant_id, execution_id, call_id = await _staged("meter")
    snapshot = await get_engine().get_execution(execution_id)

    written = await _both(lambda: pipeline._meter(tenant_id, call_id, snapshot))

    assert not [r for r in written if isinstance(r, BaseException)], written
    metered, skipped = max(written), min(written)
    assert metered > 0, "neither run metered the call at all"
    assert skipped == 0, (
        f"both runs believed they were the first to meter this call: {written} — "
        "`usage_events` is append-only, so the second set of rows is a permanent "
        "double charge"
    )
    ledger = await _ledger(tenant_id, call_id)
    assert ledger["usage_rows"] == metered, (
        f"two overlapping runs left {ledger['usage_rows']} usage rows on a {metered}-row call"
    )


async def test_the_spend_cap_counts_the_call_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of the same statement, and the half that is not about the invoice.

    `spend_state` is the pre-dispatch gate (TRD §9): `compliance.check_dispatch` refuses
    every outbound call once `capped` is true. Counting one call twice arms that gate at
    half the tenant's real allowance — their campaign stops early and nothing explains
    why, because the usage panel reads the same inflated counter.
    """
    tenant_id, execution_id, call_id = await _staged("cap")
    snapshot = await get_engine().get_execution(execution_id)
    minutes = (snapshot.duration_s or 0) / 60

    await _both(lambda: pipeline._meter(tenant_id, call_id, snapshot))

    ledger = await _ledger(tenant_id, call_id)
    assert ledger["minutes"] is not None
    assert float(ledger["minutes"]) == pytest.approx(minutes, abs=0.01), (
        f"one call of {minutes:.4f} minutes was counted as {ledger['minutes']}"
    )
    assert float(ledger["spend"]) == pytest.approx(float(snapshot.cost.total_inr), abs=0.01)


# ============================================================= 2. the outbound promises


async def test_two_overlapping_pipelines_promise_each_side_effect_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole job, twice, at once — the shape an operator replay racing a poller
    re-drive actually takes.

    The CRM row is the one that cannot be cleaned up downstream: `integrations.
    enqueue_event` mints a FRESH `delivery_id` per fan-out, so two rows are two POSTs
    the client's receiver sees as two different events, not as a retry it can
    deduplicate (WEBHOOKS §1.5). The hot-lead row is the owner's phone ringing twice.

    **THE SNAPSHOT CARRIES NO COST, AND THAT IS THE WHOLE REASON THIS TEST WORKS.**
    Written with the ordinary snapshot it passed with the fan-out's lock deleted — found
    by deleting it — because `_meter` takes the same lock four stages earlier, so the two
    runs came out of metering staggered and the second reached the fan-out after the
    first had committed. A cost-less call (the engine reports none) makes `_meter` return
    before it opens a session at all, which removes the accidental serialisation and
    leaves the fan-out's own guard as the only thing between one promise and two. A
    concurrent test whose race is being run by a DIFFERENT lock is the exact way to be
    fooled that this file exists to avoid.
    """
    tenant_id, execution_id, call_id = await _staged("promises")
    await _subscribe_crm(tenant_id)

    engine = get_engine()
    real = await engine.get_execution(execution_id)
    costless = real.model_copy(update={"cost": None})

    class _CostlessEngine:
        name = "fake"

        async def get_execution(self, execution: str) -> Any:
            return costless

    monkeypatch.setattr(pipeline, "get_engine", lambda: _CostlessEngine())

    outcomes = await _both(
        lambda: pipeline.run_post_call_pipeline(
            {},
            {
                "tenant_id": str(tenant_id),
                "call_id": str(call_id),
                "engine": "fake",
                "execution_id": execution_id,
            },
        )
    )
    assert not [o for o in outcomes if isinstance(o, BaseException)], outcomes

    assert await _outbox_count("deliver_outbound_webhook", {"data": {"call_id": str(call_id)}}) == 1
    assert await _outbox_count("notify_hot_lead", {"call_id": str(call_id)}) == 1
    async with tenant_session(tenant_id) as session:
        leads = (
            await session.execute(
                text("SELECT count(*), max(call_count) FROM leads WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).first()
    assert leads is not None
    assert leads[0] == 1, "one caller is one lead, however many pipelines ran"
    assert leads[1] == 1, "and one call is one call — a re-run must not invent a repeat caller"


# ======================================== 3. the negative control: this test can go red


async def test_the_harness_catches_an_unguarded_check_then_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrency test that never actually raced is the commonest way to be fooled, so
    this one is run with the guard removed and asserted to FAIL.

    The break is not a synthetic one: `lock_call_writes` is stubbed to a no-op, which is
    exactly the code that shipped before it existed. If a future edit made the two
    coroutines run sequentially — an `await` moved, a fixture serialising the loop, a
    session pool of one — this assertion is what goes red, rather than the tests above
    silently ceasing to test anything.
    """
    tenant_id, execution_id, call_id = await _staged("control")
    snapshot = await get_engine().get_execution(execution_id)

    async def _no_lock(session: Any, call: UUID) -> None:
        return None

    monkeypatch.setattr(pipeline, "lock_call_writes", _no_lock)

    written = await _both(lambda: pipeline._meter(tenant_id, call_id, snapshot))
    ledger = await _ledger(tenant_id, call_id)

    assert written == [5, 5], (
        f"the two runs did not overlap — this file's races are not races, got {written}"
    )
    assert ledger["usage_rows"] == 10, (
        f"the unguarded pre-check did not double-meter ({ledger['usage_rows']} rows), so "
        "the tests above would pass with the lock deleted"
    )
    assert float(ledger["minutes"]) == pytest.approx(2 * (snapshot.duration_s or 0) / 60, abs=0.01)
