"""auth_credentials + auth_sessions, deny-by-default under app.auth

Revision ID: e9a4c1d70b52
Revises: c4f18a6b90e2
Create Date: 2026-08-17

The schema half of D-165 (docs/AUTH-MIGRATION.md): the first-party replacement for the
authentication leg Clerk holds today. Nothing reads these tables yet — `apps/api/authn`
is the proof-of-concept slice and is mounted on no router — and that is why the migration
is safe to apply ahead of the cutover: it adds two tables and takes nothing away.

WHY THESE TWO TABLES HAVE ROW-LEVEL SECURITY WITHOUT HAVING A `tenant_id`
-------------------------------------------------------------------------
Hard rule 1 is about tenant isolation, and neither table is tenant-scoped: identity
crosses tenants (one person, several `memberships`), so a password or a session with a
`tenant_id` would be duplicated or wrong. `users` and `admin_users` sit outside tenant
isolation for the same reason.

What is NOT the same is the blast radius. `users` has no RLS at all, so any session in
the process can read it; the cost of that is a directory of email addresses. These two
hold password hashes and live session fingerprints, where one over-broad query in a
tenant-scoped code path is platform-wide account takeover — so the answer is not "no
policy", it is "a policy that denies everyone by default":

    USING / WITH CHECK (current_setting('app.auth', true) = 'on')

`app.auth` is set by `db/session.credential_session()` and by nothing else. A
`tenant_session`, an `admin_session`, an `invite_session` and a bare `untenanted_session`
all see zero rows, which is the property `tests/authn_rls_test.py` drives against real
rows — including the cross-tenant case that hard rule 1 asks for: tenant A's session
cannot see the credential or the session of tenant B's owner, because it cannot see
anybody's.

`current_setting(..., true)` and an equality against `'on'` rather than a cast: the
missing-GUC value on a pooled connection is `NULL` on first use and `''` after a
transaction that set it has ended, and both compare false here. There is no spelling of
"unset" that opens this table. FORCE is what makes the policy apply to the table OWNER
too, which matters because migrations run as `calevate` and a future admin-role query
must not quietly bypass it.

WHAT IS NOT HERE, AND WHY
-------------------------
* **No FK on `subject_id`.** It points at `users.id` or `admin_users.id` depending on
  `realm`, and PostgreSQL has no polymorphic FK. See `apps/api/authn/models.py` for the
  two alternatives and why each is worse.
* **No append-only trigger.** Sessions are revoked, superseded and slid forward; a
  credential is replaced on reset. Neither is a ledger, and putting one in
  `APPEND_ONLY_TABLES` would make the ordinary operations of the module impossible
  (hard rule 4 is for evidence, not for state).
* **No MFA secret, no recovery codes, no invitations table.** The design names them
  (AUTH-MIGRATION §2); this migration ships only what the proof-of-concept slice reads,
  because a column nobody reads is the defect `scripts/check_wiring.py` exists to catch.

REVERSIBLE, and the downgrade is a real drop rather than a rename: at the moment this
lands the tables are empty in every environment and nothing writes them, so there is
nothing for a two-step deprecation (hard rule 8) to protect. Once the cutover of
AUTH-MIGRATION §5 has begun, that stops being true — and by then dropping these tables
would mean dropping every password, which is a restore, not a downgrade.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e9a4c1d70b52"
# RE-PARENTED onto `f4a1d0b6e29c`, the head of this branch, rather than the
# `c4f18a6b90e2` this revision was authored against. The auth work was designed in a
# worktree cut before `e83b5d1a4c07` (outbox probes) and `f4a1d0b6e29c` (the two notices)
# existed, so its original parent is two revisions behind and would fork the chain — and
# `check_wiring` requires exactly one head, for the reason `alembic upgrade head` refuses
# to guess between two.
#
# Safe because the three are disjoint: this one CREATES new tables (credentials, sessions
# and their kin) and touches no existing one, while its two new ancestors add columns to
# `calls`, `outbox_messages` and `agents`. No read here depends on anything they write, so
# composing them in any order yields the same schema.
down_revision: str | None = "f4a1d0b6e29c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The one predicate both policies use. Spelled once so the two tables cannot drift.
AUTH_GUC = "current_setting('app.auth', true) = 'on'"

_TABLES = ("auth_credentials", "auth_sessions")


def upgrade() -> None:
    op.create_table(
        "auth_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("realm", sa.Text(), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("password_set_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        # Bare constraint names: `Base.metadata`'s naming convention (db/base.py) renders
        # `ck_%(table_name)s_%(constraint_name)s`, so spelling the prefix here produces
        # `ck_auth_credentials_ck_auth_credentials_...` and a permanent
        # `compare_metadata` diff against the model, which is exactly the drift
        # `scripts/check_metadata_columns.py` exists to keep out.
        sa.CheckConstraint("realm IN ('admin', 'client')", name="realm_enum"),
        sa.UniqueConstraint("realm", "subject_id", name="uq_auth_credentials_realm_subject_id"),
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("realm", sa.Text(), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False, unique=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_reason", sa.Text()),
        sa.Column("mfa_verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.CheckConstraint("realm IN ('admin', 'client')", name="realm_enum"),
        sa.CheckConstraint(
            "revoked_reason IS NULL OR revoked_reason IN "
            "('signed_out', 'subject_revoked', 'reuse_detected', 'administrative')",
            name="revoked_reason_enum",
        ),
        # A revocation with no reason is a row an investigator cannot use. The reverse is
        # permitted and meaningless, so it is not constrained.
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_reason IS NOT NULL",
            name="revocation_states_its_reason",
        ),
    )
    op.create_index("ix_auth_sessions_family_id", "auth_sessions", ["family_id"])
    op.create_index("ix_auth_sessions_realm_subject_id", "auth_sessions", ["realm", "subject_id"])

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY credential_store_only ON {table} "
            f"USING ({AUTH_GUC}) WITH CHECK ({AUTH_GUC})"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS credential_store_only ON {table}")
    op.drop_index("ix_auth_sessions_realm_subject_id", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_family_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("auth_credentials")
