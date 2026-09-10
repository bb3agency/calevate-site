"""Async engine + tenant-scoped sessions.

The RLS contract (DATA-MODEL §1, verified against 2026 practice):
- the GUC is set with set_config('app.tenant_id', :tid, true) — the `true` makes it
  TRANSACTION-local (SET LOCAL semantics). It auto-clears at transaction end, so a
  pooled connection can never leak one tenant's context to the next request.
- a session WITHOUT the GUC sees zero tenant rows (policies fail closed), never all
  rows. Admin paths use their own explicitly-audited surface, not a GUC bypass.

Every deployable shares the engine below: `apps/api`, `apps/voice-runtime` and
`apps/workers` all import their sessions from this module, so `hide_parameters` on it
(see `get_engine`) is the single place that decides whether a DB error can quote a
transcript.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from uuid import UUID

from calevate_shared.config import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from apps.api.core.settings import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

# How long a caller may wait for a pooled connection before being told there is none.
#
# A constant rather than a setting, unlike `db_pool_size`: the size is a capacity
# decision an operator makes per deployable, this is a doctrine the whole repo already
# shares — every wait on this path is bounded (`core/queue.py`'s `conn_timeout=2`,
# `core/redis.py`'s `socket_timeout=2`, the receiver's `_DURABLE_DEADLINE_S`). Five
# seconds is well past any healthy checkout (the receiver holds a connection for ~10ms
# uncontended, ~35ms with the loop busy)
# and well under SQLAlchemy's 30-second default, which is long enough that the caller
# has already given up and only the connection is still waiting.
#
# It is deliberately ABOVE the receiver's `_DURABLE_DEADLINE_S` (2s), not below it.
# Whichever bound fires first decides what a saturated pool looks like, and the deadline
# has a designed answer — 503, `webhook_claim_timeout`, transaction rolled back, key left
# claimable for the reconciliation poller. `QueuePool limit reached` arriving first would
# be the same outage as an unhandled 500 with no alert of its own.
_POOL_TIMEOUT_S = 5.0

#: SOCKET-LEVEL BOUNDS, because none of the deadlines above survive a cancellation.
#:
#: THE HOLE. `asyncio.timeout` cancels a task ONCE. Awaits that run in a `finally` or an
#: `__aexit__` AFTER that cancellation has been delivered are not bounded by it — proved
#: rather than assumed (`tests/db_socket_bounds_test.py` executes it): a 0.2s
#: `asyncio.timeout` around a body whose context manager awaits 5s on exit returns after
#: 5.21s. `apps/voice-runtime/webhook_routes` wraps `_claim_and_enqueue` in
#: `asyncio.timeout(_DURABLE_DEADLINE_S)` and its body is `async with untenanted_session()`,
#: whose exit issues a ROLLBACK over this connection. So the durable deadline bounds the
#: WORK and not the unwind.
#:
#: The SLOW-database case is already bounded and tested (`tests/voice_runtime_ack_budget_
#: test.py`): psycopg's cancel travels a live socket, and `statement_timeout` and
#: `pool_timeout` cover the rest. The case with nothing under it is a socket ACCEPTED AND
#: THEN BLACKHOLED — a dropped NAT mapping, a firewall change, a host that stops answering
#: without an RST, the shape `core/health.py` already names. There the connect, or the
#: ROLLBACK, waits on the kernel: with no `connect_args` a connect to an accepting,
#: never-answering socket hung for the whole 30s of an outer bound, and with
#: `connect_timeout=2` it failed in 2.01s. Measured 10 Sep 2026 against psycopg 3.3.4
#: through this same `create_async_engine`.
#:
#: ONE SET FOR ALL THREE DEPLOYABLES, and that was the open question. `api`, `workers` and
#: `voice-runtime` share this engine and have different tolerances for a slow connect —
#: but a bound is only wrong for a caller if it fires on a HEALTHY one, and no deployable
#: has a healthy connect anywhere near two seconds (Postgres is co-located; the receiver
#: holds a connection for ~10ms uncontended). What differs between them is what they do
#: AFTER the failure, and that is already per-service: the receiver answers 503 and leaves
#: the key claimable for the reconciliation poller, arq retries the job three times and
#: DLQs it, a request returns problem+json. A per-service value would be a second
#: mechanism deciding the same thing, plumbed through a module none of the three
#: configures. So: one set, tightest tolerance wins.
#:
#: THE VALUES, each derived against a bound this repo already has:
#:  * `connect_timeout` 2 — libpq's minimum meaningful value (it clamps anything under 2)
#:    and equal to the receiver's `_DURABLE_DEADLINE_S` and to `health._PROBE_BUDGET_S`. It
#:    must be UNDER `_POOL_TIMEOUT_S` (5s): SQLAlchemy's `pool_timeout` bounds the wait for
#:    a free slot and NOT the connect that happens inside the checkout, so an unbounded
#:    connect is the one wait on this path that outlives every other bound. Seconds, an
#:    integer — libpq takes no finer unit.
#:  * `tcp_user_timeout` 5000ms — the knob for the ROLLBACK case, and not the keepalives.
#:    Keepalives probe an IDLE socket; a ROLLBACK has unacknowledged data in flight, so it
#:    is TCP retransmission that governs, and `TCP_USER_TIMEOUT` is what bounds that
#:    (Linux, PG12+). Five seconds = `_POOL_TIMEOUT_S`: a blackholed connection can never
#:    outlive the wait a fresh caller would already accept for a new one.
#:  * keepalives at 2s idle + 3 probes 1s apart ≈ 5s — the same ceiling for the OTHER half,
#:    a connection sitting IDLE in the pool behind a NAT that has forgotten it. That is the
#:    failure `pool_pre_ping` catches one round trip late and at the cost of a round trip;
#:    this catches it before the checkout, so the two are complementary rather than a
#:    second mechanism for one job.
_CONNECT_ARGS: dict[str, int] = {
    "connect_timeout": 2,
    "tcp_user_timeout": 5000,
    "keepalives": 1,
    "keepalives_idle": 2,
    "keepalives_interval": 1,
    "keepalives_count": 3,
}

#: The most pooled connections ONE task may hold at the same time (D-182).
#:
#: Two, and every one of the two is a deliberate design: a request's session plus the
#: short global read something inside it makes (`loadshed._read_durable` behind
#: `check_dispatch`), or the outbox dispatcher's session plus the claim that must commit
#: on its own connection. `get_engine` turns this into `max_overflow` and
#: `scripts/check_session_nesting.py` refuses a third level, so the pool's capacity and
#: the code's shape cannot drift apart the way they had.
MAX_NESTED_CONNECTIONS = 2

# --- Statement timeouts -------------------------------------------------------------
#
# WITHOUT THESE, NOTHING IN THIS PROCESS STOPS A QUERY AT ANY DURATION. `pool_timeout`
# above bounds the WAIT for a connection and says nothing about what the holder then does
# with it, so one unindexable scan holds a pooled connection for as long as Postgres is
# willing to run it. At `db_pool_size` such queries the pool is gone and every other caller
# meets `_POOL_TIMEOUT_S`, i.e. the whole deployable fails on a query nobody cancelled. A
# bound on the connection wait without a bound on the statement is not a bound; it just
# decides which caller notices first.
#
# The shape is not hypothetical: the §12 subject-erasure arms in `apps/workers/retention.py`
# match on `strpos(regexp_replace(<column>, '[^0-9]', '', 'g'), :digits)`, a per-row
# function call no index can serve. They are no longer the live example because that
# module BATCHED them (`_delete_in_batches`, `LIMIT :batch`) — which is the right fix, and
# `long_running_statements` below says why it is not this one.
#
# TRANSACTION-LOCAL, VIA THE SAME `set_config(..., true)` THE TENANT GUC USES. Not a
# server-side default, not `SET` on the connection, not an engine `connect_args`: this
# module's whole RLS contract rests on a pooled connection carrying nothing out of the
# transaction that set it, and a second, differently-scoped mechanism for the same job is
# the drift the repo's "one way per problem" bar refuses. It costs no extra round trip —
# each factory below appends the call to the `SELECT` it was already sending.
#
# WHAT IT BOUNDS IS ONE STATEMENT, NOT THE TRANSACTION. `statement_timeout` is per
# command, so a transaction that issues ten queries gets ten budgets, and a transaction
# open across an engine HTTP round trip is not cancelled by it. That is the right shape
# for what it defends — no single query may pin a connection — and callers wanting a
# whole-transaction bound still need their own deadline (`_DURABLE_DEADLINE_S`,
# `job_timeout`). Note also that a `SET LOCAL`-scoped value is IGNORED outside a
# transaction; every factory here is inside `session.begin()`, which is what makes it
# take effect at all.
#
# Milliseconds, because that is what the GUC's bare-integer form means; the value is
# passed as a string because `set_config`'s third argument makes it a text function.

#: THE DEFAULT IS A SETTING, NOT A LITERAL: `Settings.db_statement_timeout_ms`
#: (`applies: live`), which carries the ten-second default and the argument for it. It is
#: read HERE, per session open, rather than captured at import — that is what makes the
#: console's classification true, and it is free: `get_settings()` is an O(1), IO-free
#: read of a snapshot (hard rule 3).
#:
#: The one number worth repeating beside the code: ten seconds coincides with the vendor
#: ladder's `REQUEST_TIMEOUT_S` (10.0) and that is a coincidence, not a relationship. The
#: two bound different resources, neither is a fallback for the other, and moving one
#: implies nothing about the other.
#:
#: THE OVERRIDE'S SIZE IS A CONSTANT AND MUST STAY ONE, which is the opposite call from
#: the default one line up. It is not an operator's dial: it is defined RELATIVE to
#: `apps.workers.settings.WorkerSettings.job_timeout` (300s), a value in code, and the
#: relation is the whole of its correctness. 120s is well UNDER that, not near it —
#: past `job_timeout` arq cancels the JOB (an `asyncio.CancelledError` at whatever line
#: was executing), whereas a `statement_timeout` cancellation is an ordinary
#: `QueryCanceled` the job can catch, log and reschedule, and two minutes leaves three for
#: it to do that. A console that could raise this above `job_timeout` would convert the
#: recoverable failure into the unrecoverable one, and it would do it in the WORKERS,
#: which do not run `start_config_refresher` (`apps/workers/settings.startup`) and so
#: would not see the change until a restart anyway.
LONG_RUNNING_STATEMENT_TIMEOUT_MS = 120_000

#: `None` means "no caller has declared anything, so read the setting at use time". A
#: value captured here instead would freeze the live setting at import.
_statement_timeout_ms: ContextVar[int | None] = ContextVar(
    "calevate_statement_timeout_ms", default=None
)


def _statement_timeout_ms_value() -> int:
    """This session's budget: a declared override, else the live setting."""
    declared = _statement_timeout_ms.get()
    return declared if declared is not None else get_settings().db_statement_timeout_ms


@contextmanager
def long_running_statements(
    timeout_ms: int = LONG_RUNNING_STATEMENT_TIMEOUT_MS,
) -> Iterator[None]:
    """Raise the statement budget for sessions opened inside this block. ONE door.

    A retention sweep, an erasure scan or a campaign reap legitimately runs longer than
    a request, and the alternative designs both fail the same way: a per-factory
    `statement_timeout_ms=` keyword would have to be threaded through seven context
    managers and would be spelt at the call site of every worker query rather than once
    per job, and a worker-wide default set at bootstrap would raise the budget for the
    request-shaped reads workers ALSO make (`check_dispatch`, `get_platform_status`)
    without anyone choosing that.

    So the budget is raised by ENTERING something named, and a job that needs longer says
    so in its own code. A job that does not is bounded like a request — the failure mode
    this closes is a slow query nobody declared, and it must not be reachable by
    omission.

    A `ContextVar`, so an asyncio task that enters this cannot raise the budget for a
    sibling task running on the same loop; the value is restored on exit even if the body
    raises. Nesting is fine and the innermost wins.

    **NOTHING ENTERS THIS YET, AND THE FIRST CANDIDATE DELIBERATELY DOES NOT.** The
    obvious caller looked like the subject-erasure arms in `apps/workers/retention.py`,
    whose `strpos(regexp_replace(<column>, '[^0-9]', '', 'g'), :digits)` predicates are
    unindexable by construction. That module now answers the question itself, and its
    answer is right: it BATCHES them (`_delete_in_batches`, `LIMIT :batch`) so each
    statement finishes far inside any timeout, and its own comment refuses the
    alternative — "an override exempting the erasure job from the timeout would keep it
    working and would also keep the lock, which is the actual defect".
    That is the rule this door is held to. It exists for work that is legitimately long
    and cannot be cut up — not as the escape hatch for a statement that should have been
    batched. If nothing ever needs it, the honest end state is to delete it rather than
    to find it a user.
    """
    if timeout_ms <= 0:
        raise ValueError("statement timeout must be positive; there is no 'no timeout'")
    token = _statement_timeout_ms.set(timeout_ms)
    try:
        yield
    finally:
        _statement_timeout_ms.reset(token)


#: Appended to the `SELECT` each factory below already issues, so the bound costs zero
#: extra round trips on the latency-critical path (hard rule 3).
_TIMEOUT_SQL = "set_config('statement_timeout', :stmt_timeout_ms, true)"


def _timeout_param() -> dict[str, str]:
    return {"stmt_timeout_ms": str(_statement_timeout_ms_value())}


# --- Migration connection timeouts --------------------------------------------------
#
# THEY LIVE HERE RATHER THAN IN `alembic/env.py`, and the reason is testability, not
# tidiness: `env.py` RUNS the migrations at import time and its module-level
# `context.is_offline_mode()` raises without a live `MigrationContext`, so a constant
# defined there cannot be imported by a test and a value nothing can assert is a value
# that drifts. This module is already the one place that says what a connection to this
# database carries; `env.py` reads these two and builds its engine with them.

#: How long a DDL statement may WAIT for its lock before giving up.
#:
#: **THE OUTAGE STARTS BEFORE THE LOCK IS EVER ACQUIRED**, which is the fact that decides
#: this number. `ALTER TABLE` needs ACCESS EXCLUSIVE; it conflicts with every other table
#: lock, so it queues behind any open read — and once it is queued, every subsequent
#: query on that table queues behind IT. A migration blocked on a long `SELECT` therefore
#: takes the table down for the duration of the block, not for the duration of the ALTER.
#: (GoCardless, "Zero-downtime Postgres migrations - the hard parts" and
#: `github.com/gocardless/activerecord-safer_migrations`, both read 8 Sep 2026: "even brief
#: locks can block access while waiting in the queue behind long-running queries"; their
#: gem's defaults are lock_timeout 750ms / statement_timeout 1500ms.)
#:
#: THREE SECONDS RATHER THAN THEIR 750ms, and the difference is the retry. Their gem
#: retries the migration in-process, so it can afford to give up almost at once; ours
#: aborts the DEPLOY, and a deploy that fails because one report query happened to be
#: running is a deploy a human re-runs at 3am for no defect. Three seconds buys the
#: ordinary case without buying the pathological one — it is short enough that the queue
#: it creates is a latency blip on one table rather than an outage, and long enough that
#: a healthy uncontended `ALTER` (which takes the lock immediately) never sees it. It is
#: NOT calibrated against a measurement of this database's lock waits, because there is
#: no production database yet to measure; if one ever shows 3s to be wrong, the fix is
#: this constant and the evidence goes here.
#:
#: The retry is the deploy, re-run — the correct place for it, because the thing to wait
#: for (the long read ahead in the queue finishing) is not something the migration can
#: influence by waiting longer.
MIGRATION_LOCK_TIMEOUT_MS = 3_000

#: How long one migration statement may RUN once it holds its lock.
#:
#: Kept far above `MIGRATION_LOCK_TIMEOUT_MS` on purpose: `statement_timeout` covers the
#: lock wait too, so a value below it would preempt `lock_timeout` and every contended
#: migration would report the wrong cause. Five minutes is generous enough for the real
#: index builds and backfills this schema has (including the 25 revisions that use
#: `autocommit_block()`, 24 of them for `CREATE INDEX CONCURRENTLY` (counted 8 Sep 2026) — a value a
#: `CREATE INDEX` cannot finish inside is a value to raise WITH a measurement, never a
#: reason to unset the bound) and short enough that a runaway
#: statement fails the deploy instead of holding ACCESS EXCLUSIVE indefinitely — which is
#: the other half of the same outage.
MIGRATION_STATEMENT_TIMEOUT_MS = 300_000


#: Socket bounds for the MIGRATION engine, deliberately looser than `_CONNECT_ARGS`.
#:
#: `alembic/env.py` builds its own `create_engine` and inherited none of the app engine's
#: bounds, so a connect to an accepting-but-blackholed socket hung the DEPLOY with nothing
#: under it — the same shape `_CONNECT_ARGS` fixes for the request path, on the one path
#: where a hang is hardest to notice, because a deploy that never returns looks like a
#: deploy that is still working.
#:
#: WHY NOT JUST REUSE `_CONNECT_ARGS`. Those values are derived against a 500ms ack budget;
#: this path has none. What a migration needs is "never waits forever", not "fails fast",
#: and the two failure costs are opposite: a request that gives up too early is retried by
#: the caller, while a MIGRATION abandoned mid-run leaves a half-applied chain a human has
#: to reason about at 3am. So each value is the loosest one that still bounds the wait:
#:  * `connect_timeout` 5 rather than 2 — a deploy legitimately runs while Postgres is
#:    still warming (compose brings it up in the same sequence), and the app engine's 2s is
#:    justified by a co-located, already-running server, which is not what this connects to.
#:  * `tcp_user_timeout` 30_000 rather than 5_000 — it bounds UNACKNOWLEDGED data, which on
#:    this path means the statement being sent, not the long wait for its result. Thirty
#:    seconds cannot preempt `MIGRATION_STATEMENT_TIMEOUT_MS` (300s) for a slow `CREATE
#:    INDEX`, because a client waiting on a result has nothing unacknowledged in flight.
#:  * keepalives at 30s idle + 3 probes 10s apart ≈ 60s — a migration connection sits idle
#:    for legitimately long stretches (a 5-minute index build is idle from TCP's point of
#:    view), so the app engine's 2s idle probe would be noise. The kernel answers a
#:    keepalive whether or not Postgres is busy, so this cannot kill a healthy long
#:    migration; it only catches a peer that has genuinely gone away.
_MIGRATION_SOCKET_ARGS: dict[str, str] = {
    "connect_timeout": "5",
    "tcp_user_timeout": "30000",
    "keepalives": "1",
    "keepalives_idle": "30",
    "keepalives_interval": "10",
    "keepalives_count": "3",
}


def migration_connect_args() -> dict[str, str]:
    """libpq `options` carrying both GUCs, plus socket bounds, for `alembic/env.py`.

    A CONNECT-TIME option rather than two `SET` statements after connecting, because a
    `SET` is transactional: `transaction_per_migration=True` gives each revision its own
    transaction, and a revision that rolls back would roll the GUCs back with it, leaving
    the rest of the run unprotected in exactly the situation where protection matters.
    Options passed in the connection string cannot be undone by a rollback.

    The socket bounds ride the same dict because they are the same kind of thing — a
    property of the connection, not of a statement — and because one function returning
    everything `env.py` needs is the only way this stays true the next time somebody adds
    a bound. See `_MIGRATION_SOCKET_ARGS` for why they are not `_CONNECT_ARGS`.
    """
    return {
        "options": (
            f"-c lock_timeout={MIGRATION_LOCK_TIMEOUT_MS} "
            f"-c statement_timeout={MIGRATION_STATEMENT_TIMEOUT_MS}"
        ),
        **_MIGRATION_SOCKET_ARGS,
    }


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    """The process-wide engine.

    `hide_parameters=True` is a HARD RULE 6 control, not a preference. Without it,
    SQLAlchemy renders the bound parameters into `str(exc)` for every DBAPI error —
    `[SQL: INSERT INTO transcript_turns ...] [parameters: {... 'text': '<the raw
    Telugu turn, phone number and all>' ...}]`. That string is the one thing an error
    path reliably touches: it is what `dispatch_outbox` writes to `outbox_messages.
    last_error` (500 chars, in the DB), what an unhandled worker exception hands to
    the traceback, and what any future `log.warning(..., reason=str(exc))` would emit.
    The JSON formatter's `redact_text()` (phone masking + a 200-char cap) sat in front
    of it, but that is a backstop measured in characters — whether the parameters fall
    inside the cap depends on how long the SQL statement happens to be. A payload we
    never render cannot be truncated too late.

    What it costs: DBAPI error strings keep the statement, the failing constraint and
    the driver's own message, and lose only the VALUES. Nothing in this repo reads
    them — every `except IntegrityError` handler here dispatches on the exception type
    (admin/service.py re-probes the DB for the slug rather than parsing the error), no
    test asserts on parameter text, and no engine runs with `echo=`. `exc.params` and
    `exc.statement` are still populated on the exception object, so a debugger keeps
    full access; only the *rendered* string drops them. Alembic builds its own engine
    (`alembic/env.py`) and is unaffected, so migration review keeps its parameter echo.

    THE POOL IS SIZED, NOT DEFAULTED, AND ITS OVERFLOW IS EXACTLY ONE — measured, not
    assumed, and the one is the depth of the deepest task in this tree minus one.

    SQLAlchemy's defaults are `pool_size=5, max_overflow=10`, and the overflow is the
    expensive half: connections above `pool_size` are SINGLE USE — the pool closes them
    on return rather than keeping them (the maintainer's own answer to this exact
    question is "avoid the overflow and make the pool size bigger. This avoids single
    use connections", sqlalchemy/sqlalchemy#11707, and the docs describe overflow as
    burst capacity beyond the persistent pool,
    https://docs.sqlalchemy.org/en/20/core/pooling.html). Under sustained load that is
    not a burst valve, it is a treadmill: measured on the webhook receiver at 100
    concurrent deliveries, the process burned **186 fresh Postgres backends for 1448
    requests (34 new connections/second)** while never exceeding 15 concurrent. Each of
    those costs ~6ms of CPU IN THIS PROCESS — `password_encryption = scram-sha-256`
    means every new connection runs PBKDF2 — so ~20% of the one core an asyncio process
    has was being spent re-authenticating connections it had just thrown away, on the
    service whose entire budget is 500ms (hard rule 3).

    The persistent pool therefore carries essentially the whole ceiling (16 ≈ the old
    5+10, so nothing loses capacity), and what a caller past it meets is a QUEUE — an
    `asyncio.Queue` inside the pool, which yields the event loop — instead of a
    connection storm. That queue is bounded by `pool_timeout`: waiting 30 seconds (the
    default) for a connection is not a slow request, it is a request that should already
    have failed, and on the receiver it would sit inside `_DURABLE_DEADLINE_S` anyway.

    WHY THE OVERFLOW IS 1 AND NOT 0 (D-182). This read `max_overflow=0`, justified by
    "no code path here holds two sessions at once: every `async with *_session()` block
    closes before the next opens (checked across apps/api and apps/workers)". That
    invariant was not true when it was written and is not true now — 50 functions hold
    two, and they are not accidents:

      - EVERY route handler. FastAPI's `Depends(deps.db)` opens the request's session
        before the handler runs and closes it after, so anything the handler calls that
        reads a global table (`compliance.check_dispatch` → `loadshed.get_platform_status`
        → `_read_durable`, on a cold 5s memo) is a second connection held inside the
        first. The admin realm does it structurally: `Depends(admin_db)` for the
        directory, a `tenant_session` inside for the client's own rows.
      - `dispatcher.dispatch_outbox` → `reliability.claim_outbox_batch`, which takes a
        second connection ON PURPOSE, because the claim must commit independently of the
        dispatcher's transaction (its docstring argues why at length).

    With no overflow, a pool at its ceiling holding only depth-2 tasks is a genuine
    self-deadlock: all 16 connections are held by tasks that each need a 17th, every one
    of them waits `_POOL_TIMEOUT_S` and every one of them fails. One overflow slot ends
    that — one waiter always gets it, does its short inner read, and releases — so the
    worst case degrades to a queue again instead of a mutual wait. It is a burst valve
    used only at saturation, which is what the docs describe overflow AS; the treadmill
    measured above needs sustained checkouts above `pool_size`, and one slot cannot
    sustain anything (at most one single-use connection in flight, versus the 186 that
    reproduced the storm).

    IT IS NOT A NUMBER TO NUDGE. `scripts/check_session_nesting.py` walks the tree for
    the deepest simultaneous holding and fails CI above 2 — `max_overflow + 1`. A third
    nesting is a change to this line, not a change to that file.

    `pool_pre_ping` stays. It costs one round trip per checkout — measured at ~0.5ms of
    the ~3.5ms of CPU this process spends per webhook, i.e. ~12% of its throughput
    (232 → 265 acks/s at 128 in flight when disabled) — and it is what keeps a connection
    severed by an idle NAT/firewall from surfacing as a failed ack on an at-most-once
    endpoint that never gets a retry (D-31). `pool_recycle` was the alternative and is
    weaker: it guesses an interval instead of asking.
    """
    global _engine, _sessionmaker
    if _engine is None:
        cfg = settings or Settings()  # env-sourced
        _engine = create_async_engine(
            cfg.database_url,
            pool_size=cfg.db_pool_size,
            # ONE, and `scripts/check_session_nesting.py` is the other half of the pair:
            # it fails CI if any task can hold more than `max_overflow + 1` connections.
            max_overflow=MAX_NESTED_CONNECTIONS - 1,
            pool_timeout=_POOL_TIMEOUT_S,
            pool_pre_ping=True,
            hide_parameters=True,
            # The only wait on this path with nothing above it — see `_CONNECT_ARGS`.
            connect_args=dict(_CONNECT_ARGS),
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


@asynccontextmanager
async def tenant_session(tenant_id: UUID) -> AsyncIterator[AsyncSession]:
    """A session whose whole transaction runs under the tenant's RLS context."""
    maker = get_sessionmaker()
    async with maker() as session, session.begin():
        await session.execute(
            text(f"SELECT set_config('app.tenant_id', :tid, true), {_TIMEOUT_SQL}"),
            {"tid": str(tenant_id), **_timeout_param()},
        )
        yield session


async def session_tenant(session: AsyncSession) -> UUID:
    """Which tenant this session is scoped to, read back from the GUC RLS keys on.

    Lives HERE, beside `tenant_session` which sets it, because one module spelling
    `app.tenant_id` is the whole design: the GUC is hard rule 1's machinery, and a
    second module that names the string is a second place to get the string wrong and a
    second hard-rule surface for the coverage ratchet to have to guard. This started life
    inside `crm/service.py`, and `check_coverage_ratchet.unguarded_surfaces()` refused it
    on exactly that ground — correctly.

    Service modules take a tenant-scoped session and no tenant id (that is what makes RLS
    the isolation rather than a convention), so a shared reader that genuinely needs the
    id — `billing.caps.read_spend_counters` — has to get it from somewhere.
    `current_setting` is the honest source: it is the value every policy on this
    connection is already evaluating, so a `WHERE tenant_id = ...` built from it can only
    ever name a row RLS would have allowed anyway. It cannot widen anything.

    Rejected: `core.context.principal_var`. That is set by the auth dependency, so a
    service function would answer for the wrong tenant — or crash — in every caller that
    is not an HTTP request, and `crm.service.dashboard` is called directly by four test
    modules and could be called by a worker tomorrow. A session's scope is a property of
    the session, not of the request that happened to open it.

    Raises rather than defaulting: an unset GUC means the caller is not in a tenant
    session, where every tenant-scoped read has already returned nothing. A zero here
    would render that as a confident "no usage".
    """
    raw = (await session.execute(text("SELECT current_setting('app.tenant_id', true)"))).scalar()
    if not raw:
        raise RuntimeError("a tenant-scoped session is required (app.tenant_id is unset)")
    return UUID(str(raw))


@asynccontextmanager
async def user_session(user_id: UUID) -> AsyncIterator[AsyncSession]:
    """A session that can answer 'which tenants may this user enter?' and nothing more.

    Authentication has a chicken-and-egg problem under RLS: scoping a session to a
    tenant requires first reading `memberships`, which is itself scoped to the tenant
    we do not have yet. `app.user_id` widens the READ policy by exactly one clause —
    your own membership rows and the organizations they point at — and widens the
    WRITE policy by nothing (migration 8c31d0f4ab27).

    Transaction-local like `app.tenant_id`, so a pooled connection cannot carry one
    request's identity into the next.
    """
    maker = get_sessionmaker()
    async with maker() as session, session.begin():
        await session.execute(
            text(f"SELECT set_config('app.user_id', :uid, true), {_TIMEOUT_SQL}"),
            {"uid": str(user_id), **_timeout_param()},
        )
        yield session


@asynccontextmanager
async def invite_session(token_hash: str) -> AsyncIterator[AsyncSession]:
    """Read-only view of ONE invitation: the one whose token hash the caller can name.

    The emailed token names its own tenant, so accepting an invitation must read
    `invitations` before a tenant is known. `app.invite_hash` widens the READ policy by
    exactly that row (migration c93a17d0e5b4) — guessing the value is guessing a
    32-byte secret, so it grants nothing the caller did not already hold.

    Writes are NOT widened: burning the invitation and creating the membership happen
    afterwards under `tenant_session`, once the tenant is known.
    """
    maker = get_sessionmaker()
    async with maker() as session, session.begin():
        await session.execute(
            text(f"SELECT set_config('app.invite_hash', :hash, true), {_TIMEOUT_SQL}"),
            {"hash": token_hash, **_timeout_param()},
        )
        yield session


@asynccontextmanager
async def ingest_config_session(webhook_id: UUID) -> AsyncIterator[AsyncSession]:
    """Read-only view of ONE ingest config: the row whose id is in the URL.

    Same doctrine as `invite_session`: the UUID was minted by us and is unguessable,
    so a session that can read exactly the row it names holds nothing new — and the
    shared-secret check still stands between that read and any effect
    (migration d41f88a2c6e9).
    """
    maker = get_sessionmaker()
    async with maker() as session, session.begin():
        await session.execute(
            text(f"SELECT set_config('app.ingest_webhook_id', :wid, true), {_TIMEOUT_SQL}"),
            {"wid": str(webhook_id), **_timeout_param()},
        )
        yield session


@asynccontextmanager
async def credential_session() -> AsyncIterator[AsyncSession]:
    """The ONLY session that can see `auth_credentials` and `auth_sessions` (D-165).

    Same doctrine as `invite_session` and `ingest_config_session` — a GUC that opens
    exactly one narrow surface — with the direction reversed. Those two WIDEN a tenant
    policy by one row; this one is the whole policy: both tables are FORCE-RLS'd with
    `USING (current_setting('app.auth', true) = 'on')`, so every other session in this
    process, including `tenant_session`, `admin_session` and the bare
    `untenanted_session`, sees zero rows.

    WHY THE PASSWORD STORE GETS A POLICY WHEN `users` DOES NOT. `users` holds an email
    address and a name; the blast radius of an over-broad query against it is a directory
    leak. These two hold password hashes and live session tokens, where the same mistake
    is platform-wide account takeover — so the default is "no", and `apps/api/authn` is
    the one package that says otherwise. It is a defence against OUR OWN future code: a
    SELECT written next year in a tenant-scoped code path cannot reach a credential,
    whatever it asks for.

    Transaction-local like every other GUC here, so a pooled connection cannot carry the
    authority into the next request.
    """
    maker = get_sessionmaker()
    async with maker() as session, session.begin():
        await session.execute(
            text(f"SELECT set_config('app.auth', 'on', true), {_TIMEOUT_SQL}"),
            _timeout_param(),
        )
        yield session


@asynccontextmanager
async def admin_session() -> AsyncIterator[AsyncSession]:
    """A session that can ENUMERATE tenants — the client directory, nothing more.

    `app.admin` widens `USING` on `organizations` only (migration b57e2f9c4a13); it
    does not unlock calls, leads or transcripts, and it widens no WITH CHECK anywhere.
    To see a client's data an admin enters that tenant through impersonation, which
    sets `app.tenant_id` normally, is read-only, and writes an `admin.impersonation_read`
    audit row from `core/auth.py::_record_impersonated_read` — the one function that can
    produce an impersonating principal, coalesced to one row per (admin, tenant) per
    minute rather than one per request (D-22, SEC-COMP §5).

    CALLERS MUST have verified an admin-realm principal first. This is the one place a
    mistake would be expensive, which is why it is a single small function with a name
    that cannot be confused for a general-purpose session.
    """
    maker = get_sessionmaker()
    async with maker() as session, session.begin():
        await session.execute(
            text(f"SELECT set_config('app.admin', 'on', true), {_TIMEOUT_SQL}"),
            _timeout_param(),
        )
        yield session


@asynccontextmanager
async def untenanted_session() -> AsyncIterator[AsyncSession]:
    """No GUC set: tenant tables yield ZERO rows. For global tables (users,
    reserved_slugs, admin_users, outbox/inbox/idempotency) and for tests proving
    the fail-closed property."""
    maker = get_sessionmaker()
    async with maker() as session, session.begin():
        # The one factory that had no `SELECT` of its own, so here the bound costs a
        # round trip rather than nothing — and this is the factory the LATENCY-CRITICAL
        # receiver uses (`apps/voice-runtime/webhook_routes.py`), so that cost was weighed
        # rather than waved through: one localhost round trip on a connection the pool
        # already holds, against a 500ms ack budget (hard rule 3) whose other bound
        # (`_DURABLE_DEADLINE_S`, 2s) can only fire on the receiver's own clock and cannot
        # stop the QUERY. It is set for the same reason the others are: a global-table
        # scan is exactly the shape that pins a connection, and "the session with no GUC"
        # must not also be the session with no bound.
        await session.execute(text(f"SELECT {_TIMEOUT_SQL}"), _timeout_param())
        yield session
