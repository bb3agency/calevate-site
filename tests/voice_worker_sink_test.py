"""The worker's writer, against a real database with RLS genuinely in force.

`voice_worker/sink.py` is the first thing in this repository that writes `calls`,
`transcript_turns` and `usage_events` from OUTSIDE the monolith, while a call is still
happening. Four properties are worth a test each, and every one of them is a hard rule:

1. **It writes what it was given, under the right tenant** (hard rule 1). Proved by reading
   the rows back through `tenant_session`, which is the same RLS the dashboard reads
   through — not by reading them back through the sink's own connection, which would only
   prove the sink agrees with itself.
2. **A leg it cannot price is RECORDED, never zeroed** (hard rule 7). The test asserts BOTH
   halves, because only one of them is the interesting one: a refusal row exists AND
   `usage_events` holds nothing at all for that call. A sink that wrote four legs and a
   refusal for the fifth would pass a test that only looked for the refusal, and would have
   quietly invented a settled call.
3. **Another tenant sees zero rows** (hard rule 1), on all three tables plus the new
   `call_metering_refusals`.
4. **Nothing it logs quotes a transcript** (hard rule 6), asserted over a real `loguru`
   capture of a whole session rather than by reading the source.

SHARED DATABASE DISCIPLINE: every organisation is minted by this module, every assertion is
scoped to ids this module created, and nothing counts rows globally.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from calevate_shared.engine import pipecat_call_ref
from calevate_shared.events import CallEvent, TranscriptTurn
from loguru import logger
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent
from voice_worker.db import (
    MAX_OVERFLOW,
    POOL_SIZE,
    DatabaseNotConfiguredError,
    WorkerDatabase,
)
from voice_worker.meter import (
    CarrierCdr,
    LegNotMeterableError,
    MeteredLeg,
    RuntimeUsage,
    UsageRow,
)
from voice_worker.sink import DatabaseEventSink, SinkIdentityError

pytestmark = [pytest.mark.rls]


# ---------------------------------------------------------------------------------------
# Fixtures. A real tenant, a real agent, and a sink pointed at the suite's own database.
# ---------------------------------------------------------------------------------------


def _database() -> WorkerDatabase:
    """A `WorkerDatabase` over the DSN this suite already runs against.

    Built from `get_settings()` rather than `WorkerDatabase.from_env()` so the test does not
    depend on `DATABASE_URL` being exported into the process — `from_env`'s own refusal is
    covered separately below.
    """
    return WorkerDatabase(get_settings().database_url)


async def _sink(call_id: str) -> tuple[DatabaseEventSink, uuid.UUID, uuid.UUID, WorkerDatabase]:
    tenant_id, agent_id = await _tenant_with_published_agent()
    tenant_id, agent_id = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))
    database = _database()
    sink = DatabaseEventSink(
        database,
        call_id=call_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        direction="inbound",
    )
    return sink, tenant_id, agent_id, database


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


def _row(leg: MeteredLeg, unit: str, qty: str, cost: str) -> UsageRow:
    return UsageRow(
        leg=leg,
        unit_type=unit,
        qty=Decimal(qty),
        unit_cost_inr=Decimal(cost),
        total_inr=Decimal(qty) * Decimal(cost),
        meta={"source": "test"},
    )


# ---------------------------------------------------------------------------------------
# 1. It writes what it was given.
# ---------------------------------------------------------------------------------------


async def test_a_call_event_and_its_turns_persist_under_the_calling_tenant() -> None:
    """The ordinary path, read back through RLS.

    The turn is one the redactor has something to do with, so this also proves the second
    column is populated by the pass that owns it rather than by a copy of `text`.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, database = await _sink(call_id)
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "in_progress"))
        await sink.on_transcript_turn(
            TranscriptTurn(
                call_id=call_id,
                idx=0,
                speaker="caller",
                text="my number is 9876543210",
                lang="te-IN",
                start_ms=0,
                end_ms=1500,
            )
        )
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "completed"))
    finally:
        await database.aclose()

    async with tenant_session(tenant_id) as db:
        call = (
            await db.execute(
                text(
                    "SELECT id, tenant_id, agent_id, direction, status, from_e164, to_e164 "
                    "FROM calls WHERE engine_call_id = :c"
                ),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).one()
        turns = (
            await db.execute(
                text(
                    "SELECT idx, speaker, text, text_redacted, lang, start_ms, end_ms "
                    "FROM transcript_turns WHERE call_id = :cid ORDER BY idx"
                ),
                {"cid": call[0]},
            )
        ).all()

    assert uuid.UUID(str(call[1])) == tenant_id
    assert uuid.UUID(str(call[2])) == agent_id
    assert call[3] == "inbound"
    assert call[4] == "completed"
    # §1.2: the carrier is the authority for who rang whom, so the worker leaves both alone.
    assert call[5] is None and call[6] is None

    assert len(turns) == 1
    idx, speaker, raw, redacted, lang, start_ms, end_ms = turns[0]
    assert (idx, speaker, lang, start_ms, end_ms) == (0, "caller", "te-IN", 0, 1500)
    assert raw == "my number is 9876543210"
    # HARD RULE 5: `text_redacted` is the column every CONTENT reader names — and names
    # EXCLUSIVELY, skipping a turn that has none (`crm/assist.py::_TURNS_SQL`,
    # `workers/caller_memory_distil.py::_TURNS_SQL`). A NULL here is therefore a turn that
    # never reaches the client at all, and nothing downstream would fill it: the pass that
    # would runs off a poller that returns nothing for this engine. So the VALUE is
    # asserted, not merely that the column is set.
    assert redacted is not None
    assert "9876543210" not in redacted
    assert redacted != raw


async def test_a_turn_that_arrives_before_the_started_event_still_lands() -> None:
    """Pipecat dispatches every handler as its own task (`utils/base_object.py:256-261`), so
    the order the sink sees them in is not ours to choose.

    A first turn reaching the sink before the pipeline-started event must not fail on the
    `transcript_turns -> calls` foreign key. The sink converges every write path on one
    upsert for exactly this.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, database = await _sink(call_id)
    try:
        await sink.on_transcript_turn(
            TranscriptTurn(call_id=call_id, idx=0, speaker="agent", text="namaskaram")
        )
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "in_progress"))
    finally:
        await database.aclose()

    async with tenant_session(tenant_id) as db:
        count = (
            await db.execute(
                text(
                    "SELECT count(*) FROM transcript_turns t JOIN calls c ON c.id = t.call_id "
                    "WHERE c.engine_call_id = :c"
                ),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).scalar_one()
    assert count == 1


async def test_a_status_never_moves_backwards_off_a_terminal_row() -> None:
    """A late `in_progress` must not un-complete a finished call — the clause
    `apps/workers/pipeline.py::_upsert_call_row` records in full, held here because this is
    now a second writer of that column."""
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, database = await _sink(call_id)
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "completed"))
        # A SECOND sink for the same call, because the first memoises the row id and would
        # not re-issue the upsert. This is the shape a container restart produces.
        late = DatabaseEventSink(
            database,
            call_id=call_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            direction="inbound",
        )
        await late.on_call_event(_event(call_id, tenant_id, agent_id, "in_progress"))
    finally:
        await database.aclose()

    async with tenant_session(tenant_id) as db:
        status = (
            await db.execute(
                text("SELECT status FROM calls WHERE engine_call_id = :c"),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).scalar_one()
    assert status == "completed"


async def test_an_event_naming_another_tenant_is_refused_before_it_reaches_the_database() -> None:
    """Hard rule 1, one layer above RLS.

    RLS would refuse the write anyway, and that is the point: this refuses it with a message
    naming both ids, so an isolation fault is diagnosable instead of surfacing as a policy
    violation three frames down.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, database = await _sink(call_id)
    try:
        with pytest.raises(SinkIdentityError):
            await sink.on_call_event(_event(call_id, uuid.uuid4(), agent_id, "in_progress"))
        with pytest.raises(SinkIdentityError):
            await sink.on_call_event(_event(call_id, tenant_id, uuid.uuid4(), "in_progress"))
        with pytest.raises(SinkIdentityError):
            await sink.on_transcript_turn(
                TranscriptTurn(call_id="somebody-elses-call", idx=0, speaker="agent", text="hi")
            )
        # Nothing was written by any of the three.
        async with tenant_session(tenant_id) as db:
            planted = (
                await db.execute(
                    text("SELECT count(*) FROM calls WHERE engine_call_id = :c"),
                    {"c": pipecat_call_ref(tenant_id, call_id)},
                )
            ).scalar_one()
        assert planted == 0
    finally:
        await database.aclose()


# ---------------------------------------------------------------------------------------
# 2. Money: settled, or recorded as unsettleable. Never zeroed.
# ---------------------------------------------------------------------------------------


class _AllFive:
    """A meter stub that priced everything. The sink does not care HOW the rows were made —
    `CallMeter` has its own suite — only that it writes exactly what it is handed."""

    def metered_rows(self, *, carrier: Any, runtime: Any) -> tuple[UsageRow, ...]:
        return (
            _row(MeteredLeg.CARRIER, "telephony_s", "94", "0.0213"),
            _row(MeteredLeg.RUNTIME, "platform_min", "1.6", "2.5000"),
            _row(MeteredLeg.STT, "stt_s", "88.5", "0.0040"),
            _row(MeteredLeg.TTS, "tts_kchars", "0.412", "3.4496"),
            _row(MeteredLeg.LLM, "llm_ktok_in", "1.204", "0.0143"),
        )


class _RefusesTheCarrier:
    """A meter that cannot price the carrier leg, which is EVERY production call today
    (BLOCKER-1: there is no carrier, so there is no CDR)."""

    def metered_rows(self, *, carrier: Any, runtime: Any) -> tuple[UsageRow, ...]:
        raise LegNotMeterableError(
            leg=MeteredLeg.CARRIER,
            code="meter_carrier_cdr_missing",
            detail="no carrier CDR was supplied.",
            remediation="Retrieve the CDR from the carrier and meter again.",
        )


async def test_five_priced_legs_become_five_ledger_rows_and_the_new_unit_types_are_accepted() -> (
    None
):
    """The settled path, including `llm_ktok_in` — which the `usage_events` CHECK constraint
    REFUSED until migration `a3f1c6e82d47`, so this is also the proof that landed."""
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, database = await _sink(call_id)
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "completed"))
        settlement = await sink.settle(
            _AllFive(),  # type: ignore[arg-type]
            carrier=CarrierCdr(
                connected_seconds=Decimal("94"),
                charge_inr=Decimal("2.0"),
                carrier="plivo",
                cdr_id="cdr-1",
            ),
            runtime=RuntimeUsage(
                active_minutes=Decimal("1.6"),
                inr_per_active_minute=Decimal("2.5"),
                attested_by="founder",
                source="invoice",
            ),
        )
    finally:
        await database.aclose()

    assert settlement.rows == 5
    assert settlement.refusal_code is None

    async with tenant_session(tenant_id) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT u.unit_type, u.qty, u.unit_cost_paid, u.meta->>'leg' "
                    "FROM usage_events u JOIN calls c ON c.id = u.call_id "
                    "WHERE c.engine_call_id = :c ORDER BY u.unit_type"
                ),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).all()

    by_unit = {row[0]: row for row in rows}
    assert sorted(by_unit) == [
        "llm_ktok_in",
        "platform_min",
        "stt_s",
        "telephony_s",
        "tts_kchars",
    ]
    # HARD RULE 7: NUMERIC, and the column's own quantum with half-up rounding — the sink
    # hands the rate over unquantized and lets `NUMERIC(12,4)` do it once.
    assert by_unit["tts_kchars"][2] == Decimal("3.4496")
    assert by_unit["llm_ktok_in"][2] == Decimal("0.0143")
    assert by_unit["llm_ktok_in"][1] == Decimal("1.2040")
    # The leg is stamped on the row, because `unit_type` alone does not say which of §1.3's
    # five produced it.
    assert by_unit["stt_s"][3] == "stt"


async def test_a_leg_that_cannot_be_priced_records_an_absence_and_meters_nothing() -> None:
    """**THE HARD RULE 7 TEST, AND BOTH HALVES MATTER.**

    A refusal row must exist — otherwise the only record of unmetered spend is a log line in
    a container that is about to be destroyed. And `usage_events` must hold NOTHING for this
    call: `metered_rows` is all-or-nothing by design ("THERE IS NO PARTIAL SETTLEMENT"), so
    a sink that wrote the four legs it could price and a refusal for the fifth would have
    produced a settled-looking call that is short by a leg, on an append-only ledger where
    no UPDATE can finish it.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, database = await _sink(call_id)
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "completed"))
        settlement = await sink.settle(
            _RefusesTheCarrier(),  # type: ignore[arg-type]
            carrier=None,
            runtime=None,
        )
    finally:
        await database.aclose()

    assert settlement.rows == 0
    assert settlement.refusal_code == "meter_carrier_cdr_missing"
    assert settlement.refusal_leg == "carrier"

    async with tenant_session(tenant_id) as db:
        metered = (
            await db.execute(
                text(
                    "SELECT count(*) FROM usage_events u JOIN calls c ON c.id = u.call_id "
                    "WHERE c.engine_call_id = :c"
                ),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).scalar_one()
        refusals = (
            await db.execute(
                text(
                    "SELECT r.leg, r.code, r.detail, r.remediation, r.tenant_id "
                    "FROM call_metering_refusals r JOIN calls c ON c.id = r.call_id "
                    "WHERE c.engine_call_id = :c"
                ),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).all()

    # NOT A ZERO ROW, AND NOT A PARTIAL SETTLEMENT.
    assert metered == 0
    assert len(refusals) == 1
    leg, code, detail, remediation, refusal_tenant = refusals[0]
    assert (leg, code) == ("carrier", "meter_carrier_cdr_missing")
    # The two things an operator acts on survived the trip, which is the whole reason the
    # row carries prose at all.
    assert detail and remediation
    assert uuid.UUID(str(refusal_tenant)) == tenant_id


async def test_a_call_with_nothing_to_meter_writes_neither_a_row_nor_a_refusal() -> None:
    """A session that transcribed and synthesised nothing is not an unpriceable call — it is
    a call with no leg to price, which `meter.py` distinguishes by design. Recording a
    refusal for it would cry wolf on the one board that stops for unmetered spend."""

    class _Nothing:
        def metered_rows(self, *, carrier: Any, runtime: Any) -> tuple[UsageRow, ...]:
            return ()

    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, database = await _sink(call_id)
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "completed"))
        settlement = await sink.settle(_Nothing(), carrier=None, runtime=None)  # type: ignore[arg-type]
    finally:
        await database.aclose()

    # `post_call_enqueued=True` even here, and that is the point rather than an accident:
    # a call with no leg to price still has a transcript, so its post-call pipeline — the
    # extraction, the CRM columns, the lead — is owed exactly as much as a priced call's
    # (D-603). The metering answer and the pipeline trigger are separate facts.
    assert settlement == type(settlement)(rows=0, post_call_enqueued=True)
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
    assert refusals == 0


async def test_a_settlement_that_fails_part_way_writes_no_row_at_all() -> None:
    """**A MID-SETTLEMENT DEATH LEAVES NOTHING PARTIAL.**

    Every row of one settlement goes in ONE transaction, so a process killed — or a
    statement refused — between the third leg and the fourth commits none of them. Driven
    here by a unit type the `usage_events` CHECK constraint rejects, which is the cheapest
    way to make the database refuse the LAST statement of a batch whose earlier statements
    already succeeded.

    This is the half of "a mid-call shutdown does not write a partial row" that the database
    guarantees; the half Pipecat guarantees — that a turn already handed to the sink is
    awaited before the process exits — is `runtime.py`'s `handle_sigterm=True` plus
    `PipelineWorker.cleanup`, and is asserted in `voice_worker_runtime_test.py`.
    """

    class _LastLegIsUnwritable:
        def metered_rows(self, *, carrier: Any, runtime: Any) -> tuple[UsageRow, ...]:
            return (
                _row(MeteredLeg.STT, "stt_s", "88.5", "0.0040"),
                _row(MeteredLeg.TTS, "tts_kchars", "0.412", "3.4496"),
                _row(MeteredLeg.LLM, "not_a_unit_type", "1.0", "1.0"),
            )

    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, database = await _sink(call_id)
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "completed"))
        with pytest.raises(Exception):  # noqa: B017 - the driver's IntegrityError, by any name
            await sink.settle(_LastLegIsUnwritable(), carrier=None, runtime=None)  # type: ignore[arg-type]
    finally:
        await database.aclose()

    async with tenant_session(tenant_id) as db:
        metered = (
            await db.execute(
                text(
                    "SELECT count(*) FROM usage_events u JOIN calls c ON c.id = u.call_id "
                    "WHERE c.engine_call_id = :c"
                ),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).scalar_one()
        # The CALL row survives, because it was written by an earlier, separate transaction.
        # That is the correct split: a call that happened happened, and what is missing is
        # its money — which is exactly what `calls_unmetered` looks for.
        call_rows = (
            await db.execute(
                text("SELECT count(*) FROM calls WHERE engine_call_id = :c"),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).scalar_one()
    assert metered == 0, "two legs committed without the third — the settlement was partial"
    assert call_rows == 1


async def test_settling_twice_converges_on_one_row_per_leg() -> None:
    """`usage_events` is append-only, so the second settlement cannot UPDATE and must not
    duplicate. `ON CONFLICT DO NOTHING` over the partial unique indexes is what makes a
    re-drive idempotent — including over `ux_usage_events_tenant_call_ktok`, which landed
    with the two new unit types."""
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, database = await _sink(call_id)
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "completed"))
        for _ in range(2):
            await sink.settle(
                _AllFive(),  # type: ignore[arg-type]
                carrier=None,
                runtime=None,
            )
    finally:
        await database.aclose()

    async with tenant_session(tenant_id) as db:
        counts = (
            await db.execute(
                text(
                    "SELECT u.unit_type, count(*) FROM usage_events u "
                    "JOIN calls c ON c.id = u.call_id WHERE c.engine_call_id = :c "
                    "GROUP BY u.unit_type"
                ),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).all()
    assert dict(counts) == {
        "telephony_s": 1,
        "platform_min": 1,
        "stt_s": 1,
        "tts_kchars": 1,
        "llm_ktok_in": 1,
    }


# ---------------------------------------------------------------------------------------
# 3. Cross-tenant zero rows (hard rule 1).
# ---------------------------------------------------------------------------------------


async def test_a_neighbour_sees_zero_rows_on_every_table_this_sink_writes() -> None:
    """All four, in one test, because the interesting failure is a table somebody forgot.

    `call_metering_refusals` is the new one and the one with no history: its policy was
    written in migration `a3f1c6e82d47` and this is the cross-tenant zero-rows test hard
    rule 1 requires of it. `scripts/check_rls_coverage.py` proves the policy EXISTS and
    references the GUC; this proves it isolates.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, database = await _sink(call_id)
    neighbour_id, _ = await _tenant_with_published_agent()
    neighbour_id = uuid.UUID(str(neighbour_id))
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "completed"))
        await sink.on_transcript_turn(
            TranscriptTurn(call_id=call_id, idx=0, speaker="caller", text="anything")
        )
        await sink.settle(_AllFive(), carrier=None, runtime=None)  # type: ignore[arg-type]
        await sink.settle(_RefusesTheCarrier(), carrier=None, runtime=None)  # type: ignore[arg-type]
    finally:
        await database.aclose()

    # The control: the owner can see all four, so "zero" below is a refusal and not an
    # empty table.
    async with tenant_session(tenant_id) as db:
        owner_call = (
            await db.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :c"),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).scalar_one()
        for table in ("transcript_turns", "usage_events", "call_metering_refusals"):
            planted = (
                await db.execute(
                    text(f"SELECT count(*) FROM {table} WHERE call_id = :cid"),
                    {"cid": owner_call},
                )
            ).scalar_one()
            assert planted > 0, f"the control failed: nothing was written to {table}"

    async with tenant_session(neighbour_id) as db:
        assert (
            await db.execute(
                text("SELECT count(*) FROM calls WHERE engine_call_id = :c"),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).scalar_one() == 0
        for table in ("transcript_turns", "usage_events", "call_metering_refusals"):
            leaked = (
                await db.execute(
                    text(f"SELECT count(*) FROM {table} WHERE call_id = :cid"),
                    {"cid": owner_call},
                )
            ).scalar_one()
            assert leaked == 0, f"{table} leaked another tenant's rows"


async def test_a_neighbour_cannot_write_a_refusal_against_someone_elses_call() -> None:
    """The WRITE direction, which matters more than the read here: a row saying another
    tenant's call was unmeterable is a row that re-attributes their spend, and
    `check_rls_coverage` rule 3 exists because a `WITH CHECK` nobody wrote is a policy that
    reads correctly and writes anywhere."""
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, database = await _sink(call_id)
    neighbour_id, _ = await _tenant_with_published_agent()
    neighbour_id = uuid.UUID(str(neighbour_id))
    try:
        await sink.on_call_event(_event(call_id, tenant_id, agent_id, "completed"))
    finally:
        await database.aclose()

    async with tenant_session(tenant_id) as db:
        owner_call = (
            await db.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :c"),
                {"c": pipecat_call_ref(tenant_id, call_id)},
            )
        ).scalar_one()

    with pytest.raises(Exception):  # noqa: B017 - psycopg raises its own RLS violation type
        async with tenant_session(neighbour_id) as db:
            await db.execute(
                text(
                    "INSERT INTO call_metering_refusals "
                    "(id, tenant_id, call_id, leg, code, detail, remediation) "
                    "VALUES (gen_random_uuid(), :tid, :cid, 'carrier', 'x', 'y', 'z')"
                ),
                {"tid": tenant_id, "cid": owner_call},
            )


# ---------------------------------------------------------------------------------------
# 4. Hard rule 6: nothing this path logs quotes a transcript or a number.
# ---------------------------------------------------------------------------------------


async def test_the_sink_logs_ids_and_never_a_word_of_what_was_said() -> None:
    """A whole session's logging, captured.

    The turn below carries both things hard rule 6 names — a phone number and ordinary
    speech — and the redacted form is checked too: `RedactionResult.kinds` IS logged (an
    operator needs to know the pass ran), and a lazy implementation that logged the redacted
    TEXT instead of the kinds would still hide the number while leaking the sentence.
    """
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    sink, tenant_id, agent_id, database = await _sink(call_id)
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
        await database.aclose()

    blob = "\n".join(captured)
    assert blob, "nothing was logged at all, so this test proves nothing"
    for forbidden in (spoken, "9876543210", "blouse", "husband"):
        assert forbidden not in blob, f"hard rule 6: {forbidden!r} reached a log line"
    # The ids and words an operator needs ARE there, or the log lines are not worth the risk.
    assert call_id in blob
    assert str(tenant_id) in blob
    assert "meter_carrier_cdr_missing" in blob
    assert "phone" in blob  # the redaction KIND, which is our own vocabulary


def test_the_redaction_import_does_not_drag_the_monolith() -> None:
    """`sink.py` imports `apps.workers.redaction` rather than owning a second redactor, and
    its docstring justifies that by a MEASUREMENT: the module's import graph contains no
    `apps.api` module.

    That is a property somebody could break without noticing — one `from apps.api.core...`
    added to `redaction.py` for a settings lookup would put the monolith's settings loader,
    its platform-config store and its egress guard inside a latency-critical voice
    container. Asserted rather than trusted.
    """
    import subprocess
    import sys

    probe = (
        "import sys, json; import apps.workers.redaction; "
        "print(json.dumps([m for m in sys.modules if m.startswith('apps.api')]))"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]", f"redaction now reaches the monolith: {out.stdout}"


# ---------------------------------------------------------------------------------------
# 5. The engine's own refusals.
# ---------------------------------------------------------------------------------------


def test_a_container_with_no_dsn_refuses_at_startup_and_names_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`storage.ObjectStoreNotConfiguredError`'s pattern, for the other half of the
    bootstrap: a deploy fault must be a startup failure somebody sees, not a call that
    answers the phone and then records nothing that happened on it."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(DatabaseNotConfiguredError) as caught:
        WorkerDatabase.from_env()
    assert "DATABASE_URL" in str(caught.value)


async def test_the_configured_container_builds_one_pool_with_the_bounds_it_declares(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other side of `from_env`, and the pool's shape read off the object rather than
    off the constants beside it.

    `hide_parameters` is the hard rule 6 control (a DBAPI error must not render a transcript
    turn into its message) and `max_overflow=0` is the "nothing here holds two connections"
    claim — both are properties of the ENGINE, so both are asserted on the engine.
    """
    monkeypatch.setenv("DATABASE_URL", get_settings().database_url)
    database = WorkerDatabase.from_env()
    try:
        engine = database.engine
        assert engine.dialect.name == "postgresql"
        assert engine.pool.size() == POOL_SIZE
        assert engine.pool._max_overflow == MAX_OVERFLOW
        assert engine.sync_engine.hide_parameters is True
        # And it really reaches the database under the GUC, which is the module's one job.
        tenant_id, _ = await _tenant_with_published_agent()
        async with database.tenant_connection(uuid.UUID(str(tenant_id))) as connection:
            current = (
                await connection.execute(text("SELECT current_setting('app.tenant_id', true)"))
            ).scalar_one()
        assert current == str(tenant_id)
    finally:
        await database.aclose()
