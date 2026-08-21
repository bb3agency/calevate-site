"""The one seam a suppression uses to reach dials the vendor is already holding.

THREE WRITERS, ONE ENQUEUE. `dnc_list` is written from three places — the single-number
upsert every dial-gate reader is documented against (`compliance.service.add_to_dnc`), the
tenant bulk import, and the GLOBAL bulk import — and each computes the set of numbers that
were newly suppressed. Three enqueues would be three chances to forget one, and the one
forgotten would fail silently: the suppression would still take effect at the next dispatch
tick, so every screen would look right while the queued dials rang.

IN THE CALLER'S TRANSACTION, through the outbox, and that is the whole reason this is a
function rather than a `enqueue()` call at each site. `enqueue_outbox` writes a row that
shares the suppression's fate: a DNC insert that rolls back cannot leave a recall chasing
numbers nobody suppressed, and one that commits cannot lose its recall to a crash between
the two writes. `reliability/service.py` states the discipline; this obeys it.

ONLY THE FRESH ONES. Every caller already computes which numbers were newly added — the
bulk paths as `fresh`, the single path through `ON CONFLICT`. Re-enqueueing for a number
that was already suppressed would scan for dials that the earlier recall already stamped,
find nothing, and cost a vendor round trip per re-add; on a bulk re-import of a list that
has not changed, that is the whole list.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.reliability.service import enqueue_outbox

#: The ARQ function name. Duplicated from `apps.workers.dnc_recall.DNC_RECALL_JOB` rather
#: than imported, for `compliance/deletion.DELETION_JOB`'s reason: the API has no business
#: importing a worker module — with its session factory and its scan SQL — to name a job.
#: `tests/dnc_recall_test.py` pins the two spellings together so they cannot drift.
DNC_RECALL_JOB = "recall_dials_for_dnc"


async def enqueue_dnc_recall(
    session: AsyncSession, *, tenant_id: UUID | None, phones: list[str]
) -> None:
    """Ask the recall job to pull back queued dials to `phones`. Do not commit here.

    `tenant_id=None` means a GLOBAL suppression. It is not a missing value: a global entry
    outranks every tenant's own list, so the recall has to reach every tenant's queue, and
    the job reads `None` as exactly that. A tenant-scoped entry passes its own id and the
    scan stays inside it.

    A no-op on an empty list rather than an enqueue that finds nothing: a bulk re-import of
    an unchanged list produces one of these per call, and an outbox row per no-op is noise
    in the table the dispatcher walks.
    """
    if not phones:
        return
    await enqueue_outbox(
        session,
        job=DNC_RECALL_JOB,
        payload={
            "tenant_id": str(tenant_id) if tenant_id is not None else None,
            # Sorted and de-duplicated so two enqueues for the same suppression produce
            # the same payload — which is what makes an outbox row inspectable, and what
            # a dedupe key would need if this ever grows one.
            "phones": sorted(set(phones)),
        },
    )


__all__ = ["DNC_RECALL_JOB", "enqueue_dnc_recall"]
