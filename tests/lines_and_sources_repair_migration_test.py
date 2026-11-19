"""`bd9b4b153d5a` re-runs the Inbound-line and campaign-source backfills, proved under an
owner role that row-level security binds the way it binds production's.

`d8b2f5a7c3e1` and `e3c7a1d9b4f2` listed tenants from `organizations` before setting one, so
under a NOSUPERUSER owner the list was empty and neither ran. `rls_bound_owner()` is that
owner; each test is one transaction, always rolled back.
"""

from __future__ import annotations

import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import Connection, text
from tests.call_notices_holders_test import _campaign
from tests.call_notices_repair_migration_test import load_revision, rls_bound_owner
from tests.conftest import create_org_with_receptionist
from tests.dispatch_budget_test import _tenant as _outbound_tenant

pytestmark = pytest.mark.anyio

REPAIR = "bd9b4b153d5a_lines_and_campaign_sources_under_rls"
SOURCES = "e3c7a1d9b4f2_campaign_sources"


def _run_repair(connection: Connection) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        load_revision(REPAIR).upgrade()
    connection.execute(text("RESET ROLE"))


async def _number(tenant_id: uuid.UUID, agent_id: uuid.UUID, direction: str) -> uuid.UUID:
    number_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, direction, "
                "created_at, updated_at) VALUES (:id, :t, :a, :e, '160', :d, now(), now())"
            ),
            {
                "id": number_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"+91160{uuid.uuid4().int % 10_000_000:07d}",
                "d": direction,
            },
        )
    return number_id


async def _note(tenant_id: uuid.UUID, campaign_id: uuid.UUID, title: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaign_materials (id, tenant_id, campaign_id, kind, title, note) "
                "VALUES (:id, :t, :c, 'note', :title, 'Bring the price list to the visit.')"
            ),
            {"id": uuid7(), "t": tenant_id, "c": campaign_id, "title": title},
        )


def _line_of(connection: Connection, number_id: uuid.UUID) -> uuid.UUID | None:
    found: uuid.UUID | None = connection.execute(
        text("SELECT inbound_line_id FROM phone_numbers WHERE id = :n"), {"n": number_id}
    ).scalar_one()
    return found


def _picks(connection: Connection, campaign_id: uuid.UUID) -> list[str]:
    return list(
        connection.execute(
            text(
                "SELECT k.name FROM campaign_sources s JOIN kb_sources k ON k.id = s.kb_source_id "
                "WHERE s.campaign_id = :c ORDER BY k.name"
            ),
            {"c": campaign_id},
        ).scalars()
    )


async def test_an_answering_number_gets_a_line_and_a_caller_number_does_not() -> None:
    """FAILS IF: the repair misses an answering number under an RLS-bound owner, or puts an
    outbound-only number on a line, which would make that line answer it."""
    created = await create_org_with_receptionist(
        name="Repair Lines",
        slug=f"rl-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'both' WHERE id = :a"), {"a": agent_id}
        )
    answering = await _number(tenant_id, agent_id, "both")
    caller = await _number(tenant_id, agent_id, "outbound")
    outbound_tenant, outbound_agent = await _outbound_tenant()
    on_outbound_agent = await _number(outbound_tenant, outbound_agent, "both")
    with rls_bound_owner() as (connection, become):
        become()
        _run_repair(connection)
        line_id = _line_of(connection, answering)
        assert line_id is not None
        assert (
            connection.execute(
                text("SELECT agent_id FROM inbound_lines WHERE id = :l"), {"l": line_id}
            ).scalar_one()
            == agent_id
        )
        assert _line_of(connection, caller) is None
        assert _line_of(connection, on_outbound_agent) is None


async def test_unpicked_campaigns_get_their_notes_and_a_picked_one_is_left_alone() -> None:
    """FAILS IF: the repair carries nothing under an RLS-bound owner, or makes a second note
    for a campaign that already has picks."""
    tenant_id, agent_id = await _outbound_tenant()
    unpicked = await _campaign(tenant_id, agent_id)
    await _note(tenant_id, unpicked, "Visit checklist")
    other_tenant, other_agent = await _outbound_tenant()
    picked = await _campaign(other_tenant, other_agent)
    await _note(other_tenant, picked, "Visit checklist")
    kept = uuid7()
    async with tenant_session(other_tenant) as session:
        await session.execute(
            text(
                "INSERT INTO kb_sources (id, tenant_id, kind, name, status, version, is_active, "
                "created_at, updated_at) VALUES (:i, :t, 'text', 'Owner pick', 'approved', 1, "
                "true, now(), now())"
            ),
            {"i": kept, "t": other_tenant},
        )
        await session.execute(
            text(
                "INSERT INTO campaign_sources (id, tenant_id, campaign_id, kb_source_id) "
                "VALUES (:id, :t, :c, :s)"
            ),
            {"id": uuid7(), "t": other_tenant, "c": picked, "s": kept},
        )
    with rls_bound_owner() as (connection, become):
        become()
        _run_repair(connection)
        assert _picks(connection, unpicked) == ["Visit checklist"]
        assert _picks(connection, picked) == ["Owner pick"]


async def test_the_shipped_walk_listed_no_tenant_under_an_rls_bound_owner() -> None:
    """FAILS IF: this harness stops being bound by RLS, which would make the tests above pass
    the way `e3c7a1d9b4f2`'s own did."""
    tenant_id, agent_id = await _outbound_tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    await _note(tenant_id, campaign_id, "Visit checklist")
    shipped = load_revision(SOURCES)
    with rls_bound_owner() as (connection, become):
        become()
        with Operations.context(MigrationContext.configure(connection)):
            shipped._backfill()
        connection.execute(text("RESET ROLE"))
        assert _picks(connection, campaign_id) == []
