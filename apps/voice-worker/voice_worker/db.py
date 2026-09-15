"""The container's ONE database engine, and the tenant-scoped connections it hands out.

**WHY THIS MODULE EXISTS AT ALL, IN ONE SENTENCE.** `config.load_session_config` takes an
`AsyncConnection` and owns no engine, and its docstring says why in the form of a promise:
*"one process wants ONE pool sized against ONE workload. So the engine belongs with the
container entrypoint that owns both"* — both being the config read and the
`NormalizedEventSink` writer. This is that engine, and `runtime.py` is that entrypoint.
Building a second one inside `sink.py` would give one container two pools against one
Postgres, sized by nobody, and would make "how many connections does a call hold" a
question with two answers.

**WHY IT IS NOT `apps/api/db/session.py`, WHICH ALREADY OWNS EXACTLY THIS.** That module
is shared by `apps/api`, `apps/workers` and `apps/voice-runtime` and says so — but it
imports `apps.api.core.settings`, i.e. the monolith's settings loader, its platform-config
store and everything those reach. This worker's whole dependency argument is that it does
NOT carry the monolith into a voice container (`pyproject.toml`; `storage.py` makes the
same call about `apps/workers/storage.py`, and `embedding.py` about the vendor SDKs). So
the duplication is one `create_async_engine` call and one GUC statement, deliberately, and
the parts of that module's reasoning that are load-bearing here are cited at each option
below rather than re-derived.

**HARD RULE 1 LIVES IN `tenant_connection` AND NOWHERE ELSE IN THIS DEPLOYABLE.** There is
no untenanted accessor here on purpose: this worker has no cross-tenant question to ask —
it runs ONE call for ONE tenant — so an untenanted connection could only ever be a mistake,
and the cheapest way to prevent that mistake is to not offer it.

**HARD RULE 6.** `hide_parameters=True` is not a preference, it is the control that stops a
DBAPI error from rendering a transcript turn into an exception string. See
`apps/api/db/session.get_engine`, which argues it at length for the identical statement —
`INSERT INTO transcript_turns ...` — reached from the identical direction.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

#: The DSN, read from the process environment under the spelling every deploy already uses
#: (`.env.example`, `DATABASE_URL` — the APP role, `NOSUPERUSER NOBYPASSRLS`, because RLS
#: depends on the role not being able to bypass it). Named here rather than typed at the
#: call site for `storage.BUCKET_ENV`'s reason: a rename is one edit and a typo is one
#: failure instead of a silent read of `None`.
DATABASE_URL_ENV: Final[str] = "DATABASE_URL"

#: Connections this container keeps open. **FOUR, AND THE NUMBER IS DERIVED FROM THE
#: WORKLOAD RATHER THAN COPIED FROM THE MONOLITH'S SIXTEEN.**
#:
#: A container runs ONE call (`pipeline.py` sets `idle_timeout_secs=None` and reasons about
#: "one-worker-per-call"). Its simultaneous holders are: the session-start config read,
#: which is finished before the pipeline exists, and `sink.DatabaseEventSink`, whose writes
#: are serialized behind one lock so it holds at most one. Two would therefore do; four is
#: the same number with room for a second concurrent call if Pipecat Cloud ever packs two
#: into a container, and it is small enough that a hundred containers cannot exhaust a
#: Postgres the monolith is also using.
POOL_SIZE: Final[int] = 4

#: No burst valve. `apps/api/db/session.py` keeps exactly one overflow slot because fifty
#: of its functions legitimately hold two connections at once and a full pool of those
#: self-deadlocks. Nothing here holds two — the sink's lock is what guarantees it — so an
#: overflow slot could only hand out SINGLE-USE connections (the pool closes them on
#: return), which is the re-authentication treadmill that module measured at 186 fresh
#: backends for 1448 requests. A caller past the ceiling waits on the pool's own queue.
MAX_OVERFLOW: Final[int] = 0

#: How long a caller may wait for a pooled connection before being told there is none.
#: `apps/api/db/session._POOL_TIMEOUT_S`'s value, because it is the same doctrine and two
#: numbers for one question is the drift the quality bar refuses.
POOL_TIMEOUT_S: Final[float] = 5.0

#: Socket-level bounds. Copied as a SET from `apps/api/db/session._CONNECT_ARGS`, whose
#: comment derives every one of them, because the failure they exist for is the one this
#: container is MOST exposed to and not least: box 1 is Pipecat Cloud `ap-south` and the
#: database is on box 2 (`docs/PIPECAT-MIGRATION.md` §8), so every statement here crosses a
#: network that a dropped NAT mapping can blackhole — a socket accepted and then never
#: answered, which no `asyncio.timeout` in this process bounds because the unwind runs
#: after the cancellation has already been delivered.
_CONNECT_ARGS: Final[dict[str, int]] = {
    "connect_timeout": 2,
    "tcp_user_timeout": 5000,
    "keepalives": 1,
    "keepalives_idle": 2,
    "keepalives_interval": 1,
    "keepalives_count": 3,
}

#: DATA-MODEL §1 verbatim, as every migration in this repo spells it. `true` makes the GUC
#: TRANSACTION-local, so it auto-clears at commit and a pooled connection cannot carry one
#: tenant's context into the next call's transaction.
_SET_TENANT_SQL: Final = "SELECT set_config('app.tenant_id', :tid, true)"


class DatabaseNotConfiguredError(RuntimeError):
    """The container has no database to write to. A deploy fault, and it fails at startup.

    Raised where the engine is BUILT rather than where a row is written, on
    `storage.ObjectStoreNotConfiguredError`'s pattern and for its reason: a misconfigured
    container should be a startup failure somebody sees, not a call that answers the phone
    and then silently records nothing that happened on it.
    """


class WorkerDatabase:
    """One engine, one pool, for the life of the container.

    Constructed by `runtime.py` and handed to everything that needs a row. It is a class
    rather than module-level globals for `session.pack_cache`'s reason inverted: the pack
    cache is process state that a test must be able to see, and this is process state a
    test must be able to REPLACE — a module-level engine would connect to whatever
    `DATABASE_URL` the test runner happened to export, at import time, from every test that
    imports the sink.
    """

    def __init__(self, url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(
            url,
            pool_size=POOL_SIZE,
            max_overflow=MAX_OVERFLOW,
            pool_timeout=POOL_TIMEOUT_S,
            # One round trip per checkout, and what it buys is that a connection severed by
            # an idle NAT surfaces as a reconnect instead of as a lost transcript turn on a
            # call already in progress. The monolith's engine makes the same trade and its
            # `get_engine` measures the cost.
            pool_pre_ping=True,
            # HARD RULE 6. See the module docstring.
            hide_parameters=True,
            connect_args=dict(_CONNECT_ARGS),
        )

    @classmethod
    def from_env(cls) -> WorkerDatabase:
        """The production constructor. Raises when the container was deployed without a DSN."""
        url = os.environ.get(DATABASE_URL_ENV)
        if not url:
            raise DatabaseNotConfiguredError(
                f"{DATABASE_URL_ENV} is unset, so this worker can record nothing about a call"
            )
        return cls(url)

    @property
    def engine(self) -> AsyncEngine:
        """The engine itself, for a caller that needs to say something about the pool."""
        return self._engine

    @asynccontextmanager
    async def tenant_connection(self, tenant_id: UUID) -> AsyncIterator[AsyncConnection]:
        """A connection whose whole transaction runs under this tenant's RLS context.

        `AsyncConnection` and not `AsyncSession`, which is the one shape decision here:
        `config.load_session_config` already takes a connection, this worker owns no ORM
        models (every statement it issues is `text()` against tables `apps/api` declares),
        and a Session would add an identity map and a flush order to a process whose whole
        database interaction is six INSERTs.

        The transaction commits on a clean exit and rolls back on an exception, which is
        what makes a half-written settlement impossible: `sink.settle` writes its rows
        inside ONE of these.
        """
        async with self._engine.begin() as connection:
            await connection.execute(text(_SET_TENANT_SQL), {"tid": str(tenant_id)})
            yield connection

    async def aclose(self) -> None:
        """Return every pooled connection. Idempotent, and it does NOT swallow.

        Called from `runtime.py`'s shutdown AFTER the pipeline has drained, never during
        it — disposing a pool a live call is still writing through is how a settled row
        becomes a lost one.

        **THE `try/except` THAT USED TO BE HERE IS GONE, DELIBERATELY.** It logged and
        continued, which is "never swallow an exception to make a path look green" written
        the wrong way round: a dispose that fails at shutdown has no retry, no caller that
        can act, and nothing left to protect — so the honest behaviour is to let it out,
        where the process's own exit reports it. It was also an arm nothing could reach,
        i.e. a permanent `# pragma: no cover` on a hard-rule-1 surface whose coverage budget
        is zero, which is the ratchet telling the same thing in the other language.
        """
        await self._engine.dispose()


__all__ = [
    "DATABASE_URL_ENV",
    "MAX_OVERFLOW",
    "POOL_SIZE",
    "POOL_TIMEOUT_S",
    "DatabaseNotConfiguredError",
    "WorkerDatabase",
]
