"""the vendor copy an erasure cannot reach has a record and a clock

Revision ID: c9f4a2e17b83
Revises: b7d3e91c4a05
Create Date: 2026-08-22 11:20:00.000000

D-433. A DPDP §12 erasure runs our worker, deletes from Postgres and object storage, and
writes a certificate. The voice platform that carried the calls keeps its own copy of the
recording and the transcript, in the US, and **nothing in this repository recorded that it
survived.**

`docs/evidence/subprocessor-erasure-reach.md` §1 settles the question the code had been
carrying as open. Every `DELETE` route the vendor documents was enumerated across all 335
mirrored pages: ten routes, nine of which delete configuration objects, and the tenth
(`DELETE /v2/agent/{agent_id}`) deletes an agent together with "ALL agent data including
all batches, all executions" — the wrong granularity for a request about one person, since
using it destroys every other caller's records and takes the client's live receptionist off
the air. The Executions surface is four GETs; the Calling surface is one POST.

So the obligation is real, has no API, and until this migration had no record. A human
obligation with no record is one that is believed to have happened.

--------------------------------------------------------------------------------
WHY A TABLE AND NOT A FIELD ON THE PROOF
--------------------------------------------------------------------------------

The obvious cheaper shape is a key in `deletion_requests.proof`. It was rejected for a
reason the proof itself states: `deletion_proof.py` records that **nothing UPDATEs a
stored proof** — "not to back-fill the limitations into rows written before this module
existed, not for anything" — because a certificate already handed to a data principal must
not silently change under them. A vendor's answer arrives WEEKS after the certificate is
issued, so recording it in the proof would require exactly the mutation that design
forbids.

The task is therefore a separate object with its own lifecycle, and the certificate keeps
saying what was true when it was issued: a copy exists and a written request is the way to
remove it.

--------------------------------------------------------------------------------
NOT APPEND-ONLY, DELIBERATELY (hard rule 4)
--------------------------------------------------------------------------------

This table is NOT added to `APPEND_ONLY_TABLES`, and the omission is a decision rather than
an oversight. Hard rule 4's ledgers are evidence that something WAS true at an instant.
This is a task whose entire purpose is to change state — `open → requested → confirmed |
refused`. An append-only version would need a second table to answer "is it done?", which
is the only question it exists to answer. The immutable trail of who moved it and when is
`audit_log`, which already is append-only.

--------------------------------------------------------------------------------
HARD RULE 6 IS ENFORCED IN THE SCHEMA, NOT ONLY IN THE WRITER
--------------------------------------------------------------------------------

An operator has to be able to write the vendor a specific request — "delete these
executions" — without the table ever holding the caller's number. `subject_ref` is the
sha256 hash the certificate already carries, and `vendor_refs` holds OPAQUE VENDOR
IDENTIFIERS ONLY: execution ids and agent ids, strings the vendor itself minted.

`vendor_refs` is JSONB and would accept anything, so the constraint is written into the
database as well as into `compliance/processor_erasure.assert_vendor_refs_are_id_shaped`.
A CHECK rather than a convention for the same reason `b2e6f10c94d7` gives for using a
trigger: a convention protects the callers that remember it, a database object protects
the table. The night before this migration a defect was fixed in which the consent
ledger's evidence field was storing raw phone numbers — the same column shape, the same
class of writer, the same absent constraint.

The CHECK refuses any element that is not id-shaped and any element containing a run of 7
or more digits, which is what a phone number looks like once the '+' and the spaces are
stripped off.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c9f4a2e17b83"
down_revision = "b7d3e91c4a05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processor_erasure_tasks",
        # No server default: ids are uuid_v7 minted in Python (`db/base.PKMixin`, and
        # `open_tasks_for_request` for the raw-SQL writer). One generator, one ordering.
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # FK to `organizations`, matching every other tenant-scoped table and the ORM
        # model that declares it. It was missing here and the model declared it anyway,
        # which `orm_schema_fidelity_test` caught: a model is not a place to record an
        # intention, and the next autogenerate would have proposed adding it.
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # The erasure this obligation came from. NOT a foreign key: it points at either
        # `deletion_requests` or `tenant_erasure_requests` depending on `request_kind`,
        # and a nullable pair of FKs would let a row name both or neither. The kind is
        # the discriminator and the CHECK below keeps it honest.
        sa.Column("request_ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_kind", sa.Text(), nullable=False),
        sa.Column("processor", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        # The certificate's own sha256(number)[:32]. Nullable because a TENANT erasure has
        # no subject to hash — there is no one person it is about.
        sa.Column("subject_ref", sa.Text(), nullable=True),
        sa.Column(
            "vendor_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("vendor_reference", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "request_kind IN ('subject', 'tenant')", name="request_kind_is_known"
        ),
        sa.CheckConstraint(
            "processor IN ('voice_engine', 'speech', 'llm')", name="processor_is_known"
        ),
        sa.CheckConstraint(
            "status IN ('open', 'requested', 'confirmed', 'refused')", name="status_is_known"
        ),
        # A tenant erasure has no subject; a subject erasure must name one (as a hash).
        sa.CheckConstraint(
            "(request_kind = 'tenant') OR (subject_ref IS NOT NULL)",
            name="a_subject_task_names_its_subject",
        ),
        # Hard rule 6, in the database. Every element must be id-shaped AND must not
        # contain a 7+ digit run. `jsonb_array_elements_text` over an empty array yields
        # no rows, so `NOT EXISTS` is true and an empty list passes.
        # Written against the CANONICAL JSONB TEXT rather than over
        # `jsonb_array_elements_text`, because PostgreSQL refuses a subquery in a CHECK
        # ("cannot use subquery in check constraint") — which is worth recording, since
        # the element-wise form is the one everybody reaches for first.
        #
        # jsonb normalises its own rendering, verified rather than assumed:
        #   '["a","b-c"]'::jsonb::text  =>  ["a", "b-c"]      (comma SPACE)
        #   '[]'::jsonb::text           =>  []
        # so the separator in the pattern is ", " and the empty array is the optional
        # group matching nothing. The pattern is STRICTER than the element-wise version
        # it replaces: it also refuses nested objects, arrays and bare numbers, none of
        # which an opaque vendor id ever is.
        sa.CheckConstraint(
            "vendor_refs::text ~ "
            R"'^\[(\"[A-Za-z0-9_-]{1,128}\"(, \"[A-Za-z0-9_-]{1,128}\")*)?\]$'",
            name="vendor_refs_are_id_shaped",
        ),
        # A phone number is id-shaped by the rule above ("919876543210" passes), so it
        # gets its own rule. Separate from the shape check so a refusal names which rule
        # it broke.
        #
        # THE RULE IS "AN ELEMENT THAT IS ENTIRELY DIGITS", NOT "CONTAINS A DIGIT RUN",
        # and the difference was found by sabotage rather than reasoning. The first
        # version of this constraint refused any 7+ digit run anywhere in the rendered
        # array, and it rejected a REAL execution id on the first test row:
        # `b7140255-af33-4608-8e97-04dd944b8e48` contains "7140255". A uuid carries a
        # 7-digit run by chance often enough that the blunt rule would have failed
        # legitimate erasure tasks in production, which is the worst possible failure for
        # a control whose job is to make an obligation visible.
        #
        # Anchoring on the quotes is what makes it precise: `"` followed by 7+ digits and
        # then `"` is a bare number and nothing else — a uuid always has a hyphen or a
        # letter inside its quotes. A vendor id that is legitimately all digits is
        # refused too, and that is the right side to err on: it is indistinguishable from
        # a phone number, and `processor_erasure.py` says so in the error.
        sa.CheckConstraint(
            R"""vendor_refs::text !~ '"[0-9]{7,}"'""",
            name="vendor_refs_carry_no_phone_number",
        ),
    )

    # One task per (erasure, processor). The erasure job has a retry ladder and a replay
    # must not hand an operator the same vendor request twice; `open_tasks_for_request`
    # relies on this index for its ON CONFLICT.
    op.create_index(
        "uq_processor_erasure_request_processor",
        "processor_erasure_tasks",
        ["request_ref", "processor"],
        unique=True,
    )
    # The overdue sweep's access path: unanswered tasks, oldest first, per tenant.
    op.create_index(
        "ix_processor_erasure_open",
        "processor_erasure_tasks",
        ["tenant_id", "opened_at"],
        postgresql_where=sa.text("status IN ('open', 'requested')"),
    )

    # Hard rule 1: FORCEd RLS with the standard tenant_isolation policy. NULLIF because a
    # pooled connection that once had the GUC returns '' when it is unset, and ''::uuid
    # would ERROR rather than failing closed to zero rows.
    op.execute("ALTER TABLE processor_erasure_tasks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE processor_erasure_tasks FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON processor_erasure_tasks "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON processor_erasure_tasks")
    op.drop_index("ix_processor_erasure_open", table_name="processor_erasure_tasks")
    op.drop_index("uq_processor_erasure_request_processor", table_name="processor_erasure_tasks")
    op.drop_table("processor_erasure_tasks")
