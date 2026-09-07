"""The dead-letter queue: what it may STORE about a failure, and what an erasure reaches.

**TWO DEFECTS, ONE TABLE.**

1. **`last_error` was an unredacted exception message in a durable column.** Three call
   sites in `reliability/service.py` wrote `error[:500]` straight into
   `outbox_messages.last_error` and `webhook_inbox_events.last_error`. That is not a log,
   so `JsonFormatter` never sees it and `core.logging.redact_exception` — whose whole
   verdict is that an exception MESSAGE can never be shown to be safe — never ran. A
   driver raising on a lead INSERT quotes its bound parameters; `pydantic.ValidationError`
   renders `input_value=…` by design. A 500-character cap is not a control, and hard rule
   6 has no length exemption.

2. **The payload the job carries was in no erasure path.** `outbox_messages.payload` is
   the outbound CRM delivery body itself — a lead's name, number and extracted fields
   (`integrations/service.py`; `db/registry.py` says so at length) — and the table has no
   `tenant_id`, so every tenant-scoped arm of both erasures was structurally blind to it.
   `prune_reliability_tables` only deletes `published` rows, so a DEAD LETTER holding one
   person's lead sits there for ever, waiting for an operator replay that would deliver an
   erased person's record to a CRM.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance.deletion import request_erasure
from apps.api.compliance.tenant_erasure import request_tenant_erasure
from apps.api.core.logging import MESSAGE_WITHHELD
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.reliability.service import (
    defer_outbox_claim,
    mark_inbox_failed,
    mark_outbox_failed,
)
from apps.workers.retention import execute_deletion_request, execute_tenant_erasure
from sqlalchemy import text

pytestmark = pytest.mark.anyio

#: What a driver puts in `str(exc)` when a lead INSERT fails: the bound parameters, which
#: are the lead. Distinctive enough that its survival anywhere is unmistakable.
LEAK = (
    "IntegrityError: duplicate key value violates unique constraint\n"
    "[SQL: INSERT INTO leads (name, phone_e164) VALUES (%s, %s)]\n"
    "[parameters: ('Padma Reddy', '+919876500123')]"
)


def _phone() -> str:
    return f"+9198762{uuid.uuid4().int % 100000:05d}"


async def _tenant() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="DLQ Clinic",
        slug=f"dlq-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


async def _outbox_row(
    *, tenant_id: uuid.UUID | None, phone: str | None, status: str = "failed"
) -> uuid.UUID:
    """One outbox message shaped as `integrations/service.py` writes an outbound CRM
    delivery: the lead's own fields, inline, under the tenant that owns them."""
    message_id = uuid7()
    payload: dict[str, Any] = {"event": "lead.created", "data": {"name": "Padma Reddy"}}
    if tenant_id is not None:
        payload["tenant_id"] = str(tenant_id)
    if phone is not None:
        payload["data"]["phone_e164"] = phone
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO outbox_messages (id, queue, job, payload, status, "
                "attempt_count, created_at, updated_at) VALUES (:i, 'default', "
                "'deliver_outbound_webhook', CAST(:p AS jsonb), :s, 0, now(), now())"
            ),
            {"i": message_id, "p": json.dumps(payload), "s": status},
        )
    return message_id


async def _outbox(message_id: uuid.UUID) -> Any:
    async with untenanted_session() as session:
        return (
            await session.execute(
                text("SELECT last_error FROM outbox_messages WHERE id = :i"), {"i": message_id}
            )
        ).first()


async def _erase_subject(tenant_id: uuid.UUID, phone: str) -> str:
    async with tenant_session(tenant_id) as session:
        record = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    return await execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(record.id)}
    )


# ============================================================================
# 1. What may be stored about a failure
# ============================================================================


async def test_a_dead_letter_never_stores_the_exception_message() -> None:
    """THE REGRESSION. The TYPE survives — it is what an operator triages on — and the
    message, which is where the bound parameters are, does not."""
    message_id = await _outbox_row(tenant_id=None, phone=None, status="pending")

    async with untenanted_session() as session:
        await mark_outbox_failed(session, message_id=message_id, error=LEAK, attempt_count=9)

    row = await _outbox(message_id)
    assert row is not None
    stored = str(row[0])
    assert "Padma Reddy" not in stored, "the lead's name is in the dead-letter row"
    assert "+919876500123" not in stored, "the lead's phone number is in the dead-letter row"
    assert "INSERT INTO leads" not in stored, "the failing statement quoted its parameters"
    assert stored == f"IntegrityError: {MESSAGE_WITHHELD}", stored


async def test_a_deferred_claim_stores_no_message_either() -> None:
    """`defer_outbox_claim` writes the same column from the same kind of string, and a
    fix that reached only one of the three call sites would be no fix."""
    message_id = await _outbox_row(tenant_id=None, phone=None, status="pending")

    async with untenanted_session() as session:
        await defer_outbox_claim(session, message_ids=[message_id], error=LEAK)

    row = await _outbox(message_id)
    assert row is not None
    assert "Padma Reddy" not in str(row[0]) and MESSAGE_WITHHELD in str(row[0])


async def test_the_inbox_failure_column_is_the_same_door() -> None:
    """`webhook_inbox_events.last_error` is written by the third call site, and the same
    reasoning applies to it verbatim."""
    row_id = uuid7()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO webhook_inbox_events (id, provider, event_key, payload_hash, "
                "status, created_at, updated_at) VALUES (:i, 'bolna', :k, 'sha256:x', "
                "'processing', now(), now())"
            ),
            {"i": row_id, "k": f"evt-{uuid.uuid4().hex}"},
        )
        await mark_inbox_failed(session, row_id=row_id, error=LEAK)
        stored = (
            await session.execute(
                text("SELECT last_error FROM webhook_inbox_events WHERE id = :i"), {"i": row_id}
            )
        ).scalar()
    assert "Padma Reddy" not in str(stored) and MESSAGE_WITHHELD in str(stored)


async def test_an_authored_refusal_code_still_reaches_the_operator() -> None:
    """The half a blunt fix would break. `ingest/routes.py` and `pipeline.py` pass
    AUTHORED codes — never vendor prose — and they are the ops console's only account of
    why a row failed. Withholding those would trade one defect for another."""
    row_id = uuid7()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO webhook_inbox_events (id, provider, event_key, payload_hash, "
                "status, created_at, updated_at) VALUES (:i, 'meta', :k, 'sha256:x', "
                "'processing', now(), now())"
            ),
            {"i": row_id, "k": f"evt-{uuid.uuid4().hex}"},
        )
        await mark_inbox_failed(session, row_id=row_id, error="agent ref not mapped")
        stored = (
            await session.execute(
                text("SELECT last_error FROM webhook_inbox_events WHERE id = :i"), {"i": row_id}
            )
        ).scalar()
    assert stored == "agent ref not mapped", stored


async def test_a_phone_number_inside_an_authored_reason_is_still_masked() -> None:
    """The fallback pass is `redact_text`, not "anything authored is safe"."""
    row_id = uuid7()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO webhook_inbox_events (id, provider, event_key, payload_hash, "
                "status, created_at, updated_at) VALUES (:i, 'meta', :k, 'sha256:x', "
                "'processing', now(), now())"
            ),
            {"i": row_id, "k": f"evt-{uuid.uuid4().hex}"},
        )
        await mark_inbox_failed(session, row_id=row_id, error="no consent for 9876500123")
        stored = (
            await session.execute(
                text("SELECT last_error FROM webhook_inbox_events WHERE id = :i"), {"i": row_id}
            )
        ).scalar()
    assert "9876500123" not in str(stored), stored


# ============================================================================
# 2. What an erasure reaches
# ============================================================================


async def test_an_erasure_deletes_the_dead_letter_holding_this_person() -> None:
    """THE SECOND REGRESSION. The row is filed under no call and no lead of ours — the
    delivery never succeeded — so no tenant-scoped arm could see it, and nothing prunes a
    `failed` row. An operator replay of it would deliver an erased person to a CRM."""
    tenant_id = await _tenant()
    phone = _phone()
    message_id = await _outbox_row(tenant_id=tenant_id, phone=phone)

    result = await _erase_subject(tenant_id, phone)

    assert "outbox=1" in result, result
    assert await _outbox(message_id) is None, "the dead letter still holds this person's lead"


async def test_a_queued_delivery_cannot_fire_after_the_certificate_was_issued() -> None:
    """`_erase_scheduled_callbacks`' argument, one table along: a `pending` row is work
    that has not happened yet, and it names somebody we have just certified as erased."""
    tenant_id = await _tenant()
    phone = _phone()
    message_id = await _outbox_row(tenant_id=tenant_id, phone=phone, status="pending")

    await _erase_subject(tenant_id, phone)

    assert await _outbox(message_id) is None


async def test_another_tenants_queue_is_never_touched() -> None:
    """The table has no RLS policy, so the tenant predicate is the whole of the scoping
    and a bug here would delete a stranger's queued work."""
    mine, theirs = await _tenant(), await _tenant()
    phone = _phone()
    ours = await _outbox_row(tenant_id=mine, phone=phone)
    # The same number, filed under a DIFFERENT tenant: a shared phone is ordinary, and
    # one client's erasure may not reach another client's records.
    other = await _outbox_row(tenant_id=theirs, phone=phone)

    await _erase_subject(mine, phone)

    assert await _outbox(ours) is None
    assert await _outbox(other) is not None, "another tenant's queued job was deleted"


async def test_a_bystanders_message_survives() -> None:
    """The digits matcher over-matches by design, but it still has to match: an unrelated
    job for the same tenant must not be deleted by somebody else's erasure."""
    tenant_id = await _tenant()
    subject, bystander = _phone(), _phone()
    mine = await _outbox_row(tenant_id=tenant_id, phone=subject)
    theirs = await _outbox_row(tenant_id=tenant_id, phone=bystander)

    await _erase_subject(tenant_id, subject)

    assert await _outbox(mine) is None
    assert await _outbox(theirs) is not None


async def test_the_certificate_names_the_queued_jobs() -> None:
    """SEC-COMP §4 again: a store the erasure reaches is enumerated in the document, in
    `actions`, which passes through verbatim."""
    tenant_id = await _tenant()
    phone = _phone()
    await _outbox_row(tenant_id=tenant_id, phone=phone)

    await _erase_subject(tenant_id, phone)

    async with tenant_session(tenant_id) as session:
        proof = (
            await session.execute(
                text("SELECT proof FROM deletion_requests ORDER BY created_at DESC LIMIT 1")
            )
        ).scalar()
    assert isinstance(proof, dict)
    sentence = proof["actions"]["outbox_messages"]
    assert sentence.startswith("1 queued or undelivered background job(s)"), sentence
    assert phone not in str(proof), "the proof quoted the number it certifies as erased"


async def test_offboarding_empties_the_queue_for_that_account() -> None:
    """When the subject is "all of them" there is nothing to match on — `copilot_memories`'
    reasoning — and a pending job would otherwise fire against an organisation whose
    certificate says it holds nothing."""
    tenant_id = await _tenant()
    dead = await _outbox_row(tenant_id=tenant_id, phone=_phone())
    queued = await _outbox_row(tenant_id=tenant_id, phone=None, status="pending")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned' WHERE id = :t"), {"t": tenant_id}
        )
        record = await request_tenant_erasure(session, tenant_id=tenant_id, reason="offboarding")

    await execute_tenant_erasure({}, {"tenant_id": str(tenant_id), "request_id": str(record.id)})

    assert await _outbox(dead) is None
    assert await _outbox(queued) is None
