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
    """
    global _engine, _sessionmaker
    if _engine is None:
        cfg = settings or Settings()  # env-sourced
        _engine = create_async_engine(
            cfg.database_url,
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
async def admin_session() -> AsyncIterator[AsyncSession]:
    """A session that can ENUMERATE tenants — the client directory, nothing more.

    `app.admin` widens `USING` on `organizations` only (migration b57e2f9c4a13); it
    does not unlock calls, leads or transcripts, and it widens no WITH CHECK anywhere.
    To see a client's data an admin enters that tenant through impersonation, which
    sets `app.tenant_id` normally, is read-only and is audited per page view (D-22).

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
