"""The link re-scrape reads a stranger's page. What it may spend on one is bounded.

A knowledge LINK is the one input on this platform whose bytes come from an address the
CLIENT chose and a THIRD PARTY serves. `sweep_kb_uploads` re-reads it on a schedule to
notice a material change, so the page's author — who is not our client and has agreed to
nothing — decides how much of a worker's memory and how much of its slot one read costs.

`MAX_LINK_BYTES` says 2 MB and its comment cites `storage.MAX_RECORDING_BYTES` as the
precedent. The implementation did `response.content[:MAX_LINK_BYTES]`, which is a slice
and not a limit: `.content` reads the whole body first, so the memory is spent before the
number is known. These tests hold the constant to what its own comment claims.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from apps.workers import kb_ingest


def _serving(monkeypatch: pytest.MonkeyPatch, handler: object) -> None:
    """Substitute the module's own client seam, and nothing else.

    `link_http_client` is the one place the transport is chosen, so this leaves the guard,
    the hop loop, the header check and the streaming ceiling exactly as they ship —
    `follow_redirects=False` included, because a substitute that quietly followed them
    would make the redirect test vacuous.
    """
    monkeypatch.setattr(
        kb_ingest,
        "link_http_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
            follow_redirects=False,
        ),
    )


async def test_a_page_that_lies_about_its_length_is_still_refused_at_the_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE REGRESSION. No `Content-Length`, a body over the ceiling, streamed in pieces.

    A chunked response declares no length, so the header check cannot be what enforces
    this; the running total has to. The stream is deliberately made of many small parts —
    a sender who wanted the memory would not hand it over in one measurable lump.
    """
    oversize = kb_ingest.MAX_LINK_BYTES + 1

    def handler(request: httpx.Request) -> httpx.Response:
        async def parts() -> AsyncIterator[bytes]:
            sent = 0
            while sent < oversize:
                block = b"a" * min(64 * 1024, oversize - sent)
                sent += len(block)
                yield block

        # No content-length: httpx streams an iterator as chunked.
        return httpx.Response(200, content=parts())

    _serving(monkeypatch, handler)
    assert await kb_ingest.fetch_page("https://menu.example/prices") is None


async def test_an_honest_oversized_page_costs_no_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A declared length over the ceiling is refused from the header, before the body."""
    read = {"chunks": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        async def parts() -> AsyncIterator[bytes]:
            read["chunks"] += 1
            yield b"x" * (kb_ingest.MAX_LINK_BYTES + 1)

        return httpx.Response(
            200,
            headers={"content-length": str(kb_ingest.MAX_LINK_BYTES + 1)},
            content=parts(),
        )

    _serving(monkeypatch, handler)
    assert await kb_ingest.fetch_page("https://menu.example/prices") is None
    assert read["chunks"] == 0, "the body was read even though the header already refused it"


async def test_a_page_within_the_ceiling_is_returned_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound must not have eaten the feature: an ordinary page still comes back, and
    comes back COMPLETE — a truncated read would make `page_digest` a change signal that
    lies in both directions."""
    body = b"<html><body>Idli 40, Dosa 60</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    _serving(monkeypatch, handler)
    assert await kb_ingest.fetch_page("https://menu.example/prices") == body


async def test_a_redirect_inward_is_refused_at_the_hop_not_followed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every hop is vetted, so a public page redirecting to the metadata service is
    refused rather than fetched — `follow_redirects=False` plus the guard on each hop."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    _serving(monkeypatch, handler)
    assert await kb_ingest.fetch_page("https://menu.example/prices") is None
    assert seen == ["https://menu.example/prices"], "the inward hop was requested"


async def test_the_whole_chain_sits_under_one_deadline() -> None:
    """`LINK_FETCH_DEADLINE_S` covers hops, lookups and bytes together. httpx's own
    timeout is per OPERATION, so a slow drip trips nothing without this."""
    assert kb_ingest.LINK_FETCH_DEADLINE_S >= kb_ingest.LINK_FETCH_TIMEOUT_S
    assert kb_ingest.LINK_FETCH_DEADLINE_S == kb_ingest.LINK_FETCH_TIMEOUT_S * (
        kb_ingest.LINK_REDIRECT_LIMIT + 1
    )
