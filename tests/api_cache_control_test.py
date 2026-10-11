"""No shared or browser cache keeps an API answer unless the route chose to allow it."""

from __future__ import annotations

from apps.api.main import app
from httpx import ASGITransport, AsyncClient


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def test_an_answer_with_no_caching_of_its_own_is_no_store() -> None:
    async with _client() as http:
        for path in ("/healthz", "/v1/me", "/v1/no-such-route"):
            response = await http.get(path)
            assert response.headers.get("cache-control") == "no-store", path


async def test_a_route_that_chose_its_caching_keeps_it() -> None:
    async with _client() as http:
        response = await http.get("/v1/public/rate-card")
    if response.status_code == 200:
        assert response.headers["cache-control"].startswith("public")
