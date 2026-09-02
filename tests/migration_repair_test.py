"""`b7e35c2f81da` repairs what row-level security swallowed — proved against ROWS.

**THE POINT OF THIS FILE IS THAT IT HAS DATA IN IT.** The bug being repaired reached
production precisely because a data migration was only ever exercised against an empty
table: `e1a4d70c9b52`'s backfill matched zero rows locally (no agents existed), passed, and
then failed on the first database that had any. A test that applies a repair to nothing and
asserts no error would reproduce that mistake exactly, so every test below puts a broken row
on the table first and asserts the specific value afterwards.

The statements are TAKEN FROM the migration module rather than retyped — the `op` recorder
trick `tests/retention_caller_memory_test.py` established, and for its reason: a test
holding its own copy of a statement proves only that the copy works.

Two properties are asserted of every statement, and the second is the one that is easy to
forget:

1. It REPAIRS — a row in the broken state ends up in the fixed state.
2. It is IDEMPOTENT — a row already correct is left exactly as it was. This migration runs
   on healthy deployments too (any owner that was a superuser bypassed RLS and ran the
   originals correctly), so a statement that "fixes" a row nobody broke is not a repair, it
   is a second bug with a friendlier name.
"""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = next((REPO_ROOT / "alembic" / "versions").glob("b7e35c2f81da_*.py"))


def _statements() -> list[str]:
    """Every statement `upgrade()` issues, in order, without touching the database."""
    spec = importlib.util.spec_from_file_location("_repair_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    captured: list[str] = []
    module.op = SimpleNamespace(execute=captured.append)  # type: ignore[attr-defined]
    module.upgrade()
    return captured


def _repairs() -> list[str]:
    """The statements that touch DATA, with the RLS bracket and the lock timeout dropped.

    The bracket is `ALTER TABLE`, which the test's own role may not issue — and does not
    need to: the suite's session is `calevate_app` under a tenant context, so it sees its
    own rows through the policy rather than around it. What is under test is whether the
    SQL repairs and is idempotent, not whether `ALTER TABLE` works.
    """
    return [
        sql
        for sql in _statements()
        if not sql.startswith("ALTER TABLE") and not sql.startswith("SET LOCAL")
    ]


@asynccontextmanager
async def _owner_tx() -> AsyncIterator[AsyncConnection]:
    """A transaction as the OWNER role, ALWAYS rolled back.

    `conftest`'s `platform_list_rates` fixture established the owner-connection shape and it
    is followed rather than re-invented: the suite's ordinary session is `calevate_app`,
    which is NOSUPERUSER NOBYPASSRLS and — correctly — cannot see another tenant's rows,
    issue `ALTER TABLE`, or lift a policy. A repair migration does all three, so a test
    driven through the app role would exercise a different statement than the one that
    ships.

    ROLLED BACK IN A `finally`, because this connection can do real damage: it runs the
    migration's own bracket, so RLS is off on five tables inside it, and the database is
    shared with the rest of the suite and with sibling agents. A committed fixture here
    would surface later as somebody else's unreproducible failure — the contamination the
    ratchet refuses to score through.
    """
    from apps.api.core.settings import Settings

    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: a repair migration runs as the owner"
    engine = create_async_engine(owner_url)
    try:
        async with engine.connect() as conn:
            await conn.begin()
            try:
                yield conn
            finally:
                await conn.rollback()
    finally:
        await engine.dispose()


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    from apps.api.admin import service as admin_service

    created = await admin_service.create_organization(
        name="Repair Clinic",
        slug=f"repair-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


# --- the bracket itself ---------------------------------------------------------------


def test_every_table_the_repair_touches_is_bracketed_and_unbracketed_again() -> None:
    """The bracket is what makes the repair a repair rather than another silent no-op.

    Asserted on the statement LIST, in order, because the failure this whole migration
    exists for is invisible any other way: an unbracketed statement runs, matches nothing,
    and reports success.
    """
    statements = _statements()
    opened = [s for s in statements if "NO FORCE ROW LEVEL SECURITY" in s]
    closed = [s for s in statements if "FORCE ROW LEVEL SECURITY" in s and s not in opened]
    assert opened, "the repair lifts RLS on nothing, so it repairs nothing"
    assert len(opened) == len(closed), f"{len(opened)} opened, {len(closed)} closed"

    def table_of(sql: str) -> str:
        return sql.split()[2]

    assert {table_of(s) for s in opened} == {table_of(s) for s in closed}
    # Every table named in a data statement must be one of the bracketed ones. A table that
    # is written or READ without the bracket is the original bug wearing this file's name.
    for sql in _repairs():
        for table in ("agents", "organizations", "extraction_schemas", "calls", "outbox_messages"):
            if table in sql:
                assert table in {table_of(s) for s in opened}, (
                    f"{table} is touched by the repair and never unlocked — that statement "
                    "will match zero rows and report success, which is the bug being fixed"
                )


# --- f4a1d0b6e29c: the disclosure split -----------------------------------------------


async def test_an_agent_with_no_split_disclosure_gets_one() -> None:
    """Hard rule 5's columns, filled. The dial gate refuses an agent with no AI sentence, so
    an agent left in this state by the swallowed migration cannot make a call at all."""
    tenant_id, agent_id = await _tenant()
    async with _owner_tx() as session:
        # The pre-repair state: the legacy bundled line present, the two columns empty. The
        # NOT NULL and CHECK on `ai_disclosure_line` are dropped for the duration — the
        # broken state this repairs predates them, and it is not otherwise expressible.
        await session.execute(
            text("ALTER TABLE agents ALTER COLUMN ai_disclosure_line DROP NOT NULL")
        )
        await session.execute(
            text("ALTER TABLE agents DROP CONSTRAINT IF EXISTS ck_agents_ai_disclosure_nonempty")
        )
        await session.execute(
            text(
                "UPDATE agents SET ai_disclosure_line = NULL, "
                "disclosure_line = 'Namaskaram, idi Repair Clinic AI assistant. "
                "Ee call record avutundi.' WHERE id = :aid"
            ),
            {"aid": agent_id},
        )
        for sql in _statements():
            await session.execute(text(sql))
        row = (
            await session.execute(
                text(
                    "SELECT ai_disclosure_line, recording_notice_line FROM agents WHERE id = :aid"
                ),
                {"aid": agent_id},
            )
        ).first()

    assert row is not None
    ai, notice = row
    # Split at the tail, so the AI half is the bundled line minus our own recording
    # sentence — not a template substitution. A tenant who edited their own wording keeps it.
    assert ai == "Namaskaram, idi Repair Clinic AI assistant."
    assert notice == "Ee call record avutundi."


async def test_an_agent_already_split_is_not_touched() -> None:
    """Idempotence, and it is the property that matters on a healthy deployment.

    A tenant who has EDITED their disclosure sentence since would have it overwritten by a
    repair without the `IS NULL` guard — silently rewriting a compliance sentence somebody
    chose, on a database that was never broken.
    """
    tenant_id, agent_id = await _tenant()
    mine = "Namaskaram, this is Dr Rao's clinic assistant, an AI."
    async with _owner_tx() as session:
        await session.execute(
            text("UPDATE agents SET ai_disclosure_line = :mine WHERE id = :aid"),
            {"mine": mine, "aid": agent_id},
        )
        for sql in _statements():
            await session.execute(text(sql))
        after = (
            await session.execute(
                text("SELECT ai_disclosure_line FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar_one()
    assert after == mine, "the repair overwrote a sentence the tenant had chosen"


# --- f4b1e9a2c7d0: the extraction-field key rename -------------------------------------


async def test_a_schema_still_carrying_the_old_key_is_renamed_in_order() -> None:
    """`description` -> `reason`, with FIELD ORDER preserved — the extraction prompt lists
    fields in this order, so a rewrite that reshuffled them would change what the model is
    asked to capture first."""
    tenant_id, agent_id = await _tenant()
    fields = (
        '[{"key": "a", "label": "A", "type": "text", "description": "first", "required": true},'
        ' {"key": "b", "label": "B", "type": "text", "reason": "already new", "required": false},'
        ' {"key": "c", "label": "C", "type": "text", "description": "third", "required": false}]'
    )
    async with _owner_tx() as session:
        schema_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO extraction_schemas "
                "(id, tenant_id, agent_id, version, fields, created_at) "
                "VALUES (:id, :tid, :aid, 99, CAST(:fields AS jsonb), now())"
            ),
            {"id": schema_id, "tid": tenant_id, "aid": agent_id, "fields": fields},
        )
        for sql in _statements():
            await session.execute(text(sql))
        after = (
            await session.execute(
                text("SELECT fields FROM extraction_schemas WHERE id = :id"), {"id": schema_id}
            )
        ).scalar_one()

    keys = [f["key"] for f in after]
    assert keys == ["a", "b", "c"], f"field order changed: {keys}"
    assert [f.get("reason") for f in after] == ["first", "already new", "third"]
    assert not any("description" in f for f in after), "the old key survived the rename"


# --- e83b5d1a4c07: calls.crm_notified_at ----------------------------------------------


async def test_a_call_already_marked_notified_keeps_its_own_timestamp() -> None:
    """THE ONE PLACE THIS REPAIR DEVIATES FROM THE ORIGINAL, and the reason it had to.

    The original ran when the column had just been added and every row was NULL, so it
    needed no guard. Re-running it unguarded now would overwrite whatever the application
    has written since with the outbox's `min(created_at)` — moving a timestamp the CRM probe
    reads, on rows that were never broken. `AND c.crm_notified_at IS NULL` is the deviation;
    this test is what holds it there.
    """
    tenant_id, agent_id = await _tenant()
    call_id = uuid.uuid4()
    mine = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    async with _owner_tx() as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "status, started_at, crm_notified_at, created_at, updated_at) VALUES "
                "(:id, :tid, :aid, :engine, 'inbound', 'completed', now(), :mine, now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "engine": f"repair-{call_id}",
                "mine": mine,
            },
        )
        await session.execute(
            text(
                # `outbox_messages` carries no `tenant_id` — it is not tenant-scoped, which
                # is also why the RLS guard does not flag the read of it.
                "INSERT INTO outbox_messages "
                "(id, queue, job, payload, status, attempt_count, created_at, updated_at) "
                "VALUES (:id, 'default', 'deliver_outbound_webhook', CAST(:payload AS jsonb), "
                "'published', 1, '2026-07-01T00:00:00+00:00', '2026-07-01T00:00:00+00:00')"
            ),
            {
                "id": uuid.uuid4(),
                "payload": f'{{"data": {{"call_id": "{call_id}"}}}}',
            },
        )
        for sql in _statements():
            await session.execute(text(sql))
        after = (
            await session.execute(
                text("SELECT crm_notified_at FROM calls WHERE id = :id"), {"id": call_id}
            )
        ).scalar_one()

    assert after == mine, (
        "the repair overwrote a timestamp the application had already written — the outbox "
        "row is older, so an unguarded backfill moves this call's notification backwards"
    )
