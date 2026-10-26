"""D-881: a lakh-valued money field reads "one two crores" as one to two crore.

The new wording ships in the template, reaches existing agents only where their reason is
still the old template text word for word (a new schema version, then the script
recompiled), and the migration queues exactly those accounts and goes down and back up.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.agents.extraction_routes import MAX_REASON_LEN, write_schema
from apps.api.agents.lead_fields import standard_fields
from apps.api.agents.lifecycle import create_agent
from apps.api.agents.script_builder import recompile_collect
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.workers.field_reason_refresh import JOB_NAME, refresh_field_reason
from calevate_shared.extraction import ExtractionField
from scripts.seed import VERTICAL_TEMPLATES
from sqlalchemy import create_engine, text
from tests.conftest import create_org_with_receptionist

STEM = "b3d7e2a9c461_budget_reason_spoken_ranges"


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _refresh(key: str) -> tuple[str, str]:
    """(old, new) reason the migration froze for `key`."""
    return next((old, new) for k, old, new in _revision().REFRESHES if k == key)


def _shipped(key: str) -> dict[str, Any]:
    return next(f for fields in VERTICAL_TEMPLATES.values() for f in fields if f["key"] == key)


def test_the_migrations_new_wording_is_the_shipped_template() -> None:
    revision = _revision()
    assert revision.JOB == JOB_NAME
    for key, old, new in revision.REFRESHES:
        assert _shipped(key)["reason"] == new
        assert old != new


def test_the_new_wording_spells_out_the_range_and_fits_the_field_limit() -> None:
    budget = _shipped("budget_lakhs")["reason"]
    for spoken in ("one two crores", "ఒకటి రెండు కోట్లు", "1-2 crore", "ఒకటిన్నర కోటి"):
        assert spoken in budget
    assert "200" in budget
    for _key, _old, new in _revision().REFRESHES:
        assert len(new) <= MAX_REASON_LEN
        assert "range" in new and "LAKHS" in new


async def _real_estate_account() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name=f"Budget Homes {uuid.uuid4().hex[:6]}",
        slug=f"bud-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


def _with_budget_reason(reason: str) -> list[ExtractionField]:
    return [
        f.model_copy(update={"reason": reason}) if f.key == "budget_lakhs" else f
        for f in standard_fields("real_estate")
    ]


async def _set_budget_reason(tenant_id: uuid.UUID, agent_id: uuid.UUID, reason: str) -> None:
    async with tenant_session(tenant_id) as session:
        await write_schema(session, agent_id=agent_id, fields=_with_budget_reason(reason))
        await recompile_collect(session, tenant_id=tenant_id, agent_id=agent_id)


async def _current(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> tuple[int, list[Any], str | None]:
    """(schema version, fields, compiled script body) the agent holds now."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT es.version, es.fields, pv.body FROM agents a "
                    "JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
                    "LEFT JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
                    "WHERE a.id = :aid"
                ),
                {"aid": agent_id},
            )
        ).one()
    return int(row[0]), list(row[1]), None if row[2] is None else str(row[2])


def _budget(fields: list[Any]) -> str:
    return str(next(f["reason"] for f in fields if f["key"] == "budget_lakhs"))


async def test_the_old_wording_is_refreshed_an_edited_one_is_kept() -> None:
    old, new = _refresh("budget_lakhs")
    tenant_id, edited = await _real_estate_account()
    async with tenant_session(tenant_id) as session:
        scripted = await create_agent(
            session,
            tenant_id=tenant_id,
            name="Budget desk",
            direction="inbound",
            language_primary="te-IN",
            starter="answer_calls",
        )
    await _set_budget_reason(tenant_id, scripted, old)
    owner_words = "Budget in lakhs; ask whether a loan is already sanctioned."
    await _set_budget_reason(tenant_id, edited, owner_words)
    version_before, fields_before, body_before = await _current(tenant_id, scripted)
    assert body_before is not None and old in body_before
    edited_before = await _current(tenant_id, edited)

    payload = {
        "tenant_id": str(tenant_id),
        "key": "budget_lakhs",
        "old_reason": old,
        "new_reason": new,
    }
    assert await refresh_field_reason({}, payload) == "done"

    version, fields, body = await _current(tenant_id, scripted)
    assert version == version_before + 1
    assert _budget(fields) == new
    # Only the reason moved: every other field, and the order, as they were.
    assert [{**f, "reason": None} for f in fields] == [{**f, "reason": None} for f in fields_before]
    assert body is not None and new in body and old not in body
    assert await _current(tenant_id, edited) == edited_before

    # A redelivery finds nothing left to change.
    assert await refresh_field_reason({}, payload) == "done"
    assert (await _current(tenant_id, scripted))[0] == version


async def test_one_agent_that_crashes_does_not_hold_back_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unexpected error on the first agent used to end the loop, so on every retry the
    agents after it never got the new wording. They are refreshed, and the job still fails
    so the queue retries the one that crashed."""
    from apps.workers import field_reason_refresh

    old, new = _refresh("budget_lakhs")
    tenant_id, first = await _real_estate_account()
    async with tenant_session(tenant_id) as session:
        second = await create_agent(
            session,
            tenant_id=tenant_id,
            name="Budget desk",
            direction="inbound",
            language_primary="te-IN",
            starter="answer_calls",
        )
    for agent in (first, second):
        await _set_budget_reason(tenant_id, agent, old)
    real = field_reason_refresh.recompile_collect

    async def flaky(session: Any, *, tenant_id: uuid.UUID, agent_id: uuid.UUID) -> Any:
        if agent_id == first:
            raise ConnectionError("the voice platform hung up")
        return await real(session, tenant_id=tenant_id, agent_id=agent_id)

    monkeypatch.setattr(field_reason_refresh, "recompile_collect", flaky)
    payload = {
        "tenant_id": str(tenant_id),
        "key": "budget_lakhs",
        "old_reason": old,
        "new_reason": new,
    }
    with pytest.raises(RuntimeError):
        await refresh_field_reason({}, payload)
    assert _budget((await _current(tenant_id, second))[1]) == new
    assert _budget((await _current(tenant_id, first))[1]) == old


_QUEUED = text(
    "SELECT payload FROM outbox_messages WHERE job = :job AND status = 'pending' "
    "AND payload ->> 'tenant_id' = :tid"
)


async def test_the_migration_queues_only_accounts_holding_the_exact_wording() -> None:
    old, new = _refresh("budget_lakhs")
    old_tenant, old_agent = await _real_estate_account()
    await _set_budget_reason(old_tenant, old_agent, old)
    edited_tenant, edited_agent = await _real_estate_account()
    await _set_budget_reason(edited_tenant, edited_agent, old + " Ask about the loan too.")
    new_tenant, _new_agent = await _real_estate_account()
    revision = _revision()
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
                    assert queued(old_tenant) == [
                        {
                            "tenant_id": str(old_tenant),
                            "key": "budget_lakhs",
                            "old_reason": old,
                            "new_reason": new,
                        }
                    ]
                    assert queued(edited_tenant) == []
                    assert queued(new_tenant) == []
                    revision.downgrade()
                    # The inverse, for an agent made from today's template.
                    back = queued(new_tenant)
                    assert [(p["old_reason"], p["new_reason"]) for p in back] == [(new, old)]
                    assert queued(edited_tenant) == []
                    revision.upgrade()
            finally:
                transaction.rollback()
    finally:
        sync.dispose()
