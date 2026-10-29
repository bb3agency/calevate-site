"""A vendor answer is read up to a cap, decoded once, and refused past the cap.

OWASP API Security Top 10 2023, API10 (Unsafe Consumption of APIs): what a third party
sends back is bounded before we hold it. `vendor_http` used to buffer whatever arrived.
"""

from __future__ import annotations

import gzip
import json

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.vendor_http import VENDOR_RESPONSE_MAX_BYTES, vendor_request

BASE = "https://vendor.example/api/v1"


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url=BASE)


async def test_an_answer_over_the_cap_is_refused_not_parsed() -> None:
    oversized = b'{"data":"' + b"x" * VENDOR_RESPONSE_MAX_BYTES + b'"}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=oversized)

    async with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(ProblemError) as refused:
            await vendor_request(client, "GET", "/calls", engine="thinnest", route="/calls")
    assert refused.value.code == "engine_bad_response"


async def test_a_gzip_answer_is_decoded_once() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
            content=gzip.compress(json.dumps({"id": "call_1"}).encode()),
        )

    async with _client(httpx.MockTransport(handler)) as client:
        answer = await vendor_request(client, "GET", "/calls/1", engine="thinnest", route="/c")
    assert answer == {"id": "call_1"}


async def test_an_oversized_meta_graph_answer_is_a_graph_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.whatsapp import graph

    def handler(request: httpx.Request) -> httpx.Response:
        padding = "x" * graph.GRAPH_MAX_RESPONSE_BYTES
        return httpx.Response(200, json={"verified_name": "Shop", "padding": padding})

    monkeypatch.setattr(
        graph,
        "egress_client",
        lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw),
    )
    with pytest.raises(graph.GraphError):
        await graph.phone_info(phone_number_id="1234567890", token="t")
