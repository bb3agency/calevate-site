"""One execution's failure must not end the guarantee of record for everything behind it.

D-31 makes the poller — not webhook delivery — the thing that makes call records
trustworthy: Bolna delivers at most once with no retry, so an event lost to a deploy or a
500 is lost forever at the webhook layer and `reconcile_executions` is the only mechanism
that recovers it. Its repair loop had no per-execution `try` (R-4), so:

1. execution *k* belongs to a tenant whose probe errors — a connection reset, a pool
   timeout, an RLS/GUC problem;
2. the exception escapes the loop, so executions *k+1…n* are never examined;
3. the job raises, and the cron registered it with no `max_tries`, which `arq.cron()`
   defaults to 1 — so it is finished on its first attempt;
4. **nothing alerts.** The two existing `alert()` calls cover the listing FETCH and the
   listing's INCOMPLETENESS; an exception in the repair loop is covered by neither.

A transient fault self-heals on the next tick's overlapping window. A persistent one, on
a tenant sitting early in the vendor's ordering, means the guarantee quietly stops
guaranteeing with every screen green — the fail-towards-silence shape
`dispatcher.report_stalled_pipeline` was fixed for and carries the argument about.

Deliberately DB-free: the probe and the enqueue are both substituted, because what is
under test is the loop's failure behaviour, not what a probe concludes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import apps.workers.pipeline as pipeline_module
import pytest
from apps.workers.pipeline import reconcile_executions
from apps.workers.settings import WorkerSettings
from calevate_shared.engine import ExecutionListing, ExecutionSnapshot


class _StubEngine:
    name = "fake"

    def __init__(self, listing: ExecutionListing) -> None:
        self._listing = listing

    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        return self._listing


def _snapshot(execution_id: str) -> ExecutionSnapshot:
    """A completed, billable execution — the only kind the repair loop examines."""
    return ExecutionSnapshot(
        engine_call_id=execution_id,
        direction="outbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        ended_at=datetime.now(UTC),
        duration_s=60,
    )


@pytest.fixture
def sweep(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Run the poller over a listing whose probe fails for named execution ids."""
    alerts: list[tuple[str, str, str | None]] = []
    enqueued: list[str] = []
    repairs: list[str] = []

    def _alert(stage: str, code: str, *, detail: str | None = None, **ids: str) -> None:
        alerts.append((stage, code, detail))

    monkeypatch.setattr(pipeline_module, "alert", _alert)
    monkeypatch.setattr(
        pipeline_module, "record_reconciliation_repair", lambda *, kind: repairs.append(kind)
    )

    async def _enqueue(job: str, payload: dict[str, Any], *, job_id: str | None = None) -> None:
        enqueued.append(str(payload["execution_id"]))

    monkeypatch.setattr(pipeline_module, "enqueue", _enqueue)

    async def run(execution_ids: list[str], *, broken: set[str]) -> dict[str, Any]:
        async def _probe(engine_name: str, snapshot: ExecutionSnapshot) -> str:
            if snapshot.engine_call_id in broken:
                # The shape the real probe fails with: `_pipeline_settled` opens an
                # `untenanted_session` and then a `tenant_session`, and either can raise
                # for reasons that belong to one tenant and to nobody else.
                raise RuntimeError("this tenant's session is on fire")
            return "missing_call"

        monkeypatch.setattr(pipeline_module, "_pipeline_settled", _probe)
        listing = ExecutionListing(
            snapshots=[_snapshot(eid) for eid in execution_ids], complete=True
        )
        monkeypatch.setattr(pipeline_module, "get_engine", lambda: _StubEngine(listing))
        result = await reconcile_executions({})
        return {
            "result": result,
            "alerts": list(alerts),
            "enqueued": list(enqueued),
            "repairs": list(repairs),
        }

    return run


async def test_a_failing_execution_does_not_take_the_ones_behind_it(sweep: Any) -> None:
    """THE ONE THE FINDING IS ABOUT. The broken execution is FIRST, which is the case
    that mattered: a vendor listing is ordered by the vendor, so a persistently broken
    tenant sitting at the top used to cost the whole window."""
    emitted = await sweep(["exec_a", "exec_b", "exec_c"], broken={"exec_a"})

    assert emitted["enqueued"] == ["exec_b", "exec_c"], (
        "the two executions behind the broken one were never examined — the guarantee "
        "of record stopped at the first error"
    )
    assert emitted["repairs"] == ["missing_call", "missing_call"], (
        "a repair that was not counted is a repair the metric cannot report"
    )


async def test_the_sweep_says_out_loud_that_it_did_not_finish(sweep: Any) -> None:
    """An aborted sweep produces a SMALLER repair count, which reads exactly like a
    healthy fleet — so the count has to be published as a floor, in the job result and in
    an alert, or the alarm fails towards silence."""
    emitted = await sweep(["exec_a", "exec_b"], broken={"exec_a"})

    codes = [code for _stage, code, _detail in emitted["alerts"]]
    assert codes == ["reconciliation_probe_incomplete"], (
        "an execution the poller could not probe is the one call nothing else will ever "
        "mention, and it fired no alert"
    )
    detail = emitted["alerts"][0][2]
    assert detail is not None and "1 of 2" in detail and "floor" in detail
    assert "unreached=1" in emitted["result"], "the job result must not read as a quiet tick"


async def test_a_clean_sweep_is_silent(sweep: Any) -> None:
    """The counterweight: an alarm that fires on a healthy tick is one nobody reads on
    the night it matters."""
    emitted = await sweep(["exec_a", "exec_b"], broken=set())

    assert emitted["alerts"] == []
    assert emitted["result"] == "repaired=2", "no unreached tail on a tick that reached all of it"


def test_the_poller_cron_carries_an_explicit_max_tries() -> None:
    """Read off a real `arq.worker.Worker`, not off `WorkerSettings`.

    `cron()` defaults `max_tries` to 1 and `WorkerSettings.max_tries` does NOT reach a
    function carrying its own — so the only honest place to assert the effective value is
    the schedule a Worker actually builds. `cron:dispatch_outbox` is the negative control
    in the same breath: it passes no `max_tries` and comes back as 1 even though
    `WorkerSettings.max_tries` is 3, which is the trap this assertion exists for.
    """
    from arq.worker import Worker

    worker = Worker(
        functions=WorkerSettings.functions,
        cron_jobs=WorkerSettings.cron_jobs,
        redis_settings=WorkerSettings.redis_settings,
        max_tries=WorkerSettings.max_tries,
        burst=True,
        ctx={},
    )
    jobs = {job.name: job for job in worker.cron_jobs}
    assert jobs["cron:dispatch_outbox"].max_tries == 1
    job = jobs["cron:reconcile_executions"]
    assert job.max_tries is not None and job.max_tries > 1, (
        "the guarantee of record gave up on its first transient error — a container swap "
        "mid-sweep or one bad tick and the window is gone with nothing said"
    )
    assert job.minute == {0, 10, 20, 30, 40, 50}, "every 10 minutes, D-31's window"
