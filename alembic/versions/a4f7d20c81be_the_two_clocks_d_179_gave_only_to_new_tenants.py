"""seed engine_payload and kb retention rows for the tenants that predate D-179

Revision ID: a4f7d20c81be
Revises: e5c9a2d71f38
Create Date: 2026-09-02

`c4d1f7b83e26` (D-179) widened `ck_retention_policies_category_enum` to admit
`engine_payload` and `kb`, and added `apps/workers/retention.py`'s two sweep arms behind
them. It never wrote a row. Its own docstring states the consequence in passing —
"re-upgrading re-seeds them at the defaults above **for new tenants only**" — and that
sentence is the whole defect: `_create_tenant_root` writes the full
`scripts/seed.DEFAULT_RETENTION_POLICIES` set for every organisation created AFTER that
migration, and every organisation created BEFORE it has no row for either category.

--------------------------------------------------------------------------------
WHY A MISSING ROW IS A MISSING CLOCK, NOT A DEFAULT
--------------------------------------------------------------------------------
`retention._PROBE_SQL` selects `FROM retention_policies` and `sweep_tenant` loops over
what comes back. There is no fallback to a platform default anywhere in that path: a
tenant with no `engine_payload` row is not swept at the 90-day default, it is not swept
at all, silently and for ever — the exact failure D-179 was written to close, left in
place for precisely the tenants that had been accumulating the data longest.

What that leaves behind, in the words of the migration that meant to remove it:

* **`engine_payload`** — `calls.engine_payload_ref` (D-126) points at the engine's own
  raw document for a call, which carries the caller's number and the transcript. The
  bucket lifecycle rule that was the notional clock has never been applied to a real
  bucket (`infra/README.md` §5), so nothing expires it. Only a §12 erasure reaches it,
  i.e. only for the people who filed one.
* **`kb`** — publishing a knowledge source ARCHIVES the previous version rather than
  replacing it, so every version ever published survives, including the ones no screen
  shows. A client's price list names their staff, their doctors and their contact
  numbers.

DPDP §8(7) is a duty to stop holding personal data once the purpose is served, and it is
not discharged by a category the tenant does not hold a row for.

--------------------------------------------------------------------------------
WHY HERE AND NOT IN `c4d1f7b83e26`
--------------------------------------------------------------------------------
`b7e35c2f81da` states the rule this file follows: a revision that has already run
everywhere will never run again, so editing it repairs nothing that has happened — only a
later migration can. Same discipline here, including its two consequences:

* **The values are FROZEN COPIES**, retyped from `scripts.seed.DEFAULT_RETENTION_POLICIES`
  rather than imported, so this file keeps meaning what it means today even after the
  defaults move. `tests/retention_policy_backfill_test.py` reads both and fails on drift.
* **It is idempotent**, because it runs on healthy deployments too — every tenant created
  after D-179 already has both rows. `ON CONFLICT ... DO NOTHING` on the
  `(tenant_id, data_category)` unique makes the statement a no-op there rather than an
  error, exactly as `e1a4d70c9b52::_seed_policy` does.

--------------------------------------------------------------------------------
THE `NO FORCE` / `FORCE` BRACKET
--------------------------------------------------------------------------------
`organizations` and `retention_policies` are both FORCE ROW LEVEL SECURITY, which subjects
the table OWNER to `tenant_isolation` too, and that policy is fail-closed on an unset
`app.tenant_id`. Unbracketed, the SELECT sees no organisations, the INSERT writes nothing
and the migration reports success — which is how `d4a9c17e6b02` lost the copilot-memory
row in the first place and is the failure class `tests/migration_rls_bracket_test.py`
exists to catch. The bracket lifts FORCE for the OWNER only; `calevate_app` is NOSUPERUSER
NOBYPASSRLS and keeps every policy throughout, DDL is transactional in Postgres so a
failure rolls the bracket back, and it needs no superuser.

Written out one statement per table rather than looped, for `b7e35c2f81da`'s reason: a
bracket built from a variable is invisible to a reader working from the source, including
the guard test.

The downgrade is deliberately empty: this writes no schema and invents no data. Undoing it
would delete two per-tenant settings that are now the tenant's, and re-create the gap.
`c4d1f7b83e26`'s own downgrade already removes both categories' rows if that revision is
itself reversed, which is where that deletion belongs.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a4f7d20c81be"
down_revision: str | None = "e5c9a2d71f38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: FROZEN COPIES of the two D-179 defaults (`scripts/seed.DEFAULT_RETENTION_POLICIES`):
#: 90 days for the archived vendor document, matching the period
#: `infra/object-lifecycle/policy.json` already assigned the `engine-payloads/` prefix,
#: and 365 for a superseded knowledge version, matching the transcript default because it
#: is content of the same class. Both are per-tenant defaults a client may change.
_REPAIRS: tuple[tuple[str, int, str], ...] = (
    ("engine_payload", 90, "delete"),
    ("kb", 365, "delete"),
)


def _seed_policy(category: str, ttl_days: int, action: str) -> str:
    """One default policy row per organisation, skipping any organisation that has one."""
    return (
        "INSERT INTO retention_policies (id, tenant_id, data_category, ttl_days, action, "
        f"created_at) SELECT gen_random_uuid(), id, '{category}', {ttl_days}, '{action}', "
        "now() FROM organizations "
        "ON CONFLICT ON CONSTRAINT uq_retention_policies_tenant_id_data_category DO NOTHING"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE retention_policies NO FORCE ROW LEVEL SECURITY")
    try:
        for category, ttl_days, action in _REPAIRS:
            op.execute(_seed_policy(category, ttl_days, action))
    finally:
        # In a `finally` for `b7e35c2f81da`'s reason: DDL is transactional so a failure
        # would roll the bracket back anyway, and a bracket that leans on that reads as
        # if it does not need closing. Half a bracket is a tenancy hole no RLS coverage
        # check would see — `relrowsecurity` stays true and only FORCE is gone.
        op.execute("ALTER TABLE retention_policies FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Deliberately empty — see the docstring. Removing these rows would re-open the gap."""
