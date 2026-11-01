"""Leads a call renamed to the agent's own name: the repair (`c5e2a9d4f713`) and the call
read that never shows the agent's name as the caller (`crm.service._caller_name`)."""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from apps.api.crm import service as crm
from apps.api.db.session import tenant_session
from apps.workers.caller_name import fold, is_own_name
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = next((REPO_ROOT / "alembic" / "versions").glob("c5e2a9d4f713_*.py"))


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_lead_self_name_repair", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _phone() -> str:
    return f"+9197{uuid.uuid4().int % 100000000:08d}"


async def _seed() -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, agent_id = await _seed_tenant(f"selfname_{uuid.uuid4().hex[:10]}")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET name = 'Anjali', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
        await session.execute(
            text("UPDATE organizations SET name = 'Sri Estates' WHERE id = :t"), {"t": tenant_id}
        )
    return tenant_id, agent_id


async def _lead(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, name: str, data: dict[str, Any] | None = None
) -> tuple[uuid.UUID, str]:
    lead_id, phone = uuid.uuid4(), _phone()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, schema_version, call_count, is_repeat_caller, created_at, updated_at) "
                "VALUES (:id, :t, :a, :p, :n, 'outbound_call', 'new', CAST(:d AS jsonb), 1, 1, "
                "false, now(), now())"
            ),
            {
                "id": lead_id,
                "t": tenant_id,
                "a": agent_id,
                "p": phone,
                "n": name,
                "d": json.dumps(data or {}),
            },
        )
    return lead_id, phone


async def _call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    lead_id: uuid.UUID,
    *,
    captured: dict[str, Any] | None,
    hours_ago: int,
) -> uuid.UUID:
    call_id = uuid.uuid4()
    at = datetime.now(UTC) - timedelta(hours=hours_ago)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "lead_id, to_e164, started_at, created_at, updated_at) VALUES (:id, :t, :a, :e, "
                "'outbound', 'completed', :l, '+919000000000', :at, :at, :at)"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"fake-{call_id}",
                "l": lead_id,
                "at": at,
            },
        )
        if captured is not None:
            await session.execute(
                text(
                    "INSERT INTO call_extractions (id, tenant_id, call_id, schema_version, data, "
                    "valid, created_at, updated_at) VALUES (:id, :t, :c, 1, CAST(:d AS jsonb), "
                    "true, :at, :at)"
                ),
                {
                    "id": uuid.uuid4(),
                    "t": tenant_id,
                    "c": call_id,
                    "d": json.dumps(captured),
                    "at": at,
                },
            )
    return call_id


async def _campaign_row(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, phone: str, name: str
) -> None:
    campaign_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, status, classification, "
                "created_at, updated_at) VALUES (:c, :t, :a, 'Plots', 'draft', 'service', "
                "now(), now())"
            ),
            {"c": campaign_id, "t": tenant_id, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, name, "
                "status, attempts, created_at, updated_at) VALUES (:i, :t, :c, :p, :n, "
                "'completed', 1, now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "c": campaign_id, "p": phone, "n": name},
        )


async def _repair(tenant_id: uuid.UUID) -> int:
    """The migration's own statement, run inside one tenant so no other test's rows move."""
    async with tenant_session(tenant_id) as session:
        result = await session.execute(text(_migration()._repair_statement()))
        return int(getattr(result, "rowcount", 0))


async def _row(tenant_id: uuid.UUID, lead_id: uuid.UUID) -> tuple[str | None, dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT name, data FROM leads WHERE id = :l"), {"l": lead_id}
            )
        ).one()
    return row[0], row[1] or {}


NAMES = (
    "Anjali",
    "  ANJALI!! ",
    "Añjali",
    "Anjali_Sales",
    "Sri  Estates, Pvt.",
    "అంజలి",
    "అంజలి గారు",
    "राम",
    "Ravi-Kumar",
)


async def test_the_migrations_fold_is_caller_name_fold() -> None:
    fold_sql = _migration()._fold("CAST(:x AS text)")
    tenant_id, _agent = await _seed()
    async with tenant_session(tenant_id) as session:
        for name in NAMES:
            folded = (await session.execute(text(f"SELECT {fold_sql}"), {"x": name})).scalar()
            assert folded == fold(name), name


@pytest.mark.rls
async def test_a_lead_renamed_to_its_agent_gets_its_real_name_back_or_none() -> None:
    tenant_id, agent_id = await _seed()

    # The founder's lead: dialled from a campaign row as Umesh, renamed by a call to Anjali.
    umesh, umesh_phone = await _lead(
        tenant_id, agent_id, name="Anjali", data={"name": "Anjali", "budget": "40 lakh"}
    )
    await _call(tenant_id, agent_id, umesh, captured={"name": "Anjali"}, hours_ago=1)
    await _campaign_row(tenant_id, agent_id, phone=umesh_phone, name="Umesh")

    # No campaign row: the newest name a call heard that is not the agent's.
    ravi, _ = await _lead(tenant_id, agent_id, name="anjali")
    await _call(tenant_id, agent_id, ravi, captured={"name": "Ravi"}, hours_ago=5)
    await _call(tenant_id, agent_id, ravi, captured={"name": "Anjali"}, hours_ago=1)

    # The business's name, nothing else ever heard: cleared.
    nobody, _ = await _lead(tenant_id, agent_id, name="Sri Estates")
    await _call(tenant_id, agent_id, nobody, captured={"caller_name": "Sri Estates"}, hours_ago=1)

    # Named Anjali by the client, never by a call: theirs to keep.
    owner_set, _ = await _lead(tenant_id, agent_id, name="Anjali")
    await _call(tenant_id, agent_id, owner_set, captured={"budget": "1 crore"}, hours_ago=1)

    # A caller whose name is no self name.
    sai, _ = await _lead(tenant_id, agent_id, name="Sai")
    await _call(tenant_id, agent_id, sai, captured={"name": "Sai"}, hours_ago=1)

    assert await _repair(tenant_id) == 3
    assert await _row(tenant_id, umesh) == ("Umesh", {"budget": "40 lakh"})
    assert (await _row(tenant_id, ravi))[0] == "Ravi"
    assert (await _row(tenant_id, nobody))[0] is None
    assert (await _row(tenant_id, owner_set))[0] == "Anjali"
    assert (await _row(tenant_id, sai))[0] == "Sai"

    assert await _repair(tenant_id) == 0, "the repair is not idempotent"


def test_a_name_that_is_the_agents_or_the_business_is_not_the_callers() -> None:
    assert is_own_name("anjali", agent_name="Anjali Sales", business_name="Sri Estates")
    assert is_own_name("Sri Estates.", agent_name="Anjali", business_name="Sri Estates")
    assert not is_own_name("Sai", agent_name="Anjali", business_name="Sri Sai Properties")
    assert not is_own_name(None, agent_name="Anjali", business_name="Sri Estates")
    assert not is_own_name("Umesh", agent_name=None, business_name=None)


@pytest.mark.rls
async def test_a_call_never_names_its_caller_after_its_own_agent() -> None:
    tenant_id, agent_id = await _seed()
    anjali, _ = await _lead(tenant_id, agent_id, name="Anjali")
    anjali_call = await _call(tenant_id, agent_id, anjali, captured=None, hours_ago=2)
    umesh, _ = await _lead(tenant_id, agent_id, name="Umesh")
    umesh_call = await _call(tenant_id, agent_id, umesh, captured=None, hours_ago=1)

    async with tenant_session(tenant_id) as session:
        listed = {c.id: c.lead_name for c in await crm.list_calls(session)}
        anjali_detail = await crm.get_call(session, anjali_call)
        umesh_detail = await crm.get_call(session, umesh_call)

    assert listed[anjali_call] is None
    assert listed[umesh_call] == "Umesh"
    assert anjali_detail.lead_name is None
    assert umesh_detail.lead_name == "Umesh"
