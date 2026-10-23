"""Re-run filed tenant erasures that never completed.

Run inside the workers container:

    python -m scripts.redrive_tenant_erasures            # read only: lists them
    python -m scripts.redrive_tenant_erasures --apply    # queues each one again

An erasure whose job failed (23 Oct 2026: every closed account's erasure rolled back on
`ck_organizations_deleted_implies_no_deadline`) keeps its open `tenant_erasure_requests`
row, and filing it again from the console only answers "already open", so nothing would
run it a second time. This queues the same job for the same request under its own job id.
Re-running is safe: the job rolls back whole on any failure, and marks the account erased
only once (`retention._MARK_ERASED_SQL`). Prints ids only (hard rule 6).

Accounts are found on the directory session, which reads `organizations` and nothing
else; each account's requests are read inside its own tenant session (hard rule 1).
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from apps.api.core.queue import close_queue, enqueue, job_id_for
from apps.api.db.session import admin_session, tenant_session
from sqlalchemy import text

#: `compliance.tenant_erasure.TENANT_ERASURE_JOB`, spelled here because `check_job_wiring`
#: resolves an enqueued name only from the enqueuing file.
TENANT_ERASURE_JOB: Final = "execute_tenant_erasure"

_ACCOUNTS_SQL: Final = (
    "SELECT id FROM organizations WHERE status = 'churned' AND deleted_at IS NULL ORDER BY id"
)
_OPEN_SQL: Final = (
    "SELECT id FROM tenant_erasure_requests WHERE tenant_id = :tid AND completed_at IS NULL "
    "ORDER BY requested_at"
)


@dataclass(frozen=True, slots=True)
class OpenErasure:
    tenant_id: UUID
    request_id: UUID


async def open_erasures(*, only_tenant: UUID | None = None) -> list[OpenErasure]:
    if only_tenant is not None:
        tenants = [only_tenant]
    else:
        async with admin_session() as session:
            tenants = [UUID(str(t)) for t in (await session.execute(text(_ACCOUNTS_SQL))).scalars()]
    found: list[OpenErasure] = []
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as session:
            rows = (await session.execute(text(_OPEN_SQL), {"tid": tenant_id})).scalars()
            found.extend(OpenErasure(tenant_id, UUID(str(r))) for r in rows)
    return found


async def run(*, apply: bool, only_tenant: UUID | None = None) -> int:
    """Returns how many erasures were queued (or, read only, would be)."""
    found = await open_erasures(only_tenant=only_tenant)
    queued = 0
    for item in found:
        verdict = "open"
        if apply:
            job = await enqueue(
                TENANT_ERASURE_JOB,
                {"tenant_id": str(item.tenant_id), "request_id": str(item.request_id)},
                job_id=job_id_for(TENANT_ERASURE_JOB, str(item.request_id), "redrive"),
            )
            verdict = "queued" if job else "already_queued"
            queued += bool(job)
        print(f"  tenant {item.tenant_id} request {item.request_id}: {verdict}")
    print(f"open tenant erasures: {len(found)}" + (f", queued {queued}" if apply else ""))
    if found and not apply:
        print("READ ONLY. Re-run with --apply to queue them.")
    return queued if apply else len(found)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", type=UUID, default=None, help="only this account")
    parser.add_argument("--apply", action="store_true", help="queue the erasures")
    return parser


async def _main(args: argparse.Namespace) -> None:
    try:
        await run(apply=args.apply, only_tenant=args.tenant)
    finally:
        await close_queue()


if __name__ == "__main__":
    asyncio.run(_main(build_parser().parse_args()))
