"""`GET /v1/integrations/deliveries/{id}/payload` — the raw-PII surface of D-23.

The retained delivery body is the client's customer in unredacted form, so this route is
in the same class as the raw transcript and hard rule 5 governs it: role check AND an
`audit_log` write, never one of the two. It is also the ONE place a stored body can leave
our boundary, which makes four questions worth a test each:

1. **Does the role check hold?** `staff` holds `org:read` and sees the delivery list.
   They must not see the body — the permission follows the DATA (`calls:read_raw`), not
   the screen it is rendered on.
2. **Is the read audited?** An unaudited raw read is a rule-5 violation whether or not
   anyone noticed.
3. **Can a neighbour reach it over HTTP?** `webhook_deliveries` carries no RLS policy, so
   the route's own subquery is the entire tenant boundary.
4. **Are "we no longer keep it" and "we cannot read it right now" different answers?**
   Telling a client their evidence is gone during a storage outage is a lie with a
   support ticket attached.
"""

# ruff: noqa: N803 — boto3's keyword arguments are PascalCase (`Bucket`, `Key`, `Body`,
# `Delete`, `Prefix`). A fake that renamed them would not be callable by the code under
# test, which is the only reason it exists.

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.integrations import service
from apps.api.main import app
from apps.workers import storage
from botocore.exceptions import ClientError
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

BODY = '{"id":"d1","event":"lead.created","data":{"name":"Priya","phone":"+919876500001"}}'


class _Store:
    """The object store, in a dict, with a switch for "the bucket will not answer"."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail = False

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if self.fail:
            raise ClientError({"Error": {"Code": "ServiceUnavailable"}}, "GetObject")
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        import io

        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **_: Any) -> dict[str, Any]:
        self.objects[Key] = Body
        return {}


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _Store:
    fake = _Store()
    monkeypatch.setattr(storage, "_client", lambda: fake)
    return fake


async def _tenant(role: str = "owner") -> tuple[uuid.UUID, str, str]:
    """(tenant_id, slug, bearer token) for a fresh org with one member of `role`."""
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    slug = f"dp-{tenant_id.hex[:10]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Clinic', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": slug},
        )
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return tenant_id, slug, f"dev:client:{user_id}"


async def _delivery_with_body(
    tenant_id: uuid.UUID, store: _Store, *, write_object: bool = True
) -> uuid.UUID:
    """One delivered event whose body is retained, as the worker would leave it."""
    endpoint_id, delivery_id, lead_id = uuid7(), uuid7(), uuid7()
    key = storage.delivery_body_key(
        tenant_id=tenant_id, subject_type="lead", subject_id=str(lead_id), delivery_id=delivery_id
    )
    if write_object:
        await storage.store_delivery_body(
            key=key,
            delivery_id=delivery_id,
            endpoint_id=endpoint_id,
            event="lead.created",
            subject_type="lead",
            subject_id=str(lead_id),
            body=BODY,
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "active, created_at, updated_at) VALUES (:id, :tid, 'webhook', "
                "'https://crm.example/h', 'whsec_x', ARRAY['lead.created'], true, now(), now())"
            ),
            {"id": endpoint_id, "tid": tenant_id},
        )
        await service.record_delivery(
            session,
            delivery_id=delivery_id,
            endpoint_id=endpoint_id,
            event="lead.created",
            status="delivered",
            attempts=1,
            status_code=200,
            payload_ref=key,
        )
    return delivery_id


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _auth(slug: str, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def test_an_owner_sees_the_exact_body_and_the_read_is_audited(store: _Store) -> None:
    tenant_id, slug, token = await _tenant("owner")
    delivery_id = await _delivery_with_body(tenant_id, store)

    async with _client() as http:
        response = await http.get(
            f"/v1/integrations/deliveries/{delivery_id}/payload", headers=_auth(slug, token)
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["body"] == BODY, "byte for byte, or it cannot settle a dispute"
    assert body["truncated"] is False and body["original_bytes"] == len(BODY.encode())

    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'webhook_delivery.read_payload'"
                    " AND object_id = :did"
                ),
                {"did": str(delivery_id)},
            )
        ).scalar()
    assert audited == 1, "a raw read that is not audited is a rule-5 violation"


async def test_staff_can_see_that_it_was_delivered_and_not_what_was_in_it(
    store: _Store,
) -> None:
    """`staff` holds `org:read`, so they get the delivery LIST — "did it arrive?" is a
    question a receptionist chasing a lead legitimately asks. `calls:read_raw` is owner
    only, and the body is the customer's own details."""
    tenant_id, slug, token = await _tenant("staff")
    delivery_id = await _delivery_with_body(tenant_id, store)

    async with _client() as http:
        listed = await http.get("/v1/integrations/deliveries", headers=_auth(slug, token))
        refused = await http.get(
            f"/v1/integrations/deliveries/{delivery_id}/payload", headers=_auth(slug, token)
        )

    assert listed.status_code == 200
    rows = listed.json()
    assert [row["id"] for row in rows] == [str(delivery_id)]
    assert rows[0]["payload_stored"] is True, "the list says a copy exists, not what is in it"
    assert "Priya" not in listed.text and "9876500001" not in listed.text
    assert refused.status_code == 403
    assert "Priya" not in refused.text


async def test_a_neighbouring_tenant_gets_404_over_http(store: _Store) -> None:
    """`webhook_deliveries` has no RLS policy — the route's `outbound_webhooks` subquery
    is the whole tenant boundary, and 404 (not 403) is the deliberate answer."""
    tenant_a, _, _ = await _tenant("owner")
    _, slug_b, token_b = await _tenant("owner")
    delivery_id = await _delivery_with_body(tenant_a, store)

    async with _client() as http:
        response = await http.get(
            f"/v1/integrations/deliveries/{delivery_id}/payload", headers=_auth(slug_b, token_b)
        )

    assert response.status_code == 404
    assert "Priya" not in response.text


async def test_an_expired_body_and_an_unreachable_store_are_different_answers(
    store: _Store,
) -> None:
    """Both are "no body on your screen". One is a fact about our retention and one is a
    fact about today, and a client acts differently on each."""
    tenant_id, slug, token = await _tenant("owner")
    expired = await _delivery_with_body(tenant_id, store)
    async with tenant_session(tenant_id) as session:
        # What the retention sweep and an erasure both leave behind.
        await session.execute(
            text("UPDATE webhook_deliveries SET payload_ref = NULL WHERE id = :id"),
            {"id": expired},
        )
    live = await _delivery_with_body(tenant_id, store)

    async with _client() as http:
        gone = await http.get(
            f"/v1/integrations/deliveries/{expired}/payload", headers=_auth(slug, token)
        )
        store.fail = True
        unreachable = await http.get(
            f"/v1/integrations/deliveries/{live}/payload", headers=_auth(slug, token)
        )

    # The stable machine identifier is the last segment of `type` (core/errors.py).
    assert gone.status_code == 404
    assert gone.json()["type"].endswith("/delivery_body_not_retained")
    assert gone.json()["retryable"] is False, "trying again will not bring it back"

    assert unreachable.status_code == 502
    assert unreachable.json()["type"].endswith("/delivery_body_unavailable")
    assert unreachable.json()["retryable"] is True, "this one IS worth trying again"
    assert "has not been deleted" in json.dumps(unreachable.json())
