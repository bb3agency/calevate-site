"""The outbound gate's question about disputes, kept free of the payment modules (D-699).

`compliance.service.check_dispatch` asks it, and that module must not import the
Razorpay adapter chain to do so.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: The dispute states in which outbound calling stays paused.
OPEN_STATES: Final = ("open", "under_review")

#: What the outbound gate says, in the client's words.
DISPUTE_HOLD_REASON: Final = (
    "Outbound calls are paused while a payment on your account is disputed with your "
    "bank. Incoming calls keep working. We will email you once it is resolved."
)


async def dispute_hold_active(session: AsyncSession, *, tenant_id: UUID) -> bool:
    """Is any dispute on this account still open?"""
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM payment_disputes WHERE tenant_id = :tid "
                "AND status IN ('open', 'under_review') LIMIT 1"
            ),
            {"tid": tenant_id},
        )
    ).first()
    return row is not None


__all__ = ["DISPUTE_HOLD_REASON", "OPEN_STATES", "dispute_hold_active"]
