"""Config must not claim a capability the deployment does not have (TRD §2).

`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `POSTHOG_KEY` were Settings fields
with no client anywhere in the tree: they would have been no-ops WITH real
credentials. A credential-shaped setting is a claim that something is wired, and the
next person fills it in and believes per-call token cost is being recorded.

These tests pin the removal, and pin the honest boot line that replaced the other half
of the problem — a deployment where alerts reach nobody now says so at startup instead
of at 3am.
"""

from __future__ import annotations

import logging

import pytest
from apps.api.core import observability
from apps.api.core.settings import get_settings
from calevate_shared.config import Settings

DEAD_KEYS = ("langfuse_public_key", "langfuse_secret_key", "posthog_key")


@pytest.mark.parametrize("field", DEAD_KEYS)
def test_dead_observability_config_stays_removed(field: str) -> None:
    """If this fails, someone re-added a key without a client. Restoring either
    integration is a vendor decision plus a call site — both written down in
    `calevate_shared/config.py`; the setting is the LAST step, not the first."""
    assert field not in Settings.model_fields


def test_the_alert_recipient_is_configurable_and_defaults_to_nobody() -> None:
    """Unset is the correct local/test default — and is what OPERATIONS §8's
    pre-launch gate ("alerts firing to Sri's phone") is asking someone to change."""
    assert "alerts_email" in Settings.model_fields
    assert Settings.model_fields["alerts_email"].default is None


def test_a_non_local_boot_without_an_alert_recipient_says_so(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "alerts_email", None)
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "sentry_dsn", None)
    monkeypatch.setattr(observability, "init_tracing", lambda _service: False)

    with caplog.at_level(logging.WARNING, logger=observability.log.name):
        enabled = observability.init_observability("api")

    assert enabled == "none"
    assert "alert_delivery_unconfigured" in caplog.text


def test_a_configured_recipient_is_reported_in_the_startup_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator should be able to see at a glance whether alarms go anywhere."""
    settings = get_settings()
    monkeypatch.setattr(settings, "alerts_email", "sri@calevate.tech")
    monkeypatch.setattr(settings, "sentry_dsn", None)
    monkeypatch.setattr(observability, "init_tracing", lambda _service: False)

    assert observability.init_observability("voice-runtime") == "alerts:email"


def test_a_recipient_with_no_transport_behind_it_is_called_out_at_boot(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """ALERTS_EMAIL set and SMTP_HOST unset in prod is the pre-launch gate failing in
    the least visible way available: every alert would reach `NullTransport`."""
    settings = get_settings()
    monkeypatch.setattr(settings, "alerts_email", "sri@calevate.tech")
    monkeypatch.setattr(settings, "smtp_host", None)
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "sentry_dsn", None)
    monkeypatch.setattr(observability, "init_tracing", lambda _service: False)

    with caplog.at_level(logging.WARNING, logger=observability.log.name):
        observability.init_observability("workers")

    assert "alert_delivery_has_no_transport" in caplog.text


def test_init_observability_names_the_process_in_every_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.core import alerting

    monkeypatch.setattr(get_settings(), "sentry_dsn", None)
    monkeypatch.setattr(observability, "init_tracing", lambda _service: False)
    monkeypatch.setattr(alerting, "_service", "api")

    observability.init_observability("voice-runtime")

    assert alerting._service == "voice-runtime"
