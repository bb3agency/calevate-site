"""`engine_number_daily_limit` is raised, once per calling number per window, and names no
number (D-690; `engine/vendor_http._alert_number_daily_limit`)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine import vendor_http

_BODY = {"error": "x", "code": "number_daily_limit", "limit": {"name": "number_daily", "max": 200}}


def _number() -> str:
    # Fresh per run: the throttle is a Redis key that outlives the test.
    return f"+9140{uuid.uuid4().int % 10**8:08d}"


async def _refused_dial(number: str | None) -> ProblemError:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json=_BODY)

    body: dict[str, Any] = {"agent": "ag_1", "to": "+919876543210"}
    if number is not None:
        body["from"] = number
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(answer), base_url="https://vendor.test"
    ) as client:
        with pytest.raises(ProblemError) as refused:
            await vendor_http.vendor_request(
                client, "POST", "/calls", engine="thinnest", route="/calls", json=body
            )
    return refused.value


async def test_an_exhausted_number_alarms_once_per_number_and_names_no_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raised: list[tuple[str, str, dict[str, str]]] = []
    monkeypatch.setattr(
        vendor_http,
        "alert",
        lambda stage, code, *, detail=None, **ids: raised.append((stage, code, ids)),
    )
    first, second = _number(), _number()

    for number in (first, first, second):
        refused = await _refused_dial(number)
        assert refused.code == vendor_http.NUMBER_DAILY_LIMIT_CODE

    assert [(stage, code) for stage, code, _ in raised] == [
        ("CORE_LOGIC", "engine_number_daily_limit"),
        ("CORE_LOGIC", "engine_number_daily_limit"),
    ], "one alarm per number, however many dials it refuses"
    refs = [ids["number_ref"] for _, _, ids in raised]
    assert len(set(refs)) == 2
    for _, _, ids in raised:
        assert not any(first[3:] in v or second[3:] in v for v in ids.values())


async def test_the_alarm_is_raised_when_redis_cannot_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raised: list[str] = []
    monkeypatch.setattr(vendor_http, "alert", lambda stage, code, **kw: raised.append(code))

    class _Down:
        async def set(self, *args: Any, **kwargs: Any) -> bool:
            raise ConnectionError("redis down")

    monkeypatch.setattr(vendor_http, "get_redis", lambda: _Down())
    await _refused_dial(_number())
    await _refused_dial(None)
    assert raised == ["engine_number_daily_limit", "engine_number_daily_limit"]
