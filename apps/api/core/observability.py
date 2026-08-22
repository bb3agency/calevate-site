"""Observability init — Sentry, OTel tracing, and the hard-rule-6 redaction hooks.

Bootstrap step 3 says "tracing init before the app exists", and this is that step.
Everything here is config-gated and a no-op without keys, so a local run stays quiet
and a misconfigured deploy degrades rather than crashes.

Degrading quietly is only acceptable while somebody is TOLD. `observability_readiness`
near the bottom of this file is the ladder that tells them: off skips cleanly, on-and-
consistent is ready, and **on-and-broken is named, by field, at boot and again ahead of
the deploy** (`scripts/check_observability_ready.py`). It answers configuration validity
and refuses to guess at reachability — that half is OPERATIONS §2 gate 15, against the
real hosts.

The part that is not optional is the **redaction hook**. Hard rule 6 forbids phone
numbers, transcript text and extraction payloads in logs — and an error tracker is a
log with better search. Sentry captures local variables and request bodies by default,
which on this codebase means capturing a transcript the moment anything throws inside
the pipeline. So `scrub_event` runs on every event before it leaves the process, and it
reuses the SAME redaction functions the logger uses rather than a second, drifting
copy.

Hard rule 6 names "the redaction hook" in terms of Langfuse, and there is still no
Langfuse client here (the keys were removed by D-49 and restoring them needs its own
decision-log entry — per-call token cost and the latency breakdown TRD §2 lists are
still NOT being recorded). What changed is that the rule now has a REAL enforcement
point on the trace path instead of a named function nobody called: `_redact_span`,
applied by `_RedactingSpanExporter` to every span leaving this process. The old
`redact_trace_payload` was deleted rather than kept as a shape — a second, hand-called
redaction entry point beside an automatic one is two ways to do one thing, and the
hand-called one is the one that gets forgotten.

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

That allowlist guards what OUR call sites set. It does not guard what the SDK writes
by itself — the exception message, the exception stacktrace and the span status
description — which is where a transcript actually reached the exporter. The export
filter below closes that, for every span, including ones this module did not create.

THE SAME RULE APPLIES TO THE ERROR TRACKER, and for a while it did not. `scrub_event`
walked the request, the frame locals and `extra`, and walked straight past the exception
MESSAGE (`exception.values[].value`) and the logging integration's `logentry` — the two
fields Sentry actually displays. A span dropped `exception.message` while the event
beside it shipped the same string. One rule, both exporters.
"""

from __future__ import annotations

import functools
import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from calevate_shared.config import email_transport_reason

from apps.api.core.alerting import configure_alerts
from apps.api.core.logging import (
    MESSAGE_WITHHELD,
    REDACT_KEYS,
    get_logger,
    redact_mapping,
    redact_text,
)
from apps.api.core.settings import get_settings

if TYPE_CHECKING:  # `Settings` is a type here and never a runtime import (hard rule 3).
    from calevate_shared.config import Settings

log = get_logger(__name__)

# Request headers that must never reach an error tracker, in addition to the value
# scrubbing below. `x-impersonation-grant` is here for the strongest reason on the list:
# it is a signed token that, paired with an operator's admin session, opens a client's
# account. A crash report is exactly where one would otherwise be captured verbatim.
DROP_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-org-slug",
        "x-impersonate-org",
        "x-impersonation-grant",
        "svix-signature",
    }
)


def scrub_event(
    event: dict[str, Any], _hint: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Sentry `before_send`. Returns the event with every PII-shaped value removed.

    Deliberately aggressive: a dropped detail costs a debugging round trip, a leaked
    transcript is a DPDP incident. Returning None would drop the event entirely — we
    do not, because knowing an error happened is itself the point.

    THE THREE FIELDS THIS USED TO WALK PAST, all of them read at source in the SDK
    rather than guessed at:

    * `exception.values[].value` — the exception MESSAGE, which is `str(exc)` plus any
      `__notes__` (`sentry_sdk.utils.single_exception_from_error_tuple` →
      `get_error_message`). It is the string Sentry shows as the title of the issue,
      and it was leaving unscrubbed while the OTel exporter below was dropping the
      identical field off every span. `hide_parameters=True` covers the driver-error
      spelling of the leak; it covers nothing about `ValueError(transcript)`.
    * `logentry` — `{"message", "formatted", "params"}`, written by the SDK's logging
      integration for EVERY `log.error`/`log.exception` in this repo
      (`sentry_sdk/integrations/logging.py::_emit`). `event["message"]` — the only
      spelling this function knew — is the LEGACY field; `params` is `record.args`,
      i.e. the exact values a `%`-style log call interpolated.
    * `breadcrumbs.values[]` — normally already clean, because `before_breadcrumb`
      runs at capture. Re-scrubbed here anyway: `scrub_breadcrumb` is a hook that can
      be unset by a future `sentry_sdk.init` edit, and this is the seam where the
      breadcrumbs actually leave the process.
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
        # A sibling of `headers`, not a member of it, so `DROP_HEADERS` never sees it.
        # Only populated under `send_default_pii=True` — which is off, and which is a
        # one-word edit away from being on.
        request.pop("cookies", None)
        # Query strings carry lead search filters, which can be a phone suffix.
        if isinstance(request.get("query_string"), str):
            request["query_string"] = redact_text(request["query_string"])

    for frame_holder in _iter_stacktraces(event):
        variables = frame_holder.get("vars")
        if isinstance(variables, dict):
            frame_holder["vars"] = redact_mapping(variables)

    for entry in _iter_exception_values(event):
        if entry.get("value"):
            # WITHHELD, not `redact_text`-ed, and the same marker the log traceback uses
            # (`logging.redact_exception`). Two answers for one string in one module
            # would be the drift this repo's "one way per problem" rule exists to stop —
            # and the strict answer is the correct one for the same reason there: masking
            # phone-shaped runs and capping length cannot recognise a caller's NAME or a
            # Telugu sentence, and `pydantic.ValidationError` renders `input_value=…`
            # into its own message by design. The TYPE is kept beside it in
            # `values[].type`, which is what Sentry groups on and titles the issue with.
            entry["value"] = MESSAGE_WITHHELD

    extra = event.get("extra")
    if isinstance(extra, dict):
        event["extra"] = redact_mapping(extra)

    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        event["logentry"] = redact_mapping(logentry)

    breadcrumbs = event.get("breadcrumbs")
    crumbs = breadcrumbs.get("values") if isinstance(breadcrumbs, dict) else breadcrumbs
    if isinstance(crumbs, list):
        for crumb in crumbs:
            if isinstance(crumb, dict):
                scrub_breadcrumb(crumb)

    if isinstance(event.get("message"), str):
        event["message"] = redact_text(event["message"])

    # The join key between the two systems we actually run. Sentry says WHAT broke;
    # the OTel trace says where the request had been when it did, and without the id
    # written on both, going from one to the other is a hunt through timestamps.
    # Stamped here rather than at each `capture_exception` because `before_send` is the
    # one seam every event passes through — there is no second place to forget it — and
    # AFTER the scrubbing above so a scrubber can never eat it. Tag, not context: a
    # `contexts.trace` would claim this event belongs to a SENTRY transaction, and
    # Sentry performance tracing is deliberately off (see `init_observability`).
    trace_id = current_trace_id()
    if trace_id is not None:
        tags = event.get("tags")
        if not isinstance(tags, dict):
            tags = {}
            event["tags"] = tags
        tags["otel_trace_id"] = trace_id
    return event


def scrub_breadcrumb(
    crumb: dict[str, Any], _hint: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Sentry `before_breadcrumb`. The other half of `scrub_event`, and it was missing.

    `before_send` sees the EVENT; breadcrumbs are attached to it, and `scrub_event`
    never walked them. They are not incidental on this codebase: the logging
    integration builds one from every log record — reading `record.getMessage()`
    directly, so our JsonFormatter's redaction never runs on it — and the stdlib/httpx
    integrations add one per outbound request carrying the full URL, which is a client
    webhook endpoint with a token in its query string (see `configure_logging`'s note
    on the same hazard).

    Scrubbed at CAPTURE rather than inside `scrub_event`, because a breadcrumb that was
    never taken cannot be forgotten by a later hook — and because `before_breadcrumb`
    is the hook Sentry provides for exactly this.
    """
    if isinstance(crumb.get("message"), str):
        crumb["message"] = redact_text(crumb["message"])
    data = crumb.get("data")
    if isinstance(data, dict):
        clean = redact_mapping(data)
        # `redact_mapping` masks phone-shaped runs, which is not what makes an outbound
        # URL dangerous: `?token=…` is neither a phone nor a redacted key. Same verdict
        # as `_instrument_httpx` — scheme, host and path, never the query.
        url = clean.get("url")
        if isinstance(url, str):
            split = urlsplit(url)
            clean["url"] = urlunsplit((split.scheme, split.netloc, split.path, "", ""))
        crumb["data"] = clean
    return crumb


def _iter_exception_values(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Every entry of the Exception interface — one per link of a chained exception."""
    container = event.get("exception")
    if not isinstance(container, dict):
        return []
    return [entry for entry in container.get("values", []) or [] if isinstance(entry, dict)]


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


def _note_dropped(key: str) -> None:
    _dropped_attributes[key] = _dropped_attributes.get(key, 0) + 1


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
            _note_dropped(key)
            continue
        safe = _safe_attribute_value(value)
        if safe is None:
            _note_dropped(key)
            continue
        clean[key] = safe
    return clean


def dropped_attribute_keys() -> dict[str, int]:
    """Attribute keys refused by `sanitize_attributes`, key -> count.

    Exposed because 'the transcript was dropped' is a claim a test should be able to
    make positively, rather than by failing to find it.
    """
    return dict(_dropped_attributes)


# --- Export-time redaction (hard rule 6's enforcement point on the trace path) -
#
# THE LEAK THIS EXISTS FOR. `sanitize_attributes` guards the attributes our call sites
# set. It does not guard the three fields the SDK writes by ITSELF:
# `start_as_current_span` defaults to `record_exception=True` and
# `set_status_on_exception=True`, so ANY exception escaping ANY span writes
# `exception.message`, `exception.stacktrace` (a span EVENT, not an attribute) and
# `Status.description` — none of which the allowlist ever sees. Measured on this repo
# before this filter existed, a `ValueError` raised inside `span("pipeline.extract")`
# exported the transcript verbatim in all three. The production spelling is not a
# contrived ValueError: `str(sqlalchemy.exc.IntegrityError)` is
# `"… [SQL: INSERT INTO leads (phone_e164) …] [parameters: {'p': '+919876543210'}]"`,
# and a duplicate-lead insert inside `pipeline.lead_upsert` is an ordinary Tuesday.
#
# WHY HERE AND NOT AT THE CALL SITES. `record_exception=False` on each
# `start_as_current_span` would work today (four sites) and fail at the fifth one
# somebody adds next month — D-29's own words, a guard you have to remember is a guard
# that fails when the codebase grows fastest. The exporter is the last point EVERY span
# passes through, ours and any future instrumentation library's alike.
#
# LATENCY (hard rule 3). This runs inside `BatchSpanProcessor`'s own export thread, off
# the request and ack path entirely — the cost to voice-runtime's 500ms budget is zero
# by construction, not by being small. Measured anyway at ~9us per span for a span with
# an exception event (measured by `tracing_stages_test.py`), against a batch that leaves
# the process every 5s.
#
# WHY THE MESSAGE IS DROPPED RATHER THAN `redact_text`-ed. `redact_text` masks
# phone-shaped digit runs and caps length; it does not and cannot recognise a caller's
# NAME or a Telugu sentence. An exception message is free prose authored upstream, so
# there is no way to prove it is not a transcript — which is exactly the case the
# allowlist doctrine above answers by failing closed. What survives is the half we
# authored: the exception TYPE, which is a class name. The detail is not lost, it moves
# to the log line and the Sentry event, both scrubbed, both joined to this span by
# `correlation_id`.

# Exception-event attributes that are safe by SHAPE: a class name and a bool.
_EXCEPTION_EVENT_NAME = "exception"
_EXCEPTION_KEEP_KEYS = ("exception.type", "exception.escaped")
_EXCEPTION_DROP_KEYS = ("exception.message", "exception.stacktrace")
_STATUS_DESCRIPTION_KEY = "status.description"


def _redacted_events(events: Any) -> tuple[list[Any], str | None]:
    """Scrubbed span events, plus the exception type worth keeping on the status."""
    from opentelemetry.sdk.trace import Event

    clean: list[Any] = []
    exception_type: str | None = None
    for event in events or ():
        attributes = dict(event.attributes or {})
        if event.name == _EXCEPTION_EVENT_NAME:
            for key in _EXCEPTION_DROP_KEYS:
                if key in attributes:
                    _note_dropped(key)
            kept = {key: attributes[key] for key in _EXCEPTION_KEEP_KEYS if key in attributes}
            candidate = kept.get("exception.type")
            if isinstance(candidate, str):
                exception_type = candidate
            clean.append(Event(event.name, kept, event.timestamp))
            continue
        # A non-exception event is somebody's `add_event`, and its attributes get the
        # same allowlist as a span's — there is no reason for the two to differ.
        clean.append(
            Event(redact_text(event.name), sanitize_attributes(attributes), event.timestamp)
        )
    return clean, exception_type


def _redacted_links(links: Any) -> tuple[list[Any], bool]:
    """Span links carry their own attribute bag, and it ships with the span.

    THE LAST UNFILTERED SURFACE ON A ReadableSpan. Attributes, events and the status
    were all scrubbed above and `links` was copied straight through, which made the
    class docstring's claim — "no span reaches a vendor unscrubbed" — false for any
    instrumentation that uses them. Nothing in this repo sets a link today; messaging
    instrumentation (a batch consumer linking each message's producer span) is the
    ordinary reason one appears, and `_instrument_arq` is exactly the kind of hand-rolled
    piece that gets replaced by an upstream library. Closing it now costs a list
    comprehension on the export thread; closing it after that swap costs an incident.

    Returns the scrubbed links and whether anything changed, so the no-op fast path in
    `_redact_span` stays a no-op.
    """
    from opentelemetry.trace import Link

    clean: list[Any] = []
    changed = False
    for link in links or ():
        original = dict(link.attributes or {})
        safe = sanitize_attributes(original)
        changed = changed or safe != original
        clean.append(Link(link.context, safe))
    return clean, changed


def _redacted_status(status: Any, exception_type: str | None) -> Any:
    """Keep the status CODE, replace its description with the exception type.

    The SDK writes `"<type>: <message>"`. Splitting that string to keep the head would
    be guessing at a format; the type is already on the exception event, so it is read
    from there instead.
    """
    if status is None or not getattr(status, "description", None):
        return status
    from opentelemetry.trace.status import Status

    _note_dropped(_STATUS_DESCRIPTION_KEY)
    return Status(status.status_code, description=exception_type)


def _redact_span(readable: Any) -> Any:
    """A copy of `readable` with nothing hard rule 6 forbids left in it."""
    from opentelemetry.sdk.trace import ReadableSpan

    original = dict(readable.attributes or {})
    attributes = sanitize_attributes(original)
    events, exception_type = _redacted_events(readable.events)
    status = _redacted_status(readable.status, exception_type)
    links, links_changed = _redacted_links(readable.links)
    # `redact_text` on the NAME because a span name is a format string somebody may one
    # day interpolate an id — or worse — into. Names are code-authored and low
    # cardinality by design, so this is a backstop, not the guard.
    name = redact_text(readable.name)
    if (
        name == readable.name
        and attributes == original
        and not events
        and not links_changed
        and status is readable.status
    ):
        return readable  # the common case: nothing to change, nothing to allocate
    return ReadableSpan(
        name=name,
        context=readable.context,
        parent=readable.parent,
        resource=readable.resource,
        attributes=attributes,
        events=events,
        links=links,
        kind=readable.kind,
        instrumentation_scope=readable.instrumentation_scope,
        status=status,
        start_time=readable.start_time,
        end_time=readable.end_time,
    )


class _RedactingSpanExporter:
    """Wraps the real exporter so no span reaches a vendor unscrubbed.

    Duck-typed rather than subclassing `SpanExporter`, so this module keeps its
    no-opentelemetry-import-at-module-scope property (hard rule 3).
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def export(self, spans: Any) -> Any:
        safe: list[Any] = []
        for readable in spans:
            try:
                safe.append(_redact_span(readable))
            except Exception:
                # FAIL CLOSED. A span we could not scrub is a span we do not send: the
                # alternative is exporting the unfiltered original, which is the exact
                # outcome this class exists to prevent. The counter says it happened.
                _note_dropped("span.redaction_failed")
        return self._inner.export(safe)

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return bool(self._inner.force_flush(timeout_millis))


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


def current_trace_id() -> str | None:
    """The active trace id as 32 lowercase hex chars, or None when tracing is off.

    The join key between OTel and Langfuse. Derived from the traceparent rather than
    from `opentelemetry.trace` directly so this module keeps its "no SDK import at
    module scope" property (hard rule 3), and so there is exactly one definition of
    what "the current trace" means for both the queue hop and the LLM trace.
    """
    traceparent = current_traceparent()
    if not traceparent:
        return None
    parts = traceparent.split("-")
    # 00-<32 hex trace id>-<16 hex span id>-<flags>. An all-zero trace id is the
    # invalid context OTel hands back outside any span; it is not a link to anything.
    if len(parts) < 3 or len(parts[1]) != 32 or parts[1] == "0" * 32:
        return None
    return parts[1]


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
    #
    # The scrub wraps the exporter INSIDE the batch processor, so it runs on the export
    # thread rather than the caller's, and it wraps an injected `span_exporter` too:
    # a test that could see an unfiltered span would be testing a pipeline production
    # does not have.
    # `Any` because the wrapper is duck-typed rather than a `SpanExporter` subclass —
    # that is what keeps opentelemetry out of this module's import scope (hard rule 3).
    redacting_exporter: Any = _RedactingSpanExporter(span_exporter)
    provider.add_span_processor(BatchSpanProcessor(redacting_exporter))
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


# --- Readiness ladder: is a component that is DECLARED ON actually on? --------
#
# THE STATE THIS EXISTS FOR IS THE MIDDLE ONE. "Off" is already loud — `init_observability`
# logs `observability_local_only` — and "on and working" needs nothing said about it. What
# had no name in this module was ON AND SILENTLY BROKEN: a DSN whose project id is a typo,
# an OTLP endpoint that already ends in `/v1/traces` so the exporter appends a second one,
# a sample ratio of 0.0 (configured, wired, exporting nothing), a release that still reads
# `dev` on a production host so no report names the deploy that produced it. Every one of
# those boots green, reports nothing, and says nothing — which is indistinguishable, from
# the outside, from a platform that simply is not failing.
#
# WHAT IS DECIDABLE HERE, AND WHAT IS DELIBERATELY NOT. **Configuration validity** is
# decidable in this process with no network and no credential: a DSN either names a
# project or it does not. **Reachability is not**, and this module must never simulate it.
# A function that "verified Sentry" by parsing a string would be an unverified vendor
# behaviour presented as an observation — the defect class D-31/D-32 exist for, one layer
# further in. Whether an event is ACCEPTED by the vendor, whether the collector answers,
# and whether a human sees either, are OPERATIONS §2 gate 15: performed once against the
# real hosts with the real credentials, and recorded there.
#
# These are pure functions over `Settings` so that ONE definition serves both readers —
# `init_observability` logs them at boot, and `scripts/check_observability_ready.py` runs
# them ahead of a deploy. A guard the deploy applies and the process does not is a guard
# that only covers the machines somebody remembered to run it on.

#: Component is not configured. Nothing to verify, nothing wrong. (Reference shape:
#: disabled must SKIP cleanly, or every local run learns to ignore the check.)
READINESS_SKIPPED = "skipped"
#: Configured, and every setting it needs is present and internally consistent.
READINESS_READY = "ready"
#: Configured and broken. The rung this whole ladder exists for.
READINESS_MISCONFIGURED = "misconfigured"


@dataclass(frozen=True)
class ReadinessProblem:
    """One specific thing that is wrong, named.

    `code` is a stable token safe to log and to alert on; `message` is the sentence an
    operator acts on. NEITHER MAY CARRY A VALUE — hard rule 6 covers PII, and a DSN is a
    credential besides, so both halves name FIELDS and shapes and never contents.
    """

    code: str
    message: str


@dataclass(frozen=True)
class ComponentReadiness:
    component: str
    status: str
    #: Why it is skipped, or what it is when ready. One sentence, value-free.
    summary: str
    problems: tuple[ReadinessProblem, ...] = ()


#: The exporter `init_tracing` builds. Named here so the readiness answer and the thing
#: actually constructed cannot drift into disagreeing about which package is required.
_OTLP_HTTP_TRACE_EXPORTER = "opentelemetry.exporter.otlp.proto.http.trace_exporter"


def _carries_a_url_tail(value: str) -> bool:
    """Does this configured URL carry a `?…` or `#…` tail?

    Asked of the RAW string rather than of `urlsplit`'s parts on purpose: neither a Sentry
    DSN nor an OTLP base endpoint may contain either character anywhere, and a `#` that
    landed in the userinfo is a paste accident `urlsplit` would apportion somewhere this
    check was not looking.
    """
    return "?" in value or "#" in value


def _module_installed(name: str) -> bool:
    """Is this module importable, WITHOUT importing it (hard rule 3)?

    `find_spec` raises rather than returning None when a PARENT package is missing, which
    is exactly the case being asked about, so the exception is the answer here.
    """
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _release_problem(settings: Settings) -> ReadinessProblem | None:
    """A telemetry stream that cannot name its build.

    Only a defect off `local`: `dev` is the correct answer on a laptop, and failing there
    would train everyone to ignore this ladder before it ever ran against a deploy.
    """
    if settings.app_env == "local" or settings.release_version != "dev":
        return None
    return ReadinessProblem(
        "release_version_default",
        "RELEASE_VERSION is still the `dev` default on a non-local deployment, so every "
        "report and every span claims the same build and none of them can be tied to a "
        "commit. CI sets it from the commit sha (DEPLOYMENT §8).",
    )


def _dsn_problems(dsn: str) -> list[ReadinessProblem]:
    """Sentry DSN shape: `<scheme>://<public key>@<host>/<numeric project id>`.

    Checked HERE rather than left to `sentry_sdk.init` for one reason: init runs on the
    host, at boot, and its refusal is a boot-time event nobody is watching. This runs
    before the deploy. The SDK's own parser is still consulted below when it is installed
    — it is the authority on what it will accept — and these rules exist so a host
    WITHOUT the optional `errors` group can still catch a typo.
    """
    problems: list[ReadinessProblem] = []
    split = urlsplit(dsn)
    if split.scheme not in {"http", "https"}:
        problems.append(
            ReadinessProblem(
                "dsn_scheme_unsupported",
                "SENTRY_DSN does not start with http:// or https://. A DSN copied out of "
                "the Sentry UI always does; a value that does not is usually a project "
                "name or an auth token pasted into the wrong field.",
            )
        )
    if not split.username:
        problems.append(
            ReadinessProblem(
                "dsn_no_public_key",
                "SENTRY_DSN carries no public key (the `<key>@` part). Without it every "
                "event is rejected by the ingest endpoint and the SDK reports nothing.",
            )
        )
    if not split.hostname:
        problems.append(
            ReadinessProblem(
                "dsn_no_host", "SENTRY_DSN names no host, so there is nowhere to send to."
            )
        )
    if _carries_a_url_tail(dsn):
        problems.append(
            ReadinessProblem(
                "dsn_has_query_or_fragment",
                "SENTRY_DSN contains a `?` or `#`. A DSN has neither — the value has "
                "picked up something from a copy/paste.",
            )
        )
    project_id = split.path.rsplit("/", 1)[-1]
    if not project_id:
        problems.append(
            ReadinessProblem(
                "dsn_no_project_id",
                "SENTRY_DSN ends without a project id, so events have no project to land in.",
            )
        )
    elif not project_id.isdigit():
        # sentry_sdk.utils.Dsn raises BadDsn on a non-integer project id, so this is the
        # SDK's own rule restated where it can be read before the process boots.
        problems.append(
            ReadinessProblem(
                "dsn_project_id_not_numeric",
                "SENTRY_DSN's last path segment is not a number. Sentry project ids are "
                "numeric and the SDK refuses anything else at init.",
            )
        )
    return problems


def sentry_readiness(settings: Settings) -> ComponentReadiness:
    """Sentry: declared on by `SENTRY_DSN`, and then either usable or silently absent."""
    dsn = (settings.sentry_dsn or "").strip()
    if not dsn:
        return ComponentReadiness(
            "sentry",
            READINESS_SKIPPED,
            "SENTRY_DSN is unset: errors are written to the service log and to nowhere "
            "else. That is the local and CI default; on a client-serving deployment it "
            "is OPERATIONS §8's unfinished business, not this check's failure.",
        )
    problems = _dsn_problems(dsn)
    try:
        import sentry_sdk.utils
    except ImportError:
        problems.append(
            ReadinessProblem(
                "sdk_missing",
                "SENTRY_DSN is set and `sentry-sdk` is not installed, so "
                "`init_observability` logs `sentry_dsn_set_but_sdk_missing` and reports "
                "nothing for the life of the process. Install the optional group: "
                "`uv sync --all-packages --group errors` (pyproject `[dependency-groups] "
                "errors`).",
            )
        )
    else:
        try:
            sentry_sdk.utils.Dsn(dsn)
        except Exception:
            # The vendor's parser is the authority on what it accepts; ours above says
            # WHICH part is wrong. Both, because either alone leaves a gap: theirs is
            # unavailable without the optional package, ours is a restatement.
            problems.append(
                ReadinessProblem(
                    "dsn_rejected_by_sdk",
                    "`sentry_sdk.utils.Dsn` refuses this value, so `sentry_sdk.init` "
                    "would raise at boot. The exception text is deliberately not "
                    "reproduced here: it echoes the DSN.",
                )
            )
    release = _release_problem(settings)
    if release is not None:
        problems.append(release)
    if problems:
        return ComponentReadiness(
            "sentry",
            READINESS_MISCONFIGURED,
            "SENTRY_DSN is set, so this deployment believes errors are being reported.",
            tuple(problems),
        )
    return ComponentReadiness(
        "sentry",
        READINESS_READY,
        "DSN is well formed, the SDK is installed, and the release is named. Whether the "
        "project ACCEPTS an event is OPERATIONS §2 gate 15, not this check.",
    )


def tracing_readiness(settings: Settings) -> ComponentReadiness:
    """OpenTelemetry: declared on by `OTEL_EXPORTER_OTLP_ENDPOINT`."""
    endpoint = (settings.otel_exporter_otlp_endpoint or "").strip()
    if not endpoint:
        return ComponentReadiness(
            "otel",
            READINESS_SKIPPED,
            "OTEL_EXPORTER_OTLP_ENDPOINT is unset: `init_tracing` returns False without "
            "importing the SDK, and `span()` is a generator frame. That is the documented "
            "local default.",
        )
    problems: list[ReadinessProblem] = []
    split = urlsplit(endpoint)
    if not split.scheme or not split.netloc:
        problems.append(
            ReadinessProblem(
                "endpoint_not_absolute",
                "OTEL_EXPORTER_OTLP_ENDPOINT is not an absolute URL. The exporter is "
                "constructed with this value plus `/v1/traces`; a bare host or path "
                "produces a URL the exporter retries against forever, off-thread, "
                "silently.",
            )
        )
    elif split.scheme not in {"http", "https"}:
        problems.append(
            ReadinessProblem(
                "endpoint_scheme_unsupported",
                "OTEL_EXPORTER_OTLP_ENDPOINT names a scheme this deployment cannot "
                "export to. `init_tracing` builds the OTLP/**HTTP** exporter, so the "
                "value must be http:// or https:// — a `grpc://` endpoint is the other "
                "protocol's spelling and would need the other exporter package.",
            )
        )
    if _carries_a_url_tail(endpoint):
        problems.append(
            ReadinessProblem(
                "endpoint_has_query_or_fragment",
                "OTEL_EXPORTER_OTLP_ENDPOINT contains a `?` or `#`. The signal path is "
                "appended to the raw string, so the result is `...?token=x/v1/traces` — "
                "a 404 on every batch, on a background thread, forever.",
            )
        )
    if endpoint.rstrip("/").endswith("/v1/traces"):
        # The single commonest OTLP misconfiguration, and it is invisible: the collector
        # answers 404 on a background thread and the process never mentions it. It comes
        # from the two env vars the spec defines — the SIGNAL-specific
        # `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is the full path, the BASE
        # `OTEL_EXPORTER_OTLP_ENDPOINT` this repo reads is not.
        problems.append(
            ReadinessProblem(
                "endpoint_already_names_the_signal_path",
                "OTEL_EXPORTER_OTLP_ENDPOINT already ends in `/v1/traces`. This setting "
                "is the BASE endpoint and `init_tracing` appends the signal path itself, "
                "so the exporter would POST to `/v1/traces/v1/traces`. Drop the suffix.",
            )
        )
    if settings.otel_traces_sample_ratio == 0.0:
        problems.append(
            ReadinessProblem(
                "sample_ratio_zero",
                "OTEL_TRACES_SAMPLE_RATIO is 0.0, so the provider, the exporter thread "
                "and the middleware are all built and no root trace is ever sampled. "
                "Tracing that is configured and exports nothing is the exact state this "
                "ladder exists to name; set a ratio above 0 or unset the endpoint.",
            )
        )
    # `find_spec`, not `import`: this runs during `init_observability`, which
    # `apps/voice-runtime` calls at boot, and hard rule 3 keeps that import graph small.
    # Asking whether a module is INSTALLABLE costs a path lookup; importing it would cost
    # the ~300ms `init_tracing`'s own comment measures, on a service that answers calls.
    missing = [
        name
        for name in ("opentelemetry.sdk.trace", _OTLP_HTTP_TRACE_EXPORTER)
        if not _module_installed(name)
    ]
    if missing:
        problems.append(
            ReadinessProblem(
                "sdk_missing",
                "OTEL_EXPORTER_OTLP_ENDPOINT is set and "
                f"{', '.join(missing)} is not installed, so `init_tracing` logs "
                "`otel_endpoint_set_but_sdk_missing` and returns False: the endpoint is "
                "configured and no span will ever be built.",
            )
        )
    release = _release_problem(settings)
    if release is not None:
        problems.append(release)
    if problems:
        return ComponentReadiness(
            "otel",
            READINESS_MISCONFIGURED,
            "OTEL_EXPORTER_OTLP_ENDPOINT is set, so this deployment believes it is tracing.",
            tuple(problems),
        )
    return ComponentReadiness(
        "otel",
        READINESS_READY,
        "Endpoint is a base URL the exporter can extend, the ratio samples something, and "
        "the SDK is installed. Whether the collector ACCEPTS a batch is OPERATIONS §2 "
        "gate 15.",
    )


def observability_readiness(settings: Settings) -> tuple[ComponentReadiness, ...]:
    """The ladder, in the order an operator reads it.

    Langfuse is absent from this tuple ON PURPOSE and is not an oversight: it has no
    setting to be declared on BY (D-49 removed the keys rather than leaving them looking
    wired), so "is Langfuse on" is a question about the SHAPE OF THE TREE — an import, a
    dependency, a client — and not about this process's configuration.
    `scripts/check_observability_ready.py` owns that rung, and it has to: answering it
    needs an AST walk over the repository, which is precisely what hard rule 3 forbids
    this module from importing.
    """
    return (sentry_readiness(settings), tracing_readiness(settings))


def init_observability(service: str) -> str:
    """Called from `create_app` before the app object exists. Returns what was enabled,
    for the startup log line — an operator should be able to see at a glance whether
    errors are actually going anywhere."""
    settings = get_settings()
    enabled: list[str] = []

    # Which process this is, stamped into every alert subject. Done here because this
    # is the one function every service already calls with its own name, and "which
    # process" is the first question an operator asks at 3am.
    configure_alerts(service=service)
    if settings.alerts_email:
        enabled.append("alerts:email")
        # THE SAME RESOLVER `get_transport()` USES, never a second read of the same
        # fields. It used to be `not settings.smtp_host` here, which stopped being the
        # question the moment `EMAIL_PROVIDER` existed — this line would have warned at
        # every boot of a perfectly good Resend deployment. `email_transport_reason`
        # lives in `calevate_shared.config` precisely so this check can call it:
        # voice-runtime boots through here and may not import `apps.workers`
        # (hard rule 3).
        transport_gap = email_transport_reason(settings)
        if transport_gap is not None:
            # A recipient with nothing to carry the mail: `get_transport()` is the
            # authority on selection and will hand back `NullTransport`, which refuses
            # loudly — but it refuses at 3am, and this refuses at boot. The reason rides
            # along so the operator does not have to guess which half is missing.
            log.warning(
                "alert_delivery_has_no_transport",
                extra={"service": service, "reason": transport_gap},
            )
    elif settings.app_env != "local":
        # Not a crash: a service whose job is answering calls must boot without a
        # mailbox. But a deployment where alerts reach nobody is OPERATIONS §8's
        # pre-launch gate failing, and it says so at boot rather than at 3am.
        log.warning("alert_delivery_unconfigured", extra={"service": service})

    # THE LADDER, AT BOOT. `scripts/check_observability_ready.py` is the same verdict
    # taken before the deploy; this is the one taken on the machine that actually holds
    # the configuration, because a deployment nobody ran the script against is exactly
    # the deployment where a typo survives. CODES only, never values: a DSN is a
    # credential and hard rule 6 covers the rest.
    for readiness in observability_readiness(settings):
        if readiness.status == READINESS_MISCONFIGURED:
            log.warning(
                "observability_component_misconfigured",
                extra={
                    "service": service,
                    "component": readiness.component,
                    "problems": [problem.code for problem in readiness.problems],
                },
            )

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
                # NO FRAME LOCALS, and this is the one Sentry default that beat the
                # scrubber. `include_local_variables` defaults to TRUE, so every captured
                # exception shipped a snapshot of each frame's locals — and `serialize()`
                # runs BEFORE `before_send` (sentry_sdk/client.py `_prepare_event`), so
                # `scrub_event` meets them already flattened to `repr` strings and can
                # only apply `redact_mapping`: key patterns plus phone-shaped digit runs.
                # MEASURED against a real `sentry_sdk.Client` with these exact options,
                # crashing inside a function shaped like `notifications._compose`:
                # `phone` and `billing_email` came out `[redacted]` (the keys match), and
                # `name` came out `'Ravi Kumar'` and `summary` came out
                # `'Caller asked for a callback.'` — a caller's captured name and the
                # transcript-derived call summary, verbatim, to a third-party error
                # tracker. Neither key matches `REDACT_KEYS` and neither value is
                # phone-shaped, which is the whole point: a local's NAME is chosen for
                # readability, not for a denylist.
                #
                # Withholding rather than filtering, for the reason this module already
                # gives twice — `logging.redact_exception` and `exception.values[].value`
                # above: there is no way to prove an arbitrary runtime string is not one
                # of hard rule 6's three data classes, and frame locals are runtime
                # values BY CONSTRUCTION, so they are strictly the worse case of the one
                # the exception message already lost. What a Sentry issue keeps is what
                # the log traceback keeps — the type, the frames, the source line — plus
                # our own `extra`/`logentry` (scrubbed, and where ids are deliberately
                # put) and the `otel_trace_id` tag that joins it to the trace.
                #
                # `scrub_event`'s frame-vars walk STAYS as the backstop: this keyword is
                # what stops them being collected, that walk is what catches them if a
                # future integration or an SDK default puts them back.
                include_local_variables=False,
                # CAST, and the cast is the honest expression of a real difference.
                # `sentry_sdk.init` types these as `Callable[[Event, Hint], Event | None]`
                # where `Event` is the SDK's TypedDict. Ours are typed on plain dicts on
                # purpose: they are unit-tested directly, and the whole module must import
                # and be checkable on a host where sentry-sdk is NOT installed (the import
                # above is inside this branch for exactly that reason). A `dict[str, Any]`
                # is not a supertype of a TypedDict to mypy, so the widening cannot be
                # expressed in the signature without dragging an optional dependency into
                # the module's type surface.
                #
                # THIS LINE WAS INVISIBLE TO CI UNTIL NOW. CI ran `uv sync --all-packages`
                # while the Dockerfile and DEPLOYMENT §8 install `--group errors`, so mypy
                # only ever saw the branch with sentry-sdk ABSENT — where the import is
                # unresolved, `ignore_missing_imports` makes every symbol `Any`, and any
                # signature at all type-checks. sentry-sdk ships `py.typed`; the moment it
                # is installed the real types arrive and this errors. The mypy job now
                # installs the same group production does, which is what makes the cast a
                # decision rather than a thing nobody could see.
                # `type: ignore`, NOT a `cast`. The expression must stay literally
                # `before_send=scrub_event`, because `check_sentry_hooks` reads this line
                # and refuses anything else — "the hook is the enforcement point for hard
                # rule 6 on the error path; a different function there is a different
                # guarantee, and this check cannot judge it". A cast satisfied mypy and
                # blinded that guard, which is a worse trade than the one below.
                before_send=scrub_event,  # type: ignore[arg-type]
                before_breadcrumb=scrub_breadcrumb,
                # NO `traces_sample_rate`. It used to be 0.1/1.0, which turned on
                # Sentry's own performance tracing — a SECOND tracing pipeline beside
                # the OTel one, carrying SQL descriptions and full outbound URLs, and
                # `before_send` DOES NOT RUN ON TRANSACTION EVENTS (Sentry's docs:
                # transactions need `before_send_transaction`; that gap is why the hook
                # exists at all — getsentry/sentry-python#1226). So it shipped spans
                # this module's scrubber never saw. One tracing pipeline per problem,
                # and the one we keep is the one whose exporter is filtered.
            )
            sentry_sdk.set_tag("service", service)
            enabled.append("sentry")
        except ImportError:
            # Tolerant boot (BACKEND-PATTERNS §2): a missing optional package must not
            # take down a service whose actual job is answering calls.
            log.warning("sentry_dsn_set_but_sdk_missing")
        except ValueError as exc:
            # `sentry_sdk.utils.BadDsn` subclasses ValueError, and it is what `init`
            # raises on a malformed DSN. Until this branch existed a single typo in a
            # console-managed field (`sentry_dsn` is `on_restart`, PLATFORM-CONFIG) took
            # voice-runtime DOWN at boot — the opposite of this module's own contract two
            # paragraphs into its docstring ("a misconfigured deploy degrades rather than
            # crashes"), and on the one service whose job is answering a telephone.
            #
            # The exception is NOT logged: `BadDsn`'s message echoes the DSN, which is a
            # credential. The type name and the readiness code above are what an operator
            # needs, and `dsn_rejected_by_sdk` from the ladder says the same thing before
            # the deploy rather than after it.
            log.warning(
                "sentry_dsn_rejected",
                extra={"service": service, "error": type(exc).__name__},
            )

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
    "READINESS_MISCONFIGURED",
    "READINESS_READY",
    "READINESS_SKIPPED",
    "REDACT_KEYS",
    "TRACE_KWARG",
    "ComponentReadiness",
    "ReadinessProblem",
    "TracingMiddleware",
    "current_trace_id",
    "current_traceparent",
    "dropped_attribute_keys",
    "init_observability",
    "init_tracing",
    "observability_readiness",
    "reset_tracing",
    "sanitize_attributes",
    "scrub_breadcrumb",
    "scrub_event",
    "sentry_readiness",
    "set_span_attributes",
    "shutdown_tracing",
    "span",
    "traced_job",
    "tracing_enabled",
    "tracing_readiness",
]
