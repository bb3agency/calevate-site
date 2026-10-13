"""The account's simultaneous-call limit, held at the dial gate (D-663).

The account's lines, inbound and outbound together, less a reserve kept for callers, are
what outbound dials may hold. These tests pin the pool arithmetic (three lines leave two
for outbound) and the refusal a dial gets when the vendor itself says the lines are full.
The engine-ceiling count is in `tests/thinnest_call_lifecycle_test.py`.

Run: uv run python -m pytest -q tests/carrier_line_cap_test.py
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from apps.api.agents.service import dial_was_not_placed
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine import vendor_http
from apps.api.engine.dial_lines import (
    LINES_BUSY_RULE,
    inbound_line_reserve,
    lines_busy,
    outbound_line_pool,
)
from apps.api.engine.vendor_http import is_line_limit, vendor_request

pytestmark = pytest.mark.anyio


@pytest.fixture
def lines(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CARRIER_CONCURRENCY", "3")
    monkeypatch.delenv("INBOUND_RESERVED_LINES", raising=False)
    monkeypatch.setenv("INBOUND_RESERVE_RATIO", "0.3")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- the arithmetic ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("concurrency", "reserved_lines", "reserve"),
    [
        # Unset: the automatic share, never rounded up by a float.
        (3, None, 1),
        (5, None, 2),
        (10, None, 3),
        (1, None, 1),
        # A count: taken as typed, never zero, never more than the account has.
        (5, 2, 2),
        (5, 1, 1),
        (3, 9, 3),
    ],
)
def test_the_inbound_reserve_is_never_zero_and_never_rounds_up_a_float(
    concurrency: int, reserved_lines: int | None, reserve: int
) -> None:
    assert inbound_line_reserve(concurrency, reserved_lines, 0.3) == reserve


def test_a_typed_count_sets_the_outbound_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARRIER_CONCURRENCY", "5")
    monkeypatch.setenv("INBOUND_RESERVED_LINES", "1")
    get_settings.cache_clear()
    try:
        assert outbound_line_pool() == 4
    finally:
        get_settings.cache_clear()


def test_three_lines_leave_two_for_outbound(lines: None) -> None:
    assert outbound_line_pool() == 2


def test_a_one_line_account_has_no_outbound_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARRIER_CONCURRENCY", "1")
    get_settings.cache_clear()
    try:
        assert outbound_line_pool() == 0
    finally:
        get_settings.cache_clear()


def test_a_busy_refusal_proves_no_line_was_seized() -> None:
    refusal = lines_busy()
    assert refusal.kind == "transient"
    assert dial_was_not_placed(refusal) is True
    assert refusal.code == LINES_BUSY_RULE


# --- the vendor's own 429 ---------------------------------------------------------


def _throttled(limit_type: str | None) -> httpx.Response:
    details: dict[str, Any] = {"retryAfter": 0}
    if limit_type is not None:
        details["limitType"] = limit_type
    return httpx.Response(
        429, json={"status": "error", "error": {"code": "RATE_LIMIT_EXCEEDED", "details": details}}
    )


def test_only_the_per_second_limit_is_not_a_line_limit() -> None:
    assert is_line_limit("cps") is False
    assert is_line_limit(None) is False
    assert is_line_limit("concurrency") is True
    assert is_line_limit("concurrent_calls") is True


async def test_a_429_over_the_line_limit_is_refused_at_once_as_lines_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return _throttled("concurrency")

    async def _no_sleep(_: float) -> None:
        raise AssertionError("a line limit must not be waited out inside the ladder")

    monkeypatch.setattr(vendor_http.asyncio, "sleep", _no_sleep)
    async with httpx.AsyncClient(
        base_url="https://engine.test", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ProblemError) as raised:
            await vendor_request(
                client, "POST", "/Call/", engine="thinnest", route="/Call/", json={}
            )
    assert raised.value.code == LINES_BUSY_RULE
    assert dial_was_not_placed(raised.value) is True
    assert len(sent) == 1


async def test_a_429_over_the_per_second_limit_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = [_throttled("cps"), httpx.Response(200, json={"request_uuid": "vz-1"})]

    async def _instant(_: float) -> None:
        return None

    monkeypatch.setattr(vendor_http.asyncio, "sleep", _instant)
    async with httpx.AsyncClient(
        base_url="https://engine.test", transport=httpx.MockTransport(lambda _: answers.pop(0))
    ) as client:
        body = await vendor_request(
            client, "POST", "/Call/", engine="thinnest", route="/Call/", json={}
        )
    assert body == {"request_uuid": "vz-1"}
