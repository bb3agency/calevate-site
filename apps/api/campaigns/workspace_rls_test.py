"""Cross-tenant isolation for `campaign_materials` (hard rule 1), and the workspace's rules.

The mandatory zero-rows test: a material written under tenant A is invisible to tenant B,
through the service and through a raw select, because the guarantee is the FORCEd
`tenant_isolation` policy, not the query.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

from apps.api.campaigns import workspace
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session

pytestmark = pytest.mark.rls


async def _campaign() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="RLS Campaign Materials",
        slug=f"rlscm-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    campaign_id = uuid7()
    async with tenant_session(created["id"]) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification) "
                "VALUES (:id, :t, :a, 'Install the app', 'service')"
            ),
            {"id": campaign_id, "t": created["id"], "a": created["agent_id"]},
        )
    return created["id"], campaign_id


async def test_a_tenant_cannot_see_another_tenants_campaign_materials() -> None:
    tenant_a, campaign_a = await _campaign()
    tenant_b, _ = await _campaign()

    async with tenant_session(tenant_a) as session:
        await workspace.add_material(
            session,
            tenant_id=tenant_a,
            campaign_id=campaign_a,
            kind="note",
            title="Price",
            url=None,
            note="The app is free.",
            kb_upload_id=None,
            created_by=None,
        )
        assert len(await workspace.list_materials(session, campaign_a)) == 1

    async with tenant_session(tenant_b) as session:
        assert await workspace.list_materials(session, campaign_a) == []
        rows = (await session.execute(text("SELECT count(*) FROM campaign_materials"))).scalar()
    assert rows == 0


async def test_main_task_is_kept_and_a_removed_material_is_archived_not_deleted() -> None:
    tenant, campaign = await _campaign()
    async with tenant_session(tenant) as session:
        assert await workspace.save_main_task(
            session, campaign, "  Help them install the app.  "
        ) == ("Help them install the app.")
        material = await workspace.add_material(
            session,
            tenant_id=tenant,
            campaign_id=campaign,
            kind="link",
            title="Website",
            url="https://example.com",
            note=None,
            kb_upload_id=None,
            created_by=None,
        )
        await workspace.archive_material(session, campaign, material.id)
        assert await workspace.list_materials(session, campaign) == []
        kept = (
            await session.execute(
                text("SELECT archived_at IS NOT NULL FROM campaign_materials WHERE id = :m"),
                {"m": material.id},
            )
        ).scalar()
    assert kept is True


async def test_pip_needs_a_main_task_first() -> None:
    tenant, campaign = await _campaign()
    async with tenant_session(tenant) as session:
        with pytest.raises(ProblemError) as refused:
            await workspace.request_proposal(
                session, tenant_id=tenant, campaign_id=campaign, requested_by=None
            )
    assert refused.value.code == "main_task_required"
