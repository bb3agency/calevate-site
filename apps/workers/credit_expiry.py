"""The daily job that lapses pack credit past its expiry, and the email that warns before it
(D-840, `billing/credit_expiry.py`).

    expire_credit_lots      daily, IST — one tenant_session per organization, then one
                             transaction per due lot, then the lapse notices it owes
    notify_credit_lapsing   from the outbox, once per lot

Each lot is expired in its own transaction under the tenant's credit lock, and the ledger row
is keyed per lot, so a retried or doubled tick expires nothing twice. The admin role reads the
directory only (hard rule 1), as `workers/number_rental.py` does.

THE NOTICE IS PROMISED, NOT SENT, BY THE SWEEP: each open lot with credit left that lapses
within `LAPSE_NOTICE_WINDOW` gets one outbox row keyed `credit_lapse_notice:<lot_id>`
(`enqueue_outbox_once`), so a daily sweep that sees the same lot thirty times promises one
email. The job re-reads the lot before sending and says nothing about one already spent or
closed.

Hard rule 6: ids and counts in every log line and alarm; never the address.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import ladder_delay_s
from sqlalchemy import text

from apps.api.billing import lots as credit_lots
from apps.api.billing.credit_expiry import (
    due_lots,
    expire_lot,
    lapse_notice_key,
    lapsing_lots,
)
from apps.api.billing.display import display_inr
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.transport import get_transport
from apps.api.db.session import admin_session, tenant_session
from apps.api.reliability.service import enqueue_outbox_once
from apps.workers.auth_email import CONSOLE_BASE
from apps.workers.email_render import from_text
from apps.workers.trial_notices import ist_moment

log = get_logger(__name__)

_ALL_TENANTS = "SELECT id FROM organizations WHERE deleted_at IS NULL ORDER BY id"

#: The outbox job the sweep promises; `check_job_wiring` resolves it through this constant.
CREDIT_LAPSE_NOTICE_JOB: Final = "notify_credit_lapsing"

RETRY_BACKOFF_S: tuple[float, ...] = (60.0, 300.0)

#: subject, heading, preheader. No figure in the subject: it shows in a lock-screen preview.
LAPSE_NOTICE_COPY: Final = (
    "Some of your calling credit lapses soon",
    "Some of your credit lapses soon",
    "Use it before the date below, or it is removed from your balance.",
)


async def _promise_lapse_notices(tenant_id: UUID, *, now: datetime) -> int:
    """Promise one email for each lot of this tenant that lapses inside the window."""
    promised = 0
    async with tenant_session(tenant_id) as scoped:
        for lot in await lapsing_lots(scoped, now=now):
            message_id = await enqueue_outbox_once(
                scoped,
                job=CREDIT_LAPSE_NOTICE_JOB,
                payload={"tenant_id": str(tenant_id), "lot_id": str(lot.lot_id)},
                dedupe_key=lapse_notice_key(lot.lot_id),
            )
            promised += 1 if message_id is not None else 0
    return promised


async def expire_credit_lots(ctx: dict[str, Any]) -> str:
    """Lapse every due lot's remaining credit, tenant by tenant, then promise the notices for
    lots lapsing soon. One failure is counted and alarmed, never allowed to stop the rest."""
    now = datetime.now(UTC)
    async with admin_session() as directory:
        tenants = [UUID(str(t)) for t in (await directory.execute(text(_ALL_TENANTS))).scalars()]
    expired = failed = promised = notice_failed = 0
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as scoped:
            due = await due_lots(scoped, now=now)
        for lot_id in due:
            try:
                async with tenant_session(tenant_id) as scoped:
                    done = await expire_lot(scoped, tenant_id=tenant_id, lot_id=lot_id, now=now)
                expired += 1 if done is not None else 0
            except Exception as exc:
                failed += 1
                log.error(
                    "credit_lot_expiry_failed",
                    extra={"lot_id": str(lot_id), "error": exc.__class__.__name__},
                )
        try:
            promised += await _promise_lapse_notices(tenant_id, now=now)
        except Exception as exc:
            notice_failed += 1
            log.error(
                "credit_lapse_notice_promise_failed",
                extra={"tenant_id": str(tenant_id), "error": exc.__class__.__name__},
            )
    if failed:
        alert(
            "WORKER_TERMINAL",
            "credit_expiry_incomplete",
            detail=(
                f"{failed} credit lot(s) past their expiry could not be expired; their "
                "credit is still spendable. The next daily run tries them again."
            ),
        )
    if notice_failed:
        alert(
            "WORKER_DELIVERY",
            "credit_lapse_notice_promise_failed",
            detail=(
                f"{notice_failed} tenant(s) could not be checked for credit lapsing soon; "
                "the next daily run asks again."
            ),
        )
    summary = {
        "expired": expired,
        "failed": failed,
        "notices_promised": promised,
        "notice_failed": notice_failed,
    }
    log.info("credit_lots_expired", extra=summary)
    return str(summary)


def compose_lapse_notice(*, remaining: Decimal, expires_at: datetime, slug: str) -> str:
    """The email body, in a business owner's words. No vendor name."""
    lines = [
        f"{display_inr(remaining)} of your calling credit lapses on {ist_moment(expires_at)}.",
        "",
        "Credit still unused then is removed from your balance and is not refunded. Your "
        "calls always use your oldest credit first, so calls you make before then use this "
        "credit before any you bought later.",
        "",
        "See your credit and when each purchase lapses:",
        "",
        f"{CONSOLE_BASE}/c/{slug}/billing?tab=credits",
    ]
    return "\n".join(lines)


async def notify_credit_lapsing(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """One email for one lot about to lapse. Re-reads the lot, so credit spent or closed since
    the promise is not announced."""
    tenant_id = UUID(str(payload["tenant_id"]))
    lot_id = UUID(str(payload["lot_id"]))
    attempt = int(ctx.get("job_try", 1))
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        lot = await credit_lots.read_lot(session, lot_id=lot_id)
        if (
            lot is None
            or lot.closed_at is not None
            or lot.expires_at is None
            or lot.expires_at <= now
            or lot.credits_remaining <= 0
        ):
            return "nothing_to_lapse"
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
        alert("WORKER_DELIVERY", "credit_lapse_notice_no_billing_email")
        log.warning("credit_lapse_notice_no_address", extra={"tenant_id": str(tenant_id)})
        return "no_billing_email"
    subject, heading, preheader = LAPSE_NOTICE_COPY
    body = compose_lapse_notice(
        remaining=lot.credits_remaining, expires_at=lot.expires_at, slug=str(slug)
    )
    message = from_text(
        subject=subject, preheader=preheader, heading=heading, text=body, cta="See your credit"
    )
    transport = get_transport()
    address = str(billing_email)
    # Off the event loop: the SMTP transport is synchronous (`wallet_alerts`' reason).
    delivered = await asyncio.to_thread(
        lambda: transport.send(to=address, subject=subject, body=message.text, html=message.html)
    )
    if not delivered:
        log.warning(
            "credit_lapse_notice_send_failed",
            extra={"tenant_id": str(tenant_id), "lot_id": str(lot_id), "attempt": attempt},
        )
        raise Retry(defer=ladder_delay_s(RETRY_BACKOFF_S, attempt))
    log.info("credit_lapse_notice_sent", extra={"tenant_id": str(tenant_id), "lot_id": str(lot_id)})
    return "sent"


__all__ = [
    "CREDIT_LAPSE_NOTICE_JOB",
    "LAPSE_NOTICE_COPY",
    "compose_lapse_notice",
    "expire_credit_lots",
    "notify_credit_lapsing",
]
