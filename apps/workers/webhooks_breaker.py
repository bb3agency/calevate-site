"""The webhook breaker's two jobs (D-1049, `integrations/breaker.py` holds the rules).

* `pause_failing_endpoints` — hourly, every account: pause each destination whose every
  delivery has failed for three days, and promise its owner notice in the same transaction.
* `notify_endpoint_paused` — the notice, once per pause: a bell item (an announcement for
  this one account, posted on the first run so a retried email never posts a second) and an
  email to the billing address and the live owners, retried on the email ladder. The shape
  is `campaign_archive_notice`'s, an operator-side act told to the client by both channels.

The client's words name the destination by its host (or "your Google Sheet", "your
LeadSquared"), never by its full address: a webhook URL's path routinely carries a key.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import ladder_delay_s
from sqlalchemy import text

from apps.api.announcements import service as announcements
from apps.api.announcements.schemas import AnnouncementIn
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES, job_try
from apps.api.core.transport import EmailPurpose, get_transport
from apps.api.db.session import admin_session, tenant_session
from apps.api.integrations import breaker
from apps.workers.account_closure import account_recipients
from apps.workers.email_render import from_text
from apps.workers.fleet_walk import WalkBudget, resumed_walk

log = get_logger(__name__)

NOTICE_JOB: Final = breaker.PAUSED_NOTICE_JOB
#: Hourly, at a minute no other fleet-wide walk uses (`tests/job_registration_test.py`).
BREAKER_SWEEP_MINUTE: Final = 34
RETRY_BACKOFF_S: Final[tuple[float, ...]] = (30.0, 120.0)
#: How long the bell item shows; Resume is on the Integrations page whatever it says.
IN_APP_DAYS: Final = 7

_DIRECTORY: Final = "SELECT id FROM organizations WHERE deleted_at IS NULL ORDER BY id"


async def pause_failing_endpoints(ctx: dict[str, Any]) -> str:
    del ctx
    async with admin_session() as directory:
        tenants = [UUID(str(t)) for t in (await directory.execute(text(_DIRECTORY))).scalars()]
    paused = failed = probed = 0
    budget = WalkBudget()
    async for tenant_id in resumed_walk("webhook_breaker", tenants, budget):
        probed += 1
        try:
            async with tenant_session(tenant_id) as session:
                paused += len(await breaker.pause_tripped(session, tenant_id=tenant_id))
        except Exception as exc:
            failed += 1
            log.error(
                "webhook_breaker_tenant_failed",
                extra={"tenant_id": str(tenant_id), "error": type(exc).__name__},
            )
    if failed or probed < len(tenants):
        alert(
            "WORKER_TERMINAL",
            "webhook_breaker_incomplete",
            detail=(
                f"{failed} account(s) failed and {len(tenants) - probed} were not reached; "
                "a destination failing for three days may still be sent to. The next hourly "
                "run tries them again."
            ),
        )
    return f"paused={paused} failed={failed} probed={probed}"


def destination_words(kind: str, url: str | None) -> str:
    """How the client's notice names the destination."""
    if kind == "google_sheets":
        return "your Google Sheet"
    if kind == "leadsquared":
        return "your LeadSquared"
    host = urlsplit(url or "").hostname
    return f"your address at {host}" if host else "your webhook address"


def compose(*, business: str, destination: str, since: datetime | None) -> tuple[str, str]:
    """(subject, body). What stopped, that nothing is lost, and the one button."""
    subject = f"We paused sending to {destination}"
    started = f" since {since.astimezone(UTC).strftime('%d %b %Y')}" if since is not None else ""
    body = "\n".join(
        [
            f"Every delivery from {business} to {destination} has failed{started}, so we "
            "have paused it.",
            "",
            "Nothing is lost. We keep every new lead and call result for it, and send them "
            "in order when you resume.",
            "",
            "Fix the destination, then open Integrations and press Resume. You can send a "
            "test first to check it works.",
        ]
    )
    return subject, body


async def notify_endpoint_paused(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    endpoint_id = UUID(str(payload["endpoint_id"]))
    attempt = job_try(ctx)
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT w.kind, w.url, w.failing_since, w.paused_at, o.name, o.slug "
                    "FROM outbound_webhooks w JOIN organizations o ON o.id = w.tenant_id "
                    "WHERE w.id = :id"
                ),
                {"id": endpoint_id},
            )
        ).first()
        if row is None or row[3] is None:
            # Resumed (or switched off) before the notice ran: there is nothing to tell.
            return "not_paused"
        kind, url, since, _paused_at, business, slug = row
        recipients = await account_recipients(session, tenant_id=tenant_id)
    destination = destination_words(str(kind), url)
    subject, body = compose(business=str(business), destination=destination, since=since)

    if attempt == 1:
        async with admin_session() as session:
            await announcements.create(
                session,
                AnnouncementIn(
                    message=f"{subject}. Nothing is lost: resume it on Integrations.",
                    link_url=f"/c/{slug}/integrations",
                    link_label="Open Integrations",
                    tone="warning",
                    audience="tenant",
                    target_tenant_id=tenant_id,
                    ends_at=datetime.now(UTC) + timedelta(days=IN_APP_DAYS),
                ),
                admin_user_id=None,
            )

    email = from_text(subject=subject, preheader=subject, heading=subject, text=body)
    transport = get_transport(EmailPurpose.NOTIFICATIONS)
    delivered = [
        address
        for address in recipients
        if await asyncio.to_thread(
            transport.send, to=address, subject=email.subject, body=email.text, html=email.html
        )
    ]
    if delivered:
        log.info(
            "endpoint_paused_notice_sent",
            extra={"tenant_id": str(tenant_id), "recipients": len(delivered)},
        )
        return "sent"
    if not recipients:
        alert(
            "WORKER_TERMINAL",
            "endpoint_paused_notice_no_channel",
            detail="a paused destination's owner has no billing email and no active owner",
            tenant_id=str(tenant_id),
        )
        return "no_channel"
    if attempt < WORKER_MAX_TRIES:
        raise Retry(defer=ladder_delay_s(RETRY_BACKOFF_S, attempt))
    alert(
        "WORKER_DELIVERY",
        "endpoint_paused_notice_exhausted",
        detail=f"paused-destination email undelivered after {attempt} attempt(s)",
        tenant_id=str(tenant_id),
    )
    return f"exhausted after {attempt}"


__all__ = [
    "BREAKER_SWEEP_MINUTE",
    "NOTICE_JOB",
    "compose",
    "destination_words",
    "notify_endpoint_paused",
    "pause_failing_endpoints",
]
