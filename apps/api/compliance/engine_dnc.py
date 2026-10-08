"""A client's do-not-call additions, pushed to its OWN ThinnestAI workspace (D-691).

Founder decision (8 Oct 2026, revised): do-not-call is two-way per client. Our per-client
list decides every dial (the dispatch gate), and each addition is also put on the list of
the client's own ThinnestAI customer workspace, so the platform's agent and its campaigns
refuse the number too. The other direction — `contact.opted_out` heard by the platform's
agent — is `apps/workers/engine_signals.py`.

ONLY INTO THE CLIENT'S OWN WORKSPACE. The platform's list is per workspace; until a client
has its own (`tenancy/engine_workspace.own_workspace`), an addition stays ours alone and
nothing is queued. Pushing it to our developer workspace would block the number for every
client. The resolver is asked when the addition is queued AND again when it is sent.

Through the outbox, in the transaction that wrote the suppression, so the push cannot be
lost to a crash and cannot happen for a row that rolled back. The job carries row ids, not
numbers: the number is read back under the tenant's policy when it is sent.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.settings import get_settings
from apps.api.reliability.service import enqueue_outbox
from apps.api.tenancy.engine_workspace import own_workspace

ENGINE_DNC_PUSH_JOB: Final = "push_engine_dnc"

#: Engines whose platform keeps a per-workspace do-not-call list we push to.
DNC_PUSH_ENGINES: Final = frozenset({"thinnest"})

_ROWS: Final = (
    "SELECT id FROM dnc_list WHERE tenant_id = :tid AND phone_e164 = ANY(:phones) ORDER BY id"
)


async def queue_engine_dnc_push(
    session: AsyncSession, *, tenant_id: UUID, phones: Sequence[str]
) -> bool:
    """Queue the push of these tenant-scoped suppressions, in the caller's transaction.
    False, and nothing queued, off the engine or while the tenant has no own workspace."""
    if not phones or get_settings().engine not in DNC_PUSH_ENGINES:
        return False
    if await own_workspace(tenant_id) is None:
        return False
    ids = [
        str(row)
        for row in (
            await session.execute(text(_ROWS), {"tid": tenant_id, "phones": list(phones)})
        ).scalars()
    ]
    if not ids:
        return False
    await enqueue_outbox(
        session,
        job=ENGINE_DNC_PUSH_JOB,
        payload={"tenant_id": str(tenant_id), "dnc_ids": ids},
    )
    return True


__all__ = ["DNC_PUSH_ENGINES", "ENGINE_DNC_PUSH_JOB", "queue_engine_dnc_push"]
