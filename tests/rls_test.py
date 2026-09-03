"""Tenancy isolation tests (hard rule 1) — the cross-tenant zero-rows guarantee.

Run: uv run pytest -k rls
Requires the local Postgres (docker compose up -d) with migrations applied.
"""

import re
import uuid

import pytest
from apps.api.db.session import (
    session_tenant,
    tenant_session,
    untenanted_session,
    user_session,
)
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
                "ai_disclosure_line, recording_notice_line, caller_memory_notice_line, "
                "created_at, updated_at) VALUES (:id, :tid, 'a', 'inbound', 'I am an AI', 'I am "
                "an AI', 'This call is being recorded.', 'I keep a short note of what you ask "
                "about.', now(), now())"
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


async def test_the_session_reports_the_tenant_it_is_actually_scoped_to() -> None:
    """`session_tenant` is the ONE reader of the GUC outside the writer beside it.

    Services take a tenant-scoped session and no tenant id — that is what makes RLS the
    isolation rather than a convention — so a shared reader that needs the id (spend
    counters, on the CRM dashboard) has to ask the session. Asking the GUC means the id
    can only ever be the one every policy on this connection is already enforcing, so it
    is incapable of widening anything; asking the request principal would not be.
    """
    org = await _make_org("Tenant GUC")
    async with tenant_session(org) as s:
        assert await session_tenant(s) == org


async def test_an_untenanted_session_refuses_rather_than_answering_zero() -> None:
    """The branch that decides whether a missing scope becomes a number.

    An unset GUC means the caller is outside a tenant session, where every tenant-scoped
    read above this point has already returned nothing (see the test above this pair).
    Returning a zero, or a nil UUID, would render "we are not scoped to anyone" as a
    confident "this client used nothing" on a client-facing dashboard tile — the exact
    class of defect the after-hours basis field exists to prevent one screen over. So it
    raises, loudly, in the caller's own transaction.
    """
    async with untenanted_session() as s:
        with pytest.raises(RuntimeError, match="tenant-scoped session"):
            await session_tenant(s)


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
                    "ai_disclosure_line, recording_notice_line, caller_memory_notice_line, "
                    "created_at, updated_at) VALUES (:id, :tid, 'x', 'inbound', 'AI', 'AI', "
                    "'This call is being recorded.', 'I keep a short note of what you ask "
                    "about.', now(), now())"
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
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id.hex[:8]}@x.test"},
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


# --- The read-widening GUCs, as a CATALOGUE property (hard rule 1) ------------
#
# `db/session.py` opens five sessions that are not `tenant_session`, and four of them
# widen a policy on purpose so that authentication can happen at all: `app.user_id` (your
# own memberships and the organizations they point at), `app.invite_hash` (the one
# invitation whose token you can name), `app.ingest_webhook_id` (the one ingest config in
# the URL) and `app.admin` (the tenant DIRECTORY). Each of those four docstrings makes the
# SAME promise in its own words — "widens the READ policy ... and widens the WRITE policy
# by nothing", "it widens no WITH CHECK anywhere" — and until this test nothing measured it.
#
# The tests above measure ONE of them, behaviourally, for `app.user_id`. That is the right
# shape and it does not scale: a widening added by a future migration arrives with no
# behavioural test of its own, and the failure is silent in the worst direction. A
# `WITH CHECK` carrying `app.user_id` would let any signed-in person INSERT a `memberships`
# row naming themselves `owner` of ANY tenant; one carrying `app.admin` would let the
# directory session write organizations it can only enumerate.
#
# So this asks the catalogue instead, over every policy on the database the suite is
# pointed at, which is the same source `scripts/check_rls_coverage.py` reads. It is a
# one-directional rule and deliberately so: a widening GUC may appear in `qual` (that is
# what widening IS) and may never appear in `with_check`.

#: The GUCs that exist to widen a READ and must never widen a WRITE, with the session that
#: sets each — named so a failure says which door was left open, not just which string.
_READ_ONLY_WIDENING_GUCS: dict[str, str] = {
    "app.user_id": "user_session() — 'which tenants may this user enter?'",
    "app.invite_hash": "invite_session() — the one invitation whose token the caller holds",
    "app.ingest_webhook_id": "ingest_config_session() — the one ingest config named in the URL",
    "app.admin": "admin_session() — the tenant directory, enumerate only",
}


async def test_a_read_widening_guc_never_widens_a_write() -> None:
    """`USING` may name these; `WITH CHECK` may not. Read from `pg_policies`, not assumed.

    A `DELETE` policy is exempt because a DELETE has no `WITH CHECK` in SQL at all — the
    one that exists (`organizations_delete_admin_only`, migration d1b8f30c94a7) is a
    deliberate admin authority with its own suite (`tests/organizations_delete_rls_test.py`).
    """
    async with untenanted_session() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT tablename, policyname, cmd, with_check FROM pg_policies "
                    "WHERE with_check IS NOT NULL ORDER BY tablename, policyname"
                )
            )
        ).all()
    assert rows, "found no policies with a WITH CHECK — this test would pass vacuously"
    offenders = [
        f"{table}.{policy} ({cmd}) has {guc} in its WITH CHECK. That GUC is set by "
        f"{door}, and it is a READ widening — putting it in a WITH CHECK makes it a WRITE "
        f"one: {with_check}"
        for table, policy, cmd, with_check in rows
        for guc, door in _READ_ONLY_WIDENING_GUCS.items()
        if guc in str(with_check)
    ]
    assert not offenders, "; ".join(offenders)


def test_every_widening_guc_this_repo_sets_is_covered_by_the_rule_above() -> None:
    """The other direction: a new GUC in `db/session.py` cannot slip past that assertion.

    `_READ_ONLY_WIDENING_GUCS` is a hand-kept list, and a hand-kept list of security
    exemptions rots the moment somebody adds a fifth session helper. `app.tenant_id` is the
    tenancy key itself (it is SUPPOSED to be in every `WITH CHECK`) and `app.auth` is the
    credential store's whole policy rather than a widening of a tenant one — those two are
    named here so the census is an equality rather than a subset.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent / "apps" / "api" / "db" / "session.py"
    ).read_text(encoding="utf-8")
    found = set(re.findall(r"set_config\('(app\.[a-z_]+)'", source))
    accounted = set(_READ_ONLY_WIDENING_GUCS) | {"app.tenant_id", "app.auth"}
    assert found == accounted, (
        f"`db/session.py` sets {sorted(found)} but this file accounts for "
        f"{sorted(accounted)}. A new GUC is a new door: add it to "
        "`_READ_ONLY_WIDENING_GUCS` if it widens a read, or beside `app.tenant_id` if it "
        "is a tenancy key in its own right."
    )
