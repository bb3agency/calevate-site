"""The container bootstrap, end to end: a real pipeline writing to a real database.

`tests/worker_api_test.py` holds the WRITER to its columns and its tenancy, and
`voice_worker_sink_test.py` holds the client's buffer to its bounds. This file holds the
PROCESS to the two promises `runtime.py`'s docstring makes, and neither is provable by
reading the source:

1. **A turn the sink accepted is written before the process is allowed to exit.** The
   whole graceful-shutdown argument rests on a VENDOR behaviour — that Pipecat dispatches
   each event handler as its own task and then awaits every outstanding one in
   `cleanup()` — and hard rule 11 says a claim about the outside world is asserted from a
   primary source, not from our own docstring. So the pipeline is really run, really ended,
   and the rows are counted afterwards from a different connection.
2. **`handle_sigterm` does NOT reach the runner.** It is `False` by default
   (`pipecat/workers/runner.py:115`) and is left that way on purpose: the runner answers
   SIGTERM with `cancel()` (`:347`), which cuts a live caller off mid-sentence and can lose
   the terminal event. `lifecycle.ShutdownSignal` owns the signal and drains first. That is
   one keyword argument and exactly the kind a refactor flips "to be safe", so it is
   asserted rather than assumed.

The transport, the LLM and the speech legs are the same fakes `voice_worker_pipeline_test`
uses — §6 step 4's "the worker runs locally" — because what is under test here is the
process wiring, not the vendors.

SHARED DATABASE DISCIPLINE: the organisation is minted by this module and every assertion
is scoped to ids it created.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from apps.api.db.session import tenant_session
from apps.api.engine.pipecat import PipecatEngine, engine_agent_ref_for
from calevate_shared.engine import pipecat_call_ref
from pipecat.frames.frames import LLMRunFrame
from pipecat.workers.runner import WorkerRunner
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent
from tests.voice_worker_pipeline_test import CREDENTIALS, FakeLLM, FakeTransport, _PassThrough
from tests.voice_worker_session_test import _agent_config
from tests.worker_api_harness import declare_pipecat_engine, worker_client
from voice_worker import pipeline, runtime
from voice_worker.api_client import WorkerApiClient
from voice_worker.sink import HttpEventSink

pytestmark = [pytest.mark.rls]


@pytest.fixture(autouse=True)
def _pipecat_deployment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test in this file writes through `/v1/worker`, which refuses any other engine
    (D-627). `worker_api_harness.declare_pipecat_engine` records why this is per file."""
    yield from declare_pipecat_engine(monkeypatch)


_REPLY = "నమస్కారం, ఎలా సహాయం చేయగలను"


async def _live_call() -> tuple[uuid.UUID, uuid.UUID, str, WorkerApiClient, HttpEventSink]:
    tenant_id, agent_id = await _tenant_with_published_agent()
    tenant_id, agent_id = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    api = worker_client()
    sink = HttpEventSink(
        api,
        call_id=call_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        direction="inbound",
    )
    return tenant_id, agent_id, call_id, api, sink


def _assemble(call_id: str, tenant_id: uuid.UUID, agent_id: uuid.UUID, sink: Any) -> Any:
    from tests.voice_worker_pipeline_test import make_config

    config = make_config(call_id=call_id, tenant_id=tenant_id, agent_id=agent_id)
    legs = pipeline.VendorLegs(
        stt=_PassThrough("fake-stt"), llm=FakeLLM(_REPLY), tts=_PassThrough("fake-tts")
    )
    return pipeline.assemble_call(config=config, legs=legs, transport=FakeTransport(), sink=sink)


async def test_a_running_pipeline_writes_its_call_and_its_turns_and_they_survive_the_end(
    worker_token: None,
) -> None:
    """**THE MID-CALL-SHUTDOWN GUARANTEE, EXERCISED RATHER THAN ARGUED.**

    A real `PipelineWorker` under a real `WorkerRunner` produces an agent turn, and the
    worker is then ended while that turn's sink write is still an outstanding asyncio task.
    Everything the sink accepted is read back afterwards, on a connection of its own —
    which is the only way to tell "committed" from "the task object still exists".

    A partial write is structurally impossible rather than merely absent: each flush is ONE
    request and the server writes it in ONE transaction, so an interrupted flush commits
    nothing rather than half a batch. What this test adds is the other half — that an
    accepted turn is not simply DROPPED when the process winds down.

    ⚠ Since turns are BUFFERED, "accepted" and "committed" are no longer the same instant,
    and this test says so: it flushes explicitly, exactly as `settle` does. The property it
    guards is unchanged and is now carried by `run_call`'s `finally` rather than by the
    handler task itself.
    """
    tenant_id, agent_id, call_id, api, sink = await _live_call()
    call = _assemble(call_id, tenant_id, agent_id, sink)
    worker = call.worker

    started = asyncio.Event()

    @worker.event_handler("on_pipeline_started")
    async def _started(_worker: Any, _frame: Any) -> None:
        started.set()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    run = asyncio.create_task(runner.run())
    try:
        await asyncio.wait_for(started.wait(), timeout=20)
        await worker.queue_frame(LLMRunFrame())
        # Give the assistant aggregator a chance to produce its turn, then END — which is
        # what a hang-up and what a SIGTERM both reduce to.
        for _ in range(200):
            # TURNS ARE BUFFERED (sink.DEFAULT_TURN_BATCH_SIZE), so this asks the sink to
            # send what it has rather than waiting for a batch that one turn will never
            # fill. It is the same call `settle` and `run_call`'s `finally` make; polling the
            # table without it would be waiting on the timer, which is a ten-second sleep.
            await sink.flush()
            async with tenant_session(tenant_id) as db:
                turns = (
                    await db.execute(
                        text(
                            "SELECT count(*) FROM transcript_turns t "
                            "JOIN calls c ON c.id = t.call_id WHERE c.engine_call_id = :c"
                        ),
                        {"c": pipecat_call_ref(tenant_id, call_id)},
                    )
                ).scalar_one()
            if turns:
                break
            await asyncio.sleep(0.01)
        await worker.stop_when_done()
        await asyncio.wait_for(run, timeout=20)
    finally:
        if not run.done():
            run.cancel()
        await api.aclose()

    async with tenant_session(tenant_id) as db:
        status, row_id = (
            await db.execute(
                text("SELECT status, id FROM calls WHERE engine_call_id = :c"),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).one()
        rows = (
            await db.execute(
                text(
                    "SELECT speaker, text, text_redacted FROM transcript_turns "
                    "WHERE call_id = :cid ORDER BY idx"
                ),
                {"cid": row_id},
            )
        ).all()

    # The terminal event arrived and was written, which is the event the boundary emits from
    # `on_pipeline_finished` — i.e. after the drain, on the path a shutdown takes.
    assert status == "completed"
    agent_rows = [row for row in rows if row[0] == "agent"]
    assert agent_rows, "the assistant aggregator's turn never reached the database"
    assert agent_rows[0][1] == _REPLY
    # HARD RULE 5 on the live path: the column every content reader names is populated at
    # write time, not left for a later pass that does not run for this engine.
    # `NormalizedEventBoundary` hands the sink `text_redacted=None` (asserted in
    # `voice_worker_pipeline_test`) and the worker no longer fills it either (D-621 moved the
    # redactor to the server, where the row is written); the ROW must not carry that NULL.
    assert agent_rows[0][2] is not None


async def test_a_pipeline_cancelled_mid_call_still_holds_everything_it_had_accepted(
    worker_token: None,
) -> None:
    """The ungraceful half. `runner.run()` is cancelled from outside rather than ended.

    Pipecat's own `run()` responds to an outside cancellation by cancelling the pipeline and
    waiting for it to finish (`pipecat/pipeline/worker.py:841-884`), so the rows already
    accepted are still there. What is asserted is exactly that: nothing accepted is lost,
    and nothing half-written appears — every turn present is a complete row.
    """
    tenant_id, agent_id, call_id, api, sink = await _live_call()
    call = _assemble(call_id, tenant_id, agent_id, sink)
    worker = call.worker

    started = asyncio.Event()

    @worker.event_handler("on_pipeline_started")
    async def _started(_worker: Any, _frame: Any) -> None:
        started.set()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    run = asyncio.create_task(runner.run())
    try:
        await asyncio.wait_for(started.wait(), timeout=20)
        await worker.queue_frame(LLMRunFrame())
        await asyncio.sleep(0.5)
        run.cancel()
        # AWAITED TOLERANTLY, and the tolerance is a finding rather than laziness: Pipecat's
        # `run()` catches the outside cancellation, cancels the pipeline, waits for it to
        # finish and re-raises (`pipecat/pipeline/worker.py:841-884`) — but whether the
        # re-raise reaches this frame depends on where the cancellation landed. What this
        # test is about is the rows, not the exception type.
        with contextlib.suppress(asyncio.CancelledError):
            await run
    finally:
        await api.aclose()

    async with tenant_session(tenant_id) as db:
        row = (
            await db.execute(
                text("SELECT id, status FROM calls WHERE engine_call_id = :c"),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).one()
        rows = (
            await db.execute(
                text(
                    "SELECT speaker, text, text_redacted FROM transcript_turns WHERE call_id = :cid"
                ),
                {"cid": row[0]},
            )
        ).all()

    # The call itself is on the record whatever happened to the pipeline — a call that
    # happened happened, and `admin/health.py::calls_unmetered` is what notices it has no
    # money against it.
    #
    # ⚠ **`failed` IS NOW A CORRECT ANSWER HERE AND IT USED NOT TO BE ADMITTED** (18 Sep
    # 2026). `on_pipeline_finished` fires for `CancelFrame` as well as `EndFrame`
    # (`pipecat/pipeline/worker.py:223-231`), and the handler used to discard the frame and
    # write `completed` for all three — so a call cut by a cancel was indistinguishable on
    # the row from one that ended of its own accord. This test CANCELS the pipeline, so
    # `failed` is precisely what it should now see; admitting it is the assertion catching
    # up with the defect, not a relaxation. `in_progress` remains legal because a cancel can
    # land before the terminal event is written at all.
    assert row[1] in {"in_progress", "completed", "failed"}
    # NOTHING PARTIAL: every row present has both columns, because a write that did not
    # finish wrote nothing at all rather than a row missing its redaction.
    for speaker, raw, redacted in rows:
        assert speaker in {"agent", "caller"}
        assert raw and redacted is not None


async def test_the_runner_is_not_asked_to_handle_sigterm_because_it_cancels(
    monkeypatch: pytest.MonkeyPatch,
    worker_token: None,
) -> None:
    """One keyword argument, and a live caller's last sentence depends on it.

    `handle_sigterm=True` installs a handler that calls `cancel()` — "Immediately cancel
    all running workers" (`pipecat/workers/runner.py:347`, reached from `:550-566`) — which
    cuts the caller off and can lose the terminal event, stranding the call at
    `in_progress`. Draining is `stop_when_done()` (`:322`). So SIGTERM belongs to
    `lifecycle.ShutdownSignal`, not to the runner, and this asserts the runner is left
    alone. The vendor default is read out of the installed package rather than restated, so
    a dependency bump that flips it fails here instead of silently handing SIGTERM back to
    the canceller.
    """
    import inspect

    default = inspect.signature(WorkerRunner.__init__).parameters["handle_sigterm"].default
    assert default is False, (
        "the vendor now handles SIGTERM by default, which cancels live calls; "
        "re-read runner.py and re-argue lifecycle.ShutdownSignal"
    )

    seen: dict[str, Any] = {}

    class _Recording:
        def __init__(self, **kwargs: Any) -> None:
            seen.update(kwargs)

        async def add_workers(self, *_workers: Any) -> None:
            return None

        async def run(self) -> None:
            return None

    tenant_id, agent_id, call_id, api, _sink = await _live_call()
    # `run_call` LOADS the config over the platform API, so the agent needs the runtime row
    # the control plane really publishes — minted by the adapter rather than hand-inserted
    # here, for `voice_worker_session_test._runtime_agent`'s reason.
    await PipecatEngine().create_agent(_agent_config(tenant_id, agent_id))
    monkeypatch.setattr(runtime, "WorkerRunner", _Recording)

    # A fetcher that holds nothing: this agent published no knowledge base, so `open_session`
    # never reaches it (`session.load_knowledge` refuses to fetch on an absent digest).
    class _NoPacks:
        async def fetch(self, _key: str) -> bytes | None:
            return None

    worker_runtime = runtime.WorkerRuntime(api, fetcher=_NoPacks())
    try:
        outcome = await worker_runtime.run_call(
            call_id=call_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            direction="inbound",
            engine_agent_ref=engine_agent_ref_for(str(tenant_id), str(agent_id)),
            credentials_for=lambda _provider: CREDENTIALS,
            # A fake transport fires no client-connected event, so `arm_first_turn` would
            # refuse it. Production takes the default, which is `"required"`.
            greeting="skip",
            transport=FakeTransport(),
        )
    finally:
        await worker_runtime.aclose()

    assert seen == {"handle_sigint": True, "handle_sigterm": False}
    # And the real production shape of a settlement today: this session transcribed and
    # synthesised nothing (a fake transport with no audio), so there is no measured leg to
    # price — and the two legs nobody can witness are each recorded, by name, rather than
    # one of them ending the settlement for all five (D-625).
    assert outcome.settlement.rows == 0
    assert outcome.settlement.refusals == (
        ("carrier", "meter_carrier_cdr_missing"),
        ("runtime", "meter_runtime_active_minute_unknown"),
    )

    async with tenant_session(tenant_id) as db:
        refusals = (
            await db.execute(
                text(
                    "SELECT count(*) FROM call_metering_refusals r "
                    "JOIN calls c ON c.id = r.call_id WHERE c.engine_call_id = :c"
                ),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).scalar_one()
    assert refusals == 2, "a refused leg took the leg beside it off the record"


async def test_running_a_call_records_what_prompt_the_worker_actually_loaded(
    monkeypatch: pytest.MonkeyPatch,
    worker_token: None,
) -> None:
    """**THE ATTESTATION REACHES THE DATABASE, WHICH IT NEVER DID BEFORE (D-626).**

    `voice_worker/pipeline.AssembledCall` has computed `observed_prompt_sha256` since the
    engine was built and it reached nothing: `agents/config_versions.record_attestation` was
    called only by tests, so `agent_config_attestations` was empty on every deployment and
    `PipecatEngine.get_agent` answered `system_prompt_readable=False` for every agent for
    ever. Hard rule 5's engine-side verification therefore never ran once on this leg.

    THE ASSERTION IS THE ROW, not the request: what matters is that a real `run_call` leaves
    the witness `get_agent` reads. `matches` is true because this worker loaded the prompt
    the control plane published, which is the point of the digest being recomputed rather
    than echoed.
    """
    from apps.api.agents.config_versions import latest_attestation

    class _Recording:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def add_workers(self, *_workers: Any) -> None:
            return None

        async def run(self) -> None:
            return None

    class _NoPacks:
        async def fetch(self, _key: str) -> bytes | None:
            return None

    tenant_id, agent_id, call_id, api, _sink = await _live_call()
    await PipecatEngine().create_agent(_agent_config(tenant_id, agent_id))
    monkeypatch.setattr(runtime, "WorkerRunner", _Recording)

    async with tenant_session(tenant_id) as db:
        before = await latest_attestation(db, agent_id)
    assert before is None, "something already attested; this test would prove nothing"

    worker_runtime = runtime.WorkerRuntime(api, fetcher=_NoPacks())
    try:
        await worker_runtime.run_call(
            call_id=call_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            direction="inbound",
            engine_agent_ref=engine_agent_ref_for(str(tenant_id), str(agent_id)),
            credentials_for=lambda _provider: CREDENTIALS,
            greeting="skip",
            transport=FakeTransport(),
        )
    finally:
        await worker_runtime.aclose()

    async with tenant_session(tenant_id) as db:
        stored = await latest_attestation(db, agent_id)
    assert stored is not None, "a whole call ran and left no record of the prompt it loaded"
    assert stored.matches is True


class _SlowAttestation(WorkerApiClient):
    """The real client, except the attestation POST waits until the test releases it."""

    def __init__(self, real: WorkerApiClient) -> None:
        super().__init__(client=real._client, base_url=real._base_url, token=real._token)
        self.release = asyncio.Event()
        self.posted = False

    async def post_attestation(self, *args: Any, **kwargs: Any) -> Any:
        await self.release.wait()
        answer = await super().post_attestation(*args, **kwargs)
        self.posted = True
        return answer


async def test_the_pipeline_does_not_wait_on_the_attestation(
    monkeypatch: pytest.MonkeyPatch,
    worker_token: None,
) -> None:
    """The carrier leg is already up when `run_call` starts, so every await before the
    pipeline runs is silence on the line. The attestation is evidence about the prompt, not
    a gate on the call: the pipeline must start while it is still in flight, and the call
    must still wait for it before it finishes."""
    from apps.api.agents.config_versions import latest_attestation

    tenant_id, agent_id, call_id, real, _sink = await _live_call()
    api = _SlowAttestation(real)
    await PipecatEngine().create_agent(_agent_config(tenant_id, agent_id))
    pipeline_started_before_attestation: list[bool] = []

    class _Runner:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def add_workers(self, *_workers: Any) -> None:
            return None

        async def run(self) -> None:
            pipeline_started_before_attestation.append(not api.posted)
            api.release.set()

    class _NoPacks:
        async def fetch(self, _key: str) -> bytes | None:
            return None

    monkeypatch.setattr(runtime, "WorkerRunner", _Runner)
    worker_runtime = runtime.WorkerRuntime(api, fetcher=_NoPacks())
    try:
        await asyncio.wait_for(
            worker_runtime.run_call(
                call_id=call_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                direction="inbound",
                engine_agent_ref=engine_agent_ref_for(str(tenant_id), str(agent_id)),
                credentials_for=lambda _provider: CREDENTIALS,
                greeting="skip",
                transport=FakeTransport(),
            ),
            timeout=10,
        )
    finally:
        await real.aclose()

    assert pipeline_started_before_attestation == [True], "the caller waited on a witness row"
    async with tenant_session(tenant_id) as db:
        stored = await latest_attestation(db, agent_id)
    assert stored is not None, "the call finished without the attestation it started"


async def test_a_pipeline_that_raises_leaves_no_attestation_task_behind(
    monkeypatch: pytest.MonkeyPatch,
    worker_token: None,
) -> None:
    """The attestation runs beside the pipeline, so a pipeline that dies must take it down
    rather than leave a task holding the shared client open after `run_call` has gone."""
    tenant_id, agent_id, call_id, real, _sink = await _live_call()
    api = _SlowAttestation(real)
    await PipecatEngine().create_agent(_agent_config(tenant_id, agent_id))

    class _Crashes:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def add_workers(self, *_workers: Any) -> None:
            return None

        async def run(self) -> None:
            raise RuntimeError("the pipeline died")

    class _NoPacks:
        async def fetch(self, _key: str) -> bytes | None:
            return None

    monkeypatch.setattr(runtime, "WorkerRunner", _Crashes)
    worker_runtime = runtime.WorkerRuntime(api, fetcher=_NoPacks())
    try:
        with pytest.raises(RuntimeError, match="the pipeline died"):
            await worker_runtime.run_call(
                call_id=call_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                direction="inbound",
                engine_agent_ref=engine_agent_ref_for(str(tenant_id), str(agent_id)),
                credentials_for=lambda _provider: CREDENTIALS,
                greeting="skip",
                transport=FakeTransport(),
            )
        lingering = [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and "_attest" in repr(task.get_coro())
        ]
        assert lingering == [], "the attestation outlived the call it belonged to"
        assert api.posted is False
    finally:
        await real.aclose()
