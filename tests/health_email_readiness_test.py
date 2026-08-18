"""A deployment that can mail nobody is NOT ready (D-392).

THE DEFECT, AND IT IS A LOCKOUT RATHER THAN A MISSING FEATURE. `authn/service.sign_in`
computes `needs_second_factor = realm in MFA_REQUIRED_REALMS`, that set is `{"admin"}`
with nothing to switch it off, and the only way to answer the challenge it mints is the
OTP that `deliver_auth_email` posts. So on a deployment with no email transport EVERY
operator is locked out of the admin console — not degraded, locked out — and the way back
in is not in the product: `RESEND_API_KEY` is in `ENV_ONLY_KEYS`, so the credential that
fixes it can only be installed by editing `.env` on the host, while D-95 put every other
credential in the console you can no longer reach.

Client invitations, password resets and all 120 codes in `runbooks/alarm-index.md` ride
the same transport, so the same misconfiguration also means no alarm reaches anybody —
and `/healthz/ready`, the go-live gate OPERATIONS §2 polls last, answered `ready`
throughout. The only thing that said otherwise was `alert_delivery_has_no_transport`, a
boot-time WARNING, whose own comment concedes the point: "it refuses at 3am, and this
refuses at boot".

WHY IT IS NOT THE "ABSENT OPTIONAL FEATURE" `runtime_config_missing_keys` DECLINES TO
REPORT. That function argues, correctly, that going red for a missing Google credential
would teach operators to ignore the probe: without it the dashboard assistant is off and
calls still land. The test is whether the deployment still does its job. Without a
transport nobody can sign in to watch it do the job.
"""

from __future__ import annotations

import pytest
from apps.api.core.settings import _EMAIL_KEY_FOR_REASON, runtime_config_missing_keys
from calevate_shared.config import (
    EMAIL_PROVIDER_NOT_IMPLEMENTED_REASON,
    NO_EMAIL_PROVIDER_REASON,
    NO_RESEND_API_KEY_REASON,
    NO_SENDER_ADDRESS_REASON,
    NO_SMTP_HOST_REASON,
    Settings,
    email_transport_reason,
)

#: Everything OTHER than email that `runtime_config_missing_keys` demands outside
#: `local`, so a case in this file reports the email key and nothing else. Values are
#: placeholders an operator would never use; none is read, only tested for presence.
_OTHERWISE_COMPLETE = {
    "app_env": "prod",
    "database_url": "postgresql+psycopg://u:p@localhost:5432/x",
    "redis_url": "redis://localhost:6379/0",
    "object_store_endpoint": "https://example.invalid",
    "object_store_bucket": "b",
    "engine": "fake",
    "sarvam_api_key": "sk-test",
    "impersonation_grant_secret": "x" * 48,
    "audit_chain_secret": "x" * 48,
    "idempotency_scope_secret": "x" * 48,
    "platform_kek": "x" * 48,
    "alerts_email": "ops@example.invalid",
}


@pytest.fixture(autouse=True)
def _object_store_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """The two AWS names are read off `os.environ` rather than off `Settings` (the SDK
    resolves its own), so they have to be set here or every case reports them too."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")


def _settings(**overrides: object) -> Settings:
    return Settings.model_validate({**_OTHERWISE_COMPLETE, **overrides})


# --------------------------------------------------------------------------------- 1.


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({}, "EMAIL_PROVIDER", id="no provider at all"),
        pytest.param(
            {"email_provider": "sendgrid"}, "EMAIL_PROVIDER", id="a provider we do not have"
        ),
        pytest.param(
            {"email_provider": "resend", "notifications_from": "   "},
            "NOTIFICATIONS_FROM",
            id="a provider with no return address",
        ),
        pytest.param(
            {"email_provider": "resend", "resend_api_key": None},
            "RESEND_API_KEY",
            id="resend with no key",
        ),
        pytest.param(
            {"email_provider": "smtp", "smtp_host": None},
            "SMTP_HOST",
            id="smtp with no host",
        ),
    ],
)
def test_readiness_names_the_key_that_would_restore_the_transport(
    overrides: dict[str, object], expected: str
) -> None:
    """`fields[]` on a 503 is what the operator acts on, so the entry has to be a name
    they can set — never the resolver's authored reason code, which is for logs."""
    assert runtime_config_missing_keys(_settings(**overrides)) == [expected]


def test_a_working_transport_is_not_reported() -> None:
    """The negative control that keeps this from being an assertion about nothing: with
    the same settings and one real provider, readiness has no complaint at all."""
    settings = _settings(email_provider="resend", resend_api_key="re_test")
    assert email_transport_reason(settings) is None
    assert runtime_config_missing_keys(settings) == []


def test_alerts_email_is_its_own_failure() -> None:
    """A transport addressed to nobody is the same silence one step along, and it is the
    half nothing else in the product degrades to reveal — `alerts_email` has exactly one
    consumer (`configure_alerts`)."""
    settings = _settings(email_provider="resend", resend_api_key="re_test", alerts_email=None)
    assert runtime_config_missing_keys(settings) == ["ALERTS_EMAIL"]


def test_local_is_not_asked_because_the_console_sink_is_a_real_delivery() -> None:
    """A message logged to a developer's terminal genuinely was delivered, which is why
    `email_transport_reason` answers `None` for an unconfigured `local` — and why this
    whole block sits inside the non-local branch rather than testing `app_env` twice."""
    settings = _settings(app_env="local", alerts_email=None)
    assert email_transport_reason(settings) is None
    assert runtime_config_missing_keys(settings) == []


# --------------------------------------------------------------------------------- 2.


def test_every_reason_the_resolver_can_return_has_a_key() -> None:
    """THE ANTI-DRIFT HALF. `_EMAIL_KEY_FOR_REASON` has a `.get(..., "EMAIL_PROVIDER")`
    fallback so a probe can never crash a readiness poll — which also means a reason
    added to the resolver would silently render a plausible, wrong key. This is what
    fails instead.

    Enumerated against the constants rather than by parsing the resolver: they are its
    public vocabulary (`calevate_shared.config.__all__`), and a new one has to be added
    there to be returned.
    """
    for reason in (
        NO_EMAIL_PROVIDER_REASON,
        EMAIL_PROVIDER_NOT_IMPLEMENTED_REASON,
        NO_SENDER_ADDRESS_REASON,
        NO_RESEND_API_KEY_REASON,
        NO_SMTP_HOST_REASON,
    ):
        assert reason in _EMAIL_KEY_FOR_REASON, (
            f"`email_transport_reason` can answer {reason!r} and readiness has no env-var "
            "name to put in fields[] for it, so the operator is told to set EMAIL_PROVIDER "
            "when that is not what is wrong"
        )
