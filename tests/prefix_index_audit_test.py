"""The eleven prefix-redundant indexes `f47baad` deferred, decided one table at a time.

`e7c3d10a9f52` dropped `ix_credit_ledger_tenant_id` because it was a strict PREFIX of a
composite and therefore offered no access path the composite did not. Its commit noted
twelve other tables carrying the same pattern and scoped them out, on the grounds that
"most are covered by UNIQUE indexes, which is a different call".

Migration `b9e5d2c74a18` makes that call. The finding is that **uniqueness is not the
discriminator** — the keeper on `deletion_requests` has a non-unique cover, and four of
the nine unique-covered ones are safe. What decides it is btree DEDUPLICATION.

A non-unique index on a repeating column collapses its duplicates into one posting-list
tuple per distinct value (PG16 §67.4.3: "The column key value(s) only appear once in
this representation ... This significantly reduces the storage size of indexes where
each value ... appears several times on average"). A cover whose extra columns make each
entry logically distinct cannot do that — in a unique index deduplication only ever
absorbs "version churn duplicates". So on `leads` the prefix index is 1288 kB against
the unique cover's 23 MB for the same 200k rows, and the planner, offered only the fat
cover for `tenant_id = ...`, correctly prefers a sequential scan of the heap.

That is why seven of the eleven STAY: dropping them does not move the query onto the
cover, it moves the query off indexes altogether. Full per-index measurements are in the
migration docstring.

This file asserts the four PROPERTIES that make the four drops true, and — the point of
having a test at all — that the seven keepers still have the index the measurement said
they needed.

The probe for "does this still reach an index" is `enable_seqscan = off` plus "no Seq
Scan survived", exactly as `credit_ledger_index_prune_test.py` does it and for the same
reason: a bare "must not Seq Scan" assertion measures the table's STATISTICS, so it
fails on an empty table where a sequential scan is the correct plan. `c0ce977` removed
that shape once already; this file does not reintroduce it.

CONCURRENCY: the plan probes mint their own tenant and assert no global counts, so this
file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import json
from typing import Any

from apps.api.agents.models import ExtractionSchema, PromptVersion
from apps.api.crm.models import TranscriptTurn
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.tenancy.models import Membership
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# index -> the index that was measured carrying its plans afterwards.
DROPPED: dict[str, tuple[str, str]] = {
    "ix_transcript_turns_call_id": ("transcript_turns", "uq_transcript_turns_call_id_idx"),
    "ix_prompt_versions_agent_id": ("prompt_versions", "uq_prompt_versions_agent_id_version"),
    "ix_extraction_schemas_agent_id": (
        "extraction_schemas",
        "uq_extraction_schemas_agent_id_version",
    ),
    "ix_memberships_tenant_id": ("memberships", "uq_memberships_tenant_id_user_id"),
}

# The seven that STAY, each with the query shape whose plan collapsed without it. These
# are regression anchors: a future "tidy up the redundant indexes" pass that takes one
# of these fails here with the reason it must not.
KEPT: dict[str, str] = {
    "ix_leads_tenant_id": "leads",
    "ix_call_extractions_tenant_id": "call_extractions",
    "ix_dnc_list_tenant_id": "dnc_list",
    "ix_deletion_requests_tenant_id": "deletion_requests",
    "ix_campaign_contacts_campaign_id": "campaign_contacts",
    "ix_kb_documents_source_id": "kb_documents",
    "ix_kb_sources_agent_id": "kb_sources",
}

# The model attribute each drop had to be removed from as well. A SQL-only drop leaves
# the ORM asking for the index, and the next `alembic revision --autogenerate` recreates
# it — a deprecation that undoes itself in an unrelated revision.
DECLARATIONS: list[tuple[Any, str]] = [
    (TranscriptTurn, "call_id"),
    (PromptVersion, "agent_id"),
    (ExtractionSchema, "agent_id"),
    (Membership, "tenant_id"),
]


async def _index_names(session: AsyncSession, table: str) -> set[str]:
    rows = await session.execute(
        text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = :t"),
        {"t": table},
    )
    return {row[0] for row in rows.all()}


def _nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    found = [plan]
    for child in plan.get("Plans", []):
        found.extend(_nodes(child))
    return found


async def _forced_plan(
    session: AsyncSession, sql: str, params: dict[str, Any]
) -> list[dict[str, Any]]:
    """The plan produced when a sequential scan is priced at `disable_cost`.

    PG16 documents `enable_seqscan = off` as DISCOURAGING rather than forbidding, which
    is what makes this a probe and not a lie: a Seq Scan still present after being
    priced at 1e10 is one the planner had no alternative to.
    """
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    raw = (await session.execute(text(f"EXPLAIN (FORMAT JSON) {sql}"), params)).scalar()
    payload = raw if isinstance(raw, list) else json.loads(str(raw))
    return _nodes(payload[0]["Plan"])


async def test_the_four_measured_redundant_indexes_are_gone() -> None:
    """Read from `pg_indexes`, not from the migration file.

    What matters is the database an operator's queries hit; a migration that was written
    but never applied is exactly the half-wired change this assertion exists to catch.
    """
    async with untenanted_session() as session:
        for index, (table, _) in DROPPED.items():
            names = await _index_names(session, table)
            assert index not in names, (
                f"{index} is still on this database. It is a strict prefix of "
                f"{DROPPED[index][1]}, and migration b9e5d2c74a18 measured every repo "
                f"query against {table} keeping its plan and its buffer count without it."
            )


async def test_every_dropped_column_is_still_indexed_by_a_leading_key() -> None:
    """The claim "redundant" IS the claim "some other index starts with this column".

    Asserted on the catalog's key order rather than on an index name or its definition
    string, so a future index that carries the property in a different shape still
    passes — and so the assertion fails loudly if someone drops the COVER instead.
    """
    async with untenanted_session() as session:
        for index, (table, cover) in DROPPED.items():
            column = index.removeprefix("ix_").removeprefix(f"{table}_")
            rows = await session.execute(
                text(
                    "SELECT i.relname, a.attname FROM pg_index ix "
                    "JOIN pg_class i ON i.oid = ix.indexrelid "
                    "JOIN pg_class c ON c.oid = ix.indrelid "
                    "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ix.indkey[0] "
                    "WHERE c.relname = :t"
                ),
                {"t": table},
            )
            leading = {name for name, first_key in rows.all() if first_key == column}
            assert cover in leading, (
                f"{table}.{column} lost its cover: {cover} no longer leads with it "
                f"(indexes leading with {column}: {leading or 'none'}). Dropping "
                f"{index} was only safe while it did — restore it, or downgrade "
                "b9e5d2c74a18."
            )


def test_the_models_no_longer_ask_for_the_dropped_indexes() -> None:
    """The half a SQL-only drop would have missed.

    `index=True` on a `mapped_column` is a standing request: autogenerate compares the
    model to the database and re-creates whatever the model declares. This was verified
    the way `f47baad` verified it — with the declarations restored, `alembic check`
    emits four `add_index` ops.
    """
    still_declared = [
        f"{model.__tablename__}.{column}"
        for model, column in DECLARATIONS
        for index in model.__table__.indexes
        if [c.name for c in index.columns] == [column] and len(index.expressions) == 1
    ]
    assert not still_declared, (
        f"the ORM still declares a single-column index on {still_declared}: the "
        "composite in __table_args__ already covers the column, and autogenerate will "
        "recreate the index at the next revision"
    )


async def test_the_seven_measured_keepers_are_still_there() -> None:
    """Seven prefix indexes that look redundant and are not, held in place by a test.

    Each of these IS a strict prefix of a composite, so a catalog scan for "redundant
    indexes" flags all seven — and dropping any of them was measured moving its table's
    reads onto a sequential scan or onto multiples of the buffers, because the cover
    cannot deduplicate the repeating leading column and is 4x-18x larger as a result.
    The numbers are in migration b9e5d2c74a18; this assertion is what stops the next
    pass from re-deriving them the expensive way.
    """
    async with untenanted_session() as session:
        missing = {}
        for index, table in KEPT.items():
            if index not in await _index_names(session, table):
                missing[index] = table
    assert not missing, (
        f"these indexes were measured as NOT redundant and have been dropped: {missing}. "
        "Being a prefix of a composite is necessary for redundancy, not sufficient: the "
        "cover has to be cheap enough to scan that the planner still prefers it, and for "
        "these seven it is not (migration b9e5d2c74a18)."
    )


async def test_every_query_shape_on_the_four_tables_still_reaches_an_index() -> None:
    """The regression the drop could actually cause, on rows rather than on an argument.

    One query per dropped index, in the shape the repo issues it, planned with
    sequential scans priced at `disable_cost`. A Seq Scan that survives that is a
    predicate with no index available to it at all — which is the thing removing an
    index can break, and a verdict that does not depend on how many rows this database
    happens to hold.
    """
    tenant_id = uuid7()
    agent_id = uuid7()
    call_id = uuid7()
    user_id = uuid7()
    offenders: dict[str, list[str]] = {}

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Prefix index audit', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": f"prefix-audit-{tenant_id.hex[:12]}"},
        )
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, engine, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, caller_memory_notice_line, name, "
                "direction, language_primary, status, created_at, updated_at) VALUES (:aid, "
                ":tid, 'fake', 'This is an AI assistant.', 'This is an AI assistant.', 'This "
                "call is being recorded.', 'I keep a short note of what you ask about.', 'Audit "
                "agent', 'inbound', 'te-IN', 'draft', now(), now())"
            ),
            {"aid": agent_id, "tid": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "created_at, updated_at) VALUES (:cid, :tid, :aid, :ref, 'inbound', 'completed', "
                "now(), now())"
            ),
            {"cid": call_id, "tid": tenant_id, "aid": agent_id, "ref": f"audit-{call_id.hex[:12]}"},
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "created_at, updated_at) SELECT gen_random_uuid(), :tid, :cid, g, 'agent', "
                "'turn', now(), now() FROM generate_series(1, 40) g"
            ),
            {"tid": tenant_id, "cid": call_id},
        )
        await session.execute(
            text(
                "INSERT INTO prompt_versions (id, tenant_id, agent_id, version, body, "
                "created_at, updated_at) SELECT gen_random_uuid(), :tid, :aid, g, 'body', "
                "now(), now() FROM generate_series(1, 40) g"
            ),
            {"tid": tenant_id, "aid": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO extraction_schemas (id, tenant_id, agent_id, version, fields, "
                "created_at, updated_at) SELECT gen_random_uuid(), :tid, :aid, g, "
                "'[]'::jsonb, now(), now() FROM generate_series(1, 40) g"
            ),
            {"tid": tenant_id, "aid": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:uid, :em, now(), now())"
            ),
            {"uid": user_id, "em": f"{user_id.hex[:12]}@a.test"},
        )
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :tid, :uid, 'owner', now(), now())"
            ),
            {"tid": tenant_id, "uid": user_id},
        )

        probes: dict[str, tuple[str, str, dict[str, Any]]] = {
            "transcript detail (crm/service.py:204)": (
                "transcript_turns",
                "SELECT idx, speaker, text_redacted FROM transcript_turns "
                "WHERE call_id = :cid ORDER BY idx",
                {"cid": call_id},
            ),
            "next prompt version (agents/prompts.py:129)": (
                "prompt_versions",
                "SELECT COALESCE(max(version), 0) FROM prompt_versions WHERE agent_id = :aid",
                {"aid": agent_id},
            ),
            "lead columns (crm/service.py:274)": (
                "extraction_schemas",
                "SELECT fields FROM extraction_schemas WHERE agent_id = :aid "
                "ORDER BY version DESC LIMIT 1",
                {"aid": agent_id},
            ),
            "owner notification target (workers/whatsapp.py:289)": (
                "memberships",
                "SELECT user_id FROM memberships WHERE tenant_id = :tid AND role = 'owner' "
                "ORDER BY created_at LIMIT 1",
                {"tid": tenant_id},
            ),
        }
        for caller, (table, sql, params) in probes.items():
            survivors = [
                node["Node Type"]
                for node in await _forced_plan(session, sql, params)
                if node.get("Relation Name") == table and "Seq Scan" in str(node.get("Node Type"))
            ]
            if survivors:
                offenders[caller] = survivors

        await session.rollback()

    assert not offenders, (
        "these queries have no index available to them with sequential scans priced at "
        f"disable_cost: {offenders}. A drop in b9e5d2c74a18 left a surface without a "
        "plan — downgrade it, or index the predicate that lost its index."
    )
