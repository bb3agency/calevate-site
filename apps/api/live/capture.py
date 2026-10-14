"""Which topics a committed transaction changed — captured where SQL is executed (D-774).

WHY AT THE CURSOR AND NOT AT EACH WRITE SITE. Most writes in this tree are hand-written
`text()` statements spread over ~40 modules (the dispatcher, the post-call pipeline,
billing's one ledger door, retention, the healer). A `notify("calls")` beside each would
be the half-wired pattern this repo forbids: the next writer forgets it and its screen
silently stops updating. Every statement, ORM flush included, passes through
`after_cursor_execute`, so the capture is here, once, and `topics.TABLE_TOPICS` is the
one list a new table has to join.

HOW A NOTE REACHES THE COMMIT, and why it can never go out for work that rolled back:

1. `after_begin` (Session) hands the connection a set owned by that session.
2. `after_cursor_execute` (Engine) adds the topic of each INSERT/UPDATE/DELETE target
   that touched at least one row. A compare-and-swap that lost (rowcount 0) adds nothing.
3. `after_commit` (Session) takes the set and schedules the publish. A rollback discards
   it (`after_soft_rollback` on the outermost transaction).

The connection's reference is dropped on its own commit/rollback and again on pool
check-in, because `Connection.info` belongs to the pooled DBAPI connection and outlives
the session.

INSTALLED BY THE API AND THE WORKERS, NOT BY `get_engine`. voice-runtime shares the engine
and writes `webhook_deliveries` on its 500 ms ack path; it must not gain a Redis round trip
per webhook (hard rule 3), and nothing it commits is a change a person is waiting to see
before the worker that ingests it commits one.

The tenant is the one `db.session.tenant_session` recorded on the session. A write with
no tenant (an untenanted or admin session) can only reach platform tables, so it goes to
the operator stream alone.
"""

from __future__ import annotations

import asyncio
import re
from functools import lru_cache
from typing import Any, Final
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session, SessionTransaction

from apps.api.db.session import LIVE_TENANT_INFO_KEY
from apps.api.live.topics import TABLE_TOPICS, Topic

#: Set on `Session.info` by `db.session.tenant_session`.
TENANT_INFO_KEY: Final = LIVE_TENANT_INFO_KEY
_PENDING: Final = "calevate_live_pending"
_SINK: Final = "calevate_live_sink"
_INSTALLED: Final = "_calevate_live_capture"
#: How long a shutting-down process waits for its last notes to reach Redis.
LIVE_DRAIN_S: Final = 2.0

# The DML target that follows the verb. `UPDATE` also matches `FOR UPDATE` and
# `DO UPDATE SET`; the word after those is never a table name in `TABLE_TOPICS`, so it is
# dropped by the lookup rather than special-cased here.
_TARGET = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:ONLY\s+)?\"?([a-z_][a-z0-9_]*)\"?",
    re.IGNORECASE,
)

#: Fire-and-forget publishes still in flight, held so the loop does not collect them.
_in_flight: set[asyncio.Task[None]] = set()


@lru_cache(maxsize=4096)
def topics_in(statement: str) -> frozenset[Topic]:
    """The topics a statement's write targets belong to. Cached: statements are mostly
    constant strings with bound parameters, so the regex runs once per distinct one."""
    found: set[Topic] = set()
    for match in _TARGET.finditer(statement):
        topic = TABLE_TOPICS.get(match.group(1).lower())
        if topic is not None:
            found.add(topic)
    return frozenset(found)


def _after_begin(
    session: Session, _transaction: SessionTransaction, connection: Connection
) -> None:
    if not getattr(connection.engine, _INSTALLED, False):
        return
    connection.info[_SINK] = session.info.setdefault(_PENDING, set())


def _after_cursor_execute(
    conn: Connection,
    cursor: Any,
    statement: str,
    _parameters: Any,
    _context: Any,
    _executemany: bool,
) -> None:
    sink = conn.info.get(_SINK)
    if sink is None:
        return
    topics = topics_in(statement)
    if not topics:
        return
    if getattr(cursor, "rowcount", -1) == 0:
        return
    sink.update(topics)


def _drop_sink(conn: Connection) -> None:
    conn.info.pop(_SINK, None)


def _drop_sink_on_checkin(_dbapi_connection: Any, record: Any) -> None:
    record.info.pop(_SINK, None)


def _after_commit(session: Session) -> None:
    pending: set[Topic] | None = session.info.pop(_PENDING, None)
    if not pending:
        return
    tenant = session.info.get(TENANT_INFO_KEY)
    schedule_publish(tenant if isinstance(tenant, UUID) else None, frozenset(pending))


def _after_soft_rollback(session: Session, previous: SessionTransaction) -> None:
    if previous.parent is None:
        session.info.pop(_PENDING, None)


def schedule_publish(tenant_id: UUID | None, topics: frozenset[Topic]) -> None:
    """Hand the notes to the publisher without waiting for it.

    Called from `after_commit`, a synchronous hook running inside the commit's await, so
    the publish is a task on the running loop. No loop (a synchronous script) means no
    browser is waiting on this process, and the note is dropped.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    from apps.api.live.publish import publish_changes

    task = loop.create_task(publish_changes(tenant_id, topics))
    _in_flight.add(task)
    task.add_done_callback(_in_flight.discard)


async def drain_in_flight() -> None:
    """Wait for every scheduled publish. For tests and for a graceful shutdown."""
    while _in_flight:
        await asyncio.gather(*list(_in_flight), return_exceptions=True)


def install_change_capture(engine: AsyncEngine) -> None:
    """Attach the capture to the process's engine. Idempotent."""
    sync: Engine = engine.sync_engine
    if getattr(sync, _INSTALLED, False):
        return
    setattr(sync, _INSTALLED, True)
    event.listen(sync, "after_cursor_execute", _after_cursor_execute)
    event.listen(sync, "commit", _drop_sink)
    event.listen(sync, "rollback", _drop_sink)
    event.listen(sync.pool, "checkin", _drop_sink_on_checkin)
    if not event.contains(Session, "after_begin", _after_begin):
        event.listen(Session, "after_begin", _after_begin)
        event.listen(Session, "after_commit", _after_commit)
        event.listen(Session, "after_soft_rollback", _after_soft_rollback)


__all__ = [
    "LIVE_DRAIN_S",
    "TENANT_INFO_KEY",
    "drain_in_flight",
    "install_change_capture",
    "schedule_publish",
    "topics_in",
]
