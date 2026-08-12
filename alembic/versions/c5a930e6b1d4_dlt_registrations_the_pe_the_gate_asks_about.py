"""dlt_registrations — the Principal Entity the launch gate could not ask about

Revision ID: c5a930e6b1d4
Revises: b8e4c1d70f92
Create Date: 2026-08-11 09:45:00.000000

SEC-COMP §3's FIRST bullet: "Calevate TM registration exists AND this client's PE
registration + TM-link are active (inbound-only operation is the interim mode while
pending)." Nothing in the schema recorded any of it. `launch_blockers` could not check
a fact that did not exist anywhere, so the most fundamental of the five conditions was
the only one with no code at all.

**Three registrations, not one.** The DLT registrar issues them separately and this
schema already carried two of them:

- the HEADER/number — `phone_numbers.dlt_status`, checked as `number_not_registered`;
- the voice TEMPLATE — `dlt_templates.status`, checked as `dlt_template_not_approved`;
- the ENTITY — this table, and nothing else in the schema implies it.

The third does not follow from the other two. A number can carry `dlt_status =
'registered'` in our database — a value an operator types in after provisioning —
while the entity behind it is suspended after a spam-complaint run (§1: 5+ complaints
in a rolling 10 days ⇒ TSP enforcement within 5 days). Registration state is a fact
about the CLIENT that changes underneath us, which is why the row carries `verified_at`
— when WE last looked, as opposed to what we last hoped.

**Shape.** One row per tenant, UNIQUE on `tenant_id`: a business is one Principal
Entity. PE status and TM-link status are two columns rather than one collapsed
`ready BOOL`, because they fail separately and the client's next action differs — an
unregistered entity is a ₹5,900 registration we execute for them, a missing TM-link is
an authorisation only they can grant. The gate names them separately for the same
reason. `status = 'active'` additionally requires a `pe_id` and a `registered_at`: an
active registration that cannot say which registration it is, is a claim, not a fact.

**Mutable, deliberately.** This is not an append-only ledger and is absent from
`APPEND_ONLY_TABLES`. A registration is suspended and restored over its life, and the
gate must read the CURRENT state cheaply on every launch preview; who changed it and
when is `audit_log`'s job, which is where the immutability requirement already lives.

**RLS.** New tenant table, so hard rule 1 applies in full: `tenant_id`, ENABLE + FORCE,
and the standard `tenant_isolation` policy from DATA-MODEL §1 — created in THIS
migration, next to the table, with `tests/consent_provenance_test.py` proving the
cross-tenant read returns zero rows and the cross-tenant write reaches none. The
contents are a client's own registrar identifiers; there is no cross-tenant read path
that would justify an exemption, and the gate always runs inside the tenant's own GUC.
The standard form (not `dnc_list`'s asymmetric one) is right here because there is no
such thing as a global PE registration: every row belongs to exactly one client.

**What is still missing after this migration**, stated so it is not mistaken for done:
Calevate's OWN TM registration, the company-level blocker in the same §3 bullet. It is
one boolean for the whole platform, true or false for every tenant simultaneously, and
it belongs beside the other global switches in `platform_state` (DATA-MODEL §9a) — not
copied into every tenant's row, where N copies would eventually disagree. That table is
the ops surface's, not this module's, and the gate gains a `tm_registration_missing`
blocker when it lands.

**Locking.** `CREATE TABLE` on a table nothing references yet takes locks only on
itself, and the policy statements likewise. Nothing here touches `campaigns`, `calls`
or any table another suite is reading, so a concurrent test run sees no contention at
all. `lock_timeout` is set anyway, on the same fail-fast-rather-than-queue principle
as the migration before it.

**Downgrade** drops the policy and then the table, in that order, and is exercised
(upgrade → downgrade → upgrade) rather than assumed. It loses recorded registrations,
which is unavoidable — the table is the only place they live — and it re-opens the
gate, so a revert is a compliance decision, not a rollback detail.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5a930e6b1d4"
down_revision: str | None = "b8e4c1d70f92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns ''
# when unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON dlt_registrations USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        "dlt_registrations",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("pe_id", sa.Text(), nullable=True),
        sa.Column("entity_name", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), server_default="not_started", nullable=False),
        sa.Column("tm_link_status", sa.String(), server_default="not_linked", nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('not_started', 'submitted', 'active', 'suspended', 'rejected')",
            name=op.f("ck_dlt_registrations_status_enum"),
        ),
        sa.CheckConstraint(
            "tm_link_status IN ('not_linked', 'pending', 'active', 'revoked')",
            name=op.f("ck_dlt_registrations_tm_link_status_enum"),
        ),
        sa.CheckConstraint(
            "status <> 'active' OR (pe_id IS NOT NULL AND registered_at IS NOT NULL)",
            name=op.f("ck_dlt_registrations_active_registration_names_its_pe"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_dlt_registrations_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dlt_registrations")),
        sa.UniqueConstraint("tenant_id", name=op.f("uq_dlt_registrations_tenant_id")),
    )
    op.create_index(
        op.f("ix_dlt_registrations_tenant_id"), "dlt_registrations", ["tenant_id"], unique=False
    )

    # Hard rule 1, in the same migration as the table it protects.
    op.execute("ALTER TABLE dlt_registrations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE dlt_registrations FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON dlt_registrations")
    op.drop_index(op.f("ix_dlt_registrations_tenant_id"), table_name="dlt_registrations")
    op.drop_table("dlt_registrations")
