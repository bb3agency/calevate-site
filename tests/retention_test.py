"""Retention and DPDP erasure (SEC-COMP §4, FLOWS §9).

These are legal obligations with a floor and a proof requirement, so the tests check
both directions: that data DOES go away when it should, and that the things which must
survive — the ledgers, the countable shells — are still there afterwards.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from apps.api.admin import service as admin_service
from apps.api.db.session import tenant_session
from apps.workers.retention import (
    RECORDING_FLOOR_DAYS,
    REDACTED_MARK,
    apply_retention,
    execute_deletion_request,
)
from sqlalchemy import text


async def _tenant_with_old_call(days_ago: int, phone: str) -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Retention Clinic",
        slug=f"ret-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    call_id = uuid.uuid4()
    when = datetime.now(UTC) - timedelta(days=days_ago)

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, recording_url, summary, "
                "created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', 'completed', :phone, "
                "'+911140000000', :when, :when, 90, 'recordings/x.wav', 'Booked an appointment', "
                ":when, :when)"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{call_id.hex[:10]}",
                "phone": phone,
                "when": when,
            },
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) VALUES (:i, :t, :c, 0, 'caller', "
                "'naaku appointment kavali', 'naaku appointment kavali', :w, :w)"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "c": call_id, "w": when},
        )
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, created_at, updated_at) VALUES (:i, :t, :a, :phone, 'Ravi', "
                "'inbound_call', 'new', '{\"intent\": \"book\"}'::jsonb, :w, :w)"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "a": agent_id, "phone": phone, "w": when},
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, created_at) VALUES (:i, :t, :c, 'platform_min', "
                "1.5, 2.6250, :w, :w)"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "c": call_id, "w": when},
        )
    return tenant_id, call_id


async def test_recordings_older_than_their_ttl_lose_their_pointer() -> None:
    tenant_id, call_id = await _tenant_with_old_call(200, "+919876500011")
    await apply_retention({})
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT recording_url, duration_s FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).first()
    assert row is not None
    assert row[0] is None, "the recording pointer is cleared once the TTL passes"
    assert row[1] == 90, "the call row survives — its metering must stay countable"


async def test_a_recording_inside_the_trai_floor_is_untouched() -> None:
    """The 90-day floor is enforced twice — a DB CHECK and this job — because deleting
    early is the violation that cannot be undone."""
    tenant_id, call_id = await _tenant_with_old_call(RECORDING_FLOOR_DAYS - 30, "+919876500012")
    await apply_retention({})
    async with tenant_session(tenant_id) as session:
        url = (
            await session.execute(
                text("SELECT recording_url FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).scalar()
    assert url == "recordings/x.wav"


async def test_retention_never_deletes_the_usage_ledger() -> None:
    """usage_events is append-only (hard rule 4) and a deleted call row would take its
    charges with it, silently rewriting a billing period."""
    tenant_id, call_id = await _tenant_with_old_call(500, "+919876500013")
    await apply_retention({})
    async with tenant_session(tenant_id) as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM usage_events WHERE call_id = :c"), {"c": call_id}
            )
        ).scalar()
    assert count == 1


async def test_erasure_removes_the_person_and_writes_a_proof() -> None:
    phone = "+919876500014"
    tenant_id, call_id = await _tenant_with_old_call(10, phone)
    request_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO deletion_requests (id, tenant_id, phone_e164, scope, requested_at, "
                "created_at) VALUES (:i, :t, :p, 'all', now(), now())"
            ),
            {"i": request_id, "t": tenant_id, "p": phone},
        )

    result = await execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    assert "erased" in result

    async with tenant_session(tenant_id) as session:
        call = (
            await session.execute(
                text("SELECT from_e164, recording_url, summary FROM calls WHERE id = :c"),
                {"c": call_id},
            )
        ).first()
        turns = (
            await session.execute(
                text("SELECT text, text_redacted FROM transcript_turns WHERE call_id = :c"),
                {"c": call_id},
            )
        ).all()
        leads = (
            await session.execute(
                text("SELECT phone_e164, name, data FROM leads WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).all()
        proof = (
            await session.execute(
                text("SELECT proof, completed_at FROM deletion_requests WHERE id = :i"),
                {"i": request_id},
            )
        ).first()

    assert call is not None and call[0] is None and call[1] is None and call[2] is None
    assert all(t[0] == REDACTED_MARK and t[1] == REDACTED_MARK for t in turns)
    assert all(phone not in lead[0] and lead[1] is None for lead in leads)

    assert proof is not None and proof[1] is not None, "the request is marked complete"
    document = proof[0] if isinstance(proof[0], dict) else json.loads(proof[0])
    # The proof must not BE another copy of the data it attests was removed.
    assert phone not in json.dumps(document)
    assert document["subject_hash"] and len(document["scope"]["calls"]) == 1
    # An honest certificate says what it cannot show (Bolna deletion API is a pilot gate).
    assert document["engine_deletion"] == "unconfirmed_pending_vendor_api"


async def test_erasure_is_idempotent() -> None:
    """A re-run must not overwrite the original certificate with a weaker one."""
    phone = "+919876500015"
    tenant_id, _ = await _tenant_with_old_call(5, phone)
    request_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO deletion_requests (id, tenant_id, phone_e164, requested_at, "
                "created_at) VALUES (:i, :t, :p, now(), now())"
            ),
            {"i": request_id, "t": tenant_id, "p": phone},
        )
    payload = {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    first = await execute_deletion_request({}, payload)
    second = await execute_deletion_request({}, payload)
    assert "erased" in first
    assert second == "already_completed"


async def test_consent_ledger_survives_erasure() -> None:
    """The consent record is the PROOF that consent existed. Deleting it to satisfy an
    erasure request would destroy the only evidence that the calls were lawful."""
    phone = "+919876500016"
    tenant_id, call_id = await _tenant_with_old_call(5, phone)
    request_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO consent_ledger (id, tenant_id, call_id, phone_e164, purpose, "
                "status, captured_at, created_at) VALUES (:i, :t, :c, :p, 'recording', "
                "'granted', now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "c": call_id, "p": phone},
        )
        await session.execute(
            text(
                "INSERT INTO deletion_requests (id, tenant_id, phone_e164, requested_at, "
                "created_at) VALUES (:i, :t, :p, now(), now())"
            ),
            {"i": request_id, "t": tenant_id, "p": phone},
        )

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})
    async with tenant_session(tenant_id) as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM consent_ledger WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
    assert count == 1
