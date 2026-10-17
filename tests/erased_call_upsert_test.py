"""A late webhook or a poller re-read never writes a number back onto an erased call (D-812).

`pipeline._upsert_call_row` fills a party the first event did not carry from a later one
(`COALESCE(calls.to_e164, EXCLUDED.to_e164)`). Both erasures clear the phone columns, so to
that statement an erased call looked like one whose number had not arrived yet, and the
next delivery of the same execution put the erased number back on the row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from apps.api.db.session import tenant_session
from apps.workers import pipeline, retention
from calevate_shared.engine import ExecutionSnapshot
from sqlalchemy import text
from tests.thinnest_erasure_test import _request, _tenant_with_a_platform_call


def _redelivered(engine_call_id: str, to_e164: str) -> ExecutionSnapshot:
    now = datetime.now(UTC)
    return ExecutionSnapshot(
        engine_call_id=engine_call_id,
        direction="outbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        started_at=now - timedelta(seconds=61),
        ended_at=now,
        duration_s=61,
        from_e164="+911140000000",
        to_e164=to_e164,
    )


async def _numbers(tenant_id: uuid.UUID, call_id: uuid.UUID) -> tuple[str | None, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT from_e164, to_e164 FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).one()
    return row[0], row[1]


async def _upsert_again(tenant_id: uuid.UUID, call_id: uuid.UUID, ecid: str, phone: str) -> None:
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(text("SELECT agent_id FROM calls WHERE id = :c"), {"c": call_id})
        ).scalar_one()
    assert await pipeline._upsert_call(tenant_id, agent_id, _redelivered(ecid, phone), None) == (
        call_id
    )


async def test_a_redelivery_does_not_restore_an_erased_subjects_number() -> None:
    tenant_id, call_id, phone, ecid = await _tenant_with_a_platform_call()
    request_id = await _request(tenant_id, phone)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    assert await _numbers(tenant_id, call_id) == (None, None)

    await _upsert_again(tenant_id, call_id, ecid, phone)

    assert await _numbers(tenant_id, call_id) == (None, None)


async def test_a_redelivery_does_not_restore_a_number_under_an_engagement_erasure() -> None:
    tenant_id, call_id, phone, ecid = await _tenant_with_a_platform_call()
    # What `retention._erase_tenant_calls` leaves: the request on file and the numbers
    # cleared, with no per-subject marker on the call.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO tenant_erasure_requests (id, tenant_id, reason, requested_at, "
                "completed_at, created_at) VALUES (:id, :t, 'engagement ended', now(), now(), "
                "now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id},
        )
        await session.execute(
            text("UPDATE calls SET from_e164 = NULL, to_e164 = NULL WHERE id = :c"),
            {"c": call_id},
        )

    await _upsert_again(tenant_id, call_id, ecid, phone)

    assert await _numbers(tenant_id, call_id) == (None, None)


async def test_a_call_that_was_never_erased_still_gets_its_number() -> None:
    tenant_id, call_id, phone, ecid = await _tenant_with_a_platform_call()
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE calls SET to_e164 = NULL WHERE id = :c"), {"c": call_id})

    await _upsert_again(tenant_id, call_id, ecid, phone)

    assert await _numbers(tenant_id, call_id) == ("+911140000000", phone)
