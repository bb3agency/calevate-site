"""What a response the STACK produces looks like, as opposed to one a handler produced.

Three of them exist — the body limit's 413, the rate limiter's 429 and the load-shed
guard's 503 — and every one is composed by a middleware that answers instead of calling
through. They are also the three responses a support conversation is most likely to be
about: "it says too many requests", "it says temporarily unavailable".

BACKEND-PATTERNS §3 says of the correlation id: "accept `X-Correlation-Id` else generate;
echo on response". §2 step 5 puts observability LAST before routes, so
`CorrelationIdMiddleware` sat inside all three of them and none of the three could carry
an id — not even one the caller had sent. No `X-Correlation-Id` header, `trace_id: null`
in the problem body, and no `request` log line at all, so the `rate_limited` warning had
nothing an operator could join a complaint to. `install_middleware` now puts the
correlation layer outermost and records the departure; this file is what keeps it there.

Asserted through the LIVE app for each refusal separately, because "the middleware stack"
is not one thing: each of the three composes its own response, and a fix that reached two
of them would look identical from the outside of the third.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from apps.api.core import loadshed, ratelimit
from apps.api.core.loadshed import PlatformStatus
from apps.api.core.middleware import MAX_BODY_BYTES
from apps.api.core.ratelimit import LimitProfile
from apps.api.main import app
from httpx import ASGITransport, AsyncClient, Response

CALLER_ID = "cid-under-test"


def _client() -> AsyncClient:
    """A call-unique address, so the limiter case cannot inherit another run's count."""
    peer = f"2001:db8:{uuid.uuid4().hex[:4]}:{uuid.uuid4().hex[:4]}::1"
    return AsyncClient(
        transport=ASGITransport(app=app, client=(peer, 12345)), base_url="http://api"
    )


@pytest.fixture
def one_request_per_hour(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`client_api` at one request an hour, so the second is a 429 and no window boundary
    can fall between them (the reason `rate_limit_behaviour_test` widens rather than
    narrows its window)."""
    monkeypatch.setitem(
        ratelimit.PROFILES,
        "client_api",
        LimitProfile("client_api", per_client=1, per_tenant=2, window_s=3600),
    )
    yield


def _assert_traceable(response: Response, expected_status: int) -> None:
    """One refusal, fully attributable: the caller's id on the wire, in the body, and the
    security headers still present."""
    assert response.status_code == expected_status, response.text
    assert response.headers.get("X-Correlation-Id") == CALLER_ID, (
        "a response produced by the middleware stack dropped the caller's correlation id"
    )
    assert response.json().get("trace_id") == CALLER_ID, (
        "the problem body's trace_id is what an operator greps for"
    )
    # `SecurityHeadersMiddleware` gave up being outermost, not being universal.
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


async def test_the_body_limits_refusal_is_traceable() -> None:
    async with _client() as http:
        response = await http.post(
            "/v1/agents",
            headers={"X-Correlation-Id": CALLER_ID},
            content=b"x" * (MAX_BODY_BYTES + 1),
        )
    _assert_traceable(response, 413)


async def test_the_rate_limiters_refusal_is_traceable(one_request_per_hour: None) -> None:
    async with _client() as http:
        await http.get("/v1/agents", headers={"X-Correlation-Id": CALLER_ID})
        response = await http.get("/v1/agents", headers={"X-Correlation-Id": CALLER_ID})
    _assert_traceable(response, 429)


async def test_the_load_shed_refusal_is_traceable(monkeypatch: pytest.MonkeyPatch) -> None:
    """`maintenance` sheds reads too, so a GET on a non-exempt path is the cheapest
    reachable 503. Patched at `get_platform_status` rather than by writing
    `platform_state`, so nothing else in the shared database is put into an incident."""

    async def _halted(*, force_refresh: bool = False) -> PlatformStatus:
        return PlatformStatus(mode="maintenance", outbound_halted=False)

    monkeypatch.setattr(loadshed, "get_platform_status", _halted)
    monkeypatch.setattr("apps.api.core.middleware.get_platform_status", _halted)
    async with _client() as http:
        response = await http.get("/v1/agents", headers={"X-Correlation-Id": CALLER_ID})
    _assert_traceable(response, 503)


async def test_an_absent_correlation_id_is_generated_rather_than_omitted(
    one_request_per_hour: None,
) -> None:
    """The other half of §3. A caller that sends nothing still gets an id back, or there
    is nothing for them to quote at us."""
    async with _client() as http:
        await http.get("/v1/agents")
        response = await http.get("/v1/agents")
    assert response.status_code == 429, response.text
    generated = response.headers.get("X-Correlation-Id")
    assert generated and len(generated) >= 16, "a refusal was returned with no id at all"
    assert response.json().get("trace_id") == generated
