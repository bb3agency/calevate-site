"""Outbound fetches end on OUR clock and on OUR terms, whatever the far end sends.

httpx's timeouts are per operation, so a sender that drips bytes never trips one; and a
redirect whose Location will not parse raises something other than `httpx.HTTPError`.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from apps.api.integrations import egress_guard
from apps.workers import kb_ingest, storage


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _public(host: str, port: int) -> tuple[str, ...]:
        return ("142.250.183.10",)

    monkeypatch.setattr(egress_guard, "resolve_addresses", _public)


async def test_a_voice_preview_that_never_finishes_is_unusable_not_a_hang(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _forever(url: str, **_: object) -> bytes:
        await asyncio.sleep(60)
        return b""

    monkeypatch.setattr(storage, "_fetch_recording", _forever)
    monkeypatch.setattr(storage, "RECORDING_FETCH_DEADLINE_S", 0.2)
    with pytest.raises(storage.RecordingUnavailableError):
        await asyncio.wait_for(storage.fetch_voice_preview("https://cdn.example/p.mp3"), 5)


async def test_an_unparsable_redirect_is_an_unreadable_page_not_a_crash(
    public_dns: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://[::1"})

    monkeypatch.setattr(
        kb_ingest,
        "link_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert await kb_ingest._fetch_page("https://shop.example/about") is None
