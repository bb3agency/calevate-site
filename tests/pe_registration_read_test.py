"""A client can SEE their own DLT Principal Entity registration (SEC-COMP §3).

The gap this file closes. SEC-COMP §3's first bullet has two subjects and, until now,
two write surfaces and one and a half read surfaces:

- Calevate's own TM registration is written by `POST /v1/ops/platform/tm-registration`
  and **already readable** on `GET /v1/ops/platform` (`tm_registration`), so the ops
  half needed nothing — see `test_the_ops_surface_still_reads_back_the_tm_row`, which
  pins that rather than duplicating it.
- The client's own PE registration is written by ops
  (`POST /v1/admin/tenants/{id}/dlt-registration`, deliberately never by the client)
  and could be read by **nobody in the client realm**. A tenant whose launch button
  says `pe_registration_missing` or `pe_registration_not_active` had no page that
  said what the registrar currently holds, when it was recorded, or when we last
  checked it. That is the view a client opens precisely when something is already
  blocked, which is the worst possible moment to have no view at all.

Three properties are load-bearing here and each has a test below:

1. **Absence is data, not a 404.** A tenant with no registration row is the normal
   state of every new account, not an error. The console renders "not filed yet, we
   are on it" from a 200 with `recorded: false`; a 404 would be indistinguishable
   from a broken route or a lost permission at the fetch layer.
2. **Hard rule 1.** The read goes through the RLS-scoped session, and tenant B asking
   for the registration sees their own absence — never tenant A's PE id.
3. **D-22.** It is a GET, so it must not require a permission read-only impersonation
   refuses. `org:read` is the permission `staff`, `owner` and `operator` all hold and
   `MUTATING_PERMISSIONS` does not contain.

Run: uv run pytest -q tests/pe_registration_read_test.py
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.rbac import MUTATING_PERMISSIONS, iter_api_routes
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.rls]

PATH = "/v1/compliance/dlt-registration"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


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


async def _make_member(tenant_id: uuid.UUID, role: str = "owner") -> str:
    user_id = uuid.uuid4()
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
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{user_id}"


async def _tenant() -> dict[str, Any]:
    """A fresh organization. `create_organization` files no PE registration, which is
    exactly the state this endpoint has to describe honestly."""
    created = await admin_service.create_organization(
        name="Principal Entity Motors",
        slug=f"pe-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    async with tenant_session(created["id"]) as session:
        # `create_organization` seeds a registration row on some paths; this suite is
        # about what a tenant with NOTHING filed sees, so start from nothing.
        await session.execute(
            text("DELETE FROM dlt_registrations WHERE tenant_id = :tid"), {"tid": created["id"]}
        )
    return created


async def _headers(org: dict[str, Any], role: str = "owner") -> dict[str, str]:
    token = await _make_member(uuid.UUID(str(org["id"])), role=role)
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": str(org["slug"])}


async def _record(org: dict[str, Any], *, pe_id: str, status: str = "active") -> None:
    """File the registration the way production does — through the audited ops route,
    not by writing the row here. A read test that seeds its own row can pass against a
    schema the writer no longer produces."""
    token = await _make_admin()
    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{org['id']}/dlt-registration",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "status": status,
                "tm_link_status": "active",
                "pe_id": pe_id,
                "entity_name": "Principal Entity Motors Pvt Ltd",
            },
        )
    assert response.status_code == 200, response.text


# --------------------------------------------------------------- the client read


async def test_a_tenant_with_no_registration_gets_its_absence_as_data() -> None:
    """The normal state of a new account, and not an error.

    200 with `recorded: false`, so the console can say "not filed yet" without having
    to tell a 404-that-means-nothing-is-filed apart from a 404-that-means-the-route-
    moved or the token lost its permission.
    """
    org = await _tenant()
    async with _client() as http:
        response = await http.get(PATH, headers=await _headers(org))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recorded"] is False
    assert body["status"] is None
    assert body["pe_id"] is None
    assert body["registered_at"] is None
    assert body["verified_at"] is None
    assert body["is_active"] is False


async def test_a_tenant_sees_the_registration_ops_filed_for_them() -> None:
    """Status, the registrar's entity id, when it was recorded, and when WE last
    verified it — the four facts the client is entitled to about their own PE."""
    org = await _tenant()
    pe_id = f"1102{uuid.uuid4().int % 10**9:09d}"
    await _record(org, pe_id=pe_id)

    async with _client() as http:
        response = await http.get(PATH, headers=await _headers(org))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recorded"] is True
    assert body["status"] == "active"
    assert body["tm_link_status"] == "active"
    assert body["pe_id"] == pe_id
    assert body["entity_name"] == "Principal Entity Motors Pvt Ltd"
    assert body["registered_at"] is not None
    assert body["verified_at"] is not None
    assert body["is_active"] is True


async def test_a_submitted_registration_is_not_active() -> None:
    """`is_active` is computed here rather than left to the console: "is `submitted`
    good enough" is the question the launch gate already answers, and the two must
    never disagree."""
    org = await _tenant()
    await _record(org, pe_id=f"1102{uuid.uuid4().int % 10**9:09d}", status="submitted")

    async with _client() as http:
        response = await http.get(PATH, headers=await _headers(org))

    body = response.json()
    assert body["status"] == "submitted"
    assert body["is_active"] is False
    assert body["recorded"] is True


async def test_staff_may_read_it_too() -> None:
    """`org:read`, not `org:manage`: looking at your own compliance state is not
    changing it, and a `staff` member watching a blocked launch needs the same page."""
    org = await _tenant()
    await _record(org, pe_id=f"1102{uuid.uuid4().int % 10**9:09d}")

    async with _client() as http:
        response = await http.get(PATH, headers=await _headers(org, role="staff"))

    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is True


# ------------------------------------------------------------------- hard rule 1


async def test_tenant_b_cannot_see_tenant_as_registration() -> None:
    """Cross-tenant zero rows, asserted at BOTH levels (hard rule 1).

    Through the endpoint, because that is the surface that ships; and on the raw
    RLS-scoped session, because an endpoint that filtered by `tenant_id` in Python
    would pass the first assertion while leaving the isolation to a WHERE clause
    someone can forget.
    """
    tenant_a = await _tenant()
    tenant_b = await _tenant()
    pe_id = f"1102{uuid.uuid4().int % 10**9:09d}"
    await _record(tenant_a, pe_id=pe_id)

    async with _client() as http:
        mine = await http.get(PATH, headers=await _headers(tenant_a))
        theirs = await http.get(PATH, headers=await _headers(tenant_b))

    # Ground truth from the owning tenant, so a policy that hid a tenant's OWN row
    # would fail here rather than passing as "isolated".
    assert mine.json()["pe_id"] == pe_id
    assert theirs.status_code == 200, theirs.text
    theirs_body = theirs.json()
    # Calevate's OWN telemarketer registration is platform-wide: the same two values reach
    # every tenant, and tenant B seeing them is not tenant B seeing tenant A. Asserted to
    # be identical on both responses, then dropped, so the equality below stays the strict
    # "nothing of this tenant's is here" assertion it exists to be.
    assert theirs_body["calevate_tm_id"] == mine.json()["calevate_tm_id"]
    assert theirs_body["calevate_tm_active"] == mine.json()["calevate_tm_active"]
    del theirs_body["calevate_tm_id"], theirs_body["calevate_tm_active"]
    assert theirs_body == {
        "recorded": False,
        "status": None,
        "tm_link_status": None,
        "pe_id": None,
        "entity_name": None,
        "registered_at": None,
        "verified_at": None,
        "is_active": False,
    }

    from apps.api.compliance.registration import read_pe_registration

    async with tenant_session(uuid.UUID(str(tenant_b["id"]))) as session:
        leaked = await read_pe_registration(session, tenant_id=uuid.UUID(str(tenant_a["id"])))
    assert leaked.recorded is False, "the RLS session must return zero rows for another tenant"
    assert leaked.pe_id is None

    async with untenanted_session() as session:
        blind = await read_pe_registration(session, tenant_id=uuid.UUID(str(tenant_a["id"])))
    assert blind.recorded is False, "no GUC ⇒ zero rows (fail closed)"


# --------------------------------------------------------------------- D-22 / RBAC


async def test_the_read_is_not_gated_on_a_permission_impersonation_refuses() -> None:
    """The rule `tests/impersonation_reads_test.py` asserts over the whole table,
    pinned here for this route: support looking at a client's blocked launch must be
    able to see the registration behind it."""
    declared = {
        route.path: (route.openapi_extra or {}).get("x-calevate-permission")
        for route in iter_api_routes(app)
        if route.methods == {"GET"} or route.methods == {"GET", "HEAD"}
    }
    assert declared.get(PATH) == "org:read", declared.get(PATH)
    assert "org:read" not in MUTATING_PERMISSIONS


async def test_there_is_still_no_client_route_that_writes_a_registration() -> None:
    """Adding a read must not have added a write. A client who could mark their own PE
    `active` would be marking the launch gate green on a registration that does not
    exist — the reason `record_dlt_registration` is admin-only."""
    writers = [
        (sorted(route.methods or []), route.path)
        for route in iter_api_routes(app)
        if route.path.endswith("dlt-registration")
        and not route.path.startswith("/v1/admin")
        and route.methods != {"GET"}
        and route.methods != {"GET", "HEAD"}
    ]
    assert writers == [], writers


# ------------------------------------------------------------------ the ops half


async def test_the_ops_surface_still_reads_back_the_tm_row() -> None:
    """INVESTIGATED, HOLDS: the operator read of Calevate's own TM registration already
    exists — `GET /v1/ops/platform` embeds it as `tm_registration`, written by
    `POST /v1/ops/platform/tm-registration` on the same router. Pinned rather than
    rebuilt: a second ops route returning the same row is how two surfaces start
    disagreeing about one fact.
    """
    token = await _make_admin()
    async with _client() as http:
        response = await http.get("/v1/ops/platform", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    tm = response.json()["tm_registration"]
    assert set(tm) == {"status", "tm_id", "registered_at", "verified_at", "is_live"}


async def test_the_client_is_told_calevates_own_telemarketer_id() -> None:
    """The client needs OUR registration number, and this is where they get it.

    The PE→TM authorisation is made BY THE CLIENT on the registrar's portal, and the
    portal asks for the telemarketer's registration number. Until 2 September 2026 the
    only place that number appeared was `/legal/acceptable-use`, as
    `{{DLT_TELEMARKETER_ID}}` in a public legal document — an operational identifier on
    the open web to serve the handful of people who need it. It rides on this response
    instead: behind a session, on the screen that asks for the authorisation.

    Read from `platform_state` on the tenant-scoped session, which is safe because that
    table carries no `tenant_id` and no RLS policy. Sourced from the ops console, never
    hard-coded — a fresh database says `not_registered` with no id, and the screen says
    there is nothing to authorise against rather than showing a blank.
    """
    org = await _tenant()

    async with untenanted_session() as session:
        before = (
            await session.execute(
                text("SELECT tm_registration_status, tm_id FROM platform_state WHERE id = 1")
            )
        ).first()
        await session.execute(
            text(
                "UPDATE platform_state SET tm_registration_status = 'active', "
                "tm_id = '1102000000000000001', tm_verified_at = now() WHERE id = 1"
            )
        )
        await session.commit()

    try:
        async with _client() as http:
            response = await http.get(PATH, headers=await _headers(org))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["calevate_tm_id"] == "1102000000000000001"
        assert body["calevate_tm_active"] is True
    finally:
        # The singleton is shared by every test in the session, so it goes back exactly
        # as it was rather than to a value this test believes is the default.
        assert before is not None, "platform_state singleton is missing — migrate first"
        async with untenanted_session() as session:
            await session.execute(
                text(
                    "UPDATE platform_state SET tm_registration_status = :st, tm_id = :tm "
                    "WHERE id = 1"
                ),
                {"st": before[0], "tm": before[1]},
            )
            await session.commit()


async def test_a_platform_with_no_telemarketer_registration_reports_it_as_absent() -> None:
    """The other half, and the reason the field is nullable rather than a string.

    `read_tm_registration` fails CLOSED on a missing row and reports `not_registered`
    with no id; the screen renders that as "there is nothing to authorise against yet"
    rather than as an empty value a client would read as a bug. Driven through the
    route's own projection rather than the endpoint, so it does not depend on what the
    shared `platform_state` singleton currently holds.
    """
    from apps.api.compliance.registration import PeRegistration
    from apps.api.compliance.registration_routes import _out
    from apps.api.ops.service import TmRegistration

    absent = PeRegistration(
        recorded=False,
        status=None,
        tm_link_status=None,
        pe_id=None,
        entity_name=None,
        registered_at=None,
        verified_at=None,
    )
    out = _out(
        absent,
        TmRegistration(status="not_registered", tm_id=None, registered_at=None, verified_at=None),
    )
    assert out.calevate_tm_id is None
    assert out.calevate_tm_active is False

    # `submitted` is not live either — an application in flight registers nobody — and a
    # screen reading the raw status would offer the number as though it authorised us.
    applied = _out(
        absent,
        TmRegistration(
            status="submitted", tm_id="1102000000000000001", registered_at=None, verified_at=None
        ),
    )
    assert applied.calevate_tm_id == "1102000000000000001"
    assert applied.calevate_tm_active is False
