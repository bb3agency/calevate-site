"""a ledger survives TRUNCATE, and survives a session that turns triggers off

Revision ID: a2e9f31c605d
Revises: e1a7c93d5b02
Create Date: 2026-08-16 09:40:00.000000

Hard rule 4 says the ledgers are INSERT-only, and `check_ledger_immutability` proved
that by asking whether an ENABLEd, row-level, RAISEing trigger covers UPDATE and DELETE.
It does, on all eight. Both of the following still emptied every one of them, on a
migrated database, as the OWNER role — the role migrations and any operator `psql`
session run as:

    BEGIN; TRUNCATE audit_log; SELECT count(*) FROM audit_log;   -->  0
    BEGIN; SET LOCAL session_replication_role = replica;
           DELETE FROM audit_log; SELECT count(*) FROM audit_log; -->  0

--------------------------------------------------------------------------------
1. TRUNCATE IS NOT DELETE, AND A ROW TRIGGER NEVER SEES IT
--------------------------------------------------------------------------------

`BEFORE UPDATE OR DELETE ... FOR EACH ROW` cannot fire on TRUNCATE: TRUNCATE has no
rows to fire per, which is the whole reason it is fast. PostgreSQL's answer is a
separate statement-level trigger (`BEFORE TRUNCATE ... FOR EACH STATEMENT`), and that
is what the eight ledgers were missing. So the guarantee held against the verb the
guardrail asked about and not against the verb that erases the most, fastest.

`calevate_app` could not reach it — it holds no TRUNCATE grant (05bba2f3c19c grants
exactly SELECT/INSERT/UPDATE/DELETE), and that is verified, not assumed. The owner
could, and the owner is not a hypothetical: it is what `alembic upgrade` runs as and
what a human debugging production types. A compliance ledger whose only protection is
"nobody would" is not protected; the audit hash chain in particular cannot be
reconstructed from anything else in this schema.

TRUNCATE ... CASCADE is covered by the same trigger: cascading to a child fires the
CHILD's truncate trigger, so `TRUNCATE calls CASCADE` can no longer reach
`usage_events` sideways through its foreign key.

That has a deliberate second effect worth stating plainly: `TRUNCATE leads CASCADE` and
`TRUNCATE calls CASCADE` now fail too, because both cascades reach `consent_ledger` and
`usage_events`. Nothing in this repo issues a TRUNCATE (verified across `apps`,
`packages`, `scripts`, `tests`, `infra` and the workflows), so nothing breaks — and a
statement that would have destroyed the consent evidence for calls already placed, as a
side effect of clearing a different table, is exactly the one that should have to say so
out loud.

--------------------------------------------------------------------------------
2. `session_replication_role = replica` SILENTLY DISABLES AN ORIGIN TRIGGER
--------------------------------------------------------------------------------

A trigger created the ordinary way is `tgenabled = 'O'` — fires in ORIGIN mode only.
Setting `session_replication_role = replica` makes every one of them stop firing, and
then UPDATE and DELETE on a ledger just work. It is a plain `SET`, not DDL: it leaves no
schema diff, needs no `DROP TRIGGER`, and it is exactly what `pg_restore
--disable-triggers` emits, so it arrives by accident rather than by malice.

`ENABLE ALWAYS` (`tgenabled = 'A'`) is PostgreSQL's answer and is the standard hardening
for exactly this. It is safe here in the one direction that could bite: an ALWAYS trigger
also fires inside a logical-replication apply worker, and an apply worker for these
tables only ever replays INSERTs — the tables are append-only, so there is no UPDATE or
DELETE in the stream for the trigger to refuse.

`calevate_app` cannot set the parameter at all (`permission denied to set parameter
"session_replication_role"` — superuser-only), so this too is an owner-reachable hole,
and the same argument applies.

What is deliberately NOT closed: the owner can still `ALTER TABLE ... DISABLE TRIGGER`
or `DROP TRIGGER`. That is irreducible — whoever may create a trigger may remove it —
and it is a different kind of act: it is DDL that names the guarantee it is switching
off, it shows up in a schema diff, and `check_ledger_immutability` fails on the next
run. What this migration removes is the class of bypass that does NOT name what it is
turning off.

--------------------------------------------------------------------------------
THE TABLE LIST IS SPELLED OUT
--------------------------------------------------------------------------------

Not imported from `registry.APPEND_ONLY_TABLES`. A migration is a snapshot of the schema
on the day it ran; importing today's list would silently rewrite history the next time
somebody appends to it, and the new ledger would end up with a trigger this revision
claims to have created for it (the rule `c2f7a91b4e63` and `b8e4c1d70f92` both state).
`check_ledger_immutability` reads the live constant and will fail loudly for a ninth
ledger that lands without its own migration — which is the correct place for that to
be caught.

DOWNGRADE: exact. The truncate triggers and their function go, and the mutation triggers
return to ORIGIN mode (`ENABLE TRIGGER` resets `tgenabled` to 'O'). The pre-migration
schema is restored byte-for-byte, so the down/up walk is clean — and this revision drops
its function in the same downgrade that drops the triggers using it, which is the
`DuplicateFunction`-on-re-upgrade defect class this repo has already shipped once.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a2e9f31c605d"
down_revision: str | None = "e1a7c93d5b02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The eight append-only ledgers as of this revision, and the trigger each already
# carries. Named here rather than derived, for the reason in the docstring.
LEDGERS: tuple[tuple[str, str], ...] = (
    ("usage_events", "usage_events_append_only"),
    ("consent_ledger", "consent_ledger_append_only"),
    ("audit_log", "audit_log_append_only"),
    ("credit_ledger", "credit_ledger_append_only"),
    ("one_time_charges", "one_time_charges_append_only"),
    ("whatsapp_alert_optin_ledger", "whatsapp_alert_optin_ledger_append_only"),
    ("preference_scrub_runs", "preference_scrub_runs_append_only"),
    ("platform_secrets", "platform_secrets_append_only"),
)

TRUNCATE_FN = "calevate_forbid_truncate"


def upgrade() -> None:
    # A separate function from `calevate_forbid_mutation`: the message has to name the
    # verb an operator actually typed, or the refusal reads as a bug in their DELETE.
    op.execute(
        f"""
        CREATE FUNCTION {TRUNCATE_FN}() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                '% is append-only (hard rule 4): TRUNCATE would erase the ledger, and a '
                'compensating entry cannot bring it back. Drop this trigger explicitly '
                'if that is really the intent.',
                TG_TABLE_NAME USING ERRCODE = 'raise_exception';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table, mutation_trigger in LEDGERS:
        op.execute(
            f"CREATE TRIGGER {table}_forbid_truncate "
            f"BEFORE TRUNCATE ON {table} "
            f"FOR EACH STATEMENT EXECUTE FUNCTION {TRUNCATE_FN}()"
        )
        # ALWAYS, not the default ORIGIN — see section 2 of the docstring. Both triggers,
        # because a `replica` session that cannot DELETE but can still TRUNCATE has
        # closed nothing.
        op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {table}_forbid_truncate")
        op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {mutation_trigger}")


def downgrade() -> None:
    for table, mutation_trigger in LEDGERS:
        # Plain ENABLE resets tgenabled to 'O' (ORIGIN), the pre-migration state.
        op.execute(f"ALTER TABLE {table} ENABLE TRIGGER {mutation_trigger}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_forbid_truncate ON {table}")
    op.execute(f"DROP FUNCTION IF EXISTS {TRUNCATE_FN}()")
