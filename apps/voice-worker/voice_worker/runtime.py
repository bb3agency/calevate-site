"""The container's entrypoint: one engine, one pack cache, one call at a time.

**WHAT THIS CLOSES.** Every other module in this package is deliberately ignorant of the
process it runs in — `config.py` takes a connection and owns no engine, `pipeline.py` takes
a transport and a sink and owns neither, `session.py` orders the three loads and owns
nothing. That ignorance is what makes each of them testable with no database, no network
and no carrier, and it has to be paid for exactly once, in the module that owns the
process. This is that module.

**THE BOOTSTRAP ORDER, AND WHY IT IS THIS ORDER.**

1. `WorkerDatabase` — built ONCE for the container, before any call. It is the shared thing
   `config.py`'s docstring asked for by name: *"one process wants ONE pool sized against
   ONE workload"*. The config read and the sink both borrow from it, so the pool's size is
   a property of the container rather than of whichever module needed a row first.
2. `PackFetcher` — likewise once, because `ObjectStorePackFetcher.from_env` raises when the
   container has no bucket and that must be a STARTUP failure somebody sees, not a call
   that answers the phone and then cannot find the client's knowledge.
3. Per call: the config read, the sink, the meter and its observer, then `start_session`.
   The sink is constructed from the four ids BEFORE the config load, which is why it takes
   ids and not a `SessionConfig` — `start_session` loads the config itself and takes the
   sink as an argument, so a sink that needed the config could not be passed to it.
4. Per call, after the pipeline has drained: settle.
5. At shutdown: dispose the pool, last.

**SHUTTING DOWN MID-CALL IS THE PART WORTH READING.** A container orchestrator stops a
process with SIGTERM, and Pipecat's runner does NOT handle that by default — `WorkerRunner`
takes `handle_sigint=True, handle_sigterm=False` (`pipecat/workers/runner.py:114-115`, read in the
installed 1.10.0 tree and recorded in `docs/evidence/pipecat-api-surface-2026-09-13.md`
§1.5). With the default, a SIGTERM to this container kills the process where it stands:
the turns already handed to the sink may be in flight as their own asyncio tasks, and the
settlement never runs at all. So `handle_sigterm=True` is passed EXPLICITLY here, which
turns a kill into the same graceful end a hang-up produces:

* the runner ends the worker, which drains the pipeline;
* `PipelineWorker.cleanup` waits on every outstanding event-handler task
  (`pipecat/utils/base_object.py:167-177`), and those tasks are exactly the sink's writes —
  so a turn the sink accepted is committed before `run()` returns, or its transaction rolls
  back whole and leaves nothing partial (`WorkerDatabase.tenant_connection` is one
  transaction per write);
* only then does `run_call` settle, and only then does `aclose` dispose the pool.

That ordering is the whole guarantee, and it is why `aclose()` is not registered as a
signal handler of its own: a pool disposed while the drain is still writing would turn a
settled row into a lost one, which is precisely the failure the graceful path exists to
avoid.

**WHAT IS NOT HERE, PLAINLY.** There is no `__main__` that dials, because dialling needs
the carrier transport (BLOCKER-1, §6 step 6) and this container has no HTTP server of its
own to receive a session on — `docs/PIPECAT-MIGRATION.md` §3 category D records that
nothing external calls us. `run_call` takes the transport as an argument for exactly the
reason `assemble_call` does, so the carrier lane wires its own entrypoint to this and
changes nothing here. **There is also no container IMAGE yet**: the root `Dockerfile` copies
`apps/api`, `apps/voice-runtime` and `apps/workers` and not this package, and building the
Pipecat Cloud image is part of step 6 rather than of this seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from calevate_shared.events import CallDirection
from loguru import logger
from pipecat.observers.service_metrics_observer import ServiceMetricsObserver
from pipecat.transports.base_transport import BaseTransport
from pipecat.workers.runner import WorkerRunner

from voice_worker.config import load_session_config
from voice_worker.db import WorkerDatabase
from voice_worker.knowledge import PackCache, PackFetcher, QueryEmbedder
from voice_worker.meter import CallMeter, CarrierCdr, RateCard, RuntimeUsage
from voice_worker.pipeline import VendorCredentials
from voice_worker.session import open_session, pack_cache
from voice_worker.sink import DatabaseEventSink, Settlement
from voice_worker.storage import ObjectStorePackFetcher


@dataclass(frozen=True, slots=True)
class CallOutcome:
    """What one call did, for the caller to log. Not a status anybody acts on.

    `settlement` is what `sink.settle` returned — settled, refused, or nothing to meter —
    and `drained` says whether the pipeline ended of its own accord rather than being cut
    off. They are separate because they fail separately: a call that was cancelled can
    still settle every leg it observed, and a call that drained cleanly can still be
    unmeterable because nobody has read the CDR.
    """

    call_id: str
    drained: bool
    settlement: Settlement


class WorkerRuntime:
    """The process. One database, one pack cache, and the wiring one call needs.

    An object rather than module-level functions over module-level globals, for
    `db.WorkerDatabase`'s reason: a test must be able to hand it a database of its own, and
    a module global connected at import time would reach whatever `DATABASE_URL` the test
    runner happened to export.

    **THE PACK CACHE IS THE ONE THING IT DOES NOT OWN**, and that is deliberate rather than
    an oversight: `session.pack_cache()` already holds the process's cache and argues at
    length why it lives there (`session.py`, `_PACK_CACHE`). Owning a second one here would
    give a container two caches and make which one a call hit depend on how it was started.
    """

    def __init__(
        self,
        database: WorkerDatabase,
        *,
        fetcher: PackFetcher,
        rates: RateCard | None = None,
        cache: PackCache | None = None,
        embedder: QueryEmbedder | None = None,
    ) -> None:
        self._db = database
        self._fetcher = fetcher
        self._rates = rates
        self._cache = cache if cache is not None else pack_cache()
        self._embedder = embedder

    @classmethod
    def from_env(cls, *, rates: RateCard | None = None) -> WorkerRuntime:
        """The production constructor. Both halves raise on a misconfigured container.

        ⚠ **`rates` STAYS AN ARGUMENT AND HAS NO ENV FORM**, which is hard rule 7 showing
        through the bootstrap. A rate card is attested prices, and the ops console is where
        an operator attests them (`meter.RateCardMissingError`'s remediation); a container
        that read one out of its own environment would be a container that can invent a
        price. `None` is therefore a legitimate deployment — the worker meters QUANTITIES
        and refuses every leg at settlement, loudly and on the record, which is the correct
        behaviour for a worker nobody has priced.
        """
        return cls(
            WorkerDatabase.from_env(),
            fetcher=ObjectStorePackFetcher.from_env(),
            rates=rates,
        )

    async def run_call(
        self,
        *,
        call_id: str,
        tenant_id: UUID,
        agent_id: UUID,
        direction: CallDirection,
        credentials: VendorCredentials,
        transport: BaseTransport,
        carrier: CarrierCdr | None = None,
        runtime_usage: RuntimeUsage | None = None,
    ) -> CallOutcome:
        """One call, from ids to a settled (or refused) ledger. The whole process path.

        **THE SINK IS BUILT FIRST AND THE CONFIG SECOND**, which is the order `start_session`
        requires: it takes the sink as an argument and loads the config itself. The four ids
        the sink needs are the four ids this method was called with, so nothing has to be
        read from the database to construct it.

        **THE METER IS ATTACHED BEFORE THE PIPELINE EXISTS AND READ AFTER IT HAS DRAINED.**
        `CallMeter.attach` is explicit that usage reports arrive as their own asyncio tasks
        and that a meter read from inside a teardown loses whatever was still in flight — so
        `metered_rows` is reached only after `runner.run()` has returned, which is after
        Pipecat has awaited every one of those tasks.

        `carrier` and `runtime_usage` are arguments and not something this method goes and
        fetches. §1.2 gives the connected minute and its charge to the CARRIER, whose CDR is
        not retrievable from this container, and §7 P-1 leaves what a Pipecat "active
        minute" bills UNANSWERED; both are things a human or a reconciliation supplies.
        ⚠ Today both are `None` on every production call, so every call settles as a
        RECORDED REFUSAL rather than as rupees. That is not a defect to code around — it is
        what an unwitnessed billable fact looks like when nothing is allowed to invent one.
        """
        sink = DatabaseEventSink(
            self._db,
            call_id=call_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            direction=direction,
        )
        meter = CallMeter(rates=self._rates)
        observer = ServiceMetricsObserver()
        meter.attach(observer)

        async with self._db.tenant_connection(tenant_id) as connection:
            config = await load_session_config(
                connection,
                call_id=call_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                direction=direction,
            )
        call = await open_session(
            config=config,
            credentials=credentials,
            transport=transport,
            sink=sink,
            fetcher=self._fetcher,
            cache=self._cache,
            embedder=self._embedder,
            observers=[observer],
        )

        runner = WorkerRunner(
            # SIGINT is a developer at a terminal; SIGTERM is the orchestrator stopping this
            # container, and it is the one that is OFF by default. See the module docstring.
            handle_sigint=True,
            handle_sigterm=True,
        )
        await runner.add_workers(call.worker)
        await runner.run()

        drained = call.worker.has_finished()
        settlement = await sink.settle(
            meter,
            carrier=carrier,
            runtime=runtime_usage,
            at=datetime.now(UTC),
        )
        logger.info(
            "call finished",
            call_id=call_id,
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
            drained=drained,
            settled_rows=settlement.rows,
            refusal_code=settlement.refusal_code,
            # Whether this settlement PROMISED the post-call pipeline (D-603). `False` on a
            # re-settlement is correct and expected; `False` on a container's only
            # settlement of a call is the line an operator needs, because it means the
            # extraction, the CRM columns and the lead for that call are with somebody
            # else's promise or with nobody's.
            post_call_enqueued=settlement.post_call_enqueued,
        )
        return CallOutcome(call_id=call_id, drained=drained, settlement=settlement)

    async def aclose(self) -> None:
        """Release the pool. LAST, after every call this container ran has settled."""
        await self._db.aclose()


__all__ = ["CallOutcome", "WorkerRuntime"]
