"""platform_settings gets a per-key revision, so two operators cannot silently overwrite each other

Revision ID: c5a9e34b71d0
Revises: b8e3f2a71c04
Create Date: 2026-08-15 09:10:00.000000

PLATFORM-CONFIG §7's write path was an UPSERT with no precondition: two operators with
the console open on the same key both landed, last writer won, and the first operator's
change vanished with nothing on any screen to say so. The `set_value` docstring argued
that a compare-and-swap was the wrong tool "because there is no invariant spanning the
two writes to protect". That argument is wrong, and this migration is the correction:
the invariant is that the operator DECIDED using a value they had read. `usd_inr_rate`
and `self_serve_inr_per_min` are both here — an operator who lowers a price against a
rate they read, while somebody else moves the rate, produces a margin nobody chose.

**One column, one sequence, one row-level trigger.**

WHY A SEQUENCE AND NOT A PER-ROW COUNTER (`revision = revision + 1`). A per-row counter
restarts at 1 after a revert, so an ETag an operator read BEFORE the revert would match
the row that replaced it — the exact stale-write this exists to refuse, wearing a fresh
row. A sequence is global and monotone, so a value is never reissued and a token read
before a delete can never match anything again. The `platform_settings` bump above it
argues the opposite way for the SENTINEL and both are right: the sentinel must move if
and only if the data did (so a rolled-back write must not consume a number), while a
concurrency token only has to be unique and never reused. A gap is harmless in one and a
defect in the other.

WHY NOT `xmin`. Postgres's own row version is the classic answer and SQLAlchemy supports
it as `version_id_col`. It is rejected here for one reason: it wraps around and is
reused, so "this token can never match a different row version" is not true of it. On a
table that decides the platform's FX rate, "extremely unlikely" is not the standard.

WHY NOT THE EXISTING FLEET SENTINEL as the token. `platform_config_version` already
exists and is already bumped. It is the wrong GRANULARITY: it moves on every key, so
operator B editing `alerts_email` would invalidate operator A's in-flight edit to
`usd_inr_rate`. False conflicts are worse than none — they teach people to retry without
reading, which is last-write-wins with extra steps. `core/platform_config.etag_for`
carries the same argument at the call site.

**The trigger fires on UPDATE only.** An INSERT takes its revision from the column
default, which is the same sequence; putting the trigger on INSERT as well would consume
two numbers per insert for no gain. `INSERT ... ON CONFLICT DO UPDATE` — the shape the
write path uses — takes the UPDATE path and therefore the trigger. Both routes end with
a revision no reader has seen before, which is the whole requirement.

**Concurrency.** This column makes a conditional write POSSIBLE; it does not by itself
make check-then-write atomic. `ops/config_service` takes a per-key
`pg_advisory_xact_lock` before reading the revision, so two writers on one key serialize
and the second sees the first's revision (BACKEND-PATTERNS §5, the same primitive
`set_secret` uses). Without that lock two writers could both read revision 7, both pass
the precondition and both write — which is the bug with a version column bolted on.

**Locking.** One `ALTER TABLE ... ADD COLUMN` with a volatile default, which rewrites
the table. `platform_settings` holds at most a few dozen rows and is not on any request
path (every process reads it on a background poll and keeps its last good snapshot if it
cannot), so the rewrite is milliseconds and a process that meets the lock simply serves
the snapshot it already has. `lock_timeout` is set anyway, per the house pattern.

**Downgrade** drops the trigger, the column and the sequence. Conditional writes then
fail closed rather than silently degrading to last-write-wins: `read_rows` selects the
column, so the write path errors instead of quietly losing the precondition — which is
the right direction for a control whose absence is invisible.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5a9e34b71d0"
down_revision: str | None = "b8e3f2a71c04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.execute("CREATE SEQUENCE platform_settings_revision_seq AS bigint START WITH 1")
    op.add_column(
        "platform_settings",
        sa.Column(
            "revision",
            sa.BigInteger(),
            server_default=sa.text("nextval('platform_settings_revision_seq')"),
            nullable=False,
        ),
    )
    # The sequence belongs to the column: a DROP TABLE takes it with it, and no other
    # object can start drawing from it by accident.
    op.execute("ALTER SEQUENCE platform_settings_revision_seq OWNED BY platform_settings.revision")

    # THE APP ROLE NEEDS THE SEQUENCE, AND NOTHING WAS GRANTING IT.
    #
    # `05bba2f3c19c` grants `calevate_app` DML on all tables and sets ALTER DEFAULT
    # PRIVILEGES for future TABLES — and says nothing about SEQUENCES, because until now
    # this schema had none (every primary key is a uuid_v7). The first one lands here,
    # and without these two statements every console write fails with "permission denied
    # for sequence" the moment the migration is applied to a real deployment. Found by
    # running the suite as the app role, which is the only way it could have been found.
    #
    # Both statements, not just the first: the explicit GRANT fixes THIS sequence, and
    # the default privilege means the next person to add one does not rediscover this at
    # deploy time. `USAGE` and no more — it permits `nextval`/`currval` and not `setval`,
    # so the app can draw a token and cannot rewind the counter that makes tokens unique.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'calevate_app') THEN
                GRANT USAGE ON SEQUENCE platform_settings_revision_seq TO calevate_app;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                    GRANT USAGE ON SEQUENCES TO calevate_app;
            END IF;
        END
        $$
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION platform_settings_bump_revision() RETURNS trigger AS $$
        BEGIN
            -- Unconditional: the token must move on EVERY update, including one that
            -- rewrites the note and leaves the value alone. A caller that read the row
            -- before that update read a different row.
            NEW.revision := nextval('platform_settings_revision_seq');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER platform_settings_set_revision
        BEFORE UPDATE ON platform_settings
        FOR EACH ROW EXECUTE FUNCTION platform_settings_bump_revision();
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'calevate_app') THEN
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                    REVOKE USAGE ON SEQUENCES FROM calevate_app;
            END IF;
        END
        $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS platform_settings_set_revision ON platform_settings")
    op.execute("DROP FUNCTION IF EXISTS platform_settings_bump_revision()")
    # The column owns the sequence, so dropping it takes the sequence and its grant.
    op.drop_column("platform_settings", "revision")
    op.execute("DROP SEQUENCE IF EXISTS platform_settings_revision_seq")
