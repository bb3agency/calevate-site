"""kb_uploads: the ops escape stops at reading

Revision ID: f2b91c47e0a3
Revises: e5c81d09b74a
Create Date: 2026-09-07

`b3f7c21ea940` created `kb_uploads` with one `FOR ALL` policy whose USING **and WITH
CHECK** were `(tenant_id = <guc> OR <guc> IS NULL)`. Its own RLS section calls that "the
repo-wide shape"; it is not. The repo-wide shape is `tenant_id = <guc>` for every verb,
and the one table that legitimately needs an untenanted reader — `retention_worklist`,
`b2e6f10c94d7` — buys it with a SECOND, `FOR SELECT`-only policy while `tenant_isolation`
stays strict. `kb_uploads` bought a cross-tenant READ and paid for a cross-tenant WRITE.

WHAT THAT ACTUALLY GRANTED, measured rather than reasoned (7 Sep 2026, on a database
migrated base->head): from `db/session.untenanted_session()` — the session whose docstring
promises "tenant tables yield ZERO rows" — `UPDATE kb_uploads ... WHERE id = :u` returned
rowcount 1 against another tenant's row, `DELETE` returned 1, and an `INSERT` naming a
THIRD tenant's `tenant_id` was accepted. `original_key` and `document_key` are
object-storage keys that dereference to a client's own PDF, and one route turns
`original_key` into a presigned URL; a repointed key is a neighbour's price list handed
out under this tenant's name. Nothing in the tree exploits it today — every writer
(`kb/uploads.py`, `workers/kb_ingest.py::_mark`/`_recheck_link`) runs inside
`tenant_session` — which is exactly why it is worth closing while that is still true.

WHY THE READ HALF STAYS. `workers/kb_ingest.sweep_kb_uploads` opens an untenanted session
to find rows stalled mid-ingest across every tenant (`_STALLED_SQL`), the same global
work-queue shape `retention_worklist` has. That query reads `kb_uploads` alone, so a
`FOR SELECT` policy is the whole of what it needs.

WHAT `check_rls_coverage` COULD AND COULD NOT SEE. It requires every permissive policy's
USING and WITH CHECK to MENTION `app.tenant_id`; `(tenant_id = <guc> OR <guc> IS NULL)`
mentions it twice and passed. The new `FOR SELECT` policy is written in the same
GUC-reading form for that reason, so the gate keeps its grip on both policies.

REVERSIBLE, and the downgrade is a real restore: it drops the two policies and recreates
`b3f7c21ea940`'s single combined one, so a database moved back holds exactly the schema
that revision left.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f2b91c47e0a3"
down_revision: str | None = "e5c81d09b74a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "kb_uploads"
POLICY = "tenant_isolation"
OPS_READ_POLICY = "kb_uploads_ops_read"

# Spelled out rather than imported, as every migration here spells its constants: a
# migration is a snapshot of the schema on the day it ran.
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
#: The repo-wide form. Fail-closed on an unset GUC, in both directions.
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"
#: `retention_worklist_ops_read`'s form, verbatim: the untenanted worker, and only it.
_UNTENANTED = f"({_GUC} IS NULL)"
#: What `b3f7c21ea940` created, kept here so the downgrade restores it exactly.
_OWN_TENANT_OR_OPS = f"(tenant_id = ({_GUC})::uuid OR {_GUC} IS NULL)"


def upgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.execute(
        f"CREATE POLICY {POLICY} ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )
    # SELECT only. A permissive policy is OR'd with the one above, so this widens reading
    # and cannot widen any verb it does not name.
    op.execute(f"CREATE POLICY {OPS_READ_POLICY} ON {TABLE} FOR SELECT USING {_UNTENANTED}")


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {OPS_READ_POLICY} ON {TABLE}")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.execute(
        f"CREATE POLICY {POLICY} ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT_OR_OPS} WITH CHECK {_OWN_TENANT_OR_OPS}"
    )
