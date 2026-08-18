"""`/healthz/ready` answers for whichever engine is selected, not for Bolna (D-104).

THE DEFECT. `runtime_config_missing_keys` carried one line about one vendor:

    if cfg.engine == "bolna" and not cfg.bolna_api_key:
        missing.append("BOLNA_API_KEY")

D-93/D-94 made `cartesia` a value `ENGINE=` accepts and wired the adapter behind it. That
line did not grow a second clause, so a deployment running `ENGINE=cartesia` with no
`CARTESIA_API_KEY` reported itself READY: a box that cannot place a single call, green on
the probe an orchestrator uses to decide whether to send it traffic. Nothing was lying
anywhere else — `engine_availability()` has always answered
`no_engine_credentials:cartesia` — which is what makes this the interesting kind of bug:
the correct answer already existed and readiness asked a different question of a different
authority.

WHY THE FIX IS NOT A SECOND `if`. That shape is what produced the bug, and a third engine
would need a third clause. Worse, it puts "Bolna needs BOLNA_API_KEY" in `core/settings.py`
— a fact about a vendor, in a module hard rule 2 says may not hold one. So the adapter
answers both halves: `holds_credentials()` for the verdict (already the single authority
`engine_availability` derives from) and `credential_env_keys` for the NAME, because "not
ready" without the key to set is a red light with no next step.

These drive `runtime_config_missing_keys` with hand-built `Settings`, which is the case
that also forced `build_engine` out of `get_engine`: the cache is keyed on engine NAME, so
a cached adapter built from one configuration would answer for another and readiness would
be reporting about a deployment that does not exist.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from apps.api.core.settings import Settings, runtime_config_missing_keys
from apps.api.engine import build_engine, get_engine, missing_engine_credential_keys
from calevate_shared.config import SELECTABLE_ENGINES


@pytest.fixture(autouse=True)
def _object_store_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Part of "every non-engine requirement satisfied", and it cannot live in
    `_settings()` because it is not a `Settings` field.

    Readiness reports `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` off `os.environ` — that
    is where botocore reads them and where the app therefore has to look. The suite's
    `_no_ambient_credentials` fixture strips both session-wide so local matches CI, so
    without this every assertion in this file would carry two extra keys it is not about.
    Declared here rather than borrowed, which is that fixture's whole rule.
    """
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret-key")


def _settings(**overrides: Any) -> Settings:
    """A production-shaped configuration with every non-engine requirement satisfied.

    Everything readiness checks OUTSIDE the engine is present, so any key these tests see
    reported came from the engine clause and nowhere else. `app_env="prod"` because the
    secret checks are skipped under `local`, and this file is about the branch a real
    deployment takes.

    `_env_file=None` is not optional: without it pydantic-settings reads this repo's
    `.env`, and the test would assert about whatever the developer's machine happens to
    hold — the exact class `tests/harness_ambient_env_test.py` exists to close.
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
        # The KEK joined the readiness list with P3.3's ops sweep. Present here for the
        # reason every other secret above is: this file is about the ENGINE clause, and a
        # key reported from anywhere else would be noise these assertions cannot tell
        # apart from the thing they measure.
        "platform_kek": base64.b64encode(b"k" * 32).decode(),
        # EMAIL joined the readiness list with D-392, for a reason that has nothing
        # to do with the engine: the admin realm's second factor is an emailed OTP,
        # so a deployment with no transport locks every operator out of the console.
        # Satisfied here on the same terms as every secret above — a key reported
        # from outside the engine clause is noise this file cannot tell apart from
        # what it measures. `alerts_email` is the recipient half of the same fact.
        "email_provider": "resend",
        "resend_api_key": "re_test",
        "alerts_email": "ops@example.invalid",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def test_a_credential_less_cartesia_deployment_is_not_ready() -> None:
    """THE BUG, stated as the assertion that was missing.

    Before D-104 this returned `[]` and `/healthz/ready` was 200 — the deployment declared
    itself fit to receive traffic while every outbound call it could be asked to place
    would refuse at the vendor boundary.
    """
    missing = runtime_config_missing_keys(_settings(engine="cartesia"))
    assert "CARTESIA_API_KEY" in missing, (
        "a deployment that cannot reach its voice platform reported itself ready — "
        "the exact condition /healthz/ready exists to catch"
    )


def test_a_credentialled_cartesia_deployment_is_ready() -> None:
    """The other half, and it is not symmetric decoration: a readiness probe that is red
    when it should be green is an outage of its own, and the cheapest way to get the test
    above passing is a check that never goes green."""
    assert runtime_config_missing_keys(_settings(engine="cartesia", cartesia_api_key="k")) == []


def test_bolna_still_answers_exactly_as_it_did() -> None:
    """The behaviour that already worked, pinned before it was generalised away.

    This is the regression the refactor could plausibly cause: the hardcoded clause was
    correct for Bolna, and replacing correct-for-one with general-for-all is only an
    improvement if the one still holds.
    """
    assert runtime_config_missing_keys(_settings(engine="bolna")) == ["BOLNA_API_KEY"]
    assert runtime_config_missing_keys(_settings(engine="bolna", bolna_api_key="k")) == []


def test_the_fake_engine_never_holds_readiness_down() -> None:
    """`ENGINE=fake` IS its own vendor (DEV-SETUP §3). An empty `credential_env_keys` and a
    permanently-True `holds_credentials` must combine to report nothing, or local
    development gets a red probe for a credential that does not exist."""
    assert runtime_config_missing_keys(_settings(engine="fake")) == []


@pytest.mark.parametrize("engine", sorted(SELECTABLE_ENGINES))
def test_every_selectable_engine_names_the_keys_it_is_missing(engine: str) -> None:
    """Derived from `SELECTABLE_ENGINES`, so an engine added to `EngineName` is covered by
    this file the day it is added rather than the day somebody remembers to extend a list.

    The property: an adapter without credentials must NAME what it needs. An adapter that
    reported `holds_credentials() is False` and an empty `credential_env_keys` would fail
    readiness forever with nothing an operator could do about it — a permanent red light
    is indistinguishable from a broken probe.
    """
    adapter = build_engine(_settings(engine=engine))
    if adapter.holds_credentials():
        assert missing_engine_credential_keys(_settings(engine=engine)) == ()
        return
    keys = missing_engine_credential_keys(_settings(engine=engine))
    assert keys, f"{engine} refuses for want of credentials but names no key to set"
    assert all(key.isupper() for key in keys), (
        f"{engine} reports {keys!r}; readiness publishes ENVIRONMENT key names, and a "
        "lowercase Settings field name sends an operator looking for the wrong thing"
    )


def test_readiness_reads_the_settings_it_was_handed_not_a_cached_adapter() -> None:
    """WHY `build_engine` EXISTS, as a test rather than a comment.

    `get_engine` caches on the engine NAME, which is right for the request path — one
    process serves one deployment. It is wrong for a caller that constructs its own
    `Settings`: warm the cache with a credentialled adapter, then ask readiness about a
    credential-less configuration of the same engine, and a cache-reading implementation
    answers "ready" about a deployment that is not.
    """
    from apps.api.engine import reset_engine_cache

    reset_engine_cache()
    try:
        get_engine(_settings(engine="cartesia", cartesia_api_key="warm-the-cache"))
        assert runtime_config_missing_keys(_settings(engine="cartesia")) == ["CARTESIA_API_KEY"], (
            "readiness answered from a cached adapter built from different settings"
        )
    finally:
        reset_engine_cache()


def test_the_engine_clause_is_gone_from_core_settings() -> None:
    """Hard rule 2 as a grep, because the fix is only durable if the old shape cannot
    quietly come back. A per-vendor credential name in `core/settings.py` is exactly the
    line this decision removed, and re-adding one is easier than noticing it."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "apps/api/core/settings.py").read_text()
    for vendor_key in ("BOLNA_API_KEY", "CARTESIA_API_KEY"):
        assert f'"{vendor_key}"' not in source, (
            f"{vendor_key} is named in core/settings.py again — vendor credential names "
            "belong to the adapter that reads them (apps/api/engine/), not to a core "
            "module that has to grow a clause per vendor"
        )
