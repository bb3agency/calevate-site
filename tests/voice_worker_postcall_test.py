"""A settled `owned_runtime` call reaches the post-call pipeline — the SAME one (D-607).

**WHAT WAS BROKEN.** `apps/voice-worker` writes `calls`, `transcript_turns` and
`usage_events` while a call is happening, and then nothing happened: no webhook (nothing
external calls us), no poller (`PipecatEngine.list_executions` reports nothing, on an
independence argument that is correct for a poller) and no enqueue anywhere in the
container. So for every call this engine handled, extraction never ran, the CRM columns
stayed empty, no lead was filed and no hot-lead alert fired — a silent, total loss of the
product's core value on the new engine.

**WHAT THIS PROVES, AND WHY EACH CLAUSE IS HERE RATHER THAN IMPLIED.**

1. The settlement writes ONE outbox row, in the settlement's own transaction, naming a job
   the fleet actually registers. "Registered" is asserted against `WorkerSettings.functions`
   and not against a string, because arq accepts any name, logs one warning and drops the
   job — the failure `scripts/check_job_wiring.py` exists for.
2. A second settlement of the same call writes NO second row. The trigger is idempotent at
   the database, on the partial unique index, exactly as `usage_events` converges next to
   it.
3. The row's own payload, read back out of `outbox_messages` rather than reconstructed, is
   a usable argument to `run_post_call_pipeline` — the function the BOLNA path reaches, not
   a copy of it — and driving it produces a real `call_extractions` row with the agent's
   fields in it.
4. `PipecatEngine.get_execution` can find the call at all, which is the half that is easy
   to get wrong: `calls` is FORCE-RLS'd and that signature carries no tenant, so the
   adapter parses one out of the engine-space id the sink minted. A test that read the row
   through a tenant session would prove nothing about that.

SHARED DATABASE DISCIPLINE: every organisation is minted here, every assertion is scoped to
ids this module created, and nothing is counted globally.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.workers import pipeline as pipeline_module
from apps.workers.pipeline import POSTCALL_JOB, run_post_call_pipeline
from calevate_shared.engine import VoiceEngine, pipecat_call_ref
from calevate_shared.events import CallEvent, TranscriptTurn
from sqlalchemy import text
from voice_worker.db import WorkerDatabase
from voice_worker.sink import DatabaseEventSink

pytestmark = [pytest.mark.rls]


CLINIC_SCHEMA: list[dict[str, Any]] = [
    {"key": "name", "label": "Caller name", "type": "text", "reason": "who is calling"},
    {
        "key": "intent",
        "label": "Intent",
        "type": "enum",
        "enum_values": ["book", "reschedule", "enquiry"],
        "reason": "what they want",
    },
]


# ---------------------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _the_deployment_runs_pipecat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the pipeline's engine lookup at the `pipecat` adapter, through the REAL factory.

    `get_engine()` reads one process-wide `Settings.engine`, so a deployment running this
    engine is the whole premise of the feature. The substitution is a copy of the live
    settings with that one field changed and `build_engine` doing the rest — so this
    exercises the same adapter the factory would hand production, rather than an instance
    the test constructed and therefore vouched for itself.
    """
    reset_engine_cache()

    def _pipecat() -> VoiceEngine:
        return get_engine(get_settings().model_copy(update={"engine": "pipecat"}))

    monkeypatch.setattr(pipeline_module, "get_engine", _pipecat)


async def _seed_tenant() -> tuple[uuid.UUID, uuid.UUID]:
    """An org, an agent published on THIS engine, and an extraction schema to fill.

    No `engine_agent_routes` row, deliberately: that table exists so an inbound WEBHOOK can
    find a tenant, and this engine has no webhook (`PipecatEngine.verify_webhook` is
    `none`, and §9.2 predicted the table would be redundant here). If the seam under test
    needed one, that would itself be the finding.
    """
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Pipecat Clinic', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": f"pipecat-pc-{tenant_id.hex[:10]}"},
        )
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, caller_memory_notice_line, status, "
                "engine, engine_agent_ref, created_at, updated_at) VALUES (:id, :tid, "
                "'Receptionist', 'inbound', 'Idi AI assistant.', 'Idi AI assistant.', "
                "'This call is being recorded.', 'I keep a short note.', 'live', 'pipecat', "
                ":ref, now(), now())"
            ),
            {
                "id": agent_id,
                "tid": tenant_id,
                "ref": f"pipecat:{tenant_id}:{agent_id}",
            },
        )
        await session.execute(
            text(
                "INSERT INTO extraction_schemas (id, tenant_id, agent_id, version, fields, "
                "published_at, created_at, updated_at) VALUES (:id, :tid, :aid, 1, "
                "CAST(:fields AS jsonb), now(), now(), now())"
            ),
            {
                "id": schema_id,
                "tid": tenant_id,
                "aid": agent_id,
                "fields": json.dumps(CLINIC_SCHEMA),
            },
        )
        await session.execute(
            text("UPDATE agents SET extraction_schema_id = :sid WHERE id = :aid"),
            {"sid": schema_id, "aid": agent_id},
        )
    return tenant_id, agent_id


class _NothingToMeter:
    """A meter with no priced leg. The honest shape for a deployment with no attested rate
    card and no carrier CDR, which is every deployment today (`meter.RateCardMissingError`,
    BLOCKER-1) — and the branch that used to open no transaction at all."""

    def metered_rows(self, *, carrier: Any, runtime: Any) -> tuple[Any, ...]:
        return ()


async def _run_one_call(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, call_id: str, *, settlements: int = 1
) -> list[Any]:
    """Drive a whole call through the real sink. Returns each settlement's result."""
    database = WorkerDatabase(get_settings().database_url)
    sink = DatabaseEventSink(
        database,
        call_id=call_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        direction="inbound",
    )
    results = []
    try:
        await sink.on_call_event(
            CallEvent(
                call_id=call_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                direction="inbound",
                status="in_progress",
                engine="pipecat",
            )
        )
        await sink.on_transcript_turn(
            TranscriptTurn(
                call_id=call_id,
                idx=0,
                speaker="caller",
                text="Hello, my name is Latha and I want to book an appointment.",
            )
        )
        await sink.on_transcript_turn(
            TranscriptTurn(
                call_id=call_id,
                idx=1,
                speaker="agent",
                text="Certainly. What time suits you?",
            )
        )
        await sink.on_call_event(
            CallEvent(
                call_id=call_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                direction="inbound",
                status="completed",
                engine="pipecat",
            )
        )
        for _ in range(settlements):
            results.append(await sink.settle(_NothingToMeter(), carrier=None, runtime=None))  # type: ignore[arg-type]
    finally:
        await database.aclose()
    return results


async def _call_row_id(tenant_id: uuid.UUID, call_id: str) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        return uuid.UUID(
            str(
                (
                    await session.execute(
                        text("SELECT id FROM calls WHERE engine_call_id = :e"),
                        {"e": pipecat_call_ref(tenant_id, call_id)},
                    )
                ).scalar_one()
            )
        )


async def _outbox_rows(call_row_id: uuid.UUID) -> list[Any]:
    """This call's outbox rows, scoped to its own dedupe key — never a global count."""
    async with untenanted_session() as session:
        return list(
            (
                await session.execute(
                    text(
                        "SELECT id, job, payload, status FROM outbox_messages WHERE dedupe_key = :k"
                    ),
                    {"k": f"post-call:{call_row_id}"},
                )
            ).all()
        )


# ---------------------------------------------------------------------------------------
# 1. The settlement promises the pipeline, once, under a name the fleet answers to.
# ---------------------------------------------------------------------------------------


async def test_settling_a_pipecat_call_enqueues_the_post_call_pipeline() -> None:
    tenant_id, agent_id = await _seed_tenant()
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    (settlement,) = await _run_one_call(tenant_id, agent_id, call_id)
    assert settlement.post_call_enqueued is True

    call_row_id = await _call_row_id(tenant_id, call_id)
    rows = await _outbox_rows(call_row_id)
    assert len(rows) == 1, "one settlement, one promise"
    _id, job, payload, status = rows[0]
    assert job == POSTCALL_JOB
    assert status == "pending"
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["call_id"] == str(call_row_id)
    # The ENGINE-SPACE handle, which is what `get_execution` takes. A bare uuid here would
    # leave the pipeline unable to find its own transcript, and would do it silently.
    assert payload["execution_id"] == pipecat_call_ref(tenant_id, call_id)


async def test_the_worker_and_the_fleet_name_one_job() -> None:
    """`voice_worker.sink.POSTCALL_JOB` is a RESTATEMENT of
    `apps.workers.pipeline.POSTCALL_JOB` — the worker cannot import the monolith — so the
    two spellings need something holding them in step, and this is it. A drift here is a
    job arq accepts, warns about once and drops."""
    from apps.workers.settings import FUNCTIONS
    from voice_worker.sink import POSTCALL_JOB as WORKER_SPELLING

    assert WORKER_SPELLING == POSTCALL_JOB
    assert WORKER_SPELLING in {fn.__name__ for fn in FUNCTIONS}, (
        "the worker enqueues a job no arq worker registers"
    )


async def test_settling_twice_promises_the_pipeline_once() -> None:
    """Hard rule 4's neighbour: the ledger converges with `ON CONFLICT DO NOTHING` and so
    must the trigger. Two pipelines on one call would mean two hot-lead alerts to the
    client and two CRM fan-outs under two delivery ids they cannot deduplicate."""
    tenant_id, agent_id = await _seed_tenant()
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    first, second = await _run_one_call(tenant_id, agent_id, call_id, settlements=2)

    assert first.post_call_enqueued is True
    assert second.post_call_enqueued is False, "the second settlement re-promised the pipeline"
    assert len(await _outbox_rows(await _call_row_id(tenant_id, call_id))) == 1


# ---------------------------------------------------------------------------------------
# 2. The promise, taken at face value, actually runs the pipeline.
# ---------------------------------------------------------------------------------------


async def test_the_outbox_payload_drives_the_real_post_call_pipeline() -> None:
    """End to end over a real database: settle, take the row the dispatcher would take, and
    run the job it names. The extraction row at the end is the product's core value
    arriving — the thing that was silently absent for every call on this engine."""
    tenant_id, agent_id = await _seed_tenant()
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    await _run_one_call(tenant_id, agent_id, call_id)
    call_row_id = await _call_row_id(tenant_id, call_id)

    ((_id, job, payload, _status),) = await _outbox_rows(call_row_id)
    # The dispatcher does exactly this: `enqueue(message.job, message.payload, ...)`. The
    # payload is read back out of the table rather than rebuilt, so a column that stored it
    # wrongly fails here instead of passing.
    assert job == POSTCALL_JOB
    assert await run_post_call_pipeline({}, payload) == "ok"

    async with tenant_session(tenant_id) as session:
        extraction = (
            await session.execute(
                text(
                    "SELECT schema_version, data, valid FROM call_extractions "
                    "WHERE tenant_id = :t AND call_id = :c"
                ),
                {"t": tenant_id, "c": call_row_id},
            )
        ).first()
        turns = (
            await session.execute(
                text(
                    "SELECT count(*) FROM transcript_turns "
                    "WHERE tenant_id = :t AND call_id = :c AND text_redacted IS NOT NULL"
                ),
                {"t": tenant_id, "c": call_row_id},
            )
        ).scalar_one()
    assert extraction is not None, "the pipeline ran but filed no extraction"
    schema_version, data, _valid = extraction
    assert schema_version == 1
    # The agent's OWN fields, so this is the schema-driven extraction reading THIS agent's
    # spec rather than a fixed shape. Both directions, because a subset clause alone is
    # satisfied by `{}` and would tell us nothing: every key must belong to the schema, and
    # at least one must have been filled. Not ALL of them — which of a schema's fields a
    # given transcript supports is the extractor's judgement (the offline extractor fills
    # `intent` from "book an appointment" and declines `name`), and asserting its answer
    # here would make this a test of the extractor rather than of the seam.
    assert data, "the extraction filed no field at all"
    assert set(data) <= {field["key"] for field in CLINIC_SCHEMA}
    assert turns == 2, "the pipeline must not lose the turns the worker already wrote"

    # The call row the client's screen reads, filled by the stage that just ran. Before
    # this change every one of these was NULL on every call this engine handled.
    async with tenant_session(tenant_id) as session:
        summary, sentiment, outcome = (
            await session.execute(
                text(
                    "SELECT summary, sentiment, outcome_tag FROM calls "
                    "WHERE id = :c AND tenant_id = :t"
                ),
                {"c": call_row_id, "t": tenant_id},
            )
        ).one()
    assert (summary, sentiment, outcome) != (None, None, None), (
        "the extraction landed but none of it reached the call row"
    )


# ---------------------------------------------------------------------------------------
# 3. The adapter can find the call at all — the RLS half.
# ---------------------------------------------------------------------------------------


async def test_the_adapter_reads_the_call_back_under_the_tenant_its_id_names() -> None:
    """`get_execution` carries no tenant and `calls` is FORCE-RLS'd. The tenant comes out of
    the engine-space id the sink minted, and nothing else."""
    tenant_id, agent_id = await _seed_tenant()
    call_id = f"call-{uuid.uuid4().hex[:10]}"
    await _run_one_call(tenant_id, agent_id, call_id)

    engine = get_engine(get_settings().model_copy(update={"engine": "pipecat"}))
    snapshot = await engine.get_execution(pipecat_call_ref(tenant_id, call_id))
    assert snapshot.status == "completed"
    assert snapshot.terminal is True
    assert [turn.idx for turn in snapshot.transcript] == [0, 1]
    assert snapshot.engine == "pipecat"
    # The FACTS half stays the carrier's (§1.2). Asserted rather than left implied, because
    # a snapshot that started inventing a cost would silently double-meter the call: the
    # worker already wrote its `usage_events` rows at settlement.
    assert snapshot.cost is None
    assert snapshot.billable_ready is False


async def test_a_call_id_this_engine_never_minted_is_reported_as_no_record() -> None:
    """A bare uuid, or another engine's execution id, resolves to no tenant. The adapter
    must say "no record of that call" and must never guess one (hard rule 1)."""
    from apps.api.core.errors import ProblemError

    engine = get_engine(get_settings().model_copy(update={"engine": "pipecat"}))
    with pytest.raises(ProblemError):
        await engine.get_execution(str(uuid.uuid4()))
