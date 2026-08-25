"""Transport selection, the honesty property, and the Resend contract.

The behaviour worth testing is not "does email work" (that is httpx and smtplib) but
"does an unconfigured or misconfigured deployment tell the truth". A transport that
returns success with nothing wired makes the 2-minute hot-lead SLO look met while no
client is ever told — and, since D-49, while no operator alert reaches anybody either.

The Resend half tests the three things that can silently swallow mail: a missing
credential, a sender domain the provider has not verified, and a response body that gets
logged. Nothing here talks to `api.resend.com`; `RESEND_API_CONTRACT_VERIFIED` is False
and this file is one of the reasons it is honest about that.
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import json
import logging
from pathlib import Path
from typing import Any

import pytest
from calevate_shared.config import (
    NO_EMAIL_PROVIDER_REASON,
    NO_RESEND_API_KEY_REASON,
    NO_SENDER_ADDRESS_REASON,
    NO_SMTP_HOST_REASON,
    Settings,
    email_transport_reason,
)

from apps.api.core.settings import get_settings
from apps.workers import transport as transport_module
from apps.workers.transport import (
    RESEND_API_CONTRACT_VERIFIED,
    RESEND_SEND_URL,
    ConsoleTransport,
    NullTransport,
    ResendTransport,
    SmtpTransport,
    get_transport,
)

RECIPIENT = "owner@example.com"
#: The local-part of `RECIPIENT`. Never allowed into a log record (hard rule 6).
MAILBOX = "owner"


def _extra(record: logging.LogRecord, field: str) -> object:
    """One of OUR `extra=` fields off a log record. Through `__dict__` because that is
    where `logging` puts them and `LogRecord` declares none of them to a type checker."""
    return record.__dict__[field]


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: str | None = None,
    app_env: str = "prod",
    resend_api_key: str | None = None,
    smtp_host: str | None = None,
    sender: str | None = "support@calevate.tech",
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "email_provider", provider)
    monkeypatch.setattr(settings, "app_env", app_env)
    monkeypatch.setattr(settings, "resend_api_key", resend_api_key)
    monkeypatch.setattr(settings, "smtp_host", smtp_host)
    monkeypatch.setattr(settings, "notifications_from", sender)


# --- selection: exactly one way to answer "which transport is this?" ----------


def test_local_with_nothing_configured_uses_the_console_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, app_env="local")
    assert isinstance(get_transport(), ConsoleTransport)


def test_the_provider_field_selects_resend(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch, provider="resend", resend_api_key="re_test_key")
    transport = get_transport()
    assert isinstance(transport, ResendTransport)
    assert transport.name == "resend"


def test_smtp_survives_as_the_escape_hatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """`SmtpTransport` was kept on purpose: a suspended Resend account has to be a
    configuration change from a browser, not a deploy. If this test is ever deleted,
    delete the class with it — an unreachable transport is dead code."""
    _configure(monkeypatch, provider="smtp", smtp_host="smtp.example.com")
    assert isinstance(get_transport(), SmtpTransport)


def test_a_configured_host_no_longer_selects_smtp_on_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE MIGRATION TRAP, pinned. Selection used to be "is SMTP_HOST set?", so a host
    left in the store after the move to Resend would have quietly kept sending through
    it. Selection is `EMAIL_PROVIDER` and nothing else."""
    _configure(monkeypatch, provider=None, smtp_host="smtp.example.com", app_env="prod")
    transport = get_transport()
    assert isinstance(transport, NullTransport)
    assert transport.reason == NO_EMAIL_PROVIDER_REASON


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"provider": None}, NO_EMAIL_PROVIDER_REASON),
        ({"provider": "resend"}, NO_RESEND_API_KEY_REASON),
        ({"provider": "smtp"}, NO_SMTP_HOST_REASON),
        ({"provider": "sendgrid"}, "provider_not_implemented:sendgrid"),
        (
            {"provider": "resend", "resend_api_key": "re_k", "sender": "   "},
            NO_SENDER_ADDRESS_REASON,
        ),
    ],
)
def test_every_unconfigured_shape_refuses_by_name(
    monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any], reason: str
) -> None:
    """The property this module exists for: silence is reported, not swallowed — and
    since this change, the log line says WHICH half is missing rather than leaving an
    operator to guess between four of them."""
    _configure(monkeypatch, **kwargs)
    transport = get_transport()
    assert isinstance(transport, NullTransport)
    assert transport.reason == reason
    assert transport.send(to=RECIPIENT, subject="x", body="y") is False


def test_the_boot_check_and_the_transport_ask_the_same_question(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`init_observability` warns at boot that alerts have nowhere to go. It must read
    the SAME resolver `get_transport()` does, or a Resend deployment gets a false
    `alert_delivery_has_no_transport` at every boot — and a real gap gets missed the day
    the two spellings drift."""
    from apps.api.core import observability

    _configure(monkeypatch, provider="resend", resend_api_key="re_test_key")
    settings = get_settings()
    monkeypatch.setattr(settings, "alerts_email", "sri@calevate.tech")
    monkeypatch.setattr(settings, "sentry_dsn", None)
    monkeypatch.setattr(observability, "init_tracing", lambda _service: False)

    with caplog.at_level(logging.WARNING, logger=observability.log.name):
        observability.init_observability("workers")

    assert "alert_delivery_has_no_transport" not in caplog.text
    assert email_transport_reason(settings) is None


# --- the honest defaults ------------------------------------------------------


def test_the_sender_is_defaulted_once_in_the_model() -> None:
    """`get_transport()` used to carry an inline `or "alerts@calevate.tech"`, so the
    platform had two spellings of its own return address and the console showed neither.
    One definition, on the field, visible in `GET /v1/ops/config`."""
    assert Settings.model_fields["notifications_from"].default == "support@calevate.tech"
    source = inspect.getsource(transport_module.get_transport)
    assert "@calevate.tech" not in source, "a second hardcoded sender crept back in"


def test_console_transport_reports_success() -> None:
    """It really did deliver — to a terminal. Reporting False would train developers to
    ignore the delivered flag."""
    assert ConsoleTransport().send(to=RECIPIENT, subject="x", body="y") is True


def test_smtp_failure_returns_false_rather_than_raising() -> None:
    """The caller decides whether a failed notification retries the job; it records the
    outcome on the lead timeline either way."""
    transport = SmtpTransport(
        host="127.0.0.1", port=1, username=None, password=None, sender="a@b.test"
    )
    assert transport.send(to=RECIPIENT, subject="x", body="y") is False


# --- the Resend adapter -------------------------------------------------------


class _Response:
    def __init__(self, status_code: int, payload: Any = None, decodable: bool = True) -> None:
        self.status_code = status_code
        self._payload = payload
        self._decodable = decodable

    def json(self) -> Any:
        if not self._decodable:
            raise ValueError("not json")
        return self._payload


#: What the stand-in client was asked to send, most recent run first cleared by `_install`.
_CALLS: list[dict[str, Any]] = []
#: What it answers with. A one-element list rather than a global so `_install` can rebind
#: it without the `global` statement ruff would rather we did not write in a test.
_ANSWER: list[_Response] = []


class _Client:
    """Stands in for `httpx.Client`, recording exactly what was sent."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def post(self, url: str, *, json: Any, headers: dict[str, str]) -> _Response:
        _CALLS.append({"url": url, "json": json, "headers": headers, "client_kwargs": self.kwargs})
        return _ANSWER[0]


def _install(monkeypatch: pytest.MonkeyPatch, response: _Response) -> list[dict[str, Any]]:
    import httpx

    _CALLS.clear()
    _ANSWER[:] = [response]
    monkeypatch.setattr(httpx, "Client", _Client)
    return _CALLS


def test_the_request_matches_the_contract_read_at_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """READ AT SOURCE (resend-openapi `resend.yaml`, resend-python `request.py`):
    `POST https://api.resend.com/emails`, bearer auth, JSON body of from/to/subject, and
    `text` alone is a valid body. A bounded timeout is part of the contract this repo
    holds itself to, not Resend's — an HTTP call with no deadline parks the alerting
    daemon thread for ever."""
    calls = _install(monkeypatch, _Response(200, {"id": "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794"}))
    transport = ResendTransport(api_key="re_test_key", sender="support@calevate.tech")

    assert transport.send(to=RECIPIENT, subject="Hot lead", body="line one") is True

    (call,) = calls
    assert call["url"] == RESEND_SEND_URL == "https://api.resend.com/emails"
    assert call["headers"]["Authorization"] == "Bearer re_test_key"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["json"] == {
        "from": "support@calevate.tech",
        "to": [RECIPIENT],
        "subject": "Hot lead",
        "text": "line one",
    }
    assert "html" not in call["json"], "a text-only body is schema-valid; do not fabricate html"
    assert call["client_kwargs"]["timeout"] is not None
    # A bearer credential travels in this request's headers and httpx re-sends headers on
    # a same-scheme redirect, so a 30x from a hijacked host would hand the key away.
    assert call["client_kwargs"]["follow_redirects"] is False


def test_a_success_records_the_provider_message_id(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The only join between our log line and the provider's dashboard on the day a
    client says the mail never arrived."""
    _install(monkeypatch, _Response(200, {"id": "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794"}))
    transport = ResendTransport(api_key="re_k", sender="support@calevate.tech")

    with caplog.at_level(logging.INFO, logger=transport_module.log.name):
        assert transport.send(to=RECIPIENT, subject="s", body="b") is True

    (record,) = [r for r in caplog.records if r.msg == "email_sent"]
    assert _extra(record, "provider_message_id") == "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794"
    assert _extra(record, "recipient_domain") == "example.com"


def test_an_undecodable_success_body_is_still_a_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 2xx we cannot parse means we have no id to quote, never that the send failed.
    Reporting failure here would make a delivered message look lost and burn a ladder."""
    _install(monkeypatch, _Response(202, decodable=False))
    transport = ResendTransport(api_key="re_k", sender="support@calevate.tech")
    assert transport.send(to=RECIPIENT, subject="s", body="b") is True


def test_an_unverified_sender_domain_is_the_loudest_failure_here(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """403 is the quietest possible outage: every message refused, nothing in an inbox,
    nothing obviously wrong. It gets ERROR, its own event name, the sender domain that
    has to be verified, and a remediation naming BOTH causes — this module reads a status
    code and cannot tell a wrong key from an unverified domain, and will not guess."""
    _install(monkeypatch, _Response(403, {"statusCode": 403, "name": "validation_error"}))
    transport = ResendTransport(api_key="re_k", sender="support@calevate.tech")

    with caplog.at_level(logging.INFO, logger=transport_module.log.name):
        assert transport.send(to=RECIPIENT, subject="s", body="b") is False

    (record,) = [r for r in caplog.records if r.msg == "email_sender_rejected"]
    assert record.levelno == logging.ERROR
    assert _extra(record, "sender_domain") == "calevate.tech"
    assert "verif" in str(_extra(record, "remediation"))


@pytest.mark.parametrize(
    ("status", "event", "level"),
    [
        (401, "email_credential_rejected", logging.ERROR),
        (422, "email_request_rejected", logging.ERROR),
        (400, "email_request_rejected", logging.ERROR),
        (429, "email_rate_limited", logging.WARNING),
        (503, "email_send_failed", logging.WARNING),
    ],
)
def test_every_refusal_has_its_own_name(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status: int,
    event: str,
    level: int,
) -> None:
    """`send()` returns a bool, so the LOG is the whole interface for an operator. A
    wrong key, a malformed request and a rate limit have different owners and must not
    arrive as one indistinguishable `email_send_failed`."""
    _install(monkeypatch, _Response(status, {"statusCode": status, "name": "x"}))
    transport = ResendTransport(api_key="re_k", sender="support@calevate.tech")

    with caplog.at_level(logging.INFO, logger=transport_module.log.name):
        assert transport.send(to=RECIPIENT, subject="s", body="b") is False

    (record,) = [r for r in caplog.records if r.msg == event]
    assert record.levelno == level


def test_a_transport_failure_returns_false_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same contract as the SMTP leg: the caller owns the retry decision."""
    import httpx

    class _Exploding(_Client):
        def post(self, *_: object, **__: object) -> _Response:
            raise httpx.ConnectTimeout("nowhere to connect")

    monkeypatch.setattr(httpx, "Client", _Exploding)
    transport = ResendTransport(api_key="re_k", sender="support@calevate.tech")
    assert transport.send(to=RECIPIENT, subject="s", body="b") is False


def test_no_log_record_carries_a_mailbox_a_body_or_the_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Hard rule 6, one rung harder than for SMTP: a Resend error body QUOTES the
    addresses it rejected, so a module that logged a response verbatim would put a
    mailbox in a log line. Nothing here logs a body, a subject, or the credential."""
    secret_body = "Phone: +91 90000 00000"
    for status in (200, 401, 403, 422, 429, 500):
        _install(
            monkeypatch,
            _Response(
                status,
                {"statusCode": status, "name": "validation_error", "message": RECIPIENT},
            ),
        )
        transport = ResendTransport(api_key="re_supersecret", sender="support@calevate.tech")
        with caplog.at_level(logging.INFO, logger=transport_module.log.name):
            transport.send(to=RECIPIENT, subject="Hot lead from Ravi", body=secret_body)

    rendered = json.dumps(
        [{key: str(value) for key, value in record.__dict__.items()} for record in caplog.records]
    )
    for forbidden in (MAILBOX, "re_supersecret", secret_body, "Ravi"):
        assert forbidden not in rendered, f"{forbidden!r} reached a log record"


# --- the two structural promises ----------------------------------------------


def test_httpx_is_imported_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOAD-BEARING, not style. `alerting._deliver` imports this module on a daemon
    thread inside `apps/voice-runtime`, whose import surface is asserted
    (tests/voice_runtime_import_surface_test.py, hard rule 3). httpx pulls httpcore, h11
    and certifi, and none of them are in that process's boot graph — measured, not
    assumed. At module scope they would join it in every deployment, including the ones
    that never send an email.
    """
    tree = ast.parse(inspect.getsource(transport_module))
    module_level = [
        alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names
    ]
    module_level += [node.module or "" for node in tree.body if isinstance(node, ast.ImportFrom)]
    assert "httpx" not in module_level, (
        "a module-scope httpx import puts httpcore/h11/certifi into voice-runtime's "
        "memory for every deployment. Import it inside ResendTransport.send()."
    )


def test_the_vendor_contract_is_still_a_marked_assumption() -> None:
    """OPERATIONS §2: a vendor behaviour is verified or it is a MARKED assumption, never
    a silent premise. `resend.com` is refused by this environment's egress proxy and no
    request has ever been made to `api.resend.com` from this repository, so the contract
    in `transport.py` is read out of Resend's own published SDKs and OpenAPI document —
    strong evidence, but not an observation.

    Flipping this needs a Resend account, a live key and one accepted send. When that
    happens, delete this test with the constant.
    """
    assert RESEND_API_CONTRACT_VERIFIED is False


def test_every_remediation_survives_the_log_redactor(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A remediation that overflows `logging._MAX_FREE_TEXT` loses its TAIL, and the tail
    is where the instruction is. Found by running the refusal paths and reading the
    output: the first draft of the 403 sentence came out as "…Check the key at
    admin.calevate.tech/ops and the domain i…[truncated]".
    """
    from apps.api.core.logging import _MAX_FREE_TEXT, redact_mapping

    for status in (401, 403, 422):
        _install(monkeypatch, _Response(status, {"statusCode": status}))
        transport = ResendTransport(api_key="re_k", sender="support@calevate.tech")
        with caplog.at_level(logging.INFO, logger=transport_module.log.name):
            transport.send(to=RECIPIENT, subject="s", body="b")

    remediations = [
        str(_extra(record, "remediation"))
        for record in caplog.records
        if "remediation" in record.__dict__
    ]
    assert len(remediations) == 3
    for sentence in remediations:
        assert len(sentence) <= _MAX_FREE_TEXT, f"truncated in the log: {sentence!r}"
        assert "truncated" not in str(redact_mapping({"remediation": sentence})["remediation"])


def test_the_http_budget_equals_the_number_three_other_places_were_sized_against() -> None:
    """httpx has no whole-request deadline, so the worst case is the SUM of the phases —
    and that sum is load-bearing outside this module. `alerting.ALERT_QUEUE_MAX` is
    justified against "a 15-second SMTP timeout", `alerting._flush_on_exit` waits
    `DELIVERY_RETRY_DELAY_S + 2`, and `scripts/host_alert.FLUSH_TIMEOUT_S` is 45s on the
    stated arithmetic "a 15-second timeout, one retry, plus slack". A 21-second budget
    (the first draft) pushed two attempts plus the retry delay to 47s and would have made
    the backup relay report a delivered alert as undelivered.
    """
    from apps.workers.transport import (
        RESEND_CONNECT_TIMEOUT_S,
        RESEND_POOL_TIMEOUT_S,
        RESEND_READ_TIMEOUT_S,
        RESEND_TIMEOUT_BUDGET_S,
        RESEND_WRITE_TIMEOUT_S,
        SMTP_TIMEOUT_S,
    )

    phases = (
        RESEND_CONNECT_TIMEOUT_S
        + RESEND_WRITE_TIMEOUT_S
        + RESEND_READ_TIMEOUT_S
        + RESEND_POOL_TIMEOUT_S
    )
    assert phases == RESEND_TIMEOUT_BUDGET_S == SMTP_TIMEOUT_S

    from scripts.host_alert import FLUSH_TIMEOUT_S

    from apps.api.core.alerting import DELIVERY_RETRY_DELAY_S

    two_attempts = 2 * RESEND_TIMEOUT_BUDGET_S + DELIVERY_RETRY_DELAY_S
    assert two_attempts <= FLUSH_TIMEOUT_S, (
        "the host-side backup relay would report a delivered alert as undelivered"
    )


@contextlib.contextmanager
def caplog_at_info():  # type: ignore[no-untyped-def]
    """`caplog` is a fixture and this module's non-fixture tests cannot take it."""
    import logging as _logging

    records: list[_logging.LogRecord] = []

    class _Sink(_logging.Handler):
        def emit(self, record: _logging.LogRecord) -> None:
            records.append(record)

    sink = _Sink()
    logger = transport_module.log
    logger.addHandler(sink)
    previous = logger.level
    logger.setLevel(_logging.INFO)
    try:
        yield records
    finally:
        logger.removeHandler(sink)
        logger.setLevel(previous)


# --- the branded alternative, at the wire --------------------------------------
#
# `Transport.send` gained `html` so the client-facing mail can carry the branded part
# (`workers/email_render`). These test the ADAPTERS, because an interface change verified
# only at the composer is a change that may never have reached a provider.
#
# The shared property, and the one worth stating once: html is an ALTERNATIVE, never a
# replacement. A message sent as HTML alone renders as nothing in a text client, nothing
# in a screen reader, and nothing in the inbox preview pane — and the mail this now
# carries includes the link a person needs to set their first password.


def test_resend_sends_both_parts_when_html_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install(monkeypatch, _Response(200, {"id": "m_1"}))
    transport = ResendTransport(api_key="re_test_key", sender="support@calevate.tech")

    assert (
        transport.send(to=RECIPIENT, subject="Set up", body="plain line", html="<p>rich line</p>")
        is True
    )

    (call,) = calls
    assert call["json"]["text"] == "plain line", (
        "the text part is missing from the payload. Resend given only `html` sends an "
        "HTML-only message, which is the one a plain-text client shows as empty."
    )
    assert call["json"]["html"] == "<p>rich line</p>"


def test_smtp_builds_multipart_with_the_text_part_first() -> None:
    """ORDER IS THE STANDARD'S AND IT DECIDES WHAT RENDERS.

    In multipart/alternative the LAST part a client understands is the one it shows, and
    the FIRST is what a client that understands neither falls back to. `set_content` then
    `add_alternative` produces text-then-html; the reverse would show plain text in every
    modern client and make the branded half dead weight.

    Built without a server: `EmailMessage` assembly is the part this adapter owns, and a
    live SMTP conversation would be testing smtplib.
    """
    from email.message import EmailMessage

    message = EmailMessage()
    message["Subject"] = "Set up"
    message.set_content("plain line")
    message.add_alternative("<p>rich line</p>", subtype="html")

    assert message.get_content_type() == "multipart/alternative"
    parts = [part.get_content_type() for part in message.iter_parts()]
    assert parts == ["text/plain", "text/html"], parts

    # And the adapter really does assemble it this way round.
    source = Path(transport_module.__file__).read_text(encoding="utf-8")
    set_at = source.index("message.set_content(body)")
    add_at = source.index('message.add_alternative(html, subtype="html")')
    assert set_at < add_at, (
        "SmtpTransport adds the html alternative BEFORE the text part, so the text "
        "becomes the preferred rendering and the branded part is never shown"
    )


def test_the_console_sink_logs_the_text_and_flags_the_branded_part() -> None:
    """A developer reading a terminal wants the link, not 4KB of table markup — so the
    text is what is logged. `has_html` is there so "did the branded version render?" is
    answerable without dumping it."""
    import logging as _logging

    transport = ConsoleTransport()
    with caplog_at_info() as records:
        assert transport.send(to=RECIPIENT, subject="s", body="plain", html="<p>x</p>") is True
    (record,) = [r for r in records if r.msg == "email_console"]
    assert _extra(record, "has_html") is True
    assert _logging.getLevelName(record.levelno) == "INFO"
