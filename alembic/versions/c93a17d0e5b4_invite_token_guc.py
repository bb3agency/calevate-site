"""app.invite_hash: possession of the token authorizes exactly the row it names

Revision ID: c93a17d0e5b4
Revises: f170dbce6f47
Create Date: 2026-08-11

Accepting an invitation has the same shape as the three lookup problems before it: the
emailed token names its own tenant, so we must read `invitations` BEFORE we know which
tenant to scope to — and `invitations` is FORCE-RLS'd.

The fix is the narrowest one yet, and it is narrow because the token itself is the
capability. `app.invite_hash` widens `USING` by one clause: a session may see the
invitation whose `token_hash` it can already name. Guessing that value is guessing a
32-byte secret, so the clause grants nothing an attacker did not already hold.

`WITH CHECK` is untouched, which forces the two-step the accept flow already does:
1. read under `app.invite_hash` to learn the tenant (read-only),
2. burn the invitation and create the membership under `app.tenant_id` (writes).

That split is a feature — the widened session can never write.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c93a17d0e5b4"
down_revision: str | None = "f170dbce6f47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_GUC = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
INVITE_GUC = "NULLIF(current_setting('app.invite_hash', true), '')"


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON invitations")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON invitations
            USING (tenant_id = {TENANT_GUC} OR token_hash = {INVITE_GUC})
            WITH CHECK (tenant_id = {TENANT_GUC})
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON invitations")
    op.execute(f"CREATE POLICY tenant_isolation ON invitations USING (tenant_id = {TENANT_GUC})")
