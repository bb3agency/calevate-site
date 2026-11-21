"""How many calls at once, tries per person and gaps a campaign may choose are console
settings under code ceilings; the API holds every write to them and serves them to the
screens (`GET /v1/campaigns/limits`)."""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.campaigns import service as campaigns
from apps.api.core.errors import ProblemError
from apps.api.core.platform_config import LIVE, applies_rule
from apps.api.core.settings import get_settings
from apps.api.ops.config_service import validated_value
from calevate_shared.config import (
    CAMPAIGN_CONCURRENCY_CEILING,
    CAMPAIGN_RETRY_ATTEMPTS_CEILING,
    CAMPAIGN_RETRY_GAP_CEILING_MINUTES,
)
from tests.campaign_controls_test import _account, _campaign, _client, _one

KEYS = (
    "campaign_max_concurrency",
    "campaign_max_retry_attempts",
    "campaign_retry_gap_max_minutes",
)


def test_the_defaults_are_the_limits_campaigns_had() -> None:
    settings = get_settings()
    assert settings.campaign_max_concurrency == 10
    assert settings.campaign_max_retry_attempts == 5
    assert campaigns.retry_gap_choices() == (15, 30, 60, 120, 240, 1440)
    for key in KEYS:
        assert applies_rule(key).applies == LIVE


@pytest.mark.parametrize(
    ("key", "ceiling"),
    [
        ("campaign_max_concurrency", CAMPAIGN_CONCURRENCY_CEILING),
        ("campaign_max_retry_attempts", CAMPAIGN_RETRY_ATTEMPTS_CEILING),
        ("campaign_retry_gap_max_minutes", CAMPAIGN_RETRY_GAP_CEILING_MINUTES),
    ],
)
def test_no_console_value_passes_the_code_ceiling(key: str, ceiling: int) -> None:
    assert validated_value(key, ceiling) == ceiling
    with pytest.raises(Exception):  # noqa: B017 - the range refusal, whatever its class
        validated_value(key, ceiling + 1)


def test_the_concurrency_ceiling_is_the_engines_stated_allowance() -> None:
    """20 concurrent calls, VENDOR-STATED for our ThinnestAI account."""
    assert CAMPAIGN_CONCURRENCY_CEILING == 20
    assert campaigns.RETRY_GAP_MENU[-1] == CAMPAIGN_RETRY_GAP_CEILING_MINUTES


def test_the_policy_is_held_to_the_console(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ProblemError) as refused:
        campaigns.validated_retry_policy(6, [30] * 5)
    assert refused.value.code == "campaign_retry_attempts_invalid"
    with pytest.raises(ProblemError):
        campaigns.validated_retry_policy(2, [2880])
    monkeypatch.setattr(get_settings(), "campaign_max_retry_attempts", 8)
    monkeypatch.setattr(get_settings(), "campaign_retry_gap_max_minutes", 4320)
    policy = campaigns.validated_retry_policy(8, [30, 60, 1440, 2880, 4320, 4320, 4320])
    assert policy["max_attempts"] == 8
    monkeypatch.setattr(get_settings(), "campaign_retry_gap_max_minutes", 100)
    assert campaigns.retry_gap_choices() == (15, 30, 60)


def test_concurrency_is_held_to_the_console(monkeypatch: pytest.MonkeyPatch) -> None:
    assert campaigns.validated_concurrency(10) == 10
    with pytest.raises(ProblemError) as refused:
        campaigns.validated_concurrency(11)
    assert refused.value.code == "campaign_concurrency_invalid"
    monkeypatch.setattr(get_settings(), "campaign_max_concurrency", 15)
    assert campaigns.validated_concurrency(15) == 15


async def test_the_limits_route_and_a_raised_pace_saves(monkeypatch: pytest.MonkeyPatch) -> None:
    account = await _account()
    campaign_id = await _campaign(account)
    async with _client() as client:
        limits = await client.get("/v1/campaigns/limits", headers=account.headers)
        assert limits.status_code == 200, limits.text
        assert limits.json() == {
            "max_concurrency": 10,
            "max_retry_attempts": 5,
            "retry_gap_choices": [15, 30, 60, 120, 240, 1440],
        }
        refused = await client.patch(
            f"/v1/campaigns/{campaign_id}", headers=account.headers, json={"concurrency": 12}
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["type"].endswith("/campaign_concurrency_invalid")
        monkeypatch.setattr(get_settings(), "campaign_max_concurrency", 12)
        saved = await client.patch(
            f"/v1/campaigns/{campaign_id}", headers=account.headers, json={"concurrency": 12}
        )
        assert saved.status_code == 204, saved.text
        over: dict[str, Any] = {"concurrency": CAMPAIGN_CONCURRENCY_CEILING + 1}
        schema = await client.patch(
            f"/v1/campaigns/{campaign_id}", headers=account.headers, json=over
        )
        assert schema.status_code == 422
    row = await _one(
        account.tenant_id, "SELECT concurrency FROM campaigns WHERE id = :c", c=campaign_id
    )
    assert row[0] == 12
