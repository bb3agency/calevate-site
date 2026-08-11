"""Notification delivery (post-call pipeline step 5, FLOWS §6).

Email first, WhatsApp next — that ordering is from ROADMAP M1 and it is a
deliberate scope cut, not an oversight: WhatsApp needs a template approval cycle that
client #1 does not have to wait for.

Every notification arrives here through the OUTBOX, so this function may be retried
with the same payload at any time. It therefore has to be safe to run twice — the
dedupe key is the lead event row it writes, and that row is a DELIVERED notification,
never merely an attempted one (see `_already_delivered`).

**A send that fails is retried, and an exhausted ladder is alerted.** This job used to
record `delivered: false`, return `"queued_no_channel"` and raise nothing: no ladder
ran, no operator heard, and a hot lead the client was never told about was
indistinguishable from one that arrived. That is the exact failure this notification
exists to prevent, so silence is the one outcome that is not allowed. The signal is
`arq.Retry` — arq 0.28 retries a job for `Retry`, `RetryJob` or `CancelledError` and
NOTHING else, so a plain raise here would be terminal on the first attempt and
`max_tries` decorative (`apps/workers/outbound_webhooks.py` documents the mechanism).

Not every failure earns a retry, though. A transport that could not deliver is a blip
worth another go; a tenant with no billing email is a DATA fix — the same row will be
just as empty in two minutes — so that one alerts immediately instead of burning the
ladder to reach the same verdict.

Hard rule 6 applies with full force: a notification is the easiest place to
accidentally put a phone number into a log line or a third-party API. The body is
assembled from redacted values only, and the alerts below carry ids, never addresses.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from arq import Retry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session
from apps.workers.redaction import redact
from apps.workers.transport import get_transport

log = get_logger(__name__)

HOT_LEAD_SUBJECT = "Hot lead from your AI receptionist"

# Seconds to wait before each retry, indexed by the attempt that just failed. One entry
# shorter than the budget, because the last attempt has nothing after it. Same shape
# and the same reasoning as `outbound_webhooks.RETRY_BACKOFF_S`, but tighter: this is
# the 2-minute hot-lead SLO, so the ladder has to finish inside a useful window rather
# than pace itself for a receiver that may be down for a while.
RETRY_BACKOFF_S: tuple[float, ...] = (15.0, 45.0)


def _retry_after(attempt: int) -> float:
    index = min(attempt, len(RETRY_BACKOFF_S)) - 1
    return RETRY_BACKOFF_S[max(index, 0)]


async def notify_hot_lead(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    lead_id = UUID(str(payload["lead_id"]))
    call_id = UUID(str(payload["call_id"]))
    triggers = payload.get("triggers") or []
    attempt = int(ctx.get("job_try", 1))

    async with tenant_session(tenant_id) as session:
        if await _already_delivered(session, lead_id=lead_id, call_id=call_id):
            return "duplicate"

        row = (
            await session.execute(
                text(
                    "SELECT l.name, l.phone_e164, l.status, c.summary, o.billing_email "
                    "FROM leads l JOIN calls c ON c.id = :cid "
                    "JOIN organizations o ON o.id = l.tenant_id WHERE l.id = :lid"
                ),
                {"lid": lead_id, "cid": call_id},
            )
        ).first()
        if row is None:
            return "lead_missing"
        name, phone, status, summary, billing_email = row

        if billing_email:
            body = _compose(name, phone, status, summary, triggers)
            delivered = await _send_email(billing_email, HOT_LEAD_SUBJECT, body)
        else:
            # Nothing to attempt: `_send_email` would only report the same thing back.
            delivered = False

        # Recorded whatever happened, and recorded ONCE per lead+call however many
        # attempts it takes — the timeline shows the outcome, not the ladder.
        await _record_attempt(
            session,
            tenant_id=tenant_id,
            lead_id=lead_id,
            call_id=call_id,
            delivered=delivered,
            attempts=attempt,
            triggers=triggers,
        )

    if delivered:
        # Ids only (hard rule 6). `attempts` is here because "delivered on the third
        # try" and "delivered immediately" are the same outcome and very different
        # health signals for a 2-minute SLO.
        log.info("hot_lead_notified", extra={"lead_id": str(lead_id), "attempts": attempt})
        return "sent"

    if not billing_email:
        # A data fix, not a blip. Retrying cannot conjure an address, so the ladder is
        # skipped and a human is told straight away — the lead is un-notified either
        # way, and only a person can close that.
        alert(
            "WORKER_TERMINAL",
            "hot_lead_no_channel",
            detail="tenant has no billing email; hot lead cannot be delivered",
            tenant_id=str(tenant_id),
            lead_id=str(lead_id),
        )
        return "no_channel"

    if attempt < WORKER_MAX_TRIES:
        # The one exception type arq treats as "not finished". The attempt row is
        # already committed — the session closed above — so the retry starts from a
        # recorded attempt rather than from nothing.
        raise Retry(defer=_retry_after(attempt))

    alert(
        "WORKER_DELIVERY",
        "hot_lead_notification_exhausted",
        detail=f"hot-lead email undelivered after {attempt} attempt(s)",
        tenant_id=str(tenant_id),
        lead_id=str(lead_id),
    )
    return f"exhausted after {attempt}"


async def _already_delivered(session: AsyncSession, *, lead_id: UUID, call_id: UUID) -> bool:
    """Has this lead+call notification actually REACHED someone?

    A recorded attempt is not an answer to that question. Treating one as a duplicate
    is what would make the retry ladder decorative: the second attempt would find the
    `delivered: false` row it wrote itself, report `duplicate`, and leave a timeline
    that claims the client was told.
    """
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM lead_events WHERE lead_id = :lid AND type = 'notification' "
                "AND payload->>'call_id' = :cid AND payload->>'delivered' = 'true' LIMIT 1"
            ),
            {"lid": lead_id, "cid": str(call_id)},
        )
    ).first()
    return row is not None


async def _record_attempt(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    lead_id: UUID,
    call_id: UUID,
    delivered: bool,
    attempts: int,
    triggers: list[str],
) -> None:
    """One timeline row per (lead, call), updated in place as the ladder walks.

    Update-then-insert rather than `ON CONFLICT`, because `lead_events` has no unique
    key for this shape (same pattern as `pipeline._persist_extraction`). `lead_events`
    is a timeline, not one of the append-only ledgers of hard rule 4, so flipping
    `delivered` to true when a retry finally lands is the honest record — and a
    notification that never landed stays visible as one instead of disappearing.
    """
    body = _json(
        {
            "call_id": str(call_id),
            "channel": "email",
            "delivered": delivered,
            "attempts": attempts,
            "triggers": triggers,
        }
    )
    updated = await session.execute(
        text(
            "UPDATE lead_events SET payload = CAST(:payload AS jsonb), updated_at = now() "
            "WHERE lead_id = :lid AND type = 'notification' AND payload->>'call_id' = :cid"
        ),
        {"payload": body, "lid": lead_id, "cid": str(call_id)},
    )
    if rowcount_of(updated) == 0:
        await session.execute(
            text(
                "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                "created_at, updated_at) VALUES (:id, :tid, :lid, 'notification', "
                "CAST(:payload AS jsonb), 'system', now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "lid": lead_id, "payload": body},
        )


def _compose(
    name: str | None, phone: str, status: str, summary: str | None, triggers: list[str]
) -> str:
    """The phone is masked even here. Staff open the lead in the CRM to see it, where
    the access is role-checked; an email forwarded outside the business is not."""
    masked = redact(phone).text
    lines = [
        f"A lead was marked {status} by your AI receptionist.",
        "",
        f"Name: {name or 'not captured'}",
        f"Phone: {masked}",
    ]
    if triggers:
        lines.append(f"Triggered by: {', '.join(triggers)}")
    if summary:
        lines += ["", "Call summary:", redact(summary).text]
    lines += ["", "Open the lead in your Calevate dashboard to call back."]
    return "\n".join(lines)


async def _send_email(to: str, subject: str, body: str) -> bool:
    """Delivery goes through the configured transport (`workers/transport.py`).

    Returns whether it landed; the CALLER decides what a failure costs, because only
    the caller knows which attempt this is. The no-address case never reaches here —
    it is a data fix and is alerted as one.
    """
    return get_transport().send(to=to, subject=subject, body=body)


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


__all__ = ["notify_hot_lead"]
