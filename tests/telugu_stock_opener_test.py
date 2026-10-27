"""The stock Telugu opener "సరే అండి," comes off the trade plans and off agents still holding
it, and the migration that takes it off puts it back on exactly the steps it changed
(founder, 27 Oct 2026, D-894 follow-up; migration `d7c2e9a4f6b1`)."""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.agents.lifecycle import create_agent
from apps.api.agents.script_builder import (
    load_agent_script,
    read_draft,
    rewrite_script,
    save_draft,
)
from apps.api.agents.trade_playbooks import (
    ALL_LINES,
    PLAYBOOK_LANGUAGES,
    TE_OPENER_LINES,
    TRADE_WORDS,
    is_playbook_line,
)
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.workers.example_line_refresh import JOB_NAME, refresh_example_lines
from sqlalchemy import Connection, create_engine, text
from tests.conftest import create_org_with_receptionist

STEM = "d7c2e9a4f6b1_telugu_stock_opener_off_example_lines"
OPENER = "సరే అండి"


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_plan_line_opens_with_the_stock_telugu_opener() -> None:
    assert not [said["te-IN"] for said in ALL_LINES if said["te-IN"].startswith(OPENER)]
    # The close and all eight trades' first questions were the lines that had it.
    assert len(TE_OPENER_LINES) == 1 + len(TRADE_WORDS)
    for old, new in TE_OPENER_LINES:
        assert old["te-IN"] == f"{OPENER}, {new['te-IN']}"
        # Only the Telugu line changed: the approval named the Telugu opener.
        assert all(old[tag] == new[tag] for tag in PLAYBOOK_LANGUAGES if tag != "te-IN")
        # An agent made with the old line may still take a business's own line in its place.
        assert is_playbook_line(old["te-IN"])


def test_the_migrations_lines_are_the_shipped_plans() -> None:
    revision = _revision()
    assert revision.JOB == JOB_NAME
    shipped = [(old["te-IN"], new["te-IN"]) for old, new in TE_OPENER_LINES]
    assert sorted(revision.REPLACEMENTS) == sorted(shipped)


async def _agent(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        return await create_agent(
            session,
            tenant_id=tenant_id,
            name="Anjali",
            direction="inbound",
            language_primary="te-IN",
            starter="answer_calls",
        )


async def _lines(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        loaded = await load_agent_script(session, agent_id)
    return [stage.sounds_like for stage in loaded.script.stages]


async def _put_lines(tenant_id: uuid.UUID, agent_id: uuid.UUID, swap: dict[str, str]) -> None:
    async with tenant_session(tenant_id) as session:
        script = (await load_agent_script(session, agent_id)).script
        stages = [
            stage.model_copy(update={"sounds_like": swap.get(stage.sounds_like, stage.sounds_like)})
            for stage in script.stages
        ]
        await rewrite_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=script.model_copy(update={"stages": stages}),
            notes="test: the lines an agent made before the opener came off holds",
        )


async def _draft_lines(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        draft = await read_draft(session, agent_id)
    assert draft is not None
    return [stage.sounds_like for stage in draft.script.stages]


_BACK_TO_OLD = {new["te-IN"]: old["te-IN"] for old, new in TE_OPENER_LINES}

_QUEUED = text(
    "SELECT payload FROM outbox_messages WHERE job = :job AND status = 'pending' "
    "AND payload ->> 'tenant_id' = :tid ORDER BY created_at"
)
_DRAFT = text("SELECT script_draft FROM agents WHERE id = :aid")


def _queued(connection: Connection, tenant: uuid.UUID) -> list[dict[str, Any]]:
    rows = connection.execute(_QUEUED, {"job": JOB_NAME, "tid": str(tenant)})
    return [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]


def _draft_in(connection: Connection, agent_id: uuid.UUID) -> list[str]:
    raw = connection.execute(_DRAFT, {"aid": agent_id}).scalar_one()
    draft = raw if isinstance(raw, dict) else json.loads(raw)
    return [stage["sounds_like"] for stage in draft["stages"]]


async def test_the_opener_comes_off_unedited_steps_and_goes_back_on_exactly_those() -> None:
    created = await create_org_with_receptionist(
        name=f"Guntur Homes {uuid.uuid4().hex[:6]}",
        slug=f"gnt-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    held = await _agent(tenant_id)
    shipped = await _lines(tenant_id, held)
    first_ask = TRADE_WORDS["real_estate"].first_ask["te-IN"]
    assert first_ask in shipped
    # An agent made before the change: the old lines on its script, and the owner rewrote
    # the close themselves (their words, never touched).
    await _put_lines(tenant_id, held, _BACK_TO_OLD)
    old_lines = await _lines(tenant_id, held)
    old_close = next(line for line in old_lines if line.startswith(f"{OPENER}, మీరు చెప్పింది"))
    owner_close = f"{OPENER}, మా టీమ్ మీకు ఫోన్ చేస్తారు. ఇంకేమైనా కావాలా?"
    await _put_lines(tenant_id, held, {old_close: owner_close})
    before = await _lines(tenant_id, held)
    old_first = f"{OPENER}, {first_ask}"
    assert old_first in before and owner_close in before
    # Its autosaved draft holds the old first question too.
    async with tenant_session(tenant_id) as session:
        script = (await load_agent_script(session, held)).script
        await save_draft(session, held, script)
    # An agent made after: already the new lines, and nothing about it is recorded.
    fresh = await _agent(tenant_id)
    fresh_lines = await _lines(tenant_id, fresh)

    revision = _revision()
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:
                with Operations.context(MigrationContext.configure(connection)):
                    # The database is at head: step back first, so upgrade() runs as shipped.
                    revision.downgrade()
                    revision.upgrade()
                    forward = _queued(connection, tenant_id)
                    draft_after = _draft_in(connection, held)
                    revision.downgrade()
                    back = _queued(connection, tenant_id)[len(forward) :]
                    draft_back = _draft_in(connection, held)
                    revision.upgrade()
            finally:
                transaction.rollback()
    finally:
        sync.dispose()

    index = before.index(old_first)
    # The draft: the first question lost its opener, the owner's close kept it, and the
    # downgrade put back exactly what it took.
    assert draft_after == [first_ask if i == index else line for i, line in enumerate(before)]
    assert draft_back == before
    # One message for the account, naming only the agent and the step that held the plan line.
    assert len(forward) == 1 and len(back) == 1
    assert forward[0]["stages"] == {str(held): [index]} == back[0]["stages"]
    assert forward[0]["replacements"] == [list(p) for p in revision.REPLACEMENTS]
    assert back[0]["replacements"] == [[new, old] for old, new in revision.REPLACEMENTS]

    # The job does the script, through the recompile path (a new version, republished).
    assert await refresh_example_lines({}, forward[0]) == "done"
    after = await _lines(tenant_id, held)
    assert after == [first_ask if i == index else line for i, line in enumerate(before)]
    async with tenant_session(tenant_id) as session:
        version = (await load_agent_script(session, held)).version
    # A redelivery finds nothing left to change.
    assert await refresh_example_lines({}, forward[0]) == "done"
    async with tenant_session(tenant_id) as session:
        assert (await load_agent_script(session, held)).version == version
    # The inverse restores that step and touches no agent it did not change.
    assert await refresh_example_lines({}, back[0]) == "done"
    assert await _lines(tenant_id, held) == before
    assert await _lines(tenant_id, fresh) == fresh_lines
    assert await _draft_lines(tenant_id, held) == before
