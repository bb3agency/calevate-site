"""The vendor's own sentence reaches the operator log, and only in a form we bound.

WHAT THIS FILE IS ABOUT, in one production line (10 Sep 2026 23:22:54):

    {"logger": "apps.api.engine.vendor_http", "msg": "engine_error", "engine": "bolna",
     "status": 400, "route": "/v2/agent", "vendor_error": null}

An operator had pressed Publish. `400` is not `401`, so the key authenticated and the
vendor refused the PAYLOAD — and every fact about WHICH part of it had been discarded by
`_vendor_error_code`, whose docstring argued that the vendor's `message` must never leave
the parser. That argument is sound for `POST /call`, where the field being complained
about is a caller's phone number, and over-broad for `POST /v2/agent`, which carries
prompts and model ids and no contact at all.

The fix is not a per-route allowlist — the vendor writes that string and may echo
anything into it, on any route — so the tests below are written against the BOUNDS
instead, and every one of them drives a route where the old argument was strongest
(`/call`) as well as the one that prompted the change.

**READ FROM `caplog.records`, NOT FROM FORMATTED OUTPUT, AND THAT IS THE POINT OF THE
FILE.** `JsonFormatter` runs `redact_text` over every string extra on its way out, so a
`log.warning(..., extra={"vendor_message": raw})` — the exact regression this guards —
produces clean formatted bytes and a LogRecord holding a caller's number. An assertion
over the formatted line would pass on it. The record is where the redaction has to have
already happened, so the record is what is read. `tests/pii_logging_sweep_test.py` reads
the opposite way for the opposite reason (it is proving the formatter, not the call
site), and the two together are the whole control.

The formatted view is asserted once, on its own question: that `vendor_message` is not a
key `REDACT_KEYS` swallows, which would have made this an elaborate way to log
`[redacted]`.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest
from apps.api.core.logging import JsonFormatter
from apps.api.engine import vendor_http
from apps.api.engine.vendor_http import EngineRejectedError, vendor_request

#: A real-shaped Indian mobile, the same number the rest of the suite uses.
_NUMBER = "+919876543210"

#: The two routes the design tension is between: the one whose error messages quote a
#: caller's number, and the one that prompted the change. Every bound is asserted on
#: BOTH, because none of them is allowed to be a statement about the route.
_ROUTES = ("/call", "/v2/agent")


def _client(response: httpx.Response) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://api.bolna.ai",
        transport=httpx.MockTransport(lambda _request: response),
    )


async def _refuse(response: httpx.Response, *, route: str = "/v2/agent") -> EngineRejectedError:
    with pytest.raises(EngineRejectedError) as raised:
        await vendor_request(_client(response), "POST", route, engine="bolna")
    return raised.value


def _record(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    errors = [r for r in caplog.records if r.getMessage() == "engine_error"]
    assert errors, "the refusal was not logged at all — every assertion below would be vacuous"
    return errors[-1]


def _extra(caplog: pytest.LogCaptureFixture, key: str) -> Any:
    return getattr(_record(caplog), key, None)


def _blob(caplog: pytest.LogCaptureFixture) -> str:
    """Every attribute of every record captured, which is where a leak would hide."""
    return " ".join(f"{r.__dict__}" for r in caplog.records)


async def test_the_publish_refusal_now_says_which_field_the_vendor_refused(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The 23:22:54 line, replayed. This is the whole reason the change exists."""
    for route in _ROUTES:
        caplog.clear()
        with caplog.at_level("DEBUG"):
            raised = await _refuse(
                httpx.Response(400, json={"error": 1002, "message": "agent_welcome_message"}),
                route=route,
            )

        assert _extra(caplog, "vendor_message") == "agent_welcome_message", route
        assert _extra(caplog, "vendor_error") == 1002, "the integer must not have moved"
        assert raised.vendor_status == 400
        assert raised.vendor_error == 1002


async def test_a_phone_number_in_the_vendors_message_is_masked_before_it_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """THE GUARD THAT MATTERS: this goes red the day somebody logs the raw string.

    The message is the vendor's own worked example for `POST /call`
    (`bolna-findings/mirror/pages/api-reference/calls/make.md:62-63`) with the number it
    complains about spelled out — i.e. the exact body the old docstring was written
    against. Both directions are asserted: the number gone, AND the diagnosis kept, so
    the test cannot pass by logging nothing.
    """
    for route in _ROUTES:
        caplog.clear()
        with caplog.at_level("DEBUG"):
            await _refuse(
                httpx.Response(
                    400,
                    json={
                        "error": 1001,
                        "message": f"recipient_phone_number {_NUMBER} is not valid",
                    },
                ),
                route=route,
            )

        message = _extra(caplog, "vendor_message")
        assert message == "recipient_phone_number [phone] is not valid", route
        assert "9876543210" not in _blob(caplog), f"a caller's number reached a record: {route}"


async def test_a_telugu_message_is_held_back_where_the_redactor_cannot_see_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`redact_text` recognises digit runs and addresses, not conversation.

    That is `core.logging.redact_exception`'s standing objection to logging any upstream
    prose, and it is answered structurally rather than by trusting the vendor: what is
    admitted is printable ASCII, so the one hard-rule-6 class this product holds in bulk
    — Telugu speech — cannot ride in whatever the vendor puts it inside.
    """
    turn = "మీరు రేపు ఉదయం రాగలరా"
    for route in _ROUTES:
        caplog.clear()
        with caplog.at_level("DEBUG"):
            await _refuse(
                httpx.Response(400, json={"error": 7, "message": f"prompt rejected: {turn}"}),
                route=route,
            )

        message = _extra(caplog, "vendor_message")
        # One marker per RUN, so a five-word sentence separated by ASCII spaces leaves
        # five of them. That is the honest rendering — the spacing is the vendor's, and
        # what it says is "there were words here and you were not shown them".
        assert isinstance(message, str), route
        assert message.startswith("prompt rejected: [non-ascii]"), route
        assert set(message) <= set("prompt rejected: [non-asci]"), (
            f"something other than ASCII survived: {message!r}"
        )
        assert turn not in _blob(caplog)
        assert "రాగలరా" not in _blob(caplog)


async def test_a_vendor_cannot_write_new_lines_or_escapes_into_our_log_stream(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Same bound, second thing it buys: no forged log lines, no terminal escapes.

    A control character is not printable ASCII, so an injected `\\n{"level": "INFO"...}`
    collapses to the marker instead of becoming a second line in a log stream an operator
    reads with `grep`.
    """
    with caplog.at_level("DEBUG"):
        await _refuse(
            httpx.Response(
                400,
                json={"error": 7, "message": 'bad\n{"level":"INFO","msg":"all clear"}\x1b[31m'},
            )
        )

    message = _extra(caplog, "vendor_message")
    assert isinstance(message, str)
    assert "\n" not in message and "\x1b" not in message
    assert message.startswith("bad[non-ascii]")


async def test_an_enormous_message_cannot_write_kilobytes_into_one_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 4xx is not always answered by the vendor: an edge can put a whole page in it.

    Two bounds, and the test names both. `redact_text` caps what is SHOWN at
    `core.logging._MAX_FREE_TEXT` (200) plus its own truncation marker;
    `_VENDOR_MESSAGE_READ_LIMIT` caps what is READ, so the regex passes never run over a
    megabyte. The read limit is deliberately wider than the shown cap — that is what makes
    it impossible for either bound to cut a digit run in half and surface a partial
    number.
    """
    with caplog.at_level("DEBUG"):
        await _refuse(httpx.Response(400, json={"error": 7, "message": "A" * 50_000}))

    message = _extra(caplog, "vendor_message")
    assert isinstance(message, str)
    assert len(message) <= 256, f"a vendor wrote {len(message)} characters into a log line"
    assert message.endswith("…[truncated]"), "the reader is not told the text was cut"
    assert vendor_http._VENDOR_MESSAGE_READ_LIMIT > 200, (
        "the read limit must stay wider than the shown cap, or a masked run can be halved"
    )


async def test_a_number_past_the_shown_cap_is_masked_before_the_cap_removes_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ordering, asserted rather than assumed: mask first, truncate second.

    A number sitting at character 190 straddles the 200-character cap. Masked first, it
    becomes `[phone]` and then vanishes with the rest of the tail; truncated first, its
    leading digits would have been published as the last thing on the line.
    """
    with caplog.at_level("DEBUG"):
        await _refuse(
            httpx.Response(400, json={"error": 7, "message": "B" * 190 + _NUMBER + "C" * 400})
        )

    assert "98765" not in _blob(caplog)


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ({"error": 1001}, "no message key at all"),
        ({"error": 1001, "message": None}, "a null message"),
        ({"error": 1001, "message": 42}, "a message that is not a string"),
        ({"error": 1001, "message": {"detail": "nested"}}, "a message that is an object"),
        ({"error": 1001, "message": ["a", "b"]}, "a message that is a list"),
        ({"error": 1001, "message": ""}, "an empty message"),
        ({"error": 1001, "message": "   "}, "a message that is only whitespace"),
    ],
)
async def test_a_malformed_message_field_is_absent_rather_than_rendered(
    caplog: pytest.LogCaptureFixture, body: dict[str, Any], why: str
) -> None:
    """The vendor is free to send something other than what their schema declares.

    Every shape below must produce the same thing the other three malformed cases do —
    `None`, i.e. a key that is present and empty rather than a `repr()` of whatever
    arrived. And the integer beside it must still be read: one malformed field does not
    cost the other.
    """
    with caplog.at_level("DEBUG"):
        await _refuse(httpx.Response(400, json=body))

    assert _extra(caplog, "vendor_message") is None, why
    assert _extra(caplog, "vendor_error") == 1001, f"{why} cost us the integer too"


async def test_a_body_that_is_not_an_envelope_at_all_still_logs_the_refusal(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No body, HTML from an edge, or JSON that is not an object.

    These are `_error_envelope`'s three branches and they are the ordinary failure modes
    of an API behind a CDN. None of them may raise, and none may stop the refusal being
    reported: the status is still the fact that matters.
    """
    bodies = (
        httpx.Response(400),
        httpx.Response(400, text="<html><body>403 Forbidden</body></html>"),
        httpx.Response(400, json=["not", "an", "object"]),
        httpx.Response(400, json="a bare string"),
    )
    for response in bodies:
        caplog.clear()
        with caplog.at_level("DEBUG"):
            raised = await _refuse(response)
        assert _extra(caplog, "vendor_message") is None
        assert _extra(caplog, "vendor_error") is None
        assert raised.vendor_status == 400
        assert _extra(caplog, "status") == 400


async def test_the_client_facing_sentence_stays_generic_and_carries_no_vendor_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`detail` is rendered by the browser, so it is not an operator surface.

    `ProblemError.as_problem` copies `detail` into the problem+json body verbatim,
    `apps/web/src/lib/api/client.ts:75` makes it the message the typed client throws, and
    `apps/web/src/lib/authn/problems.ts` says most screens render it. `engine_rejected`
    is reachable from client-realm routes (a tenant saving a live agent re-publishes it),
    so the vendor's sentence on `detail` is the vendor's sentence on a client's screen.
    The log is the audience; this pins the split.
    """
    with caplog.at_level("DEBUG"):
        raised = await _refuse(
            httpx.Response(400, json={"error": 1002, "message": "agent_welcome_message"})
        )

    assert raised.detail == "The voice platform could not complete this operation."
    body = raised.as_problem("/v1/agents/x")
    assert "agent_welcome_message" not in json.dumps(body)
    assert not hasattr(raised, "vendor_message"), (
        "the message is log-only; an attribute here would put it one `str()` away from a "
        "client surface and would falsify campaign_dispatch._dial_failure_reason's claim "
        "that it never reaches that process"
    )


async def test_the_log_key_is_one_the_formatter_actually_emits(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The one question that has to be asked of the FORMATTED line instead.

    `REDACT_KEYS` is a substring match over the key name, so `vendor_text`,
    `vendor_body` or `vendor_payload` would have been replaced wholesale with
    `[redacted]` on the way out — a lot of machinery to log nothing. This asserts the
    key survives the formatter with its (already redacted) value intact.
    """
    with caplog.at_level("DEBUG"):
        await _refuse(
            httpx.Response(400, json={"error": 1002, "message": f"caller {_NUMBER} unknown"})
        )

    rendered = json.loads(JsonFormatter().format(_record(caplog)))
    assert rendered["vendor_message"] == "caller [phone] unknown"
    assert rendered["vendor_error"] == 1002
