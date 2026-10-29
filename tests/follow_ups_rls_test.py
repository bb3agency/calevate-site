"""Follow-ups' tables under hard rules 1 and 4 (D-940): one account sees none of another's
rows, an untenanted session sees none at all, and the two ledgers refuse an edit."""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.callback_dispatch_test import _dialable_tenant
from tests.follow_ups_support import publish

TABLES = ("follow_ups", "follow_up_versions", "follow_up_runs", "follow_up_run_events")


async def _with_a_run() -> tuple[UUID, UUID]:
    tenant_id, agent_id = await _dialable_tenant()
    follow_up_id = await publish(tenant_id, steps=[{"id": "s1", "kind": "wait", "days": 1}])
    from apps.api.follow_ups import service

    lead_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, "
                "created_at, updated_at) VALUES (:i, :t, :a, '+919812300001', 'webhook', 'new', "
                "now(), now())"
            ),
            {"i": lead_id, "t": tenant_id, "a": agent_id},
        )
        await service.start_leads(session, follow_up_id, tenant_id=tenant_id, lead_ids=[lead_id])
    return tenant_id, follow_up_id


async def test_another_account_and_no_account_see_zero_rows() -> None:
    owner, _follow_up = await _with_a_run()
    other, _ = await _dialable_tenant()
    for table in TABLES:
        async with tenant_session(owner) as session:
            mine = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
        async with tenant_session(other) as session:
            theirs = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": owner}
                )
            ).scalar_one()
        async with untenanted_session() as session:
            nobody = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
        assert mine >= 1, f"{table}: the owner's rows exist"
        assert theirs == 0, f"{table}: another account sees {theirs} of the owner's rows"
        assert nobody == 0, f"{table}: an untenanted session sees {nobody} rows"


@pytest.mark.parametrize("table", ["follow_up_versions", "follow_up_run_events"])
async def test_a_version_and_an_event_cannot_be_changed_or_deleted(table: str) -> None:
    owner, _follow_up = await _with_a_run()
    for statement in (
        f"UPDATE {table} SET tenant_id = tenant_id",
        f"DELETE FROM {table}",
    ):
        with pytest.raises(DBAPIError):
            async with tenant_session(owner) as session:
                await session.execute(text(statement))
