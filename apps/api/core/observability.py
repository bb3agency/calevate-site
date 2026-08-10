"""Observability init — Sentry, tracing, and the Langfuse redaction hook.

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
"""

from __future__ import annotations

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

    if not enabled:
        log.info("observability_local_only", extra={"service": service})
    return ",".join(enabled) or "none"


__all__ = [
    "DROP_HEADERS",
    "REDACT_KEYS",
    "init_observability",
    "redact_trace_payload",
    "scrub_event",
]
