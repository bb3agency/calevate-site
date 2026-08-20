"""The Meta Cloud API ADAPTER — the vendor half of the WhatsApp slice (D-91).

`tests/whatsapp_test.py` owns the seam: the transport selector, the opt-in gate, the
delivery record and the retry ladders, all against the console dev sink. This file
holds the thing that would actually talk to Meta, and it exists because
`apps/workers/whatsapp_cloud.py`'s class docstring PROMISED it:

    The tests drive this through `httpx.MockTransport`, which proves the request we
    build and the verdict we return; it cannot prove Meta accepts either.

Nothing drove it. The module measured 0% — 81 statements, not one executed — while its
own prose said otherwise, which is the defect class CLAUDE.md names ("a promise in prose
with no implementation"). This file is that promise, kept.

The claims pinned here, in the order they cost money:

1. **The request is the request.** Host, the configured Graph version, the phone-number
   id in the path, and the token in an `Authorization: Bearer` header rather than in a
   URL every proxy logs. `httpx.MockTransport` means the URL and headers under assertion
   are the ones httpx would have put on the wire.
2. **Errors are part of the interface.** Every Meta failure maps to exactly ONE authored
   reason code — never vendor prose — and to a verdict on whether trying again can help.
   An unapproved template and a 429 are opposite answers; a 401 and a 400 are both
   permanent and are still different sentences on an operator's screen.
3. **A 200 is not a send.** A success body with no `messages[0].id`, and a success body
   that is not an object at all, are both reported as a failure rather than as delivery.
4. **Hard rule 6.** No recipient number, no access token and no vendor message text
   reaches a log record — asserted against the real JSON formatter, not by reading.

NO WABA AND NO NETWORK: `graph.facebook.com` is egress-blocked from this environment,
which is why `CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA` is False and why every error code
below is SECONDARY-sourced (see the module docstring). These tests pin what we BUILT;
they cannot and do not pin what Meta does. Step 4 of the operational gate is what would.

Run: uv run pytest -q tests/whatsapp_cloud_test.py
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.core.logging import JsonFormatter
from apps.api.core.settings import get_settings
from apps.workers.whatsapp import (
    NO_PHONE_ID_REASON,
    NO_TOKEN_REASON,
    SendStatus,
    UnconfiguredWhatsAppTransport,
    WhatsAppMessage,
    get_whatsapp_transport,
    whatsapp_delivery_status,
)
from apps.workers.whatsapp_cloud import (
    AUTH_FAILED_REASON,
    CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA,
    GRAPH_HOST,
    MALFORMED_RESPONSE_REASON,
    NUMBER_NOT_REGISTERED_REASON,
    OUTSIDE_WINDOW_REASON,
    PROVIDER,
    RATE_LIMITED_REASON,
    RECIPIENT_UNREACHABLE_REASON,
    REQUEST_REJECTED_REASON,
    TEMPLATE_NOT_APPROVED_REASON,
    TEMPLATE_PARAMS_REASON,
    UNAVAILABLE_REASON,
    CloudApiWhatsAppTransport,
)

# A number in the shape the seam's own tests use: documented, never a real subscriber,
# and here so the hard-rule-6 test has something concrete to search the log output for.
TO_E164 = "+919000000001"
TOKEN = "EAAG-a-system-user-token-that-is-not-real"
PHONE_NUMBER_ID = "100000000000001"
GRAPH_VERSION = "v22.0"
TEMPLATE = "calevate_hot_lead_v1"

# Meta's error envelope quotes back what we sent it — which is exactly why nothing in
# the adapter reads `message` or `error_data`, and why this fixture is hostile on purpose.
#
# TWO HALVES, AND THE SECOND IS THE ONE THAT CATCHES A LEAK. The number is redacted by
# `redact_mapping` on its way through `JsonFormatter`, so an adapter that logged the whole
# body would still pass a number-only assertion — the redactor would be doing the work the
# adapter is supposed to do. `VENDOR_PROSE` carries no digits and nothing the redactor
# recognises, so it survives formatting and is absent from the output only if the adapter
# genuinely never read the body. (Verified by sabotage: adding `response.text` to the
# refusal log reddens on this token and on nothing else.)
VENDOR_PROSE = "unapproved-template-says-the-vendor"
HOSTILE_MESSAGE = f"Template send to {TO_E164.lstrip('+')} failed: {VENDOR_PROSE}"
FBTRACE = "A1bC2dE3fG4"


def _message(*, variables: tuple[str, ...] = ("Ravi K.", "Whitefield")) -> WhatsAppMessage:
    return WhatsAppMessage(to_e164=TO_E164, template=TEMPLATE, locale="en", variables=variables)


def _transport(handler: Any) -> CloudApiWhatsAppTransport:
    """The adapter wired to httpx's own mock transport, so the request the handler
    inspects is byte-for-byte what would have been sent."""
    return CloudApiWhatsAppTransport(
        access_token=TOKEN,
        phone_number_id=PHONE_NUMBER_ID,
        graph_version=GRAPH_VERSION,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _ok(message_id: str = "wamid.HBgM") -> httpx.Response:
    return httpx.Response(200, json={"messages": [{"id": message_id}]})


def _error(code: int | None, *, status: int = 400) -> httpx.Response:
    body: dict[str, Any] = {
        "error": {
            "message": HOSTILE_MESSAGE,
            "type": "OAuthException",
            "fbtrace_id": FBTRACE,
        }
    }
    if code is not None:
        body["error"]["code"] = code
    return httpx.Response(status, json=body)


# --- the request ---------------------------------------------------------------


async def test_the_request_is_the_configured_graph_node_with_a_bearer_token() -> None:
    """A token in the query string is a token in every access log between us and Meta,
    and a phone-number id in the wrong path segment sends as the wrong business."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok()

    result = await _transport(handler).send(_message())

    assert result.status is SendStatus.DELIVERED
    assert len(seen) == 1, "one message, one POST"
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == f"{GRAPH_HOST}/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(request.url), "never in the URL"


async def test_the_body_is_a_template_invocation_with_bare_digit_recipient() -> None:
    """`to` goes without the leading `+`: every independent implementation read for this
    adapter sends bare digits, and the narrower of two accepted forms cannot be wrong.
    Step 3 of the operational gate is what confirms it against a live WABA."""
    bodies: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        bodies.append(_json.loads(request.content))
        return _ok()

    await _transport(handler).send(_message())

    assert bodies == [
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": TO_E164.lstrip("+"),
            "type": "template",
            "template": {
                "name": TEMPLATE,
                "language": {"code": "en"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": "Ravi K."},
                            {"type": "text", "text": "Whitefield"},
                        ],
                    }
                ],
            },
        }
    ]


async def test_a_template_with_no_variables_sends_no_components_at_all() -> None:
    """An empty `components` list, not a `body` component carrying an empty
    `parameters` — a template with no variables takes no components, and sending an
    empty one is a 132000 (`template_parameter_mismatch`) from Meta."""
    bodies: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        bodies.append(_json.loads(request.content))
        return _ok()

    await _transport(handler).send(_message(variables=()))

    assert bodies[0]["template"]["components"] == []


# --- what counts as delivered --------------------------------------------------


async def test_a_200_without_a_message_id_is_not_a_send() -> None:
    """Meta is not documented to return this, which is precisely why it is checked:
    reporting DELIVERED on a body we did not understand loses a lead silently, and the
    whole seam exists to make silence audible."""
    result = await _transport(lambda _: httpx.Response(200, json={"messages": []})).send(_message())

    assert result.status is SendStatus.TRANSPORT_FAILED
    assert result.reason == MALFORMED_RESPONSE_REASON
    assert result.retryable is True, "we do not know it did not send; ask again"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"not json at all", id="not-json"),
        pytest.param(b"[]", id="a-json-array"),
        pytest.param(b"null", id="a-json-null"),
        pytest.param(b'"ok"', id="a-json-string"),
    ],
)
async def test_a_200_whose_body_is_not_an_object_is_reported_not_raised(body: bytes) -> None:
    """`_accepted` used to guard `ValueError` only, so a 200 carrying valid JSON that is
    not an object (`[]`, `null`, a bare string) raised `AttributeError` straight out of
    `send()` — an unhandled exception in a job, where every OTHER reader of the same body
    (`_error_code`, `_fbtrace_id`) already caught both. A malformed success body is an
    outcome this adapter reports; it is not a crash."""
    result = await _transport(lambda _: httpx.Response(200, content=body)).send(_message())

    assert result.status is SendStatus.TRANSPORT_FAILED
    assert result.reason == MALFORMED_RESPONSE_REASON


# --- errors are part of the interface ------------------------------------------


@pytest.mark.parametrize(
    ("code", "status", "expected_status", "expected_reason"),
    [
        pytest.param(
            132001, 400, SendStatus.REJECTED, TEMPLATE_NOT_APPROVED_REASON, id="no-template"
        ),
        pytest.param(
            132000, 400, SendStatus.REJECTED, TEMPLATE_PARAMS_REASON, id="wrong-variables"
        ),
        pytest.param(131047, 400, SendStatus.REJECTED, OUTSIDE_WINDOW_REASON, id="outside-window"),
        pytest.param(
            131026, 400, SendStatus.REJECTED, RECIPIENT_UNREACHABLE_REASON, id="no-whatsapp"
        ),
        pytest.param(
            133010, 400, SendStatus.REJECTED, NUMBER_NOT_REGISTERED_REASON, id="our-number"
        ),
    ],
)
async def test_the_numeric_code_wins_over_the_status(
    code: int, status: int, expected_status: SendStatus, expected_reason: str
) -> None:
    """Cloud API returns 400 for "your template does not exist" (a human must fix it)
    and for "this recipient has no WhatsApp" (nobody can). One status, two sentences on
    a client's screen, so the code is what decides."""
    result = await _transport(lambda _: _error(code, status=status)).send(_message())

    assert result.status is expected_status
    assert result.reason == expected_reason
    assert result.retryable is False, "every coded verdict here is permanent"


@pytest.mark.parametrize(
    ("status", "expected_reason"),
    [
        pytest.param(429, RATE_LIMITED_REASON, id="429"),
        pytest.param(408, UNAVAILABLE_REASON, id="408"),
        pytest.param(500, UNAVAILABLE_REASON, id="500"),
        pytest.param(502, UNAVAILABLE_REASON, id="502"),
        pytest.param(503, UNAVAILABLE_REASON, id="503"),
        pytest.param(504, UNAVAILABLE_REASON, id="504"),
        # Not in `_TRANSIENT_STATUS`, still a server-side failure: the `>= 500` arm is
        # what stops an unlisted 5xx being classified as our request being wrong.
        pytest.param(501, UNAVAILABLE_REASON, id="501-unlisted-5xx"),
    ],
)
async def test_the_moment_was_wrong_not_the_request(status: int, expected_reason: str) -> None:
    result = await _transport(lambda _: _error(None, status=status)).send(_message())

    assert result.status is SendStatus.TRANSPORT_FAILED
    assert result.reason == expected_reason
    assert result.retryable is True, "the retry ladder exists for exactly these"


@pytest.mark.parametrize("status", [401, 403])
async def test_a_dead_token_is_permanent_and_names_the_operator_errand(status: int) -> None:
    """Retrying cannot mint a token. `whatsapp._is_operational` reads this reason to
    decide whether to page somebody, so it must not be the generic 4xx one."""
    result = await _transport(lambda _: _error(None, status=status)).send(_message())

    assert result.status is SendStatus.REJECTED
    assert result.reason == AUTH_FAILED_REASON
    assert result.retryable is False


async def test_an_uncoded_4xx_is_our_request_being_wrong_and_is_permanent() -> None:
    result = await _transport(lambda _: _error(None, status=400)).send(_message())

    assert result.status is SendStatus.REJECTED
    assert result.reason == REQUEST_REJECTED_REASON
    assert result.retryable is False


async def test_an_unknown_numeric_code_falls_through_to_the_status() -> None:
    """The code table is deliberately small — a table copied wholesale from a secondary
    source would be a large surface of unverified claims. A member it does not name must
    degrade to the status-based verdict, which is correct if less specific."""
    result = await _transport(lambda _: _error(999999, status=429)).send(_message())

    assert result.status is SendStatus.TRANSPORT_FAILED
    assert result.reason == RATE_LIMITED_REASON


async def test_a_network_failure_is_a_transport_failure_named_by_its_type() -> None:
    """The exception TYPE, never its string: an httpx error message can carry the
    request URL, and a timeout's repr can carry the request body — which holds the
    recipient's number."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connecting to 100000000000001 timed out")

    result = await _transport(handler).send(_message())

    assert result.status is SendStatus.TRANSPORT_FAILED
    assert result.reason == "ConnectTimeout"
    assert result.retryable is True


# --- hard rule 6 ---------------------------------------------------------------


async def test_no_number_token_or_vendor_prose_reaches_a_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Asserted against the real JSON formatter rather than by reading the calls: an
    `extra` that survives to the record is what actually ships, and a vendor error body
    may quote the payload we just sent — which contains the recipient."""
    caplog.set_level(logging.INFO)
    await _transport(lambda _: _ok()).send(_message())
    await _transport(lambda _: _error(132001)).send(_message())
    await _transport(lambda _: httpx.Response(200, json={"messages": []})).send(_message())

    formatter = JsonFormatter()
    # OUR records. httpx's own `HTTP Request: ...` line is excluded for the reason
    # `meta_graph_test` gives: production never emits it, because `configure_logging`
    # puts that logger at WARNING.
    emitted = "\n".join(
        formatter.format(record) for record in caplog.records if record.name != "httpx"
    )
    assert emitted, "the adapter is expected to say something"
    for forbidden in (
        TO_E164,
        TO_E164.lstrip("+"),
        TOKEN,
        VENDOR_PROSE,
        "OAuthException",
        "Ravi K.",
    ):
        assert forbidden not in emitted, f"{forbidden!r} must never reach a log line"
    # What an operator DOES get: our reason, the status, and Meta's own trace id.
    assert TEMPLATE_NOT_APPROVED_REASON in emitted
    assert FBTRACE in emitted
    assert TEMPLATE in emitted, "the template name is ours and is the useful half"


# --- the greppable constant ----------------------------------------------------


# --- selectability: the half a refusal-only suite cannot see -------------------


@pytest.fixture
def cloud_api_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that has actually been given a WABA's three values.

    Set on `Settings` rather than patched onto the module, because the thing under test
    is precisely whether the fields EXIST and reach the reader. Patching
    `_cloud_api_config` would have passed against the shim that made this file's subject
    unreachable, which is the mistake `tests/payment_order_test.py` made one slice over
    (it patched `razorpay_api_secret` on the grounds that its field did not exist, and the
    field had existed for 390 commits).
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "whatsapp_provider", PROVIDER)
    monkeypatch.setattr(settings, "whatsapp_cloud_access_token", TOKEN)
    monkeypatch.setattr(settings, "whatsapp_cloud_phone_number_id", PHONE_NUMBER_ID)
    monkeypatch.setattr(settings, "whatsapp_cloud_graph_version", GRAPH_VERSION)


def test_a_configured_deployment_actually_gets_this_transport(
    cloud_api_configured: None,
) -> None:
    """THE TEST THAT WOULD HAVE CAUGHT IT, and the reason it is worth more than the 26
    above it put together.

    `WHATSAPP_PROVIDER=meta_cloud_api` was a DEAD CONFIGURATION. `whatsapp.py` read the
    three credential fields through `getattr(settings, "...", "")` under a comment headed
    "TEMPORARY SHIM — DELETE THE `getattr`s WHEN THE SETTINGS KEYS LAND"; the keys never
    landed, `Settings` is `extra="forbid"`, and so `whatsapp_delivery_status()` answered
    `cloud_api_access_token_missing` on every deployment that has ever run and this
    transport could not be constructed by any code path outside a test that built it by
    hand — which is what every other test in this file does.

    That is the shape of the defect: a suite can prove a class works perfectly and prove
    nothing about whether anything can reach it. So this asserts the SEAM — settings in,
    transport out — and it is the one test here that fails if the fields are removed.
    """
    status = whatsapp_delivery_status()
    assert status.available is True, (
        f"a fully configured deployment reports {status.reason!r}: the Cloud API branch "
        "cannot reach its own success arm"
    )
    assert status.reason is None

    transport = get_whatsapp_transport()
    assert isinstance(transport, CloudApiWhatsAppTransport), (
        f"the factory returned {type(transport).__name__} for a configured Cloud API "
        "deployment — the provider is selected and the adapter is still unreachable"
    )
    assert transport.name == PROVIDER


async def test_the_selected_transport_carries_the_configured_values_to_the_wire(
    cloud_api_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Selectability is necessary and not sufficient: a factory that returned the right
    CLASS built from the wrong values would pass the test above and send as nobody.

    So the request the FACTORY-BUILT transport makes is inspected, not one built by hand
    — the phone-number id in the path and the token in the header both have to be the
    ones an operator configured. The client is injected afterwards because
    `get_whatsapp_transport()` deliberately builds its own; injection here replaces the
    socket, not the configuration.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok()

    transport = get_whatsapp_transport()
    assert isinstance(transport, CloudApiWhatsAppTransport)
    monkeypatch.setattr(
        transport, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    result = await transport.send(_message())

    assert result.status is SendStatus.DELIVERED
    assert str(seen[0].url) == f"{GRAPH_HOST}/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages"
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize(
    ("missing", "expected_reason"),
    [
        pytest.param("whatsapp_cloud_access_token", NO_TOKEN_REASON, id="no-token"),
        pytest.param("whatsapp_cloud_phone_number_id", NO_PHONE_ID_REASON, id="no-phone-id"),
    ],
)
def test_a_half_configured_deployment_names_the_errand_that_is_left(
    cloud_api_configured: None, monkeypatch: pytest.MonkeyPatch, missing: str, expected_reason: str
) -> None:
    """The control on the test above, and the reason these two reasons are separate codes.

    Minting a system-user token and copying a number id out of the Meta console are two
    different errands. Both refusals were reachable before the fields existed — they were
    the ONLY reachable answers — so they are asserted here against a deployment that is
    genuinely missing one thing rather than against one that could never have either.
    """
    monkeypatch.setattr(get_settings(), missing, None)

    status = whatsapp_delivery_status()
    assert status.available is False
    assert status.reason == expected_reason
    transport = get_whatsapp_transport()
    assert isinstance(transport, UnconfiguredWhatsAppTransport)
    assert transport.reason == expected_reason


def test_the_graph_version_cannot_be_blanked_into_an_unversioned_call(
    cloud_api_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meta does not support unversioned calls, so the version is pinned by the FIELD —
    `str` with a default and a `pattern`, not `str | None` with a fallback in this module.

    `_cloud_api_config` therefore needs no `or DEFAULT_GRAPH_VERSION`, and the constant
    that used to provide one is deleted: a module-level fallback beside a field default is
    two answers to one question. What stops a blank reaching the wire is the constraint,
    enforced where a console write is validated — asserted here as the model refusing,
    because that is the boundary an operator's edit actually crosses.
    """
    from apps.api.ops.config_service import validated_value

    assert validated_value("whatsapp_cloud_graph_version", "v23.0") == "v23.0"
    for refused in ("", "latest", "22.0", "v22"):
        with pytest.raises(ProblemError) as raised:
            validated_value("whatsapp_cloud_graph_version", refused)
        assert raised.value.code == "config_value_invalid", refused


def test_the_credential_seals_and_its_two_companions_do_not() -> None:
    """WHICH of the three is a secret is decided by NAME (`_SECRET_NAME_FRAGMENTS`), so it
    is asserted rather than trusted to a reading of the fragment list.

    The access token is a credential and must land in the encrypted `platform_secrets`
    path, write-only with `last_four`. The phone-number id and the Graph version must NOT:
    they identify and pin rather than authenticate, and an operator working the WABA
    checklist has to be able to SEE them to check them against the Meta console — the
    exact harm `_CREDENTIAL_REFERENCE_KEYS` was created for when
    `bolna_llm_credential_name` was sealed by accident.
    """
    from apps.api.core.platform_config import is_secret_key, managed_fields
    from apps.api.ops.secret_service import manageable_secret_keys

    assert is_secret_key("whatsapp_cloud_access_token") is True
    assert "whatsapp_cloud_access_token" in manageable_secret_keys()
    assert "whatsapp_cloud_access_token" not in managed_fields()

    for visible in ("whatsapp_cloud_phone_number_id", "whatsapp_cloud_graph_version"):
        assert is_secret_key(visible) is False, visible
        assert visible in managed_fields(), visible


def test_the_live_waba_claim_is_still_false_and_this_file_cannot_close_it() -> None:
    """`httpx.MockTransport` proves the request we build and the verdict we apply. It
    proves nothing about whether Meta accepts either, so a green run of this file must
    never be mistaken for the operational gate. Flipping the constant is a person's job
    after a real send; if this test ever fails, the four gate steps in the module
    docstring are what must have happened first."""
    assert CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA is False
    assert PROVIDER == "meta_cloud_api"
    assert CloudApiWhatsAppTransport.name == PROVIDER
