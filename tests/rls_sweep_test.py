"""Generic runtime RLS sweep (hard rule 1) — the guardrail's RUNTIME twin.

`scripts/check_rls_coverage.py` statically proves every tenant table carries a FORCEd
`tenant_isolation` policy. This sweep proves the same universe of tables at runtime,
and it discovers that universe from `information_schema` on every run — a tenant table
added next month is swept automatically, with no list here to forget to update.

The exemption list is IMPORTED from `apps.api.db.registry.RLS_EXEMPT_TENANT_COLUMNS`,
the exact source of truth the static guardrail reads, so the two checks can never
disagree about what is exempt.

Honesty about what each layer proves, and the exact count each one reaches:

1. For tables `create_organization` actually seeds (organizations, agents,
   extraction_schemas, retention_policies) we prove the REAL behavioural claim:
   rows that exist for tenant A count to zero under tenant B's session, and A sees
   exactly its own rows (checked against a ground-truth superuser count).
2. For tables where neither org has rows, zero-vs-zero would prove nothing — so for
   those we instead assert, from pg_class/pg_policy at runtime, that RLS is ENABLEd,
   FORCEd, and a `tenant_isolation` policy exists. That is the enforceable generic
   claim for an unseeded table; it is coverage of the POLICY, not of row behaviour.
3. Cross-tenant WRITES on seeded tables: FORCEd RLS hides the other tenant's rows
   from UPDATE, so the observable behaviour is rowcount 0 — not an exception.
4. Cross-tenant INSERT, on ALL 42 tenant-isolated tables and behaviourally, not by
   policy inspection. This is the one layer that reaches the whole universe, because
   RLS's insert check runs ahead of NOT NULL and CHECK — an invalid two-column row is
   enough to make the policy speak, so no table needs to be seeded first. Layers 1-3
   were the ceiling before this: a policy this file had only READ was, until now, only
   ever exercised on three tables.
5. The HIJACK — tenant A re-addressing its own row to tenant B — on the seeded tables.
   Nothing in this suite probed the direction where the attacker owns the row.
6. What an EXEMPTION buys. `RLS_EXEMPT_TENANT_COLUMNS` reasons about reading; both of
   its tenant-carrying entries are asserted to refuse cross-tenant UPDATE and DELETE
   anyway (`audit_log` by the hard-rule-4 trigger, `engine_agent_routes` by the write
   policy migration c4b70e928a1f added after this test found it could not).

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
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

pytestmark = [pytest.mark.rls]

# Table names come out of information_schema, but they are interpolated into SQL, so
# they pass an identifier gate first — belt and braces, not because we distrust our
# own catalog.
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

#: 42501 insufficient_privilege — what PostgreSQL raises for "new row violates row-level
#: security policy". P0001 raise_exception — what the hard-rule-4 immutability triggers
#: raise. Asserted by CODE rather than by message so a reworded refusal is still a
#: refusal, while a not-null or foreign-key error (which would mean RLS let the row
#: through) is still a finding.
_RLS_VIOLATION = "42501"
_APPEND_ONLY_VIOLATION = "P0001"

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
    #: EVERY table carrying tenant_id, exemptions INCLUDED. `tables` above has them
    #: removed, which is right for the isolation sweep and wrong for the one test whose
    #: whole subject is what an exemption does and does not buy.
    all_tenant_tables: tuple[str, ...] = ()
    #: Tables that have an `id` column. `spend_state` is keyed on `tenant_id` alone, so
    #: the generic INSERT probe has to know which shape to send.
    has_id: frozenset[str] = frozenset()


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
            has_id = {
                str(r[0])
                for r in await conn.execute(
                    text(
                        "SELECT c.relname FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "JOIN pg_attribute a ON a.attrelid = c.oid "
                        "WHERE n.nspname = 'public' AND a.attname = 'id' "
                        "AND a.attnum > 0 AND NOT a.attisdropped"
                    )
                )
            }
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
            all_tenant_tables=tuple(sorted(discovered)),
            has_id=frozenset(has_id),
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


async def test_no_tenant_table_accepts_an_insert_naming_another_tenant(sweep: Sweep) -> None:
    """Every tenant table, not only the seeded ones: a row addressed to B is refused.

    This is the WITH CHECK half, and it is the one layer of this file that can cover the
    whole universe behaviourally. RLS's insert check runs BEFORE NOT NULL and CHECK
    constraints (`ExecInsert` calls `ExecWithCheckOptions(WCO_RLS_INSERT_CHECK, ...)`
    ahead of `ExecConstraints`, PostgreSQL 16), so `(id, tenant_id)` alone is enough to
    provoke it on any table — the row never has to be valid, only wrongly addressed.
    That is what makes it possible here and impossible for the other three verbs, which
    need a real row of B's to aim at.

    The distinction that makes this a real assertion rather than "an error happened":
    42501 means RLS refused. 23502 (not-null) or 23503 (foreign key) would mean RLS let
    the row THROUGH and something downstream happened to stop it — which on a table with
    fewer NOT NULLs tomorrow would be a silent cross-tenant write.

    `dnc_list` is the one exception and it is asserted, not skipped: its WITH CHECK
    admits a `tenant_id IS NULL` global row only from an untenanted session, so a tenant
    session naming ANOTHER tenant is refused by the same 42501 as everywhere else.
    """
    refused, wrong_error, allowed = [], [], []
    for table in sweep.tables:
        # `id` where the table has one, `tenant_id` alone where it does not
        # (`spend_state` is keyed on tenant_id). Either way the row is minimal and
        # invalid — RLS gets to it first, which is the whole mechanism under test.
        columns = (
            "(id, tenant_id) VALUES (:rid, :tid)"
            if table in sweep.has_id
            else "(tenant_id) VALUES (:tid)"
        )
        async with tenant_session(sweep.org_a) as s:
            savepoint = await s.begin_nested()
            try:
                await s.execute(
                    text(f"INSERT INTO {_ident(table)} {columns}"),
                    {"rid": uuid.uuid4(), "tid": sweep.org_b},
                )
            except DBAPIError as exc:
                state = str(getattr(exc.orig, "sqlstate", "") or "")
                (refused if state == _RLS_VIOLATION else wrong_error).append(f"{table}({state})")
            else:
                allowed.append(table)
            await savepoint.rollback()

    assert not allowed, (
        f"{allowed}: a session scoped to tenant A successfully INSERTed a row naming "
        f"tenant B. WITH CHECK is missing or does not consult app.tenant_id."
    )
    assert not wrong_error, (
        f"{wrong_error}: the cross-tenant INSERT was stopped by something OTHER than RLS "
        f"(expected sqlstate {_RLS_VIOLATION}). A not-null or foreign-key refusal means "
        "the policy let the row through and the schema happened to catch it — which "
        "stops being true the day a column becomes nullable."
    )
    assert len(refused) == len(sweep.tables), (
        f"only {len(refused)} of {len(sweep.tables)} tables were probed to a verdict — "
        "the sweep is proving less than it claims"
    )


async def test_no_tenant_table_lets_a_tenant_move_its_own_row_to_another_tenant(
    sweep: Sweep,
) -> None:
    """The hijack in the other direction: not "read B's row" but "make my row B's".

    Nothing else in this suite probes it, and it is the attack that turns an ordinary
    write permission into a cross-tenant one — a row A legitimately owns, re-addressed
    to B, where A can no longer see it and B's dashboard renders it.

    WHY IT IS REFUSED, measured rather than assumed, because the answer is not the
    obvious one and it decides what this test is worth. TWO independent PostgreSQL
    checks refuse it, and BOTH have to be broken before the UPDATE lands:

      1. This repo's tenant policies are uniformly `FOR ALL ... USING (...)` with no
         explicit WITH CHECK. PostgreSQL then uses the USING expression as the WITH
         CHECK too, so the NEW tenant_id is checked against the GUC.
      2. An UPDATE with a WHERE clause needs SELECT rights, and the permissive SELECT
         policies are also applied to the POST-update row — a row you could not read
         after the update cannot be written.

    Adding `WITH CHECK (true)` alone leaves check 2 standing. Adding a permissive
    `FOR SELECT USING (true)` alone leaves check 1 standing. Only both together move a
    row (verified on a scratch database: with either sabotage the UPDATE still raises
    42501; with both, `agents(moved 1 rows)`). So the uniform `FOR ALL, USING only`
    shape is buying defence in depth here for free, and the thing this test really
    guards is somebody "tidying" it into per-command policies without knowing that.

    Two shapes of refusal are accepted. On an ordinary table the policy raises 42501. On
    an append-only ledger the immutability trigger (hard rule 4) fires first and raises
    P0001 — refused either way, and demanding one specific code would be asserting the
    order two independent guarantees happen to run in.
    """
    assert sweep.seeded, "nothing seeded — this test would pass vacuously"
    escaped = []
    for table in sweep.seeded:
        async with tenant_session(sweep.org_a) as s:
            savepoint = await s.begin_nested()
            try:
                result = await s.execute(
                    text(f"UPDATE {_ident(table)} SET tenant_id = :other WHERE tenant_id = :own"),
                    {"other": sweep.org_b, "own": sweep.org_a},
                )
            except DBAPIError as exc:
                state = str(getattr(exc.orig, "sqlstate", "") or "")
                if state not in (_RLS_VIOLATION, _APPEND_ONLY_VIOLATION):
                    escaped.append(f"{table}(unexpected sqlstate {state})")
                await savepoint.rollback()
                continue
            if result.rowcount:
                escaped.append(f"{table}(moved {result.rowcount} rows)")
            await savepoint.rollback()
    assert not escaped, (
        f"{escaped}: tenant A re-addressed its own row to tenant B. WITH CHECK must "
        "refuse a tenant_id it does not own, or a client can hand its rows to another."
    )


async def test_an_rls_exempt_table_still_refuses_a_cross_tenant_mutation(
    sweep: Sweep,
) -> None:
    """The exemption list buys READS. It has twice been read as buying every verb.

    `RLS_EXEMPT_TENANT_COLUMNS` holds two tables that CARRY a tenant_id and are not
    policied on it, and both reasons are arguments about reading cross-tenant. Until
    migration c4b70e928a1f, a session scoped to tenant A could UPDATE, DELETE and
    RE-TENANT tenant B's `engine_agent_routes` row — silencing or stealing another
    client's inbound calls — because nothing had ever asked whether the read-shaped
    exemption also covered writes. `e4f2a86b13d7` had already fixed the identical
    oversight on `dnc_list`.

    So the property is pinned generically rather than per table: whatever an exemption
    argues about reads, no tenant session may MODIFY or DESTROY a row belonging to
    another tenant. `audit_log` satisfies it through the hard-rule-4 trigger,
    `engine_agent_routes` through its write policy — two mechanisms, one guarantee, and
    a third exempt table added tomorrow has to satisfy it too.

    Deliberately NOT asserted: cross-tenant INSERT. `audit_log`'s chain is global by
    construction and every writer goes through `compliance/audit.py`; a forged row is
    caught by the hash chain, whereas a rewritten one is caught by nothing.
    """
    exempt_with_tenant = sorted(set(RLS_EXEMPT_TENANT_COLUMNS) & set(sweep.all_tenant_tables))
    assert exempt_with_tenant, (
        "no exempt table carries a tenant_id — either the list changed shape or "
        "discovery broke; this test must not pass on an empty set"
    )

    # THE VICTIM MUST BE A TENANT THAT REALLY HAS ROWS. `create_organization` writes
    # nothing to either exempt table, so aiming at `sweep.org_b` made every UPDATE match
    # zero rows and the whole test passed on an empty set — which is how the leak this
    # test exists for survived being written. The victim is therefore read from the
    # OWNER connection (RLS-bypassing ground truth): any tenant on that table other than
    # the attacker.
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: the victim row is found without RLS"
    owner = create_async_engine(owner_url)
    try:
        async with owner.connect() as conn:
            victims = {}
            for table in exempt_with_tenant:
                victims[table] = (
                    await conn.execute(
                        text(
                            f"SELECT tenant_id FROM {_ident(table)} "
                            "WHERE tenant_id IS NOT NULL AND tenant_id <> :attacker LIMIT 1"
                        ),
                        {"attacker": sweep.org_a},
                    )
                ).scalar()
    finally:
        await owner.dispose()

    unattackable = sorted(t for t, v in victims.items() if v is None)
    assert not unattackable, (
        f"{unattackable} hold no row belonging to any tenant other than the attacker, so "
        "the probe below would match nothing and report a refusal that never happened. "
        "Seed the table or narrow this test deliberately — do not let it pass on empty."
    )

    escaped = []
    for table, victim in victims.items():
        for verb, statement in (
            ("UPDATE", f"UPDATE {_ident(table)} SET tenant_id = tenant_id WHERE tenant_id = :tid"),
            ("DELETE", f"DELETE FROM {_ident(table)} WHERE tenant_id = :tid"),
        ):
            async with tenant_session(sweep.org_a) as s:
                savepoint = await s.begin_nested()
                try:
                    result = await s.execute(text(statement), {"tid": victim})
                except DBAPIError:
                    await savepoint.rollback()
                    continue  # refused outright — the strongest outcome
                if result.rowcount:
                    escaped.append(f"{table}.{verb} reached {result.rowcount} row(s)")
                await savepoint.rollback()
    assert not escaped, (
        f"{escaped}: an RLS-exempt table let tenant A rewrite or delete another tenant's "
        "rows. The exemption is an argument about READING cross-tenant; it has never "
        "been an argument for letting one client mutate another's."
    )
