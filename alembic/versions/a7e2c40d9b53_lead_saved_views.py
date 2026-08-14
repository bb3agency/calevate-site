"""lead_saved_views — a named filter+column combination, private to one person

Revision ID: a7e2c40d9b53
Revises: a1c4f70b9e28
Create Date: 2026-08-14 09:10:00.000000

SURFACES §2 asks for "saved views: named filter+column combinations per user (e.g. 'Hot
this week')". This is the table for them, and the shape is decided by three questions.

**1. Where does per-user-per-tenant UI state live?** Not on `memberships` as a JSONB
blob: a person keeps SEVERAL views, each with its own name, its own lifetime and its own
delete, so the cardinality is per view. A blob would be an unbounded list with no unique
name, no per-row delete and no way to count what a client is keeping. A table gives all
three for the price of one migration.

**2. Private or shared?** Private, and this table has no `visibility` column to argue
about. Shared views are a genuinely separate feature — the interesting part is not
storing a flag, it is deciding who may EDIT a view three colleagues have on screen, and
what their screens do the moment somebody does. The industry default is
private-unless-explicitly-published (Tableau's custom views, SeaTable's private views),
and private-first is the only version with no leak surface at all: there is no shared row
here for a permission check to get wrong. Adding `visibility` later is one additive
column and one policy predicate, so nothing is foreclosed.

**3. Isolation.** Hard rule 1, in this migration and not the next one: `tenant_id`, the
DATA-MODEL §1 `tenant_isolation` policy, ENABLE plus FORCE. The cross-tenant zero-rows
proof is `tests/lead_saved_views_test.py::test_tenant_b_cannot_see_tenant_as_saved_view`,
which asserts through the client route AND on the raw RLS-scoped session, so a handler
that filtered in Python would still fail.

`user_id` references `users`, which is GLOBAL and carries no RLS (DATA-MODEL §2 —
identity crosses tenants). The isolation is therefore entirely `tenant_id`'s job, and
the PER-USER half is an explicit `user_id` predicate in every query
(`apps/api/crm/saved_views.py`). That split is stated here because the tempting mistake
is to read the policy as if it scoped the person too.

**ON DELETE CASCADE on `user_id`**, against this repo's RESTRICT habit and deliberately.
Everywhere else RESTRICT protects a record somebody may need to account for later; a
saved view is one person's private lens on a table, it is evidence of nothing, and a
RESTRICT here would make "remove this user" fail on a row nobody would think to look for.
`tenant_id` keeps RESTRICT, because an organization with rows is not deletable and this
row does not change that.

**UNIQUE(tenant_id, user_id, name)** — a name identifies a view to the person who made
it, so two "Hot this week"s under one person would be a picker nobody can use. Leading
with `tenant_id` also keeps a unique violation reachable only against a row of your own:
under FORCEd RLS a conflict is one of the few channels through which a hidden row can
announce that it exists.

**The CHECKs pin the ENVELOPE, not the content.** `filters` is an object and `columns`
is either absent or a NON-EMPTY array; what is inside them is the current extraction
schema's business and is validated by Pydantic at the API boundary (DATA-MODEL §10's
stated arrangement, the same one `organizations.intake` and `extraction_schemas.fields`
use). The non-empty rule matters: NULL and `[]` would both mean "no column choice", and
one meaning with two spellings is how a reader ends up writing the wrong branch. A name
of pure whitespace is refused for the same reason `first_campaign_reviews` refuses an
empty decision note — an unnameable view is not a view.

**Locking.** A new table: nothing to lock out, no scan, no rewrite. `lock_timeout` is set
anyway so that queueing behind another session's long transaction fails fast instead of
parking an ACCESS EXCLUSIVE request in the queue. The FKs are added NOT VALID and
validated in a second statement (SHARE UPDATE EXCLUSIVE, blocks neither readers nor
writers on `organizations`/`users`), which is this repo's pattern for the same reason.

**Downgrade** drops the policy, the indexes and the table. It loses saved views, which no
downgrade can avoid since the table is the only place they live — and it loses nothing
else: a view is a lens over `leads`, never a copy of one, so the rows a view selected are
untouched and the pre-migration screen renders the whole table exactly as it did before.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7e2c40d9b53"
down_revision: str | None = "a1c4f70b9e28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once carried the GUC returns
# '' when it is unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON lead_saved_views USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        "lead_saved_views",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "filters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("columns", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.CheckConstraint(
            "jsonb_typeof(filters) = 'object'",
            name=op.f("ck_lead_saved_views_filters_is_an_object"),
        ),
        # NULL or a non-empty array — never `[]`, so "no column choice" has exactly one
        # spelling. See the module docstring.
        sa.CheckConstraint(
            "columns IS NULL OR (jsonb_typeof(columns) = 'array' AND "
            "jsonb_array_length(columns) > 0)",
            name=op.f("ck_lead_saved_views_columns_is_a_non_empty_array"),
        ),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 60",
            name=op.f("ck_lead_saved_views_name_is_nameable"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_saved_views")),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "name", name=op.f("uq_lead_saved_views_tenant_user_name")
        ),
    )
    op.create_index(
        op.f("ix_lead_saved_views_tenant_id"), "lead_saved_views", ["tenant_id"], unique=False
    )
    # The read this table exists to serve is "my views on this account", every time the
    # Leads screen opens. The UNIQUE above leads with the same two columns and would
    # answer it, but it also carries `name` — this narrower index is what the planner
    # picks for the ordered list, and it is three columns cheaper per insert.
    op.create_index(
        op.f("ix_lead_saved_views_tenant_user"),
        "lead_saved_views",
        ["tenant_id", "user_id"],
        unique=False,
    )

    op.execute(
        "ALTER TABLE lead_saved_views ADD CONSTRAINT "
        "fk_lead_saved_views_tenant_id_organizations FOREIGN KEY (tenant_id) "
        "REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID"
    )
    # CASCADE, unlike the RESTRICT beside it — the docstring argues why a private lens is
    # not a record anyone must account for after its owner is gone.
    op.execute(
        "ALTER TABLE lead_saved_views ADD CONSTRAINT "
        "fk_lead_saved_views_user_id_users FOREIGN KEY (user_id) "
        "REFERENCES users (id) ON DELETE CASCADE NOT VALID"
    )
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "ALTER TABLE lead_saved_views VALIDATE CONSTRAINT "
        "fk_lead_saved_views_tenant_id_organizations"
    )
    op.execute("ALTER TABLE lead_saved_views VALIDATE CONSTRAINT fk_lead_saved_views_user_id_users")

    # Hard rule 1, in the same migration as the table it protects.
    op.execute("ALTER TABLE lead_saved_views ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE lead_saved_views FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON lead_saved_views")
    op.drop_index(op.f("ix_lead_saved_views_tenant_user"), table_name="lead_saved_views")
    op.drop_index(op.f("ix_lead_saved_views_tenant_id"), table_name="lead_saved_views")
    op.drop_table("lead_saved_views")
