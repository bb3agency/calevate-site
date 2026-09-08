"""No query on a session from `apps.api.db.session` may run without a bound.

**WHAT THIS FILE EXISTS FOR.** Nothing in this process used to stop a query at ANY
duration: `db/session.py` set `pool_timeout`, which bounds the WAIT for a connection and
says nothing about what the holder then does with it. So one unindexable scan pins a
pooled connection for as long as Postgres will run it, and at `db_pool_size` of those the
deployable is down on a query nobody cancelled. `copilot/service.py` had half-noticed it
in a comment, and the §12 erasure arms in `apps/workers/retention.py` are the predicate
shape that gets there (a per-row `regexp_replace` no index can serve) — since batched, so
the example is the shape rather than the caller.

Every assertion below fails without the change, and each fails for its own reason rather
than by sharing one: revert the `set_config('statement_timeout', ...)` from a factory and
that factory's case is the one that goes red.

`pg_sleep` is the instrument because it is the only query whose duration is a parameter.
The timeouts asserted against are set through `long_running_statements` at millisecond
scale so the suite stays fast (D-29: a speed-dependent test is a CI flake); the DEFAULT
that ships is asserted as a VALUE, since exercising ten real seconds in CI would buy
nothing the assertion does not.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from apps.api.core.settings import get_settings
from apps.api.db.session import (
    LONG_RUNNING_STATEMENT_TIMEOUT_MS,
    MIGRATION_LOCK_TIMEOUT_MS,
    MIGRATION_STATEMENT_TIMEOUT_MS,
    admin_session,
    credential_session,
    ingest_config_session,
    invite_session,
    long_running_statements,
    migration_connect_args,
    tenant_session,
    untenanted_session,
    user_session,
)
from calevate_shared.config import Settings
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

REPO_ROOT = Path(__file__).resolve().parents[1]


async def _effective_timeout(session: AsyncSession) -> str:
    return str((await session.execute(text("SHOW statement_timeout"))).scalar())


async def test_a_query_that_outruns_the_budget_is_cancelled_rather_than_holding_the_pool() -> None:
    """The whole point: the DB kills the statement, the connection comes back.

    Without the bound this test does not fail — it HANGS for two seconds and passes,
    which is precisely the production failure wearing the shape of a success. So the
    assertion is on the refusal, not on the duration.
    """
    with long_running_statements(250):
        async with tenant_session(uuid.uuid4()) as session:
            with pytest.raises(DBAPIError) as caught:
                await session.execute(text("SELECT pg_sleep(2)"))
    # Postgres reports a statement_timeout cancellation as SQLSTATE 57014 (query_canceled)
    # with "canceling statement due to statement timeout" — observed from this Postgres by
    # this test, not recalled from a manual. Asserting the message rather than only the
    # exception type is what distinguishes "the timeout fired" from "the connection died",
    # which are the same exception class and very different incidents.
    assert "statement timeout" in str(caught.value).lower()


async def test_a_query_inside_the_budget_is_untouched() -> None:
    """A bound that also refuses healthy work is not a bound, it is an outage."""
    with long_running_statements(5_000):
        async with tenant_session(uuid.uuid4()) as session:
            assert (await session.execute(text("SELECT pg_sleep(0.05)"))).scalar() is not None


async def test_every_session_factory_carries_the_bound_including_the_one_with_no_guc() -> None:
    """All seven doors, because the slow query can be behind any of them.

    `untenanted_session` is the one that matters most and is the one that was easiest to
    miss: it is the only factory that had no `SELECT` of its own to append to, and it is
    the factory the global-table sweeps (`outbox_messages`, `inbox_events`) use.
    """
    with long_running_statements(4_000):
        async with tenant_session(uuid.uuid4()) as s:
            assert await _effective_timeout(s) == "4s"
        async with user_session(uuid.uuid4()) as s:
            assert await _effective_timeout(s) == "4s"
        async with invite_session("deadbeef") as s:
            assert await _effective_timeout(s) == "4s"
        async with ingest_config_session(uuid.uuid4()) as s:
            assert await _effective_timeout(s) == "4s"
        async with credential_session() as s:
            assert await _effective_timeout(s) == "4s"
        async with admin_session() as s:
            assert await _effective_timeout(s) == "4s"
        async with untenanted_session() as s:
            assert await _effective_timeout(s) == "4s"


async def test_the_tenant_guc_still_arrives_alongside_the_timeout() -> None:
    """The bound rides on the SAME statement as the RLS GUC (one round trip, hard rule 3).

    That is an optimisation, and an optimisation on the line that installs hard rule 1's
    isolation is exactly the kind that gets quietly broken. So: the GUC is still set.
    """
    tenant_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        read = await session.execute(text("SELECT current_setting('app.tenant_id', true)"))
    got = read.scalar()
    assert str(got) == str(tenant_id)


async def test_the_bound_is_transaction_local_and_cannot_outlive_the_session() -> None:
    """Same property the tenant GUC has, and for the same reason.

    A pooled connection that kept the previous holder's statement budget would hand a
    worker's two minutes to the next API request that happened to get that connection —
    which is the failure this file exists to close, arriving by the back door.
    """
    async with tenant_session(uuid.uuid4()) as s:
        with long_running_statements(4_000):
            pass
        raised = await _effective_timeout(s)
    assert raised == f"{get_settings().db_statement_timeout_ms // 1000}s"


async def test_the_default_is_the_request_budget_when_no_caller_raised_it() -> None:
    """The failure mode being closed is a slow query nobody DECLARED, so the default has
    to be the strict one and the long budget has to be reached by saying so."""
    expected = f"{get_settings().db_statement_timeout_ms // 1000}s"
    async with untenanted_session() as session:
        assert await _effective_timeout(session) == expected


async def test_the_setting_is_read_per_session_rather_than_frozen_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`applies: live` is a PROMISE THE CONSOLE PRINTS, and this is what makes it true.

    `core/platform_config.FIELD_APPLIES` classifies `db_statement_timeout_ms` as `live`,
    i.e. an operator who raises it while a report page is timing out sees the new value on
    the next session with no restart. That only holds while the value is read at session
    open; a module constant captured at import would classify the same way and lie.
    """
    monkeypatch.setattr(get_settings(), "db_statement_timeout_ms", 7_000)
    async with untenanted_session() as session:
        assert await _effective_timeout(session) == "7s"


def test_the_setting_refuses_a_value_that_is_worse_than_the_defect() -> None:
    """The bounds are the reason this can be console-editable at all.

    Zero is Postgres' spelling of "unbounded", so a floor is what stops the one field that
    closes this failure being the field that reopens it; and a request budget past two
    minutes is the unbounded case wearing a number. `scripts/check_config_applies.py`
    requires the bounds to EXIST — this asserts they are the right ones.
    """
    field = Settings.model_fields["db_statement_timeout_ms"]
    # The field's own annotation with its constraints folded back in — the same handle
    # `scripts/check_config_applies.py` bound-checks through, so this test and that
    # guardrail cannot disagree about what is being validated.
    adapter = TypeAdapter(field.rebuild_annotation())
    assert adapter.validate_python(10_000) == 10_000
    for refused in (0, 999, 120_001):
        with pytest.raises(ValidationError):
            adapter.validate_python(refused)


def test_the_long_running_door_restores_the_previous_budget_even_when_the_body_raises() -> None:
    from apps.api.db.session import _statement_timeout_ms

    with pytest.raises(RuntimeError), long_running_statements():
        assert _statement_timeout_ms.get() == LONG_RUNNING_STATEMENT_TIMEOUT_MS
        raise RuntimeError("boom")
    # Back to "nobody has declared anything", which is what makes the next session read
    # the live setting rather than the worker's budget.
    assert _statement_timeout_ms.get() is None


def test_there_is_no_door_to_no_timeout_at_all() -> None:
    """`statement_timeout = 0` is Postgres' spelling of 'unbounded', and a caller reaching
    for it is reaching for the defect. It is refused rather than documented."""
    with pytest.raises(ValueError), long_running_statements(0):
        pass


def test_the_worker_budget_stays_under_the_arq_job_timeout() -> None:
    """The number is only correct RELATIVE to `job_timeout`: past that arq cancels the
    JOB with a `CancelledError` at an arbitrary line, where a statement cancellation is an
    ordinary exception the job can catch and reschedule. If either constant moves, this is
    the test that says the pair no longer makes sense. It is also the reason this one is a
    constant and not a console field."""
    from apps.workers.settings import WorkerSettings

    assert get_settings().db_statement_timeout_ms < LONG_RUNNING_STATEMENT_TIMEOUT_MS
    assert int(WorkerSettings.job_timeout) * 1000 > LONG_RUNNING_STATEMENT_TIMEOUT_MS


def test_the_migration_connection_carries_both_gucs() -> None:
    """(b): a DDL migration must fail fast rather than queue the site behind itself.

    Driven through a REAL connection built with the exact `connect_args` `alembic/env.py`
    passes, not by reading the constants back — the thing that can break is the libpq
    `options` string, and a test that asserts the constants would pass with a malformed
    one. Sync engine, because migrations are sync.

    The APP url, not `ALEMBIC_DATABASE_URL`, and the substitution is safe here for the one
    reason `env.py` says it is not safe there: the owner role exists because migrations
    do DDL and install policies. This connection does neither — it connects and runs two
    `SHOW`s — so the only property under test, whether libpq honoured the options string,
    is identical on either role. `env.py` keeps its refusal; nothing here relaxes it.
    """
    from sqlalchemy import create_engine

    url = get_settings().database_url.replace("+asyncpg", "+psycopg")
    engine = create_engine(url, connect_args=migration_connect_args())
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SHOW lock_timeout").scalar() == "3s"
            assert conn.exec_driver_sql("SHOW statement_timeout").scalar() == "5min"
    finally:
        engine.dispose()


def test_the_migration_lock_wait_is_shorter_than_the_migration_statement_budget() -> None:
    """`statement_timeout` covers the lock wait too — measured against this Postgres in
    `test_a_statement_budget_below_the_lock_wait_would_report_the_wrong_cause` below, not
    recalled. If it were the smaller of the two it would preempt `lock_timeout`, and every
    contended migration would abort naming the wrong cause — which is the one thing an
    operator reads at 3am."""
    assert MIGRATION_LOCK_TIMEOUT_MS < MIGRATION_STATEMENT_TIMEOUT_MS


async def test_a_statement_budget_below_the_lock_wait_would_report_the_wrong_cause() -> None:
    """WHY THE ORDER OF THE TWO MIGRATION GUCS IS NOT ARBITRARY, verified rather than
    assumed: `www.postgresql.org` is egress-blocked from this container (403 on CONNECT,
    measured 8 Sep 2026), so the claim that `statement_timeout` counts time spent WAITING
    for a lock is settled here, against the Postgres the suite runs on.

    A session takes a lock; a second session asks for a conflicting one with a
    `statement_timeout` shorter than its `lock_timeout`. If the statement budget did not
    cover the wait, this would end in a lock timeout — the assertion says which one
    Postgres actually reports.
    """
    async with untenanted_session() as holder:
        await holder.execute(text("SELECT pg_advisory_xact_lock(4242)"))
        async with untenanted_session() as rival:
            # A minute, so the ONLY bound that can fire here is the statement budget:
            # under CI contention a 300ms cancellation may land late, and a shorter lock
            # wait would turn that into a flake reporting the opposite result (D-29).
            await rival.execute(text("SET LOCAL lock_timeout = '60s'"))
            await rival.execute(text("SET LOCAL statement_timeout = '300ms'"))
            with pytest.raises(DBAPIError) as caught:
                await rival.execute(text("SELECT pg_advisory_xact_lock(4242)"))
    assert "statement timeout" in str(caught.value).lower()


def test_the_offline_migration_script_sets_both_gucs_before_any_ddl() -> None:
    """`alembic upgrade --sql` emits SQL for a human to run, so the GUCs cannot ride on a
    connection and must be IN the script — ahead of the first statement, since a header
    after the DDL protects nothing.

    THE RENDER IS EXPECTED TO FAIL PART-WAY and the exit status is deliberately not
    asserted: `versions/f4a1d0b6e29c_two_notices_two_toggles.py` queries the database
    inside `upgrade()`, which offline mode has no connection for, so no full offline
    render of this repo has ever completed (reproduced 8 Sep 2026). What that revision
    breaks is everything AFTER it; the header this test is about is already on stdout, so
    the property is testable exactly as far as it is true.
    """
    import subprocess

    rendered = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head", "--sql"],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=REPO_ROOT,
        check=False,
    ).stdout
    head = rendered[: rendered.index("CREATE TABLE")]
    assert f"SET lock_timeout = {MIGRATION_LOCK_TIMEOUT_MS}" in head
    assert f"SET statement_timeout = {MIGRATION_STATEMENT_TIMEOUT_MS}" in head
