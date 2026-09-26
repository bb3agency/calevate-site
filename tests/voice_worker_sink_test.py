"""The worker's sink, over HTTP, against the real API with RLS genuinely in force.

⚠ **THIS FILE USED TO HOLD `DatabaseEventSink` AND ITS SQL (D-621).** The worker runs on
Pipecat Cloud and cannot reach our Postgres at all (`docs/DEPLOYMENT.md` §12.5 gate 6), so
the statements moved to `apps/api/worker/service.py` and the clauses that held them moved to
`tests/worker_api_test.py` — tenancy, the refusal-not-a-zero rule, the append-only
idempotency, the redaction. What is left here is what is genuinely the CLIENT's, and it is
three things:

1. **The buffer and both its bounds (D-620).** Size, timer, flush-on-settle, flush-on-close,
   and — the one that matters most — that a failed flush HOLDS the turns for the next
   attempt rather than dropping the conversation. That property was worth having against a
   database connection and is worth more against a network.
2. **The identity refusal.** A sink is built for one session, and an event naming another
   session's ids is refused BEFORE the request is built, so a crossed wire between two
   concurrent calls never puts another tenant's words in a body at all. The server refuses
   it too (`worker_api_test`), and neither check is redundant: this one is about what we
   send, that one is about what a client on somebody else's infrastructure may claim.
3. **Hard rule 6.** Nothing this path logs quotes a transcript or a number — asserted over a
   real `loguru` capture of a whole session rather than by reading the source.

**IT RUNS AGAINST THE REAL APP OVER `httpx.ASGITransport`**, not a mock: the point of a
contract split across two deployables is that the two halves AGREE, and a mocked transport
would only prove this half is self-consistent. `tests/worker_api_harness.py` owns the
harness that joins the two.

SHARED DATABASE DISCIPLINE: every organisation is minted by that harness, every assertion is
scoped to ids it created, and nothing counts rows globally.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.db.session import tenant_session
from apps.api.main import app as api_app
from calevate_shared.engine import pipecat_call_ref
from calevate_shared.events import CallEvent, TranscriptTurn
from calevate_shared.worker_api import OptOutToolIn
from loguru import logger
from sqlalchemy import text
from tests.worker_api_harness import (
    TOKEN,
    declare_pipecat_engine,
    published_agent,
    worker_client,
)
from voice_worker.api_client import WorkerApiClient, WorkerApiError
from voice_worker.call_tools import CallToolApiClient
from voice_worker.meter import (
    UNIT_STT_S,
    CarrierFactsMissingError,
    MeteredCall,
    MeteredLeg,
    UsageRow,
)
from voice_worker.sink import HttpEventSink, SinkIdentityError

pytestmark = [pytest.mark.rls]


@pytest.fixture(autouse=True)
def _pipecat_deployment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test in this file writes through `/v1/worker`, which refuses any other engine
    (D-627). `worker_api_harness.declare_pipecat_engine` records why this is per file."""
    yield from declare_pipecat_engine(monkeypatch)


async def _sink(call_id: str, **kwargs: Any) -> tuple[HttpEventSink, uuid.UUID, uuid.UUID, Any]:
    tenant_id, agent_id, _ref = await published_agent()
    api = worker_client()
    sink = HttpEventSink(
        api,
        call_id=call_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        direction="inbound",
        **kwargs,
    )
    return sink, tenant_id, agent_id, api


def _event(
    call_id: str, tenant_id: uuid.UUID, agent_id: uuid.UUID, status: str, **extra: Any
) -> CallEvent:
    return CallEvent(
        call_id=call_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        direction="inbound",
        status=status,  # type: ignore[arg-type]
        engine="pipecat",
        **extra,
    )


def _t(call_id: str, idx: int) -> TranscriptTurn:
    return TranscriptTurn(call_id=call_id, idx=idx, speaker="caller", text=f"turn {idx}")


async def _turn_count(tenant_id: uuid.UUID, call_id: str) -> int:
    async with tenant_session(tenant_id) as db:
        return int(
            (
                await db.execute(
                    text(
                        "SELECT count(*) FROM transcript_turns t "
                        "JOIN calls c ON c.id = t.call_id WHERE c.engine_call_id = :c"
                    ),
                    {"c": pipecat_call_ref(tenant_id, call_id)},
                )
            ).scalar_one()
        )


class _Flaky:
    """A `WorkerApiClient` whose observation POST can be made to fail and then recover.

    A WRAPPER RATHER THAN A MONKEYPATCHED METHOD: `WorkerApiClient` declares `__slots__`, so
    there is no instance attribute to rebind — which is the class doing its job (a client on
    this path should not be mutable by anything that holds one) and which this respects
    rather than works around.
    """

    def __init__(self, real: WorkerApiClient) -> None:
        self._real = real
        self.broken = False

    async def post_observations(self, *args: Any, **kwargs: Any) -> Any:
        if self.broken:
            raise WorkerApiError("connection reset")
        return await self._real.post_observations(*args, **kwargs)

    async def post_settlement(self, *args: Any, **kwargs: Any) -> Any:
        return await self._real.post_settlement(*args, **kwargs)

    async def aclose(self) -> None:
        await self._real.aclose()


class _RefusesTheCarrier:
    """The carrier leg nobody witnessed, and NOTHING else measured — a silent call with no CDR.

    ⚠ **THIS USED TO BE "the meter every production call has today" AND IT IS NOW THE CORNER
    CASE (D-625).** A real call transcribes and synthesises, so the production shape is
    `_MeasuredEverythingButTheCarrier` below: three legs priced, one recorded as unpriceable.
    This one keeps the "nothing could be priced at all" branch under test, because the server
    and the sink still have to distinguish it from a call with no leg to price.
    """

    def metered_rows(self, *, carrier: Any, runtime: Any) -> MeteredCall:
        return MeteredCall(rows=(), refusals=(CarrierFactsMissingError(),))


class _MeasuredEverythingButTheCarrier:
    """THE PRODUCTION SHAPE OF EVERY CALL ON THIS ENGINE: three legs measured, one refused."""

    def metered_rows(self, *, carrier: Any, runtime: Any) -> MeteredCall:
        return MeteredCall(
            rows=(
                UsageRow(
                    leg=MeteredLeg.STT,
                    unit_type=UNIT_STT_S,
                    qty=Decimal("60"),
                    unit_cost_inr=Decimal("0.01"),
                    total_inr=Decimal("0.60"),
                    meta={"reports": "3"},
                ),
            ),
            refusals=(CarrierFactsMissingError(),),
        )


class _NoLegs:
    """A session that transcribed and synthesised nothing — distinct from an unpriceable one."""

    def metered_rows(self, *, carrier: Any, runtime: Any) -> MeteredCall:
        return MeteredCall(rows=(), refusals=())


# ---------------------------------------------------------------------------------------
# 1. The buffer (D-620), which is now a buffer in front of a NETWORK.
# ---------------------------------------------------------------------------------------


async def test_a_turn_under_the_batch_size_is_held_and_not_sent(worker_token: None) -> None:
    """THE PROPERTY THE WHOLE OF D-620 RESTS ON, stated as a test rather than as a comment.

    Buffering is only worth its risk if it actually removes round trips, and "it sent anyway"
    is a regression no other assertion here would catch: every other test flushes first. It
    is worth MORE since D-621, because each avoided flush is now an authenticated HTTPS
    request against a 1 vCPU host rather than a statement on a pooled connection.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, _agent_id, api = await _sink(call_id, turn_batch_size=4)
    try:
        for idx in range(3):
            await sink.on_transcript_turn(_t(call_id, idx))
        assert await _turn_count(tenant_id, call_id) == 0, "a turn was sent before its batch"
        await sink.aclose()
        assert await _turn_count(tenant_id, call_id) == 3, "aclose did not send the remainder"
    finally:
        await api.aclose()


async def test_the_batch_sends_itself_the_moment_it_is_full(worker_token: None) -> None:
    """The size bound, and that it does not wait for the timer or for the hang-up."""
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, _agent_id, api = await _sink(
        call_id, turn_batch_size=3, turn_flush_seconds=3600
    )
    try:
        for idx in range(3):
            await sink.on_transcript_turn(_t(call_id, idx))
        assert await _turn_count(tenant_id, call_id) == 3, "a full batch did not send"
        await sink.on_transcript_turn(_t(call_id, 3))
        assert await _turn_count(tenant_id, call_id) == 3, "the next batch sent early"
        await sink.aclose()
    finally:
        await api.aclose()


async def test_the_timer_sends_a_conversation_that_never_fills_a_batch(
    worker_token: None,
) -> None:
    """THE BOUND THAT CAPS WHAT A CRASH COSTS, and the reason a size-only rule is not enough.

    A slow caller produces one turn and then silence. Without this arm those words sit in
    memory for the rest of the call and are lost with the container; with it the exposure is
    the interval and nothing more.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, _agent_id, api = await _sink(
        call_id, turn_batch_size=100, turn_flush_seconds=0.05
    )
    try:
        await sink.on_transcript_turn(_t(call_id, 0))
        for _ in range(100):
            if await _turn_count(tenant_id, call_id):
                break
            await asyncio.sleep(0.05)
        assert await _turn_count(tenant_id, call_id) == 1, "the timer never sent the turn"
        await sink.aclose()
    finally:
        await api.aclose()


async def test_a_terminal_event_is_never_held_by_the_buffer(worker_token: None) -> None:
    """**THE ONE BOUND D-621 ADDED, AND IT IS NOT AN OPTIMISATION.**

    `is_terminal` is the one status a reader OUTSIDE this container acts on:
    `admin/health.py` stops the board for a call stuck at `in_progress`, and the post-call
    pipeline waits on the row. Held for ten seconds it is a call that looks live after the
    caller hung up; held through a container replacement it stays that way for ever.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, api = await _sink(
        call_id, turn_batch_size=100, turn_flush_seconds=3600
    )
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "in_progress"))
        await sink.on_transcript_turn(_t(call_id, 0))
        assert await _turn_count(tenant_id, call_id) == 0, "a turn skipped the buffer"

        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "completed"))
        async with tenant_session(tenant_id) as db:
            status = (
                await db.execute(
                    text("SELECT status FROM calls WHERE engine_call_id = :c"),
                    {"c": pipecat_call_ref(tenant_id, call_id)},
                )
            ).scalar_one()
        assert status == "completed", "the terminal event was held in the buffer"
    finally:
        await sink.aclose()
        await api.aclose()


async def test_the_opening_event_mints_the_call_row_the_in_call_tools_need(
    worker_token: None,
) -> None:
    """Every in-call tool resolves its call by `calls.engine_call_id` and answers 404 when
    the row is not there yet. A buffered opening status left no row until the first batch
    filled or the timer fired, so a caller who said "stop calling me" in their first
    breath reached a tool that could not find the call, and the opt-out was never written.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, api = await _sink(
        call_id, turn_batch_size=100, turn_flush_seconds=3600
    )
    tools = CallToolApiClient.from_config(
        base_url="http://api",
        token=TOKEN,
        transport=httpx.ASGITransport(app=api_app, client=("127.0.0.1", 44444)),
    )
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "in_progress"))
        answer = await tools.opt_out(pipecat_call_ref(tenant_id, call_id), OptOutToolIn())
    finally:
        await sink.aclose()
        await api.aclose()
        await tools.aclose()

    # No number on this call, so the honest answer is `not_recorded` — but it is an ANSWER
    # about the caller, not a refusal to find the call.
    assert answer.status == "not_recorded"


async def test_settlement_sends_the_transcript_before_it_settles_anything(
    worker_token: None,
) -> None:
    """`settle` triggers the outbox row that starts the post-call pipeline (D-607), and that
    pipeline reads this call's turns. Settling first would race a dispatcher tick against
    turns still in memory."""
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, api = await _sink(call_id, turn_batch_size=100)
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "in_progress"))
        await sink.on_transcript_turn(_t(call_id, 0))
        assert await _turn_count(tenant_id, call_id) == 0

        await sink.settle(_NoLegs(), carrier=None, runtime=None)  # type: ignore[arg-type]
        assert await _turn_count(tenant_id, call_id) == 1, "settle ran before it flushed"
    finally:
        await sink.aclose()
        await api.aclose()


async def test_a_flush_that_fails_keeps_the_turns_for_the_next_one(worker_token: None) -> None:
    """A BAD REQUEST MUST NOT COST THE CONVERSATION. The buffer is cleared only after the
    request returns, so a failed flush is retried rather than swallowed — the difference
    between "one flush was lost" and "the call was".

    The retry is SAFE because the server dedupes on `(call_id, idx)`, a constraint that
    already existed: `worker_api_test` proves the second delivery inserts nothing twice, and
    this proves the client really does re-send.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    tenant_id, agent_id, _ref = await published_agent()
    api = _Flaky(worker_client())
    sink = HttpEventSink(
        api,  # type: ignore[arg-type]
        call_id=call_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        direction="inbound",
        turn_batch_size=2,
    )
    try:
        await sink.on_transcript_turn(_t(call_id, 0))
        api.broken = True
        with pytest.raises(WorkerApiError):
            await sink.on_transcript_turn(_t(call_id, 1))
        api.broken = False

        assert await _turn_count(tenant_id, call_id) == 0
        assert await sink.flush() == 2, "the failed flush dropped turns instead of holding them"
        assert await _turn_count(tenant_id, call_id) == 2
    finally:
        await sink.aclose()
        await api.aclose()


async def test_a_transcript_that_cannot_be_sent_stops_the_call_being_settled(
    worker_token: None,
) -> None:
    """**A COUPLING D-620 INTRODUCED, PINNED RATHER THAN DISCOVERED LATER.**

    `settle` flushes first, because it also triggers the outbox row that starts the post-call
    pipeline and that pipeline READS this call's turns. So a flush that fails takes
    settlement down with it, which was not true when each turn wrote itself.

    That is the intended direction and not an oversight: a lost settlement is RECOVERABLE —
    §12.4 reconciles the call from the carrier's CDR afterwards — and a lost transcript is
    not. Better to stall the ledger than to promise a pipeline over words that were dropped.
    What must not happen is the quiet version: settled, pipeline promised, transcript short.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    tenant_id, agent_id, _ref = await published_agent()
    api = _Flaky(worker_client())
    sink = HttpEventSink(
        api,  # type: ignore[arg-type]
        call_id=call_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        direction="inbound",
        turn_batch_size=100,
    )
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "completed"))
        await sink.on_transcript_turn(_t(call_id, 0))

        api.broken = True
        with pytest.raises(WorkerApiError):
            await sink.settle(_NoLegs(), carrier=None, runtime=None)  # type: ignore[arg-type]
        api.broken = False

        async with tenant_session(tenant_id) as db:
            promised = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages o JOIN calls c "
                        "ON o.dedupe_key = 'post-call:' || c.id WHERE c.engine_call_id = :c"
                    ),
                    {"c": pipecat_call_ref(tenant_id, call_id)},
                )
            ).scalar_one()
        assert promised == 0, "a pipeline was promised over a transcript that had not landed"
        assert await sink.flush() == 1, "the turn was dropped by the failed settlement"
    finally:
        await sink.aclose()
        await api.aclose()


async def test_closing_twice_is_harmless(worker_token: None) -> None:
    """`run_call`'s `finally` runs after `settle`, which has already flushed, so the ordinary
    path closes a sink that has nothing left. That must not raise."""
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, _agent_id, api = await _sink(call_id)
    try:
        await sink.on_transcript_turn(_t(call_id, 0))
        await sink.aclose()
        await sink.aclose()
        assert await _turn_count(tenant_id, call_id) == 1
    finally:
        await api.aclose()


# ---------------------------------------------------------------------------------------
# 2. The settlement the worker actually reaches, and what it reports back.
# ---------------------------------------------------------------------------------------


async def test_a_call_with_no_cdr_settles_as_a_recorded_refusal(worker_token: None) -> None:
    """**THE PRODUCTION SHAPE OF EVERY CALL TODAY**, end to end across the wire.

    `metered_rows` raises `CarrierFactsMissingError` before it prices anything, so the worker
    sends the refusal its meter reached and the server records it — one
    `call_metering_refusals` row, no `usage_events`, and the post-call pipeline promised
    exactly once. Hard rule 7: an unmetered call is RECORDED as unmetered, never zeroed.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, api = await _sink(call_id)
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "completed"))
        settlement = await sink.settle(
            _RefusesTheCarrier(),  # type: ignore[arg-type]
            carrier=None,
            runtime=None,
        )
    finally:
        await sink.aclose()
        await api.aclose()

    assert settlement.rows == 0
    assert settlement.refusals == ((MeteredLeg.CARRIER.value, "meter_carrier_cdr_missing"),)
    assert settlement.post_call_enqueued is True
    assert settlement.already_settled is False

    async with tenant_session(tenant_id) as db:
        row_id = (
            await db.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :c"),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).scalar_one()
        refusals = (
            await db.execute(
                text("SELECT leg, code FROM call_metering_refusals WHERE call_id = :c"),
                {"c": row_id},
            )
        ).all()
        usage = (
            await db.execute(
                text("SELECT count(*) FROM usage_events WHERE call_id = :c"), {"c": row_id}
            )
        ).scalar_one()
    assert refusals == [("carrier", "meter_carrier_cdr_missing")]
    assert usage == 0


async def test_the_legs_we_measured_settle_beside_the_leg_nobody_witnessed(
    worker_token: None,
) -> None:
    """**PARTIAL SETTLEMENT, END TO END ACROSS THE WIRE (D-625).**

    This is the production shape of every call on this engine: the worker measured the STT
    seconds it really witnessed, and nobody witnessed the connected minute (BLOCKER-1). Under
    the old contract the whole settlement was ONE refusal and the measured leg was discarded
    into an append-only ledger that could never take it later — so this test fails outright
    without the fix, on the `usage_events` count and on the 422 the wire model would answer a
    body carrying both.

    BOTH HALVES ARE ASSERTED IN THE DATABASE, because either alone is the bug: a usage row
    without the refusal would be a call we think we priced, and the refusal without the usage
    row is what shipped.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, api = await _sink(call_id)
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "completed"))
        settlement = await sink.settle(
            _MeasuredEverythingButTheCarrier(),  # type: ignore[arg-type]
            carrier=None,
            runtime=None,
        )
    finally:
        await sink.aclose()
        await api.aclose()

    assert settlement.rows == 1
    assert settlement.refusals == ((MeteredLeg.CARRIER.value, "meter_carrier_cdr_missing"),)
    assert settlement.post_call_enqueued is True

    async with tenant_session(tenant_id) as db:
        row_id = (
            await db.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :c"),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).scalar_one()
        usage = (
            await db.execute(
                text("SELECT unit_type, qty FROM usage_events WHERE call_id = :c"),
                {"c": row_id},
            )
        ).all()
        refusals = (
            await db.execute(
                text("SELECT leg, code FROM call_metering_refusals WHERE call_id = :c"),
                {"c": row_id},
            )
        ).all()
    assert [(unit, qty) for unit, qty in usage] == [(UNIT_STT_S, Decimal("60.0000"))]
    assert refusals == [("carrier", "meter_carrier_cdr_missing")]


async def test_settling_twice_is_reported_and_not_re_applied(worker_token: None) -> None:
    """The client half of the append-only guarantee (`worker_api_test` holds the server half).

    A worker whose POST timed out after the server committed MUST be able to retry, and the
    answer it gets has to reach the caller as a fact rather than as an error — `run_call`
    logs `post_call_enqueued`, and `False` on a re-settlement is correct and expected.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, api = await _sink(call_id)
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "completed"))
        first = await sink.settle(_RefusesTheCarrier(), carrier=None, runtime=None)  # type: ignore[arg-type]
        second = await sink.settle(_RefusesTheCarrier(), carrier=None, runtime=None)  # type: ignore[arg-type]
    finally:
        await sink.aclose()
        await api.aclose()

    assert (first.already_settled, first.post_call_enqueued) == (False, True)
    assert (second.already_settled, second.post_call_enqueued) == (True, False)

    async with tenant_session(tenant_id) as db:
        row_id = (
            await db.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :c"),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).scalar_one()
        refusals = (
            await db.execute(
                text("SELECT count(*) FROM call_metering_refusals WHERE call_id = :c"),
                {"c": row_id},
            )
        ).scalar_one()
        promises = (
            await db.execute(
                text("SELECT count(*) FROM outbox_messages WHERE dedupe_key = :k"),
                {"k": f"post-call:{row_id}"},
            )
        ).scalar_one()
    assert refusals == 1, "a retried settlement wrote a second, uncorrectable refusal row"
    assert promises == 1, "the post-call pipeline was promised twice"


async def _stored_status(tenant_id: uuid.UUID, call_id: str) -> str:
    async with tenant_session(tenant_id) as db:
        return str(
            (
                await db.execute(
                    text("SELECT status FROM calls WHERE engine_call_id = :c"),
                    {"c": pipecat_call_ref(tenant_id, call_id)},
                )
            ).scalar_one()
        )


async def test_settlement_keeps_the_failed_status_the_pipeline_reported(
    worker_token: None,
) -> None:
    """A call the pipeline ended as `failed` must still read `failed` after it settles.

    The server lets a `completed` settlement overwrite any terminal status, so a settlement
    that always claimed `completed` rewrote every cancelled or broken call as a clean one.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, api = await _sink(call_id)
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "in_progress"))
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "failed"))
        assert await _stored_status(tenant_id, call_id) == "failed"
        await sink.settle(_NoLegs(), carrier=None, runtime=None)  # type: ignore[arg-type]
    finally:
        await sink.aclose()
        await api.aclose()

    assert await _stored_status(tenant_id, call_id) == "failed", (
        "the settlement overwrote the pipeline's failed status with completed"
    )


async def test_a_settlement_with_no_observed_end_does_not_claim_completed(
    worker_token: None,
) -> None:
    """No terminal event means nobody saw the pipeline finish, which is not a clean call."""
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, api = await _sink(call_id)
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "in_progress"))
        await sink.settle(_NoLegs(), carrier=None, runtime=None)  # type: ignore[arg-type]
    finally:
        await sink.aclose()
        await api.aclose()

    assert await _stored_status(tenant_id, call_id) == "failed"


# ---------------------------------------------------------------------------------------
# 3. The identity refusal (hard rule 1), before anything reaches the wire.
# ---------------------------------------------------------------------------------------


async def test_an_event_naming_another_session_never_reaches_the_request(
    worker_token: None,
) -> None:
    """**A SINK IS BUILT FOR ONE SESSION.** Three shapes, because they arrive differently: a
    turn for another call, an event claiming another tenant, and an event claiming another
    agent. Each is either a bug in the producer or a crossed wire between two concurrent
    calls in one container, and both are hard rule 1 faults that must stop the write rather
    than pick one of the two tenants and be right half the time.

    Refused HERE, before the body exists, so another session's words never travel at all —
    which is what this check buys over the server's own (`worker_api_test`).
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    tenant_id, agent_id, _ref = await published_agent()

    class _NothingMayBeSent:
        async def post_observations(self, *_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("a refused event reached the wire")

        async def aclose(self) -> None:
            return None

    api = _NothingMayBeSent()
    sink = HttpEventSink(
        api,  # type: ignore[arg-type]
        call_id=call_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        direction="inbound",
    )
    try:
        with pytest.raises(SinkIdentityError):
            await sink.on_transcript_turn(_t("someone-elses-call", 0))
        with pytest.raises(SinkIdentityError):
            await sink.on_call_event(_event(call_id, uuid.uuid4(), agent_id, "completed"))
        with pytest.raises(SinkIdentityError):
            await sink.on_call_event(_event(call_id, tenant_id, uuid.uuid4(), "completed"))
    finally:
        await api.aclose()


# ---------------------------------------------------------------------------------------
# 4. Hard rule 6: nothing this path logs quotes a transcript or a number.
# ---------------------------------------------------------------------------------------


async def test_the_sink_logs_ids_and_never_a_word_of_what_was_said(worker_token: None) -> None:
    """A whole session's logging, captured.

    The turn below carries both things hard rule 6 names — a phone number and ordinary
    speech. ⚠ **THE REDACTION KIND IS NO LONGER LOGGED HERE AND THAT IS THE CHANGE D-621
    MADE**: this container does not redact any more, because `text_redacted` is the column
    hard rule 5 promises and its value may not be one a vendor's runtime computed. So the
    strictness moves the other way — the sink now holds RAW text in its buffer and must be
    proved to log none of it, which is what this asserts.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, api = await _sink(call_id)
    spoken = "please call my husband on 9876543210 about the blouse"
    captured: list[str] = []

    def sink_log(message: Any) -> None:
        captured.append(str(message) + repr(message.record["extra"]))

    handler = logger.add(sink_log, level="DEBUG")
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "in_progress"))
        await sink.on_transcript_turn(
            TranscriptTurn(call_id=call_id, idx=0, speaker="caller", text=spoken)
        )
        await sink.settle(_RefusesTheCarrier(), carrier=None, runtime=None)  # type: ignore[arg-type]
    finally:
        logger.remove(handler)
        await sink.aclose()
        await api.aclose()

    blob = "\n".join(captured)
    assert blob, "nothing was logged at all, so this test proves nothing"
    for forbidden in (spoken, "9876543210", "blouse", "husband"):
        assert forbidden not in blob, f"hard rule 6: {forbidden!r} reached a log line"
    # The ids and words an operator needs ARE there, or the log lines are not worth the risk.
    assert call_id in blob
    assert str(tenant_id) in blob
    assert "meter_carrier_cdr_missing" in blob


def test_nothing_in_this_container_imports_sqlalchemy() -> None:
    """**THE PASS CONDITION FOR §12.5 GATE 6, AS AN ASSERTION RATHER THAN A CLAIM.**

    `docs/evidence/worker-http-contract.md` §"What must be true when this is finished", item
    3. A database driver re-entering this deployable would not fail anything on its own — the
    container would simply carry a client it can never connect with — so the property has to
    be measured, not trusted. It is measured over the SOURCE rather than over `sys.modules`,
    because the test process legitimately has SQLAlchemy imported for `apps/api`.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "apps" / "voice-worker"
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith(("import sqlalchemy", "from sqlalchemy"))
    ]
    assert offenders == [], f"the voice worker imports SQLAlchemy again: {offenders}"


def test_the_worker_declares_no_database_driver() -> None:
    """The other half of the same property, one layer out: the DEPENDENCY is gone too.

    A declared driver is what keeps suggesting a connection is possible, and this container's
    whole deployment argument since D-621 is that it is not. Read off the manifest rather
    than off the lockfile, because the manifest is what a human edits.
    """
    import pathlib

    manifest = (
        pathlib.Path(__file__).resolve().parents[1] / "apps" / "voice-worker" / "pyproject.toml"
    ).read_text(encoding="utf-8")
    declared = [
        line.strip()
        for line in manifest.splitlines()
        if line.strip().startswith('"') and ("sqlalchemy" in line or "psycopg" in line)
    ]
    assert declared == [], f"a database driver is declared again: {declared}"


def test_the_client_is_the_only_way_the_worker_reaches_the_platform() -> None:
    """One door, so there is one place the Bearer header, the wall-clock bound and the hard
    rule 6 error handling live.

    `memory.py` is the ONE sanctioned exception and it is named rather than excluded by
    accident: it predates this seam, it calls a DIFFERENT endpoint that the rented engine
    also calls (`/v1/engine/caller-data/{engine}`), and it fails OPEN where everything on
    this client fails loud. Folding it in would mean widening that endpoint or narrowing this
    client's posture; both are worse than one named exception.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "apps" / "voice-worker"
    allowed = {"voice_worker/api_client.py", "voice_worker/memory.py", "voice_worker/embedding.py"}
    offenders = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if str(path.relative_to(root)) not in allowed
        and any(
            line.startswith(("import httpx", "from httpx"))
            for line in path.read_text(encoding="utf-8").splitlines()
        )
    )
    assert offenders == [], f"a second HTTP client appeared in the worker: {offenders}"


def test_the_client_module_is_what_the_sink_and_the_config_read_both_use() -> None:
    """One client type, both callers — the "one way per problem" property in executable form."""
    from voice_worker import config, sink

    assert sink.WorkerApiClient is WorkerApiClient
    assert config.WorkerApiClient is WorkerApiClient
