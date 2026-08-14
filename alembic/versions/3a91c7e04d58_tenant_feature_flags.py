"""tenant_feature_flags — the per-tenant flags SURFACES §1 promises

Revision ID: 3a91c7e04d58
Revises: c8b3f14e7a29
Create Date: 2026-08-14 09:00:00.000000

SURFACES §1 lists "per-tenant feature flags (config rows, TRD conventions) — enable beta
features or debug modes per client without deploys", and CLAUDE.md fixes the mechanism:
"Feature flags via plain config rows, not a flag SaaS". This is the table.

WHAT IS AND IS NOT STORED HERE
------------------------------
One row per tenant per flag they are OFF THE DEFAULT for, and NOTHING ELSE. The platform
default lives in code (`apps/api/flags/registry.py`), which is where the argument for that
split is written out; the consequence for this table is the property that matters most
about it: **absence is the default**. No tenant needs a row for any flag, adding a flag
writes nothing, and a fresh tenant resolves every flag correctly with an empty table.

That is why there is no backfill and no seed here. A migration that wrote one row per
tenant per flag would be N x M rows encoding "no opinion", and the first flag added after
it would either need its own backfill or would quietly break the invariant.

THE CHECK IS ON THE NAME'S SHAPE, NOT ON THE SET OF NAMES
----------------------------------------------------------
`flag ~ '^[a-z][a-z0-9_]{2,63}$'` — bounded and lower-snake, because the value is
interpolated into an audit action and a URL path segment, and a query parameter is
attacker-controlled on any surface.

There is deliberately NO `flag IN (...)` CHECK enumerating the declared flags. It would be
a second definition of `flags/registry.py`, migrated in lockstep with it forever, and it
would break the retirement path: when a release stops declaring a flag, its rows must
remain STORABLE long enough for an operator to clear them (hard rule 8's two-step
deprecation, applied to rows rather than a column). The registry is enforced at the
service boundary — `PUT .../feature-flags/{flag}` refuses to SET an undeclared flag and
allows CLEARING one — which is the only place that can tell the two apart.

RLS (hard rule 1)
-----------------
New tenant table, so the full treatment in this same migration: `tenant_id`, ENABLE +
FORCE, and the standard DATA-MODEL §1 `tenant_isolation` policy created HERE beside the
table. The cross-tenant zero-rows proof is
`tests/feature_flags_test.py::test_tenant_b_sees_none_of_tenant_as_flags`, which asserts
it through the admin route AND on the raw RLS-scoped session AND through `resolve_flags`
itself — so a resolver that filtered in Python, or one that leaked a memo between
tenants, would still fail it.

LOCKING (hard rule 8)
---------------------
`CREATE TABLE` locks only itself. Both foreign keys point OUT — at `organizations` and
`admin_users` — and adding a validated FK takes SHARE ROW EXCLUSIVE on the REFERENCED
table, which blocks writes there for the length of the validation. So each is added NOT
VALID (a catalogue write) and VALIDATEd separately (SHARE UPDATE EXCLUSIVE, which does not
block inserts), with `lock_timeout` set on every statement that takes a lock outside this
table so a migration that cannot get its lock fails fast rather than queueing in front of
every writer behind it.

INDEXES
-------
`ix_tenant_feature_flags_tenant_id` is the read path: `resolve_flags` fetches ALL of one
tenant's overrides in a single statement, so the index that matters is on `tenant_id`
alone. The UNIQUE `(tenant_id, flag)` constraint's own index serves the single-flag reads
and the upsert's conflict target; a third index on `flag` would only serve a cross-tenant
"who has this flag on" query, which no code makes (`check_wiring` would call it out) and
which the admin surface answers per tenant.

DOWNGRADE
---------
Drops the policy, the index, then the table. Exercised (upgrade → downgrade → upgrade)
rather than assumed. It loses every stored override, which is unavoidable — this table is
the only place they live — and every tenant falls back to the platform defaults, which is
the SAFE direction: the defaults are what the platform does for everyone today.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3a91c7e04d58"
down_revision: str | None = "c8b3f14e7a29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns ''
# when unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON tenant_feature_flags USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)

# The same rule `flags/registry.FLAG_NAME_PATTERN` declares and the ORM mirrors. Spelled
# out here because a migration cannot import application code and must still constrain
# exactly what the service will accept.
_FLAG_NAME_PATTERN = "^[a-z][a-z0-9_]{2,63}$"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        "tenant_feature_flags",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("flag", sa.String(length=64), nullable=False),
        # NOT NULL: "no position" is the ABSENCE of the row. A nullable column would be a
        # second spelling of the same fact, and the one that silently outranks the
        # platform default in every COALESCE somebody writes later.
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        # NOT NULL: every write arrives through the admin surface, which has resolved a
        # principal before the service is called. An override that cannot name who set it
        # is not a record.
        sa.Column("set_by_admin_id", sa.UUID(), nullable=False),
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
            f"flag ~ '{_FLAG_NAME_PATTERN}'",
            name=op.f("ck_tenant_feature_flags_flag_name_shape"),
        ),
        # WHY this client is off the default. An empty string accounts for nothing.
        sa.CheckConstraint(
            "length(btrim(reason)) >= 3", name=op.f("ck_tenant_feature_flags_reason_says_why")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_feature_flags")),
        # One position per tenant per flag — a second row would be a tenant that is both
        # on and off, resolved by whichever the query happened to read first. Also the
        # conflict target the upsert in `flags/service.set_flag` names.
        sa.UniqueConstraint(
            "tenant_id", "flag", name=op.f("uq_tenant_feature_flags_tenant_id_flag")
        ),
    )
    op.create_index(
        op.f("ix_tenant_feature_flags_tenant_id"),
        "tenant_feature_flags",
        ["tenant_id"],
        unique=False,
    )

    # NOT VALID first, VALIDATE second — see the LOCKING note.
    op.execute(
        "ALTER TABLE tenant_feature_flags ADD CONSTRAINT "
        "fk_tenant_feature_flags_tenant_id_organizations FOREIGN KEY (tenant_id) "
        "REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID"
    )
    op.execute(
        "ALTER TABLE tenant_feature_flags ADD CONSTRAINT "
        "fk_tenant_feature_flags_set_by_admin_id_admin_users FOREIGN KEY (set_by_admin_id) "
        "REFERENCES admin_users (id) ON DELETE RESTRICT NOT VALID"
    )
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "ALTER TABLE tenant_feature_flags VALIDATE CONSTRAINT "
        "fk_tenant_feature_flags_tenant_id_organizations"
    )
    op.execute(
        "ALTER TABLE tenant_feature_flags VALIDATE CONSTRAINT "
        "fk_tenant_feature_flags_set_by_admin_id_admin_users"
    )

    # Hard rule 1, in the same migration as the table it protects.
    op.execute("ALTER TABLE tenant_feature_flags ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_feature_flags FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenant_feature_flags")
    op.drop_index(op.f("ix_tenant_feature_flags_tenant_id"), table_name="tenant_feature_flags")
    op.drop_table("tenant_feature_flags")
