"""The error tracker must not become the PII leak (hard rule 6).

An error tracker is a searchable log with attachments. Sentry captures local variables
and request bodies by default, which on this codebase means capturing a transcript the
first time anything throws inside the post-call pipeline. These tests pin the scrubber
against exactly that.
"""

from __future__ import annotations

import json

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
