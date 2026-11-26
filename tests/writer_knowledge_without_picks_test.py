"""A campaign or line with no sources picked is written from everything the agents know.

The founder's Rytu Khata campaign (24 Nov 2026) had its business described in a knowledge
document, and Pip's scripts read none of it: with no sources picked, the writer was handed an
empty knowledge list, while the live call carried every source (D-689).
"""

from __future__ import annotations

from uuid import UUID

import pytest
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from apps.workers import script_context
from sqlalchemy import text
from tests.campaign_sources_audit_test import _campaign, _source

pytestmark = pytest.mark.rls

ABOUT = "The app has a Dashboard, My Farms, Expenses and Sales."


async def _with_knowledge() -> tuple[UUID, UUID]:
    tenant_id, campaign_id = await _campaign()
    async with tenant_session(tenant_id) as session:
        await _source(session, tenant_id, name="About the app", words=ABOUT)
    return tenant_id, campaign_id


async def test_a_campaign_with_no_sources_picked_is_written_from_all_knowledge() -> None:
    tenant_id, campaign_id = await _with_knowledge()

    inputs = await script_context.holder_context(tenant_id, "campaign", campaign_id)

    assert ("About the app", ABOUT) in inputs.words


async def test_a_line_with_no_sources_picked_is_written_from_all_knowledge() -> None:
    tenant_id, campaign_id = await _with_knowledge()
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(
                text("SELECT agent_id FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
        line_id = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, main_task="Answer", created_by=None
        )
        await session.execute(
            text("DELETE FROM inbound_line_sources WHERE inbound_line_id = :l"), {"l": line_id}
        )

    inputs = await script_context.holder_context(tenant_id, "line", line_id)

    assert ("About the app", ABOUT) in inputs.words


async def test_an_older_approved_version_beside_the_live_one_is_read_once() -> None:
    """Production, 24 Nov 2026: a guide's version 1 stayed approved beside its live version
    2, both were picked, and both were read, halving every other source's share."""
    from apps.workers.company_training_draft import knowledge_words

    tenant_id, _campaign_id = await _campaign()
    async with tenant_session(tenant_id) as session:
        old = await _source(
            session, tenant_id, name="Guide.md", kind="file", active=False, words="Old guide."
        )
        live = await _source(
            session, tenant_id, name="Guide.md", kind="file", version=2, words="Live guide."
        )
        picked = await knowledge_words(session, only=[old, live])
        everything = await knowledge_words(session)
    assert picked == [("Guide.md", "Live guide.")]
    assert everything == [("Guide.md", "Live guide.")]


def test_a_whole_manual_fits_beside_other_sources_in_the_writers_budget() -> None:
    from apps.api.first_run.models import KNOWLEDGE_DOCUMENT_CHARS
    from apps.workers.first_run import documents_block

    manual = "Step. " * 3400 + "Press Dashboard to see the totals."
    others = [(f"Note {i}", "A short note. " * 70) for i in range(4)]
    block = documents_block(
        [("Operation manual", manual), *others], budget=KNOWLEDGE_DOCUMENT_CHARS
    )
    assert "Press Dashboard to see the totals." in block
