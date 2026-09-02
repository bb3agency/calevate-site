"""tenant erasure requests, and the invariant organizations.deleted_at always had

Revision ID: f3a71c9e26b4
Revises: c1f6a94d2b07
Create Date: 2026-08-15 00:00:00.000000

Three changes, one subject: giving `organizations.deleted_at` a writer, and giving the
nine readers that already depend on it a rule the database holds rather than a rule each
of them has to remember.

--------------------------------------------------------------------------------
1. `tenant_erasure_requests` — the request, its reason, and its certificate
--------------------------------------------------------------------------------

FLOWS §9 ends offboarding at "org status churned" and D-120 recorded what that leaves
open: `organizations.deleted_at` is read by `core/auth.py` (membership resolution AND
the impersonation slug lookup), `compliance.service.account_stopped_blocker`,
`admin.service.tenant_exists`, `admin.service.assert_account_open`, the admin directory,
the health board, `quality/service.py`, `quality/sampling_routes.py` and
`workers/qa_sampling.py` — and written by NOTHING. A column of load-bearing behaviour
with no way to reach it.

This table is the request that reaches it. Deliberately NOT a `deletion_requests` row:
that table is one data principal's DPDP §12 right, keyed by `phone_e164`, surfaced in
the CLIENT realm, and its `open_request_names_its_subject` CHECK forbids an open row
with no number. A tenant erasure has a different subject (the whole account), a
different requester (us, on the client's instruction, under DPDP §8) and a different
audience for its certificate. `apps/api/compliance/tenant_erasure.py` argues it at
length.

RLS: `tenant_id` with the FORCEd `tenant_isolation` policy, verbatim from DATA-MODEL §1,
and a cross-tenant zero-rows test ships with it (hard rule 1).

NOT append-only, and it must never join `db/registry.APPEND_ONLY_TABLES`: `completed_at`
and `proof` are stamped when the worker finishes, exactly as `deletion_requests` is. The
append-only artifact of an erasure is the proof document itself, which is written once
and never rewritten.

The partial unique index is the same shape `uq_deletion_requests_open_subject` uses and
exists for the same reason: at most one QUEUED, UNEXECUTED erasure per tenant, so a
double-click cannot produce two certificates for one act. It is partial rather than total
because a completed erasure is history — though in practice a second one can never be
filed either, since `deleted_at` is set and never cleared.

--------------------------------------------------------------------------------
2. `ck_organizations_deleted_implies_churned`
--------------------------------------------------------------------------------

    deleted_at IS NOT NULL  =>  status = 'churned'

The readers listed above do not agree with each other about which column to look at, and
they do not need to — as long as this holds. Some filter `deleted_at IS NULL` alone (the
directory, `tenant_exists`, the QA sampler, the impersonation lookup); some filter
`status <> 'churned'` too (`core/auth.py`'s membership query, the health board); the dial
gate and the invitation gate compute the union. Without the implication a tenant could be
"erased" while still `active`, which would put it in `core/auth.py`'s refusal set and in
the health board's LIVE set at the same time — two halves of the console disagreeing
about whether a business exists.

Enforced here rather than only in the writer because a writer is a property of this
week's code. `NOT VALID` then `VALIDATE`, the non-blocking pattern this repo uses.
Verified clean before adding: nothing has ever written `deleted_at`, so the predicate is
vacuously true on every existing row.

--------------------------------------------------------------------------------
3. `recording_erasure_holds` gets a second owner, exclusively
--------------------------------------------------------------------------------

A hold row records "this audio is inside the TRAI floor, destroy it on this date", and
carries WHICH erasure incurred the obligation so a destruction can be tied back to the
certificate that promised it. Until now the only kind of erasure was a subject erasure,
so `request_id` pointed at `deletion_requests` and was NOT NULL.

A tenant erasure incurs exactly the same obligation and must record it the same way —
`execute_deletion_request` proved what happens otherwise: clearing `calls.recording_url`
destroys the only handle anything has on the object, and the sweep selects
`WHERE recording_url IS NOT NULL`, so the audio becomes permanently undeletable. The
alternative to this column was for a tenant erasure to skip the pointer clear, or to
mint a fake `deletion_requests` row to hang the FK on; the first leaves personal data
reachable, the second puts a §12 certificate in a client's register for a request nobody
made.

So `request_id` becomes nullable, `tenant_erasure_id` is added, and
`num_nonnulls(request_id, tenant_erasure_id) = 1` makes "exactly one owner" a database
fact — the standard exclusive-arc shape. A hold with neither owner would be an
obligation nothing can explain; one with both would be two certificates claiming the
same destruction.

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------

Reverses all three, and is HONEST about the one thing it destroys: holds owned by a
tenant erasure are DELETEd before `request_id` goes back to NOT NULL, because there is
no `deletion_requests` row they could be re-pointed at. Those rows are the only record of
scheduled destructions for erased tenants, so a downgrade returns that audio to the state
where nothing can name it — the same cost migration 9c1d3e7a05f4 documented for dropping
the table outright. Nothing here creates a function or a trigger, so there is no
`DuplicateFunction` on re-upgrade; exercised up → down → up on a pristine database rather
than assumed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a71c9e26b4"
down_revision: str | None = "c1f6a94d2b07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns ''
# when unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON tenant_erasure_requests USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "tenant_erasure_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        # Why this client's data was destroyed, verbatim from the operator. Required at
        # the API boundary for the reason the lifecycle switch requires one on a suspend:
        # an irreversible act with no stated reason is the ticket nobody can close.
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # NULL until the worker finishes. The idempotency guard reads it, so it is also
        # what makes an arq retry redo the whole erasure rather than issue a second,
        # weaker certificate.
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        # The certificate: counts, timestamps and sentences. No phone number, no
        # transcript text, no extraction payload — by construction, not by filtering.
        sa.Column("proof", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_tenant_erasure_requests_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_erasure_requests")),
    )
    op.create_index(
        op.f("ix_tenant_erasure_requests_tenant_id"),
        "tenant_erasure_requests",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "uq_tenant_erasure_requests_open",
        "tenant_erasure_requests",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("completed_at IS NULL"),
    )
    op.execute("ALTER TABLE tenant_erasure_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_erasure_requests FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)

    op.execute(
        "ALTER TABLE organizations ADD CONSTRAINT ck_organizations_deleted_implies_churned "
        "CHECK (deleted_at IS NULL OR status = 'churned') NOT VALID"
    )
    op.execute(
        "ALTER TABLE organizations VALIDATE CONSTRAINT ck_organizations_deleted_implies_churned"
    )

    op.alter_column("recording_erasure_holds", "request_id", nullable=True)
    op.add_column(
        "recording_erasure_holds", sa.Column("tenant_erasure_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_recording_erasure_holds_tenant_erasure_id_tenant_erasure_requests"),
        "recording_erasure_holds",
        "tenant_erasure_requests",
        ["tenant_erasure_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        "ALTER TABLE recording_erasure_holds ADD CONSTRAINT ck_recording_hold_one_owner "
        "CHECK (num_nonnulls(request_id, tenant_erasure_id) = 1) NOT VALID"
    )
    op.execute(
        "ALTER TABLE recording_erasure_holds VALIDATE CONSTRAINT ck_recording_hold_one_owner"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.execute(
        "ALTER TABLE recording_erasure_holds DROP CONSTRAINT IF EXISTS ck_recording_hold_one_owner"
    )
    # See the DOWNGRADE note: these holds have no `deletion_requests` row to belong to,
    # so restoring NOT NULL means losing them. Stated, not silent.
    # The bracket (`d3b71c9a5e08`): this table is FORCE ROW LEVEL SECURITY, which
    # subjects the OWNER to `tenant_isolation` too, and that policy is fail-closed on an
    # unset `app.tenant_id`. Unbracketed, the statement below matches ZERO rows and
    # reports success. Added by `e1a4d70c9b52`'s round, which hit exactly this in
    # production; `tests/migration_rls_bracket_test.py` now fails the build on a new one.
    op.execute("ALTER TABLE recording_erasure_holds NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM recording_erasure_holds WHERE request_id IS NULL")
    op.execute("ALTER TABLE recording_erasure_holds FORCE ROW LEVEL SECURITY")
    op.drop_constraint(
        op.f("fk_recording_erasure_holds_tenant_erasure_id_tenant_erasure_requests"),
        "recording_erasure_holds",
        type_="foreignkey",
    )
    op.drop_column("recording_erasure_holds", "tenant_erasure_id")
    op.alter_column("recording_erasure_holds", "request_id", nullable=False)

    op.execute(
        "ALTER TABLE organizations DROP CONSTRAINT IF EXISTS "
        "ck_organizations_deleted_implies_churned"
    )

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenant_erasure_requests")
    op.drop_index("uq_tenant_erasure_requests_open", table_name="tenant_erasure_requests")
    op.drop_index(
        op.f("ix_tenant_erasure_requests_tenant_id"), table_name="tenant_erasure_requests"
    )
    op.drop_table("tenant_erasure_requests")
