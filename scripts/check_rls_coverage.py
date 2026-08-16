"""Guardrail: every tenant table has FORCEd RLS that actually isolates (hard rule 1).

Checks the LIVE database after migrations — `pg_class`/`pg_policy`, never the migration
that CLAIMS to have created a policy:

1. every table with a `tenant_id` column either carries a FORCEd `tenant_isolation`
   policy or is listed in `RLS_EXEMPT_TENANT_COLUMNS` with a reason;
2. the policy EXPRESSIONS reference the tenant GUC — `USING (true)` is a policy that
   exists and isolates nothing, and so is a `WITH CHECK (true)` that lets a tenant
   write rows into another tenant;
3. no OTHER policy on a tenant table opens it back up (policies are OR'd: one extra
   permissive `USING (true)` defeats every careful policy next to it);
4. the exemption list itself stays honest — every entry must still name a real TABLE
   (with or without a tenant_id: platform-scoped tables are exempt for a different
   reason and are listed in the same place) and carry a reason a reviewer can weigh;
5. the registry's `TENANT_TABLES` stays in sync with reality, both directions;
6. every append-only ledger has an immutability trigger that actually blocks
   (shared with `check_ledger_immutability`, so the two cannot drift);
7. **the two shapes rules 1-5 structurally cannot see** (P4.6) — they are driven by the
   `tenant_id` COLUMN, so a table without one is invisible to all of them. Three tables
   of exactly the kind a reviewer would ask about sat outside the exemption dict for
   months with nothing able to notice. (a) every `platform_*` table must be registered —
   that prefix is this repo's convention for "one row for the whole deployment", and two
   were created after two siblings had already been listed; (b) every table holding an
   object-storage key that dereferences to tenant data (`payload_ref`, `recording_url`)
   must be tenant-isolated OR registered, because such a row is tenant data at one
   remove. `webhook_deliveries` is the table (b) exists for: no tenant_id, no policy, and
   a `payload_ref` pointing at a CRM payload with a lead's name and number, whose "why"
   lived only in a model docstring no guardrail reads.

Run: uv run python -m scripts.check_rls_coverage   (needs migrated DB; owner URL)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from apps.api.db.registry import (
    APPEND_ONLY_TABLES,
    RLS_EXEMPT_TENANT_COLUMNS,
    TENANT_TABLES,
    Base,
)
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

from scripts.check_ledger_immutability import evaluate_triggers, fetch_triggers

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# The GUC every tenant policy must consult. A policy that never reads it cannot be
# isolating anything, whatever its name says.
TENANT_GUC = "app.tenant_id"
POLICY_NAME = "tenant_isolation"
# An exemption is an argument, not a checkbox: short strings like "n/a" or "legacy"
# are how an exemption list rots into a hiding place.
MIN_EXEMPTION_REASON = 40

# `information_schema` hides tables the current role has no privilege on, so a table
# with tenant_id and no grants would simply not appear — a guardrail passing because
# it could not see the violation. The pg_catalog view has no such filter.
_TENANT_COLUMN_SQL = text(
    "SELECT c.relname FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "JOIN pg_attribute a ON a.attrelid = c.oid "
    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
    "AND a.attname = 'tenant_id' AND a.attnum > 0 AND NOT a.attisdropped"
)

# Every ordinary/partitioned table in `public`, whatever columns it has. Same catalog
# view and same reasoning as above: `information_schema` hides what the current role
# cannot see, and a guardrail that cannot see a table passes on it.
_ALL_TABLE_SQL = text(
    "SELECT c.relname FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')"
)

#: Tables that hold an OBJECT-STORAGE KEY pointing at tenant data. The column names are
#: enumerated rather than pattern-matched because the property that matters is "this
#: string dereferences to a lead's name and number in a bucket", and that is a judgement
#: about a column, not a spelling. Adding a column of this kind to a new table is exactly
#: the moment rule 7b should fire.
_OBJECT_REF_COLUMNS = ("payload_ref", "engine_payload_ref", "recording_url", "object_key")

_OBJECT_REF_TABLE_SQL = text(
    "SELECT DISTINCT c.relname FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "JOIN pg_attribute a ON a.attrelid = c.oid "
    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
    "AND a.attname = ANY(:cols) AND a.attnum > 0 AND NOT a.attisdropped"
)

_POLICY_SQL = text(
    "SELECT c.relname, p.polname, c.relrowsecurity, c.relforcerowsecurity, "
    "pg_get_expr(p.polqual, p.polrelid), pg_get_expr(p.polwithcheck, p.polrelid), "
    "p.polcmd, p.polpermissive "
    "FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public'"
)


@dataclass(frozen=True)
class PolicyFacts:
    table: str
    name: str
    rls_enabled: bool
    rls_forced: bool
    using: str | None
    with_check: str | None
    cmd: str
    permissive: bool

    def reads_guc(self, expression: str | None) -> bool:
        return expression is not None and TENANT_GUC in expression


@dataclass(frozen=True)
class SchemaState:
    """Everything the evaluation needs, so the evaluation itself is pure and testable."""

    tenant_column_tables: frozenset[str]
    policies: tuple[PolicyFacts, ...]
    model_tables: frozenset[str]
    #: EVERY ordinary table in `public`, not only the ones carrying `tenant_id`. Read so
    #: that an exemption naming a platform-scoped table (one with no tenant_id at all —
    #: see rule 4) can be told apart from an exemption naming nothing. Defaulted so the
    #: synthetic states in `tests/guardrail_audit_test.py` keep constructing, and empty
    #: is safe there because the staleness rule also accepts `model_tables`.
    all_tables: frozenset[str] = frozenset()
    #: Tables carrying an object-storage key that dereferences to tenant data
    #: (`_OBJECT_REF_COLUMNS`). Read so rule 7b can ask the question the column-driven
    #: rules structurally cannot — see `evaluate`. Defaulted empty for the synthetic
    #: states in `tests/guardrail_audit_test.py`, where an empty set makes 7b vacuous
    #: rather than wrong.
    object_ref_tables: frozenset[str] = frozenset()

    def for_table(self, table: str) -> list[PolicyFacts]:
        return [p for p in self.policies if p.table == table]


def fetch_state(engine: Engine) -> SchemaState:
    with engine.connect() as conn:
        tenant_tables = {r[0] for r in conn.execute(_TENANT_COLUMN_SQL)}
        all_tables = {r[0] for r in conn.execute(_ALL_TABLE_SQL)}
        object_ref_tables = {
            r[0] for r in conn.execute(_OBJECT_REF_TABLE_SQL, {"cols": list(_OBJECT_REF_COLUMNS)})
        }
        policies = tuple(
            PolicyFacts(
                table=r[0],
                name=r[1],
                rls_enabled=bool(r[2]),
                rls_forced=bool(r[3]),
                using=r[4],
                with_check=r[5],
                cmd=str(r[6]),
                permissive=bool(r[7]),
            )
            for r in conn.execute(_POLICY_SQL)
        )
    return SchemaState(
        tenant_column_tables=frozenset(tenant_tables),
        policies=policies,
        model_tables=frozenset(Base.metadata.tables),
        all_tables=frozenset(all_tables),
        object_ref_tables=frozenset(object_ref_tables),
    )


def _check_isolated(table: str, policies: list[PolicyFacts], failures: list[str]) -> None:
    """One tenant-scoped table: named policy present, FORCEd, and no policy that opens
    the table back up."""
    isolation = [p for p in policies if p.name == POLICY_NAME]
    if not isolation:
        failures.append(f"{table}: has tenant_id but NO {POLICY_NAME} policy")
        return
    policy = isolation[0]
    if not (policy.rls_enabled and policy.rls_forced):
        failures.append(
            f"{table}: RLS not ENABLEd+FORCEd "
            f"(enabled={policy.rls_enabled}, forced={policy.rls_forced})"
        )
    for candidate in policies:
        # Permissive policies are OR'd together: any one of them that does not consult
        # the GUC is a hole, whatever the others say.
        if not candidate.permissive:
            continue
        if not candidate.reads_guc(candidate.using):
            failures.append(
                f"{table}: policy {candidate.name} USING expression does not read "
                f"{TENANT_GUC} — it isolates nothing ({candidate.using})"
            )
        if candidate.with_check is not None and not candidate.reads_guc(candidate.with_check):
            failures.append(
                f"{table}: policy {candidate.name} WITH CHECK does not read {TENANT_GUC} "
                f"— a tenant can write rows it cannot read ({candidate.with_check})"
            )


def evaluate(
    state: SchemaState,
    *,
    tenant_tables: list[str] | None = None,
    exemptions: dict[str, str] | None = None,
) -> list[str]:
    """Every failure the live schema deserves. Pure — tests feed it synthetic states."""
    registry_tables = list(TENANT_TABLES if tenant_tables is None else tenant_tables)
    exempt = dict(RLS_EXEMPT_TENANT_COLUMNS if exemptions is None else exemptions)
    failures: list[str] = []

    # 1-3. Every tenant_id table is isolated, or exempt with a reason.
    for table in sorted(state.tenant_column_tables):
        if table in exempt:
            continue
        _check_isolated(table, state.for_table(table), failures)

    # organizations is the tenant root: its policy matches on id, so it has no
    # tenant_id column and would otherwise never be looked at.
    org_policies = state.for_table("organizations")
    if not any(p.name == POLICY_NAME for p in org_policies):
        failures.append(f"organizations: tenant root missing its {POLICY_NAME} policy")
    else:
        _check_isolated("organizations", org_policies, failures)

    # 4. The exemption list is where a new tenant table would be hidden. Make each
    #    entry keep earning its place.
    #
    #    STALENESS IS "NO SUCH TABLE", NOT "NO SUCH TENANT_ID COLUMN". It used to be the
    #    latter, which was right while every exemption was a table that HAD the column
    #    and was not policied on it. PLATFORM-CONFIG §5 adds the other shape: tables that
    #    are deliberately outside tenant isolation because they are platform state and
    #    carry no tenant_id at all, listed here — with the reason — so that one list
    #    still answers "what is not tenant-isolated, and why". Under the old rule they
    #    would have been reported as stale, and the tempting fix would have been to give
    #    them a decorative tenant_id or to start a second exemption list; both are worse
    #    than widening what counts as a real table.
    #
    #    A typo, a renamed table and a dropped table are all still caught: the entry has
    #    to name something the live schema or this repo's own model metadata knows about.
    known_tables = state.tenant_column_tables | state.all_tables | state.model_tables
    for table, reason in sorted(exempt.items()):
        if table not in known_tables:
            failures.append(
                f"{table}: STALE RLS exemption — no such table. "
                "Remove the entry; a dead exemption hides the next real gap."
            )
        if table in registry_tables:
            failures.append(f"{table}: listed BOTH in TENANT_TABLES and as RLS-exempt")
        if len(reason.strip()) < MIN_EXEMPTION_REASON:
            failures.append(
                f"{table}: RLS exemption reason is too thin to review ({reason.strip()!r}). "
                "State why cross-tenant access is correct AND what stops PII leaking."
            )

    # 5. Registry drift, both directions.
    expected = set(registry_tables)
    actual = state.tenant_column_tables - set(exempt)
    if expected != actual:
        failures.append(
            f"registry drift: TENANT_TABLES vs live schema — "
            f"only-in-registry={sorted(expected - actual)}, only-in-db={sorted(actual - expected)}"
        )
    unknown = actual - state.model_tables
    if unknown:
        failures.append(f"tables in DB not in model metadata: {sorted(unknown)}")

    # 7. THE TABLES THIS CHECK STRUCTURALLY CANNOT SEE (P4.6).
    #
    # Rules 1-5 are driven by the `tenant_id` COLUMN. A table without one is invisible to
    # every one of them — which is fine for `users` or `alembic_version`, and was not fine
    # for three tables that sat outside `RLS_EXEMPT_TENANT_COLUMNS` for months with nothing
    # able to notice, while that dict's own contract says it is the ONE place a reviewer
    # learns what is deliberately not tenant-isolated.
    #
    # Two narrow rules rather than "every unpoliced table must be registered", because the
    # broad version would demand entries for ~20 tables nobody would ever ask about and a
    # list that long is a list nobody reads — the failure mode the dict exists to avoid.
    # Each rule names a SHAPE that is genuinely worth a reviewer's attention:
    #
    # (a) PLATFORM STATE. `platform_*` is this repo's naming convention for "one row for
    #     the whole deployment" (PLATFORM-CONFIG §5): the big red switch, the TM
    #     registration, the config version, the vendor credentials, the AI spend ceiling.
    #     Every one of them is a thing a reviewer asks "why can any tenant session touch
    #     this?" about, and `platform_state` and `platform_ai_spend` were both created
    #     after two siblings had already been registered.
    for table in sorted(t for t in state.all_tables if t.startswith("platform_")):
        if table not in exempt:
            failures.append(
                f"{table}: platform-scoped table not in RLS_EXEMPT_TENANT_COLUMNS. "
                "It carries no tenant_id, so no column-driven rule above can see it — "
                "state why cross-tenant access is correct and what stops PII leaking, "
                "beside its siblings."
            )
    # (b) AN OBJECT-STORAGE KEY WITH NO TENANT. A row holding `payload_ref` or
    #     `recording_url` is a pointer INTO tenant data, so it is tenant data at one
    #     remove. If the table carries a tenant_id, rules 1-3 already own it. If it does
    #     not, the reason has to be written down: `webhook_deliveries` is the table this
    #     rule exists for, and its "why" lived only in a model docstring that no guardrail
    #     reads and no test pinned.
    for table in sorted(state.object_ref_tables - state.tenant_column_tables):
        if table not in exempt:
            failures.append(
                f"{table}: holds an object-storage reference to tenant data and has "
                "no tenant_id, so nothing above can check it. Register it in "
                "RLS_EXEMPT_TENANT_COLUMNS with what stops the reference leaking."
            )
    return failures


def main() -> int:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    engine = create_engine(url.replace("+asyncpg", "+psycopg"))
    try:
        state = fetch_state(engine)
        failures = evaluate(state)
        # 6. Append-only triggers, verified by the same code the ledger guardrail uses.
        failures += evaluate_triggers(fetch_triggers(engine))
    finally:
        engine.dispose()

    if failures:
        print("RLS COVERAGE: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    exempt = ", ".join(sorted(RLS_EXEMPT_TENANT_COLUMNS)) or "none"
    print(
        f"RLS COVERAGE: OK ({len(state.tenant_column_tables)} tenant-column tables, "
        f"{len({p.table for p in state.policies})} policied, GUC-checked; "
        f"exempt-with-reason: {exempt}; {len(APPEND_ONLY_TABLES)} append-only triggers)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
