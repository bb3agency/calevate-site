"""a_removed_credential_is_a_version — removing a platform credential appends a tombstone

Revision ID: c2b7e5a94d18
Revises: a6d2f9c41e85
Create Date: 2026-10-10 12:00:00.000000

An operator could install and rotate a credential in the ops console but never remove one:
the only way to stop a key was to overwrite it with junk, which still reads as "installed",
so every leg keyed on it stays offered and is called with a value the vendor refuses.

`platform_secrets` is append-only (hard rule 4), so a removal cannot be a DELETE or an
UPDATE. It is a NEW VERSION with `removed = true`: the newest version of a key decides
whether it is in force, and a tombstone decides "not set". The history the table exists to
keep — which key was live when a call was billed — survives a removal exactly as it survives
a rotation.

The tombstone still carries a sealed envelope (of the empty string), rather than NULL
envelope columns, so every row stays something `secret_service.rewrap_all` can re-wrap with
no tombstone branch, and the NOT NULL columns keep their meaning. `last_four` is empty on a
tombstone, and a CHECK holds that.

`removed` joins the columns the immutability trigger refuses to change: a rewrap may move a
row's wrapping, never whether it is a removal. The function is replaced in place; the
trigger, its `ENABLE ALWAYS` state (a2e9f31c605d) and the config-version bump are untouched.

**Locking.** `ADD COLUMN ... DEFAULT false NOT NULL` is a catalogue-only change on Postgres
11+, and the CHECK is validated against a table of tens of rows.

**Downgrade** refuses while any tombstone exists: without the column a tombstone would read
as an installed credential whose value is the empty string, which would put a removed key
back into force.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import probe_skipped_offline

revision: str = "c2b7e5a94d18"
down_revision: str | None = "a6d2f9c41e85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE_BEFORE = (
    "key",
    "version",
    "ciphertext",
    "nonce",
    "last_four",
    "created_at",
    "created_by",
)
_IMMUTABLE_AFTER = (*_IMMUTABLE_BEFORE, "removed")


def _forbid_mutation(immutable: Sequence[str]) -> str:
    guard = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in immutable)
    return f"""
        CREATE OR REPLACE FUNCTION platform_secrets_forbid_mutation() RETURNS trigger AS $$
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


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "platform_secrets",
        sa.Column("removed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_check_constraint(
        "removed_has_no_fragment",
        "platform_secrets",
        "NOT removed OR last_four = ''",
    )
    op.execute(_forbid_mutation(_IMMUTABLE_AFTER))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    if not probe_skipped_offline(
        "offline `--sql`: the pre-flight that refuses to drop platform_secrets.removed while\n"
        "a removal version is recorded was NOT run, and nothing in this script re-checks it:\n"
        "each such row would read as an installed empty credential. Check first with:\n"
        "SELECT count(*) FROM platform_secrets WHERE removed;"
    ):
        tombstones = op.get_bind().execute(
            sa.text("SELECT count(*) FROM platform_secrets WHERE removed")
        ).scalar_one()
        if tombstones:
            raise RuntimeError(
                f"platform_secrets holds {tombstones} removal version(s). Without the "
                "`removed` column each would read as an installed empty credential. Install a "
                "real value for those keys (or leave this revision in place) before "
                "downgrading."
            )
    op.execute(_forbid_mutation(_IMMUTABLE_BEFORE))
    op.drop_constraint("removed_has_no_fragment", "platform_secrets", type_="check")
    op.drop_column("platform_secrets", "removed")
