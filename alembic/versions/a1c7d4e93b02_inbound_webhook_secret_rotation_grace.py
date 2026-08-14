"""inbound_webhooks: a rotated secret keeps the old one alive for a stated window

Revision ID: a1c7d4e93b02
Revises: d4a1e93b70c6
Create Date: 2026-08-14

WHY TWO COLUMNS RATHER THAN ONE UPDATE.

`inbound_webhooks.secret_ref` is the credential the SENDER holds — a form vendor's
custom header, a Meta app secret. Replacing it in one statement makes every submission
between our UPDATE and the client finishing the paste in Zapier/Wix/Meta answer 401,
and this is the ingest path: a rejected submission is a lost enquiry, which is the one
thing FLOWS §4 is built not to do. Every serious webhook platform solves it the same
way — an overlap in which both the retiring and the new signing secret verify (Stripe
publishes a rolled secret with an explicit expiry,
https://docs.stripe.com/webhooks#roll-endpoint-secrets; GitHub and Slack document the
same dual-secret cutover) — so this is the established pattern, not an invention.

`previous_secret_expires_at` is what keeps it from becoming a second permanent
credential: the grace is bounded, chosen per rotation, and enforced in code
(`ingest.service.accepted_secrets`), so "rotated" eventually means "the old one is
dead" without an operator remembering to come back. A rotation with zero grace is the
same statement said immediately, which is what a leak needs.

TENANCY: no new table, so no new policy. `inbound_webhooks` already carries `tenant_id`
with FORCEd RLS (05bba2f3c19c) under the policy d41f88a2c6e9 rewrote, and columns added
to a table inherit it — the row is the unit RLS protects, not the column.
`tests/lead_source_provisioning_test.py` proves the cross-tenant zero-rows answer on
the new routes rather than assuming inheritance.

REVERSIBLE, and the downgrade drops data on purpose: a deployment rolled back to the
one-secret world can only honour one secret, and leaving a column full of live
credentials that nothing reads is worse than dropping it. Anything mid-rotation is
still reachable — the CURRENT secret is untouched by both directions.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c7d4e93b02"
down_revision: str | None = "d4a1e93b70c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "inbound_webhooks",
        sa.Column("previous_secret_ref", sa.Text(), nullable=True),
    )
    op.add_column(
        "inbound_webhooks",
        sa.Column("previous_secret_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The two columns are one fact and have to move together: a previous secret with no
    # expiry never dies, and an expiry with no secret is a window onto nothing. Written
    # as a constraint rather than trusted to the one writer, because the day a second
    # writer appears this is the invariant `accepted_secrets` reads.
    op.create_check_constraint(
        op.f("ck_inbound_webhooks_previous_secret_paired"),
        "inbound_webhooks",
        "(previous_secret_ref IS NULL) = (previous_secret_expires_at IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_inbound_webhooks_previous_secret_paired"), "inbound_webhooks", type_="check"
    )
    op.drop_column("inbound_webhooks", "previous_secret_expires_at")
    op.drop_column("inbound_webhooks", "previous_secret_ref")
