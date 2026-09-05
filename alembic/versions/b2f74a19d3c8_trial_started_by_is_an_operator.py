"""tenant_trials.started_by points at an OPERATOR, not at a client user

Revision ID: b2f74a19d3c8
Revises: c7e0b2a94f13
Create Date: 2026-09-05

`tenant_trials.started_by` shipped in a71f3c9e5d84 with a foreign key to `users.id`, and
the column can never hold a value that satisfies it. The only route that writes it —
`billing/trial_routes.py::open_trial` — is `admin:tenants` in the ADMIN realm, so the
`principal.user_id` it stores is an `admin_users.id`; `authn/operators.py` and
`authn/bootstrap.py` are the only two writers of that table and neither creates a matching
`users` row. Every attempt to put a client on a trial therefore raised
`ForeignKeyViolation` and surfaced as a 500: the feature was unreachable in full, not
merely on an edge, and the mismatch was invisible from a diff because both columns are
`UUID` and both FKs are `SET NULL`.

The repointing is what every other admin-actor column in this schema already does —
`organizations.closed_by` (e6c1a49d2f70), `platform_settings.updated_by` (a4d17c02fb98),
`platform_list_rates.set_by` (d3b81f5c02ae), the attested model prices (c7f1a9e34b62) —
so this is a correction back onto the existing pattern rather than a new one.
`ondelete="SET NULL"` is kept for the reason the column's own comment gives: a leaver must
not pin a client's trial history, and the durable record of who agreed to carry the
account is the `audit_log` row written in the same transaction.

NO DATA MIGRATION IS NEEDED AND NONE IS SAFE TO ASSUME. A non-NULL `started_by` under the
old constraint would have had to be a `users.id`, which no writer could produce; the
column is NULL wherever a row exists at all (the service path used by tests passes
`actor_user_id=None`). The new constraint is therefore validated against rows that are all
NULL. It is an ordinary ADD CONSTRAINT rather than a NOT VALID two-step because this is a
low-volume state table — one row per trial per client — with no hot write path a brief
lock hurts, unlike `credit_ledger`; `lock_timeout` bounds it either way (hard rule 8).

REVERSIBLE, AND IT REFUSES RATHER THAN CORRUPTING WHEN IT IS NOT. The downgrade restores
the original constraint verbatim, and against the state hard rule 8 asks about — a
database walked base→head→base, where `tenant_trials` is empty — it completes. Once the
fixed route has actually been used, `started_by` holds `admin_users.id` values that the
old FK cannot validate, and a bare `create_foreign_key` would fail deep inside the DDL.
So the row count is taken FIRST and the downgrade raises before touching anything, the
shape `d7b1c48a2e93` established: a refused downgrade leaves the table with exactly one
constraint rather than none, which is the one outcome worse than either direction.
Clearing those ids is the operator's decision and not this file's — they are the record of
who agreed to carry an account, and the message says so.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2f74a19d3c8"
down_revision: str | None = "c7e0b2a94f13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "fk_tenant_trials_started_by_users"
NEW = "fk_tenant_trials_started_by_admin_users"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(OLD, "tenant_trials", type_="foreignkey")
    op.create_foreign_key(
        NEW,
        "tenant_trials",
        "admin_users",
        ["started_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    stranded = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM tenant_trials t WHERE t.started_by IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id = t.started_by)"
            )
        )
        .scalar_one()
    )
    if stranded:
        # Counted BEFORE the drop, so a refused downgrade leaves the column with exactly
        # one constraint rather than none.
        raise RuntimeError(
            f"{stranded} trial row(s) name an operator in `started_by`, which the "
            "pre-b2f74a19d3c8 foreign key to `users` cannot validate. Downgrading would "
            "require discarding the record of who agreed to carry those accounts. Null "
            "those columns deliberately first — the `audit_log` rows survive — then "
            "re-run this downgrade."
        )
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(NEW, "tenant_trials", type_="foreignkey")
    op.create_foreign_key(
        OLD,
        "tenant_trials",
        "users",
        ["started_by"],
        ["id"],
        ondelete="SET NULL",
    )
