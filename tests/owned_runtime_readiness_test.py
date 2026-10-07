"""`/healthz/ready` under `ENGINE=pipecat` names the carrier leg's preconditions.

`PipecatEngine.holds_credentials()` answers for the control plane, which is our own store,
so before this a deployment with no worker token, no carrier credentials, no claim key and
a `WEBHOOK_BASE_URL` still on its `http://localhost:8100` default reported READY on both
the api and voice-runtime. Each of those surfaced only when the first call rang.

voice-runtime's half must stay plain `Settings` reads (hard rule 3): the probe that
constructs nothing is `tests/voice_runtime_readiness_surface_test.py`'s subject, and the
last test here re-asserts it for the engine this file is about.
"""

from __future__ import annotations

import base64
import sys
from typing import Any

import pytest
from apps.api.core.settings import (
    Settings,
    is_public_callback_base,
    owned_runtime_missing_keys,
    runtime_config_missing_keys,
    webhook_receiver_missing_keys,
)

#: 32 bytes: the worker's floor (`worker_api.MIN_CALLER_CLAIM_KEY_BYTES`), exactly.
GOOD_CLAIM_KEY = "c" * 32


@pytest.fixture(autouse=True)
def _object_store_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    # Read off `os.environ` by readiness; the harness strips them session-wide.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret-key")


def _settings(**overrides: Any) -> Settings:
    """Production-shaped, every non-pipecat requirement satisfied, the carrier leg complete.

    `_env_file=None` so the assertions are about this configuration and not the developer's
    `.env`.
    """
    base: dict[str, Any] = {
        "app_env": "prod",
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
        "engine": "pipecat",
        "carrier": "vobiz",
        "pipecat_worker_api_token": "worker-token",
        "vobiz_auth_id": "MA_TESTACCOUNT",
        "vobiz_auth_token": "vobiz-token",
        "carrier_claim_secret": GOOD_CLAIM_KEY,
        "vobiz_callback_secret": "v" * 64,
        "webhook_base_url": "https://hooks.calevate.tech",
        "pipecat_stream_base_url": "wss://worker.invalid/ws",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


# --- the api / workers half ---------------------------------------------------------------


def test_a_complete_carrier_leg_reports_nothing() -> None:
    """The positive control: without it every refusal below is satisfied by a probe that
    is always red."""
    assert owned_runtime_missing_keys(_settings()) == []


@pytest.mark.parametrize(
    ("field", "env_var"),
    [
        ("pipecat_worker_api_token", "PIPECAT_WORKER_API_TOKEN"),
        ("vobiz_auth_id", "VOBIZ_AUTH_ID"),
        ("vobiz_auth_token", "VOBIZ_AUTH_TOKEN"),
        ("carrier_claim_secret", "CARRIER_CLAIM_SECRET"),
        ("vobiz_callback_secret", "VOBIZ_CALLBACK_SECRET"),
    ],
)
def test_each_missing_precondition_is_named(field: str, env_var: str) -> None:
    assert owned_runtime_missing_keys(_settings(**{field: None})) == [env_var]


def test_the_full_api_probe_carries_the_carrier_leg() -> None:
    """Wired into `runtime_config_missing_keys`, not only callable beside it."""
    missing = runtime_config_missing_keys(
        _settings(pipecat_worker_api_token=None, vobiz_auth_token=None)
    )
    assert "PIPECAT_WORKER_API_TOKEN" in missing
    assert "VOBIZ_AUTH_TOKEN" in missing
    assert len(missing) == len(set(missing)), f"a key was reported twice: {missing}"


def test_a_claim_key_under_the_worker_floor_is_not_a_key() -> None:
    """Set but short is the case that looks configured. The answer leg drops it
    (`usable_caller_claim_key`), so readiness must too."""
    assert owned_runtime_missing_keys(_settings(carrier_claim_secret="c" * 31)) == [
        "CARRIER_CLAIM_SECRET"
    ]


def test_a_carrier_with_nothing_settable_on_this_host_names_the_selection() -> None:
    """Plivo's pair belongs to the worker's secret set (`ENV_ONLY_FOREIGN_ENV`) and its
    adapter is unbuilt, so naming `PLIVO_AUTH_ID` here would tell an operator to put a
    worker credential on the VPS. The thing to correct is `CARRIER`."""
    missing = owned_runtime_missing_keys(_settings(carrier="plivo"))
    assert missing == ["CARRIER"]


def test_other_engines_are_not_asked_about_the_carrier_leg() -> None:
    missing = runtime_config_missing_keys(
        _settings(
            engine="cartesia",
            cartesia_api_key="k",
            pipecat_worker_api_token=None,
            vobiz_auth_id=None,
            vobiz_auth_token=None,
            carrier_claim_secret=None,
            webhook_base_url="http://localhost:8100",
        )
    )
    assert missing == []


# --- the public callback origin ------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8100",
        "http://hooks.calevate.tech",
        "https://localhost",
        "https://api.localhost",
        "https://127.0.0.1",
        "https://127.8.0.1:8443",
        "https://[::1]",
        "https://0.0.0.0",
        "https://",
        "",
        None,
    ],
)
def test_a_callback_base_a_carrier_cannot_reach_is_refused(url: str | None) -> None:
    assert is_public_callback_base(url) is False


@pytest.mark.parametrize(
    "url",
    ["https://hooks.calevate.tech", "https://hooks.calevate.tech:8443/", "https://203.0.113.7"],
)
def test_a_public_https_callback_base_is_accepted(url: str) -> None:
    assert is_public_callback_base(url) is True


def test_the_default_callback_base_is_not_ready_outside_local() -> None:
    assert owned_runtime_missing_keys(_settings(webhook_base_url="http://localhost:8100")) == [
        "WEBHOOK_BASE_URL"
    ]


def test_local_keeps_its_loopback_callback_base() -> None:
    """A developer's carrier double runs on the same machine."""
    cfg = _settings(app_env="local", webhook_base_url="http://localhost:8100")
    assert "WEBHOOK_BASE_URL" not in owned_runtime_missing_keys(cfg)
    assert "WEBHOOK_BASE_URL" not in webhook_receiver_missing_keys(cfg)


# --- the voice-runtime half ---------------------------------------------------------------


def test_the_receiver_probe_is_quiet_on_a_complete_carrier_leg() -> None:
    assert webhook_receiver_missing_keys(_settings()) == []


@pytest.mark.parametrize(
    ("override", "env_var"),
    [
        ({"pipecat_stream_base_url": None}, "PIPECAT_STREAM_BASE_URL"),
        ({"pipecat_stream_base_url": "   "}, "PIPECAT_STREAM_BASE_URL"),
        ({"carrier_claim_secret": None}, "CARRIER_CLAIM_SECRET"),
        ({"carrier_claim_secret": "short"}, "CARRIER_CLAIM_SECRET"),
        ({"vobiz_callback_secret": None}, "VOBIZ_CALLBACK_SECRET"),
        ({"vobiz_callback_secret": "short"}, "VOBIZ_CALLBACK_SECRET"),
        ({"webhook_base_url": "http://hooks.calevate.tech"}, "WEBHOOK_BASE_URL"),
        ({"webhook_base_url": "https://127.0.0.1"}, "WEBHOOK_BASE_URL"),
    ],
)
def test_the_receiver_probe_names_what_the_answer_document_needs(
    override: dict[str, Any], env_var: str
) -> None:
    assert webhook_receiver_missing_keys(_settings(**override)) == [env_var]


def test_the_callback_secret_is_asked_for_only_under_vobiz_outside_local() -> None:
    assert "VOBIZ_CALLBACK_SECRET" not in webhook_receiver_missing_keys(
        _settings(carrier="plivo", vobiz_callback_secret=None)
    )
    local = _settings(app_env="local", vobiz_callback_secret=None)
    assert "VOBIZ_CALLBACK_SECRET" not in owned_runtime_missing_keys(local)
    assert "VOBIZ_CALLBACK_SECRET" not in webhook_receiver_missing_keys(local)


def test_the_receiver_probe_does_not_demand_the_carrier_or_worker_credentials() -> None:
    """Those are the api's and the workers' to use; voice-runtime places no call."""
    cfg = _settings(pipecat_worker_api_token=None, vobiz_auth_id=None, vobiz_auth_token=None)
    assert webhook_receiver_missing_keys(cfg) == []


def test_the_receiver_probe_constructs_no_carrier() -> None:
    """Hard rule 3: the voice-runtime probe reads `Settings` and builds nothing. Measured
    by evicting the carrier adapters and asking; a probe that reached for one would put it
    back in `sys.modules`."""
    adapters = [name for name in sys.modules if name.startswith("apps.api.engine")]
    saved = {name: sys.modules.pop(name) for name in adapters}
    try:
        webhook_receiver_missing_keys(_settings(carrier_claim_secret=None))
        reacquired = sorted(name for name in sys.modules if name.startswith("apps.api.engine"))
        assert reacquired == [], f"the receiver probe imported {reacquired}"
    finally:
        sys.modules.update(saved)


@pytest.mark.parametrize(
    "base",
    [
        # Region-less: Pipecat Cloud routes it to us-west, where the worker is not deployed.
        "wss://api.pipecat.daily.co/ws/plivo?serviceHost=calevate-pipecat-worker.org",
        "https://ap-south.api.pipecat.daily.co/ws/plivo",
        "ws://ap-south.api.pipecat.daily.co/ws/plivo",
        "wss://",
    ],
)
def test_the_receiver_probe_refuses_a_stream_base_a_call_cannot_reach(base: str) -> None:
    assert webhook_receiver_missing_keys(_settings(pipecat_stream_base_url=base)) == [
        "PIPECAT_STREAM_BASE_URL"
    ]


def test_the_regional_pipecat_endpoint_is_ready_and_local_takes_any_value() -> None:
    regional = (
        "wss://ap-south.api.pipecat.daily.co/ws/plivo?serviceHost=calevate-pipecat-worker.org"
    )
    assert webhook_receiver_missing_keys(_settings(pipecat_stream_base_url=regional)) == []
    local = _settings(app_env="local", pipecat_stream_base_url="ws://localhost:7860/ws")
    assert "PIPECAT_STREAM_BASE_URL" not in webhook_receiver_missing_keys(local)
