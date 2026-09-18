"""The container's entrypoint: one API client, one pack cache, one call at a time.

**WHAT THIS CLOSES.** Every other module in this package is deliberately ignorant of the
process it runs in — `config.py` takes an API client and owns none, `pipeline.py` takes a
transport and a sink and owns neither, `session.py` orders the three loads and owns nothing.
That ignorance is what makes each of them testable with no network and no carrier, and it
has to be paid for exactly once, in the module that owns the process. This is that module.

**THE BOOTSTRAP ORDER, AND WHY IT IS THIS ORDER.**

1. `WorkerApiClient` — built ONCE for the container, before any call. It is the shared
   thing `config.py`'s docstring asked for by name: *"one process wants ONE pool sized
   against ONE workload"*, with `httpx` where `sqlalchemy` used to be (D-621: this container
   cannot reach our Postgres at all, §12.5 gate 6). The config read and the sink both borrow
   from it, so the connection pool is a property of the container rather than of whichever
   module needed a row first.
2. `PackFetcher` — likewise once, because `ObjectStorePackFetcher.from_env` raises when the
   container has no bucket and that must be a STARTUP failure somebody sees, not a call
   that answers the phone and then cannot find the client's knowledge.
3. Per call: the config read, the sink, the meter and its observer, then `start_session`.
   The sink is constructed from the four ids BEFORE the config load, which is why it takes
   ids and not a `SessionConfig` — `start_session` loads the config itself and takes the
   sink as an argument, so a sink that needed the config could not be passed to it.
4. Per call, after the pipeline has drained: settle.
5. At shutdown: close the client, last.

**SHUTTING DOWN MID-CALL IS THE PART WORTH READING.** A container orchestrator stops a
process with SIGTERM, and Pipecat's runner does NOT handle that by default — `WorkerRunner`
takes `handle_sigint=True, handle_sigterm=False` (`pipecat/workers/runner.py:114-115`, read in the
installed 1.10.0 tree and recorded in `docs/evidence/pipecat-api-surface-2026-09-13.md`
§1.5). With the default, a SIGTERM to this container kills the process where it stands:
the turns already handed to the sink may be in flight as their own asyncio tasks, and the
settlement never runs at all.

⚠ **`handle_sigterm=True` DOES NOT FIX THAT, AND THIS DOCSTRING USED TO SAY IT DID.** The
runner's SIGTERM handler is `_sig_handler` -> `_sig_cancel` -> `cancel()`, whose own
docstring reads "Immediately cancel all running workers" (`pipecat/workers/runner.py:347`,
reached from `:550-566`). It does not drain: it cuts the caller off mid-sentence, leaves
the carrier leg up, and may lose the terminal event — which strands the call at
`in_progress` and the post-call pipeline waits on it for ever. The method that drains is
the OTHER one, `stop_when_done()` (`:322`, "stop when their current processing is
complete"). So the runner is built with `handle_sigterm=False` and
`lifecycle.ShutdownSignal` owns the signal, draining first and settling after:

* the drain ends the worker by letting the pipeline finish;
* `PipelineWorker.cleanup` waits on every outstanding event-handler task
  (`pipecat/utils/base_object.py:167-177`), and those tasks are exactly the sink's handlers;
* only then does `run_call` settle, and only then does `aclose` close the client.

⚠ **THE SECOND BULLET USED TO END "so a turn the sink accepted is committed before `run()`
returns", AND BUFFERING MADE THAT FALSE (16 Sep 2026).** A turn the sink accepts is now
held in memory until a flush, so what `cleanup` waits on is the handler that BUFFERED it,
not a transaction. The guarantee did not weaken, it MOVED, and the ordering above is still
what carries it: `sink.settle` flushes before it measures anything, and `run_call` settles
after the drain — so every accepted turn is committed before the process is allowed to
finish, and a flush that fails leaves the turns pending rather than dropping them. Between
flushes the bound is the timer (`DEFAULT_TURN_FLUSH_SECONDS`), which is why that second
bound exists at all. The `finally` below is what makes this true on the paths that never
reach `settle`.

That ordering is the whole guarantee, and it is why `aclose()` is not registered as a
signal handler of its own: a client closed while the drain is still posting would turn a
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

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from calevate_shared.events import CallDirection
from calevate_shared.worker_api import AttestationIn
from loguru import logger
from pipecat.observers.service_metrics_observer import ServiceMetricsObserver
from pipecat.transports.base_transport import BaseTransport
from pipecat.workers.runner import WorkerRunner

from voice_worker.api_client import WorkerApiClient, WorkerApiError
from voice_worker.carrier import arm_first_turn
from voice_worker.config import load_session_config
from voice_worker.knowledge import PackCache, PackFetcher, QueryEmbedder
from voice_worker.meter import CallMeter, CarrierCdr, RateCard, RuntimeUsage
from voice_worker.pipeline import SessionConfig, VendorCredentials
from voice_worker.session import AssembledCall, open_session, pack_cache
from voice_worker.sink import (
    DEFAULT_TURN_BATCH_SIZE,
    DEFAULT_TURN_FLUSH_SECONDS,
    HttpEventSink,
    Settlement,
)
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
    """The process. One API client, one pack cache, and the wiring one call needs.

    An object rather than module-level functions over module-level globals: a test must be
    able to hand it a client of its own, and a module global built at import time would
    reach whatever `PIPECAT_WORKER_API_BASE_URL` the test runner happened to export.

    **THE PACK CACHE IS THE ONE THING IT DOES NOT OWN**, and that is deliberate rather than
    an oversight: `session.pack_cache()` already holds the process's cache and argues at
    length why it lives there (`session.py`, `_PACK_CACHE`). Owning a second one here would
    give a container two caches and make which one a call hit depend on how it was started.
    """

    def __init__(
        self,
        api: WorkerApiClient,
        *,
        fetcher: PackFetcher,
        rates: RateCard | None = None,
        cache: PackCache | None = None,
        embedder: QueryEmbedder | None = None,
        turn_batch_size: int = DEFAULT_TURN_BATCH_SIZE,
        turn_flush_seconds: float = DEFAULT_TURN_FLUSH_SECONDS,
    ) -> None:
        self._api = api
        self._fetcher = fetcher
        self._rates = rates
        self._cache = cache if cache is not None else pack_cache()
        self._embedder = embedder
        #: Passed to every per-call sink. Defaulted here rather than required, so a test
        #: that only cares about the pipeline does not have to know the buffer exists.
        self._turn_batch_size = turn_batch_size
        self._turn_flush_seconds = turn_flush_seconds

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

        ⚠ **AND SINCE D-621 THE PRICE NEVER LEAVES THIS PROCESS EVEN WHEN A CARD IS
        INSTALLED.** `sink.settle` sends `MeteredQuantity` — leg, unit type, quantity — and
        `apps/api/worker/service._price` multiplies, because the rate that reaches
        `unit_cost_paid` must be one an operator attested to US rather than one a container
        on a vendor's infrastructure computed. The argument survives for the measurement it
        still gates and for the refusals it still raises.
        """
        # THE TWO BUFFER BOUNDS COME THROUGH `boot`'s PARSERS, not through a second reading
        # of the same variables here. `load_worker_config` is the authority on this
        # container's environment (DEPLOYMENT §12.2) and it is what REFUSES a nonsensical
        # value; a `os.environ.get` in this method would be a second, weaker parse that
        # could disagree with the one `--preflight` proved.
        # IMPORTED HERE, NOT AT MODULE SCOPE, AND THE CYCLE IS THE REASON RATHER THAN A
        # STYLE CHOICE: `boot` holds this class as the process's one call runner, so a
        # top-level import back into `boot` makes the two modules uninitialisable. This is
        # the only direction the dependency actually runs at runtime — a bootstrap needs
        # the environment parser, nothing in the call path does.
        from voice_worker.boot import load_worker_config, turn_buffer_bounds

        batch, flush = turn_buffer_bounds()
        config = load_worker_config()
        return cls(
            WorkerApiClient.from_config(
                base_url=config.pipecat_worker_api_base_url,
                token=config.pipecat_worker_api_token,
            ),
            fetcher=ObjectStorePackFetcher.from_env(),
            rates=rates,
            turn_batch_size=batch,
            turn_flush_seconds=flush,
        )

    async def run_call(
        self,
        *,
        call_id: str,
        tenant_id: UUID,
        agent_id: UUID,
        direction: CallDirection,
        engine_agent_ref: str,
        credentials_for: Callable[[str | None], VendorCredentials],
        transport: BaseTransport,
        carrier: CarrierCdr | None = None,
        runtime_usage: RuntimeUsage | None = None,
        greeting: Literal["required", "skip"] = "required",
        on_assembled: Callable[[AssembledCall], None] | None = None,
    ) -> CallOutcome:
        """One call, from ids to a settled (or refused) ledger. The whole process path.

        **THE SINK IS BUILT FIRST AND THE CONFIG SECOND**, which is the order `start_session`
        requires: it takes the sink as an argument and loads the config itself. The four ids
        the sink needs are the four ids this method was called with, so nothing has to be
        read from the database to construct it.

        **`credentials_for` IS A FUNCTION AND NOT A VALUE, AND THAT IS WHAT LET THE SECOND
        CALL PATH EXIST.** Which vendor key this call spends is decided by the agent's own
        `ModelConfig.llm_provider`, which lives in the config version and nowhere else — so
        the choice cannot be made before the read that happens inside this method. Taking a
        finished `VendorCredentials` forced a caller that wanted the right key to do its own
        read, its own `open_session`, and eventually its own everything; that caller was
        `bot.py`, and it drifted until it no longer settled a call. A resolver keeps the
        decision here, where the provider is known.

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

        **`greeting` DEFAULTS TO `"required"` AND THAT DEFAULT IS THE POINT.** Arming the
        first turn used to live in `bot.py`, beside a second, partial copy of this method —
        and the copy was the one the container ran, which is how it came to ship with no
        meter, no settlement and no `aclose` (audited 18 Sep 2026). With one path, a caller
        that forgets to arm the greeting would get a connected call and silence, so the
        SAFE thing is what you get for saying nothing; `"skip"` is for a fake transport,
        which fires no connect event and would otherwise be refused by `arm_first_turn`.
        """
        sink = HttpEventSink(
            self._api,
            call_id=call_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            direction=direction,
            turn_batch_size=self._turn_batch_size,
            turn_flush_seconds=self._turn_flush_seconds,
        )
        meter = CallMeter(rates=self._rates)
        observer = ServiceMetricsObserver()
        meter.attach(observer)

        config = await load_session_config(
            self._api,
            call_id=call_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            direction=direction,
            engine_agent_ref=engine_agent_ref,
        )
        call = await open_session(
            config=config,
            credentials=credentials_for(config.models.llm_provider),
            transport=transport,
            sink=sink,
            fetcher=self._fetcher,
            cache=self._cache,
            embedder=self._embedder,
            observers=[observer],
        )

        # §1.1's ATTESTATION, POSTED AT SESSION START (D-626). `AssembledCall` has recomputed
        # the digest of the prompt in this process's memory; until now it reached nothing, so
        # `agent_config_attestations` had no production writer, `PipecatEngine.get_agent`
        # answered `system_prompt_readable=False` for every agent for ever, and hard rule 5's
        # engine-side verification never ran on this leg.
        #
        # WHAT IS SENT IS THE DIGEST AND NOT `prompt_matches_config_version`. The verdict is
        # the SERVER's — an attestation whose verdict came from the attesting process agrees
        # with itself by construction, which is the whole defect `config_versions.py` exists
        # to close. The local flag stays for this log line and nothing else.
        await self._attest(engine_agent_ref, config, call)

        if on_assembled is not None:
            # THE CONTAINER LEARNS ABOUT THE CALL THE MOMENT IT EXISTS, so a SIGTERM
            # arriving one instant later drains it gracefully instead of cutting a caller
            # off. The registry reserved this call's slot before any IO (`bot.py`); this is
            # the second half of that two-step, and it is a callback rather than a registry
            # argument so that this module keeps knowing nothing about readiness files.
            on_assembled(call)

        if greeting == "required":
            # AFTER `open_session`, because it needs the assembled call, and BEFORE the
            # runner, because the connect event can fire as soon as the pipeline runs.
            # `arm_first_turn` REFUSES a transport that fires no connect event rather than
            # registering into the void — on this path that refusal is the difference
            # between a loud boot failure and every caller hearing a click and nothing.
            arm_first_turn(transport, call, call_id=call_id)

        runner = WorkerRunner(
            # SIGINT is a developer at a terminal. SIGTERM is the orchestrator stopping this
            # container and is deliberately NOT handed to the runner: its handler cancels
            # rather than drains (`runner.py:347`), which cuts a live caller off and can lose
            # the terminal event. `lifecycle.ShutdownSignal` owns SIGTERM and drains first.
            handle_sigint=True,
            handle_sigterm=False,
        )
        await runner.add_workers(call.worker)
        # `try/finally` RATHER THAN A PLAIN SEQUENCE, and only since turns are buffered.
        # `settle` flushes, so the happy path never needed this; what needs it is every path
        # that does NOT reach `settle` — the pipeline raising, the task being cancelled — on
        # which the buffered turns would otherwise be dropped by a process that is about to
        # exit. `aclose` stops the timer and writes what is left, and it is idempotent, so
        # the ordinary path pays only a second no-op flush.
        try:
            await runner.run()

            drained = call.worker.has_finished()
            settlement = await sink.settle(meter, carrier=carrier, runtime=runtime_usage)
        finally:
            await sink.aclose()
        logger.info(
            "call finished",
            call_id=call_id,
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
            drained=drained,
            settled_rows=settlement.rows,
            # EVERY LEG NOBODY COULD PRICE, NOT THE FIRST (D-625). A call now settles the
            # legs it measured and records a refusal beside them for the legs it could not,
            # so this is a list and an empty one is a fully metered call.
            refusal_codes=",".join(code for _, code in settlement.refusals),
            # Whether this settlement PROMISED the post-call pipeline (D-607). `False` on a
            # re-settlement is correct and expected; `False` on a container's only
            # settlement of a call is the line an operator needs, because it means the
            # extraction, the CRM columns and the lead for that call are with somebody
            # else's promise or with nobody's.
            post_call_enqueued=settlement.post_call_enqueued,
        )
        return CallOutcome(call_id=call_id, drained=drained, settlement=settlement)

    async def _attest(
        self, engine_agent_ref: str, config: SessionConfig, call: AssembledCall
    ) -> None:
        """Report what this process loaded, and NEVER fail the call over it.

        **A DEGRADATION AND NOT A REFUSAL, WHICH IS THE OPPOSITE OF THE SESSION READ.** That
        read decides whether a model gets a system prompt at all, so it refuses
        (`api_client.WorkerApiClient.session`). This one records EVIDENCE about a prompt the
        process already holds and has already checked: `config.refuse_unless_disclosed` has
        run, so hard rule 5's sentence is in the text either way. Dropping a live caller
        because the witness table could not be written would trade a real call for a row, and
        the row is not what protects the caller.

        What it costs when it fails is visible rather than silent: the drift sweep sees an
        agent whose worker has not attested, which is exactly the state the sweep exists to
        notice. `logger.error` and not `warning` for that reason — it is a gap in the one
        control that can say what this engine is really running.
        """
        try:
            answer = await self._api.post_attestation(
                # THE REF THIS CALL WAS STARTED WITH, not `config.engine_agent_ref`. The
                # latter is what the `agents` row happens to hold and is nullable for an
                # agent published before that column was read here; this one is the handle
                # the session was actually resolved by, so it always names the agent whose
                # prompt is being attested.
                engine_agent_ref,
                AttestationIn(
                    agent_id=config.agent_id,
                    agent_config_version_id=config.agent_config_version_id,
                    observed_prompt_sha256=call.observed_prompt_sha256,
                ),
            )
        except WorkerApiError as failure:
            logger.error(
                "prompt attestation not recorded",
                call_id=config.call_id,
                tenant_id=str(config.tenant_id),
                agent_id=str(config.agent_id),
                reason=type(failure).__name__,
            )
            return
        logger.info(
            "prompt attestation recorded",
            call_id=config.call_id,
            tenant_id=str(config.tenant_id),
            agent_id=str(config.agent_id),
            # The CONTROL PLANE's verdict, which is the one that counts. A disagreement with
            # `call.prompt_matches_config_version` would mean the two ends disagree about the
            # version row itself, and the server's reading is the one taken from it.
            matches=answer.matches,
        )

    async def aclose(self) -> None:
        """Release the client. LAST, after every call this container ran has settled."""
        await self._api.aclose()


__all__ = ["CallOutcome", "WorkerRuntime"]
