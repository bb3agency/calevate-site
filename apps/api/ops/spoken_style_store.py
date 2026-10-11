"""The founder's spoken-style review: the working copy, publishing, and the published layer
every process installs into `calevate_shared.spoken_style` (D-744).

Two append-only tables (`ops/models.SpokenStyleRevision`, `SpokenStylePublication`). The
working copy of an entry is its latest revision; what agents read is, per language, the
revisions up to the latest publication's `through_revision`, layered over the file.

HOW THE PUBLISHED LAYER REACHES A PROMPT. `calevate_shared` cannot import this, and the
prompt is composed synchronously, so each process holds the layer in memory and refreshes it
off the request path: `refresh_spoken_style` rides `ops/pricing_snapshot`'s 30-second poll,
which the API and the worker both start, and it reads one integer (the newest publication)
before deciding whether to read anything else. The live-apply walk calls it before it
publishes (`apps/workers/live_apply.apply_live_settings`), so a publish never reaches
agents with the previous words, and the publishing route refreshes its own process after
commit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from calevate_shared.spoken_style import (
    PublishedEntry,
    PublishedLanguage,
    install_published,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.plans import IST
from apps.api.core.logging import get_logger
from apps.api.db.session import untenanted_session

log = get_logger(__name__)

#: How many publications the review screen lists per language.
HISTORY_LIMIT = 10

#: The newest publication this process installed, or None before the first read.
_installed: int | None = None


@dataclass(frozen=True, slots=True)
class Revision:
    seq: int
    kind: str
    key: str
    value: dict[str, Any] | None
    approved: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Publication:
    seq: int
    language: str
    through_revision: int
    reviewer_name: str
    note: str | None
    published_at: datetime
    #: The admin account that pressed publish (the reviewer may be someone else).
    published_by: UUID

    @property
    def reviewed_on(self) -> str:
        """The IST date of publishing, the stamp's date."""
        return self.published_at.astimezone(IST).date().isoformat()


_LATEST_PER_ENTRY = (
    "SELECT DISTINCT ON (kind, entry_key) seq, kind, entry_key, value, approved, created_at "
    "FROM spoken_style_revisions WHERE language = :language "
    "AND (CAST(:through AS bigint) IS NULL OR seq <= CAST(:through AS bigint)) "
    "ORDER BY kind, entry_key, seq DESC"
)


async def entry_states(
    session: AsyncSession, *, language: str, through: int | None = None
) -> dict[tuple[str, str], Revision]:
    """The latest revision of each entry of a language, up to `through` when given (the
    published state) or all of them (the working copy)."""
    rows = (
        await session.execute(text(_LATEST_PER_ENTRY), {"language": language, "through": through})
    ).all()
    return {
        (str(r[1]), str(r[2])): Revision(
            seq=int(r[0]),
            kind=str(r[1]),
            key=str(r[2]),
            value=dict(r[3]) if r[3] is not None else None,
            approved=bool(r[4]),
            created_at=r[5],
        )
        for r in rows
    }


def _publication(row: Any) -> Publication:
    return Publication(
        seq=int(row[0]),
        language=str(row[1]),
        through_revision=int(row[2]),
        reviewer_name=str(row[3]),
        note=row[4],
        published_at=row[5],
        published_by=row[6],
    )


_PUBLICATION_COLUMNS = (
    "seq, language, through_revision, reviewer_name, note, published_at, published_by"
)


async def latest_publications(session: AsyncSession) -> dict[str, Publication]:
    """The newest publication of every language that has one."""
    rows = (
        await session.execute(
            text(
                f"SELECT DISTINCT ON (language) {_PUBLICATION_COLUMNS} "
                "FROM spoken_style_publications ORDER BY language, seq DESC"
            )
        )
    ).all()
    return {str(r[1]): _publication(r) for r in rows}


async def publication_history(session: AsyncSession, *, language: str) -> list[Publication]:
    rows = (
        await session.execute(
            text(
                f"SELECT {_PUBLICATION_COLUMNS} FROM spoken_style_publications "
                "WHERE language = :language ORDER BY seq DESC LIMIT :limit"
            ),
            {"language": language, "limit": HISTORY_LIMIT},
        )
    ).all()
    return [_publication(r) for r in rows]


async def last_revision(session: AsyncSession, *, language: str) -> int:
    """The newest revision of a language, 0 when it has none."""
    value = (
        await session.execute(
            text(
                "SELECT coalesce(max(seq), 0) FROM spoken_style_revisions "
                "WHERE language = :language"
            ),
            {"language": language},
        )
    ).scalar()
    return int(value or 0)


async def add_revision(
    session: AsyncSession,
    *,
    language: str,
    kind: str,
    key: str,
    value: dict[str, Any] | None,
    approved: bool,
    actor_id: Any,
) -> int:
    seq = (
        await session.execute(
            text(
                "INSERT INTO spoken_style_revisions "
                "(language, kind, entry_key, value, approved, created_by) "
                "VALUES (:language, :kind, :key, CAST(:value AS jsonb), :approved, :by) "
                "RETURNING seq"
            ),
            {
                "language": language,
                "kind": kind,
                "key": key,
                "value": None if value is None else _json(value),
                "approved": approved,
                "by": actor_id,
            },
        )
    ).scalar_one()
    return int(seq)


async def add_publication(
    session: AsyncSession,
    *,
    language: str,
    through_revision: int,
    reviewer_name: str,
    note: str | None,
    actor_id: Any,
) -> Publication:
    row = (
        await session.execute(
            text(
                "INSERT INTO spoken_style_publications "
                "(language, through_revision, reviewer_name, note, published_by) "
                "VALUES (:language, :through, :reviewer, :note, :by) "
                f"RETURNING {_PUBLICATION_COLUMNS}"
            ),
            {
                "language": language,
                "through": through_revision,
                "reviewer": reviewer_name,
                "note": note,
                "by": actor_id,
            },
        )
    ).one()
    return _publication(row)


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


async def published_layer(session: AsyncSession) -> dict[str, PublishedLanguage]:
    """Every language's published layer, as `spoken_style.install_published` takes it."""
    layer: dict[str, PublishedLanguage] = {}
    for language, publication in (await latest_publications(session)).items():
        states = await entry_states(
            session, language=language, through=publication.through_revision
        )
        layer[language] = PublishedLanguage(
            entries={
                key: PublishedEntry(value=state.value, approved=state.approved)
                for key, state in states.items()
            },
            reviewed_by=publication.reviewer_name,
            reviewed_on=publication.reviewed_on,
        )
    return layer


async def refresh_spoken_style() -> None:
    """Install the newest published layer in this process if it changed. Never raises: a
    store this process cannot read keeps the layer already installed (the file alone on a
    cold start), and the failure is logged."""
    global _installed
    try:
        async with untenanted_session() as session:
            newest = int(
                (
                    await session.execute(
                        text("SELECT coalesce(max(seq), 0) FROM spoken_style_publications")
                    )
                ).scalar()
                or 0
            )
            if newest == _installed:
                return
            layer = await published_layer(session)
    except Exception as exc:
        log.error("spoken_style_refresh_failed", extra={"reason": type(exc).__name__})
        return
    install_published(layer)
    _installed = newest
    log.info("spoken_style_installed", extra={"publication": newest, "languages": len(layer)})


def reset_for_test() -> None:
    """Forget what was installed, so the next refresh reads the store again."""
    global _installed
    _installed = None
    install_published(None)


__all__ = [
    "HISTORY_LIMIT",
    "Publication",
    "Revision",
    "add_publication",
    "add_revision",
    "entry_states",
    "last_revision",
    "latest_publications",
    "publication_history",
    "published_layer",
    "refresh_spoken_style",
    "reset_for_test",
]
