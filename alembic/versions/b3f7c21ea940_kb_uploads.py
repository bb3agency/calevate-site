"""kb_uploads: the file, the photo and the link a client actually has

Revision ID: b3f7c21ea940
Revises: a8d3f61c04e7
Create Date: 2026-09-04

D-534. `/c/{slug}/knowledge` offered a client a title box and a text box, so the only way
to teach an agent a price list was to retype it. This table is the row behind an UPLOAD —
a PDF, a Word file, a spreadsheet, a photograph of a laminated menu, or a link — and it is
deliberately a SIDE TABLE on `kb_sources` rather than a second knowledge system.

--------------------------------------------------------------------------------
WHY 1:1 WITH `kb_sources` AND NOT A TABLE OF ITS OWN LIFE
--------------------------------------------------------------------------------
Everything that already decides what an agent may say is keyed on a `kb_sources` version:
the approval gate (`status`, `approved_at`, `approved_by`), the versioning and rollback
(FLOWS §7), the retention sweep's knowledge arm, the vendor-object claim
(`engine_kb_routes.source_id`, D-519) and the publish path's lock, digest guard and
detach-then-activate ordering. An upload that lived outside that would need a second copy
of all six, and the two would disagree — starting with the one that matters most:
`kb/service._reconcile_engine_state` REFUSES to publish onto an agent holding a vendor
knowledge base no row of ours accounts for, and it asks `recorded_handles_of_agent`, which
reads `engine_kb_routes` through `kb_sources`. An upload attached outside that join would
have made every subsequent text publish fail with `kb_engine_out_of_sync`, correctly.

So an upload IS a knowledge source version, and this table carries only what is true of an
uploaded ORIGINAL and of nothing else: what kind it is, where the bytes are, what we
handed the engine, and how far along it got. `submitted_by`, the review state and the live
flag are NOT duplicated here — they are `kb_sources`' columns and stay its columns.

--------------------------------------------------------------------------------
WHAT AN UPLOAD BECOMES, PER KIND — AND WHY IT IS NOT ONE ANSWER
--------------------------------------------------------------------------------
* **PDF** — the client's own bytes ARE the published document. `document_key` points at
  them, and what a reviewer approves is the file itself, opened through
  `GET /v1/kb/uploads/{id}/original`. Nothing re-renders it: rendering a second document
  from a file a human already read would publish something nobody signed.
* **URL** — the ENGINE scrapes the page. There is nothing of ours to store, and
  `document_key` stays null.
* **Everything else** (Word, plain text, CSV, spreadsheets, photographs) — the conversion
  lane extracts TEXT (`calevate_shared.document_ingest`), the text is chunked into
  `kb_documents` like any pasted knowledge, a human reads the chunks, and the EXISTING
  renderer makes the PDF at publish. `document_key` stays null for these too: they reach
  the engine by the path pasted text has always taken.

  That is the conversion lane's decision and it is the right one: the alternative — a PDF
  made straight from an unread upload — routes a client's own bytes around the approval
  gate, and adds a second way to make a PDF beside `kb/pdf_render.py`, which the whole
  publish path (digest guard, size ceiling, marker traceability) is already built around.

--------------------------------------------------------------------------------
WHAT IS DELIBERATELY NOT A COLUMN: `rag_id`
--------------------------------------------------------------------------------
The vendor mints two identifiers for one knowledge base — a `rag_id` from the create and a
`vector_id` an agent must reference — and only the second is stored, in
`engine_kb_routes.engine_kb_ref`, exactly as `f1c9e0a73b46` decided and for its reason: a
second vendor identifier above the adapter is a vendor payload shape crossing hard rule 2's
wall, and it is recoverable from the account listing at the one call site that needs it
(`engine/bolna.py::_rag_id_of`, used by `detach_kb`). Storing it here would be a second
answer to "how is this filed at the vendor" that no code path reads and that a rename would
strand. `ingest_status` says how far the vendor got; the handle stays where handles live.

--------------------------------------------------------------------------------
`ingest_status`, AND WHY THE VENDOR'S THREE WORDS ARE IN IT VERBATIM
--------------------------------------------------------------------------------
    received               the bytes are ours; nothing has been asked of the engine yet
    converting             a reader (or the OCR leg) is taking the text out of it
    conversion_unavailable this deployment has no reader for that kind — an OPERATOR fixes
                           it, so a sweep must not retry it for ever
    conversion_failed      this object could not be read (corrupt, encrypted, empty, huge)
    processing             handed to the engine, indexing, no `vector_id` yet
    processed              indexed, `vector_id` recorded, referenced by the agent
    error                  the engine refused it, or we did

`processing` / `processed` / `error` are the vendor's own vocabulary for a knowledge base
(the citation lives with the wire constants in `apps/api/engine/`), spelled the same way on
purpose: the value a client reads on their screen is the value the engine reported, not a
paraphrase somebody would have to keep in step. The four before them are OURS and describe
the half of the journey that happens before the engine has heard of the file.

--------------------------------------------------------------------------------
THE LINK COLUMNS
--------------------------------------------------------------------------------
A link is scraped BY THE VENDOR (`POST /knowledgebase` takes a `url`), so `document_key` is
null for one — there is nothing of ours to upload. `content_digest`, `last_checked_at` and
`change_detected_at` exist because the founder's decision is that links are re-scraped on a
schedule and flagged when the content moves materially, and the vendor tells us nothing
about what it scraped. So we fetch the page ourselves — through the SSRF gate every
outbound fetch in this repo goes through (`integrations/egress_guard.py`) — hash the text,
and compare. The fetch is for CHANGE DETECTION only: what the engine indexes is still what
the engine scrapes.

A material change does NOT edit anything live. It submits a NEW VERSION of the same named
source for review, which is what makes the whole thing reversible: the live version keeps
serving until a human approves the new one, and then `publish_source` attaches the new
vendor object before withdrawing the old one, exactly as it does for edited text.

--------------------------------------------------------------------------------
RLS
--------------------------------------------------------------------------------
FORCEd `tenant_isolation` in this migration (hard rule 1), the repo-wide shape. Every
column here either is a tenant's own content or dereferences to it — `original_key` and
`document_key` are object-storage keys pointing at the client's document — so the table is
tenant data at one remove and `scripts/check_rls_coverage.py` rule 7(b) applies to it.

The downgrade drops the table. That loses the record of which object-storage keys held
which client's upload, so it is written to run only on a deployment that has not used the
feature; the objects themselves are unaffected and are reachable by tenant prefix.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3f7c21ea940"
down_revision: str | None = "a8d3f61c04e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "kb_uploads"
POLICY = "tenant_isolation"

# Spelled out rather than imported: a migration is a snapshot of the schema on the day it
# ran. NULLIF on the empty string is the repo-wide form.
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT_OR_OPS = f"(tenant_id = ({_GUC})::uuid OR {_GUC} IS NULL)"

#: THE UPLOAD LANE'S TWO NATIVE KINDS PLUS `document_ingest.CONVERTIBLE_KINDS`, which is
#: the conversion lane's own vocabulary and is spelled here rather than imported for the
#: reason every migration spells its constants: a migration is a snapshot of the schema on
#: the day it ran, and a constant that moves later must not change what this file did.
_KINDS = ("pdf", "url", "docx", "txt", "csv", "xlsx", "image")
_STATUSES = (
    "received",
    "converting",
    "conversion_unavailable",
    "conversion_failed",
    "processing",
    "processed",
    "error",
)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        # CASCADE: this row describes ONE version of one source and is meaningless without
        # it. That is the opposite of `engine_kb_routes`, which deliberately carries no FK
        # because its subject is a VENDOR object that outlives our rows — here the subject
        # is our own upload, and the vendor's copy is still addressable through the route
        # table after this row is gone.
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("original_key", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.Text(), nullable=True),
        sa.Column("original_bytes", sa.BigInteger(), nullable=True),
        sa.Column("original_sha256", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        # What the ENGINE is handed: the original when it is already a PDF, the converter's
        # output otherwise, and NULL for a link (the vendor scrapes it itself).
        sa.Column("document_key", sa.Text(), nullable=True),
        sa.Column("document_sha256", sa.Text(), nullable=True),
        # HOW the text was obtained and BY WHAT. `parsed` means a deterministic reader
        # took it out of a file format that stores text; `ocr` means a model looked at a
        # photograph and told us what it thought it said. They are different epistemic
        # states and the product treats them differently — OCR text is never auto-approved,
        # whoever uploaded it (`calevate_shared.document_ingest.TextProvenance`).
        sa.Column("text_provenance", sa.Text(), nullable=True),
        sa.Column("extractor", sa.Text(), nullable=True),
        sa.Column("ingest_status", sa.Text(), nullable=False, server_default="received"),
        # A sentence for the CLIENT, never a stack or a key (hard rule 6).
        sa.Column("ingest_detail", sa.Text(), nullable=True),
        sa.Column("content_digest", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("change_detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_uploads")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name=op.f("fk_kb_uploads_tenant"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_kb_uploads_agent"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["kb_sources.id"], name=op.f("fk_kb_uploads_source"), ondelete="CASCADE"
        ),
        # ONE upload per source version. The 1:1 this table's whole design rests on, stated
        # as a constraint rather than as a convention: two rows here would give one source
        # two documents and the publish path one question with two answers.
        sa.UniqueConstraint("source_id", name=op.f("uq_kb_uploads_source")),
        sa.CheckConstraint(f"source_kind IN {_KINDS!r}", name=op.f("ck_kb_uploads_kind")),
        sa.CheckConstraint(f"ingest_status IN {_STATUSES!r}", name=op.f("ck_kb_uploads_status")),
        sa.CheckConstraint(
            "text_provenance IS NULL OR text_provenance IN ('parsed', 'ocr')",
            name=op.f("ck_kb_uploads_provenance"),
        ),
        # A link has a URL and a file has a key. Stated in the schema because the two are
        # different products of the same table and a row that is neither is unserviceable:
        # nothing to upload and nothing to scrape.
        sa.CheckConstraint(
            "(source_kind = 'url' AND source_url IS NOT NULL AND original_key IS NULL) "
            "OR (source_kind <> 'url' AND original_key IS NOT NULL AND source_url IS NULL)",
            name=op.f("ck_kb_uploads_one_origin"),
        ),
    )
    op.create_index("ix_kb_uploads_tenant", TABLE, ["tenant_id"])
    op.create_index("ix_kb_uploads_agent", TABLE, ["agent_id"])
    # The sweep's predicate: rows still owed work, oldest first. Partial, because a
    # `processed` row is the steady state and the overwhelming majority.
    op.create_index(
        "ix_kb_uploads_unfinished",
        TABLE,
        ["updated_at"],
        postgresql_where=sa.text("ingest_status <> 'processed'"),
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    # FORCE so the guarantee holds for the table owner too — without it the owner is
    # exempt and the policy is a suggestion (hard rule 1).
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT_OR_OPS} WITH CHECK {_OWN_TENANT_OR_OPS}"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.drop_index("ix_kb_uploads_unfinished", table_name=TABLE)
    op.drop_index("ix_kb_uploads_agent", table_name=TABLE)
    op.drop_index("ix_kb_uploads_tenant", table_name=TABLE)
    op.drop_table(TABLE)
