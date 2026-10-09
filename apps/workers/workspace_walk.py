"""Walk every ThinnestAI workspace a sweep has to read: bounded, and resumable (D-693).

Each client's agents, calls, numbers and charges live in its own customer workspace, and a
vendor listing answers for one workspace only, so every reconciliation that used to read
"the account" now reads each workspace in turn: our developer workspace first (objects made
before D-693 live there until their next publish recreates them), then the active customer
workspaces.

BOUNDED: one tick visits at most `budget` customer workspaces, so a growing client list
cannot turn a sweep into an unbounded fan-out against the vendor's rate limit.

RESUMABLE: the last customer workspace a sweep finished is kept in Redis per sweep, and the
next tick starts after it, wrapping round. A tick cut short (a deploy, a crash) resumes where
it stopped instead of re-reading the same head of the list for ever. Redis is a hint here,
never a record: a lost cursor restarts the rotation from the first tenant and skips nothing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.tenancy.engine_workspace import WorkspaceRow, active_workspaces

log = get_logger(__name__)

#: Customer workspaces one tick of a sweep visits. Each visit is one to a few vendor
#: listings; at the plan caps (3 on pay-as-you-go, 100 on Pro) a tick covers every client.
DEFAULT_WORKSPACE_BUDGET: Final = 100

_CURSOR_KEY: Final = "calevate:workspace-walk:{sweep}"
_CURSOR_TTL_S: Final = 30 * 24 * 3600


@dataclass(frozen=True, slots=True)
class WorkspaceVisit:
    """One workspace to read. `tenant_id` and `workspace` are both None for our developer
    workspace."""

    tenant_id: UUID | None
    workspace: str | None


DEVELOPER: Final = WorkspaceVisit(tenant_id=None, workspace=None)


async def _cursor(sweep: str) -> str | None:
    try:
        value = await get_redis().get(_CURSOR_KEY.format(sweep=sweep))
    except Exception as exc:
        log.warning("workspace_walk_cursor_unreadable", extra={"reason": type(exc).__name__})
        return None
    return value if isinstance(value, str) and value else None


async def _advance(sweep: str, tenant_id: UUID) -> None:
    try:
        await get_redis().set(_CURSOR_KEY.format(sweep=sweep), str(tenant_id), ex=_CURSOR_TTL_S)
    except Exception as exc:
        log.warning("workspace_walk_cursor_unwritable", extra={"reason": type(exc).__name__})


def rotate(rows: list[WorkspaceRow], after: str | None) -> list[WorkspaceRow]:
    """`rows` starting after the tenant `after`, wrapping round; unchanged with no cursor."""
    if after is None:
        return rows
    later = [row for row in rows if str(row.tenant_id) > after]
    return later + [row for row in rows if str(row.tenant_id) <= after]


@dataclass(slots=True)
class WalkReport:
    visited: int = 0
    #: Active customer workspaces left for a later tick.
    deferred: int = 0


async def walk_workspaces(
    sweep: str,
    *,
    budget: int = DEFAULT_WORKSPACE_BUDGET,
    include_developer: bool = True,
    report: WalkReport | None = None,
) -> AsyncIterator[WorkspaceVisit]:
    """The workspaces this tick of `sweep` reads, developer workspace first. The cursor
    advances as each customer workspace is handed back, so a visit the caller finished is
    not repeated on the next tick."""
    if include_developer:
        if report is not None:
            report.visited += 1
        yield DEVELOPER
    rows = rotate(await active_workspaces(), await _cursor(sweep))
    chosen = rows[:budget]
    if report is not None:
        report.deferred = max(len(rows) - len(chosen), 0)
    for row in chosen:
        yield WorkspaceVisit(tenant_id=row.tenant_id, workspace=row.workspace_id)
        if report is not None:
            report.visited += 1
        await _advance(sweep, row.tenant_id)


async def all_workspaces(*, include_developer: bool = True) -> list[WorkspaceVisit]:
    """Every workspace at once, for a reconciliation that must compare one complete picture
    (the account-wide knowledge orphans): developer first, then every active customer."""
    visits = [DEVELOPER] if include_developer else []
    visits.extend(
        WorkspaceVisit(tenant_id=row.tenant_id, workspace=row.workspace_id)
        for row in await active_workspaces()
    )
    return visits


__all__ = [
    "DEFAULT_WORKSPACE_BUDGET",
    "DEVELOPER",
    "WalkReport",
    "WorkspaceVisit",
    "all_workspaces",
    "rotate",
    "walk_workspaces",
]
