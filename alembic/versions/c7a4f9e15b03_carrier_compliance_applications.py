"""carrier_compliance_applications — the reseller stage the tenant lifecycle was missing

Revision ID: c7a4f9e15b03
Revises: b8c3e50d4917
Create Date: 2026-09-13 09:40:00.000000

WHAT THIS IS FOR
----------------
`docs/evidence/orchestrator-commercial-and-carrier-2026-09-13.md` §5.2: the carrier
distinguishes a **Direct Brand** (one compliance application, for the brand's own calls)
from a **Reseller** (*a separate approved compliance application for each customer*).
Calevate sells agents to other businesses, so Calevate is a reseller — and every tenant
therefore needs its own carrier compliance application, ACCEPTED, before a number can be
rented for them or assigned to them. That evidence document states plainly that this
"means the tenant lifecycle gains a gating, human-signature-bearing KYC stage between
'client signs up' and 'client has a number' … None of that exists today." This migration
is where it starts existing.

EVIDENCE CLASS — READ BEFORE TREATING ANY COLUMN AS A VENDOR FACT
-----------------------------------------------------------------
Everything we believe about the carrier's requirements is **REPORTED — research-agent
reading, founder-relayed, 12 Sep 2026** (that document's §0). `www.plivo.com` is
egress-blocked from this container, re-measured 13 Sep 2026, so nobody in this repository
has opened the page. Under hard rule 11 that class may not reach money, a wire value or a
client-facing claim without re-reading from the primary source.

The schema is shaped by that, not merely annotated with it:

* **We model OUR state machine and STORE THEIR identifier.** `status` is the six states
  *we* can know — `not_started`, `documents_required`, `submitted`, `accepted`,
  `rejected`, `expired` — and the carrier's own status string is MAPPED onto them in
  `apps/api/compliance/carrier_application.py`, never stored as our truth. A vendor that
  renames a status, or a reseller migration to a different carrier, then costs one
  mapping table and no data migration.
* **No vendor constraint is baked into a CHECK.** Their document list, their ~5 MB file
  ceiling and their ~99-character filename limit are REPORTED numbers; they live in ONE
  named constant each, in that module, with the evidence class and the date beside them,
  so a wrong value is one edit and not a migration. The single exception is
  `document_kind`, which is an enum of OUR vocabulary for what a client supplied — it has
  to be closed because the gate and the console both switch on it.
* **Their approval SLA is not modelled at all.** The research reports "typically 5
  minutes" for landline series and says the 140/160 SLA is *not published*. A column
  holding a promised turnaround would be a claim this repository cannot support, and a
  screen would then show it to a client.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
* **The registry identifier.** `kyc_records.document_ref` already holds this business's
  GSTIN / CIN / Udyam number (migration a3f6b1e02d95), and two columns holding one fact
  is how they start disagreeing. This table records what was SUPPLIED TO THE CARRIER —
  which kind of document, and where the bytes are — not what the number on it says.
* **The document bytes.** Hard rule 2's discipline applied to a client's own paperwork:
  `document_object_ref` and `signed_application_ref` are object-store KEYS
  (`workers/storage.carrier_document_key`), never `bytea`. The key names the tenant and
  the application, so an account offboarding can enumerate every object by prefix.
* **A per-number application id.** The evidence says a purchase *carries* a
  `compliance_application_id`; that is a purchase-time input read from this row, not a
  second copy beside `phone_numbers`. When a number is bought we know the tenant, and the
  tenant is what this row is keyed on.

ONE ROW PER TENANT PER CARRIER, MUTABLE
---------------------------------------
Same reasoning as `kyc_records` and `dlt_registrations`, and the same absence from
`APPEND_ONLY_TABLES`: an application is submitted, decided, later expires or is suspended
after unresolved UCC complaints (§5.6), and the gate must read the CURRENT state cheaply
on every dial and every number purchase. WHO changed it and when is `audit_log`'s job,
where the immutability requirement already lives.

`carrier` is in the key rather than assumed because an application identifier is
meaningless without knowing whose it is, and because §5.5 records that the carrier choice
is not closed (Exotel "not eliminated, not evaluable"). It carries a one-member CHECK
today: the account that exists is the Plivo one.

THE CHECKS, AND THE QUESTION EACH ANSWERS
-----------------------------------------
* `ck_..._submitted_names_its_documents` — an application that has been SENT names what
  was sent and when. A `submitted` row with no document reference is a state nobody can
  act on, in either direction.
* `ck_..._accepted_names_the_carriers_id` — an `accepted` application that cannot produce
  the carrier's `compliance_application_id` is unusable: that id is what a number
  purchase has to carry. Acceptance without it is a green light attached to nothing.
* `ck_..._rejected_names_its_reason` — `kyc_records`' rule, for its reason: "rejected, no
  reason recorded" is the ticket nobody can close.
* `ck_..._decided_names_its_operator` — an acceptance or a rejection is a fact a person at
  Calevate relayed from the carrier. A decision nobody signed is not evidence.

RLS
---
New tenant table, so hard rule 1 in full: `tenant_id`, ENABLE + FORCE, and the standard
DATA-MODEL §1 `tenant_isolation` policy created HERE, in the same migration as the table.
The contents are a business's own registration paperwork; there is no cross-tenant read
path that would justify an exemption. The cross-tenant zero-rows proof is
`tests/carrier_compliance_test.py::test_tenant_b_cannot_see_tenant_as_application`, which
asserts it through the route AND on the raw RLS-scoped session, so an endpoint that
filtered in Python would still fail.

LOCKING
-------
`CREATE TABLE` on a table nothing references yet takes locks only on itself, as do the
policy statements. The foreign keys point OUT, at `organizations` and `admin_users`, and
a new FK takes a SHARE ROW EXCLUSIVE on the referenced table for as long as it validates
— so they are added NOT VALID and VALIDATEd separately, exactly as a3f6b1e02d95 does, and
`lock_timeout` is set so a migration that cannot get its lock fails fast instead of
queueing in front of every writer.

DOWNGRADE
---------
Drops the policy, the index, then the table, and is exercised (upgrade → downgrade →
upgrade) rather than assumed. It loses recorded applications — unavoidable, this table is
the only place they live — and it re-opens the carrier gate, so a revert is a compliance
decision and not a rollback detail. The stored objects are NOT deleted by it: bytes a
client uploaded outliving a schema revert is the recoverable direction.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7a4f9e15b03"
down_revision: str | None = "b8c3e50d4917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns ''
# when unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON carrier_compliance_applications USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)

# The statuses that mean "this has been sent to the carrier", i.e. everything from
# `submitted` onwards. Written once and interpolated into the CHECK below so the
# constraint and the reader of it cannot drift.
_SENT_STATUSES = "('submitted', 'accepted', 'rejected', 'expired')"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        "carrier_compliance_applications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("carrier", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), server_default="not_started", nullable=False),
        # THEIR identifier, ours to carry and never to interpret. A number purchase has
        # to quote it, which is the whole reason acceptance is worth recording.
        sa.Column("carrier_application_id", sa.Text(), nullable=True),
        sa.Column("document_kind", sa.Text(), nullable=True),
        # Object-store KEYS (hard rule 2's discipline; `workers/storage.py` mints them).
        sa.Column("document_object_ref", sa.Text(), nullable=True),
        sa.Column("document_filename", sa.Text(), nullable=True),
        # The application form signed by the authorised signatory and carrying the
        # company seal. Nullable because the reported rule scopes the signature to the
        # FIRST application, and because a client may supply the two files in two visits.
        sa.Column("signed_application_ref", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("recorded_by_admin_id", sa.UUID(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
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
        # OUR vocabulary for the carrier's lifecycle, not theirs — see the docstring.
        sa.CheckConstraint(
            "status IN ('not_started', 'documents_required', 'submitted', 'accepted', "
            "'rejected', 'expired')",
            name=op.f("ck_carrier_compliance_applications_status_enum"),
        ),
        # One member, because one carrier account exists. In the key rather than assumed
        # so a stored application id always says whose it is.
        sa.CheckConstraint(
            "carrier IN ('plivo')",
            name=op.f("ck_carrier_compliance_applications_carrier_enum"),
        ),
        # WHICH proof of registration the client supplied. Closed because the gate and
        # the console both switch on it; the list itself is REPORTED and lives as a
        # Python constant too, where its evidence class is recorded.
        sa.CheckConstraint(
            "document_kind IS NULL OR document_kind IN ('gst_certificate', "
            "'certificate_of_incorporation', 'udyam_registration')",
            name=op.f("ck_carrier_compliance_applications_document_kind_enum"),
        ),
        sa.CheckConstraint(
            f"status NOT IN {_SENT_STATUSES} OR (document_kind IS NOT NULL "
            "AND document_object_ref IS NOT NULL AND submitted_at IS NOT NULL)",
            name=op.f("ck_carrier_compliance_applications_submitted_names_its_documents"),
        ),
        sa.CheckConstraint(
            "status <> 'accepted' OR (carrier_application_id IS NOT NULL "
            "AND decided_at IS NOT NULL)",
            name=op.f("ck_carrier_compliance_applications_accepted_names_the_carriers_id"),
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR (rejection_reason IS NOT NULL AND decided_at IS NOT NULL)",
            name=op.f("ck_carrier_compliance_applications_rejected_names_its_reason"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('accepted', 'rejected') OR recorded_by_admin_id IS NOT NULL",
            name=op.f("ck_carrier_compliance_applications_decided_names_its_operator"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_carrier_compliance_applications")),
        sa.UniqueConstraint(
            "tenant_id", "carrier", name=op.f("uq_carrier_compliance_applications_tenant_carrier")
        ),
    )
    op.create_index(
        op.f("ix_carrier_compliance_applications_tenant_id"),
        "carrier_compliance_applications",
        ["tenant_id"],
        unique=False,
    )

    # NOT VALID first, VALIDATE second — see the LOCKING note. Both referenced tables are
    # read on every request and neither may have its writes blocked by a scan of a table
    # that is empty at this instant anyway.
    op.execute(
        "ALTER TABLE carrier_compliance_applications ADD CONSTRAINT "
        "fk_carrier_compliance_applications_tenant_id_organizations "
        "FOREIGN KEY (tenant_id) REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID"
    )
    op.execute(
        "ALTER TABLE carrier_compliance_applications ADD CONSTRAINT "
        "fk_carrier_compliance_applications_recorded_by_admin_users "
        "FOREIGN KEY (recorded_by_admin_id) REFERENCES admin_users (id) "
        "ON DELETE RESTRICT NOT VALID"
    )
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "ALTER TABLE carrier_compliance_applications VALIDATE CONSTRAINT "
        "fk_carrier_compliance_applications_tenant_id_organizations"
    )
    op.execute(
        "ALTER TABLE carrier_compliance_applications VALIDATE CONSTRAINT "
        "fk_carrier_compliance_applications_recorded_by_admin_users"
    )

    # Hard rule 1, in the same migration as the table it protects.
    op.execute("ALTER TABLE carrier_compliance_applications ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE carrier_compliance_applications FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON carrier_compliance_applications"
    )
    op.drop_index(
        op.f("ix_carrier_compliance_applications_tenant_id"),
        table_name="carrier_compliance_applications",
    )
    op.drop_table("carrier_compliance_applications")
