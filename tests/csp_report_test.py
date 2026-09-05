"""The Content-Security-Policy violation collector (D-541).

Suffix `_security_test` is reserved for the cross-tenant/redaction suite; this endpoint
holds no tenant data at all, which is most of what these tests assert. What they are here
to catch, in order of how expensive the mistake is:

1. **A URL reaching a log line.** Hard rule 6, and this route is handed three URL-shaped
   fields by a stranger's browser on every delivery.
2. **The nonce reaching a log line** — `original-policy` carries the policy we served,
   nonce and all.
3. **The endpoint becoming a way to spend our resources**: an unbounded body, an
   unbounded batch, a foreign site using it as free log storage.
"""

from __future__ import annotations

import json

import pytest
from apps.api.main import app
from apps.api.security import csp_reports
from apps.api.security.routes import MAX_REPORT_BYTES
from httpx import ASGITransport, AsyncClient

# `asyncio_mode = "auto"` (pyproject.toml) runs the async tests below; the pure-parser
# ones beside them are ordinary sync functions on purpose.
REPORT_PATH = "/reports/v1/csp"
LEGACY_TYPE = "application/csp-report"
REPORTING_API_TYPE = "application/reports+json"

#: A page in a real client's console: a tenant slug, a record id and a typed filter, which
#: is exactly the URL that must never survive into a log line.
DOCUMENT_URI = "https://app.calevate.tech/c/acme-dental/leads/018f-abc?q=priya+9876543210"


def _legacy_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "document-uri": DOCUMENT_URI,
        "referrer": "https://app.calevate.tech/c/acme-dental/calls/018f?token=secret",
        "violated-directive": "script-src 'self' 'nonce-ABC'",
        "effective-directive": "script-src",
        "original-policy": "default-src 'self'; script-src 'self' 'nonce-SUPERSECRETNONCE'",
        "blocked-uri": "inline",
        "status-code": 200,
        "script-sample": "alert(document.cookie)",
        "source-file": "https://app.calevate.tech/_next/static/chunks/page-9f2.js?v=3",
        "line-number": 41,
        "disposition": "enforce",
    }
    body.update(overrides)
    return {"csp-report": body}


async def _post(body: object, *, content_type: str = LEGACY_TYPE) -> int:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            REPORT_PATH,
            content=json.dumps(body).encode() if not isinstance(body, bytes) else body,
            headers={"content-type": content_type},
        )
    return response.status_code


# --- the redaction, asserted on the parser rather than through the wire ---------------
# The parser is where the decision is made, so it is where the assertion belongs; the
# route test below then proves the route uses it.


def test_the_page_path_is_cut_at_the_realm_because_the_next_segment_is_the_tenant() -> None:
    [violation] = csp_reports.parse_reports(_legacy_body())
    assert violation.document_realm == "https://app.calevate.tech/c"
    # Not the slug, not the record id, not the query.
    assert "acme-dental" not in str(violation)
    assert "9876543210" not in str(violation)


def test_the_fields_that_must_never_be_kept_are_not_on_the_record() -> None:
    [violation] = csp_reports.parse_reports(_legacy_body())
    rendered = str(violation)
    # `referrer` is a whole URL from a page we are not even being told about.
    assert "token=secret" not in rendered
    # `script-sample` is the offending script's own bytes.
    assert "document.cookie" not in rendered
    # `original-policy` carries THE NONCE WE SERVED. This is the assertion that matters
    # most in this file: the nonce is the entire basis of `script-src`.
    assert "SUPERSECRETNONCE" not in rendered


def test_a_blocked_url_is_reduced_to_its_origin_and_a_keyword_is_kept_whole() -> None:
    [violation] = csp_reports.parse_reports(
        _legacy_body(**{"blocked-uri": "https://evil.example/steal.js?tenant=acme&d=9876543210"})
    )
    assert violation.blocked_origin == "https://evil.example"
    # `inline` is the vocabulary, not data, and it is what an injected script looks like.
    [inline] = csp_reports.parse_reports(_legacy_body())
    assert inline.blocked_origin == "inline"


def test_the_source_file_keeps_its_origin_and_line_but_not_its_path() -> None:
    [violation] = csp_reports.parse_reports(_legacy_body())
    assert violation.source_origin == "https://app.calevate.tech"
    assert violation.line_number == 41


def test_the_directive_name_is_taken_off_a_violated_directive_carrying_the_source_list() -> None:
    # Some browsers put the whole source list in `violated-directive`, which is a copy of
    # our own policy — nonce included.
    [violation] = csp_reports.parse_reports(
        _legacy_body(**{"effective-directive": None, "violated-directive": "script-src 'nonce-X'"})
    )
    assert violation.effective_directive == "script-src"
    assert "nonce-X" not in str(violation)


# --- both wire shapes ------------------------------------------------------------------


def test_the_reporting_api_batch_shape_is_read_too() -> None:
    envelopes = [
        {
            "type": "csp-violation",
            "age": 12,
            "url": DOCUMENT_URI,
            "body": {
                "documentURL": DOCUMENT_URI,
                "effectiveDirective": "media-src",
                "blockedURL": "https://store.example/recordings/018f.mp3?X-Amz-Signature=deadbeef",
                "disposition": "enforce",
            },
        },
        # A Reporting API endpoint receives other report types on the same group.
        {"type": "deprecation", "body": {"id": "something-else"}},
    ]
    [violation] = csp_reports.parse_reports(envelopes)
    assert violation.effective_directive == "media-src"
    # The presigned signature is a bearer credential; only the origin survives.
    assert violation.blocked_origin == "https://store.example"
    assert "Signature" not in str(violation)


def test_a_batch_is_bounded_so_the_sender_does_not_choose_how_much_we_do() -> None:
    one = {
        "type": "csp-violation",
        "body": {"documentURL": DOCUMENT_URI, "effectiveDirective": "img-src"},
    }
    parsed = csp_reports.parse_reports([one] * (csp_reports.MAX_REPORTS_PER_POST + 25))
    assert len(parsed) == csp_reports.MAX_REPORTS_PER_POST


@pytest.mark.parametrize("payload", [None, [], {}, {"csp-report": "nope"}, 7, "text"])
def test_a_shape_we_do_not_know_yields_nothing_and_never_raises(payload: object) -> None:
    assert csp_reports.parse_reports(payload) == []


def test_a_browser_extension_is_noise_and_is_named_as_such() -> None:
    [violation] = csp_reports.parse_reports(
        _legacy_body(**{"blocked-uri": "chrome-extension://abcdefghijklmnop/inject.js"})
    )
    assert csp_reports.is_extension_noise(violation)
    [ours] = csp_reports.parse_reports(_legacy_body(**{"blocked-uri": "https://evil.example/x"}))
    assert not csp_reports.is_extension_noise(ours)


# --- the route's admission control ------------------------------------------------------


async def test_a_well_formed_report_is_accepted_with_no_body() -> None:
    assert await _post(_legacy_body()) == 204


async def test_the_reporting_api_content_type_is_accepted_too() -> None:
    envelopes = [
        {
            "type": "csp-violation",
            "body": {"documentURL": DOCUMENT_URI, "effectiveDirective": "script-src"},
        }
    ]
    assert await _post(envelopes, content_type=REPORTING_API_TYPE) == 204


async def test_a_charset_parameter_does_not_defeat_the_content_type_check() -> None:
    assert await _post(_legacy_body(), content_type="application/csp-report; charset=UTF-8") == 204


@pytest.mark.parametrize("content_type", ["application/json", "text/plain", ""])
async def test_anything_that_is_not_a_reporting_agent_is_refused_before_the_body(
    content_type: str,
) -> None:
    assert await _post(_legacy_body(), content_type=content_type) == 415


async def test_an_oversized_body_is_refused_rather_than_buffered() -> None:
    padded = _legacy_body(**{"blocked-uri": "https://evil.example/" + "A" * MAX_REPORT_BYTES})
    assert await _post(padded) == 413


async def test_a_body_that_is_not_json_is_answered_204_and_not_a_500() -> None:
    # An unauthenticated endpoint must not be an oracle for which bodies it can read.
    assert await _post(b"{not json", content_type=LEGACY_TYPE) == 204


async def test_a_report_about_somebody_elses_website_is_answered_the_same_204() -> None:
    # Indistinguishable from outside, and recorded nowhere: this endpoint is not free log
    # storage for a site we do not serve.
    assert await _post(_legacy_body(**{"document-uri": "https://not-ours.example/page"})) == 204


def test_the_admission_check_accepts_our_consoles_and_refuses_everything_else() -> None:
    from apps.api.security.routes import require_own_console_origin

    [ours] = csp_reports.parse_reports(_legacy_body())
    assert require_own_console_origin(ours)
    [theirs] = csp_reports.parse_reports(
        _legacy_body(**{"document-uri": "https://app.calevate.tech.evil.example/c/x"})
    )
    # A suffix attack on the origin must not pass: `startswith` is applied to the ORIGIN
    # plus a slash, never to the bare host string.
    assert not require_own_console_origin(theirs)
    [none] = csp_reports.parse_reports(_legacy_body(**{"document-uri": "not-a-url"}))
    assert not require_own_console_origin(none)


async def test_the_route_alerts_once_per_delivery_and_not_once_per_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A page that trips six directives is one problem, not six pages."""
    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "apps.api.security.routes.alert",
        lambda stage, code, **kw: fired.append((stage, code)),
    )
    envelopes = [
        {
            "type": "csp-violation",
            "body": {"documentURL": DOCUMENT_URI, "effectiveDirective": directive},
        }
        for directive in ("script-src", "media-src", "font-src", "img-src")
    ]
    assert await _post(envelopes, content_type=REPORTING_API_TYPE) == 204
    assert fired == [("BROWSER_RUNTIME", "csp_violation")]


async def test_extension_noise_and_foreign_origins_page_nobody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fired: list[str] = []
    monkeypatch.setattr(
        "apps.api.security.routes.alert", lambda stage, code, **kw: fired.append(code)
    )
    assert await _post(_legacy_body(**{"blocked-uri": "moz-extension://x/y.js"})) == 204
    assert await _post(_legacy_body(**{"document-uri": "https://not-ours.example/p"})) == 204
    assert fired == []
