"""an owner may let their staff curate knowledge — one capability, off until they say so

Revision ID: 67c2ef8479f7
Revises: d4a9c17e6b02
Create Date: 2026-09-01 00:00:00.000000

THE DECISION THIS COLUMN STORES. The founder: "give the staff perms allowing option to
owner and every admin should have that permission." The second half needed no schema —
every admin already approves knowledge as themselves through
`POST /v1/admin/tenants/{tenant_id}/kb/{source_id}/approve` (`agents:write`,
`realm="admin"`, audited `kb.approved`), which is a surface D-22 never blocked because
the admin reaches it WITHOUT impersonating. The first half is this column: staff MAY hold
the knowledge-curation capability, but only because THIS account's owner switched it on.

`NOT NULL DEFAULT false`, AND THE DEFAULT IS THE WHOLE SAFETY ARGUMENT. Every existing
row and every future row starts OFF, so this revision widens nothing in any live account:
a staff member in an untouched tenant is refused by `kb/curation.py` exactly as they were
refused by `requires("kb:write")` yesterday. A migration that silently changed what staff
could do in accounts nobody had looked at would be the opposite of a permission decision —
it would be a permission accident. `server_default` rather than a backfill for the same
reason `plan_tier` uses one: there is no moment where a row exists without an answer.

WHY A COLUMN ON `organizations` AND NOT A FEATURE FLAG. `apps/api/flags/` exists and was
the first candidate, and its own registry docstring is what rules it out. A flag there is
defined as "a per-tenant, reversible, OPERATOR-owned switch on OUR OWN product behaviour"
— set from the admin console at `PUT /v1/admin/tenants/{id}/feature-flags`. Both halves
are wrong here. The ACTOR is wrong: the founder gave this switch to the owner, and a
mechanism whose only writer is a Calevate operator cannot express "the owner turns it on".
And the SUBJECT is wrong: a flag gates product behaviour, whereas this decides who may
act — authorization, which the same docstring keeps at arm's length when it forbids a flag
from gating a compliance control. Building an owner-writable path into the flags table
would have given that table two writers with two audiences and two audit stories, which is
the accumulation CLAUDE.md counts as a defect even when both halves work.

The precedent followed instead is `organizations.default_llm_model` (migration
b7d2f10c93ae): an account-level setting, owner-written through a client-realm
`org:manage` route, audited, read back through RLS. One way per problem.

NO RLS CHANGE, VERIFIED RATHER THAN ASSUMED. `organizations` carries its FORCEd policy
(matching on `id` — it is the tenant root), and Postgres has no per-column RLS, so a new
column inherits it. "Inherits" stays true only until a neighbouring `ALTER TABLE` turns
FORCE off, so `_assert_rls_still_forced` re-reads `pg_class` after the DDL rather than
trusting the sentence, exactly as b7d2f10c93ae does. That is what makes "one tenant's
switch cannot be read or written by another" a property of the database rather than of
every reader remembering a WHERE clause (hard rule 1); `tests/kb_staff_curation_test.py`
drives the cross-tenant case through this column specifically.

NO CHECK CONSTRAINT: the column is `boolean NOT NULL`, so the type IS the constraint and
there is no third value for a CHECK to exclude.

REVERSIBLE. The downgrade drops the column. Nothing else depends on it — with the column
gone the reader is gone too, and `requires("kb:write")` alone is the state this revision
started from, which is a working account rather than a broken one.
"""

import sqlalchemy as sa
from alembic import op

revision = "67c2ef8479f7"
down_revision = "d4a9c17e6b02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "staff_may_curate_knowledge",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    _assert_rls_still_forced()


def _assert_rls_still_forced() -> None:
    """Hard rule 1, re-read from the catalog instead of asserted in the docstring."""
    row = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = CAST('public.organizations' AS regclass)"
            )
        )
        .first()
    )
    if row is None or not (row[0] and row[1]):
        raise RuntimeError(
            "organizations is not FORCE ROW LEVEL SECURITY after this migration; one "
            "account's staff-curation switch would be readable across tenants "
            "(hard rule 1)"
        )


def downgrade() -> None:
    op.drop_column("organizations", "staff_may_curate_knowledge")
