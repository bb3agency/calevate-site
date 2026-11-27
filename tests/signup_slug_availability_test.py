"""The signup form asks whether a web address is free as it is typed (W1.8), so a taken one is
said, with a free one like it, before the person presses Create.

The answer is taken or free and nothing about the holder; only a signed-in person with no
workspace yet may ask, and the address travels in the body, never the URL.
"""

from __future__ import annotations

import uuid

from apps.api.admin import service as admin_service
from tests.self_serve_test import _client, _headers, _signed_up_user

PATH = "/v1/auth/signup/slug-availability"


async def test_a_free_address_is_free() -> None:
    token, _ = await _signed_up_user()
    async with _client() as http:
        answer = await http.post(
            PATH, headers=_headers(token), json={"slug": f"free-{uuid.uuid4().hex[:8]}"}
        )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["available"] is True and body["reason"] is None and body["suggestion"] is None


async def test_a_taken_address_says_so_and_offers_a_free_one_like_it() -> None:
    slug = f"rytu-{uuid.uuid4().hex[:8]}"
    await admin_service.create_organization(
        name="Rytu Khata",
        slug=slug,
        vertical_template="custom",
        billing_email=None,
        created_by=None,
    )
    token, _ = await _signed_up_user()
    async with _client() as http:
        answer = await http.post(PATH, headers=_headers(token), json={"slug": slug})
    body = answer.json()
    assert answer.status_code == 200, answer.text
    assert (body["available"], body["reason"]) == (False, "taken")
    assert body["suggestion"] == f"{slug}-2"
    assert body["message"] == "Taken. Choose another web address."
    # Nothing about who holds it.
    assert set(body) == {"slug", "available", "reason", "message", "suggestion"}


async def test_a_reserved_or_malformed_address_is_refused_with_its_reason() -> None:
    token, _ = await _signed_up_user()
    async with _client() as http:
        reserved = await http.post(PATH, headers=_headers(token), json={"slug": "dashboard"})
        erased = await http.post(PATH, headers=_headers(token), json={"slug": "erased-abc123"})
        malformed = await http.post(PATH, headers=_headers(token), json={"slug": "No Caps"})
    assert reserved.json()["reason"] == "reserved"
    assert reserved.json()["message"] == "Reserved. Choose another web address."
    assert erased.json()["reason"] == "reserved"
    assert malformed.json()["reason"] == "invalid" and malformed.json()["suggestion"] is None


async def test_only_a_signed_in_person_may_ask() -> None:
    async with _client() as http:
        stranger = await http.post(PATH, json={"slug": "anything"})
    assert stranger.status_code == 401, stranger.text
