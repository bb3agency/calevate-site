"""`ai_quota.record_absorbed_stt_usage`: the speech-to-text we run for the console and
absorb. The key must be ours, a negative duration is refused, and a retried write meters
nothing a second time — the same idempotency contract as `record_ai_assist_usage`.

CONCURRENCY: every case mints its own tenant.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.ai_quota import AssistMetered, new_assist_ref, record_absorbed_stt_usage
from apps.api.billing.models import AI_STT_UNIT_TYPE
from apps.api.billing.rates import stt_rate_inr_per_minute
from apps.api.db.session import tenant_session
from sqlalchemy import text

pytestmark = [pytest.mark.rls]


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="Voice Note Clinic",
        slug=f"stt-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="books@example.com",
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


async def _meter(tenant_id: UUID, *, ref: str, audio_seconds: int = 90) -> AssistMetered:
    async with tenant_session(tenant_id) as session:
        return await record_absorbed_stt_usage(
            session,
            tenant_id=tenant_id,
            ref=ref,
            audio_seconds=audio_seconds,
            model="saaras:v3",
            feature="kb_voice",
            basis="recorder_ceiling",
        )


async def _rows(tenant_id: UUID) -> list[tuple[Decimal, Decimal]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT qty, unit_cost_paid FROM usage_events "
                    "WHERE tenant_id = :t AND unit_type = :u"
                ),
                {"t": tenant_id, "u": AI_STT_UNIT_TYPE},
            )
        ).all()
    return [(Decimal(r[0]), Decimal(r[1])) for r in rows]


async def test_a_key_not_minted_by_new_assist_ref_is_refused() -> None:
    tenant_id = await _tenant()
    for ref in ("1", f"call:{uuid.uuid4()}", "assist:not-a-uuid"):
        with pytest.raises(ValueError, match="new_assist_ref"):
            await _meter(tenant_id, ref=ref)
    assert await _rows(tenant_id) == []


async def test_a_negative_duration_is_refused() -> None:
    tenant_id = await _tenant()
    with pytest.raises(ValueError, match="negative"):
        await _meter(tenant_id, ref=new_assist_ref(), audio_seconds=-1)
    assert await _rows(tenant_id) == []


async def test_a_retried_write_meters_once_at_the_saaras_card() -> None:
    tenant_id = await _tenant()
    ref = new_assist_ref()
    first = await _meter(tenant_id, ref=ref, audio_seconds=90)
    retried = await _meter(tenant_id, ref=ref, audio_seconds=90)

    price = stt_rate_inr_per_minute()
    assert first.recorded is True
    assert first.cost_inr == Decimal("1.5000") * price
    assert retried.recorded is False
    assert retried.cost_inr == Decimal("0")
    rows = await _rows(tenant_id)
    assert len(rows) == 1, "a retry of one server-side attempt is not a second minute"
    assert rows[0][0] == Decimal("1.5000")
    assert rows[0][1] == price.quantize(Decimal("0.0001"))
