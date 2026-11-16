"""Cross-tenant isolation for `campaign_sources` (hard rule 1), and the workspace's rules.

The mandatory zero-rows test: a pick written under tenant A is invisible to tenant B, through
the service and through a raw select, because the guarantee is the FORCEd `tenant_isolation`
policy, not the query.
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
        name="RLS Campaign Sources",
        slug=f"rlscs-{uuid.uuid4().hex[:8]}",
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


async def _note(tenant: uuid.UUID, campaign: uuid.UUID, title: str, words: str) -> uuid.UUID:
    async with tenant_session(tenant) as session:
        return await workspace.add_note(
            session,
            tenant_id=tenant,
            campaign_id=campaign,
            title=title,
            note=words,
            created_by=None,
            auto_approve=True,
        )


async def test_a_tenant_cannot_see_another_tenants_campaign_sources() -> None:
    tenant_a, campaign_a = await _campaign()
    tenant_b, campaign_b = await _campaign()
    source_a = await _note(tenant_a, campaign_a, "Price", "The app is free.")
    async with tenant_session(tenant_a) as session:
        assert (await workspace.read_workspace(session, campaign_a)).sources == (source_a,)

    async with tenant_session(tenant_b) as session:
        with pytest.raises(ProblemError) as missing:
            await workspace.read_workspace(session, campaign_a)
        assert missing.value.status == 404
        rows = (await session.execute(text("SELECT count(*) FROM campaign_sources"))).scalar()
        assert rows == 0
        # Another account's source is refused as missing, never picked.
        with pytest.raises(ProblemError) as refused:
            await workspace.set_sources(
                session,
                tenant_id=tenant_b,
                campaign_id=campaign_b,
                kb_source_ids=[source_a],
                created_by=None,
            )
    assert refused.value.status == 404


async def test_a_note_goes_into_the_knowledge_under_a_free_name_and_is_picked() -> None:
    """FAILS IF: a note written on the campaign page stays the campaign's own, or takes the
    name of an item already in the knowledge and so becomes its next version."""
    tenant, campaign = await _campaign()
    first = await _note(tenant, campaign, "Offer", "First month free.")
    second = await _note(tenant, campaign, "Offer", "Second month half price.")
    async with tenant_session(tenant) as session:
        rows = (
            await session.execute(
                text("SELECT id, name FROM kb_sources WHERE id = ANY(:ids)"),
                {"ids": [first, second]},
            )
        ).all()
        names = {row.id: row.name for row in rows}
        space = await workspace.read_workspace(session, campaign)
    assert names == {first: "Offer", second: "Offer (2)"}
    assert space.sources == (first, second)


async def test_picks_replace_the_last_choice_and_leave_the_knowledge_alone() -> None:
    tenant, campaign = await _campaign()
    first = await _note(tenant, campaign, "Hours", "Open nine to five.")
    second = await _note(tenant, campaign, "Parking", "Free parking at the back.")
    async with tenant_session(tenant) as session:
        await workspace.set_sources(
            session, tenant_id=tenant, campaign_id=campaign, kb_source_ids=[second], created_by=None
        )
        assert (await workspace.read_workspace(session, campaign)).sources == (second,)
        # Unpicking leaves the note in the knowledge: the campaign only points at it.
        await workspace.set_sources(
            session, tenant_id=tenant, campaign_id=campaign, kb_source_ids=[], created_by=None
        )
        kept = (
            await session.execute(
                text("SELECT count(*) FROM kb_sources WHERE id = ANY(:ids)"),
                {"ids": [first, second]},
            )
        ).scalar()
    assert kept == 2


async def test_main_task_is_kept_and_an_empty_note_is_refused() -> None:
    tenant, campaign = await _campaign()
    async with tenant_session(tenant) as session:
        assert await workspace.save_main_task(
            session, campaign, "  Help them install the app.  "
        ) == ("Help them install the app.")
        with pytest.raises(ProblemError) as refused:
            await workspace.add_note(
                session,
                tenant_id=tenant,
                campaign_id=campaign,
                title="Empty",
                note="   ",
                created_by=None,
                auto_approve=True,
            )
    assert refused.value.code == "note_required"


async def test_pip_needs_a_main_task_first() -> None:
    tenant, campaign = await _campaign()
    async with tenant_session(tenant) as session:
        with pytest.raises(ProblemError) as refused:
            await workspace.request_proposal(
                session, tenant_id=tenant, campaign_id=campaign, requested_by=None
            )
    assert refused.value.code == "main_task_required"
