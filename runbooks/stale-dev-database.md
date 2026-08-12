# Runbook — the local database cannot reach head

Symptom: `uv run alembic upgrade head` fails on the shared development database while
building `ux_credit_ledger_tenant_reason_ref`; or half of `tests/credit_ledger_unique_index_test.py`
skips with "database is at alembic revision …, which does not include f9c2b41a8e57"; or
a fresh clone's tests behave differently from a colleague's.

**This is not a bug and it is not fixable in place.** Read the reason before reaching for
a workaround, because the obvious workaround defeats a control that exists on purpose.

---

## 1. Why it cannot build

Migration `f9c2b41a8e57` creates a partial UNIQUE index:

```sql
CREATE UNIQUE INDEX CONCURRENTLY ux_credit_ledger_tenant_reason_ref
    ON credit_ledger (tenant_id, reason, ref)
 WHERE ref IS NOT NULL
   AND reason IN ('topup', 'usage', 'adjustment')
   AND occurred_at >= '2026-08-11 08:07:00+00:00'::timestamptz;
```

The shared dev database carries **two duplicate groups stamped 2027-08-27** — the pair
`(topup, UTR-DRIFT-1)` and one `(usage, <call uuid>)` — written by an earlier form of
`credit_ledger_uniqueness_test::test_the_residue_seed_cannot_drift_past_the_cutoff` back
when it wrote its future-dated fixture for real. That test has since been rewritten to
assert against INSERT parameters instead, but the rows it wrote are still there.

They are `credit_ledger` rows. `credit_ledger` is append-only under hard rule 4, and a
database trigger (`credit_ledger_append_only`) enforces it. **So the rows are permanent.**
They sit after the cutoff, so the partial predicate does not exclude them, so the unique
build fails, so `alembic_version` never advances past `f9c2b41a8e57` and nothing after it
in the chain — `a4e7b2c95d18`, `b1d5c8e73f04`, `c2f7a91b4e63` — can run either.

That the index does not build there is **the correct outcome**. The cutoff is the
migration author's own instant, truncated down to the minute; a cutoff moved into 2028 to
dodge dev residue would be a cutoff that protects nothing.

## 2. The procedure: a fresh database

`make db-reset` is `alembic downgrade base && alembic upgrade head && python -m scripts.seed`.
It is the right tool and **it must not be pointed at the shared dev database** — that
prohibition is standing (BUILD-LOG §"One process lesson"), because `downgrade base` drops
every table including other people's in-flight work. Point it at a database of your own.

```sh
# 1. A new database, owned by the migration role.
PGPASSWORD=calevate psql -h localhost -p 5433 -U calevate -d postgres \
  -c 'CREATE DATABASE calevate_fresh OWNER calevate'
PGPASSWORD=calevate psql -h localhost -p 5433 -U calevate -d calevate_fresh \
  -c 'GRANT ALL ON SCHEMA public TO calevate_app'

# 2. Point BOTH URLs at it, in .env. They are two different roles on purpose:
#    DATABASE_URL is calevate_app (NOSUPERUSER NOBYPASSRLS — hard rule 1 is only real
#    if the role the app connects as cannot bypass a policy); ALEMBIC_DATABASE_URL is
#    the owner role and is used ONLY by migrations.
#      DATABASE_URL=postgresql+psycopg://calevate_app:calevate_app@localhost:5433/calevate_fresh
#      ALEMBIC_DATABASE_URL=postgresql+psycopg://calevate:calevate@localhost:5433/calevate_fresh

# 3. Migrate and seed.
make db-reset

# 4. Prove it.
uv run alembic current            # must print the head revision
uv run pytest tests/credit_ledger_unique_index_test.py -q
```

On a database with no rows at all the `CONCURRENTLY` build is instantaneous and nothing
is skipped: `_require_the_migration` gates on `alembic_version` ancestry, so once the
revision has run, every assertion in that file is enforced.

Note `scripts/dev_bootstrap.sh` (the no-Docker path) takes `DB_NAME` for role and
database creation but runs `alembic upgrade head` against whatever `.env` says. Editing
`.env` is therefore step 2 either way, not an alternative to it.

## 3. Why stamping is wrong

The tempting shortcut is:

```sh
uv run alembic stamp f9c2b41a8e57     # ← NO
```

It appears to work. `alembic_version` advances, the later revisions run, `make test`
goes green. It is wrong for a specific reason and not merely on principle:

**`tests/credit_ledger_unique_index_test.py` gates on `alembic_version` ancestry, not on
the presence of the index — deliberately.** Its own docstring says why: "skip if the index
is missing" would pass silently on a database whose migration is broken, which is exactly
the failure the file exists to catch. Gating on the revision means that *anywhere the
migration HAS run*, every assertion is enforced.

Stamping asserts that the migration ran when it did not. It therefore:

- turns the file's gate from a skip into a set of **false assertions** — the index is
  absent, so `test_the_index_exists_on_tenant_reason_ref` fails, and if it somehow did
  not, `test_a_second_entry_with_the_same_tenant_reason_and_ref_is_refused` would run
  its two INSERTs and find both accepted;
- and that second failure is not free. The test writes to an **append-only** ledger. It
  abandons its transaction on purpose, and its docstring is explicit that a red run of
  that test on a database where the index is missing would leave a permanent post-cutoff
  duplicate — making the index unbuildable on that database **forever**. "A test whose
  failure permanently breaks the thing it tests is not a tripwire, it is a trap."

So stamping does not just hide a missing index; it converts a recoverable local
inconvenience into an irreversible one, on the same table, by the same rule that caused
the original problem.

The general form: **`alembic stamp` records a claim about history. Use it only when the
schema change genuinely already exists** (a hand-applied hotfix being adopted into the
chain, a baseline on an existing database). Never to skip a migration that failed, and
never to make a test stop asking.

## 4. If a `CONCURRENTLY` build failed and left something behind

This is the one legitimate in-place repair, and it is the case the migration's downgrade
was written for.

A failed `CREATE INDEX CONCURRENTLY` leaves an **INVALID** index behind. It is not inert:
depending on which phase failed it can still reject new insertions while being useless
for queries. It is not rolled back — the statement runs deliberately outside the
migration's transaction (`op.get_context().autocommit_block()`), because a plain
`CREATE UNIQUE INDEX` takes a SHARE lock that would block every credit write for the
length of the build. And `alembic_version` is NOT advanced, so a plain re-run then fails
with "relation already exists".

Detect it:

```sql
SELECT i.indisvalid, pg_get_indexdef(i.indexrelid)
FROM pg_index i
WHERE i.indexrelid = to_regclass('ux_credit_ledger_tenant_reason_ref');
```

`indisvalid = false` is the state. Recovery is one statement — the same one `downgrade()`
issues, which is why that downgrade drops UNCONDITIONALLY and with `IF EXISTS`: it has to
clean up an index this revision never finished creating, on a database that does not
believe the revision ran.

```sql
DROP INDEX IF EXISTS ux_credit_ledger_tenant_reason_ref;
```

Then `uv run alembic upgrade head` again. If it fails the same way a second time, the
data is the problem and you are back at §2.

`lock_timeout` is set to 30s inside the autocommit block with plain `SET`, not
`SET LOCAL` — there is no transaction for `LOCAL` to scope to, so `SET LOCAL` would be a
no-op and the statement would wait forever. 30s rather than the 3s other migrations use,
because `CONCURRENTLY` waits on concurrent transactions as well as on the table lock. A
timeout here is a bounded failure, not a broken migration.

## 5. Correcting real duplicates (production, not this problem)

If duplicate credit entries exist on a database that matters, the repair is
`scripts/reconcile_credit_ledger.py` — READ ONLY by default:

```sh
uv run python -m scripts.reconcile_credit_ledger
uv run python -m scripts.reconcile_credit_ledger --tenant <uuid>
uv run python -m scripts.reconcile_credit_ledger --apply     # writes
```

It **deletes nothing.** It appends ONE compensating entry per duplicated group —
`reason = 'adjustment'`, `delta = -(surplus)`, a content-addressed
`ref = dedupe:<reason>:<original ref>:<fingerprint>` that is its own idempotency key, and
a `meta` naming the entry it keeps and the ones it cancels. The duplicate rows remain,
because they are the evidence that the race happened, and a ledger somebody can tidy is
not evidence of anything.

Every write goes through `billing.service.record_entry` under `lock_tenant_credits`, so
two operators running it at once write one entry between them.

## What NOT to do

- **Never `alembic stamp` past a migration that failed.** §3.
- **Never DELETE the duplicate rows** to make the index build. Hard rule 4, a database
  trigger, and the reason both exist.
- **Never `make db-reset` against a shared database.** It starts with
  `alembic downgrade base`.
- **Never edit a landed migration** to move the cutoff or widen the predicate. A migration
  is a frozen historical fact; `tests/credit_ledger_unique_index_test.py::test_the_migration_and_the_reconciler_name_the_same_cutoff`
  holds the migration's literal and `scripts.reconcile_credit_ledger.LEDGER_UNIQUE_INDEX_CUTOFF`
  equal precisely so the two copies cannot drift apart under someone's fix.
- **Never run the index tests against a database you care about while they are red.** The
  failing path of the duplicate-refusal test writes to an append-only ledger.
