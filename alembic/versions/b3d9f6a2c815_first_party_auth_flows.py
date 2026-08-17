"""Email tokens, OTP challenges — and the identity columns first-party auth needs

Revision ID: b3d9f6a2c815
Revises: e9a4c1d70b52
Create Date: 2026-08-17

The rest of D-165's schema (docs/AUTH-MIGRATION.md §2.2). `e9a4c1d70b52` shipped the two
tables the proof-of-concept slice read; this one ships the two the FLOWS read, plus the
three identity columns the flows cannot work without.

ONE MIGRATION FOR ALL OF IT (hard rule 8's "reviewed" half). Two tables and three column
changes could have been five revisions; they are one because they are one capability and
because a partial application of them is a state no code path can serve — an
`auth_email_tokens` table with no `users.email_verified_at` to set is a password reset
that cannot finish.

NO `auth_mfa_secrets` AND NO `auth_recovery_codes`, and their absence is a DECISION rather
than a phase. AUTH-MIGRATION §2.2 originally named both, on a design where the second factor
was TOTP. The founder's decision (D-166) is that the second factor IS the emailed OTP
challenge — `auth_otp_challenges` with purpose `login_challenge` — so an authenticator-app
secret and a recovery-code sheet are not "later", they are not part of this design. Shipping
the tables anyway would be a table nothing writes and a column nothing reads, which is the
half-wired defect `scripts/check_wiring.py` exists to catch. If TOTP is ever wanted, it is a
migration written then, against a design made then.

WHY EVERY NEW TABLE REPEATS THE `app.auth` POLICY
--------------------------------------------------
Same reasoning as `e9a4c1d70b52`, and it is worth restating rather than cross-referencing
because these four hold the material that reset the password store: a TOTP seed that
recomputes valid second factors forever, recovery codes that bypass the second factor
entirely, and reset tokens that mint new passwords. Hard rule 1 is about TENANT isolation
and none of these are tenant-scoped — identity crosses tenants — so what replaces it is
the stricter thing: DENY BY DEFAULT. `USING`/`WITH CHECK (current_setting('app.auth',
true) = 'on')`, a GUC that only `db/session.credential_session()` sets, FORCEd so the
table owner is bound by it too. Every other session in the process — tenant, admin,
invite, ingest, bare — sees zero rows, and `tests/authn_flow_rls_test.py` drives all of
them against rows that are definitely there.

THE THREE IDENTITY COLUMNS, AND WHY TWO OF THEM RELAX A CONSTRAINT
-------------------------------------------------------------------
* `users.email_verified_at` — the column `accept_invitation`'s recipient binding starts
  trusting instead of "Clerk said so" (AUTH-MIGRATION C-14/C-12). New, nullable, read by
  `authn/subjects.py` and by the invite path.

* `admin_users.email` — the admin realm has NO email column today, because a Clerk
  operator is identified by `clerk_user_id` and the address lives at the vendor. A
  first-party operator signs in with an address, so the address has to be ours. Nullable
  (existing Clerk-era rows have none) and UNIQUE on the lowered value, because "which
  operator is this" must have exactly one answer.

* `users.clerk_user_id` and `admin_users.clerk_user_id` DROP THEIR NOT NULL. This is the
  first step of hard rule 8's two-step, done in the direction the rule asks for: the
  column keeps existing and keeps being written by every Clerk path, and it simply stops
  being MANDATORY, because a user created by redeeming a first-party invitation has no
  Clerk account to name. Nothing that reads it changes. The DROP is a later release,
  after AUTH-MIGRATION §5 step 6, and this migration deliberately does not do it.
  The UNIQUE constraint survives untouched: Postgres treats NULLs as distinct, so many
  first-party rows coexist under it without colliding.

WHAT IS DELIBERATELY NOT HERE
------------------------------
* **No unique index on `users.email`.** It is the schema this design wants and it is not
  safe to add in this revision: `users` predates the constraint, nothing has ever enforced
  it, and a migration that fails on real data at 3am is worse than an application-level
  refusal. `subjects.resolve_by_email` therefore refuses an AMBIGUOUS address loudly —
  same generic answer to the caller, a named `WARNING` for the operator — and
  `tests/authn_enumeration_test.py` pins that behaviour. Closing it properly is a data
  cleanup plus a `CREATE UNIQUE INDEX CONCURRENTLY`, and it is named in AUTH-MIGRATION §2.2
  rather than left to be rediscovered.
* **No `users.password_migrated_at`.** AUTH-MIGRATION §2.2 names it as the cutover's
  progress column, and the cutover tooling that would write and read it is not built.
  A column nobody reads is the defect `scripts/check_wiring.py` exists to catch, so it
  lands with the tooling or not at all.
* **No append-only trigger.** Neither table is a ledger: a challenge counts its attempts
  up and a token is burned. Hard rule 4 is for evidence, and the evidence for all of this
  is `audit_log`, which already has the trigger.

REVERSIBLE. `downgrade` drops the two tables and the added column, and restores both
NOT NULLs. The restore is the one step that can legitimately fail — it will, if a
first-party user or operator has been created without a Clerk id, which is exactly the
state the constraint says must not exist. That failure is correct and is not a defect in
this migration: past that point the downgrade is a restore, not a rollback, for the same
reason `e9a4c1d70b52`'s docstring gives about dropping the password store.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b3d9f6a2c815"
down_revision: str | None = "e9a4c1d70b52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Spelled once, exactly as `e9a4c1d70b52` spells it, so the six tables cannot drift.
AUTH_GUC = "current_setting('app.auth', true) = 'on'"

_TABLES = ("auth_email_tokens", "auth_otp_challenges")

_EMAIL_TOKEN_PURPOSES = (
    "('email_verify', 'password_reset', 'invite_password', 'admin_bootstrap')"
)
_OTP_PURPOSES = "('login_challenge', 'email_verify')"


def upgrade() -> None:
    op.create_table(
        "auth_email_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("realm", sa.Text(), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True)),
        sa.Column("invitation_id", postgresql.UUID(as_uuid=True)),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"purpose IN {_EMAIL_TOKEN_PURPOSES}", name="purpose_enum"),
        sa.CheckConstraint("realm IN ('admin', 'client')", name="realm_enum"),
        sa.CheckConstraint(
            "(subject_id IS NULL) <> (invitation_id IS NULL)",
            name="names_exactly_one_recipient",
        ),
        sa.UniqueConstraint("token_hash", name="uq_auth_email_tokens_token_hash"),
    )
    op.create_index(
        "ix_auth_email_tokens_realm_subject_id",
        "auth_email_tokens",
        ["realm", "subject_id"],
    )

    op.create_table(
        "auth_otp_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("realm", sa.Text(), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"purpose IN {_OTP_PURPOSES}", name="purpose_enum"),
        sa.CheckConstraint("realm IN ('admin', 'client')", name="realm_enum"),
        sa.CheckConstraint("attempts >= 0", name="attempts_non_negative"),
    )
    op.create_index(
        "ix_auth_otp_challenges_realm_subject_purpose",
        "auth_otp_challenges",
        ["realm", "subject_id", "purpose"],
    )

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY credential_store_only ON {table} "
            f"USING ({AUTH_GUC}) WITH CHECK ({AUTH_GUC})"
        )

    # --- the identity columns ------------------------------------------------
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    op.add_column("admin_users", sa.Column("email", sa.Text()))
    # Lowered, because addresses are compared casefolded everywhere in this repo
    # (`accept_invitation` already does) and a unique index on the raw value would let
    # `Ops@calevate.tech` and `ops@calevate.tech` both exist and both try to sign in.
    op.execute("CREATE UNIQUE INDEX uq_admin_users_email_lower ON admin_users (lower(email))")

    op.alter_column("users", "clerk_user_id", existing_type=sa.Text(), nullable=True)
    op.alter_column("admin_users", "clerk_user_id", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    # NOT NULL first: if this fails, a first-party account exists and the drops below
    # would have destroyed its credentials before the failure surfaced.
    op.alter_column("admin_users", "clerk_user_id", existing_type=sa.Text(), nullable=False)
    op.alter_column("users", "clerk_user_id", existing_type=sa.Text(), nullable=False)

    op.execute("DROP INDEX IF EXISTS uq_admin_users_email_lower")
    op.drop_column("admin_users", "email")
    op.drop_column("users", "email_verified_at")

    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS credential_store_only ON {table}")
    op.drop_index("ix_auth_otp_challenges_realm_subject_purpose", table_name="auth_otp_challenges")
    op.drop_table("auth_otp_challenges")
    op.drop_index("ix_auth_email_tokens_realm_subject_id", table_name="auth_email_tokens")
    op.drop_table("auth_email_tokens")
