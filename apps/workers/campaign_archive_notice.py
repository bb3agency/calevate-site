"""Telling a client that Calevate archived or deleted one of their campaigns (F-10).

The founder's words (5 Nov 2026): "if an admin does it the client will be alerted in app and
over a mail and whatsapp too". One outbox job, promised in the same transaction as the
operator's act (BACKEND-PATTERNS §4), carries all three, the shape `account_closure.
notify_account_closed` already uses for an operator's act on a client's account:

- **In the app**: a notice for this one client on the console strip and the bell
  (`announcements`, audience `tenant`), on the first run only so a retried email never posts
  a second one. It ends by itself after `IN_APP_DAYS`.
- **Email**: the channel of record and never optional, to the billing address and the
  account's live owners (`account_closure.account_recipients`), retried on the email ladder.
- **WhatsApp**: Calevate's own channel to the owner, only where the owner has a live grant
  in `whatsapp_alert_optin_ledger` (`whatsapp.resolve_destination`), never to anyone who has
  not opted in, never retried, and only once the email has landed or its ladder is spent.

No campaign or account id reaches the client's words: the campaign is named by its own name
and the business by its own. No address or number reaches a log line (hard rule 6).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import ladder_delay_s
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.announcements import service as announcements
from apps.api.announcements.schemas import AnnouncementIn
from apps.api.compliance.audit import write_audit
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES, job_try
from apps.api.core.settings import get_settings
from apps.api.core.transport import EmailPurpose, _domain, get_transport
from apps.api.db.session import admin_session, tenant_session
from apps.api.reliability.service import enqueue_outbox
from apps.workers.account_closure import account_recipients
from apps.workers.email_render import from_text
from apps.workers.whatsapp import (
    SendStatus,
    WhatsAppMessage,
    get_whatsapp_transport,
    resolve_destination,
)

log = get_logger(__name__)

NOTICE_JOB: Final = "notify_campaign_archived"

EVENT_ARCHIVED: Final = "archived"
EVENT_DELETED: Final = "deleted"
EVENTS: Final = frozenset({EVENT_ARCHIVED, EVENT_DELETED})

#: Seconds before each email retry, as the closure notice: one shorter than the budget.
RETRY_BACKOFF_S: Final[tuple[float, ...]] = (30.0, 120.0)

#: How long the in-app notice shows before it ends by itself.
IN_APP_DAYS: Final = 14

#: The WhatsApp template body a human must submit to Meta for approval, kept next to the
#: code that fills it (the construction `account_closure.TEMPLATE_ACCOUNT_CLOSED` uses), and
#: NOT YET APPROVED:
#:
#:     "Calevate: a campaign on the {{1}} account was changed by our team. Check your email
#:      for what changed and why."
#:
#: ONE variable, the client's own business name (Meta requires a business-initiated message
#: to say who it is about). The campaign name and the reason stay in the email and the app:
#: a template variable must not carry free text an operator typed.
#:
#: EXTERNAL BLOCKER: usable only once approved in the WhatsApp Business account; until then
#: `whatsapp_enabled` is off, this leg answers "disabled", and the email is the notice.
TEMPLATE_CAMPAIGN_CHANGED: Final = "calevate_campaign_changed_v1"


def subject(event: str, campaign: str) -> str:
    return (
        f"We archived your campaign “{campaign}”"
        if event == EVENT_ARCHIVED
        else f"We deleted your draft campaign “{campaign}”"
    )


def compose(*, event: str, business: str, campaign: str, reason: str) -> str:
    """The email body, in the client's terms: what happened, why, what it did NOT touch,
    and what they can do. The operator's reason is quoted as written: it is the answer to
    the one question this email raises."""
    if event == EVENT_ARCHIVED:
        lines = [
            f"Our team archived the campaign “{campaign}” on the {business} account.",
            "",
            f"Why: {reason}",
            "",
            "It no longer calls anyone. Its calls, leads and charges are all kept.",
            "You can see it under Archived on your Campaigns page, and Restore brings it back.",
        ]
    else:
        lines = [
            f"Our team deleted the draft campaign “{campaign}” on the {business} account.",
            "",
            f"Why: {reason}",
            "",
            "It had not called anyone, so no calls or charges were affected.",
        ]
    lines += ["", "If you did not expect this, reply to this email."]
    return "\n".join(lines)


def in_app_message(event: str, campaign: str, reason: str) -> str:
    did = "archived" if event == EVENT_ARCHIVED else "deleted"
    line = f"Our team {did} your campaign “{campaign}”. Why: {reason}"
    return line[:280]


async def enqueue_campaign_notice(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    event: str,
    campaign: str,
    reason: str,
    slug: str,
) -> None:
    """Promise the client's notice in the caller's transaction (the operator's act and the
    promise to tell commit together). The campaign's NAME rides in the payload because a
    deleted campaign has no row left to read it from."""
    await enqueue_outbox(
        session,
        job=NOTICE_JOB,
        payload={
            "tenant_id": str(tenant_id),
            "event": event,
            "campaign": campaign,
            "reason": reason,
            "slug": slug,
        },
    )


async def _post_in_app(
    *, tenant_id: UUID, event: str, campaign: str, reason: str, slug: str
) -> None:
    async with admin_session() as session:
        await announcements.create(
            session,
            AnnouncementIn(
                message=in_app_message(event, campaign, reason),
                link_url=f"/c/{slug}/campaigns"
                + ("?archived=1" if event == EVENT_ARCHIVED else ""),
                link_label="Open campaigns",
                tone="warning",
                audience="tenant",
                target_tenant_id=tenant_id,
                ends_at=datetime.now(UTC) + timedelta(days=IN_APP_DAYS),
            ),
            admin_user_id=None,
        )


async def notify_campaign_archived(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    event = str(payload.get("event") or "")
    campaign = " ".join(str(payload.get("campaign") or "").split()) or "a campaign"
    reason = " ".join(str(payload.get("reason") or "").split())
    slug = str(payload.get("slug") or "")
    if event not in EVENTS:
        alert(
            "WORKER_TERMINAL",
            "campaign_notice_unknown_event",
            detail="campaign archive notice payload named an event this worker does not send",
            tenant_id=str(tenant_id),
        )
        return "unknown_event"
    attempt = job_try(ctx)

    if attempt == 1 and slug:
        # The first run only: a retry exists to deliver the email, and a second in-app
        # notice for one act reads as a second act.
        await _post_in_app(
            tenant_id=tenant_id, event=event, campaign=campaign, reason=reason, slug=slug
        )

    async with tenant_session(tenant_id) as session:
        business = (
            await session.execute(
                text("SELECT name FROM organizations WHERE id = :tid"), {"tid": tenant_id}
            )
        ).scalar()
        if business is None:
            alert(
                "WORKER_TERMINAL",
                "campaign_notice_tenant_missing",
                detail="campaign archive notice queued for an organisation that cannot be read",
                tenant_id=str(tenant_id),
            )
            return "tenant_missing"
        recipients = await account_recipients(session, tenant_id=tenant_id)
        title = subject(event, campaign)
        email = from_text(
            subject=title,
            preheader=title,
            heading=title,
            text=compose(event=event, business=str(business), campaign=campaign, reason=reason),
        )
        transport = get_transport(EmailPurpose.NOTIFICATIONS)
        delivered = [
            address
            for address in recipients
            if await asyncio.to_thread(
                transport.send, to=address, subject=email.subject, body=email.text, html=email.html
            )
        ]
        if delivered:
            await write_audit(
                session,
                action=f"campaign.notice_{event}",
                actor_type="system",
                tenant_id=tenant_id,
                object_type="organization",
                object_id=str(tenant_id),
                summary={
                    "channel": "email",
                    "recipients": len(delivered),
                    "domains": sorted({_domain(address) for address in delivered}),
                },
            )
        whatsapp = (
            await _whatsapp_leg(session, tenant_id=tenant_id, business=str(business))
            if delivered or attempt >= WORKER_MAX_TRIES or not recipients
            else None
        )

    if whatsapp:
        log.info(
            "campaign_notice_whatsapp", extra={"tenant_id": str(tenant_id), "outcome": whatsapp}
        )
    if delivered:
        log.info(
            "campaign_notice_sent",
            extra={"tenant_id": str(tenant_id), "event": event, "recipients": len(delivered)},
        )
        return "sent"
    if not recipients:
        alert(
            "WORKER_TERMINAL",
            "campaign_notice_no_channel",
            detail="client has no billing address and no active owner for a campaign notice",
            tenant_id=str(tenant_id),
        )
        return "no_channel"
    if attempt < WORKER_MAX_TRIES:
        raise Retry(defer=ladder_delay_s(RETRY_BACKOFF_S, attempt))
    alert(
        "WORKER_DELIVERY",
        "campaign_notice_exhausted",
        detail=f"campaign archive notice undelivered after {attempt} attempt(s)",
        tenant_id=str(tenant_id),
    )
    return f"exhausted after {attempt}"


async def _whatsapp_leg(session: AsyncSession, *, tenant_id: UUID, business: str) -> str:
    """The opted-in nudge beside the email, or a word saying why there was none. Three
    refusals, all closed: the channel off, no owner number, no live opt-in grant."""
    if not get_settings().whatsapp_enabled:
        return "disabled"
    destination = await resolve_destination(session, tenant_id)
    if destination is None:
        return "no_recipient"
    if destination.opt_in_at is None:
        return "not_opted_in"
    # The transport is built AFTER the opt-in is established (`scripts/check_compliance_
    # invariants.unevidenced_messages` requires the `opt_in_at` guard above the sender).
    transport = get_whatsapp_transport()
    result = await transport.send(
        WhatsAppMessage(
            to_e164=destination.to_e164,
            template=TEMPLATE_CAMPAIGN_CHANGED,
            locale=get_settings().whatsapp_template_locale,
            variables=(business,),
        )
    )
    return "delivered" if result.status is SendStatus.DELIVERED else f"undelivered:{result.status}"


__all__ = [
    "EVENT_ARCHIVED",
    "EVENT_DELETED",
    "NOTICE_JOB",
    "TEMPLATE_CAMPAIGN_CHANGED",
    "compose",
    "enqueue_campaign_notice",
    "notify_campaign_archived",
]
