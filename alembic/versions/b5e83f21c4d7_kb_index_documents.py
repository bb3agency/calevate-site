"""kb_index_documents — what the external search index holds, per published chunk

Revision ID: b5e83f21c4d7
Revises: d7c2f4a91b83
Create Date: 2026-09-15 00:00:00.000000

`docs/PIPECAT-MIGRATION.md` §8 adopts Supermemory (box 3) as the document store behind
`calevate_shared.retrieval.RetrievalProvider`. The adapter could SEARCH it; nothing wrote to
it. This table is what makes the write half convergent instead of hopeful:
`apps/api/retrieval/supermemory_index.py` sends the DIFFERENCE between the live corpus and
these rows, so a publish that failed on the vendor, a withdrawal that failed, and a document
written before anybody thought to record it all end up in the same selectable state.

WHY A TABLE RATHER THAN TWO COLUMNS ON `kb_chunks`. That is the tidier diff — `embed_state`
and `embed_model` already live there for the dense arm — and it loses the one thing this has
to do. Retention DELETEs `kb_sources` rows (`workers/retention._KB_EXPIRE_SQL`, "a DELETE,
not an anonymize"), `kb_documents` and `kb_chunks` cascade with them, and the vendor's copy
does not: the state that says "box 3 still holds this" would be destroyed by the same
statement that made it true. So the reference to the chunk is a PLAIN COLUMN with no foreign
key, and a row whose chunk is gone is exactly the instruction to withdraw the document.

That is also why `document_id` is unique but not a key of anything: it is the id we SEND as
the vendor's `customId` (an ASSUMED contract field), so a delete addresses what an ingest
wrote.

TENANCY. `tenant_id` with the FORCEd `tenant_isolation` policy, verbatim from DATA-MODEL §1,
and a cross-tenant zero-rows test ships with it (hard rule 1). It matters more here than on
an ordinary projection: §8.4 records that the local Supermemory build is single-tenant with
ONE API key, so the container tag is a filter we send rather than a wall the server
enforces — and this table is what decides which documents a delete is allowed to name.

NOT append-only (hard rule 4): the whole content of a row is a claim about another system's
CURRENT state, which changes. The append-only record of what a client published is
`kb_sources`/`kb_documents`, untouched by this.

DOWNGRADE drops the table, and the honest statement of what that costs: the vendor keeps
whatever it was sent and nothing of ours can name it afterwards, so a re-upgrade re-ingests
every live chunk (harmless — the ids are ours and the vendor upserts on them) and can never
withdraw what a deleted source left behind. Exercised up → down → up on a pristine database
rather than assumed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5e83f21c4d7"
down_revision: str | None = "a3f1c6e82d47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns ''
# when unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON kb_index_documents USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "kb_index_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        # The agent and the source this document was published under, as PLAIN COLUMNS for
        # the reason `document_id` is one: both parents cascade away on a retention delete,
        # and a row that vanished with them could not withdraw the vendor's copy.
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        # The chunk this document IS, and the id we send the vendor as its `customId`.
        sa.Column("document_id", sa.UUID(), nullable=False),
        # sha256 of exactly the text that was sent — the chunk's content AND its English
        # gloss, spelled once in `supermemory_index._CONTENT_SHA_SQL`. A late gloss moves
        # this, which is what makes the sweep re-send a document whose key improved.
        sa.Column("content_sha256", sa.Text(), nullable=False),
        # When the vendor last accepted it. Not the difference driver (the digest is) —
        # this is what an operator reads when asking how far behind box 3 is.
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_kb_index_documents_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_index_documents")),
    )
    # ONE ledger row per document. What makes the ingest idempotent in the DATABASE through
    # `ON CONFLICT` rather than in a read-then-write — `uq_kb_chunks_document_id`'s reason,
    # one table over, and here it also stops a republish minting a second row that would
    # make the same document look orphaned.
    op.create_index(
        "uq_kb_index_documents_document_id", "kb_index_documents", ["document_id"], unique=True
    )
    # The difference scans are per tenant and per source, in that order.
    op.create_index(
        op.f("ix_kb_index_documents_tenant_id"), "kb_index_documents", ["tenant_id"]
    )
    op.create_index(
        "ix_kb_index_documents_tenant_source", "kb_index_documents", ["tenant_id", "source_id"]
    )
    op.execute("ALTER TABLE kb_index_documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kb_index_documents FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON kb_index_documents")
    op.drop_index("ix_kb_index_documents_tenant_source", table_name="kb_index_documents")
    op.drop_index(op.f("ix_kb_index_documents_tenant_id"), table_name="kb_index_documents")
    op.drop_index("uq_kb_index_documents_document_id", table_name="kb_index_documents")
    op.drop_table("kb_index_documents")
