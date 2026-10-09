"""The daily comparison of Razorpay's payments and refunds with our ledger (D-699).

`GET /v1/payments` and `GET /v1/refunds` over the last `razorpay_reconciliation_days`
(`api/payments/fetch-all-payments.md`, `api/refunds/fetch-all.md`, read 9 Oct 2026, at
most 100 items a page), and for each:

- a CAPTURED payment that is ours and not on the ledger is credited now, through
  `payment_events.apply_captured` — the webhook's own path, onto the same ledger `ref`, so
  a late webhook afterwards is a replay. Alarm `razorpay_reconciliation_credited`.
- a captured payment we cannot attribute (no route, no notes) is unexplained.
- an AUTHORIZED payment of ours older than `UNCAPTURED_AFTER` is unexplained: auto-capture
  should have captured it, so the account's capture setting is wrong (runbook §1).
- a PROCESSED refund of one of our payments that is not on the ledger is recorded through
  `payments.credit_refund`, the webhook's own writer.

Anything unexplained raises `razorpay_reconciliation_unexplained` with the ids. Settlements
(`GET /v1/settlements`) are counted and summed for the report and never acted on.

Nothing here reads a ledger across tenants: each fact is checked inside the owning tenant's
session, found through `razorpay_object_routes` or the payment's notes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID

from apps.api.billing.payment_events import apply_captured
from apps.api.billing.payment_objects import route_for
from apps.api.billing.payments import (
    NOTES_TENANT_KEY,
    SUPPORTED_CURRENCY,
    CapturedPayment,
    RefundEvent,
    credit_refund,
    paise_to_inr,
)
from apps.api.billing.razorpay_api import ProviderPayment, razorpay_api
from apps.api.billing.service import find_entry_by_ref, find_topup
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session

log = get_logger(__name__)

#: An authorised payment auto-capture has not captured after this long is a finding.
UNCAPTURED_AFTER: Final = timedelta(hours=1)
#: At most this many ids in one alarm.
_ID_LIMIT: Final = 10


@dataclass
class ReconciliationReport:
    window_days: int
    payments_seen: int = 0
    refunds_seen: int = 0
    credited_late: list[str] = field(default_factory=list)
    refunds_recorded_late: list[str] = field(default_factory=list)
    unexplained: list[str] = field(default_factory=list)
    settlements: int = 0
    settled_inr: Decimal = Decimal("0.00")


def _tenant_of_notes(notes: dict[str, str]) -> UUID | None:
    try:
        raw = notes.get(NOTES_TENANT_KEY)
        return UUID(raw) if raw else None
    except ValueError:
        return None


async def _tenant_of(payment: ProviderPayment) -> UUID | None:
    route = await route_for(payment.order_id)
    return route.tenant_id if route is not None else _tenant_of_notes(payment.notes)


async def reconcile(*, now: datetime | None = None) -> ReconciliationReport:
    """One pass. Raises nothing for a single bad row; a provider failure propagates (the
    worker retries the whole pass)."""
    at = now or datetime.now(UTC)
    days = get_settings().razorpay_reconciliation_days
    since, until = int((at - timedelta(days=days)).timestamp()), int(at.timestamp())
    report = ReconciliationReport(window_days=days)
    api = razorpay_api()

    payments = await api.list_payments(since=since, until=until)
    report.payments_seen = len(payments)
    by_id = {p.payment_id: p for p in payments}
    for payment in payments:
        await _check_payment(payment, report, at=at)

    refunds = await api.list_refunds(since=since, until=until)
    report.refunds_seen = len(refunds)
    for refund in refunds:
        if refund.status != "processed" or refund.currency != SUPPORTED_CURRENCY:
            continue
        tenant_id = _tenant_of_notes(refund.notes)
        if tenant_id is None:
            original = by_id.get(refund.payment_id)
            tenant_id = None if original is None else await _tenant_of(original)
        if tenant_id is None:
            report.unexplained.append(f"refund:{refund.refund_id}")
            continue
        async with tenant_session(tenant_id) as session:
            if await find_entry_by_ref(
                session, tenant_id=tenant_id, reason="refund", ref=refund.refund_id
            ):
                continue
            if await find_topup(session, tenant_id=tenant_id, ref=refund.payment_id) is None:
                report.unexplained.append(f"refund:{refund.refund_id}")
                continue
            await credit_refund(
                session,
                refund=RefundEvent(
                    refund_id=refund.refund_id,
                    payment_id=refund.payment_id,
                    tenant_id=tenant_id,
                    amount_inr=paise_to_inr(refund.amount_paise),
                    currency=SUPPORTED_CURRENCY,
                ),
            )
        report.refunds_recorded_late.append(refund.refund_id)

    settlements = await api.list_settlements(since=since, until=until)
    report.settlements = len(settlements)
    report.settled_inr = sum((Decimal(s.amount_paise) / 100 for s in settlements), Decimal("0.00"))

    _raise_alarms(report)
    log.info(
        "razorpay_reconciliation_done",
        extra={
            "payments": report.payments_seen,
            "refunds": report.refunds_seen,
            "credited_late": len(report.credited_late),
            "refunds_late": len(report.refunds_recorded_late),
            "unexplained": len(report.unexplained),
            "settlements": report.settlements,
            "settled_inr": str(report.settled_inr),
        },
    )
    return report


async def _check_payment(
    payment: ProviderPayment, report: ReconciliationReport, *, at: datetime
) -> None:
    if payment.currency != SUPPORTED_CURRENCY:
        return
    if payment.status == "authorized":
        created = datetime.fromtimestamp(payment.created_at, UTC)
        if at - created > UNCAPTURED_AFTER and await _tenant_of(payment) is not None:
            report.unexplained.append(f"uncaptured:{payment.payment_id}")
        return
    if payment.status not in ("captured", "refunded"):
        return
    route = await route_for(payment.order_id)
    tenant_id = route.tenant_id if route is not None else _tenant_of_notes(payment.notes)
    if tenant_id is None:
        report.unexplained.append(f"unattributed:{payment.payment_id}")
        return
    async with tenant_session(tenant_id) as session:
        on_ledger = await find_topup(session, tenant_id=tenant_id, ref=payment.payment_id)
    if on_ledger is not None:
        if on_ledger.amount_inr != paise_to_inr(payment.amount_paise):
            report.unexplained.append(f"amount:{payment.payment_id}")
        return
    captured = CapturedPayment(
        payment_id=payment.payment_id,
        tenant_id=tenant_id,
        amount_inr=paise_to_inr(payment.amount_paise),
        currency=SUPPORTED_CURRENCY,
        pack_id=payment.notes.get("calevate_pack_id"),
        order_id=payment.order_id,
        international=payment.international,
        token_id=payment.token_id,
    )
    try:
        result = await apply_captured(
            None, event="reconciliation", event_id=None, payment=captured, route=route
        )
    except ProblemError as exc:
        log.warning(
            "razorpay_reconciliation_refused",
            extra={"payment_id": payment.payment_id, "code": exc.code},
        )
        report.unexplained.append(f"{exc.code}:{payment.payment_id}")
        return
    if result.status == "credited":
        report.credited_late.append(payment.payment_id)


def _raise_alarms(report: ReconciliationReport) -> None:
    if report.credited_late or report.refunds_recorded_late:
        alert(
            "WORKER_DELIVERY",
            "razorpay_reconciliation_credited",
            detail="Reconciliation recorded payments or refunds whose webhook never arrived. "
            "Check the webhook URL and events in the Razorpay dashboard.",
            payments=",".join(report.credited_late[:_ID_LIMIT]),
            refunds=",".join(report.refunds_recorded_late[:_ID_LIMIT]),
        )
    if report.unexplained:
        alert(
            "WORKER_DELIVERY",
            "razorpay_reconciliation_unexplained",
            detail="Razorpay holds payments or refunds the ledger cannot explain. "
            "Resolve each by hand: runbooks/topup-payments.md §5.",
            ids=",".join(report.unexplained[:_ID_LIMIT]),
        )


__all__ = ["UNCAPTURED_AFTER", "ReconciliationReport", "reconcile"]
