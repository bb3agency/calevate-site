"""platform_state carries Calevate's OWN telemarketer registration

Revision ID: d7f2a3c9b410
Revises: c5a930e6b1d4
Create Date: 2026-08-11 14:10:00.000000

The other half of SEC-COMP §3's first bullet. `c5a930e6b1d4` modelled the CLIENT side
— each tenant's Principal Entity registration and its link to us — and said in its own
docstring what it was leaving behind: "Calevate's OWN TM registration, the company-level
blocker in the same §3 bullet ... one boolean for the whole platform, true or false for
every tenant simultaneously". This is that column, in the place that docstring named.

**Why `platform_state` and not `dlt_registrations`.** The TM registration is ONE fact
about ONE entity: us. Copied per tenant it becomes N facts that drift — a client
onboarded in March saying we are registered and one onboarded in July saying we are
not, with no way to tell which row is the platform. It belongs beside the other global
switches (the load-shed mode, the big red switch) because it answers the same question
they do: is this platform allowed to place calls right now. One row, one read, one
place for ops to change it.

**Not RLS'd, and correctly so.** `platform_state` carries no `tenant_id`, so hard rule 1
does not reach it and neither does `check_rls_coverage` (which walks tables that HAVE
the column). It is global by definition and writable only through the audited,
step-up-confirmed ops surface.

**Seeded `not_registered`, deliberately.** The honest value: R-01 in the risk register
is precisely that our TM registration requires an entity we are still standing up.
Seeding `active` would be inventing a registration number, and the CHECK below makes
that impossible to do by accident — `active` requires both a `tm_id` and a
`tm_registered_at`, on the same principle as the PE table's "an active registration
that cannot say which registration it is, is a claim, not a fact". The consequence is
intended: on a fresh database no campaign launches until ops records the registration.
That is not a regression, it is the gate finally being able to ask.

**`tm_verified_at` vs `tm_registered_at`.** The registrar's date, and the date WE last
confirmed it. A TM registration can be suspended underneath us exactly like a client's
PE registration can, so the row records when we last looked rather than what we last
hoped — same reason `dlt_registrations.verified_at` exists.

**Locking.** Four `ADD COLUMN`s with constant defaults are metadata-only in PG 16 (no
table rewrite) and this table has exactly one row, so the ACCESS EXCLUSIVE lock is held
for microseconds. `lock_timeout` is set anyway: every reader of this row is on the
outbound path, and queueing behind a migration is worse than failing fast and retrying.

**Downgrade** drops the four columns, which loses the recorded registration and — since
the launch gate reading it goes away in the same release — re-opens the company-level
half of the gate. A revert here is a compliance decision, not a rollback detail.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7f2a3c9b410"
down_revision: str | None = "c5a930e6b1d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "platform_state",
        sa.Column(
            "tm_registration_status",
            sa.String(),
            server_default="not_registered",
            nullable=False,
        ),
    )
    # The registrar's telemarketer id (TM-xxxxxxxx). Text, not a number: it is an
    # identifier we echo back to a regulator, never something we do arithmetic on.
    op.add_column("platform_state", sa.Column("tm_id", sa.Text(), nullable=True))
    op.add_column(
        "platform_state", sa.Column("tm_registered_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "platform_state", sa.Column("tm_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_platform_state_tm_registration_enum"),
        "platform_state",
        "tm_registration_status IN "
        "('not_registered', 'submitted', 'active', 'suspended', 'revoked')",
    )
    op.create_check_constraint(
        op.f("ck_platform_state_active_tm_registration_names_itself"),
        "platform_state",
        "tm_registration_status <> 'active' OR "
        "(tm_id IS NOT NULL AND tm_registered_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(
        op.f("ck_platform_state_active_tm_registration_names_itself"),
        "platform_state",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_platform_state_tm_registration_enum"), "platform_state", type_="check"
    )
    op.drop_column("platform_state", "tm_verified_at")
    op.drop_column("platform_state", "tm_registered_at")
    op.drop_column("platform_state", "tm_id")
    op.drop_column("platform_state", "tm_registration_status")
