"""Stage spans: is the pipeline's interior visible, and does it stay clean?

`tests/tracing_test.py` proves the trace CROSSES the boundaries. This file proves the
trace has an INTERIOR worth crossing to. The distinction matters because a trace that
survives every hop and then shows one flat four-minute worker span answers the SLO
question ("lead visible within 2 minutes of hangup", OPERATIONS §5) with "yes, it was
late" — which is the thing the metric already told us.

Three claims, in the order they matter:

1. **The leak claim.** A stage span is an attribute-bearing object created inside the
   one function that handles a transcript and a caller's number. Seed both through the
   real pipeline and read back every byte of every exported span: neither appears.
   `test_the_leak_detector_bites` is here so that claim cannot pass vacuously — it
   bypasses `sanitize_attributes` once and asserts the same detector DOES find the leak.
2. **The nesting claim.** A stage span that is not a child of the job span is a span
   nobody will find: trace backends render the tree, and an orphan sorts to the bottom
   of a list of root spans in a different service. So parentage is asserted, not the
   mere existence of a name.
3. **The budget claim** (hard rule 3). The voice-runtime receiver got two new spans and
   one new attribute. With no collector configured every one of them must cost a module
   global read, and "must" is measured here rather than asserted in a comment.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import pytest
from apps.api.core import observability
from apps.api.core.observability import (
    current_trace_id,
    dropped_attribute_keys,
    init_tracing,
    reset_tracing,
    span,
    traced_job,
    tracing_enabled,
)
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.workers.pipeline import ingest_engine_event, run_post_call_pipeline
from fastapi import Response
from httpx import ASGITransport, AsyncClient
from main import app as voice_app  # apps/voice-runtime is on the pytest path (D-18)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# The same two values `tracing_test.py` and `observability_security_test.py` are pinned
# against — one definition of what a leak looks like, deliberately. `PHONE` is also the
# number the fake engine's sample transcript says out loud (`fake.SAMPLE_TURNS`), so the
# transcript half of this test is the product's own fixture rather than a plant.
PHONE = "9876543210"
E164 = f"+91{PHONE}"
TRANSCRIPT = "caller: naa number 9876543210, naa peru Ravi"

# The stage spans this file is about. Names, not a count: a renamed span is a dashboard
# and an alert that quietly stop matching, which is worth failing a test over.
PIPELINE_STAGES = (
    # The only stage that waits on a THIRD PARTY's network, so it owns the missing
    # minutes more often than anything below it — and its `outcome` attribute is how an
    # operator tells "fetched the audio" from "we already had it" on a re-drive.
    "pipeline.recording_copy",
    "pipeline.transcript_persist",
    "pipeline.extract",
    "pipeline.extraction_persist",
    "pipeline.lead_upsert",
    "pipeline.meter",
    "pipeline.notify_hot_lead",
)

CLINIC_SCHEMA: list[dict[str, Any]] = [
    {"key": "name", "label": "Caller name", "type": "text", "description": "who is calling"},
    {
        "key": "intent",
        "label": "Intent",
        "type": "enum",
        "enum_values": ["book", "reschedule", "enquiry"],
        "description": "what they want",
    },
    {
        "key": "urgency",
        "label": "Urgency",
        "type": "enum",
        "enum_values": ["routine", "urgent", "emergency"],
        "description": "how soon they need it",
    },
]


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Tracing on, exporting into memory. Ratio forced to 1.0: the production default is
    0.1 and a test that passes 10% of the time is worse than no test."""
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    monkeypatch.setenv("OTEL_TRACES_SAMPLE_RATIO", "1.0")
    get_settings.cache_clear()
    reset_tracing()
    exporter = InMemorySpanExporter()
    assert init_tracing("test", span_exporter=exporter) is True
    assert tracing_enabled() is True
    try:
        yield exporter
    finally:
        observability.shutdown_tracing()
        reset_tracing()
        monkeypatch.undo()
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _stub_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Object storage needs a bucket; the recording copy is not what this file measures."""

    async def _fake_copy(*, source_url: str, tenant_id: uuid.UUID, call_id: uuid.UUID) -> str:
        return f"recordings/{tenant_id}/{call_id}.wav"

    monkeypatch.setattr("apps.workers.pipeline.copy_recording", _fake_copy)


def finished(exporter: Any) -> list[Any]:
    """BatchSpanProcessor is asynchronous by design (it must never add latency to an
    ack), so nothing is readable without a flush."""
    observability._provider.force_flush()
    return list(exporter.get_finished_spans())


def dump(exporter: Any) -> str:
    """Every exported span serialized WHOLE — name, attributes, resource, events, status.

    Not a walk over the attributes we happen to remember: a leak that arrives through a
    span name or an exception message is still a leak, and this is the assertion that
    catches the case nobody predicted.
    """
    return "\n".join(readable.to_json() for readable in finished(exporter))


def by_name(exporter: Any, name: str) -> list[Any]:
    return [s for s in finished(exporter) if s.name == name]


async def _seed_tenant(engine_agent_ref: str) -> tuple[uuid.UUID, uuid.UUID]:
    """An org + agent + extraction schema, exactly as the admin wizard would write them.

    Its own fresh tenant id per test: other agents run pytest against the same Postgres,
    and every read below is tenant-scoped so this cannot see — or be seen by — theirs.
    """
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    schema_id = uuid.uuid4()

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Trace Clinic', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": f"trace-{tenant_id.hex[:10]}"},
        )
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, status, "
                "engine, engine_agent_ref, created_at, updated_at) VALUES (:id, :tid, "
                "'Receptionist', 'inbound', 'Idi AI assistant. Call record avutundi.', 'live', "
                "'fake', :ref, now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id, "ref": engine_agent_ref},
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

    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                "agent_id, active, created_at, updated_at) VALUES ('fake', :ref, :tid, :aid, "
                "true, now(), now()) ON CONFLICT (engine, engine_agent_ref) DO UPDATE SET "
                "tenant_id = EXCLUDED.tenant_id, agent_id = EXCLUDED.agent_id, active = true"
            ),
            {"ref": engine_agent_ref, "tid": tenant_id, "aid": agent_id},
        )
    return tenant_id, agent_id


async def _run_traced_pipeline(
    execution_id: str, agent_ref: str, tenant_id: uuid.UUID
) -> uuid.UUID:
    """Ingest + pipeline, wrapped exactly as `apps/workers/settings.py` wraps them.

    `traced_job` is applied here rather than calling the bare functions because the job
    span is the parent the stage spans are supposed to hang off — calling the bare
    function would leave them parented to whatever the test happened to be inside, and
    the nesting assertion would then be testing the test.
    """
    reset_engine_cache()
    engine = get_engine()
    engine.seed_inbound_call(  # type: ignore[attr-defined]
        call_id=execution_id, agent_ref=agent_ref, from_e164=E164, to_e164="+911140000000"
    )

    result = await traced_job(ingest_engine_event)(
        {"job_id": f"ingest:{execution_id}", "job_try": 1},
        {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref},
    )
    assert result == "pipeline_enqueued"

    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :e"), {"e": execution_id}
            )
        ).scalar()
    assert call_id is not None

    await traced_job(run_post_call_pipeline)(
        {"job_id": f"postcall:{call_id}", "job_try": 1},
        {
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )
    return uuid.UUID(str(call_id))


# --- 1. The leak (the test that matters) --------------------------------------


async def test_no_phone_or_transcript_reaches_the_trace_from_the_real_pipeline(
    spans: Any,
) -> None:
    """A real call, with a real caller id and the fake engine's real spoken-number
    transcript, driven through the real traced pipeline. Then read back every byte.

    The pipeline is the worst case for hard rule 6 and the reason the stage spans needed
    a test of their own: `pipeline.extract` sits around the function that HOLDS the
    transcript, `pipeline.lead_upsert` sits around the one that writes the caller's
    number to Postgres, and both bind that number as a SQL parameter inside their own
    child DB spans.
    """
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    agent_ref = "fakeagent_trace_" + uuid.uuid4().hex[:8]
    tenant_id, _agent_id = await _seed_tenant(agent_ref)

    call_id = await _run_traced_pipeline(execution_id, agent_ref, tenant_id)

    exported = dump(spans)
    assert exported, "nothing was exported — this test would pass vacuously"
    for forbidden in (PHONE, E164, TRANSCRIPT, "Ravi", "naa peru", "appointment"):
        assert forbidden not in exported, f"{forbidden!r} reached the trace backend"

    # Positively: the stage spans DID run and DID carry their ids, so the absence above
    # is a filtered trace and not an empty one.
    extract_spans = by_name(spans, "pipeline.extract")
    assert extract_spans, "the extract stage produced no span"
    assert extract_spans[0].attributes["call_id"] == str(call_id)
    assert extract_spans[0].attributes["field_count"] == len(CLINIC_SCHEMA)
    # The transcript's SIZE, never its text — the number an operator needs to tell a
    # slow model from a long call.
    assert extract_spans[0].attributes["input_bytes"] > 0

    # And our own call sites are honest: none of the attributes THIS change added was
    # saved by the allowlist. The filter is a backstop here, not the thing keeping the
    # pipeline clean.
    dropped = dropped_attribute_keys()
    for key in ("call_id", "lead_id", "turn_count", "field_count", "input_bytes"):
        assert key not in dropped, f"a stage span tried to ship {key} and was refused"


async def test_the_leak_detector_bites(spans: Any) -> None:
    """Proof the assertion above is not vacuous.

    `dump()` + a substring scan is only evidence if it can FAIL. So bypass
    `sanitize_attributes` once — the exact regression a future call site would cause by
    reaching a vendor SDK directly — and assert the same detector finds the transcript.
    The bypass is undone by the fixture's `monkeypatch`, so it cannot outlive this test.

    The flush happens INSIDE the bypass because attributes are now filtered twice, once
    where they are set and once in `_RedactingSpanExporter` — which is the point of the
    export filter, and which means a plant that is not exported while the bypass is up
    gets cleaned on its way out and proves nothing.
    """
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(observability, "sanitize_attributes", lambda attributes: dict(attributes))
        with span("pipeline.extract", transcript_text=TRANSCRIPT, caller_phone=E164):
            pass
        observability._provider.force_flush()
    finally:
        monkey.undo()

    leaked = dump(spans)
    assert TRANSCRIPT in leaked, "the detector cannot see a leak, so it proves nothing"
    assert E164 in leaked

    # Sanitisation restored: the same call site is clean again, which is what makes the
    # bypass above a measurement rather than a hole left behind.
    assert observability.sanitize_attributes({"transcript_text": TRANSCRIPT}) == {}


# --- 2. The nesting -----------------------------------------------------------


async def test_every_stage_span_is_a_child_of_its_job_span(spans: Any) -> None:
    """A stage span that is not a child is a span nobody will find.

    Trace backends render a tree; an orphan sorts to the bottom of a list of unrelated
    roots. So this asserts parentage and one trace id, not the existence of a name.
    """
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    agent_ref = "fakeagent_nest_" + uuid.uuid4().hex[:8]
    tenant_id, _agent_id = await _seed_tenant(agent_ref)
    await _run_traced_pipeline(execution_id, agent_ref, tenant_id)

    postcall = by_name(spans, "job run_post_call_pipeline")
    assert postcall, "the post-call job produced no span"
    job = postcall[0]

    for name in PIPELINE_STAGES:
        stage_spans = by_name(spans, name)
        assert stage_spans, f"{name} is missing — that stage is still invisible"
        stage = stage_spans[0]
        assert stage.parent is not None, f"{name} is a ROOT span, not a stage of the job"
        assert stage.parent.span_id == job.context.span_id, (
            f"{name} is not a child of the job span — it will not appear under the trace"
        )
        assert stage.context.trace_id == job.context.trace_id

    # The call upsert belongs to the INGEST job, which is a different job in the same
    # trace: it runs before the pipeline is even enqueued.
    ingest = by_name(spans, "job ingest_engine_event")
    assert ingest, "the ingest job produced no span"
    upsert = by_name(spans, "pipeline.call_upsert")
    assert upsert, "the call upsert is still invisible"
    assert upsert[0].parent is not None
    assert upsert[0].parent.span_id == ingest[0].context.span_id


async def test_the_slo_metric_and_the_trace_join_on_the_job_span(spans: Any) -> None:
    """`record_pipeline_lag` fires on 100% of calls and says the 2-minute budget was
    missed; the trace is sampled at 10% and says where the time went. Without the same
    number on both, an operator holding a breached metric has no way to ask the trace
    backend for the traces that belong to breaches."""
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    agent_ref = "fakeagent_lag_" + uuid.uuid4().hex[:8]
    tenant_id, _agent_id = await _seed_tenant(agent_ref)
    call_id = await _run_traced_pipeline(execution_id, agent_ref, tenant_id)

    job = by_name(spans, "job run_post_call_pipeline")[0]
    assert "pipeline_lag_ms" in job.attributes, "the SLO number never reached the trace"
    assert job.attributes["pipeline_lag_ms"] > 0
    assert job.attributes["call_id"] == str(call_id), "no call id to pivot the metric on"

    # The stages must account for the job, not float beside it: every stage span has to
    # fit inside the job's own window or the flame graph is lying about causality.
    for name in PIPELINE_STAGES:
        stage = by_name(spans, name)[0]
        assert stage.start_time >= job.start_time
        assert stage.end_time <= job.end_time


# --- 3. The voice-runtime budget (hard rule 3) --------------------------------


async def test_the_receiver_answers_identically_with_no_collector_configured() -> None:
    """No `spans` fixture, so tracing is OFF — the shape every deploy without a
    collector, and every other test run, actually has. The instrumentation must be
    invisible: same status, same body keys, same headers, still inside the budget."""
    reset_tracing()
    assert tracing_enabled() is False

    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    async with AsyncClient(transport=ASGITransport(app=voice_app), base_url="http://rt") as client:
        response = await client.post(
            "/hooks/v1/engine/fake",
            json={"execution_id": execution_id, "status": "completed", "agent_id": "agent_trace"},
        )

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "accepted"
    assert "X-Ack-Ms" in response.headers
    assert float(response.headers["X-Ack-Ms"]) < 500, "hard rule 3's number"


async def test_the_ack_time_lands_on_the_request_span_that_carries_the_claim(
    spans: Any,
) -> None:
    """The ack being slow is a metric. "The ack was slow AND its inbox claim took 480ms
    of it" is the thing an operator can act on — and it needs both halves on ONE trace.

    So with tracing on, `_ack` must find the request's own span and stamp the measured
    ack onto it, above the `webhook.inbox_claim` child that accounts for the Postgres
    round trip. If it stamped a fresh span of its own instead, the two numbers would sit
    in different traces and the only question worth asking (where did the 480ms go?)
    would need a human to join them by timestamp.

    The number stamped must be the SAME number the caller was handed in `X-Ack-Ms`, not
    a second measurement taken later: an operator comparing a vendor's timing complaint
    against our trace is comparing exactly those two values.

    WHICH span carries it is deliberately NOT asserted by name. `_server_span` reads
    whatever the ASGI stack made current — `TracingMiddleware`'s server span in a
    deployment with a collector, and here the client span the request is issued under,
    because `main.app` was built at import time when tracing was off and the middleware
    is therefore not in this chain. Pinning a name would pin the harness. What must hold
    is the property: the ack is stamped ONCE, on a span in the SAME TRACE as the claim.
    """
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    with span("http.request", kind="server"):
        async with AsyncClient(
            transport=ASGITransport(app=voice_app), base_url="http://rt"
        ) as client:
            response = await client.post(
                "/hooks/v1/engine/fake",
                json={"execution_id": execution_id, "status": "completed"},
            )
    assert response.status_code == 202, response.text

    exported = finished(spans)
    claim = [s for s in exported if s.name == "webhook.inbox_claim"]
    assert len(claim) == 1, "the claim child is half of the pair"
    acked = [s for s in exported if "ack_ms" in (s.attributes or {})]
    assert len(acked) == 1, f"the ack belongs on exactly one span, got {[s.name for s in acked]}"

    assert acked[0].context.trace_id == claim[0].context.trace_id, (
        "an ack in a different trace from its claim leaves 'where did the time go?' "
        "to be answered by matching timestamps"
    )
    assert acked[0].attributes["engine"] == "fake"
    assert acked[0].attributes["ack_ms"] == pytest.approx(
        float(response.headers["X-Ack-Ms"]), abs=0.05
    ), "the span, the header and the metric must all carry the one measurement"


def test_the_receiver_acks_even_when_there_is_no_span_to_annotate(spans: Any) -> None:
    """Tracing ON and nothing current to write on — the shape a deploy has between
    enabling a collector and the middleware being in the chain, and the shape every
    non-HTTP caller of this handler has.

    `_server_span` must answer None rather than hand `set_span_attributes` an invalid
    span, and `_ack` must go on to measure, header and return exactly as it always does.
    A receiver that could be broken by the absence of a span would be a phone system
    taken down by its own observability, which is what hard rule 3 keeps off this path.
    """
    from webhook_routes import _ack, _server_span

    assert tracing_enabled() is True
    assert _server_span() is None, "an invalid current span is not a span to annotate"

    response = Response()
    body = _ack(response, time.perf_counter(), "fake", {"status": "accepted"})

    assert body == {"status": "accepted"}
    assert float(response.headers["X-Ack-Ms"]) < 500, "hard rule 3's number, still measured"
    assert not [s for s in finished(spans) if "ack_ms" in (s.attributes or {})], (
        "with nothing to annotate the receiver must annotate nothing, not invent a span"
    )


def test_the_added_instrumentation_costs_microseconds_when_tracing_is_off() -> None:
    """MEASURED, not assumed.

    The receiver gained two `span()` context managers and one `set_span_attributes` call
    behind a `tracing_enabled()` guard. Disabled, each is a module-global read plus a
    generator frame. This times the exact combination the ack path now pays per request
    and holds it to a thousandth of the 500ms budget — a ceiling loose enough not to
    flake on a busy CI box and tight enough that anything doing real work fails it.
    """
    reset_tracing()
    assert tracing_enabled() is False
    from webhook_routes import _server_span

    iterations = 2000
    started = time.perf_counter()
    for _ in range(iterations):
        with span("webhook.fastpath", engine="bolna"):
            pass
        with span("webhook.inbox_claim", kind="client", engine="bolna"):
            pass
        observability.set_span_attributes(_server_span(), ack_ms=1.0, engine="bolna")
    per_request_us = (time.perf_counter() - started) / iterations * 1_000_000

    # Printed so the number is in the test output, not only in a commit message.
    print(f"\nvoice-runtime added tracing cost, tracing OFF: {per_request_us:.2f}us/request")
    assert per_request_us < 500.0, (
        f"{per_request_us:.1f}us per request is 0.1% of the 500ms ack budget — "
        "the disabled path is doing real work"
    )


# --- Exception redaction (hard rule 6 on the trace path) ----------------------
#
# The attribute allowlist guards what our call sites SET. These pin the three fields the
# OTel SDK writes by itself when an exception escapes a span — `exception.message`,
# `exception.stacktrace` and the status description — which no allowlist ever saw.


def test_a_transcript_in_an_exception_never_reaches_the_exporter(spans: Any) -> None:
    """The leak this filter was built for.

    `start_as_current_span` defaults to `record_exception=True`, so before the export
    filter existed this exported the transcript verbatim three times over: as an event
    attribute, as a stacktrace, and as the span status description.
    """
    with (
        pytest.raises(ValueError, match="extraction failed"),
        span("pipeline.extract", call_id="019f0000-0000-7000-8000-000000000006"),
    ):
        raise ValueError(f"extraction failed for {{'transcript': {TRANSCRIPT!r}}}")

    exported = dump(spans)
    assert exported, "nothing was exported — this test would pass vacuously"
    for forbidden in (PHONE, E164, TRANSCRIPT, "Ravi", "naa peru"):
        assert forbidden not in exported, f"{forbidden!r} reached the trace backend"

    # Positively: the span, its id, the error status and the exception TYPE all survive.
    # A filter that dropped the signal along with the payload would be its own outage.
    extract = by_name(spans, "pipeline.extract")[0]
    assert extract.attributes["call_id"] == "019f0000-0000-7000-8000-000000000006"
    assert extract.status.status_code.name == "ERROR"
    assert extract.status.description == "ValueError"
    event = next(e for e in extract.events if e.name == "exception")
    assert event.attributes["exception.type"] == "ValueError"
    assert "exception.message" not in event.attributes
    assert "exception.stacktrace" not in event.attributes

    # And say the drop happened positively, not by failing to find the text.
    dropped = dropped_attribute_keys()
    for key in ("exception.message", "exception.stacktrace", "status.description"):
        assert key in dropped, f"{key} was neither exported nor recorded as dropped"


def test_a_db_error_does_not_export_its_bind_parameters(spans: Any) -> None:
    """The production spelling of the test above.

    A contrived ValueError proves the mechanism; this proves the mechanism matters.
    `str(IntegrityError)` embeds `[SQL: …] [parameters: …]`, and the parameter is the
    caller's phone number — a duplicate-lead insert inside `pipeline.lead_upsert` is an
    ordinary Tuesday, not an exotic failure.
    """
    error = IntegrityError(
        "INSERT INTO leads (phone_e164) VALUES (%(p)s)",
        {"p": E164},
        Exception("duplicate key value violates unique constraint"),
    )
    assert E164 in str(error), "the fixture must actually contain the number it guards"

    with (
        pytest.raises(IntegrityError),
        span("pipeline.lead_upsert", call_id="019f0000-0000-7000-8000-000000000007"),
    ):
        raise error

    exported = dump(spans)
    assert exported, "nothing was exported — this test would pass vacuously"
    for forbidden in (PHONE, E164, "phone_e164"):
        assert forbidden not in exported, f"{forbidden!r} reached the trace backend"
    # The type name survives whole — an operator still knows it was a constraint
    # violation, which is the half of the message that was ours to keep.
    assert by_name(spans, "pipeline.lead_upsert")[0].status.description.endswith("IntegrityError")


def test_the_exception_leak_detector_bites(spans: Any) -> None:
    """Proof the two assertions above are not vacuous.

    Same doctrine as `test_the_leak_detector_bites`: bypass the filter once — the exact
    regression a future change to `init_tracing` would cause by handing the batch
    processor the raw exporter — and assert the same `dump()` scan finds the transcript.
    """
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(observability, "_redact_span", lambda readable: readable)
        with pytest.raises(ValueError, match="extraction failed"), span("pipeline.extract"):
            raise ValueError(f"extraction failed for {{'transcript': {TRANSCRIPT!r}}}")
        # Flushed INSIDE the bypass: the batch processor exports on its own thread, so
        # undoing in `finally` would race the export this test is about.
        observability._provider.force_flush()
    finally:
        monkey.undo()

    exported = dump(spans)
    assert PHONE in exported and "Ravi" in exported, (
        "the detector cannot see an exception message — the tests above prove nothing"
    )


def test_a_span_the_filter_cannot_scrub_is_dropped_not_exported(spans: Any) -> None:
    """Fail CLOSED. If `_redact_span` ever raises, the alternative to dropping the span
    is exporting the unfiltered original — the exact outcome the filter exists to
    prevent."""

    def explode(readable: Any) -> Any:
        raise RuntimeError("scrubber bug")

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(observability, "_redact_span", explode)
        with span("pipeline.extract", call_id="019f0000-0000-7000-8000-000000000008"):
            pass
        observability.shutdown_tracing()
    finally:
        monkey.undo()

    assert not by_name(spans, "pipeline.extract"), "an unscrubbable span was exported"
    assert "span.redaction_failed" in dropped_attribute_keys()


def test_a_span_link_carries_no_more_than_a_span_attribute(spans: Any) -> None:
    """A LINK has its own attribute bag, and it ships with the span.

    `_redact_span` scrubbed attributes, events and the status and copied `links` through
    untouched, which made the exporter's own claim — "no span reaches a vendor
    unscrubbed" — false for anything that sets one. Nothing in this repo does today;
    linking a batch consumer's span to each producer's is the ordinary reason one
    appears, and `_instrument_arq` is exactly the hand-rolled piece an upstream
    instrumentation package would replace. The allowlist that governs a span attribute
    governs a link's too, so `call_id` survives and a transcript does not.
    """
    from opentelemetry.trace import Link, SpanContext, TraceFlags

    linked = SpanContext(trace_id=0x1234, span_id=0x5678, is_remote=True, trace_flags=TraceFlags(1))
    tracer = observability._tracer
    with tracer.start_as_current_span(
        "pipeline.extract",
        links=[
            Link(linked, {"call_id": "019f0000-0000-7000-8000-00000000000b", "note": TRANSCRIPT})
        ],
    ):
        pass

    exported = dump(spans)
    assert PHONE not in exported, "a link attribute carried a transcript out"
    assert "Ravi" not in exported
    assert "019f0000-0000-7000-8000-00000000000b" in exported, "an id-shaped link attribute stays"
    assert "note" in dropped_attribute_keys()


def test_a_sentry_event_carries_the_otel_trace_id(spans: Any) -> None:
    """The join between the two systems we actually run.

    Sentry says WHAT broke; the trace says where the request had been when it did.
    Stamped in `before_send` because that is the one seam every event passes through,
    and after the scrubbing so no scrubber can eat it.
    """
    with span("pipeline.extract", call_id="019f0000-0000-7000-8000-00000000000a"):
        event = observability.scrub_event({"message": f"extraction failed for +91{PHONE}"})
        expected = current_trace_id()

    assert event is not None
    assert expected is not None and len(expected) == 32
    assert event["tags"]["otel_trace_id"] == expected
    assert PHONE not in json.dumps(event), "the scrubbing still runs first"


def test_a_sentry_event_gains_no_trace_tag_when_tracing_is_off() -> None:
    """A tag pointing at a trace that was never recorded is worse than no tag."""
    reset_tracing()
    assert tracing_enabled() is False
    event = observability.scrub_event({"message": "extraction failed"})
    assert event is not None and "tags" not in event
    assert current_trace_id() is None


def test_the_export_filter_is_off_the_latency_path(spans: Any) -> None:
    """Hard rule 3. The filter runs on `BatchSpanProcessor`'s export thread, so its cost
    to the 500ms ack budget is zero by construction — but the number belongs in the test
    output rather than a commit message, because "zero by construction" is a claim about
    where it runs, not about what it costs the batch."""
    with (
        pytest.raises(ValueError, match="boom"),
        span("pipeline.extract", call_id="019f0000-0000-7000-8000-000000000009"),
    ):
        raise ValueError(f"boom {TRANSCRIPT}")
    readable = by_name(spans, "pipeline.extract")[0]

    iterations = 2000
    started = time.perf_counter()
    for _ in range(iterations):
        observability._redact_span(readable)
    per_span_us = (time.perf_counter() - started) / iterations * 1_000_000

    print(f"\nexport-time span redaction: {per_span_us:.2f}us/span (export thread)")
    assert per_span_us < 200.0, (
        f"{per_span_us:.1f}us per span is too much even for a background thread"
    )
