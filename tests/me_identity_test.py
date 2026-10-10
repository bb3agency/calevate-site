"""`GET /v1/me` names the signed-in person to themselves, and to nobody else.

The account page shows "signed in as <address>". The address travels on `/v1/me` (which
declares `org:read`) rather than on the session read (which declares nothing), because a
contact field on an undeclared route is what `check_redaction_exposure` rule 2 refuses.

What must stay false: a view-as session must not receive anybody's address. The operator
is not a member of the account, and nothing on the client UI may look like the client's
own session (D-22).

CONCURRENCY: every case mints its own tenant and users, so this file runs beside the other
suites on the shared Postgres.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements
from tests.impersonation_grant_test import view_as_headers


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _tenant() -> str:
    created = await admin_service.create_organization(
        name="Identity Traders",
        slug=f"me-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    await accept_agreements(uuid.UUID(str(created["id"])))
    return str(created["slug"])


async def _member(slug: str, *, name: str | None) -> tuple[str, str]:
    """A user with an owner membership. Returns (email, dev bearer token)."""
    user_id = uuid.uuid4()
    email = f"{user_id}@example.com"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, name, created_at, updated_at) "
                "VALUES (:id, :email, :name, now(), now())"
            ),
            {"id": user_id, "email": email, "name": name},
        )
        tenant_id = (
            await session.execute(text("SELECT id FROM organizations WHERE slug = :s"), {"s": slug})
        ).scalar_one()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return email, f"dev:client:{user_id}"


async def _admin_token() -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
    return f"dev:admin:{admin_id}"


@pytest.mark.asyncio
async def test_a_member_reads_their_own_address_and_name() -> None:
    slug = await _tenant()
    email, token = await _member(slug, name="Lakshmi Rao")
    # A colleague in the same account, so "own row" is distinguishable from "a row".
    await _member(slug, name="Someone Else")

    async with _client() as http:
        response = await http.get(
            "/v1/me", headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == email
    assert body["name"] == "Lakshmi Rao"


@pytest.mark.asyncio
async def test_a_member_with_no_name_gets_null_rather_than_a_placeholder() -> None:
    slug = await _tenant()
    email, token = await _member(slug, name=None)

    async with _client() as http:
        response = await http.get(
            "/v1/me", headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
        )

    assert response.status_code == 200, response.text
    assert response.json()["email"] == email
    assert response.json()["name"] is None


@pytest.mark.asyncio
async def test_a_view_as_session_receives_no_address() -> None:
    slug = await _tenant()
    await _member(slug, name="Lakshmi Rao")
    operator = await _admin_token()

    async with _client() as http:
        headers = await view_as_headers(http, operator, slug)
        response = await http.get("/v1/me", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["impersonating"] is True
    assert response.json()["email"] is None
    assert response.json()["name"] is None
