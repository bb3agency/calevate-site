"""Cross-tenant zero rows on the two handover tables (hard rule 1, migration c4a91e60d7b3).

Both carry `tenant_id` and the FORCEd `tenant_isolation` policy, and both hold the kind of
row this rule exists for: `agent_handoff_members` is a list of a client's own staff on
their own personal mobiles, and `handoff_attempts` names one of their callers'
conversations and the number that rang because of it. A leak here is one business reading
another's staff directory.

SHARED DATABASE DISCIPLINE: two organisations minted by this module, every assertion scoped
to their own ids, and nothing counts rows globally.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from apps.api.admin import service as admin_service
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from sqlalchemy import text
from tests.conftest import accept_agreements

pytestmark = pytest.mark.asyncio


async def _org() -> tuple[uuid.UUID, uuid.UUID]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Handoff RLS",
        slug=f"handoff-rls-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    return tenant_id, uuid.UUID(str(created["agent_id"]))


async def _plant(tenant_id: uuid.UUID, agent_id: uuid.UUID, phone: str) -> uuid.UUID:
    """A real roster member and a real handover attempt, so "zero rows" below is a refusal
    rather than an empty table."""
    member_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agent_handoff_members "
                "(id, tenant_id, agent_id, position, label, phone_e164) "
                "VALUES (:id, :tid, :aid, 0, 'Owner', :phone)"
            ),
            {"id": member_id, "tid": tenant_id, "aid": agent_id, "phone": phone},
        )
        await session.execute(
            text(
                "INSERT INTO handoff_attempts (id, tenant_id, agent_id, source_execution_id, "
                "  member_id, destination_e164, started_at) "
                "VALUES (:id, :tid, :aid, :ex, :mid, :phone, :now)"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "ex": f"exec-{uuid.uuid4().hex[:10]}",
                "mid": member_id,
                "phone": phone,
                "now": datetime.now(UTC),
            },
        )
    return member_id


async def test_one_tenant_sees_none_of_anothers_handover_rows() -> None:
    """The clause hard rule 1 asks for, on both tables, in both directions."""
    first_tenant, first_agent = await _org()
    second_tenant, second_agent = await _org()
    await _plant(first_tenant, first_agent, "+919000000101")
    await _plant(second_tenant, second_agent, "+919000000202")

    for tenant_id, own_agent, other_agent in (
        (first_tenant, first_agent, second_agent),
        (second_tenant, second_agent, first_agent),
    ):
        async with tenant_session(tenant_id) as session:
            for table in ("agent_handoff_members", "handoff_attempts"):
                own = (
                    await session.execute(
                        text(f"SELECT count(*) FROM {table} WHERE agent_id = :aid"),
                        {"aid": own_agent},
                    )
                ).scalar()
                assert own == 1, f"{table}: a tenant cannot see its own row"
                theirs = (
                    await session.execute(
                        text(f"SELECT count(*) FROM {table} WHERE agent_id = :aid"),
                        {"aid": other_agent},
                    )
                ).scalar()
                assert theirs == 0, (
                    f"{table}: this tenant can read another business's handover rows — "
                    "their staff's personal mobiles, and which of their callers was "
                    "escalated"
                )


async def test_a_neighbours_row_cannot_be_written_over_either() -> None:
    """RLS is not only a read control. `tenant_isolation` has no `WITH CHECK`, so it
    applies to writes through the USING clause: a session scoped to one tenant matches
    zero of another's rows and the UPDATE affects nothing.

    Asserted because the read clause alone would pass on a policy that let a neighbour
    REDIRECT a handover destination — which is worse than reading one.
    """
    first_tenant, first_agent = await _org()
    second_tenant, second_agent = await _org()
    victim = await _plant(first_tenant, first_agent, "+919000000303")
    await _plant(second_tenant, second_agent, "+919000000404")

    async with tenant_session(second_tenant) as session:
        result = await session.execute(
            text(
                "UPDATE agent_handoff_members SET phone_e164 = '+919999999999' WHERE id = :id"
            ),
            {"id": victim},
        )
        assert result.rowcount == 0, "a neighbour rewrote a handover destination"

    async with tenant_session(first_tenant) as session:
        held = (
            await session.execute(
                text("SELECT phone_e164 FROM agent_handoff_members WHERE id = :id"),
                {"id": victim},
            )
        ).scalar()
    assert held == "+919000000303"
