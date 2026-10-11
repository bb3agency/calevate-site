"""Run the live-apply worker in a test, the way the outbox dispatcher would (D-720).

Tests do not run the dispatcher, so a save that queues a live apply leaves its run pending.
`drain_live_apply` walks every open run in the scope to the end by calling the worker's own
job, so a test asserts what the engine holds after the seam has done its work.
"""

from __future__ import annotations

from uuid import UUID

from apps.api.db.session import untenanted_session
from apps.workers.live_apply import apply_live_settings
from sqlalchemy import text


async def drain_live_apply(tenant_id: UUID | None = None, *, max_jobs: int = 50) -> list[str]:
    """Walk the open runs for `tenant_id` (or the platform's when None). Returns outcomes."""
    outcomes: list[str] = []
    for _ in range(max_jobs):
        async with untenanted_session() as session:
            run_id = (
                await session.execute(
                    text(
                        "SELECT id FROM live_apply_runs WHERE status IN ('pending', 'running') "
                        "AND walked_at IS NULL AND (lease_until IS NULL OR lease_until < now()) "
                        "AND ((CAST(:tid AS uuid) IS NULL AND scope = 'platform') "
                        "OR tenant_id = CAST(:tid AS uuid)) ORDER BY created_at LIMIT 1"
                    ),
                    {"tid": tenant_id},
                )
            ).scalar()
        if run_id is None:
            break
        outcomes.append(await apply_live_settings({}, {"run_id": str(run_id)}))
    return outcomes


__all__ = ["drain_live_apply"]
