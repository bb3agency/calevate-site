"""Telling people about a KYC review: the client when it is decided, us when it waits.

- `notify_kyc_decision` (outbox job `kyc_review.KYC_DECISION_NOTICE_JOB`, promised in the
  decision's transaction): one short email to the account's owners and billing address.
  Approved says so; rejected gives the reviewer's reason and a button to the screen where
  the client fixes it. The record is re-read when the email is sent, so a decision the
  client has already answered with a new submission is not announced.
- `alarm_overdue_kyc_reviews` (every 30 minutes): `kyc_review_overdue` while any record has
  waited for a reviewer longer than `REVIEW_ALARM_AFTER`. A client waiting on us cannot
  place outbound calls. The alarm system mails a `page` once per episode, and an episode
  stays open while it is refreshed within `ALERT_CLEAR_AFTER_S` (an hour), so the
  30-minute tick keeps one episode open for as long as anything waits.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import ladder_delay_s
from sqlalchemy import text

from apps.api.compliance.kyc import read_kyc
from apps.api.compliance.kyc_review import KYC_DECISION_NOTICE_JOB, waiting_reviews
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.transport import EmailPurpose, get_transport
from apps.api.db.session import admin_session, tenant_session
from apps.workers.account_closure import account_recipients
from apps.workers.auth_email import CONSOLE_BASE
from apps.workers.email_render import from_text

log = get_logger(__name__)

JOB_NAME: Final = KYC_DECISION_NOTICE_JOB

#: How long a submitted review may wait before the alarm. docs/OPERATIONS.md states no
#: review time for KYC, so this is one day: a client cannot dial out until it is decided,
#: and an undecided owner-ID file is deleted 30 days after upload.
REVIEW_ALARM_AFTER: Final = timedelta(hours=24)
#: Minutes past the hour of the overdue check, IST (`settings.CRON_TIMEZONE`).
OVERDUE_MINUTES: Final = frozenset({9, 39})

_RETRY_S: Final = (60.0, 300.0, 900.0)

#: The decision -> (the status the record must still hold, subject).
_DECISIONS: Final = {
    "approve": ("verified", "Your business is verified"),
    "reject": ("rejected", "We could not verify your business"),
}


def compose_decision(decision: str, *, reason: str | None, slug: str) -> str:
    """The email body. Client-facing: short lines, no provider, no internal words."""
    link = f"{CONSOLE_BASE}/c/{slug}/verify-business"
    if decision == "approve":
        return (
            f"We checked your documents. Your business is verified.\n\nSee what is next:\n\n{link}"
        )
    return (
        "We checked your documents and could not verify your business yet.\n\n"
        f"What we found: {reason or 'something in your documents did not match.'}\n\n"
        "Fix it and send it again:\n\n"
        f"{link}"
    )


async def notify_kyc_decision(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    decision = str(payload["decision"])
    if decision not in _DECISIONS:
        log.warning("kyc_decision_notice_unknown", extra={"decision": decision})
        return "unknown_decision"
    expected, subject = _DECISIONS[decision]
    async with tenant_session(tenant_id) as session:
        slug = (
            await session.execute(
                text("SELECT slug FROM organizations WHERE id = :tid"), {"tid": tenant_id}
            )
        ).scalar()
        if slug is None:
            return "tenant_missing"
        record = await read_kyc(session, tenant_id=tenant_id)
        if record.status != expected:
            return "superseded"
        recipients = await account_recipients(session, tenant_id=tenant_id)
    if not recipients:
        alert("WORKER_DELIVERY", "kyc_decision_notice_no_address", tenant_id=str(tenant_id))
        return "no_address"
    body = compose_decision(decision, reason=record.rejection_reason, slug=str(slug))
    message = from_text(
        subject=subject,
        preheader=subject,
        heading=subject,
        text=body,
        cta="Open Verify your business" if decision == "approve" else "Fix and send again",
    )
    transport = get_transport(EmailPurpose.NOTIFICATIONS)
    delivered = 0
    for address in recipients:
        delivered += bool(
            await asyncio.to_thread(
                transport.send, to=address, subject=subject, body=message.text, html=message.html
            )
        )
    # Retried only when nobody got it: a retry after a partial send mails the addresses
    # that already have it a second time.
    if not delivered:
        raise Retry(defer=ladder_delay_s(_RETRY_S, int(ctx.get("job_try", 1))))
    log.info(
        "kyc_decision_notice_sent",
        extra={"tenant_id": str(tenant_id), "decision": decision, "delivered": delivered},
    )
    return "sent"


async def alarm_overdue_kyc_reviews(ctx: dict[str, Any]) -> str:
    """Raise `kyc_review_overdue` while any review has waited past `REVIEW_ALARM_AFTER`."""
    del ctx
    cutoff = datetime.now(UTC) - REVIEW_ALARM_AFTER
    async with admin_session() as session:
        waiting = await waiting_reviews(session)
    overdue = [
        w.submitted_at for w in waiting if w.submitted_at is not None and w.submitted_at < cutoff
    ]
    if overdue:
        oldest = min(overdue)
        hours = int((datetime.now(UTC) - oldest).total_seconds() // 3600)
        alert(
            "WORKER_STALL",
            "kyc_review_overdue",
            detail=(
                f"{len(overdue)} KYC review(s) have waited more than "
                f"{int(REVIEW_ALARM_AFTER.total_seconds() // 3600)} hours; the oldest "
                f"{hours} hours. Those clients cannot place outbound calls until a reviewer "
                "decides, and an undecided owner-ID file is deleted 30 days after upload. "
                "Decide them: /admin/kyc-reviews."
            ),
        )
    log.info("kyc_review_overdue_check", extra={"waiting": len(waiting), "overdue": len(overdue)})
    return f"waiting={len(waiting)} overdue={len(overdue)}"


__all__ = [
    "JOB_NAME",
    "OVERDUE_MINUTES",
    "REVIEW_ALARM_AFTER",
    "alarm_overdue_kyc_reviews",
    "compose_decision",
    "notify_kyc_decision",
]
