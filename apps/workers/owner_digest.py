"""Send each opted-in owner their daily summary (D-944, `notifications/daily_summary.py`).

Once a day at `SEND_HOUR`:`SEND_MINUTE` IST. For each account with the switch on, the IST day
is claimed with a compare-and-set on `organizations.owner_digest_sent_on` before anything is
sent, so a doubled tick or a retry sends one summary; when nothing was delivered the claim is
put back and the run raises `Retry`, which re-walks the list and reaches only the accounts
still unclaimed. A day with nothing in it (no call, no
lead, nothing waiting, nothing spent) sends nothing: a summary of zeros every evening teaches
the owner to ignore it.

Email to the owners and billing address (`account_recipients`), sender purpose NOTIFICATIONS
(`docs/EMAILS.md` N11). WhatsApp only through Calevate's own account, only while
`whatsapp_enabled`, and only to an owner whose opt-in is on file (`whatsapp.resolve_
destination`), with the counts-only template `whatsapp_template_owner_digest`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import ladder_delay_s
from sqlalchemy import text

from apps.api.billing.plans import IST
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.settings import get_settings
from apps.api.core.transport import EmailPurpose, get_transport
from apps.api.db.session import admin_session, tenant_session
from apps.api.notifications.daily_summary import (
    DailySummary,
    build_summary,
    email_facts,
    email_lines,
    email_subject,
    whatsapp_variables,
)
from apps.workers.account_closure import account_recipients
from apps.workers.email_render import Email, product_email
from apps.workers.whatsapp import WhatsAppMessage, get_whatsapp_transport, resolve_destination

log = get_logger(__name__)

#: 20:58 IST: after most businesses close, so the day is nearly whole. :58 is free of every
#: other fleet-wide walk (`tests/job_registration_test.py` checks it; :53 is the platform
#: fee sweep's).
SEND_HOUR: Final = 20
SEND_MINUTE: Final = 58
#: Seconds before each retry of a run that left an account undelivered.
RETRY_BACKOFF_S: Final = (300.0, 900.0)

_OPTED_IN = (
    "SELECT id FROM organizations WHERE deleted_at IS NULL AND owner_digest_enabled ORDER BY id"
)
#: The claim: only the first run of the day moves the stamp.
_CLAIM = text(
    "UPDATE organizations SET owner_digest_sent_on = :day "
    "WHERE deleted_at IS NULL AND owner_digest_enabled "
    "AND owner_digest_sent_on IS DISTINCT FROM :day RETURNING owner_digest_sent_on"
)
_RELEASE = text(
    "UPDATE organizations SET owner_digest_sent_on = :previous "
    "WHERE deleted_at IS NULL AND owner_digest_sent_on = :day"
)
_PREVIOUS = text("SELECT owner_digest_sent_on FROM organizations WHERE deleted_at IS NULL")


def compose_email(summary: DailySummary) -> Email:
    return product_email(
        subject=email_subject(summary),
        preheader=email_lines(summary)[0],
        heading="Your day on the phones",
        lines=email_lines(summary),
        facts=email_facts(summary),
        cta="Open your dashboard",
        url=summary.dashboard_url,
        reason=(
            f"You got this because the daily summary is on for {summary.business_name}. "
            "Turn it off in Notification settings."
        ),
        settings_url=summary.settings_url,
    )


async def _send_email(summary: DailySummary, recipients: list[str]) -> int:
    email = compose_email(summary)
    transport = get_transport(EmailPurpose.NOTIFICATIONS)
    delivered = 0
    for address in recipients:
        delivered += bool(
            await asyncio.to_thread(
                transport.send, to=address, subject=email.subject, body=email.text, html=email.html
            )
        )
    return delivered


async def send_one(tenant_id: UUID, *, day: date) -> str:
    """Claim, build, send, and release the claim when nothing landed."""
    async with tenant_session(tenant_id) as session:
        previous = (await session.execute(_PREVIOUS)).scalar()
        claimed = (await session.execute(_CLAIM, {"day": day})).first()
        if claimed is None:
            # Already claimed today, or the switch is off.
            return "not_claimed"
        summary = await build_summary(session, tenant_id=tenant_id, day=day)
        recipients = await account_recipients(session, tenant_id=tenant_id)
        destination = await resolve_destination(session, tenant_id)
    if summary.quiet:
        return "quiet"
    delivered = await _send_email(summary, recipients) if recipients else 0
    settings = get_settings()
    whatsapp_ok = settings.whatsapp_enabled
    if destination is None or destination.opt_in_at is None:
        # An opt-in we cannot evidence is not an opt-in (SEC-COMP §4).
        whatsapp_ok = False
    if whatsapp_ok and destination is not None:
        result = await get_whatsapp_transport().send(
            WhatsAppMessage(
                to_e164=destination.to_e164,
                template=settings.whatsapp_template_owner_digest,
                locale=settings.whatsapp_template_locale,
                variables=whatsapp_variables(summary),
            )
        )
        delivered += int(result.delivered)
    if not delivered:
        async with tenant_session(tenant_id) as session:
            await session.execute(_RELEASE, {"day": day, "previous": previous})
        return "undelivered"
    return "sent"


async def send_owner_digests(ctx: dict[str, Any]) -> str:
    """Every opted-in account, one at a time; one failure is counted, never allowed to stop
    the rest."""
    attempt = int(ctx.get("job_try", 1))
    day = datetime.now(UTC).astimezone(IST).date()
    async with admin_session() as directory:
        tenants = [UUID(str(t)) for t in (await directory.execute(text(_OPTED_IN))).scalars()]
    counts: dict[str, int] = {}
    failed = 0
    for tenant_id in tenants:
        try:
            outcome = await send_one(tenant_id, day=day)
        except Exception as exc:
            failed += 1
            log.error(
                "owner_digest_failed",
                extra={"tenant_id": str(tenant_id), "error": exc.__class__.__name__},
            )
            continue
        counts[outcome] = counts.get(outcome, 0) + 1
    undelivered = counts.get("undelivered", 0)
    if (failed or undelivered) and attempt < WORKER_MAX_TRIES:
        # Every account already sent keeps its claim, so the retry reaches only these.
        raise Retry(defer=ladder_delay_s(RETRY_BACKOFF_S, attempt))
    if failed or undelivered:
        alert(
            "WORKER_DELIVERY",
            "owner_digest_incomplete",
            detail=(
                f"{failed} account(s) failed and {undelivered} had no channel deliver their "
                f"daily summary after {attempt} tries; tomorrow's run sends the next one. "
                "Read owner_digest_failed in the logs for the error type."
            ),
        )
    summary = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    log.info("owner_digests_sent", extra={"accounts": len(tenants), "failed": failed, **counts})
    return f"accounts={len(tenants)} failed={failed} {summary}".strip()


__all__ = ["SEND_HOUR", "SEND_MINUTE", "compose_email", "send_one", "send_owner_digests"]
