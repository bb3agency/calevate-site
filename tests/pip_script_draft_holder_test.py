"""Pip's script draft goes to the line or campaign named, whatever agent id comes with it.

The founder's request of 24 Nov 2026 ("Rewrite this campaign's whole call script") was
refused three times with "That Inbound line or campaign does not use this agent": Pip named
the right campaign but the account's other agent, and the draft never started.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.copilot.script_actions import _draft_holder, _DraftArgs
from apps.api.db.session import tenant_session
from tests.agent_lifecycle_test import _tenant
from tests.notes_per_job_test import _campaign

pytestmark = pytest.mark.rls


async def test_the_named_campaign_decides_the_agent_even_beside_another_agents_id() -> None:
    tenant_id, agent_id, _ = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    other_agent = uuid.uuid4()

    async with tenant_session(tenant_id) as session:
        holder = await _draft_holder(
            session, _DraftArgs(agent_id=other_agent, holder_id=campaign_id)
        )

    assert (holder.kind, holder.id, holder.agent_id) == ("campaign", campaign_id, agent_id)


async def test_the_named_campaign_alone_is_enough() -> None:
    tenant_id, agent_id, _ = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        holder = await _draft_holder(session, _DraftArgs(holder_id=campaign_id))

    assert holder.agent_id == agent_id
