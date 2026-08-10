"""The error tracker must not become the PII leak (hard rule 6).

An error tracker is a searchable log with attachments. Sentry captures local variables
and request bodies by default, which on this codebase means capturing a transcript the
first time anything throws inside the post-call pipeline. These tests pin the scrubber
against exactly that.
"""

from __future__ import annotations

import json

from apps.api.core.observability import redact_trace_payload, scrub_event

PHONE = "9876543210"
TRANSCRIPT = "caller: naa number 9876543210, naa peru Ravi"


def test_authorization_and_tenant_headers_never_leave_the_process() -> None:
    event = {
        "request": {
            "headers": {
                "Authorization": "Bearer super-secret-token",
                "X-Org-Slug": "sunrise-clinic",
                "X-Impersonate-Org": "sunrise-clinic",
                "User-Agent": "Mozilla/5.0",
            }
        }
    }
    scrubbed = scrub_event(event)
    assert scrubbed is not None
    headers = scrubbed["request"]["headers"]
    assert headers["Authorization"] == "[redacted]"
    assert headers["X-Org-Slug"] == "[redacted]"
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


def test_the_langfuse_hook_scrubs_a_prompt_containing_a_transcript() -> None:
    """An LLM trace is the richest PII object we produce: the prompt contains the
    transcript. CLAUDE.md requires it to go through the redaction hook."""
    payload = redact_trace_payload(
        {"model": "sarvam-m", "prompt": TRANSCRIPT, "extraction": {"name": "Ravi"}}
    )
    serialized = json.dumps(payload)
    assert PHONE not in serialized
    assert payload["model"] == "sarvam-m", "non-PII metadata must survive to be useful"


def test_an_event_is_never_dropped_entirely() -> None:
    """Knowing an error happened is itself the point — scrubbing must degrade the
    detail, not the signal."""
    assert scrub_event({"message": f"failed for +91{PHONE}"}) is not None
