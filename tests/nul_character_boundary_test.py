"""A NUL character in a request is a 422 at the boundary, never a 500 from the database.

PostgreSQL stores neither a NUL in `text` nor `\\u0000` in `jsonb`, and Pydantic's `str`
admits one, so these routes answered a signed-in caller's NUL with a 500 and an alarm.
"""

from __future__ import annotations

import json
import uuid

import pytest
from apps.api.core.middleware import _JSON_NUL_ESCAPE, NulCharacterMiddleware, _is_json_body
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from starlette.types import Message, Receive, Scope, Send
from tests.api_security_test import _make_tenant

pytestmark = [pytest.mark.rls]


def _client() -> AsyncClient:
    peer = f"2001:db8:{uuid.uuid4().hex[:4]}::1"
    return AsyncClient(transport=ASGITransport(app=app, client=(peer, 1)), base_url="http://api")


def _nul_refusal(response_text: str) -> bool:
    return json.loads(response_text)["type"].endswith("/nul_character")


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/v1/leads/views", {"name": "a\u0000b"}),
        ("PATCH", f"/v1/leads/views/{uuid.uuid4()}", {"name": "a\u0000b"}),
    ],
)
async def test_a_nul_in_a_json_body_is_refused_before_the_route(
    method: str, path: str, body: dict[str, object]
) -> None:
    _, slug, token = await _make_tenant("owner")
    async with _client() as http:
        response = await http.request(
            method,
            path,
            content=json.dumps(body),
            headers={
                "Authorization": f"Bearer {token}",
                "X-Org-Slug": slug,
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 422, response.text
    assert _nul_refusal(response.text), response.text


async def test_a_nul_in_a_path_or_query_parameter_is_refused() -> None:
    _, slug, token = await _make_tenant("owner")
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with _client() as http:
        in_path = await http.get("/v1/billing/wallet/receipts/a%00b", headers=headers)
        in_query = await http.get("/v1/leads?search=a%00b", headers=headers)
    for response in (in_path, in_query):
        assert response.status_code == 422, response.text
        assert _nul_refusal(response.text), response.text


async def test_an_ordinary_body_still_reaches_the_route() -> None:
    """The control: the buffered body is replayed whole, so the same request without the
    NUL is created — and an escaped backslash before `u0000` is ordinary text."""
    _, slug, token = await _make_tenant("owner")
    async with _client() as http:
        response = await http.post(
            "/v1/leads/views",
            content=json.dumps({"name": "back\\u0000slash"}),
            headers={
                "Authorization": f"Bearer {token}",
                "X-Org-Slug": slug,
                "Content-Type": "application/json",
            },
        )
    assert response.status_code in (200, 201), response.text
    assert response.json()["name"] == "back\\u0000slash"


@pytest.mark.parametrize(
    ("raw", "is_nul"),
    [
        (rb'"\u0000"', True),
        (rb'"\\u0000"', False),
        (rb'"\\\u0000"', True),
        (rb'"\\\\u0000"', False),
        (rb'"x\u00001"', True),
        (rb'"\u00001"', True),
        (rb'"\u0001"', False),
    ],
)
def test_only_an_unescaped_backslash_opens_a_nul_escape(raw: bytes, is_nul: bool) -> None:
    assert bool(_JSON_NUL_ESCAPE.search(raw)) is is_nul
    assert ("\x00" in json.loads(raw)) is is_nul


@pytest.mark.parametrize(
    ("content_type", "decoded_as_json"),
    [
        (None, True),
        ("application/json", True),
        ("Application/JSON; charset=utf-8", True),
        ("application/merge-patch+json", True),
        ("multipart/form-data; boundary=x", False),
        ("application/octet-stream", False),
        ("text/plain", False),
    ],
)
def test_the_bodies_checked_are_the_bodies_fastapi_decodes_as_json(
    content_type: str | None, decoded_as_json: bool
) -> None:
    assert _is_json_body(content_type) is decoded_as_json


async def test_vendor_channels_are_left_to_their_own_verification() -> None:
    """A signed webhook's NUL is the sender's to retry, not ours to refuse: the request
    reaches the route, whose own signature check answers."""
    async with _client() as http:
        response = await http.post(
            "/hooks/v1/meta/whatsapp",
            content=json.dumps({"object": "a\u0000b"}),
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code != 422 or not _nul_refusal(response.text), response.text


async def test_a_scope_that_is_not_http_passes_untouched() -> None:
    seen: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(str(scope["type"]))

    async def never() -> Message:
        raise AssertionError("a non-HTTP scope must not be read")

    async def drop(message: Message) -> None:
        raise AssertionError("a non-HTTP scope must not be answered here")

    await NulCharacterMiddleware(inner)({"type": "lifespan"}, never, drop)
    assert seen == ["lifespan"]
