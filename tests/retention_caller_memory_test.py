"""The caller-memory retention clock (D-507), against a real database.

**WHAT THIS FILE IS FOR.** `caller_memory` became a `retention_policies.data_category` of
its own — 180 days, `delete` — instead of riding the tenant's `transcript` policy. A new
category is worth nothing on its own: it is worth what its ARM does, and a category whose
arm is missing, half-written or merged back into somebody else's is strictly worse than no
category, because the row makes a promise the DPA prints and the sweep does not keep.

**THE THREE PROPERTIES, and each one is a different way the change can be undone.**

1. *Both halves or neither.* `caller_memories.fact` is the distilled sentence and the
   `caller_chunks` rows of that scope are the vector and the lexemes BUILT FROM it. An
   embedding is a copy of the sentence (D-503's premise — derived by a deterministic
   function of it and substantially invertible), so an arm that expired one and not the
   other would leave the sentence on file in the form nobody reads. Every assertion here
   is on the STORE — `fact = ''`, `scrubbed_at` set, `embedding IS NULL`, `tsv = ''` —
   and never on a row count: these rows are KEPT and emptied by design (the tombstone is
   what stops the ingestion sweep re-projecting the subject and re-buying a vector for
   text the sweep just destroyed), so a count assertion passes against exactly the bug
   this file guards.

2. *The two clocks are separate.* A tenant whose `transcript` period has elapsed and whose
   `caller_memory` period has not must KEEP its memories, and the reverse must hold too.
   This is the whole of D-507, and it is the assertion that fails the day somebody merges
   the arms back together for tidiness.

3. *Every tenant has the row.* A category only the tenants created after it exists ever
   receive is a hole with a new name: the organisations that predate the migration would
   hold remembered facts that nothing expires. `e1a4d70c9b52` writes the row for every
   organisation on file and the seed writes it for every organisation after, and the
   coverage assertion below does not care which of the two supplied it.

**`sweep_tenant` AND NOT `apply_retention`.** The nightly entry point resolves its own
worklist from `engine_agent_routes` and would sweep every tenant in the database — on a
development database shared with other work that is both slow and rude. `sweep_tenant` is
the same code path with the worklist step removed, and it is what `apply_retention` calls
per tenant; the probe, the arms and the counts under test are identical.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance import caller_memory
from apps.api.compliance.caller_ref import active_caller_ref
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.retrieval.embedding import EMBEDDING_DIMS
from apps.api.retrieval.models import (
    RETENTION_CALLER_MEMORY,
    RETENTION_TRANSCRIPT,
    SUBJECT_CALL_TURN,
    SUBJECT_CALLER_MEMORY,
    SUBJECT_RETENTION,
)
from apps.workers.retention import sweep_tenant
from sqlalchemy import text

pytestmark = pytest.mark.anyio

#: The caller and the sentence. A real distilled fact rather than a placeholder, because
#: what these tests watch disappear is a specific piece of somebody's information.
CALLER = "+919812345690"
FACT = "asked about IVF pricing"

#: The seeded period, restated as a literal. Imported nowhere on purpose: a test that read
#: the tenant's own row for its cutoff would pass for any number the row happened to hold,
#: including a zero somebody typed by accident.
MEMORY_TTL_DAYS = 180

#: The migration that gave the category to every organisation already on file.
MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "e1a4d70c9b52_caller_memory_says_so_and_forgets_on_its_own_clock.py"
)

#: A dense key that is not NULL, so "the vector went" is an observation rather than a
#: property the row already had. pgvector's input form is `[a,b,...]`, which is why this is
#: built as text rather than as a Postgres array.
_VECTOR_SQL = "('[' || array_to_string(array_fill(0.1::real, ARRAY[:dims]), ',') || ']')::vector"

_INSERT_CHUNK_SQL = f"""
INSERT INTO caller_chunks (
  id, tenant_id, subject_kind, subject_id, idx, agent_id, subject_ref, subject_ref_kek_id,
  retention_category, occurred_at, tsv, embedding, embed_model, embed_dim, content_sha256,
  embed_state, created_at, updated_at)
VALUES (
  :id, :tenant, :kind, :subject, 0, :agent, :ref, :kek, :category, :occurred,
  to_tsvector('english', :body), {_VECTOR_SQL}, 'test-embed', :dims, 'sha', 'ready',
  now(), now())
"""


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant with the shipped retention rows and one agent that remembers callers."""
    created = await admin_service.create_organization(
        name="Memory Retention Agency",
        slug=f"mrc-{uuid.uuid4().hex[:8]}",
        # NOT `clinic`: `caller_memory.SPDI_REFUSED_VERTICALS` refuses to write a memory at
        # all on that template, so a clinic fixture would test the refusal and report it as
        # a retention pass — the arm would have nothing to sweep and every assertion below
        # would be green against an empty table.
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET caller_memory_enabled = true WHERE id = :a"), {"a": agent_id}
        )
        await session.commit()
    return tenant_id, agent_id


async def _remember(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, days_ago: int) -> None:
    """One remembered fact, through the ONE door that writes them."""
    async with tenant_session(tenant_id) as session:
        written = await caller_memory.remember(
            session,
            tenant_id,
            agent_id=agent_id,
            phone_e164=CALLER,
            occurred_at=datetime.now(UTC) - timedelta(days=days_ago),
            source_call_id=None,
            facts=[FACT],
        )
        await session.commit()
    assert written == 1, "the fixture wrote no memory, so nothing below is under test"


async def _project(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, kind: str, days_ago: int
) -> uuid.UUID:
    """One chunk of a caller's words, filed on the clock its SUBJECT KIND rides.

    Written directly rather than through a scope's discovery, for `caller_chunks_rls_test`'s
    reason: no registered scope projects the caller-memory kind yet, and the property under
    test belongs to the store and to the sweep rather than to whichever writer arrives. The
    category comes from `SUBJECT_RETENTION` rather than from a literal, so a row here can
    never be filed on a clock the running product would not have used.
    """
    chunk_id = uuid7()
    handle = active_caller_ref(tenant_id, CALLER)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(_INSERT_CHUNK_SQL),
            {
                "id": chunk_id,
                "tenant": tenant_id,
                "kind": kind,
                "subject": uuid7(),
                "agent": agent_id,
                "ref": handle.ref,
                "kek": handle.kek_id,
                "category": SUBJECT_RETENTION[kind],
                "occurred": datetime.now(UTC) - timedelta(days=days_ago),
                "body": FACT,
                "dims": EMBEDDING_DIMS,
            },
        )
        await session.commit()
    return chunk_id


async def _memory_state(tenant_id: uuid.UUID) -> tuple[str, bool]:
    """(fact, was it scrubbed) for this tenant's one memory row."""
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text("SELECT fact, scrubbed_at FROM caller_memories"))).first()
    assert row is not None, "the memory row is gone; this arm scrubs and never deletes"
    return str(row[0]), row[1] is not None


async def _chunk_state(tenant_id: uuid.UUID, chunk_id: uuid.UUID) -> dict[str, Any]:
    """Everything a forgotten chunk must have lost, read back from the row itself."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT tsv::text, embedding IS NULL, embed_model, embed_state, "
                    "       scrubbed_at IS NOT NULL, content_sha256 "
                    "  FROM caller_chunks WHERE id = :c"
                ),
                {"c": chunk_id},
            )
        ).first()
    assert row is not None, "the chunk row is gone; the tombstone is what makes it durable"
    return {
        "tsv": str(row[0]),
        "no_vector": bool(row[1]),
        "embed_model": row[2],
        "embed_state": str(row[3]),
        "scrubbed": bool(row[4]),
        "sha": str(row[5]),
    }


async def _set_ttl(tenant_id: uuid.UUID, category: str, days: int) -> None:
    async with tenant_session(tenant_id) as session:
        result = await session.execute(
            text(
                "UPDATE retention_policies SET ttl_days = :d WHERE data_category = :c RETURNING id"
            ),
            {"d": days, "c": category},
        )
        assert result.first() is not None, f"this tenant has no {category} policy row to set"
        await session.commit()


# ==================================================== 1. BOTH HALVES, ON THE NEW CLOCK


async def test_an_expired_memory_and_its_projection_are_both_forgotten() -> None:
    """The arm, end to end: past 180 days the fact goes AND the keys built from it go.

    Asserted on the emptied columns rather than on a count of surviving rows, because the
    rows survive on purpose — a count would be green against a sweep that deleted
    everything, against one that scrubbed only the source, and against one that only
    stamped `scrubbed_at`.
    """
    tenant_id, agent_id = await _tenant()
    await _remember(tenant_id, agent_id, days_ago=MEMORY_TTL_DAYS + 5)
    chunk_id = await _project(
        tenant_id, agent_id, kind=SUBJECT_CALLER_MEMORY, days_ago=MEMORY_TTL_DAYS + 5
    )

    counts = await sweep_tenant(tenant_id)

    assert await _memory_state(tenant_id) == ("", True)
    state = await _chunk_state(tenant_id, chunk_id)
    assert state["tsv"] == "", "the lexemes survived: the caller's words are still searchable"
    assert state["no_vector"], "the embedding survived, and an embedding IS a copy of the text"
    assert state["embed_model"] is None and state["sha"] == ""
    # `expired` and not `erased`: both are terminal and both empty the same two keys, and
    # they are two values so an operator can tell an ageing-out from a §12 request.
    assert (state["embed_state"], state["scrubbed"]) == ("expired", True)
    assert (counts["caller_memories"], counts["caller_vectors"]) == (1, 1)


async def test_a_memory_inside_its_period_is_untouched() -> None:
    """The other half of the same statement. Without it the test above passes for a sweep
    that empties the table on every tick, which is not retention — it is data loss."""
    tenant_id, agent_id = await _tenant()
    await _remember(tenant_id, agent_id, days_ago=MEMORY_TTL_DAYS - 5)
    chunk_id = await _project(
        tenant_id, agent_id, kind=SUBJECT_CALLER_MEMORY, days_ago=MEMORY_TTL_DAYS - 5
    )

    await sweep_tenant(tenant_id)

    assert await _memory_state(tenant_id) == (FACT, False)
    state = await _chunk_state(tenant_id, chunk_id)
    assert state["tsv"] != "" and not state["no_vector"] and not state["scrubbed"]


async def test_the_seeded_period_is_the_one_the_sweep_obeys() -> None:
    """The number a tenant actually holds, read from their own row rather than asserted
    about a constant — 180 days and `delete`, `copilot_memory`'s pair and not the
    transcript's 365."""
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT ttl_days, action FROM retention_policies  WHERE data_category = :c"),
                {"c": RETENTION_CALLER_MEMORY},
            )
        ).first()
    assert row is not None, "a tenant created today has no caller-memory clock at all"
    assert (int(row[0]), str(row[1])) == (MEMORY_TTL_DAYS, "delete")


# ==================================================== 2. THE TWO CLOCKS ARE SEPARATE


async def test_an_elapsed_transcript_clock_does_not_reach_a_caller_memory() -> None:
    """D-507's whole point, in the direction that matters most.

    The transcript period is set to one day — elapsed for everything this tenant holds —
    and the memory period is left at its seeded 180. A memory 30 days old must survive,
    and the transcript-scope projection of the same age must NOT, because a test in which
    the transcript arm did nothing at all would pass whether the clocks were separate or
    the sweep was simply broken.
    """
    tenant_id, agent_id = await _tenant()
    await _set_ttl(tenant_id, RETENTION_TRANSCRIPT, 1)
    await _remember(tenant_id, agent_id, days_ago=30)
    memory_chunk = await _project(tenant_id, agent_id, kind=SUBJECT_CALLER_MEMORY, days_ago=30)
    transcript_chunk = await _project(tenant_id, agent_id, kind=SUBJECT_CALL_TURN, days_ago=30)

    await sweep_tenant(tenant_id)

    assert await _memory_state(tenant_id) == (FACT, False), (
        "the transcript clock reached a caller memory. The two arms have been merged back "
        "together, and a fact whose purpose is to outlive the call now expires with it."
    )
    assert not (await _chunk_state(tenant_id, memory_chunk))["scrubbed"]
    assert (await _chunk_state(tenant_id, transcript_chunk))["scrubbed"], (
        "the transcript arm scrubbed nothing, so the assertion above proves nothing"
    )


async def test_an_elapsed_caller_memory_clock_does_not_reach_a_transcript() -> None:
    """And the reverse, which is the failure a category-scoped statement would make if
    somebody dropped the `retention_category` predicate from `EXPIRE_CHUNKS_SQL`: the
    memory arm would quietly expire the transcript scope on the shorter of two clocks the
    tenant agreed to separately."""
    tenant_id, agent_id = await _tenant()
    await _set_ttl(tenant_id, RETENTION_CALLER_MEMORY, 1)
    await _remember(tenant_id, agent_id, days_ago=30)
    memory_chunk = await _project(tenant_id, agent_id, kind=SUBJECT_CALLER_MEMORY, days_ago=30)
    transcript_chunk = await _project(tenant_id, agent_id, kind=SUBJECT_CALL_TURN, days_ago=30)

    await sweep_tenant(tenant_id)

    assert await _memory_state(tenant_id) == ("", True)
    assert (await _chunk_state(tenant_id, memory_chunk))["scrubbed"]
    assert not (await _chunk_state(tenant_id, transcript_chunk))["scrubbed"], (
        "the caller-memory arm scrubbed a TRANSCRIPT chunk, so `EXPIRE_CHUNKS_SQL` is no "
        "longer scoped by `retention_category` and one tenant clock is now overriding "
        "another"
    )


async def test_the_projection_is_swept_even_when_every_fact_is_already_scrubbed() -> None:
    """THE PROBE, not the arm — and the failure it prevents is invisible.

    `sweep_tenant` runs an arm only where its probe reported work. If the caller-memory
    arm's probe asked about `caller_memories` alone, a tenant whose facts had all been
    scrubbed by a §12 erasure would report no work forever, and the vector and the lexemes
    — the copy of the sentence nobody reads — would stay on file with nothing left to
    trigger the arm that empties them.
    """
    tenant_id, agent_id = await _tenant()
    chunk_id = await _project(
        tenant_id, agent_id, kind=SUBJECT_CALLER_MEMORY, days_ago=MEMORY_TTL_DAYS + 5
    )

    counts = await sweep_tenant(tenant_id)

    assert (await _chunk_state(tenant_id, chunk_id))["scrubbed"], (
        "an expired caller-memory projection with no unscrubbed source row was never "
        "swept: the probe asks about the facts and not about the chunks built from them"
    )
    assert counts["caller_vectors"] == 1


# ==================================================== 3. EVERY TENANT HAS THE ROW


def _migration_backfill_sql(category: str = RETENTION_CALLER_MEMORY) -> str:
    """The `retention_policies` INSERT for one category, taken FROM `e1a4d70c9b52`.

    Imported and captured rather than retyped, which is the whole point: a test holding its
    own copy of the statement proves that the copy works. The module's `op` is replaced with
    a recorder, `upgrade()` is called for its statements alone (nothing reaches the
    database), and the statement that seeds THIS category is returned.

    SELECTED BY CATEGORY, NOT BY BEING THE ONLY ONE — and it used to demand the latter,
    which was right when it was written and became wrong the moment the migration grew a
    second seed. `_REPAIR` re-seeds `copilot_memory`, a row `d4a9c17e6b02` should have
    written and did not (its INSERT was unbracketed against FORCE-RLS `organizations`, so it
    matched nothing). Requiring exactly one statement would make this test fail whenever the
    migration legitimately repairs something else, which is a guard against the wrong thing.
    What still has to hold is that the category under test is seeded EXACTLY once.
    """
    spec = importlib.util.spec_from_file_location("_d507_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    captured: list[str] = []
    module.op = SimpleNamespace(execute=captured.append)  # type: ignore[attr-defined]
    module.upgrade()
    inserts = [
        sql
        for sql in captured
        if "INSERT INTO retention_policies" in sql and f"'{category}'" in sql
    ]
    assert len(inserts) == 1, (
        f"the migration seeds {category!r} {len(inserts)} times, not once — so this test is "
        "reading something other than the backfill it means to test"
    )
    return inserts[0]


async def test_an_organisation_that_predates_the_migration_gets_the_policy_row() -> None:
    """THE REACH BACKWARDS. A category only new tenants receive is the old hole renamed.

    A tenant created today receives the row from `DEFAULT_RETENTION_POLICIES`, so the seed
    proves nothing about the accounts that already existed — and those are precisely the
    ones that would hold caller memories no clock expires. The state is therefore
    CONSTRUCTED: an organisation with its caller-memory row deleted is exactly an
    organisation created before `e1a4d70c9b52` ran, and the migration's own INSERT is then
    run against it.

    The statement is taken from the migration module rather than restated here, because a
    restatement would test the restatement. It is run in the tenant's own session, so RLS
    scopes the `SELECT ... FROM organizations` inside it to this one account and no sibling
    tenant's rows are touched by a test.
    """
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("DELETE FROM retention_policies WHERE data_category = :c"),
            {"c": RETENTION_CALLER_MEMORY},
        )
        await session.commit()

    # The premise: with no row, an expired memory is swept by nothing at all. This is the
    # hole itself, asserted rather than described.
    await _remember(tenant_id, agent_id, days_ago=MEMORY_TTL_DAYS + 5)
    await sweep_tenant(tenant_id)
    assert await _memory_state(tenant_id) == (FACT, False), (
        "a memory expired with no policy row, so the assertion below cannot tell whether "
        "the backfill did anything"
    )

    async with tenant_session(tenant_id) as session:
        await session.execute(text(_migration_backfill_sql()))
        await session.commit()

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT ttl_days, action FROM retention_policies WHERE data_category = :c"),
                {"c": RETENTION_CALLER_MEMORY},
            )
        ).first()
    assert row is not None, (
        "the migration wrote no policy row for an organisation that already existed, so "
        "every account created before it holds remembered facts nothing expires"
    )
    assert (int(row[0]), str(row[1])) == (MEMORY_TTL_DAYS, "delete")

    await sweep_tenant(tenant_id)
    assert await _memory_state(tenant_id) == ("", True)


async def test_the_backfill_is_safe_to_run_over_a_tenant_that_already_has_the_row() -> None:
    """The `ON CONFLICT DO NOTHING` half, which is what makes the migration safe to run on
    a database where the seed had already supplied the row — and what stops it writing a
    SECOND policy for the same category, which `uq_retention_policies_tenant_id_data_category`
    would refuse and which would abort the whole migration on the first tenant."""
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(text(_migration_backfill_sql()))
        count = (
            await session.execute(
                text("SELECT count(*) FROM retention_policies WHERE data_category = :c"),
                {"c": RETENTION_CALLER_MEMORY},
            )
        ).scalar_one()
        await session.commit()
    assert int(count) == 1


async def test_the_repair_gives_an_old_tenant_the_copilot_memory_row_its_migration_missed() -> None:
    """`_REPAIR`, and this one fixes a CONFIRMED production gap rather than a hypothesis.

    `d4a9c17e6b02` seeds a `copilot_memory` policy for every existing organisation with an
    unbracketed `INSERT ... SELECT FROM organizations`. `organizations` is FORCE ROW LEVEL
    SECURITY, which subjects the table OWNER to `tenant_isolation` too, and that policy is
    fail-closed on an unset `app.tenant_id` — so on a deployment whose migration role is
    subject to RLS the SELECT saw nothing, the INSERT wrote nothing, and the statement
    reported success. Production was checked on 1 Sep 2026 and holds one organisation with
    a `kb` policy and NO `copilot_memory` policy: the signature exactly.

    That migration has already run and its revision will never be applied again, so the
    repair rides here. The state is CONSTRUCTED the same way the caller-memory test above
    constructs its own — an organisation with the row deleted IS an organisation that
    predates the migration — because a tenant created today gets the row from
    `DEFAULT_RETENTION_POLICIES` and so proves nothing about the ones that already existed.
    """
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("DELETE FROM retention_policies WHERE data_category = 'copilot_memory'")
        )
        await session.commit()

    async with tenant_session(tenant_id) as session:
        missing = (
            await session.execute(
                text("SELECT count(*) FROM retention_policies WHERE data_category = :c"),
                {"c": "copilot_memory"},
            )
        ).scalar_one()
        # The hole itself, asserted rather than described: without this the test below
        # would pass against a database that never lost the row.
        assert int(missing) == 0
        await session.execute(text(_migration_backfill_sql("copilot_memory")))
        row = (
            await session.execute(
                text("SELECT ttl_days, action FROM retention_policies WHERE data_category = :c"),
                {"c": "copilot_memory"},
            )
        ).first()
        await session.commit()

    assert row is not None, "the repair did not reach an organisation that predates it"
    assert (int(row[0]), str(row[1])) == (180, "delete"), (
        "the repair must write the same pair `scripts/seed.DEFAULT_RETENTION_POLICIES` "
        "declares, or a repaired tenant runs on a clock no seeded tenant runs on"
    )


def test_the_repair_pair_matches_the_seed_it_restores() -> None:
    """The migration retypes 180/`delete` rather than importing it, for the reason every
    migration copies its constants — it must keep meaning what it meant on the day it ran.
    This is the cost of that copy, paid: the two are read and compared, so a change to the
    seed that leaves the repair behind fails here instead of silently splitting old tenants
    from new ones onto different clocks."""
    from scripts.seed import DEFAULT_RETENTION_POLICIES

    seeded = {
        policy["data_category"]: (policy["ttl_days"], policy["action"])
        for policy in DEFAULT_RETENTION_POLICIES
    }
    sql = _migration_backfill_sql("copilot_memory")
    ttl, action = seeded["copilot_memory"]
    assert f"'copilot_memory', {ttl}, '{action}'" in sql
