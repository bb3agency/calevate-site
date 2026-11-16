"""Campaigns pick their sources from What your agents know (founder, 16 Nov 2026).

Revision ID: e3c7a1d9b4f2
Revises: d8b2f5a7c3e1

* `campaign_sources`: the `kb_sources` a campaign is written from, as `inbound_line_sources`
  is for a line. Tenant data, FORCEd RLS in this migration (hard rule 1).

ONE PLACE HOLDS WHAT THE AGENTS KNOW, so every live campaign material becomes a pick:

* a file or link material already points at the client's knowledge (`kb_upload_id`), so it
  becomes a pick of that upload's source;
* a note (the owner's, or an answer to a question its calls raised) becomes a typed note in
  What your agents know, approved in the name of whoever wrote it, and a pick of it. A link
  material with no upload behind it is kept the same way, its address as the note's words.
  A note whose name is already taken is "Name (2)", "Name (3)", as a new item named after
  its file is (`kb/uploads.name_for_new_item`): sharing a name would make it that item's
  next version and replace it. The new notes are approved and not yet live; the ingest
  sweep publishes them (`kb_ingest._UNPUBLISHED_TYPED_SQL`), the same path as a note whose
  publish job was lost.

Rejected: keeping the materials readable beside the picks. Two lists of what a campaign
works from, two writers to keep in step and two things for Pip to read is the drift this
change removes. `campaign_materials` keeps every row (hard rule 8: a later release drops
it); nothing reads or writes it after this.

Walked one tenant at a time under that tenant's `app.tenant_id`, because every table it
touches is FORCE-RLS'd. `downgrade()` drops the picks; the notes it made stay in What your
agents know, where the owner may already have edited or published them, so an upgrade after
a downgrade makes each note again under the next free name.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3c7a1d9b4f2"
down_revision: str | None = "d8b2f5a7c3e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "campaign_sources"
POLICY = "tenant_isolation"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"
_FALLBACK_NAME = "Campaign note"

_POINTERS = sa.text(
    "SELECT m.campaign_id, u.source_id, m.created_by FROM campaign_materials m "
    "JOIN kb_uploads u ON u.id = m.kb_upload_id "
    "WHERE m.archived_at IS NULL AND m.kind IN ('file', 'link') ORDER BY m.created_at, m.id"
)
_PICK = sa.text(
    "INSERT INTO campaign_sources (id, tenant_id, campaign_id, kb_source_id, created_by) "
    "VALUES (:id, :t, :c, :s, :by) ON CONFLICT DO NOTHING"
)
_WORDS = sa.text(
    "SELECT tenant_id, campaign_id, kind, title, url, note, created_by FROM campaign_materials "
    "WHERE archived_at IS NULL AND (kind = 'note' OR (kind = 'link' AND kb_upload_id IS NULL)) "
    "ORDER BY created_at, id"
)


def _free_name(title: str, taken: set[str]) -> str:
    from apps.api.core.errors import ProblemError
    from apps.api.kb.uploads import _MAX_NAME, safe_name

    try:
        base = safe_name(given=None, fallback=title)
    except ProblemError:
        base = _FALLBACK_NAME
    candidate, n = base, 2
    while candidate in taken:
        suffix = f" ({n})"
        candidate = base[: _MAX_NAME - len(suffix)].rstrip() + suffix
        n += 1
    return candidate


def _words_of(kind: str, url: str | None, note: str | None) -> str:
    if kind == "link":
        return "\n\n".join(part for part in (url, note) if part)
    return note or ""


def _carry_over(bind: sa.Connection, tenant_id: object) -> None:
    from apps.api.db.base import uuid7
    from apps.api.kb.service import chunk_text
    from apps.api.teach.facts import FACTS_SOURCE_NAME

    for campaign_id, source_id, created_by in bind.execute(_POINTERS).all():
        bind.execute(
            _PICK,
            {"id": uuid7(), "t": tenant_id, "c": campaign_id, "s": source_id, "by": created_by},
        )
    rows = bind.execute(_WORDS).all()
    if not rows:
        return
    # Named by tenant: inside the bracket the owner reads every tenant's rows.
    taken = set(
        bind.execute(
            sa.text("SELECT DISTINCT name FROM kb_sources WHERE tenant_id = :t"), {"t": tenant_id}
        ).scalars()
    )
    taken.add(FACTS_SOURCE_NAME)
    for row in rows:
        chunks = chunk_text(_words_of(row.kind, row.url, row.note))
        if not chunks:
            continue
        name = _free_name(row.title, taken)
        taken.add(name)
        source_id = uuid7()
        bind.execute(
            sa.text(
                "INSERT INTO kb_sources (id, tenant_id, kind, name, uri, status, version, "
                "submitted_by, approved_by, approved_at, is_active, created_at, updated_at) "
                "VALUES (:id, :t, 'text', :name, NULL, 'approved', 1, :by, :by, now(), false, "
                "now(), now())"
            ),
            {"id": source_id, "t": tenant_id, "name": name, "by": row.created_by},
        )
        for idx, chunk in enumerate(chunks):
            bind.execute(
                sa.text(
                    "INSERT INTO kb_documents (id, tenant_id, source_id, idx, title, content, "
                    "created_at, updated_at) VALUES (:id, :t, :s, :idx, :title, :content, "
                    "now(), now())"
                ),
                {
                    "id": uuid7(),
                    "t": tenant_id,
                    "s": source_id,
                    "idx": idx,
                    "title": name,
                    "content": chunk,
                },
            )
        bind.execute(
            _PICK,
            {
                "id": uuid7(),
                "t": tenant_id,
                "c": row.campaign_id,
                "s": source_id,
                "by": row.created_by,
            },
        )


def _backfill() -> None:
    bind = op.get_bind()
    # Each write already runs under its own tenant's `app.tenant_id`; the bracket is the
    # repo's form for a migration writing to a live FORCE-RLS table (`d3b71c9a5e08`), and
    # lifts RLS for the owner only, inside this transaction.
    op.execute("ALTER TABLE kb_sources NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kb_documents NO FORCE ROW LEVEL SECURITY")
    entry = bind.execute(sa.text("SELECT current_setting('app.tenant_id', true)")).scalar()
    for tenant_id in bind.execute(sa.text("SELECT id FROM organizations ORDER BY id")).scalars():
        bind.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
        )
        _carry_over(bind, tenant_id)
    bind.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": entry or ""})
    op.execute("ALTER TABLE kb_documents FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kb_sources FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kb_source_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("kb_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint(
            "campaign_id", "kb_source_id", name=op.f(f"uq_{TABLE}_campaign_source")
        ),
    )
    op.create_index(f"ix_{TABLE}_tenant_id", TABLE, ["tenant_id"])
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {TABLE} FOR ALL USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )
    _backfill()


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.drop_index(f"ix_{TABLE}_tenant_id", table_name=TABLE)
    op.drop_table(TABLE)
