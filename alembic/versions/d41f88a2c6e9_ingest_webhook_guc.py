"""app.ingest_webhook_id: an ingest URL can read exactly its own config row

Revision ID: d41f88a2c6e9
Revises: c93a17d0e5b4
Create Date: 2026-08-11

The sixth lookup-before-tenant case, and the pattern is now routine: an external
sender hits `/hooks/v1/ingest/{webhook_id}` carrying no tenant context, and the config
row that names the tenant lives in `inbound_webhooks` — which is FORCE-RLS'd.

Same doctrine as `app.invite_hash` (c93a17d0e5b4): the identifier in the URL is
already an unguessable UUID minted by us, so letting a session read exactly the row it
can name grants nothing a sender did not already hold — and the row's own `active`
flag plus the shared-secret check still stand between that read and any effect.

`WITH CHECK` untouched: the widened session can see one config row and change nothing.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d41f88a2c6e9"
down_revision: str | None = "c93a17d0e5b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_GUC = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
WEBHOOK_GUC = "NULLIF(current_setting('app.ingest_webhook_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON inbound_webhooks")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON inbound_webhooks
            USING (tenant_id = {TENANT_GUC} OR id = {WEBHOOK_GUC})
            WITH CHECK (tenant_id = {TENANT_GUC})
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON inbound_webhooks")
    op.execute(
        f"CREATE POLICY tenant_isolation ON inbound_webhooks USING (tenant_id = {TENANT_GUC})"
    )
