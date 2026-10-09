"""Razorpay background work (D-699): auto-recharge, reconciliation, client payment emails.

- `sweep_auto_recharge` (every five minutes): fails charges Razorpay never answered,
  reads the state of mandates whose `token.*` webhook has not arrived, and starts a
  recharge for each wallet below its threshold. One recharge in flight per tenant is a
  database fact (`ux_auto_recharge_charges_one_pending`), so two overlapping sweeps cannot
  double-charge.
- `reconcile_razorpay` (daily): `billing/reconciliation.reconcile`.
- `send_payment_notice` (outbox job `auto_recharge.PAYMENT_NOTICE_JOB`): the client email
  for a recharge started, captured or failed, a mandate confirmed or ended, and
  auto-recharge switched off. The words are the client's view: no internals, and Razorpay
  is named only as the payment gateway.

Every sweep is bounded: it walks `auto_recharge_settings` rows (opted-in tenants only),
never the whole fleet.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final
from uuid import UUID

from arq import Retry
from sqlalchemy import text

from apps.api.billing.auto_recharge import (
    due_tenants,
    expire_unanswered,
    maybe_start_recharge,
    pending_mandates,
    refresh_pending_mandate,
)
from apps.api.billing.payments import payment_capability
from apps.api.billing.reconciliation import reconcile
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.transport import get_transport
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers.auth_email import CONSOLE_BASE
from apps.workers.email_render import from_text

log = get_logger(__name__)

#: Minutes past the hour the recharge sweep runs, clear of :00/:30.
AUTO_RECHARGE_MINUTES: Final = frozenset({2, 7, 12, 17, 22, 27, 32, 37, 42, 47, 52, 57})
#: The reconciliation's daily slot, UTC (07:55 IST, before the working day).
RECONCILE_HOUR_UTC: Final = 2
RECONCILE_MINUTE: Final = 25

_RETRY_S: Final = (60.0, 300.0, 900.0)


async def sweep_auto_recharge(ctx: dict[str, Any]) -> dict[str, int]:
    """One pass. A tenant whose recharge fails does not stop the others."""
    if not payment_capability().creates_orders:
        return {"skipped": 1}
    started = expired = refreshed = failed = 0
    async with untenanted_session() as session:
        pending_tenants = [
            UUID(str(r[0]))
            for r in (
                await session.execute(
                    text(
                        "SELECT DISTINCT tenant_id FROM auto_recharge_charges "
                        "WHERE status = 'pending' ORDER BY tenant_id"
                    )
                )
            ).all()
        ]
    for tenant_id in pending_tenants:
        expired += await expire_unanswered(tenant_id)
    for tenant_id, customer_id, token_id in await pending_mandates():
        try:
            if await refresh_pending_mandate(tenant_id, customer_id, token_id):
                refreshed += 1
        except ProblemError:
            log.warning("auto_recharge_mandate_refresh_failed", extra={"tenant_id": str(tenant_id)})
    for tenant_id in await due_tenants():
        try:
            outcome = await maybe_start_recharge(tenant_id)
        except Exception:
            log.exception("auto_recharge_start_crashed", extra={"tenant_id": str(tenant_id)})
            failed += 1
            continue
        started += outcome == "started"
        failed += outcome == "failed"
    return {"started": started, "expired": expired, "refreshed": refreshed, "failed": failed}


async def reconcile_razorpay(ctx: dict[str, Any]) -> dict[str, int]:
    if not payment_capability().creates_orders:
        return {"skipped": 1}
    try:
        report = await reconcile()
    except ProblemError as exc:
        alert("WORKER_DELIVERY", "razorpay_reconciliation_failed", problem_code=exc.code)
        raise
    return {
        "payments": report.payments_seen,
        "refunds": report.refunds_seen,
        "credited_late": len(report.credited_late),
        "unexplained": len(report.unexplained),
    }


_SUBJECTS: Final = {
    "recharge_started": "We are topping up your Calevate balance",
    "recharge_captured": "Your Calevate balance has been topped up",
    "recharge_failed": "Your automatic top-up did not go through",
    "auto_recharge_disabled": "Auto-recharge is now off",
    "mandate_confirmed": "Automatic top-ups are approved",
    "mandate_ended": "Your automatic top-up approval has ended",
}


def compose(kind: str, *, amount_inr: str | None, reason: str | None, slug: str) -> str:
    """The email body for one notice, in the client's words."""
    link = f"{CONSOLE_BASE}/c/{slug}/billing"
    amount = f"₹{amount_inr}" if amount_inr else "the recharge amount"
    if kind == "recharge_started":
        return (
            f"Your calling credit is below the level you set, so we are adding {amount} "
            "using the payment method you approved.\n\n"
            "Your bank or UPI app will send you a notice before the money is taken, as the "
            "rules for automatic payments require, and the payment usually completes within "
            "one to two days. Your calls keep running meanwhile.\n\n"
            f"To change or stop auto-recharge, go to {link}."
        )
    if kind == "recharge_captured":
        return f"{amount} has been added to your calling credit. The receipt is at {link}."
    if kind == "recharge_failed":
        return (
            f"We could not collect {amount} with your approved payment method, so your "
            "balance has not changed. Your calls keep running while you have credit.\n\n"
            f"You can add credit now, or check your payment method, at {link}."
        )
    if kind == "auto_recharge_disabled":
        return (
            f"{reason or 'Auto-recharge has been turned off.'}\n\n"
            f"Add credit yourself, or set up a payment method again, at {link}."
        )
    if kind == "mandate_confirmed":
        return (
            "Your payment method is approved for automatic top-ups. Turn auto-recharge on "
            f"and choose your amounts at {link}."
        )
    return (
        f"{reason or 'Your automatic top-up approval has ended.'} Auto-recharge is off.\n\n"
        f"You can approve a payment method again at {link}."
    )


async def send_payment_notice(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    kind = str(payload["kind"])
    if kind not in _SUBJECTS:
        log.warning("payment_notice_unknown_kind", extra={"kind": kind})
        return "unknown_kind"
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT billing_email, slug FROM organizations WHERE id = :tid"),
                {"tid": tenant_id},
            )
        ).first()
    if row is None:
        return "tenant_missing"
    billing_email, slug = row
    if not billing_email:
        alert("WORKER_DELIVERY", "payment_notice_no_billing_email", tenant_id=str(tenant_id))
        return "no_billing_email"
    body = compose(
        kind,
        amount_inr=payload.get("amount_inr"),
        reason=payload.get("reason"),
        slug=str(slug),
    )
    subject = _SUBJECTS[kind]
    message = from_text(
        subject=subject, preheader=subject, heading=subject, text=body, cta="Open billing"
    )
    transport = get_transport()
    delivered = await asyncio.to_thread(
        lambda: transport.send(
            to=str(billing_email), subject=subject, body=message.text, html=message.html
        )
    )
    if not delivered:
        attempt = int(ctx.get("job_try", 1))
        raise Retry(defer=_RETRY_S[min(attempt, len(_RETRY_S)) - 1])
    log.info("payment_notice_sent", extra={"tenant_id": str(tenant_id), "kind": kind})
    return "sent"


__all__ = [
    "AUTO_RECHARGE_MINUTES",
    "RECONCILE_HOUR_UTC",
    "RECONCILE_MINUTE",
    "compose",
    "reconcile_razorpay",
    "send_payment_notice",
    "sweep_auto_recharge",
]
