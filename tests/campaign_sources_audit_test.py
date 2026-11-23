"""A campaign's sources from What your agents know (D-999): how a pick resolves, how many a
campaign may hold, and what Pip reads of a source picked before it is live.

SHARED DATABASE DISCIPLINE: every organisation is minted here and every assertion is scoped
to its own ids.
"""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from apps.api.campaigns import workspace
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.kb import picks
from apps.workers.company_training_draft import knowledge_words
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import create_org_with_receptionist

pytestmark = pytest.mark.rls


async def _campaign() -> tuple[UUID, UUID]:
    created = await create_org_with_receptionist(
        name="Sunrise Homes",
        slug=f"cps-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="en-IN",
        created_by=None,
    )
    tenant_id, campaign_id = UUID(str(created["id"])), uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification) "
                "VALUES (:id, :t, :a, 'Install the app', 'service')"
            ),
            {"id": campaign_id, "t": tenant_id, "a": created["agent_id"]},
        )
    return tenant_id, campaign_id


async def _source(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    name: str,
    kind: str = "text",
    version: int = 1,
    status: str = "approved",
    active: bool = True,
    words: str = "",
) -> UUID:
    source_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO kb_sources (id, tenant_id, kind, name, status, version, is_active, "
            "created_at, updated_at) VALUES (:i, :t, :k, :n, :s, :v, :a, now(), now())"
        ),
        {
            "i": source_id,
            "t": tenant_id,
            "k": kind,
            "n": name,
            "s": status,
            "v": version,
            "a": active,
        },
    )
    if words:
        await session.execute(
            text(
                "INSERT INTO kb_documents (id, tenant_id, source_id, idx, content, created_at, "
                "updated_at) VALUES (:id, :t, :s, 0, :w, now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "s": source_id, "w": words},
        )
    return source_id


async def test_a_picked_note_follows_its_newest_version_and_a_file_keeps_its_own_row() -> None:
    tenant_id, campaign_id = await _campaign()
    async with tenant_session(tenant_id) as session:
        file_id = await _source(session, tenant_id, name="Price list", kind="file")
        # A typed note given the same name as the file, as the knowledge page allows.
        await _source(session, tenant_id, name="Price list", version=2)
        note_v1 = await _source(session, tenant_id, name="Offer")
        note_v2 = await _source(session, tenant_id, name="Offer", version=2)
        await workspace.set_sources(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            kb_source_ids=[file_id, note_v1],
            created_by=None,
        )
        found = await picks.read_picks(session, picks.CAMPAIGN_PICKS, [campaign_id])
    assert found[campaign_id] == [file_id, note_v2]


async def test_one_pick_past_the_bound_is_refused_and_a_repeat_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(picks, "MAX_PICKS", 2)
    tenant_id, campaign_id = await _campaign()
    async with tenant_session(tenant_id) as session:
        first, second, third = [
            await _source(session, tenant_id, name=f"Note {n}") for n in range(3)
        ]
        for source_id in (first, second, second):
            await workspace.pick_source(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                kb_source_id=source_id,
                created_by=None,
            )
        with pytest.raises(ProblemError) as refused:
            await workspace.pick_source(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                kb_source_id=third,
                created_by=None,
            )
        found = await picks.read_picks(session, picks.CAMPAIGN_PICKS, [campaign_id])
    assert refused.value.code == "sources_full"
    assert found[campaign_id] == [first, second]


async def test_pip_reads_a_picked_note_that_is_approved_but_not_yet_live() -> None:
    tenant_id, _campaign_id = await _campaign()
    async with tenant_session(tenant_id) as session:
        publishing = await _source(
            session, tenant_id, name="Just added", active=False, words="Free first month."
        )
        in_review = await _source(
            session,
            tenant_id,
            name="Waiting",
            status="pending_approval",
            active=False,
            words="Not reviewed yet.",
        )
        removed = await _source(
            session, tenant_id, name="Gone", status="archived", active=False, words="Old."
        )
        picked = await knowledge_words(session, only=[publishing, in_review, removed])
        everything = await knowledge_words(session)
    assert picked == [("Just added", "Free first month.")]
    # What every agent uses is still only what is live.
    assert "Just added" not in dict(everything)


async def test_a_picked_file_that_was_replaced_reads_as_its_live_version_once() -> None:
    tenant_id, campaign_id = await _campaign()
    async with tenant_session(tenant_id) as session:
        old = await _source(
            session, tenant_id, name="Guide.md", kind="file", status="archived", active=False
        )
        live = await _source(session, tenant_id, name="Guide.md", kind="file", version=2)
        await workspace.set_sources(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            kb_source_ids=[old, live],
            created_by=None,
        )
        found = await picks.read_picks(session, picks.CAMPAIGN_PICKS, [campaign_id])
    assert found[campaign_id] == [live]


async def test_a_link_named_like_an_item_already_known_is_its_own_item() -> None:
    """A link added from the campaign page under a name the knowledge already uses gets a
    free name ("Name (2)"), as a note does: taken as given it would be that item's next
    version, and publishing it would replace the item for every agent."""
    tenant_id, campaign_id = await _campaign()
    async with tenant_session(tenant_id) as session:
        price_list = await _source(session, tenant_id, name="Price list", kind="file")
        source_id, _upload_id = await workspace.add_link(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            url="https://example.com/prices",
            name="Price list",
            created_by=None,
            auto_approve=True,
        )
        row = (
            await session.execute(
                text("SELECT name, version FROM kb_sources WHERE id = :s"), {"s": source_id}
            )
        ).one()
        found = await picks.read_picks(session, picks.CAMPAIGN_PICKS, [campaign_id])
        await session.rollback()
    assert (row.name, row.version) == ("Price list (2)", 1)
    assert found[campaign_id] == [source_id]
    assert source_id != price_list
