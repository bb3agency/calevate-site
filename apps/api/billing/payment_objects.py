"""Which tenant a Razorpay object belongs to, and what we asked an order for (D-699).

The webhook receiver has no session and, for token events, no notes
(`api/payments/recurring-payments/webhooks.md`, token.confirmed sample, read 9 Oct 2026),
so the tenant of an order, token or customer is recorded here when WE create it, in that
tenant's session, and read back in an untenanted one through the table's ops-read policy.

`verify_order` is the founder's rule "verify the amount and the tenant from OUR order
record, never from client-supplied notes alone": a payment against an order we recorded
must name that order's tenant and carry exactly its amount.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.payments import CapturedPayment, inr_to_paise
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import untenanted_session

log = get_logger(__name__)

RouteKind = Literal["order", "token", "customer"]
RoutePurpose = Literal["topup", "mandate", "auto_recharge"]

TOPUP: Final = "topup"
MANDATE: Final = "mandate"
AUTO_RECHARGE: Final = "auto_recharge"


@dataclass(frozen=True, slots=True)
class ObjectRoute:
    tenant_id: UUID
    object_id: str
    kind: str
    purpose: str | None
    amount_paise: int | None


async def record_route(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    object_id: str,
    kind: RouteKind,
    purpose: RoutePurpose | None = None,
    amount_inr: Decimal | None = None,
) -> None:
    """Remember who owns `object_id`. Idempotent: the id is unique at Razorpay, so a
    replayed write keeps the first row. Called in the OWNING tenant's session; the
    table's write policy refuses any other."""
    await session.execute(
        text(
            "INSERT INTO razorpay_object_routes "
            "(id, tenant_id, object_id, kind, purpose, amount_paise) "
            "VALUES (:id, :tid, :oid, :kind, :purpose, :paise) "
            "ON CONFLICT (object_id) DO NOTHING"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "oid": object_id,
            "kind": kind,
            "purpose": purpose,
            "paise": None if amount_inr is None else inr_to_paise(amount_inr),
        },
    )


async def route_for(object_id: str | None) -> ObjectRoute | None:
    """The route of one Razorpay id, read without a tenant. None when we never made it."""
    if not object_id:
        return None
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT tenant_id, object_id, kind, purpose, amount_paise "
                    "FROM razorpay_object_routes WHERE object_id = :oid"
                ),
                {"oid": object_id},
            )
        ).first()
    if row is None:
        return None
    return ObjectRoute(
        tenant_id=UUID(str(row[0])),
        object_id=str(row[1]),
        kind=str(row[2]),
        purpose=None if row[3] is None else str(row[3]),
        amount_paise=None if row[4] is None else int(row[4]),
    )


def verify_order(payment: CapturedPayment, route: ObjectRoute | None) -> None:
    """Refuse a payment that disagrees with OUR record of its order.

    No route is not a refusal here: a payment made before routes existed, or an order made
    on the dashboard, still credits on its notes and `credit_captured_payment`'s own
    checks. A route that names ANOTHER tenant, or an amount that differs from what we asked
    the order for, is refused, because both mean the notes are not to be trusted.
    """
    if route is None:
        return
    if route.tenant_id != payment.tenant_id:
        log.error(
            "razorpay_order_tenant_mismatch",
            extra={"payment_ref": payment.payment_id, "order_id": route.object_id},
        )
        raise ProblemError.conflict(
            "payment_order_mismatch",
            "This payment's account does not match the order it paid.",
            remediation="Nothing was credited. Reconcile it against the provider dashboard.",
        )
    if route.amount_paise is not None and route.amount_paise != inr_to_paise(payment.amount_inr):
        log.error(
            "razorpay_order_amount_mismatch",
            extra={"payment_ref": payment.payment_id, "order_id": route.object_id},
        )
        raise ProblemError.conflict(
            "payment_order_mismatch",
            "This payment's amount does not match the order it paid.",
            remediation="Nothing was credited. Reconcile it against the provider dashboard.",
        )


__all__ = [
    "AUTO_RECHARGE",
    "MANDATE",
    "TOPUP",
    "ObjectRoute",
    "RouteKind",
    "RoutePurpose",
    "record_route",
    "route_for",
    "verify_order",
]
