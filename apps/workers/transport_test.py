"""Transport selection and the honesty property.

The behaviour worth testing is not "does SMTP work" (it is smtplib) but "does an
unconfigured deployment tell the truth". A transport that returns success with nothing
wired makes the 2-minute hot-lead SLO look met while no client is ever told.
"""

from __future__ import annotations

import pytest

from apps.api.core.settings import get_settings
from apps.workers.transport import (
    ConsoleTransport,
    NullTransport,
    SmtpTransport,
    get_transport,
)


def test_local_without_smtp_uses_the_console_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", None)
    monkeypatch.setattr(settings, "app_env", "local")
    assert isinstance(get_transport(), ConsoleTransport)


def test_a_configured_host_selects_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    assert isinstance(get_transport(), SmtpTransport)


def test_a_non_local_env_without_smtp_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The property this module exists for: silence is reported, not swallowed."""
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", None)
    monkeypatch.setattr(settings, "app_env", "prod")
    transport = get_transport()
    assert isinstance(transport, NullTransport)
    assert transport.send(to="owner@example.com", subject="x", body="y") is False


def test_console_transport_reports_success() -> None:
    """It really did deliver — to a terminal. Reporting False would train developers to
    ignore the delivered flag."""
    assert ConsoleTransport().send(to="owner@example.com", subject="x", body="y") is True


def test_smtp_failure_returns_false_rather_than_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """The caller decides whether a failed notification retries the job; it records the
    outcome on the lead timeline either way."""
    transport = SmtpTransport(
        host="127.0.0.1", port=1, username=None, password=None, sender="a@b.test"
    )
    assert transport.send(to="owner@example.com", subject="x", body="y") is False
