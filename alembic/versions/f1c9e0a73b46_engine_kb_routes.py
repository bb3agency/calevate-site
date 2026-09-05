"""engine_kb_routes: the claim that ties one vendor knowledge base to one tenant

Revision ID: f1c9e0a73b46
Revises: b7e35c2f81da
Create Date: 2026-09-03

D-519. The mapping moves out of `kb_documents.meta ->> 'engine_kb_ref'` and into a table
of its own, for three reasons that a JSONB key on a FORCE-RLS table cannot satisfy.

--------------------------------------------------------------------------------
1. THE QUESTION THAT MATTERS MOST IS CROSS-TENANT AND WAS THEREFORE UNASKABLE
--------------------------------------------------------------------------------
We run ONE Bolna account for every tenant, and the vendor's knowledge base is an
ACCOUNT-LEVEL object with no owner field of any kind: `POST /knowledgebase` takes no agent
id, and a listing row carries exactly `rag_id`, `file_name`, `humanized_created_at`,
`created_at`, `updated_at`, `vector_id`, `status`, `chunk_size`, `similarity_top_k` and
`language_support` (`bolna-findings/mirror/pages/api-reference/knowledgebase/
get_knowledgebases.md:63-121`). So every client's documents are interleaved in one flat
pool and the ONLY thing tying one of them to a tenant is what WE record.

"Which of the objects on this account does no tenant of ours claim?" is therefore the
question that decides whether a client's document — which may hold their customers' names
and numbers — is reachable by any erasure path at all. It is inherently cross-tenant, and
`kb_documents` and `kb_sources` are both FORCE-RLS'd, so it could not be asked of them
without an RLS exemption on the tables that hold the client's actual content. This is
exactly the argument `fa06ed03b49d` made for `engine_agent_routes` and `b2e6f10c94d7` made
for `retention_worklist`, and the answer is the same: a deliberately global, deliberately
boring table of opaque ids, so the content tables stay shut.

--------------------------------------------------------------------------------
2. UNIQUENESS, WHICH A JSONB KEY CANNOT ENFORCE
--------------------------------------------------------------------------------
Nothing stopped two sources — two tenants' sources — recording the SAME handle. That is
not hypothetical: `attach_kb`'s own comment records that the throttle ladder can retry a
create whose response was lost, and any path that copies a handle from one row to another
lands in the same place. A detach then deletes a vendor object a second row still points
at, and the second tenant's agent silently loses knowledge our tables say is live.
`pk (engine, engine_kb_ref)` makes that a constraint violation instead of a silent loss,
and `uq (source_id)` states the other half — a source is pushed to the engine as ONE
document, so it holds at most one vendor object at a time.

--------------------------------------------------------------------------------
3. IT WAS UNINDEXED
--------------------------------------------------------------------------------
`meta ->> 'engine_kb_ref'` has no index, expression or otherwise. Every read walked
`kb_documents` — the largest table in this feature, one row per CHUNK per version — to find
at most one string.

--------------------------------------------------------------------------------
WHY THIS TABLE HAS NO FOREIGN KEY TO `kb_sources`, WHICH IS THE DELIBERATE PART
--------------------------------------------------------------------------------
`ON DELETE CASCADE` is the obvious choice and it is the wrong one. A route row is a claim
on a VENDOR object that outlives our own rows: when the retention sweep or a tenant erasure
deletes `kb_sources`, a cascade would delete the only record that can address the vendor's
copy — at exactly the moment we are promising a client their data is gone. So the claim
stays, and `kb/orphans.py` reports a route whose source no longer resolves as an object a
human must delete at the vendor. `engine_agent_routes` carries no FK either, for the same
family of reason.

--------------------------------------------------------------------------------
THE POLICY IS `engine_agent_routes`'s, VERBATIM IN SHAPE (c4b70e928a1f)
--------------------------------------------------------------------------------
    engine_kb_routes_global_read   FOR SELECT  USING (true)
    tenant_isolation               FOR ALL     USING/WITH CHECK
                                               (tenant_id = GUC OR GUC IS NULL)

Permissive policies are OR'd per command and `FOR SELECT` participates only in SELECT, so
the read is global — which is the whole point — while INSERT/UPDATE/DELETE see only the
tenant policy. Without the second one, a session scoped to tenant A could delete or
re-tenant tenant B's claim on a vendor object, which is the same widening `e4f2a86b13d7`
fixed on `dnc_list`.

--------------------------------------------------------------------------------
THE BACKFILL, AND THE RLS BRACKET IT NEEDS
--------------------------------------------------------------------------------
It SELECTs from `kb_documents`, `kb_sources` and `agents`, all three FORCE-RLS, and then
UPDATEs `kb_documents` to remove the keys it has moved. Under FORCE RLS the owner is
subject to `tenant_isolation`, which is fail-closed on an unset `app.tenant_id`, so every
one of those statements would match ZERO rows and report success
(`tests/migration_rls_bracket_test.py`). The `NO FORCE` / `FORCE` bracket is written one
statement per table rather than looped, because a loop builds the statement from a variable
and makes the mitigation invisible to that guard and to a human grepping for it.

`engine` is taken from `engine_agent_routes` where the agent has one, because that is the
value the publish path actually wrote (`engine.name`, the process-wide selection — NOT the
per-agent `agents.engine` column, which `get_engine()` does not consult), and it falls back
to `agents.engine` (NOT NULL) for an agent with no route row. The subselect is ORDERed
rather than a bare LIMIT because an agent can hold several route rows once experiment arms
exist, and a migration may not depend on which one the planner happens to return.

The downgrade is REAL: it writes both keys back into `kb_documents.meta` before dropping
the table, so the data survives a round trip in either direction.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1c9e0a73b46"
down_revision: str | None = "e9b24c73f105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "engine_kb_routes"
READ_POLICY = "engine_kb_routes_global_read"
WRITE_POLICY = "tenant_isolation"

# Spelled out rather than imported: a migration is a snapshot of the schema on the day it
# ran. NULLIF on the empty string is the repo-wide form — `SET LOCAL app.tenant_id = ''`
# must read as "no tenant", not fail the ::uuid cast.
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT_OR_OPS = f"(tenant_id = ({_GUC})::uuid OR {_GUC} IS NULL)"

#: Every FORCE-RLS table this migration reads or writes. See the docstring.
_BRACKETED = ("kb_documents", "kb_sources", "agents")

_BACKFILL = """
INSERT INTO engine_kb_routes
    (engine, engine_kb_ref, tenant_id, agent_id, source_id, digest, created_at, updated_at)
SELECT COALESCE(
           (SELECT r.engine FROM engine_agent_routes r
             WHERE r.agent_id = s.agent_id ORDER BY r.created_at, r.engine LIMIT 1),
           a.engine),
       d.meta ->> 'engine_kb_ref', s.tenant_id, s.agent_id, s.id,
       d.meta ->> 'engine_kb_digest', now(), now()
FROM kb_documents d
JOIN kb_sources s ON s.id = d.source_id
JOIN agents a ON a.id = s.agent_id
WHERE d.idx = 0 AND d.meta ->> 'engine_kb_ref' IS NOT NULL
ON CONFLICT DO NOTHING
"""

#: Idempotent by its own predicate: once no first chunk carries the key, it matches nothing.
_CLEAR_META = """
UPDATE kb_documents SET meta = meta - 'engine_kb_ref' - 'engine_kb_digest'
WHERE idx = 0 AND meta ? 'engine_kb_ref'
"""

#: The reverse, so the downgrade is a real one rather than a `DROP TABLE` that loses the
#: only record of what the vendor is holding.
_RESTORE_META = """
UPDATE kb_documents d SET meta = coalesce(d.meta, '{}'::jsonb) || jsonb_strip_nulls(
    jsonb_build_object('engine_kb_ref', to_jsonb(r.engine_kb_ref),
                       'engine_kb_digest', to_jsonb(r.digest)))
FROM engine_kb_routes r
WHERE r.source_id = d.source_id AND d.idx = 0
"""


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("engine", sa.Text(), nullable=False),
        # The VECTOR id, which is the handle an agent references and the one thing both
        # halves of an attach can be addressed by (`engine/bolna.py::attach_kb`). The
        # `rag_id` the DELETE route takes is NOT stored: it is recoverable from the
        # account listing, and a second vendor identifier above the adapter would be a
        # vendor payload shape crossing the boundary (hard rule 2).
        sa.Column("engine_kb_ref", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        # The digest of the document this handle was minted from — the idempotency key
        # `publish_source`'s re-upload guard compares. It travels with the handle because
        # it is a fact about the VENDOR's copy, not about our chunks.
        sa.Column("digest", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("engine", "engine_kb_ref", name=op.f("pk_engine_kb_routes")),
        # ONE VENDOR OBJECT PER SOURCE, FULL STOP — `engine` is deliberately NOT part of
        # this key. A source is pushed to the engine as one document and every read asks
        # "what is this source filed as", never "what is it filed as on engine X": the
        # engine a publish used is `get_engine()`, a process-wide setting, and keying the
        # claim to that string would strand every existing claim the day an adapter is
        # renamed or the setting moves. `engine` stays on the row because the orphan sweep
        # must know WHICH account holds the object; it is not part of its identity here.
        sa.UniqueConstraint("source_id", name=op.f("uq_engine_kb_routes_source")),
    )
    op.create_index("ix_engine_kb_routes_agent", TABLE, ["agent_id"])
    op.create_index("ix_engine_kb_routes_tenant", TABLE, ["tenant_id"])
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    # FORCE so the guarantee holds for the table owner too — without it the owner is
    # exempt and the policy is a suggestion (hard rule 1).
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {READ_POLICY} ON {TABLE} FOR SELECT USING (true)")
    op.execute(
        f"CREATE POLICY {WRITE_POLICY} ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT_OR_OPS} WITH CHECK {_OWN_TENANT_OR_OPS}"
    )

    op.execute("ALTER TABLE kb_documents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kb_sources NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(_BACKFILL)
        op.execute(_CLEAR_META)
    finally:
        op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE kb_sources FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE kb_documents FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE kb_documents NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(_RESTORE_META)
    finally:
        op.execute("ALTER TABLE kb_documents FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {WRITE_POLICY} ON {TABLE}")
    op.execute(f"DROP POLICY IF EXISTS {READ_POLICY} ON {TABLE}")
    op.drop_index("ix_engine_kb_routes_tenant", table_name=TABLE)
    op.drop_index("ix_engine_kb_routes_agent", table_name=TABLE)
    op.drop_table(TABLE)
