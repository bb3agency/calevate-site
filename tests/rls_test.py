"""Tenancy isolation tests (hard rule 1) — the cross-tenant zero-rows guarantee.

Run: uv run pytest -k rls
Requires the local Postgres (docker compose up -d) with migrations applied.
"""

import uuid

import pytest
from apps.api.db.session import tenant_session, untenanted_session, user_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = [pytest.mark.rls]


async def _make_org(name: str) -> uuid.UUID:
    """Org creation runs under the NEW org's own GUC: FORCE RLS derives WITH CHECK
    from USING, so inserting a tenant root requires app.tenant_id = new org id.
    (The onboarding wizard does exactly this — generate the id first, then insert.)
    """
    org_id = uuid.uuid4()
    slug = f"t-{org_id.hex[:12]}"
    async with tenant_session(org_id) as s:
        await s.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, :name, :slug, 'active', now(), now())"
            ),
            {"id": org_id, "name": name, "slug": slug},
        )
    return org_id


async def _make_lead(tenant_id: uuid.UUID, phone: str) -> None:
    async with tenant_session(tenant_id) as s:
        agent_id = uuid.uuid4()
        await s.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "created_at, updated_at) VALUES (:id, :tid, 'a', 'inbound', 'I am an AI', "
                "now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id},
        )
        await s.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :phone, 'manual', "
                "now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "aid": agent_id, "phone": phone},
        )


async def test_cross_tenant_reads_return_zero_rows() -> None:
    org_a = await _make_org("Tenant A")
    org_b = await _make_org("Tenant B")
    await _make_lead(org_a, "+919000000001")
    await _make_lead(org_b, "+919000000002")

    async with tenant_session(org_a) as s:
        rows = (await s.execute(text("SELECT phone_e164 FROM leads"))).scalars().all()
    assert rows == ["+919000000001"], "tenant A must see ONLY its own leads"

    async with tenant_session(org_b) as s:
        rows = (await s.execute(text("SELECT phone_e164 FROM leads"))).scalars().all()
    assert rows == ["+919000000002"], "tenant B must see ONLY its own leads"


async def test_missing_guc_yields_zero_rows_never_all() -> None:
    org = await _make_org("Tenant C")
    await _make_lead(org, "+919000000003")

    async with untenanted_session() as s:
        leads = (await s.execute(text("SELECT count(*) FROM leads"))).scalar()
        orgs = (await s.execute(text("SELECT count(*) FROM organizations"))).scalar()
    assert leads == 0, "no GUC ⇒ zero lead rows (fail closed)"
    assert orgs == 0, "no GUC ⇒ zero organization rows (fail closed)"


async def test_wrong_tenant_guc_cannot_write_into_other_tenant() -> None:
    org_a = await _make_org("Tenant D")
    org_b = await _make_org("Tenant E")

    with pytest.raises(DBAPIError):
        # Session bound to A tries to insert an agent belonging to B ⇒ RLS
        # WITH CHECK (derived from USING) rejects the row.
        async with tenant_session(org_a) as s:
            await s.execute(
                text(
                    "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                    "created_at, updated_at) VALUES (:id, :tid, 'x', 'inbound', 'AI', "
                    "now(), now())"
                ),
                {"id": uuid.uuid4(), "tid": org_b},
            )


async def test_usage_events_ledger_is_append_only() -> None:
    org = await _make_org("Tenant F")
    event_id = uuid.uuid4()
    async with tenant_session(org) as s:
        await s.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, unit_type, qty, occurred_at, "
                "created_at) VALUES (:id, :tid, 'platform_min', 1.0, now(), now())"
            ),
            {"id": event_id, "tid": org},
        )

    with pytest.raises(DBAPIError, match="append-only"):
        async with tenant_session(org) as s:
            await s.execute(
                text("UPDATE usage_events SET qty = 2.0 WHERE id = :id"), {"id": event_id}
            )

    with pytest.raises(DBAPIError, match="append-only"):
        async with tenant_session(org) as s:
            await s.execute(text("DELETE FROM usage_events WHERE id = :id"), {"id": event_id})


async def test_organization_slug_is_immutable() -> None:
    org = await _make_org("Tenant G")
    with pytest.raises(DBAPIError, match="immutable"):
        async with tenant_session(org) as s:
            await s.execute(
                text("UPDATE organizations SET slug = 'new-slug' WHERE id = :id"), {"id": org}
            )


# --- app.user_id (migration 8c31d0f4ab27) ------------------------------------
# The second GUC exists so authentication can answer "which tenants may this user
# enter?" before a tenant is chosen. These tests pin down that it widens READS by
# exactly one clause and widens WRITES by nothing.


async def _make_user_with_membership(tenant_id: uuid.UUID, role: str = "owner") -> uuid.UUID:
    user_id = uuid.uuid4()
    async with untenanted_session() as s:
        await s.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:id, :cid, :email, now(), now())"
            ),
            {"id": user_id, "cid": f"u_{user_id.hex[:12]}", "email": f"{user_id.hex[:8]}@x.test"},
        )
    async with tenant_session(tenant_id) as s:
        await s.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return user_id


async def test_user_guc_sees_only_its_own_memberships() -> None:
    org_a = await _make_org("Tenant H")
    org_b = await _make_org("Tenant I")
    user_a = await _make_user_with_membership(org_a)
    await _make_user_with_membership(org_b)

    async with user_session(user_a) as s:
        rows = (await s.execute(text("SELECT tenant_id FROM memberships"))).scalars().all()
        orgs = (await s.execute(text("SELECT id FROM organizations"))).scalars().all()

    assert rows == [org_a], "a user sees only the membership rows that are their own"
    assert orgs == [org_a], "and only the organizations those memberships point at"


async def test_user_guc_cannot_write_anything() -> None:
    """The whole point of the narrower GUC: it is a READ widening. If it could write,
    membership in one tenant would become a way to create rows in it without ever
    being scoped to it."""
    org = await _make_org("Tenant J")
    user = await _make_user_with_membership(org)

    with pytest.raises(DBAPIError):
        async with user_session(user) as s:
            await s.execute(
                text(
                    "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, "
                    "updated_at) VALUES (:id, :tid, :uid, 'owner', now(), now())"
                ),
                {"id": uuid.uuid4(), "tid": org, "uid": user},
            )


async def test_user_guc_does_not_unlock_tenant_data() -> None:
    """Membership lets you find the door; it does not open it. Leads still need
    app.tenant_id."""
    org = await _make_org("Tenant K")
    user = await _make_user_with_membership(org)
    await _make_lead(org, "+919000000004")

    async with user_session(user) as s:
        leads = (await s.execute(text("SELECT count(*) FROM leads"))).scalar()
    assert leads == 0, "the user GUC must not widen access to tenant business data"
