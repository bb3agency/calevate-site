"""`NormalizedEventSink`, over HTTP. The worker's record of what happened on a call.

**IT POSTS; IT DOES NOT WRITE (D-621).** This worker runs on Pipecat Cloud and cannot
reach our Postgres at all — the database lives on the VPS host behind the Docker bridge
(`docs/DEPLOYMENT.md` §12.5 gate 6). The rows are still written by the same statements
under the same idempotency keys, by `apps/api/worker/service.py`, and this posts to it.
**There is exactly ONE sink, and this is it** — a database writer surviving beside an HTTP
one would be two writers of one ledger.

**THE RULE THE SHAPE FOLLOWS, from `docs/evidence/worker-http-contract.md`:**

    THE WORKER SENDS WHAT IT OBSERVED. THE SERVER DECIDES WHAT THAT MEANS.

So three things that used to happen here do not any more, and each is a property rather
than a simplification:

* **The tenant is not resolved here.** The server parses it out of the engine-space call
  ref this sink mints (`pipecat_call_ref`) and runs every statement under that tenant's RLS.
* **The redactor does not run here.** `apps/workers/redaction.redact` now runs on our side
  of the wall, which is where the value in a column hard rule 5 promises belongs. A
  `text_redacted` this process computed would be a client-supplied value in that column.
  That import is gone from this container with it.
* **Nothing is priced here.** `settle` sends the QUANTITIES it measured with the prices
  stripped off, and a refusal for every leg its meter could not measure. `unit_cost_inr`
  cannot travel: the wire model has no field for it
  (`calevate_shared.worker_api.MeteredQuantity`).

**WHAT DID NOT CHANGE, AND MUST NOT.** The buffer and both its bounds (D-620), the identity
refusal, the flush-before-settle ordering, and the fact that a failed write leaves the turns
pending rather than dropping the conversation. If anything the buffer matters more now: each
flush was a transaction and is now an authenticated HTTP round trip.

**HARD RULE 6.** Transcript text reaches exactly one place — the `turns` list on the way to
the request body — and is never logged, never rendered into an exception (`api_client.py`
carries no response body into a message for this reason), and never counted in a log line
beyond its index. Nothing here logs a phone number because nothing here HAS one.

**HARD RULE 4 AND 7.** `usage_events` is INSERT-only, so a leg written wrong can never be
corrected by an UPDATE. That is why a leg whose quantity could not be read produces a
refusal instead of a zero, and why a RE-SETTLEMENT is answered `already_settled` by the
server rather than writing the ledger twice.

⚠ **THE UNIT OF ALL-OR-NOTHING IS THE LEG, NOT THE SETTLEMENT** (`meter.MeteredCall`,
D-625). Append-only is why: a settlement that answers is FINAL, so STT seconds and TTS
characters dropped because the carrier leg had no CDR are not deferred, they are destroyed.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from calevate_shared.engine import pipecat_call_ref
from calevate_shared.events import CallDirection, CallEvent, TranscriptTurn
from calevate_shared.worker_api import (
    KnowledgeReport,
    MeteredQuantity,
    ObservationBatch,
    SettlementRefusal,
    SettlementRequest,
)
from loguru import logger

from voice_worker.api_client import WorkerApiClient
from voice_worker.meter import CallMeter, CarrierCdr, LegNotMeterableError, RuntimeUsage, UsageRow

#: How many turns may wait in memory before they are written, and how long the oldest one
#: may wait. Two bounds rather than one, because either alone has a hole: a size-only rule
#: never flushes a slow conversation, and a time-only rule writes one row at a time in a
#: fast one.
#:
#: **WHY BUFFER AT ALL — AND WHAT IT COSTS, SAID PLAINLY.** A write per turn is one round
#: trip per sentence, and since D-621 that round trip is an authenticated HTTPS request
#: against a 1 vCPU host rather than a statement on a pooled connection. The saving is real
#: — a three-minute call is roughly 35 turns and ~4 flushes at these defaults.
#:
#: The cost is equally real and is the whole reason the second bound exists: a container
#: that dies with turns in memory loses them, where a per-turn write loses only the tail.
#: The interval is what CAPS that loss — never "the call", only "the last few seconds".
#:
#: ⚠ NOTHING READS A TURN WHILE THE CALL IS RUNNING, WHICH IS WHAT MAKES THIS SAFE: every
#: reader of `transcript_turns` is post-call (`crm/service.py`, `crm/assist.py`,
#: `compliance/export_routes.py`, `compliance/tenant_erasure.py`) and no transcript surface
#: in `apps/web` polls. A live transcript surface is what would force this buffer to be
#: reconsidered.
DEFAULT_TURN_BATCH_SIZE: Final[int] = 8
DEFAULT_TURN_FLUSH_SECONDS: Final[float] = 10.0


class SinkIdentityError(RuntimeError):
    """An event named a tenant, agent or call this sink was not built for.

    RAISED and not logged-and-dropped. A sink is built for one session; an event carrying
    another session's ids is either a bug in the producer or a crossed wire between two
    concurrent calls in one container, and both are hard rule 1 faults that must stop the
    write rather than pick one of the two tenants and be right half the time.

    **IT IS CHECKED HERE AS WELL AS ON THE SERVER, AND NEITHER IS REDUNDANT.** The server
    refuses a batch whose contents disagree with the ref it was posted to, because a client
    is a thing on somebody else's infrastructure. This refuses BEFORE the request is built,
    so a crossed wire never puts another session's words in a body at all.

    Ids only (hard rule 6).
    """


@dataclass(frozen=True, slots=True)
class Settlement:
    """What one settlement attempt did. Returned so a caller can log the branch, not decide it.

    ⚠ **`refusals` IS A LIST BECAUSE THE BRANCHES ARE NOT EXCLUSIVE (D-625).** A call
    routinely settles three legs AND records a refusal for the carrier leg nobody could
    witness — that is partial settlement. Four readable cases: rows and no refusals is a
    fully settled call; refusals and no rows is a call nothing could be priced on; zero of
    both is a call with nothing to meter (`meter.MeteredCall`); rows AND refusals is the
    ordinary shape on this engine today.
    """

    rows: int
    #: `(leg, code)` per leg nobody could price, in the order `metered_rows` reached them.
    #: The SERVER's own refusals are not in here: it can refuse a leg this worker measured
    #: fine (an unattested rate), and `refusals_recorded` on the answer is what counts those.
    refusals: tuple[tuple[str, str], ...] = ()
    #: Whether THIS settlement wrote the outbox row that starts the post-call pipeline.
    #: `False` on a re-settlement is the correct and expected answer — the promise was
    #: already on the books and the pipeline must run once, not twice.
    post_call_enqueued: bool = False
    #: Whether the server answered "this call was already settled". A retried POST whose
    #: first attempt committed gets this, and it is not an error: an append-only ledger has
    #: no UPDATE with which to correct a double write, so answering the retry is the only
    #: shape available.
    already_settled: bool = False


class HttpEventSink:
    """The production `NormalizedEventSink`: OUR normalized models in, HTTP requests out.

    **ONE PER CALL, AND THAT IS WHAT MAKES THE IDENTITY CHECK POSSIBLE.** `TranscriptTurn`
    carries a `call_id` and no tenant — it cannot, it is the shape every engine's transcript
    normalizes to — so the tenant a turn belongs to has to come from somewhere, and the only
    honest somewhere is the `SessionConfig` this call was assembled from. A process-wide
    sink would have to infer it from the call id.

    **WRITES ARE SERIALIZED BEHIND ONE LOCK.** Pipecat dispatches every event handler as its
    own task (`pipecat/utils/base_object.py:256-261`, read in the installed 1.10.0 tree), so
    two turns and the call-ended event can be in flight at once. Serializing them costs
    nothing on a path that is already off the conversation's critical path, and it buys the
    property the server's own call-row upsert depends on being able to assume: one request
    about this call at a time, so two concurrent batches cannot interleave a status backwards
    past a status forwards.

    **THE CLIENT IS SHARED AND THIS OBJECT DOES NOT CLOSE IT.** One `httpx.AsyncClient` per
    process (`api_client.WorkerApiClient`), not one per call: a client per call re-does DNS,
    TCP and TLS on every session, and the container is reused across sessions.
    """

    def __init__(
        self,
        api: WorkerApiClient,
        *,
        call_id: str,
        tenant_id: UUID,
        agent_id: UUID,
        direction: CallDirection,
        turn_batch_size: int = DEFAULT_TURN_BATCH_SIZE,
        turn_flush_seconds: float = DEFAULT_TURN_FLUSH_SECONDS,
    ) -> None:
        """The four ids this call is, and the client it posts them through.

        **FOUR IDS RATHER THAN A `SessionConfig`, WHICH IS THE ONE SHAPE DECISION HERE.**
        Those are the only fields of that object this sink would read — and taking the whole
        thing would mean the sink could not exist until the config had been fetched, which is
        precisely the order `session.start_session` does NOT have: it takes the sink as an
        argument and loads the config itself, exactly as it takes the transport.
        """
        self._api = api
        self._call_id = call_id
        #: What lands in `calls.engine_call_id` — the idempotency key every writer of that
        #: row converges on, and, since D-621, the ONLY handle this worker ever names a call
        #: by. The server parses the tenant back out of it (`tenant_of_pipecat_ref`) and
        #: reads the row under that tenant's RLS, which is what lets the worker address a
        #: call without ever holding a `calls.id`.
        #:
        #: **MINTED HERE RATHER THAN TAKEN AS A FIFTH ARGUMENT**, because this is the only
        #: place that has both halves by construction. A caller that had to assemble it
        #: could assemble it wrongly, and the failure would be silent and late.
        self._engine_call_id = pipecat_call_ref(tenant_id, call_id)
        self._tenant_id = tenant_id
        self._agent_id = agent_id
        self._direction = direction
        self._lock = asyncio.Lock()
        #: Turns waiting to be sent. RAW, because redaction is the server's now — which also
        #: means this buffer holds exactly what the wire will carry and nothing derived.
        self._pending: list[TranscriptTurn] = []
        #: Call events waiting to go with them. Buffered TOO, and that is new: over SQL a
        #: lifecycle event was one statement and there was no reason to hold it, but over
        #: HTTP an unbuffered event is a whole round trip for a status nobody is waiting on.
        #: A TERMINAL event forces the flush (see `on_call_event`), so the one status that
        #: matters is never held.
        self._events: list[CallEvent] = []
        #: WHAT THIS CALL'S KNOWLEDGE TURNED OUT TO BE, waiting for the next batch to carry
        #: it. Set once, cleared once it has been accepted, `None` either side of that.
        self._knowledge: KnowledgeReport | None = None
        self._batch_size = max(1, turn_batch_size)
        self._flush_seconds = turn_flush_seconds
        #: The timer arm. Started on the FIRST buffered turn rather than in `__init__`,
        #: because a sink is constructed before there is a running loop to attach to in some
        #: of this repository's tests, and a task created there would warn and die.
        self._flusher: asyncio.Task[None] | None = None
        self._closed = False

    # -- the Protocol --------------------------------------------------------------------

    async def on_call_event(self, event: CallEvent) -> None:
        """One lifecycle event. Status only ever moves forward, and the server enforces it.

        **A TERMINAL EVENT FLUSHES IMMEDIATELY AND THE REST DO NOT.** `is_terminal` is the
        one status a reader outside this container acts on: `admin/health.py` stops the board
        for a call stuck at `in_progress`, and the post-call pipeline waits on the row. An
        opening status held for ten seconds costs nothing; a terminal one held for ten
        seconds is a call that looks live after the caller hung up, and a container replaced
        in those ten seconds leaves it that way for ever.
        """
        self._check_identity(
            call_id=event.call_id, tenant_id=event.tenant_id, agent_id=event.agent_id
        )
        async with self._lock:
            self._events.append(event)
            self._start_flusher()
            if event.is_terminal or len(self._pending) >= self._batch_size:
                await self._flush_locked()
        logger.info(
            "call event recorded",
            call_id=self._call_id,
            tenant_id=str(self._tenant_id),
            agent_id=str(self._agent_id),
            status=event.status,
        )

    async def on_transcript_turn(self, turn: TranscriptTurn) -> None:
        """One turn, buffered, and sent raw for the server to redact and store.

        **`text_redacted` IS FILLED BY THE SERVER AND THIS PROCESS MUST NOT COMPUTE IT.**
        That column is what every CONTENT reader in this repository names
        (`crm/assist.py::_TURNS_SQL`, `workers/caller_memory_distil.py::_TURNS_SQL`) — what
        a client's dashboard, the copilot and caller memory are allowed to see. Computing it
        in a container on a vendor's infrastructure would put the least trusted party in the
        system in charge of the redaction hard rule 5 promises. `apps/workers/redaction.
        redact` is the repository's one redactor, and it runs where the row is written.
        """
        self._check_identity(call_id=turn.call_id)
        logger.info(
            "transcript turn buffered",
            call_id=self._call_id,
            tenant_id=str(self._tenant_id),
            idx=turn.idx,
            speaker=turn.speaker,
        )
        async with self._lock:
            self._pending.append(turn)
            self._start_flusher()
            if len(self._pending) >= self._batch_size:
                await self._flush_locked()

    def report_knowledge(self, report: KnowledgeReport) -> None:
        """Record what this call's knowledge base turned out to be. **SYNCHRONOUS, ALWAYS.**

        **IT DOES NOT AWAIT, DOES NOT SEND AND CANNOT FAIL, AND THAT IS THE WHOLE DESIGN.**
        The caller is `runtime.run_call`, one line after the pack was resolved and one line
        before the pipeline runs — the moment the caller is waiting to be greeted. Telling
        our side that a call is degraded is REPORTING, not a gate: a `await` here would put
        the platform API's latency (and its outages) in front of the first sentence of a
        call that is already having a bad day. So the fact is parked, and the batch that
        was leaving anyway takes it.

        **AND IT DOES NOT ARM THE TIMER.** `_start_flusher` needs a running loop and this
        is a plain synchronous method; every call emits lifecycle events and every call
        settles, and both paths flush — so the report always leaves without this method
        needing to create a task it might not be allowed to create.

        A second report on one call REPLACES the first rather than queueing: the pack is
        resolved once per session and there is no second answer to preserve.
        """
        self._knowledge = report

    # -- the buffer ----------------------------------------------------------------------

    async def flush(self) -> int:
        """Send every buffered turn now, and answer how many. Safe to call at any time.

        **THE DRAIN PATH CALLS THIS, AND THAT IS WHAT BOUNDS THE LOSS.** `settle` calls it
        too, so a call that ends normally never depends on the timer having fired.
        """
        async with self._lock:
            return await self._flush_locked()

    async def _flush_locked(self) -> int:
        """The one writer. Assumes `_lock` is held.

        **ONE REQUEST FOR THE WHOLE BATCH, EVENTS AND TURNS TOGETHER**, which is the shape
        the server needs rather than merely the cheap one: it upserts the call row once and
        every turn in the batch references it, so the foreign key can never be half-satisfied
        by a crash between two requests.

        The buffer is cleared only AFTER the request returns. A failed flush therefore leaves
        the turns pending and the next flush retries them, rather than dropping the
        conversation on one bad connection — and a retry is safe because the server dedupes
        on `(call_id, idx)`, a constraint that already existed.
        """
        # A PENDING KNOWLEDGE REPORT IS ENOUGH ON ITS OWN. Without this clause a call whose
        # turns and events had all already been sent would drop the one fact that says it
        # answered nothing — `settle` flushes first, and an empty flush used to return here.
        if not self._pending and not self._events and self._knowledge is None:
            return 0
        batch = ObservationBatch(
            agent_id=self._agent_id,
            direction=self._direction,
            events=list(self._events),
            turns=list(self._pending),
            knowledge=self._knowledge,
        )
        answer = await self._api.post_observations(self._engine_call_id, batch)
        sent = len(batch.turns)
        del self._pending[:sent]
        del self._events[: len(batch.events)]
        # Cleared only AFTER the request returned, exactly as the two buffers above are: a
        # flush that failed leaves the report pending and the next one re-sends it. The
        # server writes the column by the same rule, so a re-delivery restates one value.
        if batch.knowledge is not None:
            self._knowledge = None
        logger.info(
            "observations posted",
            call_id=self._call_id,
            tenant_id=str(self._tenant_id),
            events=len(batch.events),
            turns=sent,
            # WHAT THE SERVER DID, which is not the same number and must not be read as
            # loss: a smaller `turns_written` is a retry meeting rows we already had.
            turns_written=answer.turns_written,
            turns_already_present=answer.turns_already_present,
            # `None` on every batch but the one that carried the report. A word out of a
            # closed set, never a key or a question (hard rule 6).
            knowledge=None if batch.knowledge is None else batch.knowledge.state,
        )
        return sent

    def _start_flusher(self) -> None:
        """Arm the timer once, on the first buffered turn or event.

        **THE TIMER IS THE HALF THAT MAKES BUFFERING HONEST.** Size alone never flushes a
        conversation that goes quiet, and "quiet then the container is replaced" is exactly
        when turns are lost. Started lazily because a sink is constructed outside a running
        loop in several tests, where `create_task` would raise.
        """
        if self._flusher is not None or self._closed or self._flush_seconds <= 0:
            return
        self._flusher = asyncio.create_task(self._flush_forever())

    async def _flush_forever(self) -> None:
        """Flush on a clock until the sink closes.

        Failures are swallowed HERE and nowhere else: a timer that dies on one bad request
        would silently disarm the bound this buffer's safety rests on, and the turns it could
        not send stay pending for the next tick either way.
        """
        while not self._closed:
            await asyncio.sleep(self._flush_seconds)
            try:
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "buffered turn flush failed; will retry on the next tick",
                    call_id=self._call_id,
                    error=type(exc).__name__,
                )

    async def aclose(self) -> None:
        """Stop the timer and send what is left. Idempotent.

        Ordering is deliberate: the flag first so the timer cannot re-arm, the FLUSH before
        the cancel so a turn buffered microseconds ago is not thrown away by the shutdown
        that was meant to save it.
        """
        self._closed = True
        try:
            await self.flush()
        finally:
            flusher, self._flusher = self._flusher, None
            if flusher is not None:
                flusher.cancel()
                with suppress(asyncio.CancelledError):
                    await flusher

    # -- settlement ----------------------------------------------------------------------

    async def settle(
        self,
        meter: CallMeter,
        *,
        carrier: CarrierCdr | None,
        runtime: RuntimeUsage | None,
    ) -> Settlement:
        """Send what this call measured, or the refusal the meter reached. One request.

        **THE TRANSCRIPT LANDS BEFORE THE SETTLEMENT DOES, and the order is the point:** the
        settlement is what writes the outbox row that starts the post-call pipeline (D-607),
        and that pipeline reads this call's turns. Settling first would race a dispatcher
        tick against turns still sitting in memory.

        **THE WORKER SENDS QUANTITIES AND THE SERVER PRICES THEM (D-621).** The RATE the
        meter multiplied by cannot cross this wire: `MeteredQuantity` has no money field, and
        `apps/api/billing/rates.py` is the one door a rupee comes through. What travels is
        what this container witnessed.

        ⚠ **TWO OF THE FIVE LEGS §1.3 NAMES ARE NOT SETTLEABLE FROM HERE, AND THAT IS THE
        DESIGN RATHER THAN A REGRESSION.** The carrier's connected minute is priced by the
        CARRIER (§1.2 makes their CDR the authority for the quantity AND the charge) and
        Pipecat Cloud's active minute is an unanswered vendor question (§7 P-1). Neither is a
        rate; both are outside facts somebody hands us, and a worker asserting one would be
        the third party in this system telling us what a call cost. Each records a refusal
        naming its leg.

        ⚠ **THE OTHER THREE SETTLE ANYWAY (D-625), AND THAT IS WHY THIS IS NOT
        ALL-OR-NOTHING.** `carrier` and `runtime` are `None` on every production call
        (BLOCKER-1), so refusing the whole settlement on the two unwitnessed legs throws
        away the STT seconds, TTS characters and LLM tokens this container really measured
        — permanently, because `usage_events` is append-only. Both halves are sent: the
        quantities it could read, and a refusal per leg it could not.

        **CALLED AFTER THE PIPELINE HAS DRAINED, NEVER FROM INSIDE ITS TEARDOWN.**
        `CallMeter.attach` states the reason: usage reports arrive as their own tasks.

        ⚠ **NO `at` ARGUMENT, FOR THE SAME REASON THERE IS NO PRICE.**
        `usage_events.occurred_at` and `call_metering_refusals.occurred_at` are stamped by
        the SERVER. A ledger row's instant is a fact about when WE recorded it, and a
        container on a vendor's infrastructure with an unverified clock is not the authority
        for that — the same reason `_duration_s` is not the billable minute.
        """
        await self.flush()
        metered = meter.metered_rows(carrier=carrier, runtime=runtime)

        request = SettlementRequest(
            # `completed` and not the observed status: `settle` runs after the pipeline has
            # drained, so this is the worker saying the SESSION finished. The server's clause
            # is forward-only and a terminal status already on the row wins, so a call cut
            # off mid-sentence keeps the status its terminal event reported.
            final_status="completed",
            direction=self._direction,
            agent_id=self._agent_id,
            refusals=[_refusal_of(refused) for refused in metered.refusals],
            quantities=[_quantity_of(row) for row in metered.rows],
        )
        answer = await self._api.post_settlement(self._engine_call_id, request)

        refusals = tuple((refused.leg.value, refused.code) for refused in metered.refusals)
        if refusals or answer.refusals_recorded:
            # `error` and not `warning`: an unmetered leg is spend we absorbed and cannot
            # bill, and it is the state `admin/health.py::calls_unmetered` stops the board
            # for. It is logged even when other legs settled — a call that priced three legs
            # of five is still a call whose cost we do not know.
            #
            # TWO COUNTS, BECAUSE THE TWO ENDS REFUSE FOR DIFFERENT REASONS: ours is a
            # quantity nobody could read, and the server's is an attested rate that does not
            # exist for a quantity we read fine (hard rule 7). An operator triages them in
            # different places, so the log must not merge them.
            logger.error(
                "call leg not meterable",
                call_id=self._call_id,
                tenant_id=str(self._tenant_id),
                legs=",".join(leg for leg, _ in refusals),
                codes=",".join(code for _, code in refusals),
                server_refusals=answer.refusals_recorded,
                rows=answer.rows_written,
                already_settled=answer.already_settled,
                post_call_enqueued=answer.post_call_enqueued,
            )
        else:
            logger.info(
                "call settled",
                call_id=self._call_id,
                tenant_id=str(self._tenant_id),
                legs=",".join(sorted({row.leg.value for row in metered.rows})),
                rows=answer.rows_written,
                already_settled=answer.already_settled,
                post_call_enqueued=answer.post_call_enqueued,
            )
        return Settlement(
            rows=answer.rows_written,
            refusals=refusals,
            post_call_enqueued=answer.post_call_enqueued,
            already_settled=answer.already_settled,
        )

    # -- internals -----------------------------------------------------------------------

    def _check_identity(
        self,
        *,
        call_id: str,
        tenant_id: UUID | None = None,
        agent_id: UUID | None = None,
    ) -> None:
        """Refuse an event that is not this session's. See `SinkIdentityError`.

        `tenant_id`/`agent_id` are optional because `TranscriptTurn` carries neither and
        `CallEvent` declares both `| None` (an adapter resolves them from a vendor ref and
        they stay None until it does). What is checked is DISAGREEMENT, not presence: a
        `None` is an event that never claimed, and a claim that differs is the fault.
        """
        if call_id != self._call_id:
            raise SinkIdentityError(
                f"event names call {call_id!r}, sink was built for {self._call_id!r}"
            )
        if tenant_id is not None and tenant_id != self._tenant_id:
            raise SinkIdentityError(
                f"event names tenant {tenant_id}, sink was built for {self._tenant_id}"
            )
        if agent_id is not None and agent_id != self._agent_id:
            raise SinkIdentityError(
                f"event names agent {agent_id}, sink was built for {self._agent_id}"
            )


def _refusal_of(error: LegNotMeterableError) -> SettlementRefusal:
    """`meter.py`'s refusal, as the four fields `call_metering_refusals` already stores.

    OUR OWN PROSE, all four of them: every string is authored in this repository and quotes
    no payload, no transcript and no number — the same bar `core/alerting.alert` sets for its
    `detail`.
    """
    return SettlementRefusal(
        leg=error.leg.value,
        code=error.code,
        detail=error.detail,
        remediation=error.remediation,
    )


def _quantity_of(row: UsageRow) -> MeteredQuantity:
    """One measured leg, with the price stripped off. Hard rule 7 at the wire.

    `unit_cost_inr` and `total_inr` are DROPPED rather than absent-by-accident: the server
    re-derives them from the rate card it holds, so the figure that reaches `unit_cost_paid`
    is one an operator attested and never one this container computed. The leg name travels
    because `unit_type` alone does not say which of §1.3's five legs produced it.
    """
    return MeteredQuantity(
        leg=row.leg.value, unit_type=row.unit_type, qty=row.qty, meta=dict(row.meta)
    )


__all__ = [
    "DEFAULT_TURN_BATCH_SIZE",
    "DEFAULT_TURN_FLUSH_SECONDS",
    "HttpEventSink",
    "Settlement",
    "SinkIdentityError",
]
