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

import re
from pathlib import Path
from typing import Any

import pytest
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.workers import auth_email, transport
from arq import Retry

pytestmark = pytest.mark.asyncio

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


async def test_the_invitation_link_names_the_page_the_web_app_serves() -> None:
    """The guard `auth_email.py`'s own comment promised and nobody wrote.

    That comment named `tests/auth_email_test.py`, a file this repo does not have, so the
    emailed path and the web app's path could drift apart with nothing going red — the
    same defect class as a router nobody mounted. D-190 made this template the ONLY way an
    invitation reaches anybody, so a stale path here is a dead invite for every new member.

    The path is READ OUT OF the TypeScript source (at import, so this stays a pure
    assertion): a constant copied into a Python string is the drift, not the guard.
    """
    assert WEB_ACCEPT_INVITE_PATH, "CLIENT_ACCEPT_INVITE_PATH moved — this guard is blind"
    body = auth_email._body("invite_password", "client", "tok_abc")
    assert f"{WEB_ACCEPT_INVITE_PATH}?token=tok_abc" in body, (
        f"the invitation email points somewhere other than {WEB_ACCEPT_INVITE_PATH}, which "
        "is the page the web app actually serves"
    )
