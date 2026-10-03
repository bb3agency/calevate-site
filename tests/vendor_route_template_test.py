"""The vendor ladder logs a route TEMPLATE, never the concrete path (hard rule 6).

The carrier's number-binding routes carry the phone number in the path
(`/Account/{auth_id}/numbers/{number}/application`), and every account route carries the
auth id. The formatter would redact a number, but `caplog.records`, a non-JSON handler and
Sentry's breadcrumbs all read the raw record, so the path must never be on it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx
import pytest
from apps.api.engine import vendor_http
from apps.api.engine.vendor_http import EngineRejectedError, vendor_request
from apps.api.engine.vobiz import VobizCarrier

pytestmark = pytest.mark.anyio

AUTH_ID = "MA_TESTACCT"
BASE = "https://api.vobiz.ai/api/v1"
NUMBER = "+919876543210"


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _instant(_: float) -> None:
        return None

    monkeypatch.setattr(vendor_http.asyncio, "sleep", _instant)


def _carrier(handler: Callable[[httpx.Request], httpx.Response]) -> VobizCarrier:
    return VobizCarrier(
        auth_id=AUTH_ID,
        auth_token="tok",
        base_url=BASE,
        client=httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(handler)),
    )


def _blob(records: list[logging.LogRecord]) -> str:
    """Every attribute of every record OUR code wrote. httpx's own request line is held at
    WARNING by `core.logging` in every deployable, and is not what this file is about."""
    return " ".join(f"{record.__dict__}" for record in records if record.name.startswith("apps."))


def _routes(records: list[logging.LogRecord]) -> list[str]:
    return [record.route for record in records if hasattr(record, "route")]


async def test_a_refused_number_binding_logs_the_template_and_not_the_number(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.url.path.endswith("/application"):
            return httpx.Response(400, json={"error": 1, "message": "bad"})
        if request.method == "GET":
            return httpx.Response(200, json={"objects": [{"app_name": "x", "app_id": "a1"}]})
        return httpx.Response(200, json={"app_id": "a1"})

    with caplog.at_level(logging.DEBUG), pytest.raises(EngineRejectedError):
        await _carrier(handler).bind_number(
            NUMBER, answer_url="https://a.test/x", hangup_url="https://a.test/y", label="agent"
        )

    assert sent[-1].url.raw_path.decode().endswith("/numbers/%2B919876543210/application"), (
        "the concrete path must still reach the vendor"
    )
    assert "/Account/{auth_id}/numbers/{number}/application" in _routes(caplog.records)
    blob = _blob(caplog.records)
    assert "9876543210" not in blob
    assert AUTH_ID not in blob


async def test_an_unbind_of_an_absent_number_logs_the_template(
    caplog: pytest.LogCaptureFixture,
) -> None:
    carrier = _carrier(lambda _request: httpx.Response(404))
    with caplog.at_level(logging.DEBUG):
        await carrier.unbind_number(NUMBER)

    assert _routes(caplog.records) == ["/Account/{auth_id}/numbers/{number}/application"]
    assert "9876543210" not in _blob(caplog.records)


async def test_every_ladder_log_line_carries_the_route_it_was_given(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The throttle, redirect, refusal and non-JSON rungs all log `route`, never `path`."""
    answers = [
        httpx.Response(429),
        httpx.Response(302, headers={"location": "https://elsewhere.test"}),
        httpx.Response(500),
        httpx.Response(200, content=b"<html>"),
    ]
    concrete = f"/numbers/{NUMBER}"
    for answer in answers:
        async with httpx.AsyncClient(
            base_url=BASE, transport=httpx.MockTransport(lambda _r, a=answer: a)
        ) as client:
            with caplog.at_level(logging.DEBUG), pytest.raises(Exception):  # noqa: B017
                await vendor_request(client, "GET", concrete, engine="test", route="/numbers/{n}")

    routes = _routes(caplog.records)
    assert routes, "nothing was logged, so the assertion below would be vacuous"
    assert set(routes) == {"/numbers/{n}"}
    assert "9876543210" not in _blob(caplog.records)


def test_the_route_is_a_required_argument() -> None:
    """A new call site cannot fall back to logging its concrete path by omission."""
    import inspect

    parameter = inspect.signature(vendor_request).parameters["route"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty
