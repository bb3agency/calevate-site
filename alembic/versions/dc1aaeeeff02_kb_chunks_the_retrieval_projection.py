"""kb chunks: the retrieval projection, with pgvector

Revision ID: dc1aaeeeff02
Revises: f2c81a4d05e7
Create Date: 2026-09-01 00:00:00.000000

`kb_chunks` — the table `docs/DATA-MODEL.md` §7 has specified as CONTINGENCY since D-28 and
which D-502 now adopts, plus the `vector` extension it needs. One row per PUBLISHED chunk,
carrying the two retrieval keys (a `tsvector` and a 1536-dimension embedding) and the scope
a query filters on. FORCEd RLS in this same migration (hard rule 1), and a backfill so an
account that published knowledge before today is searchable without republishing.

--------------------------------------------------------------------------------
WHY A SECOND TABLE AND NOT TWO MORE COLUMNS ON `kb_documents`
--------------------------------------------------------------------------------
`kb_documents` is what a client SUBMITTED: it holds a row from the moment text is pasted,
long before anyone approves it, and its scope lives one join away on `kb_sources`
(`agent_id`, `is_active`). `kb_chunks` is what is RETRIEVABLE. The difference buys two
properties that columns on `kb_documents` could not have:

1. **The approval gate becomes structural rather than remembered.** A row exists here only
   because `kb/service.publish_source` put it here, in the transaction that published an
   APPROVED source. A retrieval query therefore cannot reach unapproved text by forgetting
   a predicate — the same argument `retrieval/compiled_facts.py` makes for reading the
   compiled block instead of `kb_documents`, applied to the store.
2. **The measured query plan depends on `(tenant_id, agent_id, is_active)` being ONE btree
   on ONE table.** `docs/evidence/kb-retrieval-bakeoff.md` §2.3(b) measured that Postgres
   serves the multi-tenant case by that btree and an EXACT sort, never entering the HNSW
   graph — perfect recall, and the reason the pre-0.8.0 filtered-scan hazard did not occur
   in 500 trials at any size. Denormalising the scope is what makes that index possible;
   with the scope on `kb_sources` the same query is a join and the plan is not the one that
   was measured.

**AND IT STORES NO CONTENT.** `content` is on `kb_documents` and stays there, reached
through `document_id`. Copying a client's prose into a second table would double the bytes
retention and backups pay for, create two rows a DPDP erasure has to find, and make a
correction to one an invisible divergence from the other. What lives here is DERIVED —
lexemes and a vector — and every byte of it is reconstructible from `kb_documents`, which
is what makes `downgrade` lossless.

--------------------------------------------------------------------------------
THE EXTENSION, AND THE VERSION FLOOR THIS DELIBERATELY DOES NOT SET
--------------------------------------------------------------------------------
`CREATE EXTENSION IF NOT EXISTS vector`. It is NOT a trusted extension (its control file
carries no `trusted = true`, read from `/usr/share/postgresql/16/extension/vector.control`
on 1 Sep 2026), so it needs a superuser once per database. The migration runs as the OWNER
role, which is superuser on the dev cluster and may not be in production, so a missing
extension is refused with the exact statement an operator must run rather than with
`InsufficientPrivilege` out of context (errors are part of the interface).

**`vector(1536)`, NOT `halfvec`, AND THE REASON IS MEASURED RATHER THAN PREFERRED.**
`halfvec` arrived in pgvector **0.7.0** and iterative index scans in **0.8.0**
(VERIFIED-VENDOR-DOCS: pgvector `CHANGELOG.md` @ `master`, fetched from
`raw.githubusercontent.com` 1 Sep 2026). The server this repository actually runs against
offers **0.6.0** and nothing newer is packaged for it (`pg_available_extensions` and
`apt-cache policy postgresql-16-pgvector`, MEASURED-HERE 1 Sep 2026), so a `halfvec` column
would fail here and pass in CI, which is the worst of both. Three further reasons make full
precision the right answer even after an upgrade, so this is not a stopgap:

* **Quantisation belongs in the INDEX, not in the column.** pgvector's own README documents
  half-precision *indexing* — `CREATE INDEX ... USING hnsw ((embedding::halfvec(1536))
  halfvec_cosine_ops)` (`README.md:558-569`, same fetch) — which halves the graph with no
  table rewrite and no re-embedding, and can be added or dropped later. A `halfvec` COLUMN
  is a lossy store; the index cast is a lossy *search* over an exact store.
* **The exit clause depends on it.** The founder's condition for adopting pgvector is that
  moving to a managed vendor stays cheap. A managed vendor ingests float32; exporting from
  a half-precision column would ship rounded vectors and make the migrated index measurably
  worse than a re-embed, which is the expensive outcome this choice exists to avoid.
* **There is nothing to save yet.** §2.3(b) measured that the HNSW graph is not entered at
  our corpus sizes, so its memory footprint is not on any hot path today.

`hnsw.iterative_scan` is likewise NOT set anywhere, and the reason is sharper than
unavailability: on 0.6.0 `SET hnsw.iterative_scan = 'relaxed_order'` **succeeds silently**
as an unvalidated GUC placeholder and does nothing (MEASURED-HERE 1 Sep 2026 — so does
`SET hnsw.total_nonsense = 'banana'`). A safety control that reads as applied and is not is
worse than its absence, so the repo has none of it and `retrieval/pgvector.py` says what it
would take to earn one.

--------------------------------------------------------------------------------
THE INDEXES
--------------------------------------------------------------------------------
* `ix_kb_chunks_scope` — `(tenant_id, agent_id, is_active)`, the DATA-MODEL btree and the
  one the measured plan uses. Leading `tenant_id` because no query omits it (RLS aside, the
  adapter re-states it).
* `ix_kb_chunks_tsv` — GIN, the sparse arm.
* `ix_kb_chunks_embedding` — HNSW `vector_cosine_ops`, `m = 16`, `ef_construction = 64`.
  Built `CONCURRENTLY` in its own transaction because §2.3(c) measured an **11.3-minute**
  build at 100k rows under a stock `maintenance_work_mem`: an ACCESS EXCLUSIVE lock for
  that long on a live table is an outage. It is empty at creation here (the column is NULL
  until the sweep runs), so the build is instantaneous on any existing deployment — but the
  statement has to be right for the deployment where it is not.
* `ix_kb_chunks_embed_pending` — partial on `embed_state = 'pending'`, so the sweep's work
  list is a catalogue-sized index that SHRINKS to empty as the backlog drains rather than
  growing with the corpus. `a7f4c31d95e8`'s shape, for its reason.

--------------------------------------------------------------------------------
RLS, AND THE BACKFILL THAT RUNS UNDER THE OWNER
--------------------------------------------------------------------------------
`ENABLE` + `FORCE ROW LEVEL SECURITY` with the standard `tenant_isolation` policy, in this
migration (hard rule 1), and `kb_chunks` joins `db/registry.TENANT_TABLES` so the RLS
coverage guard counts it. `tests/kb_chunks_rls_test.py` is the cross-tenant zero-rows test
the rule also asks for, in both directions.

The backfill runs BEFORE the policy exists, deliberately: it is one fleet-wide statement
over every currently-published source, and the owner role is the only session that can see
them all (`b2e6f10c94d7`'s precedent). It writes `tsv` and leaves `embedding` NULL with
`embed_state = 'pending'` — the sweep is what fills those, and until it does the sparse arm
answers alone, which is a weaker result and never a wrong one.

--------------------------------------------------------------------------------
REVERSIBILITY (hard rule 8)
--------------------------------------------------------------------------------
`downgrade` drops the table and leaves the extension installed — dropping `vector` would
fail on any other database object using it and is not this migration's to decide. Every
byte dropped is derived from `kb_documents`, which is untouched, so re-running `upgrade`
plus the sweep reconstructs the table exactly.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from apps.api.retrieval.embedding import EMBEDDING_DIMS

revision: str = "dc1aaeeeff02"
down_revision: str | None = "f2c81a4d05e7"
branch_labels: str | None = None
depends_on: str | None = None

TABLE = "kb_chunks"

#: The text-search configuration BOTH the stored lexemes and every query use. It must be
#: one name: a `tsvector` built under one configuration and a `tsquery` built under another
#: silently fail to match, and the failure is an empty result rather than an error.
#:
#: **`english` RATHER THAN `simple`, AND IT IS SAFE FOR TELUGU — MEASURED, NOT ASSUMED.**
#: `to_tsvector('english', <Telugu sentence>)` is BYTE-IDENTICAL to `to_tsvector('simple',
#: …)` on this server (MEASURED-HERE 1 Sep 2026): the English snowball stemmer strips ASCII
#: suffixes, which a Telugu token has none of, and no English stop word collides with one.
#: What the English configuration buys is the half that matters for the query form this
#: product actually receives — it stems `costs` to `cost`, so "what does a consultation
#: cost" matches "A consultation costs 500 rupees", which under `simple` returns NOTHING.
#: That is the exact failure `retrieval/compiled_facts._singular` exists to hand-fix on the
#: T0 ranker, solved here by the database instead of by a second rule of ours.
TS_CONFIG = "english"

#: The chunk's own text and its ENGLISH GLOSS, concatenated into one `tsvector`. The gloss
#: is a RETRIEVAL KEY (D-489, `apps/api/kb/gloss.py`), so it belongs in the search vector
#: and never in a result — `retrieval/pgvector.py` returns `kb_documents.content` and never
#: this. `coalesce` because most chunks have no gloss and `||` with NULL would erase the
#: whole vector.
TSV_SQL = (
    f"to_tsvector('{TS_CONFIG}', d.content) || "
    f"to_tsvector('{TS_CONFIG}', coalesce(d.gloss, ''))"
)

_POLICY = (
    f"CREATE POLICY tenant_isolation ON {TABLE} USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)

#: Every published chunk that has no projection yet. Also the sweep's self-healing statement
#: — `kb/service.publish_source` writes these rows transactionally, so this can only ever
#: find rows that predate the feature; it is written once, here, and read from the worker so
#: the two cannot drift.
_BACKFILL = f"""
INSERT INTO kb_chunks (id, tenant_id, agent_id, source_id, document_id, tsv, version, is_active)
SELECT gen_random_uuid(), d.tenant_id, s.agent_id, s.id, d.id, {TSV_SQL}, s.version, true
FROM kb_documents d
JOIN kb_sources s ON s.id = d.source_id
WHERE s.is_active = true
ON CONFLICT (document_id) DO NOTHING
"""


def upgrade() -> None:
    _require_vector_extension()
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tsv", sa.dialects.postgresql.TSVECTOR(), nullable=False),
        # NULLABLE, and that is the design rather than a concession: a chunk is searchable
        # by its sparse arm the instant it is published and gains its dense arm when the
        # sweep reaches it. A NOT NULL column here would make publishing depend on a
        # provider being up.
        # `Vector` from the `pgvector` package (already a dependency of `apps/api` and
        # `apps/workers`), at the ONE width `retrieval/embedding.EMBEDDING_DIMS` defines —
        # imported rather than spelled, because a column built at one width and searched at
        # another is not an error Postgres reports on the unlucky path, it is a silently
        # wrong ranking.
        sa.Column("embedding", Vector(EMBEDDING_DIMS), nullable=True),
        sa.Column("embed_model", sa.Text(), nullable=True),
        sa.Column("embed_dim", sa.Integer(), nullable=True),
        # THE IDEMPOTENCY KEY of `apps/workers/kb_embeddings.py`, and it is a column for
        # `kb_documents.gloss_state`'s reason: `embedding IS NULL` cannot distinguish
        # "nobody has looked at this" from "looked at and the provider is refusing it", so a
        # sweep keyed on the vector alone would re-pay for the same failure on every tick.
        sa.Column(
            "embed_state", sa.String(), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("chunk_meta", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_chunks")),
        # ONE PROJECTION PER CHUNK, enforced by the database. It is what makes both the
        # publish path and the backfill idempotent by `ON CONFLICT` rather than by a
        # read-then-write, and it is the reason a republished source cannot accumulate
        # duplicate rows that would each take a slot in the top-k.
        sa.UniqueConstraint("document_id", name=op.f("uq_kb_chunks_document_id")),
        sa.CheckConstraint(
            "embed_state IN ('pending', 'ready', 'refused')",
            name=op.f("ck_kb_chunks_embed_state_enum"),
        ),
    )
    op.create_index(op.f("ix_kb_chunks_scope"), TABLE, ["tenant_id", "agent_id", "is_active"])
    op.execute("CREATE INDEX ix_kb_chunks_tsv ON kb_chunks USING gin (tsv)")
    op.create_index(
        op.f("ix_kb_chunks_embed_pending"),
        TABLE,
        ["tenant_id"],
        postgresql_where=sa.text("embed_state = 'pending'"),
    )

    # NOT VALID then VALIDATE — `d5b8a2c60e17`'s locking shape. `organizations` RESTRICT
    # because offboarding is an explicit workflow and never a cascade (`db/base.TenantMixin`);
    # `kb_documents` and `kb_sources` CASCADE because this table is a PROJECTION of them —
    # a chunk whose text has been erased under DPDP must not leave its lexemes and its
    # vector behind, and RESTRICT would make the projection block the erasure it exists to
    # follow.
    for statement in (
        f"ALTER TABLE {TABLE} ADD CONSTRAINT fk_kb_chunks_tenant_id_organizations "
        "FOREIGN KEY (tenant_id) REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID",
        f"ALTER TABLE {TABLE} ADD CONSTRAINT fk_kb_chunks_document_id_kb_documents "
        "FOREIGN KEY (document_id) REFERENCES kb_documents (id) ON DELETE CASCADE NOT VALID",
        f"ALTER TABLE {TABLE} ADD CONSTRAINT fk_kb_chunks_source_id_kb_sources "
        "FOREIGN KEY (source_id) REFERENCES kb_sources (id) ON DELETE CASCADE NOT VALID",
        f"ALTER TABLE {TABLE} ADD CONSTRAINT fk_kb_chunks_agent_id_agents "
        "FOREIGN KEY (agent_id) REFERENCES agents (id) ON DELETE CASCADE NOT VALID",
    ):
        op.execute(statement)
    for constraint in (
        "fk_kb_chunks_tenant_id_organizations",
        "fk_kb_chunks_document_id_kb_documents",
        "fk_kb_chunks_source_id_kb_sources",
        "fk_kb_chunks_agent_id_agents",
    ):
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {constraint}")

    # The reach backwards, under the owner role — the only session that sees every tenant.
    # Without it, every account that published knowledge before today is invisible to search
    # until it republishes, which is a silent gap rather than an error.
    op.execute(_BACKFILL)

    # Hard rule 1, in the same migration as the table it protects.
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)

    # LAST, and outside the transaction. `CREATE INDEX CONCURRENTLY` cannot run inside one;
    # `autocommit_block` is Alembic's own escape hatch for exactly this statement. It is
    # last so that a failure here leaves a table that WORKS — every query in
    # `retrieval/pgvector.py` is served by the btree and the GIN index, and the bake-off
    # measured that the HNSW graph is not entered at our sizes anyway. An operator re-runs
    # the one statement; nobody re-runs the migration.
    with op.get_context().autocommit_block():
        op.execute(_HNSW_INDEX_SQL)


#: THE HNSW INDEX, BUILT OUTSIDE THE MIGRATION TRANSACTION.
#:
#: `CREATE INDEX CONCURRENTLY` cannot run inside a transaction block and Alembic wraps every
#: migration in one, so `upgrade` runs it inside `autocommit_block()`. It is built
#: concurrently rather than plainly because §2.3(c) measured an **11.3-minute** build at
#: 100k rows: on a fresh table (which this always is at migration time) either form is
#: instant, but the statement has to be the one that is also correct on a REBUILD, and a
#: reader who copies a non-concurrent form onto a populated table gets an outage.
#:
#: `m = 16` and `ef_construction = 64` are pgvector's own documented starting point
#: (`README.md`, "Index Options", read from `raw.githubusercontent.com` 1 Sep 2026). They
#: are not tuned, because there is nothing to tune against: the bake-off measured that the
#: planner does not enter this graph at our corpus sizes (§2.3(b)), so any tuning today
#: would be fitting parameters to a code path nothing executes. `ef_construction` is the one
#: to raise first when it does — it costs build time and nothing at query time.
_HNSW_INDEX_SQL = (
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_kb_chunks_embedding ON kb_chunks "
    "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
)


def _require_vector_extension() -> None:
    """Install `vector`, or refuse with the statement a human must run.

    `CREATE EXTENSION` needs a superuser here (the extension is not marked `trusted`), and
    the migration role is not guaranteed to be one in production. Attempting it and letting
    `InsufficientPrivilege` escape would report a permissions error on a `CREATE EXTENSION`
    the reader did not write; this reports the one action that fixes it.
    """
    bind = op.get_bind()
    installed = bind.execute(
        sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    ).first()
    if installed is not None:
        return
    available = bind.execute(
        sa.text("SELECT default_version FROM pg_available_extensions WHERE name = 'vector'")
    ).first()
    if available is None:
        raise RuntimeError(
            "pgvector is not available on this PostgreSQL server, so kb_chunks cannot be "
            "created. Install the server package (Debian/Ubuntu: postgresql-16-pgvector; "
            "the pgvector/pgvector:pg16 image ships it) and re-run this migration."
        )
    try:
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception as failure:  # pragma: no cover - exercised only without superuser
        raise RuntimeError(
            "pgvector is available but this role may not install it. Run "
            "`CREATE EXTENSION vector;` in the calevate database as a superuser, then "
            "re-run this migration."
        ) from failure


def downgrade() -> None:
    # The index goes with the table; it is named here only so a reader can see that nothing
    # is left behind. The EXTENSION is deliberately not dropped: `DROP EXTENSION vector`
    # fails if any other object uses it, and whether this deployment still wants it is not
    # this migration's question to answer.
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_table(TABLE)
