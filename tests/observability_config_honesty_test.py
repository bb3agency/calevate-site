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


def test_no_module_holds_a_direct_langfuse_client() -> None:
    """Hard rule 6 names "the redaction hook" in terms of Langfuse, and the honest state
    is that there is no Langfuse at all (D-49). The hook the rule asks for exists as
    `_RedactingSpanExporter`, which filters every span leaving the process.

    That inheritance is CONDITIONAL, and `calevate_shared/config.py` says so in prose:
    restoring Langfuse by exporting the existing OTel spans to a Langfuse OTLP endpoint
    keeps the filter, while a direct `langfuse.get_client()` would be a second,
    UNFILTERED path — the v3 SDK is itself an OpenTelemetry SDK and builds its own
    provider with its own exporter, so nothing this repo installs would be in front of
    it. A warning in a comment is not a control; this is.

    It refuses the SDK IMPORT, not the vendor. Choosing Langfuse is a decision plus
    credentials (config.py names both); this only makes the unfiltered spelling of it
    fail here first, where the reason is written down.

    THE SCAN MOVED, AND THIS TEST FOLLOWED IT (D-169). The AST walk used to live in this
    function and covered `apps/` and `packages/`. It is now the langfuse rung of
    `scripts/check_observability_ready.py`, which runs in `make guardrails` and in CI —
    so the rule blocks a merge rather than only failing a suite — and which asks two
    surfaces this test never could: `scripts/` (operator tooling talks to the same
    models) and the dependency manifest, because a declared package with no import yet
    is the commit before the import. Calling the guardrail here rather than keeping a
    second copy is the house rule: two implementations of one rule agree with each other
    right up until one of them is edited.
    """
    from scripts.check_observability_ready import langfuse_footholds

    offenders = langfuse_footholds()
    assert not offenders, (
        "a direct Langfuse client bypasses `_RedactingSpanExporter` (hard rule 6). Export "
        "the existing OTel spans to a Langfuse OTLP endpoint instead, and record the "
        "choice in the decision log — see calevate_shared/config.py:\n  " + "\n  ".join(offenders)
    )


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
