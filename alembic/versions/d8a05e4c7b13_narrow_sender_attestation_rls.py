"""The sender-attestation ledger's policy stops accepting an untenanted write.

Revision ID: d8a05e4c7b13
Revises: c9d41f7b2e08
"""

from __future__ import annotations

from alembic import op

revision = "d8a05e4c7b13"
down_revision = "c9d41f7b2e08"
branch_labels = None
depends_on = None

TABLE = "outbound_sender_attestations"
POLICY = "tenant_isolation"
MUTATION_TRIGGER = f"{TABLE}_append_only"
TRUNCATE_TRIGGER = f"{TABLE}_forbid_truncate"

_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
#: The canonical predicate (`05bba2f3c19c`), with NO `OR <guc> IS NULL` arm.
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"


def upgrade() -> None:
    # `b7e4c02fa519` built this policy as `FOR ALL` with `(tenant_id = ... OR <guc> IS
    # NULL)` in BOTH `USING` and `WITH CHECK`, copied from `b3f7c21ea940`. On a read that
    # arm lets an untenanted operator session see every row; on a WRITE it accepts an
    # INSERT naming ANY tenant, which is the cross-tenant hole hard rule 1 exists to
    # close. Both readers of this table are tenant-scoped (`campaigns/
    # sender_attestation.latest_attestation` and the client routes), so narrowing changes
    # no behaviour and closes the write.
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.execute(
        f"CREATE POLICY {POLICY} ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )

    # `a2e9f31c605d`'s pair, which this table shipped without. TRUNCATE is not an UPDATE
    # or a DELETE, so the append-only trigger never sees it and one statement empties the
    # evidence; ENABLE ALWAYS so neither survives a session in replica mode.
    op.execute(
        f"CREATE TRIGGER {TRUNCATE_TRIGGER} "
        f"BEFORE TRUNCATE ON {TABLE} "
        f"FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ALWAYS TRIGGER {TRUNCATE_TRIGGER}")
    op.execute(f"ALTER TABLE {TABLE} ENABLE ALWAYS TRIGGER {MUTATION_TRIGGER}")


def downgrade() -> None:
    op.execute(f"ALTER TABLE {TABLE} ENABLE REPLICA TRIGGER {MUTATION_TRIGGER}")
    op.execute(f"DROP TRIGGER IF EXISTS {TRUNCATE_TRIGGER} ON {TABLE}")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.execute(
        f"CREATE POLICY {POLICY} ON {TABLE} FOR ALL "
        f"USING (tenant_id = ({_GUC})::uuid OR {_GUC} IS NULL) "
        f"WITH CHECK (tenant_id = ({_GUC})::uuid OR {_GUC} IS NULL)"
    )
