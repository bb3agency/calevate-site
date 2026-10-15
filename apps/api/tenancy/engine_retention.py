"""How long the voice platform keeps a client's calls: its workspace's `callRetentionDays`.

ThinnestAI keeps each workspace's call recordings for the plan's window and its transcripts
with no end, unless `callRetentionDays` sets a shorter period for both (1 to
`planRetentionDays`: 30 on pay-as-you-go, 49 Pro, 75 Scale, 365 Enterprise; a longer one is
refused with a 400). Each night it then deletes older calls' content the way Delete Call
Content does (VERIFIED-VENDOR-DOCS, `thinnest-findings/mirror/snapshots/2026-10-15/pages/
api-reference/workspace/update-workspace.md:528-599`, `workspace/data-and-erasure.md:94-108`).

So every client workspace is given a number, never left on the default, from the client's
own retention policy: the SHORTER of its recording and transcript periods, because the
platform deletes both at once and the shorter promise is the one the client was made. The
plan's window, read from the platform, caps it; a client whose period is longer simply has
the platform keep less than we do, which is stricter and fine. Our own copies follow our own
policy (`workers/retention.py`), recordings never under the 90-day floor.

Pushed when a workspace is provisioned (`queue_retention_sync`, from `workers/
engine_workspaces._activate`) and read back and repaired hourly (`workers/engine_retention`).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.reliability.service import enqueue_outbox
from apps.api.tenancy.engine_workspace import engine_has_workspaces

RETENTION_SYNC_JOB: Final = "sync_engine_retention"

#: The policy categories whose content the platform holds for a call.
CALL_CONTENT_CATEGORIES: Final = ("recording", "transcript")

_POLICIES_SQL: Final = (
    "SELECT data_category, ttl_days FROM retention_policies "
    "WHERE tenant_id = :tid AND data_category = ANY(:cats)"
)


def call_content_days(policies: Iterable[tuple[str, int]]) -> int | None:
    """The shorter of the recording and transcript periods among `policies`, or None when
    neither is set."""
    periods = [int(ttl) for category, ttl in policies if category in CALL_CONTENT_CATEGORIES]
    return min(periods) if periods else None


async def wanted_retention_days(session: AsyncSession, tenant_id: UUID) -> int | None:
    """The tenant's own period for the platform's copy of its calls, in its tenant session."""
    rows = (
        await session.execute(
            text(_POLICIES_SQL), {"tid": tenant_id, "cats": list(CALL_CONTENT_CATEGORIES)}
        )
    ).all()
    return call_content_days((str(row[0]), int(row[1])) for row in rows)


def retention_to_send(wanted: int | None, plan_days: int) -> int:
    """The `callRetentionDays` to set: the tenant's period capped at the plan's window, or
    the plan's window itself when the tenant states none. Never null: null keeps transcripts
    with no end."""
    return plan_days if wanted is None else max(1, min(wanted, plan_days))


async def queue_retention_sync(session: AsyncSession, *, tenant_id: UUID) -> bool:
    """Owe the tenant's workspace its call retention, in the caller's transaction."""
    if not engine_has_workspaces():
        return False
    await enqueue_outbox(session, job=RETENTION_SYNC_JOB, payload={"tenant_id": str(tenant_id)})
    return True


__all__ = [
    "CALL_CONTENT_CATEGORIES",
    "RETENTION_SYNC_JOB",
    "call_content_days",
    "queue_retention_sync",
    "retention_to_send",
    "wanted_retention_days",
]
