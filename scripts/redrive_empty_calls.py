"""Re-drive answered calls that settled with no transcript (D-848).

Run inside the workers container (it reaches Postgres, Redis and the engine):

    python -m scripts.redrive_empty_calls --hours 48            # read only: lists them
    python -m scripts.redrive_empty_calls --hours 48 --apply    # queues each re-drive

A candidate is a call recorded `completed` with talk time (`duration_s > 0`) that holds no
transcript turn or whose summary was settled `empty`, ended inside the window and at least
`PIPELINE_STALL_AFTER` ago (younger ones may still be on the pipeline's ladder). Before
D-848 such a call was settled from the `call.completed` delivery, which carries no
transcript or recording link, and the later `call.analysed` delivery was deduped.

`--apply` queues the same ingest job the reconciliation poller queues, under its own job id:
it reads the call from the engine (Get Call), updates the row and queues the post-call
pipeline, which writes the turns, copies the recording and reads the call again. Re-running
is safe: metering and the CRM fan-out are claimed once per call, and the job id refuses a
second queueing of one call within the hour. Prints ids and counts only (hard rule 6).

Tenants are walked through `engine_agent_routes` (`pipeline.callable_tenants`), and every
read is inside that tenant's own session, so no RLS is widened (hard rule 1).
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Final
from uuid import UUID

from apps.api.core.queue import close_queue, enqueue, job_id_for
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.workers.pipeline import PIPELINE_STALL_AFTER, callable_tenants
from sqlalchemy import text

#: `pipeline.INGEST_JOB`, spelled here because `check_job_wiring` resolves an enqueued name
#: only from the enqueuing file.
INGEST_JOB: Final = "ingest_engine_event"

_CANDIDATES_SQL: Final = (
    "SELECT c.id, c.engine_call_id FROM calls c "
    "WHERE c.tenant_id = :tid AND c.status = 'completed' AND c.duration_s > 0 "
    "AND c.engine_call_id IS NOT NULL "
    "AND COALESCE(c.ended_at, c.created_at) > now() - :window "
    "AND COALESCE(c.ended_at, c.created_at) < now() - :grace "
    "AND (c.summary_state = 'empty' OR NOT EXISTS (SELECT 1 FROM transcript_turns t "
    "  WHERE t.call_id = c.id AND t.tenant_id = c.tenant_id)) "
    "ORDER BY COALESCE(c.ended_at, c.created_at) LIMIT :cap"
)


@dataclass(frozen=True, slots=True)
class Candidate:
    tenant_id: UUID
    call_id: UUID
    execution_id: str


async def candidates(*, window: timedelta, cap: int, only_tenant: UUID | None) -> list[Candidate]:
    found: list[Candidate] = []
    for tenant_id in [only_tenant] if only_tenant else await callable_tenants():
        if len(found) >= cap:
            break
        async with tenant_session(tenant_id) as session:
            rows = (
                await session.execute(
                    text(_CANDIDATES_SQL),
                    {
                        "tid": tenant_id,
                        "window": window,
                        "grace": PIPELINE_STALL_AFTER,
                        "cap": cap - len(found),
                    },
                )
            ).all()
        found.extend(Candidate(tenant_id, UUID(str(row[0])), str(row[1])) for row in rows)
    return found


async def run(*, window: timedelta, cap: int, apply: bool, only_tenant: UUID | None) -> int:
    """Returns how many calls were queued (or, read only, would be)."""
    engine_name = get_engine().name
    found = await candidates(window=window, cap=cap, only_tenant=only_tenant)
    queued = 0
    for candidate in found:
        verdict = "candidate"
        if apply:
            job = await enqueue(
                INGEST_JOB,
                {
                    "engine": engine_name,
                    "execution_id": candidate.execution_id,
                    "source": "redrive_empty_calls",
                },
                job_id=job_id_for(INGEST_JOB, engine_name, candidate.execution_id, "redrive"),
            )
            verdict = "queued" if job else "already_queued"
            queued += bool(job)
        print(
            f"  tenant {candidate.tenant_id} call {candidate.call_id} "
            f"execution {candidate.execution_id}: {verdict}"
        )
    hours = window.total_seconds() / 3600
    if apply:
        print(f"answered calls without a transcript ({hours:g}h): {len(found)}, queued {queued}")
    else:
        print(f"answered calls without a transcript ({hours:g}h): {len(found)}")
        if found:
            print("READ ONLY. Re-run with --apply to queue the re-drives.")
    return queued if apply else len(found)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hours", type=int, default=48, help="how far back a call may have ended (default 48)"
    )
    parser.add_argument(
        "--limit", type=int, default=200, help="at most this many calls (default 200)"
    )
    parser.add_argument("--tenant", type=UUID, default=None, help="only this tenant's calls")
    parser.add_argument("--apply", action="store_true", help="queue the re-drives")
    return parser


async def _main(args: argparse.Namespace) -> None:
    try:
        await run(
            window=timedelta(hours=args.hours),
            cap=args.limit,
            apply=args.apply,
            only_tenant=args.tenant,
        )
    finally:
        await close_queue()


if __name__ == "__main__":
    asyncio.run(_main(build_parser().parse_args()))
