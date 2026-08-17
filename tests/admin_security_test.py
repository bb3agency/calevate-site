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
from tests.impersonation_grant_test import view_as_headers


async def _make_admin(role: str = "superadmin") -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}"


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
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:i, :e, now(), now())"
            ),
            {"i": user_id, "e": "invitee@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        _invitation_id, token = await service.create_invitation(
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


async def test_an_invitee_can_accept_before_they_have_any_membership() -> None:
    """The chicken-and-egg the `/v1/invitations/accept` route exists for: a new invitee
    is authenticated but has no membership, and creating one is the point. Every other
    authenticated route would 403 them, correctly."""
    created = await service.create_organization(
        name="Accept Clinic",
        slug=f"acc-{uuid.uuid4().hex[:8]}",
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
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:i, :e, now(), now())"
            ),
            {"i": user_id, "e": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        _invitation_id, token = await service.create_invitation(
            session,
            tenant_id=tenant_id,
            email=f"{user_id}@example.com",
            role="owner",
            created_by=None,
        )

    headers = {"Authorization": f"Bearer dev:client:{user_id}"}
    async with _client() as http:
        # Before accepting, a normal tenant route refuses them.
        blocked = await http.get("/v1/leads", headers=headers)
        accepted = await http.post("/v1/invitations/accept", json={"token": token}, headers=headers)
        after = await http.get("/v1/leads", headers={**headers, "X-Org-Slug": created["slug"]})

    assert blocked.status_code == 403, "no membership, no tenant data"
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["slug"] == created["slug"]
    assert accepted.json()["role"] == "owner"
    assert after.status_code == 200, "the membership the accept created now works"


async def test_a_bad_or_reused_invite_token_is_indistinguishable() -> None:
    """An attacker guessing tokens must not learn whether one exists, is used, or has
    expired — all three answer identically."""
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:i, :e, now(), now())"
            ),
            {"i": user_id, "e": f"{user_id}@example.com"},
        )
    async with _client() as http:
        response = await http.post(
            "/v1/invitations/accept",
            json={"token": "x" * 40},
            headers={"Authorization": f"Bearer dev:client:{user_id}"},
        )
    assert response.status_code == 422
    assert response.json()["type"].endswith("/invitation_invalid")


async def test_the_invite_guc_grants_no_writes_and_no_other_rows() -> None:
    """The widening is READ-ONLY and scoped to the single named row (c93a17d0e5b4)."""
    from apps.api.db.session import invite_session

    created = await service.create_organization(
        name="Guc Invite Clinic",
        slug=f"gi-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    async with tenant_session(created["id"]) as session:
        _invitation_id, token = await service.create_invitation(
            session, tenant_id=created["id"], email="a@b.test", role="owner", created_by=None
        )
    import hashlib

    token_hash = hashlib.sha256(token.encode()).hexdigest()

    async with invite_session(token_hash) as session:
        visible = (await session.execute(text("SELECT count(*) FROM invitations"))).scalar()
        leads = (await session.execute(text("SELECT count(*) FROM leads"))).scalar()
    assert visible == 1, "exactly the row the caller could already name"
    assert leads == 0, "the invite GUC unlocks nothing else"

    with pytest.raises(DBAPIError):
        async with invite_session(token_hash) as session:
            await session.execute(
                text(
                    "INSERT INTO invitations (id, tenant_id, email, role, token_hash, "
                    "expires_at, created_at, updated_at) VALUES (:i, :t, 'x@y.test', 'owner', "
                    ":h, now() + interval '72 hours', now(), now())"
                ),
                {"i": uuid.uuid4(), "t": created["id"], "h": "deadbeef" * 8},
            )


async def test_view_as_client_actually_resolves_the_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: "view as client" 404'd on every tenant that exists.

    The impersonation slug was resolved under `untenanted_session`, where
    `organizations` is RLS'd on `app.tenant_id` or a membership — an operator has
    neither, so the lookup saw zero rows and raised "Organization not found" for a
    live client. Reading the client directory is precisely what `app.admin` (and only
    `admin_session`) is for.
    """
    token = await _make_admin()
    created = await service.create_organization(
        name="Impersonation Clinic",
        slug=f"imp-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    slug = created["slug"]

    async with _client() as http:
        # A real grant, so the 403 below is D-22's read-only rule and not the grant
        # check refusing before that rule is reached (tests/impersonation_grant_test).
        headers = await view_as_headers(http, token, slug, **{"X-Org-Slug": slug})
        seen = await http.get("/v1/agents", headers=headers)
        # D-22 still holds: read-only. A mutation through the impersonated session is
        # refused, which is the other half of the same feature.
        blocked = await http.post(
            "/v1/kb/sources",
            headers=headers,
            json={
                "agent_id": str(created["agent_id"]),
                "name": "Hours",
                "body": "9 to 5",
                "kind": "text",
            },
        )
        # No grant here, and none is possible: the slug lookup runs first, so a tenant
        # that does not exist is a 404 before there is anything for a grant to name.
        unknown = await http.get(
            "/v1/agents",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Org-Slug": "no-such-client",
                "X-Impersonate-Org": "no-such-client",
            },
        )

    assert seen.status_code == 200, seen.text
    assert blocked.status_code == 403, "impersonation is read-only (D-22)"
    assert "read-only" in blocked.json()["detail"].lower(), blocked.text
    assert unknown.status_code == 404, "a slug that does not exist is still a 404"
