"""`a6c2e9f4b8d1` fills what `e2a7c4f9b1d3` / `f3b8d2a6c1e4` never copied, and nothing else.

Run against rows: a job left with an empty "What it notes" list gets its agent's list, a job
whose list or suggestions were set since keeps them. The statements are taken from the
migration module, so the test proves the SQL that ships.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from types import ModuleType
from uuid import UUID

from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

from apps.api.db.session import tenant_session

MIGRATION = next(
    (Path(__file__).resolve().parents[1] / "alembic" / "versions").glob("a6c2e9f4b8d1_*.py")
)
AGENT_FIELDS = [{"key": "budget", "label": "Budget", "type": "text"}]
OWN_FIELDS = [{"key": "visit_day", "label": "Visit day", "type": "text"}]


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_notes_rerun", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _tenant() -> tuple[UUID, UUID]:
    created = await create_org_with_receptionist(
        name="Rerun Shop", slug=f"rerun-{uuid.uuid4().hex[:8]}"
    )
    tenant_id = UUID(str(created["id"]))
    agent_id = UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE extraction_schemas SET fields = CAST(:f AS jsonb) WHERE id = :s"),
            {"f": json.dumps(AGENT_FIELDS), "s": created["extraction_schema_id"]},
        )
        await session.execute(
            text("UPDATE agents SET extraction_schema_id = :s WHERE id = :a"),
            {"s": created["extraction_schema_id"], "a": agent_id},
        )
    return tenant_id, agent_id


async def _line(tenant_id: UUID, agent_id: UUID, fields: list[dict[str, str]]) -> UUID:
    line_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO inbound_lines (id, tenant_id, name, agent_id, extraction_fields) "
                "VALUES (:id, :t, 'Desk', :a, CAST(:f AS jsonb))"
            ),
            {"id": line_id, "t": tenant_id, "a": agent_id, "f": json.dumps(fields)},
        )
    return line_id


async def _run(tenant_id: UUID) -> None:
    module = _module()
    async with tenant_session(tenant_id) as session:
        for statement in [*module._FIELDS.values(), *module._SUGGESTIONS.values()]:
            await session.execute(statement, {"t": tenant_id})


async def _fields(tenant_id: UUID, line_id: UUID) -> object:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text("SELECT extraction_fields FROM inbound_lines WHERE id = :l"), {"l": line_id}
            )
        ).scalar_one()


async def test_an_empty_list_gets_its_agents_and_an_owners_list_is_kept() -> None:
    tenant_id, agent_id = await _tenant()
    empty = await _line(tenant_id, agent_id, [])
    owned = await _line(tenant_id, agent_id, OWN_FIELDS)

    await _run(tenant_id)
    await _run(tenant_id)

    assert await _fields(tenant_id, empty) == AGENT_FIELDS
    assert await _fields(tenant_id, owned) == OWN_FIELDS


async def test_waiting_suggestions_reach_a_job_with_none_and_spare_one_with_its_own() -> None:
    tenant_id, agent_id = await _tenant()
    waiting = [{"id": "a" * 16, "kind": "add"}]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET field_suggestions = CAST(:s AS jsonb) WHERE id = :a"),
            {"s": json.dumps(waiting), "a": agent_id},
        )
    bare = await _line(tenant_id, agent_id, OWN_FIELDS)
    passed = await _line(tenant_id, agent_id, OWN_FIELDS)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE inbound_lines SET field_suggestions = '[]'::jsonb, "
                "field_suggestions_state = 'done' WHERE id = :l"
            ),
            {"l": passed},
        )

    await _run(tenant_id)

    async with tenant_session(tenant_id) as session:
        rows = dict(
            (
                await session.execute(
                    text(
                        "SELECT id, field_suggestions FROM inbound_lines WHERE id IN (:a, :b)"
                    ),
                    {"a": bare, "b": passed},
                )
            ).all()
        )
    assert rows[bare] == waiting
    assert rows[passed] == []
