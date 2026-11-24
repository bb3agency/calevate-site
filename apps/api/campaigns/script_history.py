"""Every saved version of a campaign's or inbound line's script (D-1039).

Each write of a holder's script records a row in `script_versions` in the same transaction:
the script, who wrote it (`Author`), a short reason and when. "Put back the flow from before
Pip" restores the newest version the owner made (`owner_made`), not the script as it stood
before the last write: the automatic passes (script repair, step outcomes, the notice weave)
each save a small edit, and a single switch-back copy taken before each of them held a script
almost identical to the one on screen, so putting it back changed nothing visible.

A restore is saved through the holder's own Save with author `restored`, so it is a version
too and can be undone from the list. It inherits `owner_made` from the version it brings back,
which keeps "put back" pointing at the owner's own script after a restore.

The history is bounded at `KEEP` rows per holder, and the newest owner-made row is never
pruned, so a long run of automatic edits cannot push the owner's script out of reach.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import CallScript
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.plans import IST
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

HolderKind = Literal["campaign", "line"]
Author = Literal[
    "owner",
    "pip_draft",
    "pip_repair",
    "pip_outcomes",
    "pip_notices",
    "system",
    "restored",
    "copied",
    "earlier",
]
#: Rows kept per holder, the newest owner-made one always among them.
KEEP: Final = 30
REASON_MAX: Final = 200

_REASONS: Final[dict[Author, str]] = {
    "owner": "You saved the script.",
    "pip_draft": "You kept a script Pip wrote.",
    "pip_repair": "Pip repaired lines the script checks found.",
    "pip_outcomes": "Pip wrote the outcome of steps that had none.",
    "pip_notices": "Pip added the notices to the opening line.",
    "system": "Updated to match the agent.",
    "restored": "You put back an earlier version.",
    "copied": "Copied from another campaign.",
    "earlier": "The script as it was when versions began.",
}


#: The rules a whole-script rewrite by Pip is written under (founder, 25 Nov 2026: once the
#: fixed writer ships, every script Pip wrote and the owner has not edited since is rewritten
#: under the new rules). A later change of the rules names a new value, which makes the
#: scripts Pip still owns eligible again.
REWRITE_RULES: Final = "2026-11-25"
#: What the version a rewrite saves says, as a `pip_draft`: Pip wrote the script.
REWRITE_REASON: Final = "Pip rewrote its script under the script rules of 25 Nov 2026."
#: The versions an owner's action made: their save, a version they put back, a script they
#: copied in. Any of them after Pip's last whole script means the script is the owner's.
_OWNER_ACTIONS: Final = ("owner", "restored", "copied")


async def pip_owns(session: AsyncSession, kind: HolderKind, holder_id: UUID) -> bool:
    """Whether the holder's script is still the one Pip wrote: a `pip_draft` version is on
    file and nothing the owner did comes after the newest one (`owner_made`, or an owner's
    action in `_OWNER_ACTIONS`). Pip's own automatic passes after it (`pip_repair`,
    `pip_outcomes`, `pip_notices`) and a sync to the agent (`system`) keep it Pip's.

    A script older than the history has only an `earlier` row, which says nothing about who
    wrote it, so it is never Pip's here: rewriting an owner's script unasked is the costly
    mistake, and such a script still gets the automatic line repairs (`agents/script_heal`)."""
    column = _holder_column(kind)
    return bool(
        (
            await session.execute(
                text(
                    f"WITH last AS (SELECT created_at, id FROM script_versions "
                    f"WHERE {column} = :h AND author = 'pip_draft' "
                    "ORDER BY created_at DESC, id DESC LIMIT 1) "
                    "SELECT EXISTS (SELECT 1 FROM last) AND NOT EXISTS ("
                    f"SELECT 1 FROM script_versions v, last WHERE v.{column} = :h "
                    "AND (v.created_at, v.id) > (last.created_at, last.id) "
                    "AND (v.owner_made OR v.author = ANY(:owner)))"
                ),
                {"h": holder_id, "owner": list(_OWNER_ACTIONS)},
            )
        ).scalar()
    )


def _holder_column(kind: HolderKind) -> str:
    """The holder's column, as a conditional of literals so `scripts/check_raw_sql.py` can
    read it."""
    return "campaign_id" if kind == "campaign" else "inbound_line_id"


@dataclass(frozen=True)
class Version:
    id: UUID
    author: Author
    owner_made: bool
    reason: str
    created_at: datetime
    restored_from: UUID | None


@dataclass(frozen=True)
class PutBack:
    """What "Put back the flow from before Pip" would restore, or why it cannot."""

    #: The newest version on file, which a restore names for its compare-and-set.
    current_version_id: UUID | None
    #: The owner's own last version to bring back; None when `unavailable` says why.
    version: Version | None
    #: `no_owner_version`: nothing the owner saved is on file. `already_current`: the
    #: owner's last version is the script now.
    unavailable: Literal["no_owner_version", "already_current"] | None


def _version(row: Any) -> Version:
    return Version(
        id=row.id,
        author=row.author,
        owner_made=row.owner_made,
        reason=row.reason,
        created_at=row.created_at,
        restored_from=row.restored_from,
    )


_COLUMNS: Final = "id, author, owner_made, reason, created_at, restored_from"


async def record(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    kind: HolderKind,
    holder_id: UUID,
    script: CallScript,
    author: Author,
    made_by: UUID | None = None,
    reason: str | None = None,
    restored_from: UUID | None = None,
    owner_made: bool | None = None,
) -> UUID:
    """Keep this save as a version and prune the holder's history to `KEEP`. Called by every
    writer of a holder's script, inside the transaction that writes it. `owner_made` defaults
    from the author; a restore takes it from the version it brings back."""
    column = _holder_column(kind)
    if owner_made is None:
        if author == "restored" and restored_from is not None:
            owner_made = bool(
                (
                    await session.execute(
                        text("SELECT owner_made FROM script_versions WHERE id = :v"),
                        {"v": restored_from},
                    )
                ).scalar()
            )
        else:
            owner_made = author == "owner"
    version_id = uuid7()
    await session.execute(
        text(
            f"INSERT INTO script_versions (id, tenant_id, {column}, script, author, owner_made, "
            "reason, made_by, restored_from, created_at) VALUES (:id, :t, :h, CAST(:s AS jsonb), "
            ":a, :o, :r, :by, :from, clock_timestamp())"
        ),
        {
            "id": version_id,
            "t": tenant_id,
            "h": holder_id,
            "s": script.model_dump_json(),
            "a": author,
            "o": owner_made,
            "r": (reason or _REASONS[author])[:REASON_MAX],
            "by": made_by,
            "from": restored_from,
        },
    )
    await session.execute(
        text(
            f"DELETE FROM script_versions WHERE {column} = :h AND id NOT IN ("
            f"SELECT id FROM script_versions WHERE {column} = :h "
            "ORDER BY created_at DESC, id DESC LIMIT :keep) "
            f"AND id IS DISTINCT FROM (SELECT id FROM script_versions WHERE {column} = :h "
            "AND owner_made ORDER BY created_at DESC, id DESC LIMIT 1)"
        ),
        {"h": holder_id, "keep": KEEP},
    )
    return version_id


async def versions(session: AsyncSession, kind: HolderKind, holder_id: UUID) -> list[Version]:
    """The holder's versions, newest first, at most `KEEP` + 1."""
    column = _holder_column(kind)
    rows = await session.execute(
        text(
            f"SELECT {_COLUMNS} FROM script_versions WHERE {column} = :h "
            "ORDER BY created_at DESC, id DESC LIMIT :n"
        ),
        {"h": holder_id, "n": KEEP + 1},
    )
    return [_version(row) for row in rows]


async def put_back(
    session: AsyncSession, kind: HolderKind, holder_id: UUID, current: CallScript | None
) -> PutBack:
    column = _holder_column(kind)
    latest = (
        await session.execute(
            text(
                f"SELECT id FROM script_versions WHERE {column} = :h "
                "ORDER BY created_at DESC, id DESC LIMIT 1"
            ),
            {"h": holder_id},
        )
    ).scalar()
    own = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS}, script FROM script_versions WHERE {column} = :h "
                "AND owner_made ORDER BY created_at DESC, id DESC LIMIT 1"
            ),
            {"h": holder_id},
        )
    ).first()
    if own is None:
        return PutBack(current_version_id=latest, version=None, unavailable="no_owner_version")
    if current is not None and CallScript.model_validate(own.script) == current:
        return PutBack(current_version_id=latest, version=None, unavailable="already_current")
    return PutBack(current_version_id=latest, version=_version(own), unavailable=None)


async def script_to_restore(
    session: AsyncSession,
    kind: HolderKind,
    holder_id: UUID,
    *,
    version_id: UUID | None,
    expected_version_id: UUID | None,
    current: CallScript | None,
) -> tuple[CallScript, Version]:
    """The script a restore of `version_id` saves (None: the owner's own last version),
    checked under the holder's row lock the caller holds: refused when another save landed
    since the page read the history (the compare-and-set) and when it is already the
    script, so a put-back never reports a change it did not make."""
    column = _holder_column(kind)
    if version_id is None:
        target = await put_back(session, kind, holder_id, current)
        if target.version is None:
            raise nothing_to_put_back(target.unavailable)
        version_id = target.version.id
    latest = (
        await session.execute(
            text(
                f"SELECT id FROM script_versions WHERE {column} = :h "
                "ORDER BY created_at DESC, id DESC LIMIT 1"
            ),
            {"h": holder_id},
        )
    ).scalar()
    if latest != expected_version_id:
        raise ProblemError.conflict(
            "script_changed",
            "The script changed since you opened it.",
            remediation="Look at the versions again, then put one back.",
        )
    held = (
        await session.execute(
            text(f"SELECT {_COLUMNS}, script FROM script_versions WHERE id = :v AND {column} = :h"),
            {"v": version_id, "h": holder_id},
        )
    ).first()
    if held is None:
        raise ProblemError.not_found("Version")
    script = CallScript.model_validate(held.script)
    if current is not None and script == current:
        raise ProblemError.conflict(
            "script_version_is_current",
            "That version is the script you have now.",
            remediation="Nothing needs putting back.",
        )
    return script, _version(held)


def nothing_to_put_back(unavailable: str | None) -> ProblemError:
    detail = (
        "This is already your own last version."
        if unavailable == "already_current"
        else "There is no version you saved yourself to put back."
    )
    return ProblemError.conflict(
        "nothing_to_put_back", detail, remediation="Open Versions to pick another one."
    )


def restored_reason(at: datetime) -> str:
    """The reason a restore records: which version came back, its time in IST."""
    return f"You put back the version from {at.astimezone(IST).strftime('%d %b, %H:%M')}."


class ScriptVersionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    author: Author
    #: The owner's own script (their save, or one of theirs put back).
    owner_made: bool
    reason: str
    created_at: datetime


class ScriptPutBackOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The version "put back" restores; null when `unavailable` says why it cannot.
    version: ScriptVersionOut | None
    unavailable: Literal["no_owner_version", "already_current"] | None


class ScriptVersionsOut(BaseModel):
    """A campaign's or line's script versions, newest first (at most `KEEP` + 1), and what
    "Put back the flow from before Pip" would restore."""

    model_config = ConfigDict(extra="forbid")
    #: The newest version, which a restore sends back as `expected_version_id`.
    current_version_id: UUID | None
    put_back: ScriptPutBackOut
    versions: list[ScriptVersionOut]


class ScriptRestoreIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: `current_version_id` as the page read it: a save since then refuses the restore.
    expected_version_id: UUID | None


def _version_out(v: Version) -> ScriptVersionOut:
    return ScriptVersionOut(
        id=v.id, author=v.author, owner_made=v.owner_made, reason=v.reason, created_at=v.created_at
    )


async def versions_out(
    session: AsyncSession, kind: HolderKind, holder_id: UUID, current: CallScript | None
) -> ScriptVersionsOut:
    target = await put_back(session, kind, holder_id, current)
    return ScriptVersionsOut(
        current_version_id=target.current_version_id,
        put_back=ScriptPutBackOut(
            version=None if target.version is None else _version_out(target.version),
            unavailable=target.unavailable,
        ),
        versions=[_version_out(v) for v in await versions(session, kind, holder_id)],
    )


__all__ = [
    "KEEP",
    "REWRITE_REASON",
    "REWRITE_RULES",
    "Author",
    "HolderKind",
    "PutBack",
    "ScriptPutBackOut",
    "ScriptRestoreIn",
    "ScriptVersionOut",
    "ScriptVersionsOut",
    "Version",
    "nothing_to_put_back",
    "pip_owns",
    "put_back",
    "record",
    "restored_reason",
    "script_to_restore",
    "versions",
    "versions_out",
]
