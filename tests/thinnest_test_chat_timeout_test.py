"""A test-chat reply may take longer than an ordinary ThinnestAI request (production, 20 Oct
2026: a reply on our Gemini key landed just after the 10 s ceiling and the whole test run
failed `engine_unreachable`), and when the platform does not answer, the log names the route
and the kind of failure."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.thinnest import BASE_URL, TEST_CHAT_TIMEOUT, ThinnestEngine
from apps.api.engine.vendor_http import REQUEST_TIMEOUT_S


def _engine(handler: Any) -> ThinnestEngine:
    return ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )


async def test_a_test_chat_reply_is_given_longer_than_an_ordinary_request() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.extensions["timeout"])
        return httpx.Response(200, json={"session": "s1", "reply": "ok", "tools": []})

    turn = await _engine(handler).test_chat("ag_9", "hello")
    assert turn.reply == "ok"
    assert seen["read"] == TEST_CHAT_TIMEOUT.read == 30.0
    assert seen["read"] > REQUEST_TIMEOUT_S
    assert seen["connect"] == REQUEST_TIMEOUT_S


async def test_an_unanswered_request_logs_its_route_and_the_kind_of_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with caplog.at_level(logging.WARNING), pytest.raises(ProblemError) as caught:
        await _engine(handler).test_chat("ag_9", "hello")
    assert caught.value.code == "engine_unreachable"
    record = next(r for r in caplog.records if r.getMessage() == "engine_unreachable")
    assert record.__dict__["route"] == "/agents/{ref}/test-chat"
    assert record.__dict__["error"] == "ReadTimeout"
    assert "ag_9" not in str(record.__dict__)
