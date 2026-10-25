"""Telling people about value given with no payment behind it (D-890).

Founder, 26 Oct 2026: when a super admin grants credit or makes an account paid, the client's
owner is told (an email and a notice in their dashboard), and every super admin is emailed
too. The second is the control that stands in for a second approver while there is one super
admin: an act nobody else sees is the one internal audit stops on.

Promised here through the outbox, in the transaction that moved the money or the account, so
a rolled-back grant tells nobody and a replayed one tells once (`enqueue_outbox_once`, keyed
on the act). `workers/comp_notices.notify_comp` does the telling.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.reliability.service import enqueue_outbox_once

#: The ARQ name of `workers/comp_notices.notify_comp`.
COMP_NOTICE_JOB: Final = "notify_comp"

CompKind = Literal["grant", "paid"]


async def owe_comp_notices(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    kind: CompKind,
    act_ref: str,
    actor_id: UUID | None,
    reason: str,
    amount_inr: Decimal | None = None,
) -> None:
    """Promise the notices for one act, in the caller's transaction. `act_ref` names the act
    (a grant's ledger reference, or the conversion's audit object), so the same act is told
    once however often it is replayed."""
    await enqueue_outbox_once(
        session,
        job=COMP_NOTICE_JOB,
        payload={
            "tenant_id": str(tenant_id),
            "kind": kind,
            "amount_inr": str(amount_inr) if amount_inr is not None else None,
            "actor_id": str(actor_id) if actor_id is not None else None,
            "reason": reason,
        },
        dedupe_key=f"comp:{kind}:{tenant_id}:{act_ref}",
    )


__all__ = ["COMP_NOTICE_JOB", "CompKind", "owe_comp_notices"]
