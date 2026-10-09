"""The operator's list of unfinished onboardings (D-695).

The operator's part of onboarding is creating the account and inviting the owner; the
client fills in the business profile. An account is unfinished while nobody has accepted
an invitation, or while the profile still lacks what an agent needs to go live, and the
row says which.

Concurrency: every case creates its own run-unique tenant and looks only for it.
"""

from __future__ import annotations

import uuid

from apps.api.admin import service as admin_service
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import seed_business_profile

UNFINISHED_PATH = "/v1/admin/onboarding/unfinished"


async def _tenant() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Sunrise Dental",
        slug=f"unfin-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


async def _owner(tenant_id: uuid.UUID) -> None:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :e, now(), now())"
            ),
            {"id": user_id, "e": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )


async def _operator_headers() -> dict[str, str]:
    admin_id = uuid.uuid4()
    async with admin_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
    return {"Authorization": f"Bearer dev:admin:{admin_id}"}


async def _row(tenant_id: uuid.UUID) -> dict[str, object] | None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        listed = await http.get(UNFINISHED_PATH, headers=await _operator_headers())
    assert listed.status_code == 200, listed.text
    return next((row for row in listed.json() if row["tenant_id"] == str(tenant_id)), None)


async def test_a_new_account_is_unfinished_with_every_blocker_and_no_owner() -> None:
    tenant_id = await _tenant()
    row = await _row(tenant_id)
    assert row is not None
    assert row["owner_present"] is False
    assert row["steps_done"] == 0
    assert row["steps_total"] == 8
    assert set(row["blockers"]) == {  # type: ignore[arg-type]
        "business_hours_missing",
        "branch_missing",
        "service_missing",
        "escalation_contact_missing",
    }
    # The account, never anyone at it: no phone number, no answers, no email.
    assert set(row) == {
        "tenant_id",
        "name",
        "slug",
        "created_at",
        "vertical_template",
        "owner_present",
        "steps_done",
        "steps_total",
        "blockers",
        "profile_saved_at",
        "invite_pending",
    }


async def test_an_owner_without_a_ready_profile_is_still_unfinished() -> None:
    tenant_id = await _tenant()
    await _owner(tenant_id)
    row = await _row(tenant_id)
    assert row is not None and row["owner_present"] is True and row["blockers"]


async def test_a_profile_without_an_owner_is_still_unfinished() -> None:
    tenant_id = await _tenant()
    await seed_business_profile(tenant_id)
    row = await _row(tenant_id)
    assert row is not None and row["owner_present"] is False and row["blockers"] == []


async def test_an_owner_and_a_ready_profile_leave_the_list() -> None:
    tenant_id = await _tenant()
    await _owner(tenant_id)
    await seed_business_profile(tenant_id)
    assert await _row(tenant_id) is None
