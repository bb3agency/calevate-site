"""A teach-box voice note is transcribed at OUR cost (founder, 11 Oct 2026): one absorbed
`ai_stt_min` row at the Saaras card, never against the client's AI allowance, never on its
wallet or its spend (hard rule 7: our cost is recorded per use).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from apps.api.billing.ai_quota import read_ai_quota
from apps.api.billing.rates import stt_rate_inr_per_minute
from apps.api.billing.service import _NOT_AI_UNITS
from apps.api.db.session import tenant_session
from apps.workers import kb_teach
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant


async def test_a_voice_note_writes_our_cost_and_spends_nothing_of_the_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def heard(_data: bytes, _content_type: str) -> str:
        return "we open at nine"

    monkeypatch.setattr(kb_teach, "transcribe_voice", heard)
    tenant_id, _agent_id = await _seed_tenant(f"fakeagent_{uuid.uuid4().hex[:10]}")
    async with tenant_session(tenant_id) as session:
        before = await read_ai_quota(session, tenant_id=tenant_id)

    words = await kb_teach.read_upload(
        tenant_id, data=b"audio", input_kind="voice", content_type="audio/webm", filename="v"
    )

    assert words == "we open at nine"
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT unit_type, qty, unit_cost_paid, meta->>'feature', "
                    "meta->>'audio_seconds_basis' FROM usage_events WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).all()
        after = await read_ai_quota(session, tenant_id=tenant_id)
        client_cost = (
            await session.execute(
                text(f"SELECT count(*) FROM usage_events WHERE tenant_id = :t AND {_NOT_AI_UNITS}"),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert rows == [
        (
            "ai_stt_min",
            Decimal("0.5000"),
            stt_rate_inr_per_minute(),
            kb_teach.ASSIST_FEATURE_KB_VOICE,
            "recorder_ceiling",
        )
    ]
    assert after.used_inr == before.used_inr and after.requests_used == before.requests_used
    assert client_cost == 0


async def test_a_voice_note_that_could_not_be_heard_costs_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    async def failed(_data: bytes, _content_type: str) -> str:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(kb_teach, "transcribe_voice", failed)
    tenant_id, _agent_id = await _seed_tenant(f"fakeagent_{uuid.uuid4().hex[:10]}")
    with pytest.raises(kb_teach.UnreadableError):
        await kb_teach.read_upload(
            tenant_id, data=b"audio", input_kind="voice", content_type="audio/webm", filename="v"
        )
    async with tenant_session(tenant_id) as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM usage_events WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
    assert count == 0
