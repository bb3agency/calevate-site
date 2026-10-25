"""D-887: the real-estate BHK field names every size up to five.

A caller who said "Five" was saved as 3BHK (production, 25 Oct 2026). The new choices and
reason ship in the template, reach existing agents only where the field is still the old
template's reason AND choices exactly (a new schema version, then the script recompiled),
and the migration queues exactly those accounts and goes down and back up.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.agents.extraction_routes import MAX_REASON_LEN, write_schema
from apps.api.agents.lead_fields import standard_fields
from apps.api.agents.script_builder import recompile_collect
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.workers.field_reason_refresh import JOB_NAME, refresh_field_reason
from calevate_shared.extraction import ExtractionField, ExtractionSchemaSpec, validate_extraction
from scripts.seed import VERTICAL_TEMPLATES
from sqlalchemy import create_engine, text
from tests.conftest import create_org_with_receptionist

STEM = "c8e2f4a6b913_bhk_sizes_to_five"


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _shipped() -> dict[str, Any]:
    return next(f for f in VERTICAL_TEMPLATES["real_estate"] if f["key"] == "bhk_size")


def test_the_migrations_new_field_is_the_shipped_template() -> None:
    revision = _revision()
    shipped = _shipped()
    assert revision.JOB == JOB_NAME
    assert revision.KEY == "bhk_size"
    assert shipped["reason"] == revision.NEW_REASON
    assert shipped["enum_values"] == list(revision.NEW_CHOICES)
    assert len(revision.NEW_REASON) <= MAX_REASON_LEN
    assert revision.OLD_CHOICES != revision.NEW_CHOICES


def test_every_size_up_to_five_is_its_own_choice_and_five_is_spelled_out() -> None:
    shipped = _shipped()
    assert shipped["enum_values"] == ["1BHK", "2BHK", "3BHK", "4BHK", "5BHK+"]
    for spoken in ("'five'", "ఐదు బెడ్ రూమ్స్", "5BHK+", "Never round"):
        assert spoken in shipped["reason"]


def _spec() -> ExtractionSchemaSpec:
    return ExtractionSchemaSpec(version=1, fields=VERTICAL_TEMPLATES["real_estate"])


def test_a_five_bedroom_answer_validates_and_the_old_top_value_does_not() -> None:
    """FAILS IF: the model's "5BHK+" is refused as off-list, or "4BHK+" (now a past value)
    is still accepted for a new reading."""
    ok = validate_extraction(_spec(), {"bhk_size": "5BHK+", "budget_lakhs": 45})
    assert ok.data["bhk_size"] == "5BHK+"
    old = validate_extraction(_spec(), {"bhk_size": "4BHK+", "budget_lakhs": 45})
    assert "bhk_size" not in old.data


async def _real_estate_account() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name=f"Bedroom Homes {uuid.uuid4().hex[:6]}",
        slug=f"bhk-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


async def _set_bhk(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, reason: str, choices: list[str]
) -> None:
    fields: list[ExtractionField] = [
        f.model_copy(update={"reason": reason, "enum_values": choices})
        if f.key == "bhk_size"
        else f
        for f in standard_fields("real_estate")
    ]
    async with tenant_session(tenant_id) as session:
        await write_schema(session, agent_id=agent_id, fields=fields)
        await recompile_collect(session, tenant_id=tenant_id, agent_id=agent_id)


async def _bhk(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> tuple[int, dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT es.version, es.fields FROM agents a "
                    "JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
                    "WHERE a.id = :aid"
                ),
                {"aid": agent_id},
            )
        ).one()
    return int(row[0]), next(f for f in row[1] if f["key"] == "bhk_size")


def _payload(tenant_id: uuid.UUID) -> dict[str, Any]:
    revision = _revision()
    return {
        "tenant_id": str(tenant_id),
        "key": "bhk_size",
        "old_reason": revision.OLD_REASON,
        "new_reason": revision.NEW_REASON,
        "old_enum_values": list(revision.OLD_CHOICES),
        "new_enum_values": list(revision.NEW_CHOICES),
    }


async def test_the_old_field_is_moved_and_an_owners_choices_are_kept() -> None:
    """FAILS IF: an agent still on the old template keeps 4BHK+ as its top size, or an
    owner who added a choice of their own ("Villa") loses it to the refresh."""
    revision = _revision()
    tenant_id, agent_id = await _real_estate_account()
    await _set_bhk(tenant_id, agent_id, revision.OLD_REASON, list(revision.OLD_CHOICES))
    before, _ = await _bhk(tenant_id, agent_id)

    assert await refresh_field_reason({}, _payload(tenant_id)) == "done"
    version, field = await _bhk(tenant_id, agent_id)
    assert version == before + 1
    assert field["enum_values"] == list(revision.NEW_CHOICES)
    assert field["reason"] == revision.NEW_REASON
    # A redelivery finds nothing left to change.
    assert await refresh_field_reason({}, _payload(tenant_id)) == "done"
    assert (await _bhk(tenant_id, agent_id))[0] == version

    owner_tenant, owner_agent = await _real_estate_account()
    owners = [*revision.OLD_CHOICES, "Villa"]
    await _set_bhk(owner_tenant, owner_agent, revision.OLD_REASON, owners)
    kept = await _bhk(owner_tenant, owner_agent)
    assert await refresh_field_reason({}, _payload(owner_tenant)) == "done"
    assert await _bhk(owner_tenant, owner_agent) == kept


_QUEUED = text(
    "SELECT payload FROM outbox_messages WHERE job = :job AND status = 'pending' "
    "AND payload ->> 'tenant_id' = :tid AND payload ->> 'key' = 'bhk_size'"
)


async def test_the_migration_queues_only_accounts_holding_the_exact_field() -> None:
    revision = _revision()
    old_tenant, old_agent = await _real_estate_account()
    await _set_bhk(old_tenant, old_agent, revision.OLD_REASON, list(revision.OLD_CHOICES))
    edited_tenant, edited_agent = await _real_estate_account()
    await _set_bhk(
        edited_tenant, edited_agent, revision.OLD_REASON, [*revision.OLD_CHOICES, "Plot"]
    )
    new_tenant, _new_agent = await _real_estate_account()
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:

                def queued(tenant: uuid.UUID) -> list[dict[str, Any]]:
                    rows = connection.execute(_QUEUED, {"job": JOB_NAME, "tid": str(tenant)})
                    return [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]

                with Operations.context(MigrationContext.configure(connection)):
                    revision.upgrade()
                    assert queued(old_tenant) == [_payload(old_tenant)]
                    assert queued(edited_tenant) == []
                    assert queued(new_tenant) == []
                    revision.downgrade()
                    back = queued(new_tenant)
                    assert [(p["old_enum_values"], p["new_enum_values"]) for p in back] == [
                        (list(revision.NEW_CHOICES), list(revision.OLD_CHOICES))
                    ]
                    assert queued(edited_tenant) == []
                    revision.upgrade()
            finally:
                transaction.rollback()
    finally:
        sync.dispose()
