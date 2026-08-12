"""the erasure record stops being the last copy of the number

Revision ID: f4a8e1c07b62
Revises: e2c47b90d5a1
Create Date: 2026-08-11 05:45:00.000000

`execute_deletion_request` (apps/workers/retention.py) erases a subject everywhere it can
reach — `calls.from_e164`/`to_e164` nulled, transcript turns overwritten, extraction
payloads emptied, leads anonymised — and then writes its proof back onto the row that
asked for it. That row still holds `phone_e164` in cleartext. So after a successful
DPDP erasure the LAST place the person's number survives is the record proving we
removed it, and no retention policy covers `deletion_requests` at all: `retention_policies`
is keyed by `data_category` in ('recording', 'transcript', 'lead', 'consent_log'), and
`apply_retention` sweeps calls, turns, extractions and leads. Nothing sweeps this table,
by design or otherwise, so the copy is not merely surviving — it is permanent.

`ERASURE_LIMITATIONS` said so out loud ("This request record itself retains the number,
because the queued worker has to be able to find the subject; it is not cleared when the
erasure completes"), which is honest and is also the description of a defect. This
migration ends it.

--------------------------------------------------------------------------------
THE SHAPE OF THE FIX
--------------------------------------------------------------------------------

The number cannot be cleared BEFORE execution: the worker resolves the subject FROM the
row (`SELECT phone_e164 ... WHERE id = :rid`, then `WHERE from_e164 = :phone`), and the
outbox payload deliberately carries only ids so a queue dump is not a list of people who
asked to be forgotten (hard rule 6). So the number lives exactly as long as the erasure
takes, and not one moment longer:

    open request      phone_e164 NOT NULL   — the worker's only handle on the subject
    completed request phone_e164 IS NULL    — cleared in the same UPDATE as `proof`

**What clearing costs, and how it is paid.** "Have we already erased this person?" is a
question support gets asked, and after this change the row can no longer answer it from
the number. `subject_ref` — sha256(number)[:32], the same construction as the erasure
proof's `subject_hash` (`retention._hash`) and the subject-access export's `subject_ref`
(`compliance/export.py`), which is the whole reason those two agree — becomes a COLUMN
rather than something derived at read time from a field that is about to be NULL. The
hash is sufficient for every question that survives:

- *has this subject an erasure on file?* — `WHERE subject_ref = :ref`, which is why this
  migration also adds `(tenant_id, subject_ref)` as an index rather than leaving the
  lookup to a scan;
- *what did the erasure do?* — `proof`, which never carried the number in the first place;
- *is one already open?* — see below, and this one deliberately still uses the number.

The hash is not reversible, so a completed row can confirm a subject and cannot enumerate
one. That asymmetry is the entire point: `subject_ref` answers questions ABOUT a number
you already have, and answers nothing to a reader who has the table and not the number.

**Why the OPEN-request dedupe keeps using `phone_e164`.** The partial unique index from
e2c47b90d5a1 is on `(tenant_id, phone_e164) WHERE completed_at IS NULL`, and it stays
that way. Open rows always carry the number — that is now a CHECK, not an assumption —
so the index is total over exactly the rows it must cover, and switching it to
`subject_ref` would buy nothing (an open row holds the number regardless) while making
the constraint depend on the application computing a hash correctly. NULLs never conflict
in a unique index, so had the column simply been made nullable without the CHECK, a
cleared-too-early row would have silently opted OUT of the guarantee the previous
migration just established. The CHECK is what keeps those two migrations from quietly
cancelling each other.

--------------------------------------------------------------------------------
WHAT THIS MIGRATION DOES, IN ORDER, AND WHY THAT ORDER
--------------------------------------------------------------------------------

1. `subject_ref` is added nullable, then BACKFILLED from `phone_e164` in SQL —
   `substr(encode(sha256(convert_to(phone_e164, 'UTF8')), 'hex'), 1, 32)`, verified byte
   for byte against `hashlib.sha256(phone.encode()).hexdigest()[:32]`. It must be filled
   BEFORE any number is cleared, or the 176 completed rows on this database would lose
   their only future handle on the subject. `sha256()` is a core function in PG11+; no
   extension is required and none is created.
2. `phone_e164` drops NOT NULL.
3. Completed rows are cleared. They are the ones whose erasure is already done: the
   worker has no further use for them, and by definition every one of them is a number
   the client asked us to forget.
4. The two CHECKs go on `NOT VALID` first and are VALIDATEd in a second statement. That
   is the non-blocking pattern this repo uses (c5a930e6b1d4's neighbourhood): `ADD
   CONSTRAINT ... NOT VALID` takes a brief ACCESS EXCLUSIVE lock and does NOT scan the
   table, and `VALIDATE CONSTRAINT` scans it under a SHARE UPDATE EXCLUSIVE lock that
   readers and writers do not block on. On 215 rows it is indistinguishable from
   instantaneous; on a table that matters it is the difference between a deploy and an
   outage, and getting the habit right on the small table is how it is right on the big
   one.
5. `subject_ref` is then SET NOT NULL. Postgres 12+ recognises the already-VALIDated
   `subject_ref IS NOT NULL` CHECK and skips the second full scan, which is the only
   reason the redundant-looking CHECK in step 4 is there.

6. A BEFORE INSERT trigger fills `subject_ref` from `phone_e164` when the writer did not
   supply it. Two reasons, and the second is the important one:

   - **The hash cannot drift from the number.** One definition of the reference now
     lives in the database, next to the column, deriving it the same way
     `compliance.export.subject_ref` and `retention._hash` do. A writer that computes it
     differently is still free to be wrong, but a writer that does not compute it at all
     — which is every INSERT written before this migration existed, in fixtures and ops
     scripts alike — gets the right answer rather than a NOT NULL violation.
   - **NOT NULL without it would be a trap.** `subject_ref` is not optional (it is the
     only handle on a completed request), so the column has to be NOT NULL; but a NOT
     NULL column with no default turns every existing INSERT statement in the repository
     into a failure in the same release. The trigger is what makes those two facts
     compatible, and it is why this migration does not need to reach into test files or
     scripts it does not own.

   It fills, and never overwrites: a caller that supplies `subject_ref` keeps its value,
   so the application remains the author of the reference and the trigger is the floor.

Steps 1 and 3 are DML, and migrations run as the table OWNER while `deletion_requests`
is FORCE ROW LEVEL SECURITY — with no `app.tenant_id` GUC the policy is fail-closed, so
both statements would touch zero rows, report success, and leave the SET NOT NULL in
step 5 to fail on data the migration believed it had filled. The `NO FORCE` / `FORCE`
bracket (d3b71c9a5e08's, for the same reason) lifts RLS for the OWNER ONLY, for the
duration of this transaction: `calevate_app` is not the owner and is NOSUPERUSER
NOBYPASSRLS, so it keeps every policy throughout, and DDL being transactional means FORCE
is restored before anything commits.

`deletion_requests` is not an append-only ledger — it is absent from `APPEND_ONLY_TABLES`
(apps/api/db/registry.py), carries no immutability trigger, and the worker already
UPDATEs it to stamp `completed_at` and `proof`. Hard rule 4 is not in tension here: the
proof, which is the evidence, is untouched and remains what an auditor reads.

**Hard rule 8, two-step deprecation.** `phone_e164` is NOT dropped and must not be — this
release stops KEEPING it, the column itself stays, and a later release may consider
whether an open request could work from something else. Dropping it now would break the
worker in the same deploy that stopped writing it, which is precisely the sequence the
rule forbids.

**The code that ships with this**: `retention.execute_deletion_request` clears the number
in the same UPDATE that stamps `completed_at`, so no window exists where a request is
complete and still holds the number; `compliance/deletion.py` writes `subject_ref` on
insert and READS it back rather than re-deriving it from a column that may be NULL, so a
completed request's status still carries a subject reference; and `ERASURE_LIMITATIONS`
loses the bullet that promised the opposite.

**Downgrade** restores NOT NULL on `phone_e164` and drops `subject_ref`, in that order,
and it cannot resurrect the numbers it cleared — nor should it want to: they were cleared
because a data principal exercised a right, and a rollback that reconstituted them would
be a fresh breach. That means a downgrade can only be taken on a database whose completed
requests it is willing to LOSE: rows with a NULL `phone_e164` are deleted so NOT NULL can
be restored. That is stated here rather than discovered at 3am. The schema returns to its
previous shape and the pre-migration code runs correctly against the result, which is
what hard rule 8's reversibility means; the erasure records that survive are the open
ones, which are the only ones the pre-migration code needs.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a8e1c07b62"
down_revision: str | None = "e2c47b90d5a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "deletion_requests"
INDEX = "ix_deletion_requests_tenant_subject"
CK_OPEN_HAS_NUMBER = "ck_deletion_requests_open_request_names_its_subject"
CK_SUBJECT_REF = "ck_deletion_requests_subject_ref_not_null"

# The identical construction to `compliance.export.subject_ref` and `retention._hash`:
# sha256 of the UTF-8 bytes, hex, first 32 characters. An access request and an erasure
# request for the same person must be correlatable without either record carrying the
# number, which only works if all three derive the same reference.
_SUBJECT_REF = "substr(encode(sha256(convert_to(phone_e164, 'UTF8')), 'hex'), 1, 32)"

TRIGGER = "deletion_requests_subject_ref"
FUNCTION = "calevate_deletion_request_subject_ref"

# Fills, never overwrites: the application stays the author of the reference and this is
# the floor under it, so a writer that predates the column cannot produce a row with no
# handle on its subject.
_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {FUNCTION}() RETURNS trigger AS $$
BEGIN
    IF NEW.subject_ref IS NULL AND NEW.phone_e164 IS NOT NULL THEN
        NEW.subject_ref := substr(
            encode(sha256(convert_to(NEW.phone_e164, 'UTF8')), 'hex'), 1, 32
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(TABLE, sa.Column("subject_ref", sa.Text(), nullable=True))

    # RLS is FORCEd on this table and the migration role owns it, so the owner is subject
    # to the policy too; with no app.tenant_id GUC both statements below would silently
    # match zero rows. The bracket lifts it for the owner only, inside this transaction.
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"UPDATE {TABLE} SET subject_ref = {_SUBJECT_REF} WHERE subject_ref IS NULL")
    op.alter_column(TABLE, "phone_e164", existing_type=sa.Text(), nullable=True)
    # The erasure is done; the worker has no further use for the number, and it is the
    # number a data principal asked us to forget.
    op.execute(f"UPDATE {TABLE} SET phone_e164 = NULL WHERE completed_at IS NOT NULL")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")

    # Before the NOT NULL below, so no writer is caught between the two.
    op.execute(_FUNCTION_SQL)
    op.execute(
        f"CREATE TRIGGER {TRIGGER} BEFORE INSERT ON {TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION {FUNCTION}()"
    )

    # NOT VALID first: no table scan under the ACCESS EXCLUSIVE lock. The VALIDATE that
    # follows scans under SHARE UPDATE EXCLUSIVE, which concurrent readers and writers do
    # not block on.
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CK_OPEN_HAS_NUMBER} "
        "CHECK (completed_at IS NOT NULL OR phone_e164 IS NOT NULL) NOT VALID"
    )
    op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CK_OPEN_HAS_NUMBER}")
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CK_SUBJECT_REF} "
        "CHECK (subject_ref IS NOT NULL) NOT VALID"
    )
    op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CK_SUBJECT_REF}")
    # PG12+ uses the validated CHECK above instead of a second full scan.
    op.alter_column(TABLE, "subject_ref", existing_type=sa.Text(), nullable=False)

    # "Has this subject an erasure on file?" — the question that replaces the one the
    # cleared number used to answer.
    op.create_index(INDEX, TABLE, ["tenant_id", "subject_ref"], unique=False)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_index(INDEX, table_name=TABLE)
    op.execute(f"DROP TRIGGER IF EXISTS {TRIGGER} ON {TABLE}")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}()")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CK_SUBJECT_REF}")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CK_OPEN_HAS_NUMBER}")

    # The numbers this migration cleared cannot be reconstituted from a hash, and must
    # not be: they were cleared because someone exercised an erasure right. Restoring
    # NOT NULL therefore costs the completed rows. Documented in the docstring, not
    # discovered here.
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DELETE FROM {TABLE} WHERE phone_e164 IS NULL")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")

    op.alter_column(TABLE, "phone_e164", existing_type=sa.Text(), nullable=False)
    op.drop_column(TABLE, "subject_ref")
