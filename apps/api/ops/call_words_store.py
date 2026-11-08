"""The founder's edits to the words the call checks listen for (G-C2), and the refresh that
installs them into `calevate_shared.call_words` in every API and worker process.

One append-only table (`ops/models.CallWordRevision`). The newest revision of each entry is
in force; a NULL value puts the shipped entry back. `version()` is the row count with the
newest `seq`.

HOW AN EDIT REACHES A RUNNING CHECK. `calevate_shared` cannot import this, and the checks run
synchronously inside the post-call pipeline, so each process holds the entries in memory and
refreshes them off the request path: `refresh_call_words` rides `ops/pricing_snapshot`'s
30-second poll, which the API and the worker both start, and reads `version()` before
deciding whether to read anything else. `call_words.install` then bumps the
process's generation, and each check's `Live` rebuilds its pattern the next time it is used.
The saving route also refreshes its own process after commit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from calevate_shared import call_words
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.logging import get_logger
from apps.api.db.session import untenanted_session

log = get_logger(__name__)

#: How many past revisions the editor shows for one entry.
HISTORY_LIMIT = 20

#: The `version()` this process installed, or None before the first read.
_installed: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class Revision:
    seq: int
    key: str
    #: None when this revision put the shipped entry back.
    value: Any
    note: str | None
    created_by: UUID
    created_at: datetime


_COLUMNS = "seq, entry_key, value, note, created_by, created_at"


def _revision(row: Any) -> Revision:
    return Revision(
        seq=int(row[0]),
        key=str(row[1]),
        value=row[2],
        note=row[3],
        created_by=row[4],
        created_at=row[5],
    )


async def latest(session: AsyncSession) -> dict[str, Revision]:
    """The newest revision of every entry that has one."""
    rows = (
        await session.execute(
            text(
                f"SELECT DISTINCT ON (entry_key) {_COLUMNS} FROM call_word_revisions "
                "ORDER BY entry_key, seq DESC"
            )
        )
    ).all()
    return {str(r[1]): _revision(r) for r in rows}


async def history(session: AsyncSession, *, key: str) -> list[Revision]:
    rows = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM call_word_revisions WHERE entry_key = :key "
                "ORDER BY seq DESC LIMIT :limit"
            ),
            {"key": key, "limit": HISTORY_LIMIT},
        )
    ).all()
    return [_revision(r) for r in rows]


async def version(session: AsyncSession) -> tuple[int, int]:
    """`(revisions, newest seq)`, `(0, 0)` when nothing was ever edited.

    The newest `seq` alone is not a version: an identity value is taken at INSERT, so a save
    holding seq 5 can commit after one holding seq 6, and a process that installed at 6
    would never see 5. The table is append-only, so every committed save moves the count.
    """
    row = (
        await session.execute(
            text("SELECT count(*), coalesce(max(seq), 0) FROM call_word_revisions")
        )
    ).one()
    return int(row[0]), int(row[1])


async def add_revision(
    session: AsyncSession, *, key: str, value: Any, note: str | None, actor_id: UUID
) -> Revision:
    row = (
        await session.execute(
            text(
                "INSERT INTO call_word_revisions (entry_key, value, note, created_by) "
                "VALUES (:key, CAST(:value AS jsonb), :note, :by) "
                f"RETURNING {_COLUMNS}"
            ),
            {
                "key": key,
                "value": None if value is None else json.dumps(value, ensure_ascii=False),
                "note": note,
                "by": actor_id,
            },
        )
    ).one()
    return _revision(row)


def overrides(revisions: dict[str, Revision]) -> dict[str, Any]:
    """The entries the console holds in place of the file's."""
    return {key: r.value for key, r in revisions.items() if r.value is not None}


async def refresh_call_words() -> None:
    """Install the newest entries in this process if they changed. Never raises: a store this
    process cannot read keeps what is installed (the file alone on a cold start), and the
    failure is logged."""
    global _installed
    try:
        async with untenanted_session() as session:
            newest = await version(session)
            if newest == _installed:
                return
            entries = overrides(await latest(session))
    except Exception as exc:
        log.error("call_words_refresh_failed", extra={"error": type(exc).__name__})
        return
    call_words.install(entries)
    _installed = newest
    log.info(
        "call_words_installed",
        extra={"revision": newest[1], "revisions": newest[0], "entries": len(entries)},
    )


def reset_for_test() -> None:
    """Forget what was installed, so the next refresh reads the store again."""
    global _installed
    _installed = None
    call_words.install(None)


__all__ = [
    "HISTORY_LIMIT",
    "Revision",
    "add_revision",
    "history",
    "latest",
    "overrides",
    "refresh_call_words",
    "reset_for_test",
    "version",
]
