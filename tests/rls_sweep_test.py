"""Generic runtime RLS sweep (hard rule 1) — the guardrail's RUNTIME twin.

`scripts/check_rls_coverage.py` statically proves every tenant table carries a FORCEd
`tenant_isolation` policy. This sweep proves the same universe of tables at runtime,
and it discovers that universe from `information_schema` on every run — a tenant table
added next month is swept automatically, with no list here to forget to update.

The exemption list is IMPORTED from `apps.api.db.registry.RLS_EXEMPT_TENANT_COLUMNS`,
the exact source of truth the static guardrail reads, so the two checks can never
disagree about what is exempt.

Honesty about what each layer proves:

1. For tables `create_organization` actually seeds (organizations, agents,
   extraction_schemas, retention_policies, ...) we prove the REAL behavioural claim:
   rows that exist for tenant A count to zero under tenant B's session, and A sees
   exactly its own rows (checked against a ground-truth superuser count).
2. For tables where neither org has rows, zero-vs-zero would prove nothing — so for
   those we instead assert, from pg_class/pg_policy at runtime, that RLS is ENABLEd,
   FORCEd, and a `tenant_isolation` policy exists. That is the enforceable generic
   claim for an unseeded table; it is coverage of the POLICY, not of row behaviour.
3. Cross-tenant WRITES on seeded tables: FORCEd RLS hides the other tenant's rows
   from UPDATE, so the observable behaviour is rowcount 0 — not an exception.

Run: uv run pytest tests/rls_sweep_test.py -q
Requires the local Postgres (docker compose up -d) with migrations applied, plus
ALEMBIC_DATABASE_URL (owner role) for the ground-truth counts — the same requirement
the static guardrail has.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from apps.api.admin import service
from apps.api.db.registry import RLS_EXEMPT_TENANT_COLUMNS
from apps.api.db.session import tenant_session, untenanted_session
from calevate_shared.config import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

pytestmark = [pytest.mark.rls]

# Table names come out of information_schema, but they are interpolated into SQL, so
# they pass an identifier gate first — belt and braces, not because we distrust our
# own catalog.
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

# The same discovery query the static guardrail runs: every real table in `public`
# carrying a tenant_id column. The pg_tables join excludes views.
_DISCOVER_SQL = text(
    "SELECT c.table_name FROM information_schema.columns c "
    "JOIN pg_tables t ON t.tablename = c.table_name AND t.schemaname = 'public' "
    "WHERE c.column_name = 'tenant_id' AND c.table_schema = 'public'"
)

# The same policy-presence query the static guardrail runs.
_POLICY_SQL = text(
    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
    "FROM pg_class c JOIN pg_policy p ON p.polrelid = c.oid "
    "WHERE p.polname = 'tenant_isolation'"
)


def _ident(table: str) -> str:
    assert _IDENT_RE.match(table), f"suspicious table name from catalog: {table!r}"
    return f'"{table}"'


@dataclass(frozen=True)
class Sweep:
    org_a: uuid.UUID
    org_b: uuid.UUID
    agent_a: uuid.UUID
    agent_a_name: str
    tables: tuple[str, ...]  # discovered tenant tables minus documented exemptions
    seeded: tuple[str, ...]  # subset where org A really has rows (owner-truth)
    ground_a: dict[str, int]  # per-table row counts for org A, counted WITHOUT RLS
    ground_b: dict[str, int]  # same for org B
    policies: dict[str, tuple[bool, bool]]  # table -> (rls enabled, rls FORCEd)


async def _count(conn: AsyncConnection, table: str, tid: uuid.UUID) -> int:
    row = await conn.execute(
        text(f"SELECT count(*) FROM {_ident(table)} WHERE tenant_id = :tid"),
        {"tid": tid},
    )
    return int(row.scalar_one())


@pytest.fixture(scope="module")
async def sweep() -> AsyncIterator[Sweep]:
    """Two real orgs via the production onboarding path, plus a ground-truth view.

    Ground truth comes from the OWNER role (ALEMBIC_DATABASE_URL) which bypasses RLS —
    without it, 'A sees zero of B's rows' could pass vacuously because the rows were
    never written at all. Never use that role in app code paths; a test's ground truth
    is the one legitimate use.
    """
    a = await service.create_organization(
        name="Sweep Clinic A",
        slug=f"sweep-a-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    b = await service.create_organization(
        name="Sweep Clinic B",
        slug=f"sweep-b-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )

    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: ground-truth counts bypass RLS"
    owner = create_async_engine(owner_url)
    try:
        async with owner.connect() as conn:
            discovered = {r[0] for r in await conn.execute(_DISCOVER_SQL)}
            tables = tuple(sorted(discovered - set(RLS_EXEMPT_TENANT_COLUMNS)))
            policies = {
                str(r[0]): (bool(r[1]), bool(r[2])) for r in await conn.execute(_POLICY_SQL)
            }
            ground_a = {t: await _count(conn, t, a["id"]) for t in tables}
            ground_b = {t: await _count(conn, t, b["id"]) for t in tables}
        yield Sweep(
            org_a=a["id"],
            org_b=b["id"],
            agent_a=a["agent_id"],
            agent_a_name="Sweep Clinic A receptionist",
            tables=tables,
            seeded=tuple(t for t in tables if ground_a[t] > 0),
            ground_a=ground_a,
            ground_b=ground_b,
            policies=policies,
        )
    finally:
        await owner.dispose()


async def test_every_tenant_table_yields_zero_rows_cross_tenant(sweep: Sweep) -> None:
    """Every discovered tenant table isolates, via the strongest claim available.

    Seeded tables get the behavioural proof (B counts zero of A's rows; A counts
    exactly its own, against the RLS-bypassing ground truth). Unseeded tables get the
    policy proof (RLS ENABLEd + FORCEd + tenant_isolation present) — stated separately
    because zero-vs-zero on an empty table would be fake behavioural coverage.
    """
    # Discovery sanity: an empty or absurdly small sweep means the discovery query
    # broke, and a broken sweep must fail loudly rather than pass on nothing.
    assert len(sweep.tables) >= 2, f"discovery found too few tenant tables: {sweep.tables}"
    for sentinel in ("agents", "leads"):
        assert sentinel in sweep.tables, f"discovery lost a known tenant table: {sentinel}"
    assert "agents" in sweep.seeded, (
        "create_organization no longer seeds agents — the behavioural layer of this "
        "sweep just went hollow; re-point it at whatever the onboarding path now seeds"
    )

    for table in sweep.seeded:
        async with tenant_session(sweep.org_a) as s:
            own = (
                await s.execute(
                    text(f"SELECT count(*) FROM {_ident(table)} WHERE tenant_id = :tid"),
                    {"tid": sweep.org_a},
                )
            ).scalar_one()
            others = (
                await s.execute(
                    text(f"SELECT count(*) FROM {_ident(table)} WHERE tenant_id = :tid"),
                    {"tid": sweep.org_b},
                )
            ).scalar_one()
        assert own == sweep.ground_a[table], (
            f"{table}: tenant A sees {own} of its own rows, ground truth says "
            f"{sweep.ground_a[table]} — the policy is hiding a tenant's OWN data"
        )
        assert others == 0, f"{table}: tenant A can count tenant B's rows ({others} visible)"

        async with tenant_session(sweep.org_b) as s:
            leaked = (
                await s.execute(
                    text(f"SELECT count(*) FROM {_ident(table)} WHERE tenant_id = :tid"),
                    {"tid": sweep.org_a},
                )
            ).scalar_one()
        assert leaked == 0, (
            f"{table}: holds {sweep.ground_a[table]} rows for tenant A but tenant B's "
            f"session sees {leaked} of them — cross-tenant leak"
        )

    for table in sweep.tables:
        if table in sweep.seeded and sweep.ground_b[table] > 0:
            continue  # behavioural proof above is strictly stronger
        assert table in sweep.policies, (
            f"{table}: carries tenant_id but has NO tenant_isolation policy and is not "
            f"in RLS_EXEMPT_TENANT_COLUMNS — new table dodged hard rule 1"
        )
        enabled, forced = sweep.policies[table]
        assert enabled and forced, (
            f"{table}: RLS must be ENABLEd+FORCEd (enabled={enabled}, forced={forced}); "
            f"without FORCE the table owner silently bypasses the policy"
        )

    # The tenant root is special-cased everywhere (its policy matches on id, so
    # tenant_id-column discovery never finds it) — mirror the guardrail's explicit
    # check so it cannot fall through the crack between the two sweeps.
    assert "organizations" in sweep.policies, "organizations: tenant root lost its policy"
    org_enabled, org_forced = sweep.policies["organizations"]
    assert org_enabled and org_forced, "organizations: RLS must stay ENABLEd+FORCEd"
    async with tenant_session(sweep.org_b) as s:
        visible = (
            await s.execute(
                text("SELECT count(*) FROM organizations WHERE id = :oid"),
                {"oid": sweep.org_a},
            )
        ).scalar_one()
    assert visible == 0, "organizations: tenant B can see tenant A's org row"


async def test_untenanted_session_sees_no_tenant_rows_anywhere(sweep: Sweep) -> None:
    """No GUC ⇒ zero rows, on every table proven non-empty by the ground truth.

    Restricting to seeded tables keeps the assertion honest: 0 on an empty table
    proves nothing, 0 on a table that demonstrably holds rows proves fail-closed.
    """
    assert sweep.seeded, "nothing seeded — this test would pass vacuously"
    for table in sweep.seeded:
        async with untenanted_session() as s:
            n = (await s.execute(text(f"SELECT count(*) FROM {_ident(table)}"))).scalar_one()
        assert n == 0, (
            f"{table}: untenanted session sees {n} rows (ground truth has at least "
            f"{sweep.ground_a[table]}) — missing GUC must fail CLOSED, never open"
        )


async def test_no_tenant_table_accepts_a_cross_tenant_write(sweep: Sweep) -> None:
    """A session scoped to B cannot UPDATE A's rows — they are invisible to it.

    FORCEd RLS filters the target rows out of the UPDATE, so the observable behaviour
    is rowcount 0, NOT an exception (WITH CHECK only fires on rows the USING clause
    lets you reach). Asserting on rowcount is therefore the correct probe; expecting
    an error here would be testing the wrong mechanism.
    (organizations is skipped by construction: its policy matches on id, not
    tenant_id, and discovery never selects it — its write path is covered by the
    onboarding tests.)
    """
    # The concrete, named case first: B tries to rename A's receptionist.
    async with tenant_session(sweep.org_b) as s:
        result = await s.execute(
            text("UPDATE agents SET name = 'hijacked' WHERE id = :aid"),
            {"aid": sweep.agent_a},
        )
    assert result.rowcount == 0, (
        f"agents: tenant B's UPDATE reached {result.rowcount} of tenant A's rows"
    )
    async with tenant_session(sweep.org_a) as s:
        name = (
            await s.execute(text("SELECT name FROM agents WHERE id = :aid"), {"aid": sweep.agent_a})
        ).scalar_one()
    assert name == sweep.agent_a_name, "tenant A's agent was renamed by tenant B"

    # Then the generic sweep: a no-op UPDATE targeting A's rows from B's session must
    # touch zero rows on every seeded table. (No-op assignment so the probe needs no
    # knowledge of each table's shape; 0 matched rows also means no immutability
    # trigger on the append-only ledgers ever fires.)
    for table in sweep.seeded:
        async with tenant_session(sweep.org_b) as s:
            result = await s.execute(
                text(f"UPDATE {_ident(table)} SET tenant_id = tenant_id WHERE tenant_id = :tid"),
                {"tid": sweep.org_a},
            )
        assert result.rowcount == 0, (
            f"{table}: tenant B's UPDATE matched {result.rowcount} of tenant A's "
            f"{sweep.ground_a[table]} rows — RLS is not hiding them from writes"
        )
