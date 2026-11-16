"""Inbound lines and the picks of what the agents know, across accounts and at their bounds.

Hard rule 1's zero-rows test is only worth something when the owner's side holds a row: a
count of zero from a neighbour proves nothing about a table nobody wrote to.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from apps.api.campaigns import workspace
from apps.api.campaigns.workspace_rls_test import _campaign, _note
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from apps.api.kb import picks
from sqlalchemy import text
from tests.agent_lifecycle_test import _number

pytestmark = pytest.mark.rls


async def _account() -> tuple[UUID, UUID, UUID, UUID]:
    """A tenant, its agent, one of its campaigns and one source in What your agents know."""
    tenant_id, campaign_id = await _campaign()
    source_id = await _note(tenant_id, campaign_id, "Hours", "Open nine to six.")
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(
                text("SELECT agent_id FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
    return tenant_id, UUID(str(agent_id)), campaign_id, source_id


async def test_a_lines_picked_source_is_invisible_to_another_account() -> None:
    tenant_a, agent_a, _campaign_a, source_a = await _account()
    tenant_b, agent_b, _campaign_b, _source_b = await _account()
    async with tenant_session(tenant_a) as session:
        line_a = await lines.create_line(
            session, tenant_id=tenant_a, agent_id=agent_a, created_by=None
        )
        await lines.set_sources(
            session, tenant_id=tenant_a, line_id=line_a, kb_source_ids=[source_a], created_by=None
        )
        assert (await lines.read_line(session, line_a)).sources == (source_a,)
    async with tenant_session(tenant_b) as session:
        seen = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM inbound_lines), "
                    "(SELECT count(*) FROM inbound_line_sources)"
                )
            )
        ).one()
        assert tuple(seen) == (0, 0)
        line_b = await lines.create_line(
            session, tenant_id=tenant_b, agent_id=agent_b, created_by=None
        )
        with pytest.raises(ProblemError) as refused:
            await lines.set_sources(
                session,
                tenant_id=tenant_b,
                line_id=line_b,
                kb_source_ids=[source_a],
                created_by=None,
            )
    assert refused.value.status == 404


async def test_a_neighbours_number_cannot_be_put_on_ones_own_line() -> None:
    tenant_a, agent_a, _c, _s = await _account()
    tenant_b, agent_b, _c2, _s2 = await _account()
    number_a = await _number(tenant_a, agent_a, ref=f"num_idor_{agent_a.hex[:8]}")
    async with tenant_session(tenant_b) as session:
        line_b = await lines.create_line(
            session, tenant_id=tenant_b, agent_id=agent_b, created_by=None
        )
        with pytest.raises(ProblemError) as missing:
            await lines.assign_number(session, line_b, number_a)
    assert missing.value.status == 404
    async with tenant_session(tenant_a) as session:
        kept = (
            await session.execute(
                text("SELECT agent_id, inbound_line_id FROM phone_numbers WHERE id = :n"),
                {"n": number_a},
            )
        ).one()
    assert (kept.agent_id, kept.inbound_line_id) == (agent_a, None)


async def test_an_account_keeps_at_most_max_lines_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lines, "MAX_LINES", 2)
    tenant_id, agent_id, _c, _s = await _account()
    async with tenant_session(tenant_id) as session:
        first = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, created_by=None
        )
        await lines.create_line(session, tenant_id=tenant_id, agent_id=agent_id, created_by=None)
        with pytest.raises(ProblemError) as full:
            await lines.create_line(
                session, tenant_id=tenant_id, agent_id=agent_id, created_by=None
            )
        assert full.value.code == "inbound_lines_full"
        await session.execute(
            text("UPDATE inbound_lines SET archived_at = now() WHERE id = :l"), {"l": first}
        )
        # An archived line frees its place.
        await lines.create_line(session, tenant_id=tenant_id, agent_id=agent_id, created_by=None)
        assert len(await lines.list_lines(session)) == 2


async def test_adding_sources_one_at_a_time_stops_at_max_picks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a note, link or file added from the campaign page is picked past the bound
    `PUT .../sources` holds, so the campaign's source list grows without one."""
    monkeypatch.setattr(picks, "MAX_PICKS", 2)
    tenant_id, _agent, campaign_id, _first = await _account()
    await _note(tenant_id, campaign_id, "Prices", "Consultation is free.")
    with pytest.raises(ProblemError) as full:
        await _note(tenant_id, campaign_id, "Parking", "Park behind the building.")
    assert full.value.code == "sources_full"
    async with tenant_session(tenant_id) as session:
        held = await workspace.read_workspace(session, campaign_id)
        assert len(held.sources) == 2
        # Picking one already picked is still a no-op, not a refusal.
        await picks.add_pick(
            session,
            picks.CAMPAIGN_PICKS,
            tenant_id=tenant_id,
            holder_id=campaign_id,
            kb_source_id=held.sources[0],
            created_by=None,
        )
