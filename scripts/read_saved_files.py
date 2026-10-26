"""Read the words of PDFs and links saved before they were read (D-893 L8).

Run inside the api or workers container (it reaches Postgres):

    python -m scripts.read_saved_files                  # read only: counts per tenant
    python -m scripts.read_saved_files --apply          # queues each reading
    python -m scripts.read_saved_files --apply --retry-failed

A candidate is a PDF or link upload of a version that is not history (`archived`) whose
words were never read (`read_state` NULL) — or, with `--retry-failed`, whose reading failed.
`--apply` queues `read_kb_upload` through the outbox (`kb.reading.queue_read`), one per
upload, in that tenant's own session; the job reads the file or page, stores the words where
every upload's text is stored, and re-sends a live one only while `kb_send_extracted_files`
is on. A scanned PDF's pages are read by our Gemini reader and metered to the client, so the
read-only run comes first. Re-running is safe: a reading already `ready` is never queued.
Prints ids and counts only (hard rule 6).

Tenants are walked through `kb_gloss.tenants_holding_knowledge`, and every read is inside
that tenant's own session, so no RLS is widened (hard rule 1).
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Final
from uuid import UUID

from apps.api.db.session import tenant_session
from apps.api.kb.models import READ_COPY_KINDS
from apps.api.kb.reading import queue_read
from apps.workers.kb_gloss import tenants_holding_knowledge
from sqlalchemy import text

_CANDIDATES_SQL: Final = (
    "SELECT u.source_id FROM kb_uploads u JOIN kb_sources s ON s.id = u.source_id "
    "WHERE u.tenant_id = :tid AND u.source_kind = ANY(:kinds) AND s.status <> 'archived' "
    "AND (u.read_state IS NULL OR (CAST(:retry AS boolean) AND u.read_state = 'failed')) "
    "ORDER BY u.created_at LIMIT :cap"
)


async def run(*, apply: bool, retry_failed: bool, cap: int, only_tenant: UUID | None) -> int:
    """Returns how many uploads were queued (or, read only, would be)."""
    total = 0
    for tenant_id in [only_tenant] if only_tenant else await tenants_holding_knowledge():
        if total >= cap:
            break
        async with tenant_session(tenant_id) as session:
            source_ids = [
                UUID(str(sid))
                for sid in (
                    await session.execute(
                        text(_CANDIDATES_SQL),
                        {
                            "tid": tenant_id,
                            "kinds": list(READ_COPY_KINDS),
                            "retry": retry_failed,
                            "cap": cap - total,
                        },
                    )
                ).scalars()
            ]
            if apply:
                for source_id in source_ids:
                    await queue_read(
                        session, tenant_id=tenant_id, source_id=source_id, force=retry_failed
                    )
        if source_ids:
            print(f"  tenant {tenant_id}: {len(source_ids)} {'queued' if apply else 'unread'}")
        total += len(source_ids)
    print(f"PDFs and links to read: {total}" + (" (queued)" if apply else ""))
    if total and not apply:
        print("READ ONLY. Re-run with --apply to queue the readings.")
    return total


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="queue the readings")
    parser.add_argument(
        "--retry-failed", action="store_true", help="also read again the ones that failed"
    )
    parser.add_argument("--limit", type=int, default=1000, help="at most this many (default 1000)")
    parser.add_argument("--tenant", type=UUID, default=None, help="only this tenant")
    return parser


if __name__ == "__main__":
    parsed = build_parser().parse_args()
    asyncio.run(
        run(
            apply=parsed.apply,
            retry_failed=parsed.retry_failed,
            cap=parsed.limit,
            only_tenant=parsed.tenant,
        )
    )
