"""`POST /v1/ops/carrier/probe`: the env-only carrier pair, checked as this process holds it.

The Vobiz pair can never be installed from the console (`ENV_ONLY_REASONS`), so the
candidate-shaped `POST /v1/ops/secrets/{key}/test` had nothing to offer an operator who
had just edited `.env` and redeployed. This route takes no input, asks the configured
carrier one read-only question, and keeps the same three-way distinction the candidate
probe does: refused, not checked, accepted.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from apps.api.core.settings import get_settings
from apps.api.engine.vobiz import VobizCarrier
from apps.api.main import app
from apps.api.ops import secret_probes, secret_routes
from apps.api.ops.secret_probes import ProbeResult
from httpx import ASGITransport, AsyncClient
from tests.admin_security_test import _make_admin

BASE = "https://api.vobiz.ai/api/v1"
URL = "/v1/ops/carrier/probe"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


@pytest.fixture
def _vobiz_pair(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CARRIER", "vobiz")
    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_PROBE")
    monkeypatch.setenv("VOBIZ_AUTH_TOKEN", "probe-token")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _answering(monkeypatch: pytest.MonkeyPatch, status: int) -> list[httpx.Request]:
    """Every carrier the probe builds answers `status` to whatever it is asked."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={"auth_id": "MA_PROBE"})

    def build(cfg: Any, name: Any = None) -> VobizCarrier:
        return VobizCarrier(
            auth_id=cfg.vobiz_auth_id,
            auth_token=cfg.vobiz_auth_token,
            base_url=BASE,
            client=httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(handler)),
        )

    monkeypatch.setattr(secret_probes, "build_carrier", build)
    return seen


@pytest.mark.usefixtures("_vobiz_pair")
@pytest.mark.parametrize(
    ("status", "outcome"), [(200, "accepted"), (401, "rejected"), (500, "unreachable")]
)
async def test_the_configured_pair_is_asked_once_and_read_only(
    monkeypatch: pytest.MonkeyPatch, status: int, outcome: str
) -> None:
    seen = _answering(monkeypatch, status)
    carrier, result = await secret_probes.probe_configured_carrier()
    assert carrier == "vobiz"
    assert result.outcome == outcome
    assert result.verified is False
    assert [(r.method, r.url.path) for r in seen] == [("GET", "/api/v1/auth/me")]
    assert seen[0].headers["X-Auth-ID"] == "MA_PROBE"


async def test_a_deployment_without_the_pair_is_not_checked_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "Not checked" must never render as "refused": the operator's next step is the
    environment, not the vendor's dashboard."""
    monkeypatch.setenv("CARRIER", "vobiz")
    monkeypatch.delenv("VOBIZ_AUTH_ID", raising=False)
    monkeypatch.delenv("VOBIZ_AUTH_TOKEN", raising=False)
    get_settings.cache_clear()
    try:
        carrier, result = await secret_probes.probe_configured_carrier()
    finally:
        get_settings.cache_clear()
    assert carrier == "vobiz"
    assert result.outcome == "unreachable"
    assert result.detail.startswith("Nothing was checked.")


@pytest.mark.usefixtures("_vobiz_pair")
async def test_the_route_answers_audits_and_echoes_no_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _answering(monkeypatch, 200)
    recorded: list[dict[str, Any]] = []
    real = secret_routes.write_audit

    async def spy(session: Any, **kwargs: Any) -> None:
        recorded.append(kwargs)
        await real(session, **kwargs)

    monkeypatch.setattr(secret_routes, "write_audit", spy)
    token = await _make_admin()
    async with _client() as http:
        response = await http.post(URL, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "carrier": "vobiz",
        "outcome": "accepted",
        "detail": body["detail"],
        "verified": False,
    }
    assert "probe-token" not in response.text
    assert [(r["action"], r["object_id"], r["summary"]) for r in recorded] == [
        ("platform.carrier_probed", "vobiz", {"carrier": "vobiz", "outcome": "accepted"})
    ]


async def test_the_route_refuses_a_caller_without_a_session() -> None:
    async with _client() as http:
        response = await http.post(URL)
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_the_route_reports_an_unchecked_pair_as_a_200_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verdict is the payload: a refusal or an outage at the carrier is an answer to
    the operator's question, not a failure of this route."""

    async def unchecked() -> tuple[str, ProbeResult]:
        return "vobiz", ProbeResult(
            outcome="unreachable", status=None, detail="d", verified=False, source=None
        )

    monkeypatch.setattr(secret_routes, "probe_configured_carrier", unchecked)
    token = await _make_admin()
    async with _client() as http:
        response = await http.post(URL, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "unreachable"
