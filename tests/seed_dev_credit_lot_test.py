"""The seeded wallet's opening credit sits on a credit lot (e2e audit L3-15, seed half).

Every credit screen reads minutes from the lots and the balance from the ledger; a seed that
wrote only the ledger row showed "₹5,000" beside "0 minutes" everywhere.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from apps.api.billing.lots import read_open_lots
from apps.api.billing.service import find_entry_by_ref, record_entry
from apps.api.db.session import tenant_session
from scripts import seed_dev
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist


async def _tenant() -> uuid.UUID:
    created = await create_org_with_receptionist(
        name="Seed Lot Shop",
        slug=f"seedlot-{uuid.uuid4().hex[:8]}",
        vertical_template="custom",
        billing_email=None,
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


async def _lot_total(tenant_id: uuid.UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        lots = await read_open_lots(session, tenant_id=tenant_id)
    return sum((lot.credits_remaining for lot in lots), Decimal("0"))


async def test_the_opening_credit_opens_its_lot_once() -> None:
    tenant_id = await _tenant()
    assert await seed_dev._ensure_opening_credit(tenant_id) == seed_dev.SEED_OPENING_CREDIT_INR
    assert await seed_dev._ensure_opening_credit(tenant_id) == seed_dev.SEED_OPENING_CREDIT_INR
    assert await _lot_total(tenant_id) == seed_dev.SEED_OPENING_CREDIT_INR


async def test_a_database_seeded_without_a_lot_gets_one_on_the_next_run() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=seed_dev.SEED_OPENING_CREDIT_INR,
            reason="topup",
            ref=seed_dev.SEED_CREDIT_REF,
        )
        assert await find_entry_by_ref(
            session, tenant_id=tenant_id, reason="topup", ref=seed_dev.SEED_CREDIT_REF
        )
    assert await _lot_total(tenant_id) == Decimal("0")

    await seed_dev._ensure_opening_credit(tenant_id)

    assert await _lot_total(tenant_id) == seed_dev.SEED_OPENING_CREDIT_INR


async def test_every_seeded_call_is_on_its_leads_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L3-26: the seed writes the `call` lead event the pipeline writes, so a seeded lead's
    History is never "Nothing has happened yet" beside a call."""
    # `engine_call_id` is globally unique; a prefix of this run's own keeps a database that
    # was seeded before from swallowing the inserts.
    monkeypatch.setattr(seed_dev, "SEED_CALL_PREFIX", f"seed-test-{uuid.uuid4().hex[:8]}-")
    tenant_id = await _tenant()
    agent_id = await seed_dev._tenant_agent(tenant_id)
    owner = await seed_dev._upsert_user(
        email=f"seed-{uuid.uuid4().hex[:8]}@example.com", name="Seed Owner"
    )
    written = await seed_dev._seed_calls(
        tenant_id=tenant_id, agent_id=agent_id, owner_user_id=owner
    )
    assert written == len(seed_dev.DEMO_CALLS)

    async with tenant_session(tenant_id) as session:
        missing = (
            await session.execute(
                text(
                    "SELECT count(*) FROM calls c WHERE NOT EXISTS (SELECT 1 FROM lead_events e "
                    "WHERE e.lead_id = c.lead_id AND e.type = 'call' "
                    "AND e.payload->>'call_id' = c.id::text)"
                )
            )
        ).scalar_one()
    assert missing == 0
