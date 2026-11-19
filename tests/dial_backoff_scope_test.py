"""The dial hold-off after a ThinnestAI `429` holds only what the refused limit covers: one
`from` number's daily cap holds dials from that number, a workspace's request limit holds
that client's workspace, and every other limit holds the whole account
(`engine/dial_lines.py`; snapshots/2026-10-29/pages/api-reference/errors.md:100-108,
calls/place-call.md:674-711).
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine import dial_lines, vendor_http
from apps.api.engine.dial_lines import DialOrigin
from apps.api.engine.vendor_http import (
    NUMBER_DAILY_LIMIT_CODE,
    EngineNumberDailyLimitError,
    EngineRateLimitedError,
    ThrottleScope,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.ttl_ms: dict[str, int] = {}

    async def pttl(self, key: str) -> int:
        return self.ttl_ms.get(key, -2)

    async def set(self, key: str, value: str, px: int) -> bool:
        self.ttl_ms[key] = px
        return True


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeRedis]:
    fake = _FakeRedis()
    monkeypatch.setattr(dial_lines, "get_engine", lambda: SimpleNamespace(name="thinnest"))
    monkeypatch.setattr(dial_lines, "get_redis", lambda: fake)
    monkeypatch.setenv("THINNEST_MAX_CONCURRENT_CALLS", "5")
    get_settings.cache_clear()
    yield fake
    get_settings.cache_clear()


#: Two clients, each dialling from its own number in its own workspace.
CLIENT_A = DialOrigin(workspace="org_a", number_key="number-a")
CLIENT_A_OTHER_NUMBER = DialOrigin(workspace="org_a", number_key="number-a2")
CLIENT_B = DialOrigin(workspace="org_b", number_key="number-b")


async def test_one_numbers_daily_cap_does_not_hold_another_clients_dial(
    redis: _FakeRedis,
) -> None:
    taken = await dial_lines.start_dial_backoff(None, scope=ThrottleScope.NUMBER, origin=CLIENT_A)
    assert taken == dial_lines.ENGINE_BACKOFF_MAX_S
    held = await dial_lines.dial_backoff_refusal(CLIENT_A)
    assert held is not None and held.code == NUMBER_DAILY_LIMIT_CODE
    assert await dial_lines.dial_backoff_refusal(CLIENT_B) is None
    # Nor the same client's other number, nor the campaign tick's account-wide budget.
    assert await dial_lines.dial_backoff_refusal(CLIENT_A_OTHER_NUMBER) is None
    assert await dial_lines.dial_backoff_remaining_s() == 0.0
    # No key names a phone number: only our ids.
    assert all("+91" not in key for key in redis.ttl_ms)


async def test_a_workspace_limit_holds_only_that_workspace(redis: _FakeRedis) -> None:
    await dial_lines.start_dial_backoff(120, scope=ThrottleScope.WORKSPACE, origin=CLIENT_A)
    for origin in (CLIENT_A, CLIENT_A_OTHER_NUMBER):
        held = await dial_lines.dial_backoff_refusal(origin)
        assert held is not None and held.code == "engine_rate_limited"
        assert await dial_lines.dial_backoff_remaining_s(origin) == 120.0
    assert await dial_lines.dial_backoff_refusal(CLIENT_B) is None
    assert await dial_lines.dial_backoff_remaining_s() == 0.0


async def test_the_developer_workspace_is_a_workspace_of_its_own(redis: _FakeRedis) -> None:
    ours = DialOrigin(workspace=None, number_key=dial_lines.TRIAL_LINE_KEY)
    await dial_lines.start_dial_backoff(None, scope=ThrottleScope.WORKSPACE, origin=ours)
    assert await dial_lines.dial_backoff_refusal(ours) is not None
    assert await dial_lines.dial_backoff_refusal(CLIENT_A) is None


async def test_an_account_limit_still_holds_every_dial(redis: _FakeRedis) -> None:
    await dial_lines.start_dial_backoff(None, origin=CLIENT_A)
    for origin in (CLIENT_A, CLIENT_A_OTHER_NUMBER, CLIENT_B):
        held = await dial_lines.dial_backoff_refusal(origin)
        assert held is not None and held.code == "engine_rate_limited"
    assert await dial_lines.dial_backoff_remaining_s() == dial_lines.ENGINE_BACKOFF_DEFAULT_S


async def test_a_number_cap_on_a_dial_that_named_no_number_holds_nothing(
    redis: _FakeRedis,
) -> None:
    vendor_chose = DialOrigin(workspace="org_a", number_key=None)
    taken = await dial_lines.start_dial_backoff(
        None, scope=ThrottleScope.NUMBER, origin=vendor_chose
    )
    assert taken == 0.0 and redis.ttl_ms == {}


async def _refused(body: dict[str, Any], headers: dict[str, str] | None = None) -> ProblemError:
    answer = httpx.Response(429, headers=headers or {"Retry-After": "60"}, json=body)
    async with httpx.AsyncClient(
        base_url="https://vendor.test", transport=httpx.MockTransport(lambda _: answer)
    ) as client:
        with pytest.raises(ProblemError) as raised:
            await vendor_http.vendor_request(
                client, "POST", "/calls", engine="thinnest", route="/calls", json={}
            )
    return raised.value


@pytest.mark.parametrize(
    ("code", "scope"),
    [
        ("rate_limit_resources", ThrottleScope.WORKSPACE),
        ("rate_limit_family", ThrottleScope.ACCOUNT),
        ("rate_limit_calls", ThrottleScope.ACCOUNT),
        ("rate_limited", ThrottleScope.ACCOUNT),
    ],
)
async def test_the_refusal_carries_the_scope_the_vendor_code_names(
    code: str, scope: ThrottleScope
) -> None:
    refused = await _refused({"error": "Reworded in any release.", "code": code})
    assert isinstance(refused, EngineRateLimitedError)
    assert refused.scope is scope and refused.retry_after_s == 60.0


async def test_a_429_with_no_code_is_held_account_wide() -> None:
    refused = await _refused({"error": "slow down"})
    assert isinstance(refused, EngineRateLimitedError)
    assert refused.scope is ThrottleScope.ACCOUNT


async def test_a_numbers_daily_cap_is_scoped_to_the_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_alarm(**_: str) -> None:
        return None

    monkeypatch.setattr(vendor_http, "_alert_number_daily_limit", _no_alarm)
    refused = await _refused(
        {"error": "x", "code": "number_daily_limit", "limit": {"name": "number_daily", "max": 200}},
        headers={"Retry-After": "3600"},
    )
    assert isinstance(refused, EngineNumberDailyLimitError)
    assert refused.code == NUMBER_DAILY_LIMIT_CODE
    assert refused.scope is ThrottleScope.NUMBER and refused.retry_after_s == 3600.0
