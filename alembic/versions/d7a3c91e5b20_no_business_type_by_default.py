"""No account is a clinic unless somebody chose it (D-722, founder 11 Oct 2026)

Revision ID: d7a3c91e5b20
Revises: b6d2f8a4c9e1
Create Date: 2026-10-11 12:00:00.000000

Until 11 Oct 2026 the operator wizard pre-selected `clinic` (and the API defaulted to it), so
an operator who did not touch the picker created a clinic. Raghava Organics, a chilli and
chilli-powder shop, was created that way and its calls captured "Symptom / reason",
"Preferred doctor" and "Insurance". Nothing recorded whether a type was chosen or defaulted:
`audit_log` stores `organization.created` with the slug only and the vertical travels in the
log-stream summary, which is not queryable from here. So every clinic account is treated as
UNCONFIRMED:

* `vertical_template` moves to the new `unconfirmed_business_type` and is cleared, so every
  reader of the type (lead fields, starters, examples, the assistant) sees an account with
  no type and falls back to the neutral core. `caller_memory` reads both columns, so an
  unconfirmed clinic is refused cross-call memory exactly as a confirmed one is.
* Raghava Organics (01a12103-9681-7f10-a7d3-526ac0beed7c, when it exists here) is set to
  `retail` ("Shop, food or produce"), the founder's decision.
* Each of those accounts gets one `apply_business_type` outbox message. The worker
  (`apps/workers/business_type.py`) replaces the clinic default fields on its agents (the
  type's standard set for Raghava, the neutral core for the rest), recompiles each agent's
  script so it stops asking callers for them, republishes live agents through the one
  publish path, and asks the dashboard AI for a suggested type for the unconfirmed ones.
  Agents whose fields somebody edited away from the clinic set keep their fields.

Also adds the suggestion columns the admin "Confirm business type" prompt reads.

DOWNGRADE puts `clinic` back on every unconfirmed account and drops the columns. It does not
revert Raghava to clinic (that was the defect being repaired) and does not delete the schema
or prompt versions the worker wrote: those are immutable history, and the earlier versions
are still on file.
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "d7a3c91e5b20"
down_revision: str | None = "b6d2f8a4c9e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

#: FROZEN COPIES, not imports: a migration must keep meaning what it meant on the day.
CLINIC = "clinic"
RETAIL = "retail"
RAGHAVA_ORGANICS = "01a12103-9681-7f10-a7d3-526ac0beed7c"
#: `apps/api/admin/business_type.APPLY_JOB`.
APPLY_JOB = "apply_business_type"
CHECK = "ck_organizations_business_type_chosen_or_unconfirmed"


def upgrade() -> None:
    op.add_column("organizations", sa.Column("unconfirmed_business_type", sa.Text()))
    op.add_column("organizations", sa.Column("suggested_business_type", sa.Text()))
    op.add_column("organizations", sa.Column("suggested_business_type_reason", sa.Text()))
    op.add_column(
        "organizations",
        sa.Column("business_type_suggested_at", sa.DateTime(timezone=True)),
    )

    # The FORCE bracket (`f4a2c7e19d63`): `organizations` is FORCE-RLS'd, so without it
    # these statements match no rows.
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    raghava = execute_data_statement(
        sa.text(
            f"UPDATE organizations SET vertical_template = '{RETAIL}', updated_at = now() "
            f"WHERE id = '{RAGHAVA_ORGANICS}' AND deleted_at IS NULL"
        ),
        note="Set Raghava Organics to 'Shop, food or produce' (founder, 11 Oct 2026).",
    )
    unconfirmed = execute_data_statement(
        sa.text(
            "UPDATE organizations SET unconfirmed_business_type = vertical_template, "
            f"vertical_template = NULL, updated_at = now() WHERE vertical_template = '{CLINIC}' "
            "AND deleted_at IS NULL"
        ),
        note="Moved every clinic account to unconfirmed: nothing recorded who chose clinic.",
    )
    queued = execute_data_statement(
        sa.text(
            "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, created_at, "
            f"updated_at) SELECT gen_random_uuid(), '{APPLY_JOB}', "
            "jsonb_build_object('tenant_id', id::text, 'replace_clinic_default', true), "
            "'pending', 0, now(), now() FROM organizations WHERE deleted_at IS NULL AND ("
            f"unconfirmed_business_type IS NOT NULL OR id = '{RAGHAVA_ORGANICS}')"
        ),
        note="Queued the field refit, script recompile and AI suggestion for each of them.",
    )
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    log.info(
        "business type: raghava=%s unconfirmed=%s queued=%s", raghava, unconfirmed, queued
    )

    op.execute(
        f"ALTER TABLE organizations ADD CONSTRAINT {CHECK} CHECK "
        "(unconfirmed_business_type IS NULL OR vertical_template IS NULL)"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT {CHECK}")
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    execute_data_statement(
        sa.text(
            "UPDATE organizations SET vertical_template = unconfirmed_business_type, "
            "updated_at = now() WHERE unconfirmed_business_type IS NOT NULL"
        ),
        note="Put the unconfirmed business type back as the account's type.",
    )
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.drop_column("organizations", "business_type_suggested_at")
    op.drop_column("organizations", "suggested_business_type_reason")
    op.drop_column("organizations", "suggested_business_type")
    op.drop_column("organizations", "unconfirmed_business_type")
