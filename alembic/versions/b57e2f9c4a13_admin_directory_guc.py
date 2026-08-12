"""app.admin GUC — the admin realm can enumerate tenants, and NOTHING else

Revision ID: b57e2f9c4a13
Revises: 8c31d0f4ab27
Create Date: 2026-08-10

The admin console has to answer "which clients exist and how are they doing?", which
is a cross-tenant read of `organizations` — and `organizations` is FORCE-RLS'd. This is
the third variant of the same problem (after `engine_agent_routes` for webhook routing
and `app.user_id` for membership lookup), and it gets the narrowest fix that works.

**Scope, deliberately minimal.** This GUC widens `USING` on `organizations` ONLY. It
does not touch `calls`, `leads`, `transcript_turns` or anything else, and it widens no
`WITH CHECK` anywhere. An admin listing clients is not an admin reading a client's
transcripts: to see tenant data they enter that tenant through impersonation (D-22),
which sets `app.tenant_id` normally, is READ-ONLY, and is audited per page view.

**Why a GUC rather than a role.** Hard rule 1 forbids the admin DB role in app code
paths, and for good reason: a bypass role turns every future bug into a total breach.
A transaction-local GUC set only by `admin_session()` — which requires an already
verified admin principal — keeps the blast radius to one table and one code path.

The directory is not secret (names and slugs of our own clients); the call content is,
and that stays behind the tenant GUC exactly as before.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b57e2f9c4a13"
down_revision: str | None = "8c31d0f4ab27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_GUC = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
USER_GUC = "NULLIF(current_setting('app.user_id', true), '')::uuid"
ADMIN_GUC = "current_setting('app.admin', true) = 'on'"


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON organizations")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON organizations
            USING (
                id = {TENANT_GUC}
                OR id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = {USER_GUC})
                OR {ADMIN_GUC}
            )
            WITH CHECK (id = {TENANT_GUC})
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON organizations")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON organizations
            USING (
                id = {TENANT_GUC}
                OR id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = {USER_GUC})
            )
            WITH CHECK (id = {TENANT_GUC})
        """
    )
