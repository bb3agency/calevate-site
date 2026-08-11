"""one open erasure request per subject

Revision ID: e2c47b90d5a1
Revises: d7f2a3c9b410
Create Date: 2026-08-11 05:40:00.000000

`request_erasure` (apps/api/compliance/deletion.py) promises that a subject has at most
ONE queued, unexecuted erasure: a support agent double-clicking, or two staff filing the
same caller's request an hour apart, converge on one request and one certificate. Its
own docstring names what enforces that today and what does not:

    "The check-then-write runs under `pg_advisory_xact_lock` on the same key ... A
    partial unique index on `(tenant_id, phone_e164) WHERE completed_at IS NULL` would be
    the stronger guarantee, but that needs a migration and this table is used as-is."

This is that migration. The advisory lock demotes from load-bearing to belt-and-braces:
it still serialises the two requesters so the loser gets the WINNER'S request back
(`already_open=True`) instead of an error, which is the behaviour the API surface wants.
What changes is the failure mode of a caller who does not take the lock — a future
producer, an ops script, a fixture — from "a second erasure is queued and the subject
gets two certificates" to "the database refuses".

**Why the index and not the lock is the guarantee.** An advisory lock is only as good as
every future writer remembering to take it, and here the thing being protected is a
person's DPDP right: two open requests mean two workers racing over the same rows, two
proofs describing overlapping erasures, and a status page that cannot say which request
is *the* request. The lock is a convention in Redis-shaped clothing; this is a database
fact.

**Existing data.** Checked before writing this, and clean: 215 rows, 176 completed and
39 open, and ZERO (tenant_id, phone_e164) groups holding more than one open request. So
unlike `call_extractions` (d3b71c9a5e08) nothing has to be collapsed first — the
constraint is declared against data that already satisfies it, and the build is the
check. Nothing is deleted here and nothing needs to be.

**Why the predicate.** `WHERE completed_at IS NULL` is the whole point and not an
optimisation. Erasure is NOT terminal for a phone number: the same person can call the
same client next month, generate fresh personal data, and exercise DPDP §12 again over
it. A unique index over the full table would make that second genuine request
impossible — a compliance bug wearing a safety feature's clothes. What must never exist
twice is an OPEN request, and that is exactly what the predicate says.

**Why (tenant_id, phone_e164) and not (phone_e164).** Two tenants may each hold data
about the same caller, and each owes them an erasure separately; a global key would make
one client's request block another's. Leading with `tenant_id` also keeps a unique
violation reachable only against a row of your own — under FORCEd RLS a conflict is one
of the few channels through which a row your policy hides can announce it exists.

**RLS.** No new table, so no new policy: `deletion_requests` already carries the FORCEd
`tenant_isolation` policy from 05bba2f3c19c, and the index inherits the table's
protection. Index BUILDS are not RLS-filtered (RLS constrains queries, not the storage
layer), so unlike d3b71c9a5e08's dedupe this migration needs no `NO FORCE` bracket — it
issues no DML at all.

**Locking.** Plain `CREATE UNIQUE INDEX` inside the migration's transaction, with
`lock_timeout` so this fails fast rather than parking a lock in front of the suites that
are hammering this database right now. Not CONCURRENTLY: that cannot run inside a
transaction, and a failed concurrent build leaves an INVALID index behind — a revision
that is half applied and a table that still permits the double. The table holds 215
rows; the SHARE lock is held for microseconds.

**Downgrade** drops the index. The advisory lock in `request_erasure` is untouched by
either direction, so the pre-migration code runs correctly against the pre-migration
schema — reversibility in the sense hard rule 8 means.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e2c47b90d5a1"
down_revision: str | None = "d7f2a3c9b410"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_deletion_requests_open_subject"

_CREATE = (
    f"CREATE UNIQUE INDEX {INDEX} ON deletion_requests (tenant_id, phone_e164) "
    "WHERE completed_at IS NULL"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(_CREATE)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP INDEX IF EXISTS {INDEX}")
