"""Forwarded lines (D-746): settling a forwarding test, hanging its legs up, the quiet-line
sweep, and the once-per-caller "save our number" WhatsApp.

The test's own logic lives in `apps/api/forwarding/testing.py`; these are its jobs. The send
is here rather than beside it because the transport is a worker's (`workers/whatsapp.py`).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.models import WHATSAPP_MESSAGE_UNIT_TYPE
from apps.api.campaigns.engine_numbers import live_tenants
from apps.api.compliance.consent import read_messaging_consent
from apps.api.compliance.service import check_dispatch
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.forwarding import quiet
from apps.api.forwarding.save_number import TEMPLATE, caller_ref, locale_for
from apps.api.forwarding.testing import (
    ARRIVAL_WINDOW,
    SETTLE_JOB,
    hang_up_legs,
    settle_test,
)
from apps.api.ingest.service import normalize_phone
from apps.workers.whatsapp import (
    Destination,
    SendStatus,
    WhatsAppMessage,
    get_whatsapp_transport,
)

log = get_logger(__name__)

#: The hourly sweep's minute: one no other fleet-wide walk uses.
FORWARDING_SWEEP_MINUTE: Final = 26
#: A test still `placing` this long after it was created never got its legs reported.
STALE_PLACING_S: Final = 600


def _ids(payload: dict[str, Any]) -> tuple[UUID, UUID]:
    return UUID(str(payload["tenant_id"])), UUID(str(payload["test_id"]))


async def settle_forwarding_test(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id, test_id = _ids(payload)
    return await settle_test(tenant_id, test_id)


async def hang_up_forwarding_test(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id, test_id = _ids(payload)
    return f"ended:{await hang_up_legs(tenant_id, test_id)}"


async def _fail_unplaced(session: AsyncSession) -> None:
    """Fail a test that never got its legs placed (the process died between)."""
    await session.execute(
        text(
            "UPDATE forwarding_tests SET status = 'failed', outcome = 'not_placed', "
            "failure_code = 'placing_abandoned', settled_at = now(), updated_at = now() "
            "WHERE status = 'placing' AND created_at < now() - make_interval(secs => :s)"
        ),
        {"s": STALE_PLACING_S},
    )
    # A line left reading "testing" by such a test goes back to what its last finished
    # test said.
    await session.execute(
        text(
            "UPDATE forwarded_lines l SET status = COALESCE((SELECT CASE WHEN t.outcome = "
            "'arrived' THEN 'working' ELSE 'not_working' END FROM forwarding_tests t "
            "WHERE t.id = l.last_test_id), 'untested'), updated_at = now() "
            "WHERE l.status = 'testing' AND NOT EXISTS (SELECT 1 FROM forwarding_tests f "
            "WHERE f.line_id = l.id AND f.status IN ('placing', 'ringing'))"
        )
    )


async def sweep_forwarded_lines(ctx: dict[str, Any]) -> str:
    """Hourly: open or close quiet-line episodes, and settle tests whose job was lost."""
    quiet_lines = late = 0
    for tenant_id in await live_tenants():
        async with tenant_session(tenant_id) as session:
            has_lines = (
                await session.execute(text("SELECT EXISTS (SELECT 1 FROM forwarded_lines)"))
            ).scalar()
            if not has_lines:
                continue
            outcome = await quiet.sweep_tenant(session, tenant_id=tenant_id)
            quiet_lines += outcome == "quiet"
            await _fail_unplaced(session)
            stale = (
                await session.execute(
                    text(
                        "SELECT id FROM forwarding_tests WHERE status = 'ringing' "
                        "AND window_ends_at < now() - make_interval(secs => :s)"
                    ),
                    {"s": ARRIVAL_WINDOW.total_seconds()},
                )
            ).all()
        for (test_id,) in stale:
            await settle_test(tenant_id, UUID(str(test_id)))
            late += 1
    log.info("forwarded_lines_swept", extra={"quiet": quiet_lines, "late_settled": late})
    return f"quiet:{quiet_lines} late:{late}"


# --- "save our number" ---------------------------------------------------------------------


async def _claim_caller(
    session: AsyncSession, *, tenant_id: UUID, ref: str, call_id: UUID
) -> UUID | None:
    """The once-ever claim: one row per caller per client. None when one exists already."""
    row = (
        await session.execute(
            text(
                "INSERT INTO save_number_messages (id, tenant_id, caller_ref, call_id, status) "
                "VALUES (:id, :tid, :ref, :cid, 'queued') "
                "ON CONFLICT (tenant_id, caller_ref) DO NOTHING RETURNING id"
            ),
            {"id": uuid7(), "tid": tenant_id, "ref": ref, "cid": call_id},
        )
    ).first()
    return UUID(str(row[0])) if row else None


async def _finish(
    session: AsyncSession,
    message_id: UUID,
    *,
    status: str,
    code: str | None,
    language: str | None,
) -> None:
    await session.execute(
        text(
            "UPDATE save_number_messages SET status = :status, refusal_code = :code, "
            "language = :lang, sent_at = CASE WHEN :sent THEN now() ELSE NULL END, "
            "updated_at = now() WHERE id = :id"
        ),
        {
            "id": message_id,
            "status": status,
            "code": code,
            "lang": language,
            "sent": status == "sent",
        },
    )


async def _meter_message(session: AsyncSession, *, tenant_id: UUID, message_id: UUID) -> None:
    price: Decimal | None = get_settings().whatsapp_message_inr
    await session.execute(
        text(
            "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, unit_cost_paid, "
            "ref, occurred_at, meta, created_at) VALUES (:id, :tid, NULL, :unit, 1, :cost, :ref, "
            "now(), CAST(:meta AS jsonb), now()) ON CONFLICT (tenant_id, unit_type, ref) "
            "WHERE ref IS NOT NULL AND call_id IS NULL DO NOTHING"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "unit": WHATSAPP_MESSAGE_UNIT_TYPE,
            "cost": price,
            "ref": f"save-number:{message_id}",
            "meta": '{"kind": "save_number"}',
        },
    )


async def send_save_number_message(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Gate, claim, send, meter, in that order. Every refusal is recorded on the claim row
    so the caller is not tried again; a transport failure that may pass is released."""
    tenant_id = UUID(str(payload["tenant_id"]))
    call_id = UUID(str(payload["call_id"]))
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT o.save_number_message_enabled, o.name, c.agent_id, c.direction, "
                    "c.from_e164, c.to_e164, c.summary_language, l.phone_e164, c.caller_id_hidden "
                    "FROM calls c JOIN organizations o ON o.id = c.tenant_id "
                    "LEFT JOIN leads l ON l.id = c.lead_id WHERE c.id = :cid"
                ),
                {"cid": call_id},
            )
        ).first()
        if row is None or not row[0]:
            return "switched_off"
        _enabled, business, agent_id, direction, from_e, to_e, language, lead_phone, hidden = row
        # The caller is the lead's number when the network hid theirs; ours is the other end.
        caller = lead_phone if hidden else (from_e if direction == "inbound" else to_e)
        ours = to_e if direction == "inbound" else from_e
        if not caller or not ours or normalize_phone(str(caller)) is None:
            return "no_number"
        from apps.api.agents.service import resolve_caller_id

        calling = await resolve_caller_id(session, agent_id=agent_id) or ours
        message_id = await _claim_caller(
            session, tenant_id=tenant_id, ref=caller_ref(tenant_id, str(caller)), call_id=call_id
        )
        if message_id is None:
            return "already_sent"
        locale = locale_for(language)
        decision = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164=str(caller),
            dlt_governed=False,
        )
        if not decision.allowed:
            await _finish(
                session,
                message_id,
                status="refused",
                code=f"blocked_{decision.rule}",
                language=locale,
            )
            return "refused"
        consent = await read_messaging_consent(session, tenant_id=tenant_id, raw_phone=str(caller))
        destination = Destination(
            to_e164=str(caller), opt_in_at=consent.captured_at if consent.messageable else None
        )
        if destination.opt_in_at is None:
            await _finish(
                session,
                message_id,
                status="refused",
                code="recipient_not_opted_in",
                language=locale,
            )
            return "not_opted_in"
        result = await get_whatsapp_transport().send(
            WhatsAppMessage(
                to_e164=destination.to_e164,
                template=TEMPLATE,
                locale=locale,
                variables=(str(business), str(calling)),
            )
        )
        if result.status is SendStatus.DELIVERED:
            await _finish(session, message_id, status="sent", code=None, language=locale)
            await _meter_message(session, tenant_id=tenant_id, message_id=message_id)
            log.info(
                "save_number_sent", extra={"tenant_id": str(tenant_id), "call_id": str(call_id)}
            )
            return "sent"
        if result.retryable:
            # Released, so the outbox's retry can claim this caller again.
            await session.execute(
                text("DELETE FROM save_number_messages WHERE id = :id"), {"id": message_id}
            )
            raise RuntimeError("save_number_transport_failed")
        await _finish(
            session, message_id, status="failed", code=result.reason[:64], language=locale
        )
        return "failed"


__all__ = [
    "FORWARDING_SWEEP_MINUTE",
    "SETTLE_JOB",
    "hang_up_forwarding_test",
    "send_save_number_message",
    "settle_forwarding_test",
    "sweep_forwarded_lines",
]
