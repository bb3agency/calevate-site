"""The error tracker must not become the PII leak (hard rule 6).

An error tracker is a searchable log with attachments. Sentry captures local variables
and request bodies by default, which on this codebase means capturing a transcript the
first time anything throws inside the post-call pipeline. These tests pin the scrubber
against exactly that.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import sentry_sdk
from apps.api.core.logging import REDACTED
from apps.api.core.observability import scrub_breadcrumb, scrub_event

PHONE = "9876543210"
TRANSCRIPT = "caller: naa number 9876543210, naa peru Ravi"


def test_authorization_and_tenant_headers_never_leave_the_process() -> None:
    event = {
        "request": {
            "headers": {
                "Authorization": "Bearer super-secret-token",
                "X-Org-Slug": "sunrise-clinic",
                "X-Impersonate-Org": "sunrise-clinic",
                "X-Impersonation-Grant": "eyJhbGciOiJIUzI1NiJ9.signed.grant",
                "User-Agent": "Mozilla/5.0",
            }
        }
    }
    scrubbed = scrub_event(event)
    assert scrubbed is not None
    headers = scrubbed["request"]["headers"]
    assert headers["Authorization"] == "[redacted]"
    assert headers["X-Org-Slug"] == "[redacted]"
    assert headers["X-Impersonate-Org"] == "[redacted]"
    # The strongest reason on the list: paired with an operator's admin session this
    # token opens a client's account, and a crash report is where one would be captured.
    assert headers["X-Impersonation-Grant"] == "[redacted]"
    # Harmless headers survive — an unusable report is its own failure mode.
    assert headers["User-Agent"] == "Mozilla/5.0"


def test_the_request_body_is_dropped_entirely() -> None:
    """A webhook body is a transcript; a lead POST is a phone number. Neither is worth
    the debugging convenience."""
    event = {"request": {"data": {"transcript": TRANSCRIPT, "phone": f"+91{PHONE}"}}}
    scrubbed = scrub_event(event)
    assert scrubbed is not None
    assert "data" not in scrubbed["request"]


def test_a_phone_number_in_a_query_string_is_masked() -> None:
    """The leads search filter accepts a phone suffix, so query strings are PII too."""
    event = {"request": {"query_string": f"search=+91{PHONE}&status=hot"}}
    scrubbed = scrub_event(event)
    assert scrubbed is not None
    assert PHONE not in scrubbed["request"]["query_string"]


def test_local_variables_in_a_stack_frame_are_scrubbed() -> None:
    """This is the case that actually bites: the pipeline throws, and the frame holds
    the transcript it was mid-way through redacting."""
    event = {
        "exception": {
            "values": [
                {
                    "stacktrace": {
                        "frames": [
                            {
                                "function": "run_post_call_pipeline",
                                "vars": {
                                    "transcript_text": TRANSCRIPT,
                                    "phone_e164": f"+91{PHONE}",
                                    "call_id": "019f-…",
                                },
                            }
                        ]
                    }
                }
            ]
        }
    }
    scrubbed = scrub_event(event)
    assert scrubbed is not None
    frame_vars = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
    assert PHONE not in json.dumps(frame_vars)
    assert "Ravi" not in json.dumps(frame_vars)
    # The id survives, which is what a debugger actually needs (hard rule 6: log ids).
    assert frame_vars["call_id"] == "019f-…"


def test_a_log_breadcrumb_is_scrubbed_before_it_is_taken() -> None:
    """Breadcrumbs were the hole beside `scrub_event`.

    Sentry's logging integration builds a breadcrumb from `record.getMessage()` — our
    JsonFormatter never runs on it — so an unscrubbed breadcrumb rides out attached to
    the next error event.
    """
    crumb = scrub_breadcrumb(
        {"type": "log", "message": f"delivering to +91{PHONE}", "data": {"transcript": TRANSCRIPT}}
    )
    assert crumb is not None
    serialized = json.dumps(crumb)
    assert PHONE not in serialized
    assert "Ravi" not in serialized
    assert crumb["type"] == "log", "the signal survives; only the values are taken"


def test_an_outbound_url_breadcrumb_keeps_no_query_string() -> None:
    """A client webhook target carries its own credential in the query string (D-23),
    and it is neither a phone nor a redacted key — `redact_mapping` alone lets it out."""
    crumb = scrub_breadcrumb(
        {
            "type": "http",
            "data": {"url": "https://hooks.zapier.com/x/abc?token=s3cret", "status_code": 200},
        }
    )
    assert crumb is not None
    assert crumb["data"]["url"] == "https://hooks.zapier.com/x/abc"
    assert crumb["data"]["status_code"] == 200, "the useful half of the breadcrumb survives"


def test_an_event_is_never_dropped_entirely() -> None:
    """Knowing an error happened is itself the point — scrubbing must degrade the
    detail, not the signal."""
    assert scrub_event({"message": f"failed for +91{PHONE}"}) is not None


# --- the three fields `before_send` used to walk straight past --------------------


def test_the_exception_message_is_scrubbed() -> None:
    """`exception.values[].value` is `str(exc)` plus `__notes__`
    (`sentry_sdk.utils.single_exception_from_error_tuple` → `get_error_message`), and it
    is the string Sentry shows as the TITLE of the issue.

    It shipped raw while the OTel exporter in the same module was dropping the identical
    field off every span. `hide_parameters=True` covers the driver-error spelling; it
    covers nothing about a `ValueError` raised inside the pipeline with the turn it was
    mid-way through processing.

    One entry per link of a chained exception, because `raise … from …` is how the
    pipeline's error ladder reports and the cause is where the original message lives.
    """
    event = {
        "exception": {
            "values": [
                {"type": "KeyError", "value": TRANSCRIPT},
                {"type": "ValueError", "value": f"extraction failed at +91{PHONE}"},
            ]
        }
    }
    scrubbed = scrub_event(event)
    assert scrubbed is not None
    serialized = json.dumps(scrubbed["exception"])
    assert PHONE not in serialized
    assert "naa number" not in serialized, "the cause's message is scrubbed too"
    # The TYPE survives: it is a class name from our own import graph, it is what Sentry
    # groups on, and it is what the alert path now fingerprints on.
    assert scrubbed["exception"]["values"][0]["type"] == "KeyError"


def test_the_logging_integrations_logentry_is_scrubbed() -> None:
    """`logentry`, not `message`, is what the SDK writes for every `log.error` in this
    repo (`sentry_sdk/integrations/logging.py::_emit` sets
    `{"message", "formatted", "params"}`). `event["message"]` — the only spelling this
    hook knew — is the legacy field, and `params` is `record.args`: the exact values a
    `%`-style call interpolated.
    """
    event = {
        "logentry": {
            "message": "delivering to %s",
            "formatted": f"delivering to +91{PHONE}",
            "params": [f"+91{PHONE}", TRANSCRIPT],
        }
    }
    scrubbed = scrub_event(event)
    assert scrubbed is not None
    serialized = json.dumps(scrubbed["logentry"])
    assert PHONE not in serialized
    assert "Ravi" not in serialized
    assert scrubbed["logentry"]["message"] == "delivering to %s", "the event name survives"


def test_breadcrumbs_attached_to_an_event_are_scrubbed_again() -> None:
    """`before_breadcrumb` normally cleans these at capture. It is also one `init` edit
    away from not being installed, and this hook is the seam where the crumbs actually
    leave the process — so they are re-scrubbed where the event is."""
    event = {
        "breadcrumbs": {
            "values": [
                {"type": "log", "message": f"lead +91{PHONE}", "data": {"transcript": TRANSCRIPT}}
            ]
        }
    }
    scrubbed = scrub_event(event)
    assert scrubbed is not None
    assert PHONE not in json.dumps(scrubbed["breadcrumbs"])


def test_request_cookies_are_dropped_not_merely_header_scrubbed() -> None:
    """`cookies` is a SIBLING of `headers` in Sentry's request interface, so
    `DROP_HEADERS` never sees it. Only populated under `send_default_pii=True` — which
    is off, and which is a one-word edit away from being on."""
    event = {"request": {"headers": {"Host": "app.calevate.tech"}, "cookies": {"__session": "x"}}}
    scrubbed = scrub_event(event)
    assert scrubbed is not None
    assert "cookies" not in scrubbed["request"]
    assert scrubbed["request"]["headers"]["Host"] == "app.calevate.tech"


# --- The SDK's own capture, driven for real ------------------------------------
#
# Everything above hands `scrub_event` a hand-built event, which tests the hook and
# nothing else. The hook is not the whole control: `sentry_sdk` decides WHAT to collect
# before the hook decides what to keep, and `serialize()` runs BEFORE `before_send`
# (`sentry_sdk/client.py::_prepare_event`) — so a value the SDK gathers arrives already
# flattened to a `repr` string, with only `redact_mapping`'s key patterns and phone
# regex left to judge it. The tests below therefore drive a REAL client with the real
# options and read the envelope, which is the only way to see that difference.


class _CapturingTransport(sentry_sdk.transport.Transport):
    """Every envelope the client would have sent, kept in memory."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Any) -> None:
        for item in envelope.items:
            payload = item.payload.json
            if payload is not None:
                self.events.append(payload)


@contextmanager
def _capturing_client(**overrides: Any) -> Iterator[_CapturingTransport]:
    """A client configured exactly as `init_observability` configures it.

    The options are spelled here rather than read out of `init_observability`, because
    that function needs a DSN, a settings object and a live `configure_alerts`. What
    keeps the two in step is `scripts/check_observability_ready.check_sentry_hooks`,
    which fails the build if `sentry_sdk.init` stops passing any of them —
    `tests/observability_readiness_guard_test.py::TestSentryHooks` is that half.
    """
    transport = _CapturingTransport()
    options: dict[str, Any] = {
        "dsn": "https://public@o0.ingest.example.invalid/1",
        "environment": "local",
        "send_default_pii": False,
        "max_request_body_size": "never",
        "include_local_variables": False,
        "before_send": scrub_event,
        "before_breadcrumb": scrub_breadcrumb,
        "transport": transport,
    }
    client = sentry_sdk.Client(**{**options, **overrides})
    scope = sentry_sdk.get_global_scope()
    previous = scope.client
    scope.set_client(client)
    try:
        yield transport
    finally:
        client.close()
        scope.set_client(previous)


def _crash_holding_a_lead() -> None:
    """The shape `workers/notifications._compose` and `crm.service._lead_out` both have
    in scope when something throws: a captured name, a number, an owner address and the
    transcript-derived summary, as four ordinary locals."""
    # `noqa: F841` FOUR TIMES, and the unusedness is the subject: what Sentry captures
    # is the frame's locals, so a variable that were read afterwards would prove nothing
    # the raise does not already carry. These four exist to BE locals at the moment of
    # the raise.
    name = "Ravi Kumar"  # noqa: F841
    phone = f"+91{PHONE}"  # noqa: F841
    billing_email = "owner@sunriseclinic.example"  # noqa: F841
    summary = "Caller asked for a callback."  # noqa: F841
    raise ValueError("transport refused")


def test_a_captured_exception_ships_no_frame_locals_at_all() -> None:
    """`include_local_variables=False`, proved by reading the envelope.

    THE LEAK IT CLOSES, measured before it was closed: with the SDK default (True) and
    this exact scrubber, `phone` and `billing_email` came out `[redacted]` — their keys
    match `REDACT_KEYS` — while `name` came out `'Ravi Kumar'` and `summary` came out
    `'Caller asked for a callback.'`. A caller's captured name and the transcript-derived
    call summary, verbatim, to a third-party error tracker. Neither key is on any
    denylist and neither value is phone-shaped, which is the point: a local is named for
    the reader, not for the filter.

    `test_local_variables_in_a_stack_frame_are_scrubbed` above still pins the hook, and
    still matters — it is the backstop for the day an integration puts `vars` back.
    """
    with _capturing_client() as transport:
        try:
            _crash_holding_a_lead()
        except ValueError:
            sentry_sdk.capture_exception()

    assert transport.events, "nothing was captured — the assertions below prove nothing"
    (event,) = transport.events
    frames = event["exception"]["values"][0]["stacktrace"]["frames"]
    assert frames, "the stack is still a stack"
    assert all("vars" not in frame for frame in frames), (
        f"a frame carried its locals: {[f.get('vars') for f in frames if f.get('vars')]}"
    )
    # And the diagnosis survives, which is what makes withholding affordable: the type
    # Sentry titles the issue with, and the frames that say where.
    assert event["exception"]["values"][0]["type"] == "ValueError"
    assert any(frame.get("function") == "_crash_holding_a_lead" for frame in frames)


def test_the_frame_locals_control_is_the_option_and_not_the_scrubber() -> None:
    """The control on the control. An absence proves nothing unless the same crash, with
    the SDK's own default restored, would have carried the value out — so this asserts
    the leak that `include_local_variables=False` exists to stop, rather than trusting
    that the previous test's `vars` were ever going to be there.

    It also pins WHY the scrubber alone is not the answer: the two names below survive
    `redact_mapping` in full, and both are hard rule 6 data (`name` is an extraction
    field, `summary` is transcript-derived prose that
    `scripts/check_redaction_exposure.RAW_TRANSCRIPT_FIELDS` refuses on every response).
    """
    with _capturing_client(include_local_variables=True) as transport:
        try:
            _crash_holding_a_lead()
        except ValueError:
            sentry_sdk.capture_exception()

    (event,) = transport.events
    frames = event["exception"]["values"][0]["stacktrace"]["frames"]
    leaky = next(frame for frame in frames if frame.get("function") == "_crash_holding_a_lead")
    variables = leaky["vars"]
    # The key-based half of `redact_mapping` really does work — these two are covered.
    assert variables["phone"] == REDACTED
    assert variables["billing_email"] == REDACTED
    # And these two are what it cannot see, which is the whole finding.
    assert "Ravi Kumar" in variables["name"]
    assert "callback" in variables["summary"]
