"""Migration f4b8d2a6c913 (D-940): every account's calling plan becomes its "Call new
leads" Follow-up with the same agent, wait and retries, and the downgrade puts them back.

Run against the migrated database in one transaction that is rolled back, the way
`tests/bhk_sizes_test.py` exercises its revision."""

from __future__ import annotations

import importlib.util
from datetime import time
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.ingest import lead_policy
from apps.api.ingest.lead_policy import LeadCallPlan
from sqlalchemy import create_engine, text
from tests.callback_dispatch_test import _dialable_tenant
from tests.follow_ups_support import set_new_lead_call

STEM = "f4b8d2a6c913_follow_ups"


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_STEP = text(
    "SELECT f.status, v.number, v.steps->0 FROM follow_ups f "
    "JOIN follow_up_versions v ON v.id = f.live_version_id "
    "WHERE f.tenant_id = :t AND f.starter = 'call_new_leads'"
)
_PLAN = text(
    "SELECT calling_agent_id, wait_seconds, retry_attempts, retry_interval_minutes "
    "FROM lead_call_policies WHERE tenant_id = :t"
)


async def test_the_plan_moves_into_call_new_leads_and_back() -> None:
    with_plan, agent_id = await _dialable_tenant()
    without_plan, _other = await _dialable_tenant()
    async with tenant_session(with_plan) as session:
        await lead_policy.save_plan(
            session, tenant_id=with_plan, plan=LeadCallPlan(hours_start=time(10)), user_id=None
        )
    await set_new_lead_call(
        with_plan, agent_id=agent_id, wait_seconds=90, wait_minutes=2, retries=2, retry_minutes=30
    )
    revision = _revision()
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:

                def one(statement: Any, tenant: UUID) -> Any:
                    return connection.execute(statement, {"t": tenant}).first()

                with Operations.context(MigrationContext.configure(connection)):
                    revision.downgrade()
                    assert tuple(one(_PLAN, with_plan)) == (agent_id, 90, 2, 30), (
                        "the downgrade writes the Follow-up's call step back into the plan"
                    )
                    assert one(_PLAN, without_plan) is None
                    revision.upgrade()
                    status, number, step = one(_STEP, with_plan)
                    assert (status, number) == ("live", 1)
                    assert step == {
                        "id": "s1",
                        "kind": "call",
                        "agent_id": str(agent_id),
                        "wait_minutes": 2,
                        "wait_seconds": 90,
                        "retries": 2,
                        "retry_minutes": 30,
                        "next": {"answered": None, "not_reached": None},
                    }
                    status, number, step = one(_STEP, without_plan)
                    assert (status, number) == ("live", 1)
                    assert (step["agent_id"], step["wait_seconds"], step["retries"]) == (
                        None,
                        0,
                        0,
                    ), "no plan row: call at once with the lead's own agent, no retries"
            finally:
                transaction.rollback()
    finally:
        sync.dispose()


async def test_the_frozen_defaults_match_the_definition() -> None:
    import json

    from apps.api.follow_ups import definition as d
    from apps.api.follow_ups import runner

    revision = _revision()
    assert json.loads(revision._SETTINGS) == d.dump_settings(d.Settings())
    assert json.loads(revision._TRIGGER) == d.dump_trigger(d.NewLeadTrigger(kind="new_lead"))
    assert d.dump_steps(d.load_steps(runner.DEFAULT_NEW_LEAD_STEPS)) == (
        runner.DEFAULT_NEW_LEAD_STEPS
    )
