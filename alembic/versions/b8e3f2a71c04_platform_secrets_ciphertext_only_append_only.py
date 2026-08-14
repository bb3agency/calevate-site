"""platform_secrets — ciphertext only, append-only, with the ONE bounded exception

Revision ID: b8e3f2a71c04
Revises: a4d17c02fb98
Create Date: 2026-08-14 10:20:00.000000

PLATFORM-CONFIG §5, phase 4 of §13's build order.

**No plaintext column exists except `last_four`**, and that is the point rather than a
detail: a table that CAN hold a credential in the clear is one bad migration away from
holding one. The value arrives already sealed by `core/envelope.seal`; this schema has
nowhere to put an unsealed one.

**Not tenant-scoped, no `tenant_id`**, same as `platform_settings` — registered in
`db/registry.RLS_EXEMPT_TENANT_COLUMNS` with "platform-scoped, admin realm only" as the
written reason. Per-tenant credentials are §11's `tenant_secrets`, a different table with
`tenant_id` and FORCEd RLS, reusing this module's envelope.

## Append-only, and the one thing an UPDATE may touch

`platform_secrets` joins the hard-rule-4 family (`usage_events`, `consent_ledger`,
`audit_log`, `credit_ledger`, `one_time_charges`, `whatsapp_alert_optin_ledger`). A new
value is a NEW VERSION; the old row is retired, never edited and never deleted. That is
what makes "which key was live when this call was billed?" answerable a year later.

But a KEK rotation has to RE-WRAP every DEK, including historical ones — that is the
whole reason the envelope exists (§3 rule 3: re-wrapping is cheap because the secrets
themselves are not re-encrypted). If historical rows kept their old wrapping, the retired
KEK could never be removed from the environment without losing the ability to read
history, and "the rotation completed" would never be true.

So the trigger is not the blanket `calevate_forbid_mutation` the other six ledgers use.
It permits an UPDATE **only** when every column except `dek_wrapped`, `dek_nonce`,
`kek_version` and `retired_at` is byte-for-byte unchanged, and it RAISEs on everything
else including every DELETE. The ciphertext — the evidence — is immutable; the wrapping —
operational state — is not.

REJECTED ALTERNATIVE, recorded because it is the obvious one and it is defensible:
splitting the wrapping into a second table (`platform_secret_keys`) so that
`platform_secrets` could carry the blanket trigger with no exception at all. It would
have kept hard rule 4 absolutely intact and made the rewrap a plain UPDATE on a table
nobody calls a ledger. It was rejected because it puts a join on every credential read
and splits one fact across two rows, and because the exception here is *narrower* than
the alternative's blast radius: this trigger enumerates the four mutable columns
positively and a fifth cannot be added without editing this migration and its test
(`tests/platform_secrets_test.py` proves a ciphertext edit and a delete both raise).

## Why `kek_version` holds a fingerprint

It is `core/envelope.Envelope.kek_id` — SHA-256 of the key material under a
purpose-separated prefix, truncated to 31 bits (D-96). NOT an operator-maintained
counter: a counter that nobody bumps during a rotation stamps new rows with the previous
generation, the rewrap job then reads those rows as already current and skips them, and
the NEXT rotation makes them permanently unreadable. That is silent, unrecoverable data
loss gated on human memory. A fingerprint cannot disagree with the key that produced it.

It is a REPORTING field. `secret_service.rewrap_all` iterates every row and never filters
on it — see that function's docstring for why letting it decide what to process would
reintroduce the counter's failure mode wearing a hash.

## The sentinel

`platform_secrets` gets the SAME `platform_config_bump_version` trigger as
`platform_settings`, so a rotation propagates to every process on the same ≤8s poll as a
config change. §6 proposed a separate shorter TTL for secrets; one sentinel is strictly
better — it is faster than any TTL, it is one mechanism rather than two, and a rotation
is exactly the change that must not wait.

**Locking.** One `CREATE TABLE` and two triggers on it. Nothing existing is touched.

**Downgrade** drops the table, which destroys every stored credential. It is recoverable
only from the environment: an operator reverting this must put the keys back in `.env`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8e3f2a71c04"
down_revision: str | None = "a4d17c02fb98"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The columns a rewrap may change. Spelled once, here, and read by the trigger below.
# Adding to this list is an edit to a migration and to the test that proves the
# boundary — which is the cost it should have.
_REWRAPPABLE = ("dek_wrapped", "dek_nonce", "kek_version", "retired_at")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "platform_secrets",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        # AES-256-GCM(value, DEK, nonce). The ONLY form the value ever takes on disk.
        sa.Column("ciphertext", postgresql.BYTEA(), nullable=False),
        sa.Column("nonce", postgresql.BYTEA(), nullable=False),
        # AES-256-GCM(DEK, KEK). The KEK itself is an environment variable and NEVER
        # enters this database — a store holding both the lock and the key is theatre.
        sa.Column("dek_wrapped", postgresql.BYTEA(), nullable=False),
        sa.Column("dek_nonce", postgresql.BYTEA(), nullable=False),
        sa.Column("kek_version", sa.Integer(), nullable=False),
        # The only plaintext fragment that touches disk. It exists so the console can
        # show WHICH key is installed without being able to show the key; anything under
        # eight characters is masked entirely (`core/envelope.last_four`).
        sa.Column("last_four", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["admin_users.id"],
            name=op.f("fk_platform_secrets_created_by_admin_users"),
        ),
        sa.PrimaryKeyConstraint("key", "version", name=op.f("pk_platform_secrets")),
    )
    # The current version of one key is `MAX(version)`, read on every resolution.
    op.create_index(
        "ix_platform_secrets_key_version",
        "platform_secrets",
        ["key", sa.text("version DESC")],
    )

    # Every column that must NEVER change on an UPDATE — the complement of
    # `_REWRAPPABLE`. A column added to this table later would NOT be in this list and
    # would therefore be silently mutable, which is why `tests/platform_secrets_test.py`
    # derives the expected set from the LIVE schema rather than from this literal: adding
    # a column without deciding which side it falls on fails that test.
    immutable = (
        "key",
        "version",
        "ciphertext",
        "nonce",
        "last_four",
        "created_at",
        "created_by",
    )
    guard = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in immutable)
    op.execute(
        f"""
        CREATE FUNCTION platform_secrets_forbid_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION
                    'platform_secrets is append-only (hard rule 4): a superseded key is '
                    'retired, never deleted — the record of which key was live when a '
                    'call was billed has to survive'
                    USING ERRCODE = 'raise_exception';
            END IF;
            IF {guard} THEN
                RAISE EXCEPTION
                    'platform_secrets is append-only (hard rule 4): only the WRAPPING '
                    '(dek_wrapped, dek_nonce, kek_version) and retired_at may change, '
                    'and only from a KEK rewrap. A new VALUE is a new version.'
                    USING ERRCODE = 'raise_exception';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER platform_secrets_append_only "
        "BEFORE UPDATE OR DELETE ON platform_secrets "
        "FOR EACH ROW EXECUTE FUNCTION platform_secrets_forbid_mutation()"
    )

    # The SAME sentinel the settings table bumps, so a rotation propagates on the same
    # poll as a config change rather than waiting for a second TTL of its own.
    op.execute(
        """
        CREATE TRIGGER platform_secrets_bump_config_version
        AFTER INSERT OR UPDATE OR DELETE ON platform_secrets
        FOR EACH STATEMENT EXECUTE FUNCTION platform_config_bump_version();
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP TRIGGER IF EXISTS platform_secrets_bump_config_version ON platform_secrets")
    op.execute("DROP TRIGGER IF EXISTS platform_secrets_append_only ON platform_secrets")
    op.execute("DROP FUNCTION IF EXISTS platform_secrets_forbid_mutation()")
    op.drop_index("ix_platform_secrets_key_version", table_name="platform_secrets")
    op.drop_table("platform_secrets")
