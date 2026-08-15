"""recording erasure holds, and two constraints retention_policies never had

Revision ID: 9c1d3e7a05f4
Revises: e4f2a86b13d7
Create Date: 2026-08-15 10:10:00.000000

Three changes, one subject: making a retention/erasure promise a thing the DATABASE
holds rather than a thing every reader has to remember.

--------------------------------------------------------------------------------
1. `recording_erasure_holds` — the handle that survives the pointer clear
--------------------------------------------------------------------------------

`execute_deletion_request` sets `calls.recording_url = NULL` for every call it erases,
at any age (SEC-COMP §4 reserves the decision to destroy under-floor audio EARLY to the
founder, and nothing here takes it). That key was the ONLY handle anything in this system
had on the audio object. The retention sweep's recording arm reads
`WHERE recording_url IS NOT NULL`, so once the erasure cleared it the sweep could never
see the object again either.

Read that composition once more, because it is the defect this table closes: **filing a
DPDP erasure made the recording permanently undeletable.** A caller who never asked to be
forgotten had their audio expire on the tenant's recording policy; a caller who DID ask
had theirs orphaned in the bucket with nothing left that could name it. Neither reading of
the DPDP/TRAI tension wants that outcome, which is how it survived — it is not the answer
to the open question, it is the failure to ask it.

A hold row is the key, plus the earliest instant at which destroying it is lawful. DPDP
§12(3) requires erasure "unless retention of the same is necessary for the specified
purpose or for compliance with any law for the time being in force" — a retention
obligation defers an erasure, it does not extinguish it, and DPDP §8(7) makes keeping the
data past the end of that obligation a breach in its own right. So the row encodes a
SCHEDULE, not an exemption, and `apply_retention` destroys the bytes the first time it
runs after `erase_after`.

Not a ledger: `erased_at` is stamped on completion, so this table must never be added to
`db/registry.APPEND_ONLY_TABLES`. The append-only artifact of an erasure is
`deletion_requests.proof`, which is a different table and is untouched here.

RLS: `tenant_id` with the FORCEd `tenant_isolation` policy, verbatim from DATA-MODEL §1,
and a cross-tenant zero-rows test ships with it (hard rule 1).

--------------------------------------------------------------------------------
2. `retention_policies.ttl_days > 0`
--------------------------------------------------------------------------------

The table had exactly one guard — the 90-day recording floor — and nothing at all
stopping `ttl_days = 0` or a negative on the other three categories. A zero makes every
row of that category expired the moment it is written, so the next nightly tick would
anonymise a live client's entire CRM. The only thing preventing that today is that
nothing except onboarding writes these rows; "no writer does it yet" is a property of
this week's code, not a constraint, and this slice's whole subject is TTLs being enforced
at WRITE time rather than noticed at sweep time.

Verified clean before adding: `SELECT count(*) FROM retention_policies WHERE ttl_days <= 0`
returns 0 on the development database (122,753 rows).

--------------------------------------------------------------------------------
3. `retention_policies` UNIQUE (tenant_id, data_category)
--------------------------------------------------------------------------------

Two rows for one category is not a harmless duplicate. `sweep_tenant` loops over the
probe's rows and applies each policy it finds, so a second `lead` row with a shorter TTL
silently overrides the period the client agreed to — and a screen rendering "your
retention settings" has to pick one row to show, with no rule saying which. The DB now
refuses the ambiguity rather than leaving each reader to resolve it differently.

Verified clean before adding: the `GROUP BY tenant_id, data_category HAVING count(*) > 1`
probe returns no rows on the development database.

Both constraints go on `NOT VALID` and are VALIDATEd in a second statement — the
non-blocking pattern this repo uses — except the UNIQUE, which needs its index built
first; `CREATE UNIQUE INDEX` (non-concurrently, in the migration transaction) then
`ADD CONSTRAINT ... USING INDEX` is the equivalent, and on a table of this size the scan
is milliseconds.

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------

Drops the two constraints and then the table, policy first. It loses any scheduled
recording destructions that have not yet run, which is the honest cost: those rows are
the only place the orphaned keys are recorded, and a downgrade returns the system to the
state where the audio has no handle. Exercised up → down → up on a pristine database
rather than assumed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c1d3e7a05f4"
down_revision: str | None = "e4f2a86b13d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns ''
# when unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON recording_erasure_holds USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        "recording_erasure_holds",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        # The call survives an erasure as a stripped, countable shell (SEC-COMP §4), so
        # this FK is stable. RESTRICT everywhere, like every other tenant FK here:
        # offboarding is an explicit workflow, never a cascade.
        sa.Column("call_id", sa.UUID(), nullable=False),
        # WHICH erasure incurred the obligation, so a destruction can be tied back to the
        # certificate that promised it.
        sa.Column("request_id", sa.UUID(), nullable=False),
        # `recordings/{tenant}/{yyyy}/{mm}/{call}.wav` — names a call, not a person.
        sa.Column("object_key", sa.Text(), nullable=False),
        # The earliest instant destroying the bytes is lawful. NOT a TTL and not a
        # duration: the floor is measured from the call's own clock, which is settled by
        # the time this row is written and must not be recomputed later against a
        # different `now()`.
        sa.Column("erase_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # NULL until the sweep destroys the bytes. Kept rather than deleted so "when did
        # the audio actually go?" is answerable years later, next to the certificate that
        # said it would.
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_recording_erasure_holds_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name=op.f("fk_recording_erasure_holds_call_id_calls"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["deletion_requests.id"],
            name=op.f("fk_recording_erasure_holds_request_id_deletion_requests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recording_erasure_holds")),
        # A retried erasure re-inserts the same hold; this makes that idempotent in the
        # database rather than by the worker remembering to check.
        sa.UniqueConstraint(
            "tenant_id", "object_key", name=op.f("uq_recording_erasure_holds_tenant_id_object_key")
        ),
    )
    op.create_index(
        op.f("ix_recording_erasure_holds_tenant_id"),
        "recording_erasure_holds",
        ["tenant_id"],
        unique=False,
    )
    # The sweep's only query: this tenant's holds that are due and not yet done. Partial,
    # because a hold that has been honoured is history and must not cost the index that
    # serves the worklist.
    op.create_index(
        "ix_recording_erasure_holds_due",
        "recording_erasure_holds",
        ["tenant_id", "erase_after"],
        unique=False,
        postgresql_where=sa.text("erased_at IS NULL"),
    )
    op.execute("ALTER TABLE recording_erasure_holds ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE recording_erasure_holds FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)

    op.execute(
        "ALTER TABLE retention_policies ADD CONSTRAINT ck_retention_policies_ttl_positive "
        "CHECK (ttl_days > 0) NOT VALID"
    )
    op.execute(
        "ALTER TABLE retention_policies VALIDATE CONSTRAINT ck_retention_policies_ttl_positive"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_retention_policies_tenant_id_data_category "
        "ON retention_policies (tenant_id, data_category)"
    )
    op.execute(
        "ALTER TABLE retention_policies ADD CONSTRAINT "
        "uq_retention_policies_tenant_id_data_category UNIQUE USING INDEX "
        "uq_retention_policies_tenant_id_data_category"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "ALTER TABLE retention_policies DROP CONSTRAINT IF EXISTS "
        "uq_retention_policies_tenant_id_data_category"
    )
    op.execute(
        "ALTER TABLE retention_policies DROP CONSTRAINT IF EXISTS "
        "ck_retention_policies_ttl_positive"
    )
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON recording_erasure_holds")
    op.drop_index("ix_recording_erasure_holds_due", table_name="recording_erasure_holds")
    op.drop_index(
        op.f("ix_recording_erasure_holds_tenant_id"), table_name="recording_erasure_holds"
    )
    op.drop_table("recording_erasure_holds")
