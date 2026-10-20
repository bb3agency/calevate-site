"""the owner turning Pip off, and the in-call data-use attestation

Revision ID: a3d8f1c6e092
Revises: d8a4c2e7f150
Create Date: 2026-10-20 23:00:00.000000

D-839 (founder, 20 Oct 2026), two additive changes:

* `copilot_consents.kind` — `accepted` (every existing row, by the default) or `withdrawn`:
  the account owner turning Pip off is a later row, never an edit of the append-only record,
  and `copilot/consent.read_consent` judges the latest row. Adding a column with a constant
  default is a catalogue change in PostgreSQL 11+, so no row is rewritten and the append-only
  trigger never fires.
* `platform_in_call_data_use` — the operator's attestation about a provider's data-use terms
  for RAW CALLER SPEECH on our own model, the shape of `platform_dashboard_data_use`
  (migration `d4a83f06c1e7` argues each column) with its own rows, statement and step-up.
  Platform-scoped (no tenant, `db/registry.RLS_EXEMPT_TENANT_COLUMNS`) and append-only with
  both shared triggers, `ENABLE ALWAYS`.

No row is copied from the dashboard table into the new one: an attestation is a person's
name on one statement, and the in-call statement is a different one. Own-model readiness
reads the new table, so a deployment whose readiness rested on the dashboard row shows the
in-call step as not done until an operator attests it (D-839 names the step).

**Downgrade** drops the new table (its history is re-made only by re-attesting) and drops
`kind`, refusing while any `withdrawn` row exists: without the column that row would read as
an acceptance and turn Pip back on for an account whose owner turned it off.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3d8f1c6e092"
down_revision: str | None = "d8a4c2e7f150"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSENTS = "copilot_consents"
IN_CALL = "platform_in_call_data_use"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.add_column(
        CONSENTS,
        sa.Column("kind", sa.Text(), server_default=sa.text("'accepted'"), nullable=False),
    )
    op.create_check_constraint(
        op.f(f"ck_{CONSENTS}_kind_enum"), CONSENTS, "kind IN ('accepted', 'withdrawn')"
    )

    op.create_table(
        IN_CALL,
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vendor_account_ref", sa.Text(), nullable=False),
        sa.Column("paid_tier_confirmed", sa.Boolean(), nullable=False),
        sa.Column("no_training_opt_in_confirmed", sa.Boolean(), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["attested_by"],
            ["admin_users.id"],
            name=op.f(f"fk_{IN_CALL}_attested_by_admin_users"),
        ),
        sa.PrimaryKeyConstraint("provider", "attested_at", name=op.f(f"pk_{IN_CALL}")),
        sa.CheckConstraint(
            "btrim(vendor_account_ref) <> '' AND btrim(source_note) <> ''",
            name=op.f(f"ck_{IN_CALL}_evidence_present"),
        ),
    )
    op.create_index(f"ix_{IN_CALL}_provider", IN_CALL, ["provider", sa.text("attested_at DESC")])
    op.execute(
        f"CREATE TRIGGER {IN_CALL}_append_only BEFORE UPDATE OR DELETE ON {IN_CALL} "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {IN_CALL}_forbid_truncate BEFORE TRUNCATE ON {IN_CALL} "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(f"ALTER TABLE {IN_CALL} ENABLE ALWAYS TRIGGER {IN_CALL}_append_only")
    op.execute(f"ALTER TABLE {IN_CALL} ENABLE ALWAYS TRIGGER {IN_CALL}_forbid_truncate")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP TRIGGER IF EXISTS {IN_CALL}_forbid_truncate ON {IN_CALL}")
    op.execute(f"DROP TRIGGER IF EXISTS {IN_CALL}_append_only ON {IN_CALL}")
    op.drop_index(f"ix_{IN_CALL}_provider", table_name=IN_CALL)
    op.drop_table(IN_CALL)

    # Bracketed: `copilot_consents` is FORCE RLS and fail-closed on an unset `app.tenant_id`,
    # so an unbracketed count reads zero on any deployment and the refusal below never fires
    # (`b6e41d9c3a72`'s bracket; DDL is transactional, so FORCE is back before commit).
    op.execute(f"ALTER TABLE {CONSENTS} NO FORCE ROW LEVEL SECURITY")
    withdrawn = (
        op.get_bind()
        .execute(sa.text(f"SELECT count(*) FROM {CONSENTS} WHERE kind = 'withdrawn'"))
        .scalar_one()
    )
    op.execute(f"ALTER TABLE {CONSENTS} FORCE ROW LEVEL SECURITY")
    if withdrawn:
        raise RuntimeError(
            f"{withdrawn} account(s) have turned Pip off; dropping copilot_consents.kind "
            "would read those rows as acceptances and turn Pip back on. Not downgraded."
        )
    op.drop_constraint(op.f(f"ck_{CONSENTS}_kind_enum"), CONSENTS, type_="check")
    op.drop_column(CONSENTS, "kind")
