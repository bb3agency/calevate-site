"""first_campaign_reviews — the hold R-11's last mitigation had nothing behind it

Revision ID: c4d9e18a72b6
Revises: b9e5d2c74a18
Create Date: 2026-08-12 12:00:00.000000

D-34 ships the self-serve motion WITH six R-11 mitigations, and BRD §245 and FLOWS §2
both end the list with "manual review of the first campaign for any self-serve account".
Five of the six held in code; this one was a sentence in three documents with no flag,
no queue and no blocker behind it. This migration gives it somewhere to live.

WHAT "FIRST" MEANS, AND WHY IT IS NOT A COLUMN ON `campaigns`
-------------------------------------------------------------
The obvious shape — `campaigns.review_required`, set on the first campaign row a tenant
creates — is defeated two ways in about a minute, and both are the ordinary behaviour of
a client who is in a hurry rather than an attack:

* **launch a second campaign.** The flag is on campaign #1; #2 carries no flag and
  dials. The account's first calls were never reviewed by anyone.
* **delete the flagged campaign.** The flag goes with the row, and the replacement is
  campaign #1 all over again — or is not, depending on whether "first" counted rows that
  no longer exist. Either way the answer is decided by a DELETE.

So "first" is not a row. **It is the state of an account that no human has cleared yet**,
and it is stored as what a human DID: one decision per tenant, here. The campaign the
operator actually looked at is recorded as evidence (`reviewed_campaign_id`), never as
the thing the hold hangs on — hence `ON DELETE SET NULL`: deleting the campaign loses the
pointer and changes nothing about whether the account is cleared.

The consequence, stated so nobody has to re-derive it: while the account is held, EVERY
campaign is refused, not only the first one. Once released, no campaign is refused again
on this rule. That is exactly the mitigation as written — the first campaign gets a
human's eyes, and the account is trusted afterwards — and it is the only reading of it
that cannot be skipped by launching two campaigns instead of one.

ABSENCE IS "NOT REVIEWED"; THERE IS NO `pending` ROW
-----------------------------------------------------
The status enum is exactly `approved` / `rejected` — the two things a human can decide.
A tenant with no row has not been reviewed, which is the state EVERY self-serve account
starts in and the state the gate refuses. A `pending` row would be a second
representation of that same fact, writable by a request path, capable of disagreeing
with the absence, and treated identically by every gate that reads it. (`kyc_records`
carries pre-decision states because a client SUBMITS documents there and the states are
different to-do items for different people. Nothing is submitted here: the client builds
a campaign, which is already a row.)

It also keeps the refusal path pure. A hold that had to INSERT a request row when a
launch is refused would be a write on a rejected request, inside a transaction the error
handler rolls back — a queue entry that exists only when the launch succeeded, which is
the one case it is not needed for.

BACKFILL: WHO IS GRANDFATHERED, AND WHY THAT IS NOT A HOLE
-----------------------------------------------------------
Self-serve tenants that have ALREADY launched a campaign get an `approved` row with
`decision_source = 'migration_backfill'`. Their first campaign is in the past; a control
introduced today cannot review it, and refusing their in-flight dialling would be an
outage inflicted by a paperwork state — the mistake `tm_registration_missing` already
cost this repo once. `self_serve_signup_enabled` defaults OFF, so in production this
backfill selects nothing; it exists for the dev and staging databases where it would
otherwise halt fixtures mid-run and teach everyone to work around the gate.

`decision_source` is what keeps that honest. An operator decision must name the operator
(`ck_first_campaign_reviews_operator_decision_names_its_operator`), so a NULL
`decided_by_admin_id` cannot be a human release with the name left off — it can only be
this migration, and it says so in the same row.

RLS
---
New tenant table, so hard rule 1 in full: `tenant_id`, ENABLE + FORCE, and the standard
DATA-MODEL §1 `tenant_isolation` policy created HERE, beside the table. The cross-tenant
zero-rows proof is `tests/first_campaign_review_test.py::
test_tenant_b_cannot_see_tenant_as_review`, which asserts it through the client route AND
on the raw RLS-scoped session, so an endpoint that filtered in Python would still fail.
The policy is created AFTER the backfill for the same reason the backfill is first: FORCE
applies to the table owner too, and a policy-first ordering would make the INSERT depend
on the migration role's superuser status rather than on the statement order.

LOCKING (hard rule 8)
---------------------
`CREATE TABLE` locks only itself. The three foreign keys point OUT, at `organizations`,
`campaigns` and `admin_users`; adding a validated FK takes SHARE ROW EXCLUSIVE on the
REFERENCED table, which blocks writes there for the length of the validation — on
`campaigns` that is a table a live dispatcher writes every tick. So each FK is added NOT
VALID (a catalogue write) and VALIDATEd separately (SHARE UPDATE EXCLUSIVE, which does
not block inserts). `lock_timeout` is set on every statement that takes a lock outside
this table, so a migration that cannot get its lock fails fast instead of queueing in
front of every writer behind it.

DOWNGRADE
---------
Drops the policy, the index, then the table, and is exercised (upgrade → downgrade →
upgrade) rather than assumed. It loses the recorded reviews, which is unavoidable —
this table is the only place they live — and it re-opens the hold for every self-serve
account, so a revert is a compliance decision, not a rollback detail.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d9e18a72b6"
down_revision: str | None = "b9e5d2c74a18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns ''
# when unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON first_campaign_reviews USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)

# The tiers the hold applies to — `compliance.service.SELF_SERVE_TIERS`, spelled out
# once here because a migration cannot import application code and must still select
# the same population the gate does.
_SELF_SERVE_TIERS = "('self_serve', 'trial')"

_GRANDFATHERED = (
    "Grandfathered by migration c4d9e18a72b6: this account launched a campaign before "
    "the first-campaign review existed, so its first campaign cannot be reviewed now."
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        "first_campaign_reviews",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        # Evidence, never the mechanism: WHICH campaign the operator read before
        # releasing the account. SET NULL on delete — losing the pointer must not
        # change whether the account is cleared.
        sa.Column("reviewed_campaign_id", sa.UUID(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=False),
        sa.Column("decision_source", sa.String(), server_default="operator", nullable=False),
        sa.Column("decided_by_admin_id", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
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
        # Two decisions a human can make. "Not reviewed" is the ABSENCE of a row — see
        # the module docstring for why there is deliberately no third value.
        sa.CheckConstraint(
            "status IN ('approved', 'rejected')",
            name=op.f("ck_first_campaign_reviews_status_enum"),
        ),
        sa.CheckConstraint(
            "decision_source IN ('operator', 'migration_backfill')",
            name=op.f("ck_first_campaign_reviews_decision_source_enum"),
        ),
        # WHO, as a constraint. An operator release that cannot name its operator is not
        # a review, and the only rows exempt are the ones that say in the same breath
        # that no operator made them.
        sa.CheckConstraint(
            "decision_source <> 'operator' OR decided_by_admin_id IS NOT NULL",
            name=op.f("ck_first_campaign_reviews_operator_decision_names_its_operator"),
        ),
        # WHAT was reviewed. A release nobody can account for later is the audit finding
        # this table exists to avoid, and an empty string is not an account of anything.
        sa.CheckConstraint(
            "length(btrim(decision_note)) >= 3",
            name=op.f("ck_first_campaign_reviews_decision_says_what_was_reviewed"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_first_campaign_reviews")),
        # One decision per tenant: this is the account's CURRENT state, and a reversal
        # updates it. The history that must be immutable is `audit_log` (hard rule 4),
        # where every decision writes a row.
        sa.UniqueConstraint("tenant_id", name=op.f("uq_first_campaign_reviews_tenant_id")),
    )
    op.create_index(
        op.f("ix_first_campaign_reviews_tenant_id"),
        "first_campaign_reviews",
        ["tenant_id"],
        unique=False,
    )

    # NOT VALID first, VALIDATE second — see the LOCKING note.
    op.execute(
        "ALTER TABLE first_campaign_reviews ADD CONSTRAINT "
        "fk_first_campaign_reviews_tenant_id_organizations FOREIGN KEY (tenant_id) "
        "REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID"
    )
    op.execute(
        "ALTER TABLE first_campaign_reviews ADD CONSTRAINT "
        "fk_first_campaign_reviews_reviewed_campaign_id_campaigns "
        "FOREIGN KEY (reviewed_campaign_id) REFERENCES campaigns (id) ON DELETE SET NULL NOT VALID"
    )
    op.execute(
        "ALTER TABLE first_campaign_reviews ADD CONSTRAINT "
        "fk_first_campaign_reviews_decided_by_admin_users FOREIGN KEY (decided_by_admin_id) "
        "REFERENCES admin_users (id) ON DELETE RESTRICT NOT VALID"
    )
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "ALTER TABLE first_campaign_reviews VALIDATE CONSTRAINT "
        "fk_first_campaign_reviews_tenant_id_organizations"
    )
    op.execute(
        "ALTER TABLE first_campaign_reviews VALIDATE CONSTRAINT "
        "fk_first_campaign_reviews_reviewed_campaign_id_campaigns"
    )
    op.execute(
        "ALTER TABLE first_campaign_reviews VALIDATE CONSTRAINT "
        "fk_first_campaign_reviews_decided_by_admin_users"
    )

    # Grandfather the accounts whose first campaign already happened — BEFORE the policy
    # exists, so the INSERT does not depend on the migration role bypassing RLS.
    op.execute(
        sa.text(
            "INSERT INTO first_campaign_reviews (id, tenant_id, status, decision_note, "
            "  decision_source, decided_by_admin_id, decided_at, created_at, updated_at) "
            "SELECT gen_random_uuid(), o.id, 'approved', :note, 'migration_backfill', NULL, "
            "  now(), now(), now() "
            "FROM organizations o "
            f"WHERE o.plan_tier IN {_SELF_SERVE_TIERS} AND EXISTS ("
            "  SELECT 1 FROM campaigns c WHERE c.tenant_id = o.id AND c.launched_at IS NOT NULL"
            ") ON CONFLICT (tenant_id) DO NOTHING"
        ).bindparams(note=_GRANDFATHERED)
    )

    # Hard rule 1, in the same migration as the table it protects.
    op.execute("ALTER TABLE first_campaign_reviews ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE first_campaign_reviews FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON first_campaign_reviews")
    op.drop_index(
        op.f("ix_first_campaign_reviews_tenant_id"), table_name="first_campaign_reviews"
    )
    op.drop_table("first_campaign_reviews")
