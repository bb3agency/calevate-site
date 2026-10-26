"""Read again the answered calls whose post-call reading stored nothing.

Run inside the workers container (it reaches Postgres, Redis and the model):

    python -m scripts.reread_extractions --hours 48            # read only: lists them
    python -m scripts.reread_extractions --hours 48 --apply    # reads each one again

A candidate is a call recorded `completed`, in which the caller said something, ended
inside the window and at least `PIPELINE_STALL_AFTER` ago, whose reading is either a
provider failure (`errors._model`) or an answer that held nothing: no outcome and no
captured detail. The second kind is what an unusable model answer was stored as before
`ExtractionUnusableError` (27 Oct 2026: site-visit calls read as "Answered", "the caller did
not give any details"); it carries no `_model` error, so the half-hourly re-read sweep
(`workers/extraction_reread`) never picks it up, and the sweep stops a day after the call.

`--apply` runs the sweep's own re-read (`extraction_reread.reread_extraction`) for each
call with the stored reading set aside: the extraction, summary, outcome, business
outcome, lead and hot alert are filed as the pipeline files them, the model pass is metered
as ours (`ASSIST_FEATURE_CALL_EXTRACTION`), and a changed outcome sends the client's CRM
`call.updated`. Re-running is safe: a call read successfully is no longer a candidate, and
each call is claimed by compare-and-swap on `call_extractions.reread_at` before the model is
asked, so two runs (or a run and the sweep) cannot both pay for one call within
`CLAIM_SPACING`. Prints ids and counts only (hard rule 6).

Tenants are walked through `engine_agent_routes` (`pipeline.callable_tenants`), and every
read is inside that tenant's own session, so no RLS is widened (hard rule 1).
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from typing import Final
from uuid import UUID

from apps.api.core.queue import close_queue
from apps.api.db.session import tenant_session
from apps.workers.extraction import MODEL_FAILURE
from apps.workers.extraction_reread import reread_extraction
from apps.workers.pipeline import PIPELINE_STALL_AFTER, callable_tenants
from sqlalchemy import text

#: A claim older than this is free again: long enough for one reading (the model's timeout
#: and its retries), short enough that a run killed mid-way can be repeated the same hour.
CLAIM_SPACING: Final = timedelta(minutes=10)

_CANDIDATES_SQL: Final = (
    "SELECT ce.call_id FROM call_extractions ce "
    "JOIN calls c ON c.id = ce.call_id AND c.tenant_id = ce.tenant_id "
    "WHERE ce.tenant_id = :tid AND c.status = 'completed' "
    "AND ce.scrubbed_at IS NULL AND c.erased_subject_ref IS NULL "
    "AND NOT EXISTS (SELECT 1 FROM tenant_erasure_requests e WHERE e.tenant_id = c.tenant_id) "
    "AND COALESCE(c.ended_at, c.created_at) > now() - :window "
    "AND COALESCE(c.ended_at, c.created_at) < now() - :grace "
    "AND EXISTS (SELECT 1 FROM transcript_turns t WHERE t.call_id = c.id "
    "  AND t.tenant_id = c.tenant_id AND t.speaker = 'caller' AND btrim(t.text) <> '') "
    "AND ((ce.errors ->> :model_failure) IS NOT NULL "
    "  OR (ce.outcome_hint IS NULL AND (ce.data IS NULL OR ce.data = '{}'::jsonb))) "
    "ORDER BY COALESCE(c.ended_at, c.created_at), ce.call_id LIMIT :cap"
)

_CLAIM_SQL: Final = (
    "UPDATE call_extractions SET reread_at = now(), updated_at = now() "
    "WHERE call_id = :cid AND tenant_id = :tid "
    "AND (reread_at IS NULL OR reread_at < now() - :spacing) RETURNING call_id"
)


@dataclass(frozen=True, slots=True)
class Candidate:
    tenant_id: UUID
    call_id: UUID


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
                        "model_failure": MODEL_FAILURE,
                        "cap": cap - len(found),
                    },
                )
            ).all()
        found.extend(Candidate(tenant_id, UUID(str(row[0]))) for row in rows)
    return found


async def _claim(candidate: Candidate) -> bool:
    async with tenant_session(candidate.tenant_id) as session:
        claimed = (
            await session.execute(
                text(_CLAIM_SQL),
                {
                    "cid": candidate.call_id,
                    "tid": candidate.tenant_id,
                    "spacing": CLAIM_SPACING,
                },
            )
        ).first()
    return claimed is not None


async def run(
    *, window: timedelta, cap: int, apply: bool, only_tenant: UUID | None
) -> Counter[str]:
    """Returns the count of each verdict (`candidate` when read only)."""
    found = await candidates(window=window, cap=cap, only_tenant=only_tenant)
    verdicts: Counter[str] = Counter()
    for candidate in found:
        verdict = "candidate"
        if apply:
            verdict = (
                await reread_extraction(candidate.tenant_id, candidate.call_id, reuse=False)
                if await _claim(candidate)
                else "claimed_elsewhere"
            )
        verdicts[verdict] += 1
        print(f"  tenant {candidate.tenant_id} call {candidate.call_id}: {verdict}")
    hours = window.total_seconds() / 3600
    summary = ", ".join(f"{name} {count}" for name, count in sorted(verdicts.items()))
    print(f"answered calls whose reading stored nothing ({hours:g}h): {len(found)}; {summary}")
    if found and not apply:
        print("READ ONLY. Re-run with --apply to read them again.")
    return verdicts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hours", type=int, default=48, help="how far back a call may have ended (default 48)"
    )
    parser.add_argument(
        "--limit", type=int, default=200, help="at most this many calls (default 200)"
    )
    parser.add_argument("--tenant", type=UUID, default=None, help="only this tenant's calls")
    parser.add_argument("--apply", action="store_true", help="read the calls again")
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
        # A re-read can queue a hot-lead alert and a CRM event through the outbox and Redis.
        await close_queue()


if __name__ == "__main__":
    asyncio.run(_main(build_parser().parse_args()))
