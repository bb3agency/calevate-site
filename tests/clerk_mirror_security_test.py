"""Clerk mirror: signature verification and the mirror's effect on auth (D-37).

This endpoint writes to `users`, the table RLS keys its membership lookup off. A
forged event here would be an account-creation primitive, so the signature tests are
the point of the file — the mirroring itself is the easy half.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid

import pytest
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.tenancy.clerk_webhooks import MAX_SKEW_S, verify_svix
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

SECRET = "whsec_" + base64.b64encode(b"calevate-test-signing-key").decode()


def _sign(body: bytes, *, svix_id: str, timestamp: int | None = None) -> dict[str, str]:
    ts = str(timestamp if timestamp is not None else int(time.time()))
    key = base64.b64decode(SECRET.removeprefix("whsec_"))
    signed = f"{svix_id}.{ts}.{body.decode()}".encode()
    signature = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    return {"svix-id": svix_id, "svix-timestamp": ts, "svix-signature": f"v1,{signature}"}


def _user_event(clerk_id: str, email: str) -> bytes:
    return json.dumps(
        {
            "type": "user.created",
            "data": {
                "id": clerk_id,
                "first_name": "Ravi",
                "last_name": "Kumar",
                "primary_email_address_id": "idn_1",
                "email_addresses": [{"id": "idn_1", "email_address": email}],
            },
        }
    ).encode()


def test_a_valid_signature_verifies() -> None:
    body = _user_event("user_x", "x@example.com")
    assert verify_svix(secret=SECRET, headers=_sign(body, svix_id="msg_1"), body=body)


def test_a_tampered_body_fails() -> None:
    """The signature covers the BODY, so editing the email after signing must fail."""
    body = _user_event("user_x", "x@example.com")
    headers = _sign(body, svix_id="msg_1")
    tampered = _user_event("user_x", "attacker@example.com")
    assert not verify_svix(secret=SECRET, headers=headers, body=tampered)


def test_a_replayed_old_request_fails_even_with_a_valid_signature() -> None:
    """A captured request must not be replayable forever."""
    body = _user_event("user_x", "x@example.com")
    stale = _sign(body, svix_id="msg_1", timestamp=int(time.time()) - MAX_SKEW_S - 60)
    assert not verify_svix(secret=SECRET, headers=stale, body=body)


def test_missing_headers_fail_closed() -> None:
    body = _user_event("user_x", "x@example.com")
    assert not verify_svix(secret=SECRET, headers={}, body=body)


#: `svix-timestamp` values a stranger can put on the wire that are not timestamps.
#: The 400-digit one is the whole point of the parametrisation: it parses as an `int`
#: (Python integers are arbitrary precision) and only stops being usable at the moment it
#: meets a float. See the test below.
HOSTILE_TIMESTAMPS = ("9" * 400, "-" + "9" * 400, "1e400", "0x10", " 1755000000 ", "")


@pytest.mark.parametrize("timestamp", HOSTILE_TIMESTAMPS)
def test_a_hostile_timestamp_is_a_refusal_not_an_unhandled_error(timestamp: str) -> None:
    """A header value nobody authenticated must never leave this function by raising.

    THE DEFECT, measured before the fix: `abs(time.time() - sent_at)` coerces `sent_at`
    to a float, and a 400-digit integer cannot be one — `OverflowError: int too large to
    convert to float`. `OverflowError` is not `ValueError`, so the guard above it never
    saw it, and it escaped `clerk_webhook` as an unhandled exception: a 500 plus an
    `internal_error` alert, on an UNAUTHENTICATED route, from one header any stranger can
    set. The module docstring already states the rule for the body ("an unverifiable
    request must come back as a refusal, never as an unhandled exception on an
    unauthenticated route"); the timestamp line was the half that did not follow it.

    The fix is integer arithmetic rather than a bounded parse: Python's ints do not
    overflow, so the comparison is total over every value `int()` accepts, and there is
    no second length rule for a future reader to get wrong.
    """
    body = _user_event("user_x", "x@example.com")
    headers = _sign(body, svix_id="msg_1")
    headers["svix-timestamp"] = timestamp
    assert verify_svix(secret=SECRET, headers=headers, body=body) is False


async def test_a_hostile_timestamp_reaches_the_endpoint_as_a_401(monkeypatch) -> None:
    """The same defect end to end, because the unit above would still pass if the
    exception moved rather than disappeared."""
    settings = get_settings()
    monkeypatch.setattr(settings, "clerk_webhook_secret", SECRET)
    body = _user_event(f"user_{uuid.uuid4().hex[:12]}", "x@example.com")
    headers = _sign(body, svix_id=f"msg_{uuid.uuid4().hex[:10]}")
    headers["svix-timestamp"] = "9" * 400

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.post("/hooks/v1/clerk", content=body, headers=headers)

    assert response.status_code == 401, response.text
    assert not str(response.json()["type"]).endswith("/internal_error"), response.text


async def test_a_late_update_does_not_resurrect_a_deleted_account(monkeypatch) -> None:
    """Svix does not guarantee ORDER, so `user.updated` can land after `user.deleted`.

    `mirror_clerk_user` leaves `deactivated_at` out of its `DO UPDATE` set for exactly
    this reason and says so in a comment; nothing held it to that. The consequence if it
    ever changes is not cosmetic — `resolve_mirrored_user` reads that column on every
    single request, so clearing it restores a revoked account's access to every tenant it
    belonged to, silently, from an event Clerk sent in good faith.

    Both directions are driven: the stale update still refreshes the DISPLAY fields (it
    is not ignored), and the account stays refused at the door.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "clerk_webhook_secret", SECRET)

    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    email = f"{clerk_id}@example.com"
    created = _user_event(clerk_id, email)
    deleted = json.dumps({"type": "user.deleted", "data": {"id": clerk_id}}).encode()
    late = json.dumps(
        {
            "type": "user.updated",
            "data": {
                "id": clerk_id,
                "first_name": "Resurrected",
                "last_name": "Account",
                "primary_email_address_id": "idn_1",
                "email_addresses": [{"id": "idn_1", "email_address": email}],
            },
        }
    ).encode()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        for payload in (created, deleted, late):
            response = await http.post(
                "/hooks/v1/clerk",
                content=payload,
                headers=_sign(payload, svix_id=f"m_{uuid.uuid4().hex[:8]}"),
            )
            assert response.status_code == 202, response.text
        refused = await http.get(
            "/v1/agents", headers={"Authorization": f"Bearer dev:client:{clerk_id}"}
        )

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT deactivated_at, name FROM users WHERE clerk_user_id = :c"),
                {"c": clerk_id},
            )
        ).first()
    assert row is not None
    assert row[0] is not None, "a late user.updated cleared the deletion"
    assert row[1] == "Resurrected Account", "the stale event was ignored entirely, not merged"
    assert refused.status_code == 401, refused.text
    assert "deactivated" in refused.json()["detail"].lower(), refused.text


def test_multiple_signatures_pass_if_any_matches() -> None:
    """Secret rotation sends several signatures in one header."""
    body = _user_event("user_x", "x@example.com")
    headers = _sign(body, svix_id="msg_1")
    headers["svix-signature"] = f"v1,not-the-right-signature {headers['svix-signature']}"
    assert verify_svix(secret=SECRET, headers=headers, body=body)


async def test_an_unsigned_request_is_rejected_by_the_endpoint() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.post("/hooks/v1/clerk", json={"type": "user.created", "data": {}})
    # 401 when a secret is configured, 502 when it is not — both are refusals, and the
    # unconfigured case failing CLOSED is the property that matters.
    assert response.status_code in (401, 502)


async def test_a_signed_event_mirrors_the_user_and_a_repeat_is_deduped(
    monkeypatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "clerk_webhook_secret", SECRET)

    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    email = f"{clerk_id}@example.com"
    body = _user_event(clerk_id, email)
    headers = _sign(body, svix_id=f"msg_{uuid.uuid4().hex[:10]}")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        first = await http.post("/hooks/v1/clerk", content=body, headers=headers)
        second = await http.post("/hooks/v1/clerk", content=body, headers=headers)

    assert first.status_code == 202, first.text
    assert first.json()["status"] == "mirrored"
    # Clerk retries on non-2xx, so an event legitimately arrives more than once.
    assert second.json()["status"] == "duplicate"

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT email, name, deactivated_at FROM users WHERE clerk_user_id = :c"),
                {"c": clerk_id},
            )
        ).first()
    assert row is not None
    assert row[0] == email
    assert row[1] == "Ravi Kumar"
    assert row[2] is None


async def test_a_delete_event_deactivates_rather_than_removing(monkeypatch) -> None:
    """Hard-deleting would orphan memberships and audit rows that must survive
    (hard rule 4). `deactivated_at` is what the auth guard re-checks per request, so
    the effect is immediate anyway."""
    settings = get_settings()
    monkeypatch.setattr(settings, "clerk_webhook_secret", SECRET)

    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    created = _user_event(clerk_id, f"{clerk_id}@example.com")
    deleted = json.dumps({"type": "user.deleted", "data": {"id": clerk_id}}).encode()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        await http.post(
            "/hooks/v1/clerk",
            content=created,
            headers=_sign(created, svix_id=f"m_{uuid.uuid4().hex[:8]}"),
        )
        response = await http.post(
            "/hooks/v1/clerk",
            content=deleted,
            headers=_sign(deleted, svix_id=f"m_{uuid.uuid4().hex[:8]}"),
        )

    assert response.json()["status"] == "deactivated"
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT deactivated_at FROM users WHERE clerk_user_id = :c"), {"c": clerk_id}
            )
        ).first()
    assert row is not None and row[0] is not None, "the row survives, deactivated"
