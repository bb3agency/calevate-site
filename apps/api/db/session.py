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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from calevate_shared.config import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

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

#: The most pooled connections ONE task may hold at the same time (D-182).
#:
#: Two, and every one of the two is a deliberate design: a request's session plus the
#: short global read something inside it makes (`loadshed._read_durable` behind
#: `check_dispatch`), or the outbox dispatcher's session plus the claim that must commit
#: on its own connection. `get_engine` turns this into `max_overflow` and
#: `scripts/check_session_nesting.py` refuses a third level, so the pool's capacity and
#: the code's shape cannot drift apart the way they had.
MAX_NESTED_CONNECTIONS = 2


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
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
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
            text("SELECT set_config('app.user_id', :uid, true)"),
            {"uid": str(user_id)},
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
            text("SELECT set_config('app.invite_hash', :hash, true)"), {"hash": token_hash}
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
            text("SELECT set_config('app.ingest_webhook_id', :wid, true)"),
            {"wid": str(webhook_id)},
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
        await session.execute(text("SELECT set_config('app.auth', 'on', true)"))
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
        await session.execute(text("SELECT set_config('app.admin', 'on', true)"))
        yield session


@asynccontextmanager
async def untenanted_session() -> AsyncIterator[AsyncSession]:
    """No GUC set: tenant tables yield ZERO rows. For global tables (users,
    reserved_slugs, admin_users, outbox/inbox/idempotency) and for tests proving
    the fail-closed property."""
    maker = get_sessionmaker()
    async with maker() as session, session.begin():
        yield session
