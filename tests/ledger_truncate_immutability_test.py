"""The append-only ledgers survive the two verbs the trigger check never asked about.

`check_ledger_immutability` proved, on the live database, that every table in
`APPEND_ONLY_TABLES` carries an enabled, row-level, RAISEing trigger covering UPDATE and
DELETE. All eight did. Both of these still emptied every one of them, on a fully
migrated database, as the OWNER role:

    TRUNCATE audit_log;                                        -->  0 rows left
    SET session_replication_role = replica; DELETE FROM ...;   -->  0 rows left

TRUNCATE never reaches a `FOR EACH ROW` trigger — it has no rows to fire per — and a
trigger created the ordinary way is `tgenabled = 'O'` (ORIGIN), which stops firing
entirely under `session_replication_role = replica`. Migration a2e9f31c605d adds a
statement-level `BEFORE TRUNCATE` trigger to each ledger and promotes every blocking
trigger to `ENABLE ALWAYS`; this file is what fails if either is undone.

WHY THE OWNER ROLE, NOT `calevate_app`. `calevate_app` was never the risk and this file
proves it (`test_the_app_role_holds_no_truncate_grant`): 05bba2f3c19c grants it exactly
SELECT/INSERT/UPDATE/DELETE, and `session_replication_role` is superuser-only. The role
that can do both is the OWNER — what `alembic upgrade` runs as, and what a human
debugging production types into `psql`. A compliance ledger whose only protection is
"nobody would" is not protected, so every attack below is mounted as the owner.

NOTHING HERE COMMITS. Each attack runs inside one transaction that is abandoned, for the
reason `credit_ledger_unique_index_test` sets out at length: a red run must not leave a
row in a table hard rule 4 forbids deleting. The two attacks that need a row to fire a
row-level trigger insert it in the same transaction they abandon.

THE HONEST SABOTAGE for a DATABASE-enforced guarantee is not deleting a line of Python;
it is turning the DDL off. Four were run against a migrated scratch database while
writing this file, each restored afterwards with a green run either side. The four
signatures are distinct, and none of them is "everything went red":

    ALTER TABLE audit_log DISABLE TRIGGER audit_log_forbid_truncate
        -> [audit_log] TRUNCATE audit_log was not refused ... (sqlstate=None)
        -> [TRUNCATE]  under session_replication_role=replica, TRUNCATE ... not refused
        -> ...switched_off_by_a_session_variable: ['audit_log'] carry no BEFORE TRUNCATE
    ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only    (ALWAYS -> ORIGIN)
        -> [UPDATE] / [DELETE] under session_replication_role=replica, ... not refused
        -> ...switched_off_by_a_session_variable: audit_log.audit_log_append_only is
           ENABLE ORIGIN, not ENABLE ALWAYS
    GRANT TRUNCATE ON leads TO calevate_app
        -> test_the_app_role_holds_no_truncate_grant: calevate_app can TRUNCATE ['leads']
    DROP TRIGGER usage_events_forbid_truncate ON usage_events
        -> [usage_events] TRUNCATE usage_events was not refused ... (sqlstate=None)

`scripts/check_ledger_immutability` fails on the first two as well, which is the point of
having both: this file proves the refusal happens, the guardrail proves the DDL that
causes it is still installed.

Run: uv run pytest tests/ledger_truncate_immutability_test.py -q
Requires ALEMBIC_DATABASE_URL (owner role) — an unprivileged connection cannot mount
the attacks this file exists to prove are refused.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from apps.api.db.registry import APPEND_ONLY_TABLES
from calevate_shared.config import Settings
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

pytestmark = [pytest.mark.rls]

#: PostgreSQL's `raise_exception`, the ERRCODE every append-only trigger uses. Asserted
#: rather than matching on the message text so a reworded refusal does not read as a
#: hole, while a *different* failure (a missing grant, a FK, a syntax error) still does.
RAISE_EXCEPTION = "P0001"

#: A ledger whose parent can be TRUNCATEd, and that parent. `TRUNCATE calls CASCADE`
#: reaches `usage_events` and `consent_ledger` sideways through their foreign keys, and
#: a cascade fires the CHILD's truncate trigger — so the sideways route has to be proven
#: closed too, not assumed closed because the direct one is.
CASCADE_PARENT = "calls"


@pytest.fixture(scope="module")
async def owner() -> AsyncIterator[AsyncEngine]:
    """The OWNER role. The app role cannot mount these attacks — that is the point."""
    url = Settings().alembic_database_url
    assert url, (
        "ALEMBIC_DATABASE_URL (owner role) required: TRUNCATE and "
        "session_replication_role are exactly the privileges calevate_app does not hold, "
        "so an app-role connection would pass this file for the wrong reason"
    )
    engine = create_async_engine(url)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _attack(conn: AsyncConnection, statements: list[str]) -> str | None:
    """Run `statements` in one transaction, always abandoned. Returns the SQLSTATE of
    the first refusal, or None if every statement was allowed to run."""
    trans = await conn.begin()
    try:
        for statement in statements:
            await conn.execute(text(statement))
    except DBAPIError as exc:
        return str(getattr(exc.orig, "sqlstate", "") or "")
    finally:
        await trans.rollback()
    return None


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
async def test_truncate_is_refused_on_every_append_only_ledger(
    owner: AsyncEngine, table: str
) -> None:
    """The verb that empties a ledger fastest, and the one no row trigger can see."""
    async with owner.connect() as conn:
        state = await _attack(conn, [f'TRUNCATE "{table}"'])
    assert state == RAISE_EXCEPTION, (
        f"TRUNCATE {table} was not refused by a raising trigger (sqlstate={state!r}). "
        f"{table} is in APPEND_ONLY_TABLES: hard rule 4 says its rows are evidence, and "
        f"TRUNCATE destroys all of them with no compensating entry possible."
    )


async def test_truncate_cascade_cannot_reach_a_ledger_through_a_foreign_key(
    owner: AsyncEngine,
) -> None:
    """A cascade fires the CHILD's truncate trigger — prove it, do not assume it."""
    async with owner.connect() as conn:
        state = await _attack(conn, [f'TRUNCATE "{CASCADE_PARENT}" CASCADE'])
    assert state == RAISE_EXCEPTION, (
        f"TRUNCATE {CASCADE_PARENT} CASCADE was not refused (sqlstate={state!r}). It "
        f"cascades into usage_events and consent_ledger, so a ledger can be emptied "
        f"sideways by naming a table that is not one."
    )


@pytest.mark.parametrize("verb", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_replica_mode_cannot_switch_the_append_only_trigger_off(
    owner: AsyncEngine, verb: str
) -> None:
    """`SET session_replication_role = replica` is a plain SET — no DDL, no schema diff,
    and it is what `pg_restore --disable-triggers` emits. Under it, an ENABLE ORIGIN
    trigger simply does not fire.

    `audit_log` is the table to prove it on: its hash chain (compliance/audit.py) is the
    one record in this schema that nothing else can reconstruct.

    A row is inserted first because a row-level trigger has nothing to fire on in an
    empty table — without it a green result would mean "no rows matched", not "refused".
    """
    seed = (
        "INSERT INTO audit_log (id, actor_type, actor_id, action, object_type, object_id, "
        f"at, prev_hash, entry_hash) VALUES ('{uuid.uuid4()}', 'system', NULL, "
        "'replica_mode_probe', 'test', NULL, now(), NULL, "
        f"'{uuid.uuid4().hex}{uuid.uuid4().hex}')"
    )
    attack = {
        "UPDATE": "UPDATE audit_log SET action = 'tampered'",
        "DELETE": "DELETE FROM audit_log",
        "TRUNCATE": "TRUNCATE audit_log",
    }[verb]
    async with owner.connect() as conn:
        state = await _attack(conn, [seed, "SET LOCAL session_replication_role = replica", attack])
    assert state == RAISE_EXCEPTION, (
        f"under session_replication_role=replica, {verb} on audit_log was not refused "
        f"(sqlstate={state!r}). The trigger is ENABLE ORIGIN, so a session variable "
        f"turns hard rule 4 off with no DDL and no schema diff."
    )


async def test_no_blocking_trigger_can_be_switched_off_by_a_session_variable(
    owner: AsyncEngine,
) -> None:
    """Catalogue twin of the behavioural test above, over ALL eight ledgers.

    The behavioural test can only afford to attack one table (it has to write a row).
    This one reads `pg_trigger.tgenabled` for every ledger, so a ninth that lands with
    an ORIGIN trigger is caught even though nothing attacks it directly.
    """
    async with owner.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT c.relname, t.tgname, t.tgenabled "
                    "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_proc p ON p.oid = t.tgfoid "
                    "WHERE NOT t.tgisinternal AND c.relname = ANY(:tables) "
                    "AND position('RAISE EXCEPTION' in upper(p.prosrc)) > 0"
                ),
                {"tables": list(APPEND_ONLY_TABLES)},
            )
        ).all()
    assert rows, "no raising triggers found at all — is this database migrated?"
    origin_only = sorted(f"{r[0]}.{r[1]}" for r in rows if r[2] != "A")
    assert not origin_only, (
        f"{', '.join(origin_only)} is ENABLE ORIGIN, not ENABLE ALWAYS. "
        "`SET session_replication_role = replica` stops an ORIGIN trigger firing, so "
        "hard rule 4 would hold only for sessions that did not think to type it. Fix in "
        "a migration: ALTER TABLE <t> ENABLE ALWAYS TRIGGER <name>."
    )
    # And the cover is complete: every ledger has a truncate trigger, not just the ones
    # that happened to be attacked above.
    covered = {r[0] for r in rows if r[1].endswith("_forbid_truncate")}
    missing = sorted(set(APPEND_ONLY_TABLES) - covered)
    assert not missing, (
        f"{missing} carry no BEFORE TRUNCATE trigger. A FOR EACH ROW trigger cannot see "
        "TRUNCATE, so UPDATE/DELETE cover alone leaves the ledger erasable."
    )


async def test_the_app_role_holds_no_truncate_grant(owner: AsyncEngine) -> None:
    """The other half of why the attacks above are mounted as the owner.

    Stated as a test rather than as a sentence in a docstring, because the grant is one
    `GRANT TRUNCATE` away from being false and nothing else would notice.
    """
    async with owner.connect() as conn:
        held = (
            (
                await conn.execute(
                    text(
                        "SELECT c.relname FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = 'public' AND c.relkind = 'r' "
                        "AND has_table_privilege('calevate_app', c.oid, 'TRUNCATE')"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert not held, (
        f"calevate_app can TRUNCATE {sorted(held)}. It is granted exactly "
        "SELECT/INSERT/UPDATE/DELETE (05bba2f3c19c) and must stay that way — the app "
        "role has no business emptying a table."
    )
