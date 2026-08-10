"""Admin-realm security: the onboarding wizard, invitations, and the narrow admin GUC.

The `app.admin` GUC is the single widest thing in the tenancy model, so it gets the
most explicit tests: it must open the client DIRECTORY and nothing else, and it must
open no writes at all.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


async def _make_admin(role: str = "superadmin") -> str:
    clerk_id = f"admin_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:id, :cid, 'Ops', :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "cid": clerk_id, "role": role},
        )
    return f"dev:admin:{clerk_id}"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def test_admin_guc_opens_the_directory_but_not_tenant_data() -> None:
    """The precise claim migration b57e2f9c4a13 makes, asserted rather than trusted."""
    created = await service.create_organization(
        name="Guc Test Clinic",
        slug=f"guc-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = created["id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, "
                "created_at, updated_at) VALUES (:i, :t, :a, '+919876500001', 'manual', 'new', "
                "now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "a": created["agent_id"]},
        )

    async with admin_session() as session:
        orgs = (await session.execute(text("SELECT count(*) FROM organizations"))).scalar()
        leads = (await session.execute(text("SELECT count(*) FROM leads"))).scalar()
        calls = (await session.execute(text("SELECT count(*) FROM calls"))).scalar()
        turns = (await session.execute(text("SELECT count(*) FROM transcript_turns"))).scalar()

    assert orgs and orgs >= 1, "the admin realm must be able to enumerate clients"
    assert leads == 0, "app.admin must NOT unlock lead data"
    assert calls == 0, "app.admin must NOT unlock call data"
    assert turns == 0, "app.admin must NOT unlock transcripts"


async def test_admin_guc_grants_no_writes() -> None:
    """WITH CHECK was left untouched on purpose: reading the directory is not a licence
    to create tenants outside the normal path."""
    with pytest.raises(DBAPIError):
        async with admin_session() as session:
            await session.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                    "VALUES (:i, 'Sneaky', :s, 'active', now(), now())"
                ),
                {"i": uuid.uuid4(), "s": f"sneaky-{uuid.uuid4().hex[:8]}"},
            )


async def test_onboarding_creates_retention_policies_and_a_schema() -> None:
    """A tenant with no retention policy is a compliance gap from its first call, and a
    tenant with no extraction schema produces leads with no columns."""
    created = await service.create_organization(
        name="Wizard Clinic",
        slug=f"wiz-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@example.com",
        language="te-IN",
        created_by=None,
    )
    async with tenant_session(created["id"]) as session:
        policies = (
            await session.execute(
                text("SELECT data_category, ttl_days FROM retention_policies ORDER BY 1")
            )
        ).all()
        agent = (
            await session.execute(
                text("SELECT disclosure_line, status, direction FROM agents LIMIT 1")
            )
        ).first()
        fields = (
            await session.execute(text("SELECT fields FROM extraction_schemas LIMIT 1"))
        ).scalar()

    categories = {p[0]: p[1] for p in policies}
    assert categories, "retention defaults must exist from creation"
    assert categories["recording"] >= 90, "TRAI's 90-day recording floor (SEC-COMP §1)"
    assert agent is not None
    assert "AI assistant" in agent[0], "the disclosure line is inserted by us, always"
    assert agent[1] == "draft", "nothing is client-visible until publish"
    assert agent[2] == "inbound", "D-38: the receptionist is the default agent"
    assert fields, "the vertical template must seed the extraction schema"


async def test_reserved_slugs_are_refused() -> None:
    from apps.api.core.errors import ProblemError

    async with admin_session() as session:
        with pytest.raises(ProblemError) as exc:
            await service.assert_slug_available(session, "admin")
    assert exc.value.code == "slug_reserved"


async def test_an_invitation_can_only_be_burned_once() -> None:
    """Two clicks on the same emailed link must produce one membership (CAS on
    used_at IS NULL, BACKEND-PATTERNS §5)."""
    from apps.api.core.errors import ProblemError

    created = await service.create_organization(
        name="Invite Clinic",
        slug=f"inv-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = created["id"]
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:i, :c, :e, now(), now())"
            ),
            {"i": user_id, "c": f"u_{user_id.hex[:10]}", "e": "invitee@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        token = await service.create_invitation(
            session, tenant_id=tenant_id, email="invitee@example.com", role="owner", created_by=None
        )
        stored = (await session.execute(text("SELECT token_hash FROM invitations"))).scalar()

    assert stored != token, "invitations are hashed at rest — a leaked DB grants nothing"

    async with tenant_session(tenant_id) as session:
        assert await service.accept_invitation(session, raw_token=token, user_id=user_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as exc:
            await service.accept_invitation(session, raw_token=token, user_id=user_id)
    assert exc.value.code == "invitation_invalid"

    async with tenant_session(tenant_id) as session:
        count = (await session.execute(text("SELECT count(*) FROM memberships"))).scalar()
    assert count == 1


async def test_admin_routes_reject_a_client_token() -> None:
    """Realms never share session logic (TRD §11): a client token is not an admin token
    even if the user is also an operator."""
    async with _client() as http:
        response = await http.get(
            "/v1/admin/tenants", headers={"Authorization": "Bearer dev:client:user_local"}
        )
    assert response.status_code in (401, 403)


async def test_admin_can_list_tenants_with_health() -> None:
    token = await _make_admin()
    async with _client() as http:
        response = await http.get("/v1/admin/tenants", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list) and body
    assert {"id", "name", "slug", "status", "calls_7d", "leads"} <= set(body[0])
