"""A tenant cannot DELETE its own organization — the tenancy anchor stops being tenant-writable

Revision ID: d1b8f30c94a7
Revises: c9e2a7b41d63
Create Date: 2026-08-18 09:40:00.000000

D-206.

THE HOLE. `organizations`' `tenant_isolation` policy is `FOR ALL` with

    USING       (id = <app.tenant_id>) OR (id IN <this user's orgs>) OR (app.admin = 'on')
    WITH CHECK  (id = <app.tenant_id>)

and `WITH CHECK` is not consulted on DELETE — the same PostgreSQL fact `e4f2a86b13d7` was
written about one table over. `USING` alone decides, and it admits the session's own
organization. Reproduced as `calevate_app` against a database at the previous revision:

    BEGIN;
    SELECT set_config('app.tenant_id', '01a0…dead', true);
    DELETE FROM organizations WHERE id = '01a0…dead';    -- DELETE 1
    ROLLBACK;

That is the tenancy anchor of the whole schema. Every one of the 43 tenant tables carries
`tenant_id REFERENCES organizations(id) ON DELETE RESTRICT`, so the row is what makes
"this data belongs to somebody" true.

WHAT IT CONTRADICTS. FLOWS §9 makes offboarding an explicit workflow; `deleted_at` is the
soft delete, guarded by `ck_organizations_deleted_implies_churned`; and `db/registry.py`
says `tenant_erasure_requests` is "the only thing in this product that writes
`organizations.deleted_at`". A hard DELETE is not a faster version of any of that — it
destroys the lifecycle record, the erasure certificate's subject, and the retention
countdown's anchor in one statement.

WHY IT IS NOT AN INCIDENT TODAY, stated so the severity is not overclaimed. No route or
worker issues the statement (the only `DELETE FROM organizations` in the tree was a test
cleanup, moved in this change), and an organization that `create_organization` made
carries children behind `ON DELETE RESTRICT`, so a real one fails on the foreign key. The
protection today is therefore the FKs, by accident, rather than the policy, by design —
and "by accident" runs out the first time a tenant's last child row is deletable through
a route, which several already are (`memberships`, `invitations`, `lead_saved_views`,
`tenant_feature_flags`, `dnc_list`).

THE PREDICATE, and why it is not simply `false`. DELETE on this table is an ADMIN-realm
operation or nothing: `admin_session()` is the one session factory that sets `app.admin`,
it is minted only after an admin-realm principal is verified (`db/session.py`), and the
existing `USING` clause already grants that session the visibility this policy now
requires it to have. Writing `USING (false)` would leave the platform with no way to
remove a mistyped prospect that never got children, which is a real operator task and the
reason `admin.delete_organization`-shaped work exists at all; it would also make every
test fixture that mints an organization unable to clean up after itself, and a suite that
cannot delete its own rows is the reason this development database carries 34,470 of
them. What must be impossible is a TENANT doing it, and that is exactly what this says.

WHY A RESTRICTIVE POLICY RATHER THAN REWRITING THE EXISTING ONE — the same argument
`e4f2a86b13d7` makes and for the same reason: the permissive `FOR ALL` policy is
load-bearing for SELECT (the client's own org header, the admin directory, the
membership-based read) and correct for INSERT/UPDATE. Restrictive policies are ANDed with
the permissive ones (PG16 §5.8), so this subtracts one verb and leaves the other three
exactly as they were.

WHY NOT AN APPLICATION GUARD. There is nothing to guard: no application code performs
this DELETE, which is precisely why an `if` cannot be the enforcement. Hard rule 1 says
RLS is.

LOCKING. `CREATE POLICY` takes `AccessExclusiveLock` on `organizations` (measured in
`e7b45c19a308`, whose first attempt queued behind two idle transactions and took the
table down). `SET LOCAL lock_timeout` bounds the wait to 5s in both directions, and
`transaction_per_migration=True` in `alembic/env.py` makes that boundary exactly this
revision: a contended database gets a migration an operator retries, not an outage.

DOWNGRADE drops the policy and restores the prior behaviour, hole included.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d1b8f30c94a7"
down_revision: str | None = "c9e2a7b41d63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "organizations_delete_admin_only"

# No WITH CHECK: for a policy that can carry both, PostgreSQL applies USING to the rows a
# statement may select and, with no WITH CHECK defined, reuses the USING expression for
# the new row. DELETE has no new row, so USING is the whole rule here.
DELETE_USING = "current_setting('app.admin', true) = 'on'"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        f"CREATE POLICY {POLICY} ON organizations AS RESTRICTIVE FOR DELETE "
        f"USING ({DELETE_USING})"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(f"DROP POLICY {POLICY} ON organizations")
