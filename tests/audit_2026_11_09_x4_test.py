"""Backend audit round 4, lane X4 (compliance and personal data), 9 Nov 2026.

X4-01: a client's WhatsApp follow-up to a lead stored Meta's `wamid.` message id on the
lead's timeline, and a failed-delivery webhook queued the same id. That id is base64 of a
record holding the recipient's number in clear, and `lead_events` is exempt from both
erasures on the ground that no producer writes a number, so an erased person's number
stayed on file under a certificate saying it was gone.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

from apps.api.crm import swipe
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.whatsapp import webhooks
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.lead_assignment_test import _the_lead

#: The shape Meta answers a send with, for a message to +91 98765 43210 (the example id
#: in the voice platform's own send-message reference, `thinnest-findings/mirror/
#: snapshots/2026-10-13/pages/api-reference/messages/send-message.md:455`).
WAMID = "wamid.HBgMOTE5ODc2NTQzMjEwFQIAERgSQjM2RDVGMEU4QzA3RjE2QTYA"
NUMBER_DIGITS = "919876543210"


STEM = "d9a4e7c2b1f6_lead_timeline_keeps_no_whatsapp_message_id"


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_whatsapp_message_id_carries_the_recipients_number() -> None:
    """The premise: the id is not opaque."""
    decoded = base64.b64decode(WAMID.removeprefix("wamid."))
    assert NUMBER_DIGITS.encode() in decoded


async def _payloads(tenant_id: uuid.UUID, lead_id: uuid.UUID) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM lead_events WHERE lead_id = :lid "
                    "AND type = 'notification' ORDER BY created_at, id"
                ),
                {"lid": lead_id},
            )
        ).all()
    return [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]


def _holds_the_number(payload: dict[str, Any]) -> bool:
    flat = json.dumps(payload)
    return WAMID in flat or WAMID.removeprefix("wamid.")[:20] in flat or NUMBER_DIGITS in flat


async def test_a_leads_timeline_keeps_no_message_id_and_still_finds_the_failure() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    async with tenant_session(tenant_id) as session:
        await swipe.record_whatsapp_on_timeline(
            session,
            lead_id=lead_id,
            template="order_ready",
            out=swipe.WhatsAppSendOut(status="sent"),
            actor="system",
            message_id=WAMID,
        )
    async with tenant_session(tenant_id) as session:
        assert await swipe.record_whatsapp_not_delivered(
            session, ref=webhooks.message_ref(WAMID), meta_code="131026"
        )
    rows = await _payloads(tenant_id, lead_id)
    assert [r["status"] for r in rows] == ["sent", "failed"]
    for row in rows:
        assert not _holds_the_number(row), row
        assert row["message_ref"] == hashlib.sha256(WAMID.encode()).hexdigest()


async def test_the_migration_digests_a_stored_id_as_the_code_does() -> None:
    """A row written before the fix is rewritten to the digest `message_ref` computes, so a
    late failure report for an older send still lands on it."""
    migration = _revision()
    tenant_id, _slug, _token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                "created_at, updated_at) VALUES (:id, :tid, :lid, 'notification', "
                "CAST(:p AS jsonb), 'system', now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "lid": lead_id,
                "p": json.dumps(
                    {
                        "channel": "whatsapp",
                        "kind": "client_follow_up",
                        "status": "sent",
                        "template": "order_ready",
                        "message_id": WAMID,
                    }
                ),
            },
        )
        # The statement alone: the tenant's own policy scopes it here, where the migration
        # lifts FORCE to reach every tenant.
        await session.execute(text(migration._UPGRADE))
    [row] = await _payloads(tenant_id, lead_id)
    assert "message_id" not in row
    assert row["message_ref"] == webhooks.message_ref(WAMID)
    async with tenant_session(tenant_id) as session:
        assert await swipe.record_whatsapp_not_delivered(
            session, ref=webhooks.message_ref(WAMID), meta_code=None
        )


def test_a_failed_delivery_report_carries_no_message_id_into_the_queue() -> None:
    """The webhook's event is queued as an outbox job, which neither erasure reaches by the
    number because the job holds no tenant id; it must not carry the id either."""
    delivery = {
        "object": webhooks.WABA_OBJECT,
        "entry": [
            {
                "id": "123",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "statuses": [
                                {
                                    "id": WAMID,
                                    "status": "failed",
                                    "recipient_id": NUMBER_DIGITS,
                                    "errors": [{"code": 131026}],
                                }
                            ]
                        },
                    }
                ],
            }
        ],
    }
    [event] = webhooks.extract_events(delivery)
    assert event.kind == "send_failed"
    assert event.detail == {"message_ref": webhooks.message_ref(WAMID)}
    assert not _holds_the_number(event.payload())
