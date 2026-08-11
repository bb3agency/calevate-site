"""Observability init — Sentry, OTel tracing, and the Langfuse redaction hook.

Bootstrap step 3 says "tracing init before the app exists", and this is that step.
Everything here is config-gated and a no-op without keys, so a local run stays quiet
and a misconfigured deploy degrades rather than crashes.

The part that is not optional is the **redaction hook**. Hard rule 6 forbids phone
numbers, transcript text and extraction payloads in logs — and an error tracker is a
log with better search. Sentry captures local variables and request bodies by default,
which on this codebase means capturing a transcript the moment anything throws inside
the pipeline. So `scrub_event` runs on every event before it leaves the process, and it
reuses the SAME redaction functions the logger uses rather than a second, drifting
copy.

Langfuse (LLM traces) gets the same treatment: TRD §2 wants per-call token cost and
latency, SEC-COMP §4 says traces are scrubbed. `redact_trace_payload` is the seam.

The tracing half (TRD §2 "OpenTelemetry traces") exists to answer ONE question: when
"lead visible within 2 minutes of hangup" (OPERATIONS §5) is missed, WHERE did the time
go? A call crosses voice-runtime → Redis/ARQ → a worker → the engine adapter →
Postgres, and a trace that stops at a process edge answers nothing. So the W3C
traceparent rides in the ARQ job payload and the worker continues the same trace.

Same PII posture as the rest of this module, only stricter: span attributes are an
ALLOWLIST (`ALLOWED_SPAN_ATTRIBUTES`), not a denylist. A denylist on a tracing API
fails open — the next person adds `agent_note=...` to a span and it ships to a vendor
before anyone reads the diff. An allowlist fails closed: an unlisted attribute is
silently dropped and counted, and making it visible is a reviewable change to THIS
file. On top of that every value must be id-shaped, judged by `redact_text` — the
logger's own verdict, so the two cannot drift.
"""

from __future__ import annotations

import functools
import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from apps.api.core.logging import REDACT_KEYS, get_logger, redact_mapping, redact_text
from apps.api.core.settings import get_settings

log = get_logger(__name__)

# Request headers that must never reach an error tracker, in addition to the value
# scrubbing below.
DROP_HEADERS = frozenset(
    {"authorization", "cookie", "set-cookie", "x-org-slug", "x-impersonate-org", "svix-signature"}
)


def scrub_event(
    event: dict[str, Any], _hint: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Sentry `before_send`. Returns the event with every PII-shaped value removed.

    Deliberately aggressive: a dropped detail costs a debugging round trip, a leaked
    transcript is a DPDP incident. Returning None would drop the event entirely — we
    do not, because knowing an error happened is itself the point.
    """
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                k: ("[redacted]" if k.lower() in DROP_HEADERS else v) for k, v in headers.items()
            }
        # The body can be a lead payload or a webhook full of transcript text.
        request.pop("data", None)
        # Query strings carry lead search filters, which can be a phone suffix.
        if isinstance(request.get("query_string"), str):
            request["query_string"] = redact_text(request["query_string"])

    for frame_holder in _iter_stacktraces(event):
        variables = frame_holder.get("vars")
        if isinstance(variables, dict):
            frame_holder["vars"] = redact_mapping(variables)

    extra = event.get("extra")
    if isinstance(extra, dict):
        event["extra"] = redact_mapping(extra)

    if isinstance(event.get("message"), str):
        event["message"] = redact_text(event["message"])
    return event


def _iter_stacktraces(event: dict[str, Any]) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for container in (event.get("exception"), event.get("threads")):
        if not isinstance(container, dict):
            continue
        for entry in container.get("values", []) or []:
            stacktrace = entry.get("stacktrace") if isinstance(entry, dict) else None
            if isinstance(stacktrace, dict):
                frames.extend(f for f in stacktrace.get("frames", []) or [] if isinstance(f, dict))
    return frames


def redact_trace_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """The Langfuse hook (CLAUDE.md hard rule 6: "Langfuse traces go through the
    redaction hook").

    An LLM trace is the single richest PII object we produce — it contains the prompt,
    which contains the transcript. Same redaction primitives as the logger so the two
    cannot drift apart.
    """
    return redact_mapping(payload)


# --- Distributed tracing (OpenTelemetry) --------------------------------------
#
# Nothing below imports opentelemetry at module scope. `apps/voice-runtime` imports
# `apps.api.core.bootstrap`, which imports this module, and hard rule 3 forbids heavy
# imports on the latency path. The SDK import (measured: ~79ms, exporter ~220ms — vs
# fastapi's own ~456ms, which that service already pays) happens inside `init_tracing`
# and ONLY when a collector is configured. With no collector configured the module
# holds `None` and every helper here is a branch on a module global.

# The ARQ job kwarg that carries the W3C traceparent across the queue boundary. Named
# with a leading underscore so it cannot collide with a domain kwarg, and popped by
# `traced_job` before the real job function ever sees it.
TRACE_KWARG = "_calevate_traceparent"

# Attributes we are willing to ship. Ids, counts, durations and enums — nothing else
# (CLAUDE.md hard rule 6: "log ids"). Adding a key here is the reviewable act.
ALLOWED_SPAN_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "service.name",
        "service.version",
        "deployment.environment",
        "http.request.method",
        "http.response.status_code",
        "url.path",
        "url.scheme",
        "server.address",
        "db.system",
        "db.operation",
        # A fingerprint, not the SQL: the statement is parameterised, but "usually
        # parameterised" is not a property worth betting a DPDP incident on.
        "db.statement_fingerprint",
        "messaging.system",
        "messaging.operation",
        "messaging.destination.name",
        "engine",
        "job",
        "outcome",
        "deduped",
    }
)

# Suffix rules, so `call_id`, `tenant_id`, `queue_wait_ms`, `db_rows` need no listing.
# The REDACT_KEYS check runs FIRST, so `caller_phone_id` is still refused.
ALLOWED_SPAN_ATTRIBUTE_SUFFIXES: tuple[str, ...] = (
    "_id",
    "_ms",
    "_count",
    "_bytes",
    "_rows",
    "_try",
    "_status",
)

# An id is short. Anything longer is prose, and prose on this codebase is a transcript.
MAX_ATTRIBUTE_CHARS = 128

# uuid7 ids are digit-rich enough to trip a phone-shaped-digit-run check, and dropping
# `call_id` would defeat the entire point of the trace. Ids are excised before the
# value is judged, never after.
_UUID_ANYWHERE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

_SQL_OPERATIONS = frozenset(
    {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "WITH",
        "SET",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "CREATE",
        "DROP",
        "ALTER",
        "SHOW",
    }
)

_tracer: Any = None
_provider: Any = None
_propagator: Any = None
_dropped_attributes: dict[str, int] = {}


def _attribute_key_allowed(key: str) -> bool:
    # The logger's denylist first: it is the house standard and it is a superset of
    # anything the allowlist could accidentally admit (`phone_id`, `body_count`, ...).
    if any(marker in key.lower() for marker in REDACT_KEYS):
        return False
    return key in ALLOWED_SPAN_ATTRIBUTES or key.endswith(ALLOWED_SPAN_ATTRIBUTE_SUFFIXES)


def _safe_attribute_value(value: object) -> Any:
    """The value-shape gate. Returns the value, or None meaning 'drop it'.

    Second line of defence: an allowlisted key handed a transcript by a buggy call site
    must still not ship. The verdict comes from `redact_text` rather than a second
    regex, so the tracer and the logger cannot disagree about what a phone number is.
    """
    if isinstance(value, bool | int | float):
        return value
    if not isinstance(value, str) or not value or len(value) > MAX_ATTRIBUTE_CHARS:
        return None
    if any(character.isspace() for character in value):
        return None  # ids do not contain spaces; sentences do
    probe = _UUID_ANYWHERE.sub("", value)
    if redact_text(probe) != probe:
        return None  # the logger says this is phone-shaped
    return value


def sanitize_attributes(attributes: dict[str, object]) -> dict[str, Any]:
    """Allowlist + value-shape filter. Dropped keys are counted, never guessed at."""
    clean: dict[str, Any] = {}
    for key, value in attributes.items():
        if not _attribute_key_allowed(key):
            _dropped_attributes[key] = _dropped_attributes.get(key, 0) + 1
            continue
        safe = _safe_attribute_value(value)
        if safe is None:
            _dropped_attributes[key] = _dropped_attributes.get(key, 0) + 1
            continue
        clean[key] = safe
    return clean


def dropped_attribute_keys() -> dict[str, int]:
    """Attribute keys refused by `sanitize_attributes`, key -> count.

    Exposed because 'the transcript was dropped' is a claim a test should be able to
    make positively, rather than by failing to find it.
    """
    return dict(_dropped_attributes)


def tracing_enabled() -> bool:
    return _tracer is not None


@contextmanager
def span(name: str, *, kind: str = "internal", **attributes: object) -> Iterator[Any]:
    """A span, or nothing at all when tracing is off (local dev, tests, no collector).

    Disabled it is one global read and a generator frame — deliberately cheap enough
    to sit on the voice path.
    """
    tracer = _tracer
    if tracer is None:
        yield None
        return
    from opentelemetry.trace import SpanKind

    with tracer.start_as_current_span(name, kind=getattr(SpanKind, kind.upper())) as active:
        active.set_attributes(sanitize_attributes(attributes))
        yield active


def set_span_attributes(active: Any, **attributes: object) -> None:
    """Attributes discovered mid-span (a status code, a row count). No-op when off."""
    if active is not None:
        active.set_attributes(sanitize_attributes(attributes))


def current_traceparent() -> str | None:
    """The W3C traceparent for the active span, or None. This is what crosses Redis."""
    if _propagator is None:
        return None
    carrier: dict[str, str] = {}
    _propagator.inject(carrier)
    return carrier.get("traceparent")


def _context_from_traceparent(traceparent: str | None) -> Any:
    if _propagator is None or not traceparent:
        return None
    return _propagator.extract({"traceparent": traceparent})


def traced_job(function: Any) -> Any:
    """Wrap an ARQ job so it CONTINUES the trace that enqueued it.

    Registered from `apps/workers/settings.py`. `functools.wraps` matters more than it
    looks: arq keys a job by `__qualname__`, so an un-wrapped name would silently
    register the job under `wrapper` and every enqueue would land in the DLQ.

    It also pops `TRACE_KWARG` unconditionally — including when tracing is off — so a
    job enqueued by a traced producer can always be consumed, whatever this process's
    own configuration says.
    """

    @functools.wraps(function)
    async def wrapper(ctx: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        traceparent = kwargs.pop(TRACE_KWARG, None)
        tracer = _tracer
        if tracer is None:
            return await function(ctx, *args, **kwargs)
        from opentelemetry.trace import SpanKind

        # `__name__`, not `__qualname__`: arq registers by qualname, but a qualname is
        # allowed to carry an enclosing scope and a span name wants low cardinality.
        name = getattr(function, "__name__", "job")
        with tracer.start_as_current_span(
            f"job {name}",
            context=_context_from_traceparent(traceparent),
            kind=SpanKind.CONSUMER,
        ) as active:
            active.set_attributes(
                sanitize_attributes(
                    {
                        "messaging.system": "arq",
                        "messaging.operation": "process",
                        "job": name,
                        "job_id": ctx.get("job_id"),
                        "job_try": ctx.get("job_try"),
                    }
                )
            )
            outcome = await function(ctx, *args, **kwargs)
            if isinstance(outcome, str):
                set_span_attributes(active, outcome=outcome)
            return outcome

    return wrapper


class TracingMiddleware:
    """The server span. Installed by `create_app` ONLY when tracing is enabled, so a
    deploy without a collector — and every test run — has the exact ASGI chain it has
    today (BACKEND-PATTERNS §2 step 5: observability sits innermost, next to the
    correlation id, so the span can carry it).

    `trust_incoming_traceparent` is False for voice-runtime. Its receiver is the one
    unauthenticated public write surface we expose (webhook_routes.py), and a
    traceparent carries a `sampled` flag: honouring a stranger's flag hands them a
    switch that turns on 100% of our tracing spend. Engine webhooks start a fresh root.
    """

    def __init__(self, app: Any, *, trust_incoming_traceparent: bool) -> None:
        self.app = app
        self.trust_incoming_traceparent = trust_incoming_traceparent

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        tracer = _tracer
        if scope.get("type") != "http" or tracer is None:
            await self.app(scope, receive, send)
            return

        from opentelemetry.trace import SpanKind

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        parent = (
            _context_from_traceparent(headers.get("traceparent"))
            if self.trust_incoming_traceparent
            else None
        )
        method = str(scope.get("method", "GET"))
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = int(message["status"])
            await send(message)

        with tracer.start_as_current_span(
            f"HTTP {method}", context=parent, kind=SpanKind.SERVER
        ) as active:
            # Path, never the query string — the leads filter accepts a phone suffix
            # (same reason CorrelationIdMiddleware logs `scope['path']` alone).
            from apps.api.core.context import correlation_id_var

            active.set_attributes(
                sanitize_attributes(
                    {
                        "http.request.method": method,
                        "url.path": str(scope.get("path", "")),
                        "url.scheme": str(scope.get("scheme", "http")),
                        "correlation_id": correlation_id_var.get(),
                    }
                )
            )
            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                # The matched route TEMPLATE, resolved only after routing. Naming the
                # span `/v1/leads/{lead_id}` instead of a concrete id is what keeps the
                # trace backend's cardinality (and bill) finite.
                route = scope.get("route")
                template = getattr(route, "path_format", None) or getattr(route, "path", None)
                if template:
                    active.update_name(f"HTTP {method} {template}")
                set_span_attributes(
                    active, **{"http.response.status_code": status_holder.get("status")}
                )


def _instrument_arq() -> None:
    """Inject the traceparent into the ARQ job payload at enqueue time.

    This patches `ArqRedis.enqueue_job` rather than `apps/api/core/queue.py` on purpose:
    every producer — the webhook receiver, the outbox dispatcher, the campaign tick —
    reaches Redis through this one method, and instrumenting the library boundary is
    how OTel instrumentation works everywhere else. There is no second place to forget.

    DEPLOY NOTE: the extra kwarg is only understood by a worker whose jobs are wrapped
    in `traced_job`. Producer and consumer ship in the same image (DEPLOYMENT §1: "one
    image, three services"), so the exposure is the seconds-long window of a rolling
    restart, and those jobs retry.
    """
    from arq.connections import ArqRedis

    original = ArqRedis.enqueue_job
    if getattr(original, "_calevate_traced", False):
        return

    @functools.wraps(original)
    async def enqueue_job(self: Any, function: str, *args: Any, **kwargs: Any) -> Any:
        with span(
            f"enqueue {function}",
            kind="producer",
            **{
                "messaging.system": "arq",
                "messaging.operation": "publish",
                "messaging.destination.name": str(function),
                "job": str(function),
                "job_id": kwargs.get("_job_id"),
            },
        ) as active:
            # Injected INSIDE the span, so the worker's span is a child of the enqueue
            # and the queue wait is the gap between them — which is the number the
            # 2-minute SLO is actually made of.
            traceparent = current_traceparent()
            if traceparent and TRACE_KWARG not in kwargs:
                kwargs[TRACE_KWARG] = traceparent
            result = await original(self, function, *args, **kwargs)
            set_span_attributes(active, deduped=result is None)
            return result

    enqueue_job._calevate_traced = True  # type: ignore[attr-defined]
    ArqRedis.enqueue_job = enqueue_job  # type: ignore[method-assign]


def _sql_operation(statement: str) -> str:
    head = statement.lstrip().split(None, 1)
    token = head[0].upper() if head else ""
    return token if token in _SQL_OPERATIONS else "OTHER"


def _instrument_sqlalchemy() -> None:
    """DB round trips, listened for on the `Engine` CLASS.

    Class-level so it covers every engine the process ever builds — including the
    async ones, whose sync engine underneath is what actually emits these events —
    without `apps/api/db/session.py` having to know tracing exists.

    Attributes are the operation verb, a statement FINGERPRINT and a row count. Never
    the statement, never the parameters: `parameters` is where a phone number lives.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    if getattr(Engine, "_calevate_traced", False):
        return

    def before(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
    ) -> None:
        tracer = _tracer
        if tracer is None:
            return
        from opentelemetry.trace import SpanKind

        # `start_span`, not `start_as_current_span`: the span opens and closes in two
        # different callbacks, and attaching/detaching a context across that boundary
        # would corrupt the contextvar stack of whatever task is mid-flight.
        active = tracer.start_span(f"db {_sql_operation(statement)}", kind=SpanKind.CLIENT)
        active.set_attributes(
            sanitize_attributes(
                {
                    "db.system": "postgresql",
                    "db.operation": _sql_operation(statement),
                    "db.statement_fingerprint": hashlib.sha256(
                        statement.encode("utf-8", "replace")
                    ).hexdigest()[:12],
                }
            )
        )
        conn.info.setdefault("calevate_db_spans", []).append(active)

    def _close(conn: Any, rows: int | None = None) -> None:
        stack = conn.info.get("calevate_db_spans") if conn is not None else None
        if not stack:
            return
        active = stack.pop()
        if rows is not None and rows >= 0:
            active.set_attributes(sanitize_attributes({"db_rows": rows}))
        active.end()

    def after(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
    ) -> None:
        _close(conn, getattr(cursor, "rowcount", None))

    def on_error(exception_context: Any) -> None:
        # Without this, a failing statement leaks its span forever — and the traces
        # that matter most are the ones with an error in them.
        _close(getattr(exception_context, "connection", None))

    event.listen(Engine, "before_cursor_execute", before)
    event.listen(Engine, "after_cursor_execute", after)
    event.listen(Engine, "handle_error", on_error)
    Engine._calevate_traced = True  # type: ignore[attr-defined]


def _instrument_httpx() -> None:
    """Outbound HTTP — the engine adapter (apps/api/engine/bolna.py), the extractor,
    client webhook delivery.

    Hand-rolled rather than `opentelemetry-instrumentation-httpx` because that package
    records `url.full`. Outbound webhook targets are CLIENT-supplied URLs, so a full
    URL can carry `?api_key=` or a phone in a callback parameter. Host + path only.
    """
    import httpx

    original = httpx.AsyncClient.send
    if getattr(original, "_calevate_traced", False):
        return

    @functools.wraps(original)
    async def send(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        with span(
            f"HTTP {request.method}",
            kind="client",
            **{
                "http.request.method": request.method,
                "server.address": request.url.host,
                "url.path": request.url.path,
            },
        ) as active:
            response = await original(self, request, *args, **kwargs)
            set_span_attributes(active, **{"http.response.status_code": response.status_code})
            return response

    send._calevate_traced = True  # type: ignore[attr-defined]
    httpx.AsyncClient.send = send  # type: ignore[method-assign]


def init_tracing(service: str, *, span_exporter: Any = None) -> bool:
    """Bootstrap step 3. Returns whether tracing came up.

    LOCAL DEV AND TESTS REQUIRE NOTHING. With `OTEL_EXPORTER_OTLP_ENDPOINT` unset this
    returns False without importing a single opentelemetry module, and the caller logs
    `observability_local_only` exactly as it does for a missing Sentry DSN.

    `span_exporter` is the seam `tests/tracing_test.py` uses to capture spans in memory;
    production always passes None and gets the OTLP/HTTP exporter built from config.
    """
    global _tracer, _provider, _propagator
    # Idempotent, and checked first: `api` and `workers` share this module, and a
    # second caller must not build a second provider (two batch exporters, doubled
    # spans) nor report "off" for a process where tracing is plainly on.
    if _provider is not None:
        return True
    settings = get_settings()
    endpoint = settings.otel_exporter_otlp_endpoint
    if not endpoint and span_exporter is None:
        return False

    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    except ImportError:
        # Tolerant boot (BACKEND-PATTERNS §2), same contract as the Sentry branch: a
        # missing optional package must not take down a service that answers calls.
        log.warning("otel_endpoint_set_but_sdk_missing")
        return False

    # SAMPLING (the deliberate decision).
    #
    # ParentBased is the part that is not negotiable: the sampling verdict is taken
    # ONCE, at the root, and rides the traceparent across Redis into the worker. A
    # per-process sampler would re-roll the dice at every hop, and 10% of 10% of a
    # four-process path is a trace backend full of orphans — the exact opposite of
    # what this is for.
    #
    # The default ratio is 10%. Tracing every call is real money and real I/O on a
    # single VPS (DEPLOYMENT §1), and it buys nothing: the SLO BREACH is detected on
    # 100% of calls by `record_pipeline_lag` (alerting.py), a metric that costs a log
    # line. Traces exist to DIAGNOSE a breach, and diagnosis needs a representative
    # sample of complete paths, not every path. At M1 volumes 10% is still hundreds of
    # end-to-end call traces a day — enough to characterise p95 per stage.
    #
    # It is config, not a constant, because the first thing an operator does in an
    # incident is turn it to 1.0 for an hour. That must be an env change and a restart,
    # not a deploy.
    ratio = settings.otel_traces_sample_ratio
    resource = Resource.create(
        {
            "service.name": f"calevate-{service}",
            "service.version": settings.release_version,
            "deployment.environment": settings.app_env,
        }
    )
    provider = TracerProvider(resource=resource, sampler=ParentBased(root=TraceIdRatioBased(ratio)))
    if span_exporter is None and endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        span_exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
    # Batched, never synchronous: the export must not be able to add latency to a
    # webhook ack. A full queue drops spans, which is the correct trade — losing
    # telemetry beats missing the 500ms budget (hard rule 3).
    provider.add_span_processor(BatchSpanProcessor(span_exporter))
    otel_trace.set_tracer_provider(provider)

    _provider = provider
    _tracer = provider.get_tracer("calevate")
    _propagator = TraceContextTextMapPropagator()

    _instrument_arq()
    _instrument_sqlalchemy()
    _instrument_httpx()
    return True


def shutdown_tracing() -> None:
    """Flush on drain. A crash-time trace that never left the process is a trace that
    never existed, and drains are exactly when the interesting ones happen."""
    if _provider is not None:
        _provider.force_flush()
        _provider.shutdown()


def reset_tracing() -> None:
    """Test seam only: drop the provider so the next `init_tracing` rebuilds it. The
    monkeypatched library methods stay in place — they are no-ops while `_tracer` is
    None, and un-patching them would race any other test already inside one."""
    global _tracer, _provider, _propagator
    _tracer = None
    _provider = None
    _propagator = None
    _dropped_attributes.clear()


def init_observability(service: str) -> str:
    """Called from `create_app` before the app object exists. Returns what was enabled,
    for the startup log line — an operator should be able to see at a glance whether
    errors are actually going anywhere."""
    settings = get_settings()
    enabled: list[str] = []

    if settings.sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(
                dsn=settings.sentry_dsn,
                environment=settings.app_env,
                release=settings.release_version,
                # Never send PII, and scrub what the SDK gathers anyway.
                send_default_pii=False,
                max_request_body_size="never",
                before_send=scrub_event,
                traces_sample_rate=0.1 if settings.app_env == "prod" else 1.0,
            )
            sentry_sdk.set_tag("service", service)
            enabled.append("sentry")
        except ImportError:
            # Tolerant boot (BACKEND-PATTERNS §2): a missing optional package must not
            # take down a service whose actual job is answering calls.
            log.warning("sentry_dsn_set_but_sdk_missing")

    if init_tracing(service):
        enabled.append(f"otel@{settings.otel_traces_sample_ratio:g}")

    if not enabled:
        log.info("observability_local_only", extra={"service": service})
    return ",".join(enabled) or "none"


__all__ = [
    "ALLOWED_SPAN_ATTRIBUTES",
    "ALLOWED_SPAN_ATTRIBUTE_SUFFIXES",
    "DROP_HEADERS",
    "MAX_ATTRIBUTE_CHARS",
    "REDACT_KEYS",
    "TRACE_KWARG",
    "TracingMiddleware",
    "current_traceparent",
    "dropped_attribute_keys",
    "init_observability",
    "init_tracing",
    "redact_trace_payload",
    "reset_tracing",
    "sanitize_attributes",
    "scrub_event",
    "set_span_attributes",
    "shutdown_tracing",
    "span",
    "traced_job",
    "tracing_enabled",
]
