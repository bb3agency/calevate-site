"""kyc_records — the subscriber verification nothing in the schema modelled

Revision ID: a3f6b1e02d95
Revises: e7c3d10a9f52
Create Date: 2026-08-12 10:20:00.000000

SURFACES §2b, last bullet of the self-serve list: "**Number purchase + KYC**: gated;
calling stays disabled until verification clears." It is the final R-11 mitigation
(BRD §245) and it was the only one with nothing behind it — no table, no column, no
blocker, no route. This migration gives it somewhere to live.

WHAT THE LAW ACTUALLY ASKS FOR, AND WHY THIS IS NOT THE DLT REGISTRATION
------------------------------------------------------------------------
Researched before the column list was written (sources cited in
`apps/api/compliance/kyc.py`; summarised here so a reviewer reading the schema does
not have to go looking):

* DoT replaced "bulk connections" with **business connections** (instructions of
  31 Aug 2023, expanded May 2024). To issue one, the licensee must obtain the
  subscribing entity's **CIN / business licence / trade registration**, its
  **address**, its **GST certificate where applicable**, and a **list of end-users**
  with name, designation and identity-document details. A June 2025 DoT circular
  extends the same KYC to internet-telephony connections issued under the business
  category — a cloud-telephony number is not a lesser thing than a SIM.
* The **Telecommunications Act 2023 s.3(7)** requires authorised entities to identify
  their users, and procuring a telecom identifier on someone else's identity carries
  up to three years and ₹50 lakh. This is the exposure R-11 names: on a self-serve
  motion the person signing up is a stranger, and "we did not know who they were" is
  not a defence anyone has ever won with.
* **DLT Principal Entity registration overlaps but does not subsume it.** PE
  registration asks for PAN, GST/CIN and the authorised signatory's government ID on
  letterhead — the same *entity documents* — but it is held by an access provider on
  its DLT portal, for the purpose of headers and templates, and it says nothing about
  the *connection*: no address tied to the number's city, no end-user list, no CAF.
  So this table deliberately does NOT re-ask what `dlt_registrations` already holds,
  and it does not duplicate `pe_id`. It records the one fact that registration cannot
  supply: **that a person at Calevate verified this business's identity against a
  named document, on a date, and the evidence for it is filed under a reference.**

SHAPE, AND THE TWO QUESTIONS IT HAS TO ANSWER
---------------------------------------------
An **auditor** asks: what was verified, by whom, when, against what document
reference. Those are four NOT NULL-when-verified columns, enforced by
`ck_kyc_records_verified_names_its_evidence` rather than by a convention — a
`status='verified'` row that cannot say who verified it or against what is a claim,
exactly as `dlt_registrations`' active-registration CHECK says of a PE id.

A **support person** asks: why is this account blocked. That is `status` plus
`rejection_reason`, and `ck_kyc_records_rejected_names_its_reason` makes a rejection
that cannot be explained unstorable — "rejected, no reason recorded" is the ticket
nobody can close.

**Never the document itself.** `document_ref` holds the *public business-registry
identifier* (CIN, LLPIN, GSTIN, Udyam) — company-register data, not personal data —
and `evidence_ref` holds a REFERENCE to where the verification pack is filed, the
same discipline `outbound_webhooks.secret_ref` uses for credentials. No scan, no
image, no Aadhaar, no PAN of a natural person is stored anywhere in this schema.
`ck_kyc_records_document_ref_is_not_an_aadhaar` is a cheap structural guard on that
promise: an Aadhaar number is exactly twelve digits and none of the permitted
registry identifiers is (GSTIN 15, CIN 21, LLPIN 8, Udyam 19), so a bare 12-digit
value in that column is a DPDP incident being typed in and the database refuses it.
It is a backstop, not the control — the control is that the enum names only entity
registries — but it costs one regex and it fails at the moment of the mistake.

`signatory_name` is the natural person who signed for the entity. A NAME, deliberately
without their identity-document number: the licensee's CAF holds that, we hold who to
ask for. It is the minimum that makes the record usable and the maximum that does not
turn this table into a personal-data store.

MUTABLE, ONE ROW PER TENANT
---------------------------
Same reasoning as `dlt_registrations` and the same absence from `APPEND_ONLY_TABLES`:
a verification is submitted, cleared, and later expires or is withdrawn when the
entity's registration lapses, and the gate must read the CURRENT state cheaply on
every dial. Who changed it and when is `audit_log`'s job, where the immutability
requirement already lives — `kyc.recorded` is written there by the ops route.

RLS
---
New tenant table, so hard rule 1 in full: `tenant_id`, ENABLE + FORCE, and the
standard DATA-MODEL §1 `tenant_isolation` policy created HERE, beside the table. The
contents are a business's own registry identifiers; there is no cross-tenant read path
that would justify an exemption and no global row (unlike `dnc_list`, whose asymmetric
policy exists because a national suppression must be visible to everyone). The
cross-tenant zero-rows proof is `tests/kyc_gate_test.py::
test_tenant_b_cannot_see_tenant_as_kyc_record`, which asserts it through the route AND
on the raw RLS-scoped session, so an endpoint that filtered in Python would still fail.

LOCKING
-------
`CREATE TABLE` on a table nothing references yet takes locks only on itself, as do the
policy statements; the only foreign keys point OUT, at `organizations` and
`admin_users`, and a new FK takes a SHARE ROW EXCLUSIVE on the referenced table which
would block writes there for as long as it validates. Both are small, but "small
today" is not a locking argument, so the constraints are added NOT VALID and VALIDATEd
separately: the NOT VALID add takes the lock for a catalogue write only, and VALIDATE
takes a weaker SHARE UPDATE EXCLUSIVE that does not block inserts into
`organizations`. `lock_timeout` is set on both statements so a migration that cannot
get its lock fails fast instead of queueing behind a long read and stalling every
writer behind IT.

DOWNGRADE
---------
Drops the policy, the index, then the table, and is exercised
(upgrade → downgrade → upgrade) rather than assumed. It loses recorded verifications —
unavoidable, this table is the only place they live — and it re-opens the provisioning
gate, so a revert is a compliance decision, not a rollback detail.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3f6b1e02d95"
down_revision: str | None = "e7c3d10a9f52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns ''
# when unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON kyc_records USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        "kyc_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(), server_default="not_started", nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=True),
        sa.Column("document_kind", sa.Text(), nullable=True),
        sa.Column("document_ref", sa.Text(), nullable=True),
        sa.Column("signatory_name", sa.Text(), nullable=True),
        sa.Column("evidence_ref", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("verified_by_admin_id", sa.UUID(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('not_started', 'submitted', 'in_review', 'verified', "
            "'rejected', 'expired')",
            name=op.f("ck_kyc_records_status_enum"),
        ),
        sa.CheckConstraint(
            "entity_type IS NULL OR entity_type IN ('sole_proprietorship', 'partnership', "
            "'llp', 'private_limited', 'public_limited', 'trust_or_society', 'huf')",
            name=op.f("ck_kyc_records_entity_type_enum"),
        ),
        # Entity registries ONLY. No member here identifies a natural person, which is
        # what keeps `document_ref` out of DPDP scope: a CIN or a GSTIN is published
        # data about a business, an Aadhaar or a personal PAN is not.
        sa.CheckConstraint(
            "document_kind IS NULL OR document_kind IN ('cin', 'llpin', 'gstin', "
            "'udyam', 'shop_establishment', 'trade_licence')",
            name=op.f("ck_kyc_records_document_kind_enum"),
        ),
        # The auditor's four questions, as a constraint: what, against what reference,
        # by whom, when. A `verified` row missing any of them is not evidence.
        sa.CheckConstraint(
            "status <> 'verified' OR (document_kind IS NOT NULL AND document_ref IS NOT NULL "
            "AND verified_by_admin_id IS NOT NULL AND verified_at IS NOT NULL)",
            name=op.f("ck_kyc_records_verified_names_its_evidence"),
        ),
        # The support person's question, as a constraint.
        sa.CheckConstraint(
            "status <> 'rejected' OR rejection_reason IS NOT NULL",
            name=op.f("ck_kyc_records_rejected_names_its_reason"),
        ),
        # Backstop against an Aadhaar being typed into a business-registry field. See
        # the module docstring: no permitted registry identifier is 12 bare digits.
        sa.CheckConstraint(
            "document_ref IS NULL OR document_ref !~ '^[0-9]{12}$'",
            name=op.f("ck_kyc_records_document_ref_is_not_an_aadhaar"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kyc_records")),
        sa.UniqueConstraint("tenant_id", name=op.f("uq_kyc_records_tenant_id")),
    )
    op.create_index(op.f("ix_kyc_records_tenant_id"), "kyc_records", ["tenant_id"], unique=False)

    # NOT VALID first, VALIDATE second — see the LOCKING note. Both FKs point at tables
    # that are read on every request; neither may have its writes blocked by a scan of
    # a table that is empty at this instant anyway.
    op.execute(
        "ALTER TABLE kyc_records ADD CONSTRAINT fk_kyc_records_tenant_id_organizations "
        "FOREIGN KEY (tenant_id) REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID"
    )
    op.execute(
        "ALTER TABLE kyc_records ADD CONSTRAINT fk_kyc_records_verified_by_admin_users "
        "FOREIGN KEY (verified_by_admin_id) REFERENCES admin_users (id) "
        "ON DELETE RESTRICT NOT VALID"
    )
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "ALTER TABLE kyc_records VALIDATE CONSTRAINT fk_kyc_records_tenant_id_organizations"
    )
    op.execute(
        "ALTER TABLE kyc_records VALIDATE CONSTRAINT fk_kyc_records_verified_by_admin_users"
    )

    # Hard rule 1, in the same migration as the table it protects.
    op.execute("ALTER TABLE kyc_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kyc_records FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON kyc_records")
    op.drop_index(op.f("ix_kyc_records_tenant_id"), table_name="kyc_records")
    op.drop_table("kyc_records")
