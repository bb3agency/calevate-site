"""app.user_id GUC: let a session resolve WHICH tenants it may enter

Revision ID: 8c31d0f4ab27
Revises: 17a91a69dee9
Create Date: 2026-08-10

The gap this closes, found by writing the API auth tests:

Authentication has a chicken-and-egg problem under RLS. To scope a session to a tenant
we must first ask "which tenants is this user a member of?" — and that question is
answered by `memberships` and `organizations`, both of which are FORCE-RLS'd on the
very tenant id we do not have yet. With only `app.tenant_id`, the login query returns
zero rows and every legitimate member gets a 403.

The wrong fixes, and why:
- **Drop RLS on memberships** — memberships carry the role that decides what a user may
  do; making them world-readable to the app role is the opposite of hard rule 1.
- **Run the lookup as the owner role** — app code must never use the admin DB role.
- **Duplicate memberships into a global index** — two sources of truth for authorization
  data, which drift silently and fail open.

The fix instead ADDS a second, narrower GUC. `app.user_id` is set from an already-
verified session and widens `USING` by exactly one clause: a user may read THEIR OWN
membership rows, and the organizations they are a member of. It widens `WITH CHECK` by
nothing at all — writes still require `app.tenant_id`, so this cannot become a path to
creating or editing rows in a tenant you merely belong to.

Both GUCs are transaction-local (`set_config(..., true)`), so a pooled connection can
never carry one request's identity into the next.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "8c31d0f4ab27"
down_revision: str | None = "17a91a69dee9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_GUC = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
USER_GUC = "NULLIF(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    # memberships: read your own rows, or all rows of the tenant you are scoped to.
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON memberships")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON memberships
            USING (tenant_id = {TENANT_GUC} OR user_id = {USER_GUC})
            WITH CHECK (tenant_id = {TENANT_GUC})
        """
    )

    # organizations: the tenant you are scoped to, or any tenant you are a member of.
    # The subquery runs under memberships' own policy, which is why the clause above
    # has to exist first — it is not a second, looser path to the same data.
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


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON memberships")
    op.execute(f"CREATE POLICY tenant_isolation ON memberships USING (tenant_id = {TENANT_GUC})")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON organizations")
    op.execute(f"CREATE POLICY tenant_isolation ON organizations USING (id = {TENANT_GUC})")
