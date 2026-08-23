"""admin_users.deactivated_at + a partial unique address index

Revision ID: f2c74b81a9d3
Revises: e4a91c6b02d7
Create Date: 2026-08-22

THE TWO-TIER ADMIN REALM NEEDED A WAY TO REMOVE AN OPERATOR, AND THERE WAS NOT ONE.

`admin_users` is the allowlist the whole admin realm resolves against, and the stated
removal mechanism was `DELETE FROM admin_users` — `authn/subjects.py` argued that row
presence IS the liveness rule and that a `deactivated_at` column would be "a second way
to express the same fact". The premise does not survive contact with the schema. Eight
tables reference this one `ON DELETE RESTRICT`:

    first_campaign_reviews.decided_by_admin_id      qa_call_samples.reviewed_by_admin_id
    kyc_records.verified_by_admin_id                tenant_feature_flags.set_by_admin_id
    preference_scrub_runs.recorded_by_admin_id      platform_settings.updated_by
    whatsapp_alert_optin_ledger.recorded_by_admin_id  platform_secrets.created_by

So the DELETE succeeds only for an operator who has never approved a first campaign,
verified a KYC record, scrubbed a preference list, reviewed a call, flipped a tenant
flag, changed a platform setting or installed a vendor credential — i.e. only for
operators nobody has a reason to remove. For everyone else it raises 23503 and the
product has no revocation at all. Those references are also the reason the row MUST
survive: each one answers "who decided this", and an erased decider turns a compliance
record into an anonymous one.

`deactivated_at` is therefore the removal mechanism, and it is not a second way of
saying the same thing — it is the only way that works on the rows that matter. The
uniformity `subjects.py` was protecting is untouched, because that uniformity was always
a property of the RETURN TYPE: `load_subject` answers `None` for absent, hard-deleted and
deactivated alike, and no caller can tell which. It is also the shape `users` has had
since 769a9152cb06, so the two realms now read the same way.

WHY THE ADDRESS INDEX BECOMES PARTIAL.
`uq_admin_users_email_lower` (b3d9f6a2c815) is unconditional, so once an operator is
revoked their address is permanently spent: re-hiring the same person, or correcting a
revocation made in error, would collide with a row that can never sign in again. The
predicate `WHERE deactivated_at IS NULL` makes the constraint say what it means — ONE
LIVE OPERATOR ACCOUNT PER ADDRESS — and re-adding somebody mints a NEW row with a new
id, leaving the old one intact for the eight foreign keys above. This is exactly the
shape `c7a1e93d40b8` chose for `users.email`, and its docstring named `admin_users` as
"the one departure"; the departure is now closed rather than argued.

REVERSIBLE (hard rule 8). The downgrade restores the unconditional index, which can fail
if two rows share an address and one of them is deactivated — that is correct behaviour
for a downgrade that is re-imposing a narrower constraint, and it fails loudly on the
index build rather than silently dropping a row.

NO BACKFILL AND NO NOT NULL: every existing row is live, which is exactly what a NULL
`deactivated_at` says.

NO DATABASE-LEVEL "AT LEAST ONE SUPERADMIN" TRIGGER, considered and rejected. The
invariant is real and is enforced in `admin/operators.py` (a superadmin may not demote or
revoke the last live superadmin, including themselves). A statement trigger would be
tempting defence in depth and would be wrong here for two reasons: it would refuse the
one honest escape hatch `authn/bootstrap.py` documents — delete every operator row and
re-run the bootstrap — and it would fire against the suite's own fixtures, which insert
lone `operator` rows into whatever state the shared database happens to be in, turning a
security invariant into a source of order-dependent flakes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2c74b81a9d3"
down_revision: str | None = "e4a91c6b02d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The name is unchanged across the swap, deliberately: it is the constraint's identity,
#: the string `authn/bootstrap` and `admin/operators` catch a 23505 against, and a rename
#: would leave a stale `IF EXISTS` drop in a future migration matching nothing.
INDEX_NAME = "uq_admin_users_email_lower"


def upgrade() -> None:
    op.add_column(
        "admin_users", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
    op.execute(
        f"CREATE UNIQUE INDEX {INDEX_NAME} ON admin_users (lower(email)) "
        "WHERE deactivated_at IS NULL"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
    op.execute(f"CREATE UNIQUE INDEX {INDEX_NAME} ON admin_users (lower(email))")
    op.drop_column("admin_users", "deactivated_at")
