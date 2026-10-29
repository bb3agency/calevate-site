"""Tell my team (D-904): send a team address its code, and tell the team about a caller, by
email or, through the client's own WhatsApp connection, on WhatsApp.

Both arrive through the OUTBOX (`apps/api/team_alerts/service.py` queues them in the
transaction that made the promise), so both may run more than once. The alert's dedupe is its
own row: `team_alerts.status = 'sent'` answers "already done" for any later run.

A send that fails is retried on the same short ladder as the hot-lead email, and an exhausted
ladder raises an alarm, because a team that was never told is the failure this exists to stop.

Hard rule 6: no address, number, name or problem text reaches a log line or an alert; ids and
the recipient's domain only. The FULL number goes in the alert body on purpose; the module
docstring of `team_alerts/service.py` records why.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import ladder_delay_s
from sqlalchemy import text

from apps.api.billing.plans import IST
from apps.api.compliance.audit import write_audit
from apps.api.core.alerting import alert
from apps.api.core.console_links import CONSOLE_BASE
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.transport import EmailPurpose, get_transport
from apps.api.crm.service import redacted_summary
from apps.api.db.session import tenant_session
from apps.api.team_alerts import whatsapp as team_whatsapp
from apps.workers.email_render import Email, from_text

log = get_logger(__name__)

#: Same pacing as `notifications.RETRY_BACKOFF_S`: a person is waiting to ring a caller back.
RETRY_BACKOFF_S: Final[tuple[float, ...]] = (15.0, 45.0)
#: The code email has someone looking at a screen for it, so the auth email's ladder.
CODE_RETRY_BACKOFF_S: Final[tuple[float, ...]] = (10.0, 30.0)

ALERT_SUBJECT: Final = "A caller needs your team"
CODE_SUBJECT: Final = "Your code for caller alerts"

_DESTINATION_COLUMNS: Final = (
    "tc.channel, tc.address, tc.whatsapp_credential_id, tc.whatsapp_template, "
    "tc.whatsapp_language, tc.whatsapp_number_id, tc.whatsapp_values"
)


@dataclass(frozen=True, slots=True)
class _Destination:
    channel: str
    address: str
    credential_id: UUID | None
    template: str | None
    language: str | None
    number_id: str | None
    slots: tuple[str, ...]


def _destination(row: Any) -> _Destination:
    return _Destination(
        channel=str(row[0]),
        address=str(row[1]),
        credential_id=row[2],
        template=row[3],
        language=row[4],
        number_id=row[5],
        slots=tuple(str(s) for s in (row[6] or [])),
    )


_ALERT_SQL: Final = (
    "SELECT ta.status, ta.trigger, ta.reasons, ta.call_id, ta.agent_id, "
    f"{_DESTINATION_COLUMNS}, tc.verified_at IS NOT NULL AND tc.removed_at IS NULL "
    "AND (tc.channel = 'email' OR tc.whatsapp_credential_id IS NOT NULL), "
    # The own-language summary while the English is still being written (D-931).
    "c.direction, c.from_e164, c.to_e164, COALESCE(c.started_at, c.created_at), "
    "COALESCE(c.summary, c.summary_local), "
    "a.name, o.name, o.slug, "
    "COALESCE(l.name, (SELECT lp.name FROM leads lp WHERE lp.agent_id = ta.agent_id "
    "  AND lp.phone_e164 = CASE WHEN c.direction = 'outbound' THEN c.to_e164 ELSE c.from_e164 END "
    "  AND lp.deleted_at IS NULL ORDER BY lp.updated_at DESC LIMIT 1)) "
    "FROM team_alerts ta "
    "JOIN team_alert_contacts tc ON tc.id = ta.contact_id "
    "JOIN calls c ON c.id = ta.call_id "
    "JOIN agents a ON a.id = ta.agent_id "
    "JOIN organizations o ON o.id = ta.tenant_id "
    "LEFT JOIN leads l ON l.id = c.lead_id "
    "WHERE ta.id = :id FOR UPDATE OF ta"
)


async def send_team_contact_code(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Mail a team address the code that proves it is reachable."""
    attempt = int(ctx.get("job_try", 1) or 1)
    tenant_id = UUID(str(payload["tenant_id"]))
    contact_id = UUID(str(payload["contact_id"]))
    code = str(payload.get("code", ""))
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT tc.verified_at IS NOT NULL, tc.removed_at IS NOT NULL, o.name, "
                    f"{_DESTINATION_COLUMNS} FROM team_alert_contacts tc JOIN organizations o "
                    "ON o.id = tc.tenant_id WHERE tc.id = :id"
                ),
                {"id": contact_id},
            )
        ).first()
        if row is None or row[0] or row[1] or not code:
            return "not_needed"
        business = str(row[2] or "your business")
        destination = _destination(row[3:])
        if destination.channel == "whatsapp":
            delivered = await _whatsapp(
                session,
                tenant_id,
                destination,
                {
                    "name": f"{_one_line(business)} caller alerts",
                    "phone": destination.address,
                    "why": f"Your code is {code}. Enter it within 30 minutes.",
                    "link": CONSOLE_BASE,
                },
            )
        else:
            message = from_text(
                subject=CODE_SUBJECT,
                preheader="Enter this code to receive caller alerts.",
                heading="Confirm this address",
                text=compose_code(business, code),
            )
            delivered = await _email(
                destination.address, CODE_SUBJECT, message, purpose=EmailPurpose.SECURITY
            )
    if delivered:
        log.info("team_contact_code_sent", extra={"contact_id": str(contact_id)})
        return "sent"
    log.warning(
        "team_contact_code_undelivered",
        extra={"contact_id": str(contact_id), "channel": destination.channel, "attempt": attempt},
    )
    if attempt < WORKER_MAX_TRIES:
        raise Retry(defer=ladder_delay_s(CODE_RETRY_BACKOFF_S, attempt))
    alert(
        "WORKER_DELIVERY",
        "team_contact_code_exhausted",
        detail=f"team address code undelivered after {attempt} attempt(s)",
        tenant_id=str(tenant_id),
        contact_id=str(contact_id),
    )
    return f"exhausted after {attempt}"


def compose_code(business: str, code: str) -> str:
    name = _one_line(business)
    return "\n".join(
        [
            f"Someone at {name} added this address to hear about callers who need a person.",
            "",
            f"Your code: {code}",
            "",
            "Enter it on the Tell my team screen within 30 minutes. If you were not expecting "
            "this, ignore it and nothing will be sent here.",
        ]
    )


async def deliver_team_alert(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Tell the team about one caller, once."""
    attempt = int(ctx.get("job_try", 1) or 1)
    tenant_id = UUID(str(payload["tenant_id"]))
    alert_id = UUID(str(payload["alert_id"]))
    problem = str(payload.get("problem") or "")
    ids = {"tenant_id": str(tenant_id), "alert_id": str(alert_id)}

    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text(_ALERT_SQL), {"id": alert_id})).first()
        if row is None:
            return "alert_missing"
        (
            status,
            trigger,
            reasons,
            call_id,
            agent_id,
            *destination_row,
            reachable,
            direction,
            from_e164,
            to_e164,
            at,
            summary,
            agent_name,
            business,
            slug,
            caller_name,
        ) = row
        if status == "sent":
            return "duplicate"
        if status in ("failed", "cancelled"):
            return str(status)
        if not reachable:
            # The address was removed (or its verification undone) after the alert was queued.
            await _finish(session, alert_id, "cancelled", attempt)
            return "cancelled"
        destination = _destination(destination_row)
        phone = str((to_e164 if direction == "outbound" else from_e164) or "")
        link = f"{CONSOLE_BASE}/c/{slug}/calls/{call_id}"
        if destination.channel == "whatsapp":
            why = "; ".join(
                [line for line in (_reason_line(r) for r in reasons or []) if line]
                + ([f"Agent noted: {_one_line(problem)}"] if problem else [])
            )
            delivered = await _whatsapp(
                session,
                tenant_id,
                destination,
                {
                    "name": _one_line(caller_name) or "not captured",
                    "phone": phone or "not recorded",
                    "why": why or "Needs your team",
                    "link": link,
                },
            )
        else:
            body = compose_alert(
                agent_name=str(agent_name or "Your agent"),
                caller_name=caller_name,
                phone=phone,
                at=at,
                reasons=list(reasons or []),
                problem=problem,
                summary=redacted_summary(summary) if trigger != "in_call" else None,
                link=link,
            )
            delivered = await _send(destination.address, body, business=str(business or ""))
        if delivered:
            await _finish(session, alert_id, "sent", attempt)
            await write_audit(
                session,
                action="team_alert.sent",
                actor_type="system",
                tenant_id=tenant_id,
                object_type="call",
                object_id=str(call_id),
                summary={
                    "alert_id": str(alert_id),
                    "agent_id": str(agent_id),
                    "attempts": str(attempt),
                },
            )
        elif attempt >= WORKER_MAX_TRIES:
            await _finish(session, alert_id, "failed", attempt)
            await write_audit(
                session,
                action="team_alert.failed",
                actor_type="system",
                tenant_id=tenant_id,
                object_type="call",
                object_id=str(call_id),
                summary={
                    "alert_id": str(alert_id),
                    "agent_id": str(agent_id),
                    "attempts": str(attempt),
                },
            )
        else:
            await session.execute(
                text("UPDATE team_alerts SET attempts = :n, updated_at = now() WHERE id = :id"),
                {"n": attempt, "id": alert_id},
            )

    if delivered:
        log.info("team_alert_sent", extra={**ids, "attempts": attempt})
        return "sent"
    if attempt < WORKER_MAX_TRIES:
        raise Retry(defer=ladder_delay_s(RETRY_BACKOFF_S, attempt))
    alert(
        "WORKER_DELIVERY",
        "team_alert_exhausted",
        detail=f"team alert undelivered after {attempt} attempt(s)",
        **ids,
    )
    return f"exhausted after {attempt}"


async def _finish(session: Any, alert_id: UUID, status: str, attempt: int) -> None:
    await session.execute(
        text(
            "UPDATE team_alerts SET status = CAST(:status AS varchar), attempts = :n, "
            "sent_at = CASE WHEN CAST(:status AS varchar) = 'sent' THEN now() ELSE sent_at END, "
            "updated_at = now() WHERE id = :id"
        ),
        {"status": status, "n": attempt, "id": alert_id},
    )


def _reason_line(reason: dict[str, Any]) -> str | None:
    kind = reason.get("kind")
    if kind == "outcome":
        return f"Call ended as: {_one_line(str(reason.get('label') or reason.get('key') or ''))}"
    if kind == "field":
        values = ", ".join(_one_line(str(v)) for v in reason.get("values") or [])
        return f"{_one_line(str(reason.get('label') or reason.get('key') or ''))}: {values}"
    if kind == "follow_up":
        return f"Follow-up: {_one_line(str(reason.get('why') or ''))}"
    return None


def compose_alert(
    *,
    agent_name: str,
    caller_name: str | None,
    phone: str,
    at: datetime | None,
    reasons: list[dict[str, Any]],
    problem: str,
    summary: str | None,
    link: str,
) -> str:
    """The alert's text. `email_render.from_text` reads its structure: a blank line starts a
    paragraph and a paragraph that is one URL becomes the button, so every untrusted value is
    put on one line first."""
    when = at.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST") if at else "not recorded"
    lines = [
        f"{_one_line(agent_name)} needs someone from your team to follow up with a caller.",
        "",
        f"Name: {_one_line(caller_name) or 'not captured'}",
        f"Phone: {phone or 'not recorded'}",
        f"Call time: {when}",
    ]
    lines += [line for line in (_reason_line(r) for r in reasons) if line]
    if problem:
        lines.append(f"What the agent noted: {_one_line(problem)}")
    spoken = _without_blank_lines(summary) if summary else ""
    if spoken:
        lines += ["", "Call summary:", spoken]
    lines += ["", "Open the call to hear it and see the details:", "", link]
    return "\n".join(lines)


async def _send(to: str, body: str, *, business: str) -> bool:
    message = from_text(
        subject=ALERT_SUBJECT,
        preheader=f"A caller of {_one_line(business) or 'yours'} is waiting to hear from you.",
        heading="A caller needs your team",
        text=body,
        cta="Open the call",
    )
    return await _email(to, ALERT_SUBJECT, message, purpose=EmailPurpose.ALERTS)


async def _email(to: str, subject: str, message: Email, *, purpose: EmailPurpose) -> bool:
    transport = get_transport(purpose)
    return await asyncio.to_thread(
        lambda: transport.send(to=to, subject=subject, body=message.text, html=message.html)
    )


async def _whatsapp(
    session: Any, tenant_id: UUID, destination: _Destination, values: dict[str, str]
) -> bool:
    """Through the client's own WhatsApp connection and template only (founder, 27 Oct)."""
    if destination.credential_id is None or not destination.template:
        return False
    return await team_whatsapp.send(
        session,
        tenant_id=tenant_id,
        credential_id=destination.credential_id,
        number_e164=destination.address,
        template=destination.template,
        language=destination.language,
        number_id=destination.number_id,
        body_values=[values.get(slot, "") for slot in destination.slots],
    )


def _one_line(value: str | None) -> str:
    return " ".join((value or "").split())


def _without_blank_lines(value: str) -> str:
    return "\n".join(line for line in value.splitlines() if line.strip())


__all__ = [
    "ALERT_SUBJECT",
    "compose_alert",
    "compose_code",
    "deliver_team_alert",
    "send_team_contact_code",
]
