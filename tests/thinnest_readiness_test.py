"""`/healthz/ready` on `ENGINE=thinnest`: every key the engine cannot serve without.

The engine's own credential (`THINNEST_API_KEY`) comes from the adapter through
`missing_engine_credential_keys`; the public `WEBHOOK_BASE_URL`, the public
`ENGINE_ACTIONS_BASE_URL` its in-call actions call, and `ENGINE_INTAKE_KEK` are deployment
keys this engine adds. The intake key seals and opens each agent's webhook signing
secret, so all three services report it: the api (seals at publish), the workers (open sealed
deliveries) and voice-runtime (verifies every delivery).
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from apps.api.core.settings import (
    Settings,
    readiness_missing_keys,
    runtime_config_missing_keys,
    webhook_receiver_missing_keys,
)

_GOOD_KEK = base64.b64encode(b"t" * 32).decode()


@pytest.fixture(autouse=True)
def _object_store_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    # Readiness reads these off `os.environ`; present so only engine keys are reported.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret-key")


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "app_env": "prod",
        "engine": "thinnest",
        "database_url": "postgresql+psycopg://calevate_app:x@db.internal:5432/calevate",
        "redis_url": "redis://redis.internal:6379/0",
        "object_store_endpoint": "https://example.invalid",
        "object_store_bucket": "calevate-prod",
        "sarvam_api_key": "sk-sarvam",
        "impersonation_grant_secret": "i" * 32,
        "audit_chain_secret": "a" * 32,
        "idempotency_scope_secret": "d" * 32,
        "platform_kek": base64.b64encode(b"k" * 32).decode(),
        "email_provider": "resend",
        "resend_api_key": "re_test",
        "alerts_email": "ops@example.invalid",
        "thinnest_api_key": "ta_live_test",
        "webhook_base_url": "https://hooks.example.com",
        "engine_intake_kek": _GOOD_KEK,
        "engine_actions_base_url": "https://api.example.com",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def test_a_fully_configured_thinnest_deployment_is_ready() -> None:
    cfg = _settings()
    assert runtime_config_missing_keys(cfg) == []
    assert webhook_receiver_missing_keys(cfg) == []


def test_the_api_key_is_reported_when_absent() -> None:
    assert "THINNEST_API_KEY" in runtime_config_missing_keys(_settings(thinnest_api_key=None))


def test_a_private_callback_base_is_reported() -> None:
    missing = runtime_config_missing_keys(_settings(webhook_base_url="http://localhost:8100"))
    assert "WEBHOOK_BASE_URL" in missing


@pytest.mark.parametrize("kek", [None, "not-base64!", base64.b64encode(b"short").decode()])
def test_an_absent_or_unusable_intake_key_holds_every_service_down(kek: str | None) -> None:
    cfg = _settings(engine_intake_kek=kek)
    for service in ("api", "workers", "voice-runtime"):
        assert "ENGINE_INTAKE_KEK" in readiness_missing_keys(service, cfg), service


def test_local_derives_a_development_intake_key() -> None:
    cfg = _settings(app_env="local", engine_intake_kek=None)
    assert "ENGINE_INTAKE_KEK" not in runtime_config_missing_keys(cfg)
    assert "ENGINE_INTAKE_KEK" not in webhook_receiver_missing_keys(cfg)


def test_the_intake_key_is_not_asked_of_another_engine() -> None:
    cfg = _settings(engine="fake", engine_intake_kek=None)
    assert "ENGINE_INTAKE_KEK" not in runtime_config_missing_keys(cfg)
    assert "ENGINE_INTAKE_KEK" not in webhook_receiver_missing_keys(cfg)


def test_the_in_call_actions_origin_is_reported_by_the_api_and_not_by_voice_runtime() -> None:
    cfg = _settings(engine_actions_base_url=None)
    assert "ENGINE_ACTIONS_BASE_URL" in runtime_config_missing_keys(cfg)
    # voice-runtime never publishes an agent, so it does not need the api's own origin.
    assert "ENGINE_ACTIONS_BASE_URL" not in webhook_receiver_missing_keys(cfg)


def test_a_loopback_actions_origin_is_reported() -> None:
    cfg = _settings(engine_actions_base_url="https://localhost:8000")
    assert "ENGINE_ACTIONS_BASE_URL" in runtime_config_missing_keys(cfg)
