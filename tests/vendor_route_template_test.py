"""The vendor ladder logs a route TEMPLATE, never the concrete path (hard rule 6).

A vendor path can carry a phone number or an account id. The formatter would redact a
number, but `caplog.records`, a non-JSON handler and Sentry's breadcrumbs all read the raw
record, so the path must never be on it.
"""

from __future__ import annotations

import logging

import httpx
import pytest
from apps.api.engine import vendor_http
from apps.api.engine.vendor_http import vendor_request

pytestmark = pytest.mark.anyio

BASE = "https://vendor.test/api/v1"
NUMBER = "+919876543210"


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _instant(_: float) -> None:
        return None

    monkeypatch.setattr(vendor_http.asyncio, "sleep", _instant)


def _blob(records: list[logging.LogRecord]) -> str:
    """Every attribute of every record OUR code wrote. httpx's own request line is held at
    WARNING by `core.logging` in every deployable, and is not what this file is about."""
    return " ".join(f"{record.__dict__}" for record in records if record.name.startswith("apps."))


def _routes(records: list[logging.LogRecord]) -> list[str]:
    return [record.route for record in records if hasattr(record, "route")]


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
