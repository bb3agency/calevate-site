"""Audit of the post-call pipeline, the reconciliation poller and the retention workers.

Every case here started life as a FAILING test against the code as found — the ones that
passed first time are marked "holds" in their docstring and stay as regression guards.

Scope discipline (other suites share this database): every test creates its own tenant
and asserts only on rows it created. Nothing here counts globally.

Fixtures come from the two existing suites rather than a new harness:
`_seed_tenant` (smoke) builds the tenant/agent/route/schema an engine event needs;
`_tenant_with_old_call` (retention) builds a tenant that has real retention policies.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.core.errors import ProblemError
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.workers import pipeline
from apps.workers.extraction import extract_call
from apps.workers.pipeline import (
    _meter,
    ingest_engine_event,
    reconcile_executions,
    run_post_call_pipeline,
)
from apps.workers.retention import _apply_one, apply_retention, execute_deletion_request
from arq import Retry
from calevate_shared.extraction import ExtractionOutput, ExtractionSchemaSpec
from sqlalchemy import text
from tests.conftest import FakeS3, untenanted_session

# The real-arq-worker harness, imported rather than copied: it is the only way to count
# the attempts arq ACTUALLY made, and a second copy of it would be a second thing to get
# subtly wrong (see its own docstring).
from tests.ingest_ordering_test import _run_to_exhaustion
from tests.retention_test import _tenant_with_old_call
from tests.smoke_pipeline_test import _seed_tenant


@pytest.fixture(autouse=True)
def _stub_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same substitution the smoke test makes: a bucket is an environment concern."""

    async def _fake_copy(*, source_url: str, tenant_id: uuid.UUID, call_id: uuid.UUID) -> str:
        return f"recordings/{tenant_id}/{call_id}.wav"

    monkeypatch.setattr("apps.workers.pipeline.copy_recording", _fake_copy)


# --- helpers ------------------------------------------------------------------


async def _completed_call(label: str, *, caller: str | None = None) -> tuple[UUID, str, UUID]:
    """A provisioned tenant with one completed inbound call already ingested.

    Returns (tenant_id, execution_id, call_id). The pipeline has NOT run yet.
    """
    agent_ref = f"fakeagent_{label}_{uuid.uuid4().hex[:8]}"
    tenant_id, _agent_id = await _seed_tenant(agent_ref)
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    get_engine().seed_inbound_call(  # type: ignore[attr-defined]
        call_id=execution_id,
        agent_ref=agent_ref,
        from_e164=caller or f"+9198{uuid.uuid4().int % 100000000:08d}",
        to_e164="+911140000000",
    )
    await ingest_engine_event(
        {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
    )
    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :e"), {"e": execution_id}
            )
        ).scalar()
    return tenant_id, execution_id, UUID(str(call_id))


async def _run_pipeline(tenant_id: UUID, call_id: UUID, execution_id: str) -> None:
    await run_post_call_pipeline(
        {},
        {
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )


async def _scalar(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).scalar()


async def _subscribe_crm_endpoint(tenant_id: UUID) -> UUID:
    """A client CRM subscribed to call.completed (D-23) — the outbound edge of the pipeline."""
    endpoint_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, events, active, "
                "created_at, updated_at) VALUES (:id, :tid, 'webhook', "
                "'https://crm.example.invalid/hook', ARRAY['call.completed'], true, now(), now())"
            ),
            {"id": endpoint_id, "tid": tenant_id},
        )
    return endpoint_id


async def _outbox_rows(job: str, matcher: dict[str, Any]) -> list[dict[str, Any]]:
    """Outbox rows for one job whose payload contains `matcher` — the durable record of
    what the pipeline promised to send."""
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload @> CAST(:matcher AS jsonb)"
                ),
                {"job": job, "matcher": json.dumps(matcher)},
            )
        ).all()
    return [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]


# --- the poller is the source of truth, the webhook is a hint (TRD §5, D-31) ----


async def test_reconciliation_leaves_a_settled_call_alone() -> None:
    """The poller's "is there anything left to do?" probe must actually be able to SEE
    the call.

    `calls` is FORCE-RLS'd, so a probe on an untenanted session returns zero rows for
    every execution ever placed — and the poller then re-drives the entire 30-minute
    window on every tick, reporting each healthy call as a repair.
    """
    reset_engine_cache()
    tenant_id, execution_id, call_id = await _completed_call("recon")
    await _run_pipeline(tenant_id, call_id, execution_id)

    enqueued: list[tuple[str, dict[str, Any]]] = []

    async def _capture(job: str, *args: Any, job_id: str | None = None, **kw: Any) -> str | None:
        payload = args[0] if args and isinstance(args[0], dict) else {}
        enqueued.append((job, payload))
        return job_id

    import apps.workers.pipeline as pipeline_module

    original = pipeline_module.enqueue
    pipeline_module.enqueue = _capture  # type: ignore[assignment]
    try:
        await reconcile_executions({})
    finally:
        pipeline_module.enqueue = original  # type: ignore[assignment]

    redriven = [p.get("execution_id") for _job, p in enqueued]
    assert execution_id not in redriven, (
        "a completed call the pipeline already finished must not be re-driven by the poller"
    )


async def test_a_late_hint_cannot_un_complete_a_call_the_fetch_already_resolved() -> None:
    """HOLDS. Webhook and poller disagreeing: the authenticated fetch wins and a status
    already terminal never walks backwards."""
    tenant_id, execution_id, call_id = await _completed_call("late")
    await _run_pipeline(tenant_id, call_id, execution_id)
    usage_before = await _scalar(
        tenant_id, "SELECT count(*) FROM usage_events WHERE call_id = :c", c=call_id
    )

    engine = get_engine()
    engine._calls[execution_id]["status"] = "ringing"  # type: ignore[attr-defined]
    result = await ingest_engine_event(
        {}, {"engine": "fake", "execution_id": execution_id, "status": "ringing"}
    )

    assert result.startswith("awaiting_completion")
    assert await _scalar(tenant_id, "SELECT status FROM calls WHERE id = :c", c=call_id) == (
        "completed"
    )
    assert (
        await _scalar(tenant_id, "SELECT count(*) FROM usage_events WHERE call_id = :c", c=call_id)
        == usage_before
    )


# --- every step is idempotent and re-runnable ---------------------------------


async def test_a_re_run_does_not_duplicate_the_extraction_row() -> None:
    """A webhook that arrives after the poller already resolved the call re-enters the
    pipeline. `call_extractions` has no unique key, so a plain INSERT files a second
    extraction for the same call — two answers, no way to tell which the CRM read."""
    tenant_id, execution_id, call_id = await _completed_call("dupex")
    await _run_pipeline(tenant_id, call_id, execution_id)
    await _run_pipeline(tenant_id, call_id, execution_id)

    count = await _scalar(
        tenant_id, "SELECT count(*) FROM call_extractions WHERE call_id = :c", c=call_id
    )
    assert count == 1, "one call has one extraction, however many times the pipeline runs"


async def test_a_re_run_does_not_inflate_the_lead_or_its_history() -> None:
    """`call_count` drives the repeat-caller context injection (FLOWS §3). A re-run of
    the SAME call must not make a first-time caller look like a returning one, and must
    not file the call twice on the lead's timeline."""
    tenant_id, execution_id, call_id = await _completed_call("dupelead")
    await _run_pipeline(tenant_id, call_id, execution_id)
    await _run_pipeline(tenant_id, call_id, execution_id)

    async with tenant_session(tenant_id) as session:
        lead = (
            await session.execute(
                text("SELECT id, call_count, is_repeat_caller FROM leads WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).first()
        assert lead is not None
        events = (
            await session.execute(
                text(
                    "SELECT count(*) FROM lead_events WHERE lead_id = :l AND type = 'call' "
                    "AND payload->>'call_id' = :c"
                ),
                {"l": lead[0], "c": str(call_id)},
            )
        ).scalar()

    assert lead[1] == 1, "one call is one call, however many times the pipeline runs"
    assert lead[2] is False, "a single call does not make a repeat caller"
    assert events == 1, "the lead timeline records the call once"


async def test_a_genuine_second_call_still_counts_as_a_repeat_caller() -> None:
    """HOLDS (and guards the fix above from over-correcting): two DIFFERENT calls from
    the same number are two calls and do flip `is_repeat_caller`."""
    caller = f"+9198{uuid.uuid4().int % 100000000:08d}"
    tenant_id, execution_id, call_id = await _completed_call("repeat", caller=caller)
    await _run_pipeline(tenant_id, call_id, execution_id)

    async with tenant_session(tenant_id) as session:
        agent_ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()

    second_exec = f"exec_{uuid.uuid4().hex[:12]}"
    get_engine().seed_inbound_call(  # type: ignore[attr-defined]
        call_id=second_exec, agent_ref=str(agent_ref), from_e164=caller, to_e164="+911140000000"
    )
    await ingest_engine_event(
        {}, {"engine": "fake", "execution_id": second_exec, "engine_agent_ref": str(agent_ref)}
    )
    second_call_id = await _scalar(
        tenant_id, "SELECT id FROM calls WHERE engine_call_id = :e", e=second_exec
    )
    await _run_pipeline(tenant_id, UUID(str(second_call_id)), second_exec)

    async with tenant_session(tenant_id) as session:
        lead = (
            await session.execute(
                text("SELECT call_count, is_repeat_caller FROM leads WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).first()
    assert lead is not None
    assert lead[0] == 2
    assert lead[1] is True


async def test_a_re_run_does_not_deliver_the_crm_event_twice() -> None:
    """Step 8 mints a NEW delivery id per run, so a receiver deduplicating on it cannot
    collapse the copies — a re-run is a second `call.completed` POST at the client."""
    tenant_id, execution_id, call_id = await _completed_call("crmdup")
    await _subscribe_crm_endpoint(tenant_id)
    await _run_pipeline(tenant_id, call_id, execution_id)
    await _run_pipeline(tenant_id, call_id, execution_id)

    rows = await _outbox_rows("deliver_outbound_webhook", {"data": {"call_id": str(call_id)}})
    assert len(rows) == 1, "one completed call is one outbound event, not one per pipeline run"


async def test_a_re_run_does_not_queue_the_hot_lead_notification_twice() -> None:
    """The notification worker dedupes on its own lead_event, so this is about the
    OUTBOX row: a second promise to notify is a promise we never meant to make."""
    tenant_id, execution_id, call_id = await _completed_call("hotdup")
    await _run_pipeline(tenant_id, call_id, execution_id)
    await _run_pipeline(tenant_id, call_id, execution_id)

    rows = await _outbox_rows("notify_hot_lead", {"call_id": str(call_id)})
    assert len(rows) == 1, "the sample call is a hot lead exactly once"


# --- money (hard rule 7) -------------------------------------------------------


async def test_the_usage_ledger_reconstructs_what_the_call_actually_cost() -> None:
    """`unit_cost_paid` is a PRICE PER UNIT of `qty` — that is what the column is named,
    what billing_surfaces_test seeds, and what `margin_for_tenant` multiplies.

    Writing each leg's TOTAL there instead makes SUM(qty * unit_cost_paid) report ~50x
    our real cost for a 95-second call, and drops the TTS and LLM legs entirely because
    their qty is zero.
    """
    tenant_id, execution_id, call_id = await _completed_call("money")
    snapshot = await get_engine().get_execution(execution_id)
    assert snapshot.cost is not None
    expected = snapshot.cost.total_inr

    await _run_pipeline(tenant_id, call_id, execution_id)

    async with tenant_session(tenant_id) as session:
        recorded = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(qty * COALESCE(unit_cost_paid, 0)), 0) "
                    "FROM usage_events WHERE call_id = :c"
                ),
                {"c": call_id},
            )
        ).scalar()
        legs = (
            await session.execute(
                text("SELECT unit_type, qty, unit_cost_paid FROM usage_events WHERE call_id = :c"),
                {"c": call_id},
            )
        ).all()

    recorded_inr = Decimal(str(recorded))
    assert all(isinstance(qty, Decimal) for _u, qty, _c in legs), "money and qty are NUMERIC"
    assert all(cost is None or isinstance(cost, Decimal) for _u, _q, cost in legs)
    # 4-decimal unit prices cannot divide exactly; 1% is the rounding envelope.
    assert abs(recorded_inr - expected) <= expected / 100, (
        f"ledger reconstructs {recorded_inr} for a call that cost {expected}"
    )


async def test_spend_state_counts_the_call_in_its_ist_billing_month() -> None:
    """Caps are enforced pre-dispatch off `spend_state` (TRD §9) while the invoice reads
    the IST month (billing `_IST_MONTH`). A UTC month boundary puts every call between
    00:00 and 05:30 IST on the 1st into the wrong month — the counter and the invoice
    then disagree, and a capped tenant stays capped 5.5 hours into the new month."""
    tenant_id, execution_id, call_id = await _completed_call("month")
    snapshot = await get_engine().get_execution(execution_id)
    # 2026-04-01 01:00 IST — the same instant is still March in UTC.
    ended = datetime(2026, 3, 31, 19, 30, tzinfo=UTC)
    ist_new_year = snapshot.model_copy(update={"ended_at": ended})

    await _meter(tenant_id, call_id, ist_new_year)

    month = await _scalar(
        tenant_id, "SELECT month FROM spend_state WHERE tenant_id = :t", t=tenant_id
    )
    assert month == "2026-04", "spend_state counts in the IST month the invoice bills in"


# --- redaction happens before anything leaves (hard rule 5, SEC-COMP §4) -------


async def test_a_redaction_failure_never_leaves_raw_text_as_the_only_copy() -> None:
    """HOLDS. If the redaction pass dies mid-transcript the whole write must roll back
    and the job must raise so ARQ retries — never a row with `text` and no
    `text_redacted`, which is what every API response returns by default."""
    tenant_id, execution_id, call_id = await _completed_call("redactfail")

    def _explode(value: str) -> Any:
        if "9876543210" in value:
            raise RuntimeError("redaction backend unavailable")
        from apps.workers.redaction import redact as real_redact

        return real_redact(value)

    import apps.workers.pipeline as pipeline_module

    original = pipeline_module.redact
    pipeline_module.redact = _explode  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError):
            await _run_pipeline(tenant_id, call_id, execution_id)
    finally:
        pipeline_module.redact = original  # type: ignore[assignment]

    async with tenant_session(tenant_id) as session:
        raw_only = (
            await session.execute(
                text(
                    "SELECT count(*) FROM transcript_turns WHERE call_id = :c "
                    "AND text_redacted IS NULL"
                ),
                {"c": call_id},
            )
        ).scalar()
    assert raw_only == 0, "no turn may exist with raw text and no redacted copy"


async def test_the_crm_event_never_carries_an_unredacted_summary() -> None:
    """SEC-COMP §4: redaction runs BEFORE any transcript leaves our system. The summary
    is transcript-derived — with the offline extractor it is a transcript line verbatim
    — and step 8 posts it to a third-party CRM. The notification path already redacts
    it (`notifications._compose`); the webhook path must too."""
    tenant_id, execution_id, call_id = await _completed_call("crmpii")
    await _subscribe_crm_endpoint(tenant_id)

    async def _leaky_extraction(*_args: Any, **_kw: Any) -> ExtractionOutput:
        return ExtractionOutput(
            data={"intent": "book"},
            summary="Caller Ravi asked us to call 9876543210 back about a booking.",
            sentiment="neutral",
            outcome_tag="needs_follow_up",
        )

    import apps.workers.pipeline as pipeline_module

    original = pipeline_module.extract_call
    pipeline_module.extract_call = _leaky_extraction  # type: ignore[assignment]
    try:
        await _run_pipeline(tenant_id, call_id, execution_id)
    finally:
        pipeline_module.extract_call = original  # type: ignore[assignment]

    rows = await _outbox_rows("deliver_outbound_webhook", {"data": {"call_id": str(call_id)}})
    assert rows, "the endpoint is subscribed to call.completed"
    summary = str(rows[0]["data"]["summary"])
    assert "9876543210" not in summary, "a phone number must not leave on an outbound webhook"
    assert "booking" in summary, "redaction is targeted, not a blanket wipe"


# --- a model failure costs the fields, never the call (TRD §7) ----------------


async def test_a_malformed_model_response_does_not_fail_the_whole_call() -> None:
    """Both adapters index into the provider's response — `choices[0]`, `candidates[0]`
    — and both come back EMPTY in ordinary operation (filtered content on Sarvam, a
    safety block on Gemini). The resulting IndexError walked straight past the error
    ladder, so a provider declining to answer failed the post-call job, and after three
    ARQ retries the call had no lead and no usage row at all."""

    class DecliningProvider:
        model_name = "test-declining"

        async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
            raise IndexError("list index out of range")

    spec = ExtractionSchemaSpec(version=1, fields=[])
    outcome = await extract_call(spec, "naaku appointment kavali", extractor=DecliningProvider())

    assert outcome.valid is False
    assert outcome.errors, "the failure is recorded on the extraction, not raised at the pipeline"


# --- retention and erasure actually erase (SEC-COMP §4, FLOWS §9) -------------


async def test_a_policy_below_the_trai_floor_cannot_delete_a_recording_early() -> None:
    """HOLDS. The 90-day floor is enforced twice — a DB CHECK on `retention_policies`
    and the clamp in the job — because deleting early is the violation that cannot be
    undone. This drives the job's half directly, with a TTL the CHECK would refuse."""
    tenant_id, call_id = await _tenant_with_old_call(30, "+919876511005")
    async with tenant_session(tenant_id) as session:
        await _apply_one(
            session, tenant_id=tenant_id, category="recording", ttl_days=1, action="delete"
        )

    url = await _scalar(tenant_id, "SELECT recording_url FROM calls WHERE id = :c", c=call_id)
    assert url == "recordings/x.wav", "a 30-day-old recording survives a 1-day policy"


async def test_a_lead_with_no_captured_name_still_ages_out() -> None:
    """The lead sweep skips rows where `name IS NULL` — but a lead whose name the caller
    never gave still carries their phone number and every extracted field. Those are the
    rows the TTL exists for, and they were living forever."""
    phone = "+919876511001"
    tenant_id, _call_id = await _tenant_with_old_call(1200, phone)
    nameless_phone = "+919876511002"
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(
                text("SELECT id FROM agents WHERE tenant_id = :t LIMIT 1"), {"t": tenant_id}
            )
        ).scalar()
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, created_at, updated_at) VALUES (:i, :t, :a, :p, NULL, 'inbound_call', "
                '\'new\', \'{"intent": "book", "symptom": "fever"}\'::jsonb, :w, :w)'
            ),
            {
                "i": uuid.uuid4(),
                "t": tenant_id,
                "a": agent_id,
                "p": nameless_phone,
                "w": datetime(2020, 1, 1, tzinfo=UTC),
            },
        )

    await apply_retention({})

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT phone_e164, data FROM leads WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).all()
    assert rows
    for stored_phone, data in rows:
        assert nameless_phone not in stored_phone and phone not in stored_phone
        assert not data, "extracted fields go with the phone number"


async def test_retention_still_runs_for_a_soft_deleted_tenant(s3: FakeS3) -> None:
    """FLOWS §9: churn STARTS the retention countdown. Skipping soft-deleted
    organizations stops the sweep for exactly the tenant whose data must age out.

    Takes the `s3` fixture since D-115. The sweep destroys the OBJECT and only then clears
    the reference, and when object storage is unreachable it deliberately defers rather
    than dropping the only handle on the bytes — so without a store this test was asserting
    the deferral, not the sweep. Both halves are asserted now: an offboarded tenant's audio
    is destroyed AND its pointer cleared, which is what "expire on schedule" was always
    supposed to mean.
    """
    tenant_id, call_id = await _tenant_with_old_call(200, "+919876511003")
    key = await _scalar(tenant_id, "SELECT recording_url FROM calls WHERE id = :c", c=call_id)
    assert key, "the fixture must give the sweep something to destroy"
    s3.objects[str(key)] = b"audio"

    async with tenant_session(tenant_id) as session:
        await session.execute(
            # `status = 'churned'` in the same statement, because `deleted_at` is not a
            # free-standing flag: `ck_organizations_deleted_implies_churned` (D-122) makes
            # an erased tenant always a churned one, which is what lets the readers of the
            # column filter on different halves of "account closed" and still agree. The
            # real writer (`workers/retention.execute_tenant_erasure`) refuses to run at
            # all unless the account is already churned, so this fixture is now producing
            # a state the product can actually reach rather than one only a test could.
            text("UPDATE organizations SET deleted_at = now(), status = 'churned' WHERE id = :t"),
            {"t": tenant_id},
        )

    await apply_retention({})

    url = await _scalar(tenant_id, "SELECT recording_url FROM calls WHERE id = :c", c=call_id)
    assert url is None, "an offboarded tenant's recordings still expire on schedule"
    assert str(key) not in s3.objects, (
        "the pointer was cleared and the audio kept — the defect D-115 closed, back on "
        "the one tenant whose data must age out"
    )


async def test_erasure_also_clears_the_extracted_copy_of_the_person() -> None:
    """DPDP erasure has to reach the DERIVED copies. `call_extractions.data` is the
    caller's name, symptom and callback number in structured form — the proof claimed
    the person was gone while that row still held them."""
    phone = "+919876511004"
    tenant_id, call_id = await _tenant_with_old_call(10, phone)
    request_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO call_extractions (id, tenant_id, call_id, schema_version, data, "
                "valid, created_at, updated_at) VALUES (:i, :t, :c, 1, CAST(:d AS jsonb), true, "
                "now(), now())"
            ),
            {
                "i": uuid.uuid4(),
                "t": tenant_id,
                "c": call_id,
                "d": json.dumps({"name": "Ravi", "callback_number": phone, "symptom": "fever"}),
            },
        )
        await session.execute(
            text(
                "INSERT INTO deletion_requests (id, tenant_id, phone_e164, scope, requested_at, "
                "created_at) VALUES (:i, :t, :p, 'all', now(), now())"
            ),
            {"i": request_id, "t": tenant_id, "p": phone},
        )

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    async with tenant_session(tenant_id) as session:
        data = (
            await session.execute(
                text("SELECT data FROM call_extractions WHERE call_id = :c"), {"c": call_id}
            )
        ).scalar()
        proof = (
            await session.execute(
                text("SELECT proof FROM deletion_requests WHERE id = :i"), {"i": request_id}
            )
        ).scalar()

    assert not data, "the extracted copy of the caller is erased with the rest"
    document = proof if isinstance(proof, dict) else json.loads(proof)
    assert phone not in json.dumps(document)
    assert "call_extractions" in document["actions"], "the proof states what it did"


# --- the pipeline is retried, and a retry cannot bill twice ---------------------
#
# `run_post_call_pipeline` raised plain exceptions everywhere except the recording copy,
# and arq 0.28 finishes a job after ONE attempt on anything that is not `Retry`,
# `RetryJob` or `CancelledError` (`arq/worker.py::run_job`, read at 0.28.0; the same
# sentence is in `WorkerSettings.max_tries`). So one database blip or one engine timeout
# dropped extraction, the lead upsert, metering and the hot-lead alert to manual replay —
# and the reconciliation poller could not recover it, because `ingest_engine_event` had
# already written `status = 'completed'` and the poller's probe skipped on exactly that.
# That probe is `_pipeline_settled` now and asks the wider question — are the artefacts
# this snapshot implies actually present — so the poller DOES recover that shape today.
# The retry ladder below is still the fast path; the poller is the guarantee behind it.
#
# ATTEMPT COUNTS COME FROM A REAL WORKER. A test that writes `ctx["job_try"]` itself can
# only prove that an `if` compares two integers — it cannot notice that arq never calls
# the branch, which is precisely how this survived in the ingest job (`ingest_ordering_test`
# says the same thing, and its harness is reused here rather than copied).


@pytest.fixture
def _fast_ladder(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """The real ladder is 30s then 120s; its SHAPE is what these tests are about, not its
    pace. Returns the alerts fired, because the terminal branch is part of the contract:
    a call abandoned in silence is indistinguishable from a call that never happened."""
    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(pipeline, "RETRY_BACKOFF_S", (0.02, 0.02))
    monkeypatch.setattr(
        pipeline, "alert", lambda stage, code, **kw: fired.append((str(stage), str(code)))
    )
    return fired


class _RefusingEngine:
    """An engine whose authenticated read always fails the same way."""

    name = "fake"

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def get_execution(self, call_id: str) -> Any:
        raise self._exc


async def test_an_engine_blip_gets_the_whole_retry_ladder_on_a_real_worker(
    monkeypatch: pytest.MonkeyPatch, _fast_ladder: list[tuple[str, str]]
) -> None:
    """The fetch at the top of the pipeline was bare. A transport failure there is the
    case that costs a lead: the engine was never asked, so nothing is wrong with the call
    — and without a ladder the whole pipeline is gone for that call."""
    tenant_id, execution_id, call_id = await _completed_call("ladder")
    unreachable = ProblemError(
        kind="dependency",
        code="engine_unreachable",
        title="Voice engine unreachable",
        detail="The voice platform did not respond.",
    )
    monkeypatch.setattr(pipeline, "get_engine", lambda: _RefusingEngine(unreachable))

    attempts = await _run_to_exhaustion(
        pipeline.run_post_call_pipeline,
        {
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )

    assert attempts == WORKER_MAX_TRIES, (
        f"an engine that never answered must get the ladder; the worker ran it {attempts} time(s)"
    )
    assert ("WORKER_TERMINAL", "post_call_abandoned") in _fast_ladder, (
        "the end of the ladder is still a lost lead and has to say so"
    )


async def test_an_execution_the_engine_rejects_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, _fast_ladder: list[tuple[str, str]]
) -> None:
    """The other half of a retry policy: knowing what not to retry. `engine_rejected` is
    the engine ANSWERING — for a re-fetch, overwhelmingly a 404 for an execution it does
    not hold. The same GET fails identically two minutes later, and the ladder buys
    nothing but a later alert and three times the load on a platform already saying no.

    Same split as `ingest_engine_event`, from the same `_is_transient`, because two retry
    policies for one engine is how the two would come to disagree."""
    tenant_id, execution_id, call_id = await _completed_call("verdict")
    rejected = ProblemError(
        kind="dependency",
        code="engine_rejected",
        title="Voice engine rejected the request",
        detail="The voice platform could not complete this operation.",
    )
    monkeypatch.setattr(pipeline, "get_engine", lambda: _RefusingEngine(rejected))

    attempts = await _run_to_exhaustion(
        pipeline.run_post_call_pipeline,
        {
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )

    assert attempts == 1, f"a verdict is not a blip; the worker ran it {attempts} time(s)"
    assert ("WORKER_TERMINAL", "post_call_abandoned") in _fast_ladder


async def test_a_malformed_job_payload_is_not_retried(
    _fast_ladder: list[tuple[str, str]],
) -> None:
    """A payload is fixed for the life of the job: three parses of the same dict fail
    three identical times. It is reported as a `validation` ProblemError so the ONE
    transient/permanent split classifies it, rather than the job growing a second one."""
    attempts = await _run_to_exhaustion(
        pipeline.run_post_call_pipeline, {"engine": "fake", "call_id": "not-a-uuid"}
    )

    assert attempts == 1, f"a broken payload was retried {attempts} times"
    assert ("WORKER_TERMINAL", "post_call_abandoned") in _fast_ladder


async def test_a_retry_after_a_partial_run_does_not_bill_the_call_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE PROOF THE RETRY LADDER RESTS ON, and the reason it is a test and not a claim.

    `usage_events` and `credit_ledger` are INSERT-only (hard rule 4), so a second run
    that meters again cannot be undone — only compensated. This drives the exact shape
    the ladder now creates: a run that gets PAST metering and then fails, followed by a
    retry that completes. If the ledger were not idempotent, this is the test that would
    be red, and the ladder would have to be a poller-side redrive instead.

    The tenant is `self_serve` so the credit debit runs too — a managed tenant is
    invoiced against a retainer and never touches `credit_ledger`, which would have made
    this test prove half of what it says.
    """
    tenant_id, execution_id, call_id = await _completed_call("nodouble")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :t"),
            {"t": tenant_id},
        )

    # Step 6 — AFTER metering, which is what makes this a partial run rather than a
    # no-op. The first attempt dies there; the second is allowed through.
    real_notify = pipeline._maybe_notify_hot_lead
    calls = {"n": 0}

    async def _fail_once(*args: Any, **kwargs: Any) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("a database blip after the ledger was written")
        return await real_notify(*args, **kwargs)

    monkeypatch.setattr(pipeline, "_maybe_notify_hot_lead", _fail_once)
    monkeypatch.setattr(pipeline, "alert", lambda *a, **k: None)

    payload = {
        "tenant_id": str(tenant_id),
        "call_id": str(call_id),
        "engine": "fake",
        "execution_id": execution_id,
    }
    # Attempt 1: a transient failure asks arq for a retry rather than finishing the job.
    with pytest.raises(Retry):
        await pipeline.run_post_call_pipeline({"job_try": 1}, payload)
    metered_once = await _ledger_state(tenant_id, call_id)
    assert metered_once["usage_rows"] > 0, "the partial run must really have metered"

    # Attempt 2: the retry arq would make, completing the job.
    assert await pipeline.run_post_call_pipeline({"job_try": 2}, payload) == "ok"

    assert await _ledger_state(tenant_id, call_id) == metered_once, (
        "the retry billed the call a second time — usage_events and credit_ledger are "
        "INSERT-only, so this is a charge that can only be compensated, never removed"
    )
    assert calls["n"] == 2, "the second attempt really did re-run the stage that failed"


async def _ledger_state(tenant_id: UUID, call_id: UUID) -> dict[str, Any]:
    """Everything a double-run would move: the usage rows, the money on them, the credit
    debit, and the spend counter the cap is enforced against."""
    async with tenant_session(tenant_id) as session:
        usage = (
            await session.execute(
                text(
                    "SELECT count(*), COALESCE(SUM(qty * COALESCE(unit_cost_paid, 0)), 0) "
                    "FROM usage_events WHERE call_id = :c AND tenant_id = :t"
                ),
                {"c": call_id, "t": tenant_id},
            )
        ).first()
        debits = (
            await session.execute(
                text(
                    "SELECT count(*), COALESCE(SUM(delta), 0) FROM credit_ledger "
                    "WHERE ref = :r AND reason = 'usage' AND tenant_id = :t"
                ),
                {"r": str(call_id), "t": tenant_id},
            )
        ).first()
        spend = (
            await session.execute(
                text("SELECT minutes_used, spend_used FROM spend_state WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).first()
    assert usage is not None and debits is not None
    return {
        "usage_rows": int(usage[0]),
        "usage_cost": Decimal(str(usage[1])),
        "credit_rows": int(debits[0]),
        "credit_delta": Decimal(str(debits[1])),
        "minutes_used": Decimal(str(spend[0])) if spend else None,
        "spend_used": Decimal(str(spend[1])) if spend else None,
    }
