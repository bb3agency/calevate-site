"""Notification delivery (post-call pipeline step 5, FLOWS §6).

Email first, WhatsApp next — that ordering is from ROADMAP M1 and it is a
deliberate scope cut, not an oversight: WhatsApp needs a template approval cycle that
client #1 does not have to wait for.

Every notification arrives here through the OUTBOX, so this function may be retried
with the same payload at any time. It therefore has to be safe to run twice — the
dedupe key is the lead event row it writes.

Hard rule 6 applies with full force: a notification is the easiest place to
accidentally put a phone number into a log line or a third-party API. The body is
assembled from redacted values only.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.redaction import redact

log = get_logger(__name__)

HOT_LEAD_SUBJECT = "Hot lead from your AI receptionist"


async def notify_hot_lead(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    lead_id = UUID(str(payload["lead_id"]))
    call_id = UUID(str(payload["call_id"]))

    async with tenant_session(tenant_id) as session:
        # Idempotence: if we already recorded a notification for this lead+call, stop.
        already = (
            await session.execute(
                text(
                    "SELECT 1 FROM lead_events WHERE lead_id = :lid AND type = 'notification' "
                    "AND payload->>'call_id' = :cid LIMIT 1"
                ),
                {"lid": lead_id, "cid": str(call_id)},
            )
        ).first()
        if already:
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

        body = _compose(name, phone, status, summary, payload.get("triggers") or [])
        delivered = await _send_email(billing_email, HOT_LEAD_SUBJECT, body)

        await session.execute(
            text(
                "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                "created_at, updated_at) VALUES (:id, :tid, :lid, 'notification', "
                "CAST(:payload AS jsonb), 'system', now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "lid": lead_id,
                "payload": _json(
                    {
                        "call_id": str(call_id),
                        "channel": "email",
                        "delivered": delivered,
                        "triggers": payload.get("triggers") or [],
                    }
                ),
            },
        )
    return "sent" if delivered else "queued_no_channel"


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


async def _send_email(to: str | None, subject: str, body: str) -> bool:
    """Delivery is not wired to a provider yet (M1 ops task). Until it is, this logs a
    structured record and reports FALSE rather than pretending success — a silent
    'sent' would make the hot-lead SLO look met when nobody was told."""
    if not to:
        log.warning("notification_no_channel")
        return False
    log.info("notification_pending_transport", extra={"subject": subject, "chars": len(body)})
    return False


def _json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)


__all__ = ["notify_hot_lead"]
