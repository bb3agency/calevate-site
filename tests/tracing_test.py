"""Distributed tracing: does it cross the boundaries, and does it leak (hard rule 6)?

Two questions, and the second one is the important one.

1. A call crosses voice-runtime → Redis/ARQ → a worker → the engine adapter → Postgres.
   When "lead visible within 2 minutes of hangup" (OPERATIONS §5) is missed, the trace
   has to say WHERE the time went — which it can only do if the trace id survives every
   one of those hops. `test_the_trace_survives_...` are those hops, one per test.

2. A tracing system that attaches a phone number to a span is a PII leak with a nice UI,
   and unlike a log line it ships to a third-party backend by design. So the suite seeds
   a real phone number and a real transcript line into every instrumented path — as a
   span attribute, as a SQL parameter, as a query string, as a job payload — and then
   asserts they appear NOWHERE in the exported spans. That is the test that matters; the
   rest is scaffolding for it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from typing import Any

import httpx
import pytest
from apps.api.core import observability
from apps.api.core.observability import (
    TRACE_KWARG,
    TracingMiddleware,
    current_traceparent,
    dropped_attribute_keys,
    init_tracing,
    reset_tracing,
    sanitize_attributes,
    span,
    traced_job,
    tracing_enabled,
)
from apps.api.core.queue import enqueue, get_queue
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from arq.jobs import Job
from fastapi import FastAPI
from sqlalchemy import text

# The two values that must never leave the process. Same shapes the Sentry scrubber is
# pinned against in observability_security_test.py, deliberately: one leak surface, one
# definition of what a leak looks like.
PHONE = "9876543210"
E164 = f"+91{PHONE}"
TRANSCRIPT = "caller: naa number 9876543210, naa peru Ravi"


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Tracing, exporting into memory instead of at a collector.

    `span_exporter` is the only test-shaped seam in `init_tracing`; sampling still comes
    from real config, so this also exercises the settings path. Ratio is forced to 1.0
    because the production default is 0.1 and a test that passes 10% of the time is
    worse than no test.
    """
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


def finished(exporter: Any) -> list[Any]:
    """Everything exported so far. BatchSpanProcessor is asynchronous by design (it
    must never add latency to a webhook ack), so nothing is readable without a flush."""
    observability._provider.force_flush()
    return list(exporter.get_finished_spans())


def dump(exporter: Any) -> str:
    """Every exported span as one string: names, attributes, resource, events, status.

    Deliberately the WHOLE serialized span rather than a walk over the attributes we
    happen to remember — a leak that arrived through a span name or an exception message
    is still a leak, and this is the assertion that catches the case nobody predicted.
    """
    return "\n".join(readable.to_json() for readable in finished(exporter))


def named(exporter: Any, prefix: str) -> list[Any]:
    return [s for s in finished(exporter) if s.name.startswith(prefix)]


# --- The boundaries -----------------------------------------------------------


async def test_the_trace_survives_the_queue_from_enqueue_to_worker(spans: Any) -> None:
    """The hop that actually matters.

    A trace that stops at the process edge answers nothing: the queue wait is usually
    the largest slice of the 2-minute budget, and it is precisely the gap between the
    producer's span and the consumer's. So the W3C traceparent has to travel IN the ARQ
    job payload — this test reads it back out of Redis to prove it did, rather than
    trusting the in-process contextvar.
    """
    job_id = f"tracing_probe:{uuid.uuid4().hex}"
    with span("test.request", kind="server") as root:
        root_trace_id = root.get_span_context().trace_id
        # `_expires` keeps the probe from loitering in a queue no worker consumes.
        await enqueue(
            "tracing_probe_job", {"call_id": str(uuid.uuid4())}, job_id=job_id, _expires=60
        )

    queue = await get_queue()
    definition = await Job(job_id, queue).info()
    assert definition is not None, "the probe job never reached Redis"
    traceparent = definition.kwargs.get(TRACE_KWARG)
    assert traceparent, "the traceparent did not cross the queue boundary"
    assert traceparent.startswith("00-"), "not a W3C traceparent"
    assert f"{root_trace_id:032x}" in traceparent

    # The consumer side: exactly what arq will hand the worker.
    seen: dict[str, Any] = {}

    @traced_job
    async def tracing_probe_job(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
        # The wrapper must have removed the transport kwarg before the real job runs —
        # otherwise every job signature in apps/workers would have to know about it.
        seen["kwargs"] = dict(ctx)
        seen["payload"] = payload
        return "ok"

    await tracing_probe_job(
        {"job_id": job_id, "job_try": 1},
        {"call_id": "019f0000-0000-7000-8000-000000000001"},
        **{TRACE_KWARG: traceparent},
    )

    worker_spans = named(spans, "job tracing_probe_job")
    assert worker_spans, "the worker produced no span"
    assert worker_spans[0].context.trace_id == root_trace_id, (
        "the worker started a NEW trace — the queue wait is invisible"
    )
    assert named(spans, "enqueue tracing_probe_job"), "no producer span"


def test_the_worker_still_registers_its_jobs_under_the_names_producers_enqueue() -> None:
    """arq keys a job by `__qualname__`. Wrapping every job in `traced_job` without
    `functools.wraps` would register them all as `wrapper`, and every enqueue in the
    codebase would land in the DLQ — a failure that looks nothing like a tracing bug.
    The names are literals here on purpose: they are the strings producers pass."""
    from apps.workers.settings import CRON_JOBS, FUNCTIONS

    registered = {function.__qualname__ for function in FUNCTIONS}
    assert {"ingest_engine_event", "run_post_call_pipeline", "notify_hot_lead"} <= registered
    assert "wrapper" not in registered
    # arq prefixes cron names with `cron:`; the suffix is still the wrapped qualname.
    assert {job.name for job in CRON_JOBS} >= {"cron:dispatch_outbox", "cron:reconcile_executions"}


async def test_a_job_still_runs_when_the_consumer_has_tracing_off() -> None:
    """Deploy safety: the producer may be traced while this process is not. The wrapper
    pops the transport kwarg unconditionally, so an untraced worker cannot be handed an
    argument its job function has never heard of."""
    reset_tracing()
    assert tracing_enabled() is False

    @traced_job
    async def probe(ctx: dict[str, Any], value: int) -> str:
        return f"ran:{value}"

    assert await probe({}, 7, **{TRACE_KWARG: "00-" + "a" * 32 + "-" + "b" * 16 + "-01"}) == "ran:7"


async def test_the_trace_survives_an_http_hop_and_reaches_the_database(spans: Any) -> None:
    """HTTP request → handler → Postgres round trip, all under one trace id.

    The DB half is why `apps/api/db/session.py` needs no changes: the listener is
    registered on the SQLAlchemy `Engine` CLASS, so every engine the process builds is
    covered without anyone remembering to opt in.
    """
    app = FastAPI()
    app.add_middleware(TracingMiddleware, trust_incoming_traceparent=True)

    @app.get("/v1/leads/{lead_id}")
    async def read_lead(lead_id: str) -> dict[str, str]:
        # A phone number bound as a SQL PARAMETER — the exact place a naive
        # `db.statement`/`db.parameters` attribute would leak it.
        async with untenanted_session() as session:
            await session.execute(text("SELECT :phone AS probe"), {"phone": E164})
        return {"lead_id": lead_id}

    with span("test.client", kind="client") as root:
        root_trace_id = root.get_span_context().trace_id
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            # The query string carries the phone the leads filter really does accept.
            response = await client.get(
                "/v1/leads/019f0000-0000-7000-8000-000000000002",
                params={"search": E164},
                headers={"traceparent": current_traceparent() or ""},
            )
    assert response.status_code == 200

    server = named(spans, "HTTP GET /v1/leads")
    assert server, "no server span (or it was named with the concrete id, not the route)"
    assert server[0].attributes["http.response.status_code"] == 200
    assert server[0].context.trace_id == root_trace_id

    db_spans = named(spans, "db ")
    assert db_spans, "no DB span — the round trips are invisible"
    assert {s.context.trace_id for s in db_spans} == {root_trace_id}
    assert any(s.attributes.get("db.operation") == "SELECT" for s in db_spans)
    assert all("db.statement_fingerprint" in s.attributes for s in db_spans)


async def test_the_trace_survives_an_outbound_engine_call(spans: Any) -> None:
    """The engine adapter reaches Bolna over httpx; so does the extractor and so does
    outbound webhook delivery. One CLIENT span each, host and path only — never
    `url.full`, because an outbound webhook target is a CLIENT-supplied URL and can
    carry a key or a phone in its query."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "completed"})

    with span("test.worker") as root:
        root_trace_id = root.get_span_context().trace_id
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await client.get(f"https://api.bolna.ai/executions/abc?callee={E164}")

    engine_spans = [s for s in named(spans, "HTTP GET") if s.attributes.get("server.address")]
    assert engine_spans, "the engine call produced no span"
    assert engine_spans[0].attributes["server.address"] == "api.bolna.ai"
    assert engine_spans[0].attributes["url.path"] == "/executions/abc"
    assert engine_spans[0].attributes["http.response.status_code"] == 200
    assert engine_spans[0].context.trace_id == root_trace_id


# --- The leak (the test that matters) -----------------------------------------


async def test_no_phone_number_or_transcript_appears_on_any_exported_span(spans: Any) -> None:
    """Seed PII into every shape the instrumentation touches, then read back every byte
    of every exported span. Nothing. Not the number, not the line, not the name in it."""
    job_id = f"tracing_probe:{uuid.uuid4().hex}"
    with span(
        "test.receive",
        kind="server",
        # A call site doing exactly the wrong thing, on purpose.
        caller_phone=E164,
        transcript_text=TRANSCRIPT,
        extraction_payload={"name": "Ravi", "phone": E164},
        lead_note=TRANSCRIPT,
        call_id="019f0000-0000-7000-8000-000000000003",
    ):
        await enqueue(
            "tracing_probe_job",
            {"phone_e164": E164, "transcript": TRANSCRIPT},
            job_id=job_id,
            _expires=60,
        )
        async with untenanted_session() as session:
            await session.execute(
                text("SELECT :phone AS a, :line AS b"), {"phone": E164, "line": TRANSCRIPT}
            )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await client.post(f"https://crm.example.com/leads?phone={E164}", json={"t": TRANSCRIPT})

    exported = dump(spans)
    assert exported, "nothing was exported — this test would pass vacuously"
    for forbidden in (PHONE, E164, TRANSCRIPT, "Ravi", "naa peru"):
        assert forbidden not in exported, f"{forbidden!r} reached the trace backend"

    # And say so positively: the attributes were REFUSED, not merely absent because the
    # span was never created.
    dropped = dropped_attribute_keys()
    for key in ("caller_phone", "transcript_text", "extraction_payload", "lead_note"):
        assert key in dropped, f"{key} was neither exported nor recorded as dropped"
    # The id survives, which is the whole point of hard rule 6's "log ids".
    receive = named(spans, "test.receive")[0]
    assert receive.attributes["call_id"] == "019f0000-0000-7000-8000-000000000003"


def test_the_attribute_filter_is_an_allowlist_not_a_denylist() -> None:
    """A denylist on a tracing API fails open: the next attribute nobody thought of
    ships. An unlisted key is dropped even when its value is perfectly innocent."""
    clean = sanitize_attributes(
        {
            "call_id": "019f0000-0000-7000-8000-000000000004",
            "duration_ms": 41.5,
            "engine": "bolna",
            "agent_disposition": "qualified",  # innocent, unlisted -> still dropped
        }
    )
    assert set(clean) == {"call_id", "duration_ms", "engine"}


def test_an_allowlisted_key_handed_prose_or_a_phone_is_still_refused() -> None:
    """Second line of defence: `sanitize_attributes` does not trust its own allowlist.
    The verdict on 'is this a phone number' comes from the logger's `redact_text`, so
    the tracer and the logger cannot drift apart about what PII looks like."""
    assert sanitize_attributes({"lead_id": E164}) == {}
    assert sanitize_attributes({"outcome": TRANSCRIPT}) == {}
    assert sanitize_attributes({"engine": "x" * 500}) == {}
    # uuid7 ids are digit-dense enough to look phone-shaped; dropping them would defeat
    # the entire trace, so ids are excised before the value is judged.
    composite = "ingest_engine_event:bolna:019f0000-0000-7000-8000-000000000005:completed"
    assert sanitize_attributes({"job_id": composite}) == {"job_id": composite}


# --- Local dev and tests must not need a collector -----------------------------


def test_with_no_collector_configured_tracing_is_off_and_costs_nothing() -> None:
    """The `observability_local_only` contract. `uv run pytest` and a dev box run with
    nothing listening, exactly as they do with no SENTRY_DSN."""
    reset_tracing()
    get_settings.cache_clear()
    assert get_settings().otel_exporter_otlp_endpoint is None, ".env.example must ship empty"
    assert init_tracing("local") is False
    assert tracing_enabled() is False
    with span("anything", call_id="019f") as nothing:
        assert nothing is None


def test_importing_the_module_does_not_import_the_opentelemetry_sdk() -> None:
    """Hard rule 3: `apps/voice-runtime` imports `apps.api.core.bootstrap`, which
    imports this module, and every import there is paid for on the voice path. The SDK
    (measured ~79ms, the OTLP exporter ~220ms) is imported inside `init_tracing` and
    only when a collector is configured — a subprocess is the only honest way to assert
    that, since this test session has already loaded it."""
    probe = (
        "import apps.api.core.bootstrap, sys;"
        "leaked=[m for m in sys.modules if m.startswith('opentelemetry.sdk')"
        " or m.startswith('opentelemetry.exporter')];"
        "print(json.dumps(leaked))"
    )
    result = subprocess.run(
        [sys.executable, "-c", "import json;" + probe],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == [], "the OTel SDK was imported on the voice path"
