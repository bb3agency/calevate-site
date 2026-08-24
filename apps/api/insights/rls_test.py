"""Cross-tenant isolation for the knowledge-gap tables (hard rule 1).

The mandatory zero-rows test: a gap written under tenant A must be invisible to tenant B —
through the service AND through a raw select, because the guarantee is the FORCEd
`tenant_isolation` policy, not the query.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from apps.api.admin import service as admin_service
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.insights import service
from apps.api.insights.detection import RedactedTurn

pytestmark = pytest.mark.rls


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="RLS Gaps",
        slug=f"rlsgap-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def test_a_tenant_cannot_see_another_tenants_knowledge_gaps() -> None:
    tenant_a, agent_a = await _tenant()
    tenant_b, _agent_b = await _tenant()

    call_id = uuid7()
    async with tenant_session(tenant_a) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) VALUES (:id, :t, :a, :ecid, 'inbound', "
                "'completed', :at, now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_a,
                "a": agent_a,
                "ecid": f"rls-{uuid.uuid4().hex}",
                "at": datetime.now(UTC),
            },
        )
    await service.record_call_gaps(
        tenant_id=tenant_a,
        agent_id=agent_a,
        call_id=call_id,
        turns=[
            RedactedTurn(speaker="caller", text="How much is the fee?"),
            RedactedTurn(speaker="agent", text="I don't know the price."),
        ],
    )

    # Tenant A sees its own gap.
    async with tenant_session(tenant_a) as session:
        assert (await service.list_gaps(session, status=None)).total == 1

    # Tenant B sees nothing — through the service and through a raw select.
    async with tenant_session(tenant_b) as session:
        assert (await service.list_gaps(session, status=None)).total == 0
        agg = (await session.execute(text("SELECT count(*) FROM knowledge_gaps"))).scalar()
        occ = (
            await session.execute(text("SELECT count(*) FROM knowledge_gap_occurrences"))
        ).scalar()
    assert agg == 0
    assert occ == 0
