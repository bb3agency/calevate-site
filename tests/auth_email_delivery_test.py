"""`deliver_auth_email` under failure — the one message a person is actively waiting for.

This job carries every one-time secret `apps/api/authn` mints (D-170): password resets,
the email-verification code, the sign-in OTP, the invitation link. Its failure mode is a
person staring at a screen that has truthfully told them an email is on its way.

It shipped with a docstring promising a retry ladder and a dead-letter queue, and had
NEITHER:

* it raised `RuntimeError` on an undelivered send, and arq 0.28 retries for `Retry`,
  `RetryJob` and `CancelledError` and for nothing else — so `WorkerSettings.max_tries = 3`
  never reached it and one bad minute at the mail provider was terminal;
* there is no arq dead-letter queue (`WorkerSettings`' docstring), so the only trace of a
  lost reset link was a `log.warning`.

The tests below are the shape of both failures. `test_a_transient_failure_asks_for_the
_retry_ladder` fails against the old code with `RuntimeError`; `test_the_last_attempt
_alerts` fails against it with the same, because it never got to a last attempt.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from apps.api.core import console_links
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.workers import auth_email, transport
from arq import Retry

pytestmark = pytest.mark.asyncio

#: Read at IMPORT, in a synchronous context. `Path.read_text()` inside an `async def` is
#: a blocking call on the event loop and ruff (ASYNC240) refuses it — correctly, even for
#: a test — so the one file this suite inspects as TEXT is loaded once, here.
_OTP_SOURCE = (Path(__file__).resolve().parents[1] / "apps/api/authn/otp.py").read_text(
    encoding="utf-8"
)

#: Stand-in so a missing constant fails on the ASSERTION below with a sentence a
#: reader can act on, rather than on `None.group` at import.
_NO_MATCH = re.match(r"(?P<x>)", "")

#: The client console's accept-invitation route, read out of the TypeScript that defines it
#: rather than restated here — a constant copied into a Python string is the drift this
#: guard exists to catch. Resolved at import so the test itself does no file I/O.
_CLIENT_AUTHN_TS = Path(__file__).resolve().parent.parent / "apps/web/src/lib/authn/clientAuthn.ts"
WEB_ACCEPT_INVITE_PATH = (
    re.search(
        r'CLIENT_ACCEPT_INVITE_PATH\s*=\s*"([^"]+)"',
        _CLIENT_AUTHN_TS.read_text(encoding="utf-8"),
    )
    or _NO_MATCH
).group(1)

#: The admin console's bootstrap route, same treatment as the invite one above.
_ADMIN_AUTHN_TS = Path(__file__).resolve().parent.parent / "apps/web/src/lib/authn/adminAuthn.ts"
WEB_ADMIN_BOOTSTRAP_PATH = (
    re.search(
        r'ADMIN_BOOTSTRAP_PATH\s*=\s*"([^"]+)"',
        _ADMIN_AUTHN_TS.read_text(encoding="utf-8"),
    )
    or _NO_MATCH
).group(1)

_APP_DIR = Path(__file__).resolve().parent.parent / "apps/web/src/app"


def _served_paths() -> frozenset[str]:
    """Every URL the Next.js App Router actually serves a page for.

    THE AUTHORITY, and the reason this exists at all. The guard that used to stand here
    compared the two bootstrap-link composers TO EACH OTHER; they agreed, on
    `/bootstrap`, which is a page nobody serves. Agreement between writers proves nothing
    about the thing that has to answer — so the paths are resolved against the route tree
    on disk instead.

    `(auth)` and friends are ROUTE GROUPS: they organise files and contribute NO url
    segment, which is exactly what makes `/auth/admin/bootstrap` hard to read off a
    directory listing and easy to get wrong from memory. Dynamic segments (`[slug]`) are
    dropped rather than modelled — no mailed link has one, and pretending to match them
    would let a wrong path pass by landing on a catch-all.
    """
    paths = set()
    for page in _APP_DIR.rglob("page.tsx"):
        segments = [
            part
            for part in page.relative_to(_APP_DIR).parent.parts
            if not (part.startswith("(") and part.endswith(")"))
        ]
        if any(part.startswith("[") for part in segments):
            continue
        paths.add("/" + "/".join(segments) if segments else "/")
    return frozenset(paths)


PAYLOAD: dict[str, Any] = {
    "kind": "password_reset",
    "realm": "client",
    "to": "someone@example.com",
    "secret": "tok_not_a_real_secret",
}


class _Transport:
    """A transport that answers however the test needs and records what it was asked."""

    def __init__(self, *, delivers: bool) -> None:
        self.delivers = delivers
        self.sent: list[tuple[str, str, str]] = []

    def send(self, *, to: str, subject: str, body: str) -> bool:
        self.sent.append((to, subject, body))
        return self.delivers


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str | None]]:
    """Every `alert()` this job fires, captured. The alert IS the dead letter here, so a
    test that did not assert on it would be asserting that the job fails quietly."""
    fired: list[tuple[str, str, str | None]] = []

    def _capture(stage: str, code: str, *, detail: str | None = None, **ids: str) -> None:
        fired.append((stage, code, detail))

    monkeypatch.setattr(auth_email, "alert", _capture)
    return fired


def _install(monkeypatch: pytest.MonkeyPatch, delivers: bool) -> _Transport:
    fake = _Transport(delivers=delivers)
    monkeypatch.setattr(auth_email, "get_transport", lambda: fake)
    return fake


async def test_a_delivered_email_is_sent_once_and_reported(
    monkeypatch: pytest.MonkeyPatch, alerts: list[tuple[str, str, str | None]]
) -> None:
    fake = _install(monkeypatch, delivers=True)
    assert await auth_email.deliver_auth_email({"job_try": 1}, PAYLOAD) == "sent"
    assert len(fake.sent) == 1
    to, subject, body = fake.sent[0]
    assert to == PAYLOAD["to"] and subject == "Reset your Calevate password"
    assert PAYLOAD["secret"] in body, "the link would not work"
    assert alerts == []


async def test_a_transient_failure_asks_for_the_retry_ladder(
    monkeypatch: pytest.MonkeyPatch, alerts: list[tuple[str, str, str | None]]
) -> None:
    """THE REGRESSION. The old code raised `RuntimeError`, which arq does not retry, so
    this attempt was the only one — `WorkerSettings.max_tries` never applied."""
    _install(monkeypatch, delivers=False)
    with pytest.raises(Retry) as raised:
        await auth_email.deliver_auth_email({"job_try": 1}, PAYLOAD)
    # arq reads the deferral off the exception, in milliseconds.
    assert raised.value.defer_score == int(auth_email.RETRY_BACKOFF_S[0] * 1000)
    assert alerts == [], "the ladder has not run out yet; alerting now would cry wolf"


async def test_every_attempt_before_the_last_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ladder is one entry shorter than the budget, so the arithmetic has to hold for
    every attempt rather than only the first."""
    _install(monkeypatch, delivers=False)
    monkeypatch.setattr(auth_email, "alert", lambda *a, **k: None)
    for attempt in range(1, WORKER_MAX_TRIES):
        with pytest.raises(Retry):
            await auth_email.deliver_auth_email({"job_try": attempt}, PAYLOAD)


async def test_the_last_attempt_alerts_instead_of_failing_in_silence(
    monkeypatch: pytest.MonkeyPatch, alerts: list[tuple[str, str, str | None]]
) -> None:
    """There is no arq DLQ, so the alert is the dead letter. Without it a lost password
    reset is a `log.warning` and nothing else."""
    _install(monkeypatch, delivers=False)
    outcome = await auth_email.deliver_auth_email({"job_try": WORKER_MAX_TRIES}, PAYLOAD)
    assert outcome == f"exhausted after {WORKER_MAX_TRIES}"
    assert len(alerts) == 1, alerts
    stage, code, detail = alerts[0]
    assert (stage, code) == ("WORKER_DELIVERY", "auth_email_exhausted")
    assert detail is not None and "password_reset" in detail


async def test_the_alert_body_carries_no_mailbox_and_no_secret(
    monkeypatch: pytest.MonkeyPatch, alerts: list[tuple[str, str, str | None]]
) -> None:
    """Hard rule 6, on the path most exposed to it: the payload holds an email address AND
    a live credential, and an alert body is forwarded further than a log line is."""
    _install(monkeypatch, delivers=False)
    await auth_email.deliver_auth_email({"job_try": WORKER_MAX_TRIES}, PAYLOAD)
    detail = alerts[0][2] or ""
    assert PAYLOAD["secret"] not in detail
    assert "someone@" not in detail and "someone" not in detail
    assert "example.com" in detail, "the domain is the part an operator can act on"


async def test_a_malformed_payload_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, alerts: list[tuple[str, str, str | None]]
) -> None:
    """OUR bug, not a transient failure. Walking the ladder would spend three attempts
    learning what the first one already said, and the ladder is for the provider."""
    _install(monkeypatch, delivers=True)
    with pytest.raises(ValueError):
        await auth_email.deliver_auth_email({"job_try": 1}, {**PAYLOAD, "kind": "not_a_kind"})
    assert alerts == []


async def test_the_ladder_fits_inside_the_shortest_secret_it_carries() -> None:
    """An OTP expires in ten minutes (`_body`). A ladder that outlasted it would retry its
    way to a code that no longer works, which is a delivery nobody can use."""
    assert len(auth_email.RETRY_BACKOFF_S) == WORKER_MAX_TRIES - 1
    assert sum(auth_email.RETRY_BACKOFF_S) < 10 * 60


async def test_the_real_transport_protocol_is_what_the_fake_implements() -> None:
    """The fake above is only evidence while it is the shape the job actually calls. A
    signature change in `transport.Transport` must break this file, not pass through it."""
    import inspect

    expected = inspect.signature(transport.Transport.send)
    assert inspect.signature(_Transport.send) == expected


def test_the_route_tree_resolver_can_see_the_app_at_all() -> None:
    """The premise every assertion below rests on.

    FAILS IF: `apps/web/src/app` moves, or Next stops using `page.tsx`. Without this, an
    empty set would make every path below look wrong and send the next reader after a
    composer that is fine.
    """
    served = _served_paths()
    assert len(served) > 20, f"only {len(served)} routes found — the resolver is blind"
    assert "/auth/sign-in" in served, sorted(served)[:20]


@pytest.mark.parametrize(
    ("what", "link"),
    [
        ("the operator setup link", console_links.admin_bootstrap_link("tok")),
        ("the client password reset", console_links.password_reset_link("client", "tok")),
        ("the operator password reset", console_links.password_reset_link("admin", "tok")),
        ("the invitation link", console_links.accept_invitation_link("tok")),
    ],
)
def test_every_mailed_link_names_a_page_this_app_serves(what: str, link: str) -> None:
    """THE GUARD THAT WAS MISSING, and two of these four failed the day it was written.

    `admin_bootstrap` said `/bootstrap`; the page is `/auth/admin/bootstrap`.
    `password_reset` said `/reset-password` for BOTH realms; the pages are
    `/auth/reset-password` and `/auth/admin/reset-password`. Each is single-use and
    short-lived, so a wrong path does not merely inconvenience somebody — it burns the
    credential, and the bootstrap one is the only way into a fresh deployment.
    """
    path = urlsplit(link).path
    served = _served_paths()
    assert path in served, (
        f"{what} points at {path}, which no page serves. Nearest: "
        f"{sorted(p for p in served if p.startswith('/auth'))}"
    )


def test_the_query_parameter_is_the_one_the_page_strips_from_the_url() -> None:
    """`useLinkToken` takes exactly `token` out of the URL on arrival, so the secret is not
    left in browser history or in a screenshot. A link that named it anything else would
    both fail to redeem AND leave the token sitting in the address bar."""
    for link in (
        console_links.admin_bootstrap_link("tok"),
        console_links.password_reset_link("client", "tok"),
        console_links.accept_invitation_link("tok"),
    ):
        assert parse_qs(urlsplit(link).query) == {"token": ["tok"]}, link


def test_the_two_realms_get_different_reset_pages_on_different_hosts() -> None:
    """One string served both realms before, which is how it could be wrong for both at
    once. Admin and client are separate hostnames with separate session modules (D-177);
    a shared reset URL is a category error even when the path happens to exist."""
    admin = console_links.password_reset_link("admin", "tok")
    client = console_links.password_reset_link("client", "tok")
    assert admin != client
    assert admin.startswith(console_links.ADMIN_CONSOLE_BASE)
    assert client.startswith(console_links.CONSOLE_BASE)


@pytest.mark.parametrize(
    ("ts_path", "python_path", "constant"),
    [
        (
            WEB_ACCEPT_INVITE_PATH,
            console_links.CLIENT_ACCEPT_INVITE_PATH,
            "CLIENT_ACCEPT_INVITE_PATH",
        ),
        (WEB_ADMIN_BOOTSTRAP_PATH, console_links.ADMIN_BOOTSTRAP_PATH, "ADMIN_BOOTSTRAP_PATH"),
    ],
)
def test_the_web_app_and_the_mailer_name_the_same_page(
    ts_path: str, python_path: str, constant: str
) -> None:
    """The route tree says the page EXISTS; this says the browser code agrees which one it
    is. Both are needed: a rename that moved the directory and the TypeScript constant
    together would keep the test above green while the mailer pointed at the old page.
    """
    assert ts_path, f"{constant} moved or was renamed — this guard is blind"
    assert ts_path == python_path, (
        f"{constant} is {ts_path!r} in the web app and {python_path!r} in "
        "apps/api/core/console_links — one of them is mailing a dead URL"
    )


async def test_the_bodies_carry_the_composed_link_rather_than_one_of_their_own() -> None:
    """`_body` used to write these URLs itself, and `scripts/bootstrap_admin` wrote the
    same one a second time. Both now delegate, which is what makes the guards above cover
    the mail that actually goes out rather than a function nobody sends."""
    from scripts.bootstrap_admin import _link

    assert console_links.admin_bootstrap_link("tok_admin") in auth_email._body(
        "admin_bootstrap", "admin", "tok_admin"
    )
    assert _link("tok_admin") == console_links.admin_bootstrap_link("tok_admin")
    assert console_links.accept_invitation_link("tok_abc") in auth_email._body(
        "invite_password", "client", "tok_abc"
    )
    for realm in ("admin", "client"):
        assert console_links.password_reset_link(realm, "tok_r") in auth_email._body(
            "password_reset", realm, "tok_r"
        )
    assert auth_email._SUBJECTS["admin_bootstrap"], "the kind has no subject line"


async def test_every_kind_the_api_can_enqueue_has_a_subject_and_a_body() -> None:
    """A kind with no `_SUBJECTS` entry is a `ValueError` on the FIRST attempt — the
    payload the job treats as our bug and refuses to retry. That is the right refusal and
    the wrong place to discover a new kind, because the discovery happens in a worker, on
    somebody's password reset, after the request that enqueued it returned 200.

    The list is the API's, read off the call sites rather than restated: `_enqueue_auth_email`
    is private and its four public callers each name one kind.
    """
    for kind in ("password_reset", "invite_password", "admin_bootstrap"):
        assert kind in auth_email._SUBJECTS, kind
        body = auth_email._body(kind, "admin" if kind == "admin_bootstrap" else "client", "tok")
        assert "tok" in body and body.strip()


# --- the dev sink actually delivers (D-409) -------------------------------------------
#
# Admin sign-in is password + an emailed six-digit code (D-170). The code is stored only
# as a keyed hash, so the plaintext lives in exactly one place: the message body. The
# console sink logged the recipient's domain, the subject and a CHARACTER COUNT — so on a
# laptop the one thing a developer needed was the one thing discarded, and a correctly
# working second factor presented as a broken one.
#
# WHAT THESE TESTS ARE REALLY GUARDING is the shape of the fix rather than the fix: the
# tempting repair is a flag that skips the OTP check on local, which would leave
# `authn/otp.py` unexercised on every laptop and sit one env var away from doing the same
# in production. `test_no_app_env_branch_can_skip_the_second_factor` is the one that says
# so in code.


async def test_the_dev_sink_delivers_the_code_a_developer_needs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A sink that reports success while discarding the content did not deliver anything.

    Asserted on a realistic OTP body, because the six digits are the payload: this test
    fails against the old transport, which logged `chars=...` and nothing else.
    """
    from apps.api.core.settings import get_settings

    assert get_settings().app_env == "local", "the suite is not on the branch under test"
    body = "Your Calevate sign-in code is 481920. It is good for ten minutes."

    with caplog.at_level(logging.DEBUG):
        assert transport.ConsoleTransport().send(
            to="ops@calevate.example.com", subject="Your sign-in code", body=body
        )

    delivered = [r for r in caplog.records if r.getMessage() == "email_console"]
    assert delivered, "the console sink logged nothing at all"
    assert any("481920" in str(getattr(r, "dev_message", "")) for r in delivered), (
        "the console sink did not carry the code, so a local admin sign-in cannot be completed"
    )


async def test_the_dev_sink_prints_no_body_outside_local(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Defence in depth, and the half whose failure is a real customer's message in an
    aggregated log.

    `get_transport` should never reach this class outside APP_ENV=local — the resolver in
    `config.email_transport_reason` decides that first. This asserts the transport does
    not RELY on that: two reads of one fact eventually disagree, and the cost of this
    particular disagreement is disclosure rather than an error.
    """
    from apps.api.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "app_env", "prod")
    body = "Your Calevate sign-in code is 481920. It is good for ten minutes."

    with caplog.at_level(logging.DEBUG):
        assert transport.ConsoleTransport().send(
            to="ops@calevate.example.com", subject="Your sign-in code", body=body
        )

    for record in caplog.records:
        assert "481920" not in str(getattr(record, "dev_message", "")), (
            "the console sink printed a message body outside APP_ENV=local"
        )
        assert not hasattr(record, "dev_message"), "the dev-only field escaped local"


async def test_the_body_is_still_redacted_on_the_way_out(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Hard rule 6 does not get a local exemption, and it does not need one.

    The body rides in an EXTRA, so `JsonFormatter` sends it through `redact_mapping` —
    a caller's number in a hot-lead alert is masked while a six-digit OTP survives
    (`_PHONE_RE` needs nine-plus digits). That is the whole reason the field is an extra
    rather than an f-string in the message, and it is why the key name matters below.
    """
    from apps.api.core.logging import redact_mapping

    body = "Code 481920. Lead Padma Rao, +919812345678, asked about implants."
    rendered = redact_mapping({"dev_message": body})["dev_message"]

    assert "481920" in rendered, "redaction ate the OTP, which is the payload"
    assert "+919812345678" not in rendered, "a caller's number reached a log line"
    assert "[phone]" in rendered


async def test_the_dev_message_key_stays_out_of_the_redact_list() -> None:
    """The fix is one word from being silently undone.

    `body`, `text` and `recipient` are all in `REDACT_KEYS`, so the OBVIOUS names for this
    field would render `[redacted]` and restore the exact bug — a sink that logs a
    placeholder where the code should be, with every test above still passing on the
    presence of the field. Adding `dev_message` (or `message`, or `dev`) to that tuple
    later would do the same, so the incompatibility is pinned here rather than discovered
    by the next person who cannot sign in.
    """
    from apps.api.core.logging import REDACT_KEYS

    assert not any(marker in "dev_message" for marker in REDACT_KEYS), (
        "`dev_message` now matches a REDACT_KEYS marker, so the console sink logs "
        "'[redacted]' instead of the code and local admin sign-in is broken again"
    )


async def test_no_app_env_branch_can_skip_the_second_factor() -> None:
    """**THIS IS A DELIVERY FIX, NOT AN MFA BYPASS, and this test is what keeps it one.**

    The cheap way to make a local sign-in easy is `if app_env == "local": return True`
    somewhere in the OTP path. It would work, and it would be wrong twice: the code path
    most worth exercising would go unexercised on every developer's machine, and the
    branch would sit one misconfigured environment variable away from accepting any code
    in production (CLAUDE.md: never add a bypass "for testing").

    So `authn/otp.py` must not read the environment at all. Asserted as TEXT because the
    edit that would break it is one line long and reads, in isolation, like a convenience.
    """
    source = _OTP_SOURCE

    for smell in ("app_env", "APP_ENV", "is_local", "DEBUG"):
        assert smell not in source, (
            f"{smell!r} appears in authn/otp.py — the second factor must not know which "
            "environment it is running in, or 'local' becomes a value someone can set"
        )
